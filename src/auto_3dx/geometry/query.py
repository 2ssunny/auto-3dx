"""Queries that pick faces and edges by what they ARE, not by where they sit in a list.

    top = (
        part.topology.faces(body="PartBody").query()
        .planar()
        .normal_parallel((0, 0, 1))       # a horizontal face, whichever way it points
        .extreme((0, 0, 1))               # the highest one
        .one()
    )
    hole_rim = (
        part.topology.edges(body="PartBody").query()
        .circular()
        .radius_near(5.0, tolerance_mm=0.01)
        .nearest((-15.0, 0.0, 20.0))
        .one()
    )

A query is immutable: every filter or ranking returns a new query over a snapshot's
elements, measured through `Edge.geometry`/`Face.geometry` (`geometry.facts`). It never
contacts CATIA except to measure, and it inherits the snapshot's staleness: after a model
change, measuring raises `StaleSnapshotError` and so does the query.

Three rules make the result deterministic for an agent:

* **Nothing is compared exactly.** Every numeric filter takes an explicit tolerance, with a
  small default where one is sensible.
* **Rankings keep ties.** `largest()`, `nearest()`, `extreme()` and their siblings keep
  every element within the tolerance of the best value, so two equal faces stay two.
* **`one()` never chooses.** It raises `TopologyQueryNoMatchError` for no match and
  `TopologyQueryAmbiguousError` for several, listing what was measured. `first()` exists for
  callers who genuinely accept snapshot order, which is not stable across rebuilds.

Adjacency is measured, not inferred. `EdgeQuery.adjacent_to(face)` keeps the edges that
bound a face and `FaceQuery.adjacent_to(edge)` the faces an edge bounds: an edge bounds a
face when its start, middle and end points all lie ON that face, measured by CATIA as a
distance to the bounded face (`Face.distance_to`, probe 47l) -- not to its plane, so an
edge of a neighbouring coplanar face does not count. Profile edges of consumed sketches,
which a topology search also returns, bound no face and are skipped (`Edge.from_sketch`).
No BRep name is parsed and nothing is picked by position.

Normals are compared as AXES: CATIA reports a planar face's plane normal, whose sign is not
the outward direction (live, a block's top and bottom faces both reported +Z). To tell top
from bottom, rank by position with `extreme(direction)`, which uses the face's centre.
"""

import math
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from auto_3dx.errors import (
    ParameterTypeError,
    UnsupportedOperationError,
    TopologyQueryAmbiguousError,
    TopologyQueryNoMatchError,
    ValidationError,
)
from auto_3dx.geometry.edges import Edge
from auto_3dx.geometry.faces import Face
from auto_3dx.geometry.facts import (
    CURVE_ARC,
    CURVE_CIRCLE,
    CURVE_LINE,
    SURFACE_CYLINDRICAL,
    SURFACE_PLANAR,
    Point,
)

DEFAULT_ANGLE_TOLERANCE_DEG: float = 1.0
"""How far from parallel a normal or a line may be and still count, in degrees."""

DEFAULT_LENGTH_TOLERANCE_MM: float = 1e-3
"""How close two lengths, radii or distances must be to count as equal, in millimetres."""

DEFAULT_AREA_TOLERANCE_MM2: float = 1e-3
"""How close two areas must be to count as equal, in square millimetres."""

DEFAULT_ADJACENCY_TOLERANCE_MM: float = 1e-3
"""How far from a face an edge's sample points may measure and still bound it, in mm.

Live (probe 47l) a point on a face measured exactly 0.0; a point 5 mm off measured 5.0.
"""

_Q = TypeVar("_Q", bound="_Query")


def _vector(value: Any, what: str) -> Point:
    """Validates a 3D vector or point given by a caller."""
    try:
        x, y, z = (float(component) for component in value)
    except (TypeError, ValueError) as error:
        raise ParameterTypeError(f"{what} must be three numbers, not {value!r}.") from error
    if not all(math.isfinite(component) for component in (x, y, z)):
        raise ParameterTypeError(f"{what} must be finite, not {value!r}.")
    return (x, y, z)


_WORLD_AXES: "dict[str, Point]" = {
    "X": (1.0, 0.0, 0.0),
    "Y": (0.0, 1.0, 0.0),
    "Z": (0.0, 0.0, 1.0),
}


def _direction(value: Any, what: str) -> Point:
    """Validates a direction and returns it as a unit vector.

    Accepts three numbers or a world axis name -- `"X"`, `"Y"`, `"Z"`, optionally signed
    (`"-Z"`) -- the same words `part.geometry`'s finders take.
    """
    if isinstance(value, str):
        text = value.strip().upper()
        key = text.lstrip("+-")
        if key not in _WORLD_AXES or len(text) - len(key) > 1:
            raise ParameterTypeError(
                f"{what} must be 'X', 'Y', 'Z' (optionally signed) or three numbers, "
                f"not {value!r}."
            )
        sign = -1.0 if text.startswith("-") else 1.0
        x, y, z = _WORLD_AXES[key]
        return (sign * x, sign * y, sign * z)
    vector = _vector(value, what)
    length = math.hypot(*vector)
    if length == 0.0:
        raise ParameterTypeError(f"{what} must not be the zero vector.")
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def _tolerance(value: Any, what: str) -> float:
    """Validates a tolerance: a finite, non-negative number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ParameterTypeError(f"{what} must be a number, not {type(value).__name__}.")
    if not math.isfinite(value) or value < 0:
        raise ParameterTypeError(f"{what} must be finite and not negative, not {value!r}.")
    return float(value)


def _require_same_part(first: Any, second: Any) -> None:
    """Refuses to relate a face and an edge taken from two different Parts.

    Both carry their Part's `ModelGeneration`; one Part shares one object, so identity of
    that object is identity of the Part. A handle built without one cannot say.
    """
    mine = getattr(first, "_model_generation", None)
    theirs = getattr(second, "_model_generation", None)
    if mine is not None and theirs is not None and mine is not theirs:
        raise ValidationError(
            "The face and the edge belong to different Parts; adjacency only relates "
            "elements of one Part. Take both from the same part.topology."
        )


def _bounds(face: Face, edge: Edge, tolerance: float) -> bool:
    """Whether `edge` bounds `face`: its start, middle and end all measure ON the face."""
    if edge.from_sketch:
        return False
    facts = edge.geometry
    return all(
        face.distance_to(point) <= tolerance
        for point in (facts.mid_mm, facts.start_mm, facts.end_mm)
    )


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _angle_between_axes(a: Point, b: Point) -> float:
    """The angle between two lines through the origin, ignoring direction, in degrees."""
    cosine = min(1.0, abs(_dot(a, b)))
    return math.degrees(math.acos(cosine))


class _Query:
    """What face and edge queries share: scoping, rankings by position, and cardinality."""

    _noun = "element"

    def __init__(self, elements: Sequence[Any], applied: "tuple[str, ...]" = ()) -> None:
        """Initializes the query.

        Args:
            elements: The candidate faces or edges, in snapshot order.
            applied: A description of every filter applied so far, for messages.
        """
        self._elements = tuple(elements)
        self._applied = applied

    def _derive(self: _Q, elements: Sequence[Any], step: str) -> _Q:
        return type(self)(elements, (*self._applied, step))

    def _where(self: _Q, keep: Callable[[Any], bool], step: str) -> _Q:
        return self._derive([element for element in self._elements if keep(element)], step)

    def _best(
        self: _Q, metric: Callable[[Any], float], highest: bool, tolerance: float, step: str
    ) -> _Q:
        """Keeps every element within `tolerance` of the best metric value."""
        if not self._elements:
            return self._derive([], step)
        values = [(metric(element), element) for element in self._elements]
        best = max(value for value, _ in values) if highest else min(v for v, _ in values)
        return self._derive(
            [element for value, element in values if abs(value - best) <= tolerance], step
        )

    def _position(self, element: Any) -> Point:
        """Where an element is, for `nearest` and `extreme`."""
        raise NotImplementedError

    def _describe(self, element: Any) -> str:
        """A short account of one element's measured facts, for messages."""
        raise NotImplementedError

    def owned_by(self: _Q, feature_name: str) -> _Q:
        """Keeps elements CATIA currently attributes to one feature.

        This is the feature whose result carries the element now (`Reference.Parent`),
        usually the latest solid feature -- not the feature that first created it
        (`Edge.current_owner_feature_name`).

        Args:
            feature_name: The feature's name.

        Returns:
            A narrowed query.
        """
        return self._where(
            lambda element: element.owner_feature_name == feature_name,
            f"owned_by({feature_name!r})",
        )

    def nearest(
        self: _Q, point: Any, tolerance_mm: float = DEFAULT_LENGTH_TOLERANCE_MM
    ) -> _Q:
        """Keeps the element(s) closest to a point.

        A face is placed at its centre of gravity, a circle or arc at its centre, and any
        other edge at its midpoint.

        Args:
            point: The point, as three numbers in millimetres.
            tolerance_mm: How much further than the closest an element may be and still
                count as tied.

        Returns:
            A query holding the closest element and anything tied with it.
        """
        target = _vector(point, "point")
        tolerance = _tolerance(tolerance_mm, "tolerance_mm")
        return self._best(
            lambda element: math.dist(self._position(element), target),
            False,
            tolerance,
            f"nearest({target})",
        )

    def extreme(
        self: _Q, direction: Any, tolerance_mm: float = DEFAULT_LENGTH_TOLERANCE_MM
    ) -> _Q:
        """Keeps the element(s) furthest along a direction.

        This is how "the top face" is asked for: the planar horizontal face whose centre is
        highest along +Z. It does not rely on the sign of any normal.

        Args:
            direction: The direction, as three numbers.
            tolerance_mm: How far behind the furthest an element may be and still count as
                tied.

        Returns:
            A query holding the furthest element and anything tied with it.
        """
        axis = _direction(direction, "direction")
        tolerance = _tolerance(tolerance_mm, "tolerance_mm")
        return self._best(
            lambda element: _dot(self._position(element), axis),
            True,
            tolerance,
            f"extreme({axis})",
        )

    def all(self) -> "list[Any]":
        """list: Every element that matched, in snapshot order."""
        return list(self._elements)

    def count(self) -> int:
        """int: How many elements matched."""
        return len(self._elements)

    def first(self) -> Any:
        """Returns the first match in snapshot order.

        Snapshot order is CATIA's search order, which changes when the model changes. Use
        `one()` whenever the query is meant to identify a single element.

        Raises:
            TopologyQueryNoMatchError: If nothing matched.
        """
        if not self._elements:
            raise self._no_match()
        return self._elements[0]

    def one(self) -> Any:
        """Returns the single element the query identifies.

        Raises:
            TopologyQueryNoMatchError: If nothing matched.
            TopologyQueryAmbiguousError: If more than one element matched. The message
                lists each candidate's measured facts so the query can be narrowed.
        """
        if not self._elements:
            raise self._no_match()
        if len(self._elements) > 1:
            listed = "; ".join(self._describe(element) for element in self._elements[:6])
            more = "" if len(self._elements) <= 6 else f"; and {len(self._elements) - 6} more"
            raise TopologyQueryAmbiguousError(
                f"{len(self._elements)} {self._noun}s match {self._steps()}: "
                f"{listed}{more}. Narrow the query; one() never picks among candidates."
            )
        return self._elements[0]

    def _steps(self) -> str:
        return " -> ".join(self._applied) if self._applied else "an empty query"

    def _no_match(self) -> TopologyQueryNoMatchError:
        return TopologyQueryNoMatchError(
            f"No {self._noun} matches {self._steps()}. Check the body scope, loosen a "
            "tolerance, or take a fresh snapshot if the model changed."
        )

    def __len__(self) -> int:
        """int: How many elements matched."""
        return len(self._elements)

    def __repr__(self) -> str:
        """str: The filters applied and the match count; does not contact CATIA."""
        return f"{type(self).__name__}({self._steps()}, count={len(self._elements)})"


class FaceQuery(_Query):
    """A query over faces, from `FaceSnapshot.query()`."""

    _noun = "face"

    def _position(self, element: Any) -> Point:
        return element.geometry.center_mm

    def _describe(self, element: Any) -> str:
        return str(element.describe())

    def of_type(self, surface_type: str) -> "FaceQuery":
        """Keeps faces of one surface type (`geometry.facts.SURFACE_*`)."""
        return self._where(
            lambda face: face.geometry.surface_type == surface_type,
            f"of_type({surface_type!r})",
        )

    def planar(self) -> "FaceQuery":
        """Keeps planar faces."""
        return self.of_type(SURFACE_PLANAR)

    def adjacent_to(
        self, edge: Edge, tolerance_mm: float = DEFAULT_ADJACENCY_TOLERANCE_MM
    ) -> "FaceQuery":
        """Keeps the faces that `edge` bounds -- two for an ordinary edge of a solid.

        A face is kept when the edge's start, middle and end points all measure within
        `tolerance_mm` of the face itself (`Face.distance_to`), which is a distance to the
        bounded face, not to its plane (probe 47l).

        Args:
            edge: An `Edge` of the solid, from a snapshot of the current model.
            tolerance_mm: How far from a face a sample point may measure.

        Returns:
            A narrowed query.

        Raises:
            ParameterTypeError: If `edge` is not an `Edge`.
            UnsupportedOperationError: If `edge` is a profile edge of a consumed sketch,
                which bounds no face.
            ValidationError: If `edge` belongs to another Part.
            StaleSnapshotError: If `edge` or a face comes from an outdated snapshot.
        """
        if not isinstance(edge, Edge):
            raise ParameterTypeError(
                f"adjacent_to() takes an Edge from part.topology.edges(), not "
                f"{type(edge).__name__}."
            )
        if edge.from_sketch:
            raise UnsupportedOperationError(
                "This edge is a profile edge of a consumed sketch, not an edge of the solid; "
                "it bounds no face. Pick an edge of the solid (Edge.from_sketch is False)."
            )
        tolerance = _tolerance(tolerance_mm, "tolerance_mm")
        for face in self._elements:
            _require_same_part(face, edge)
        return self._where(
            lambda face: _bounds(face, edge, tolerance),
            f"adjacent_to(edge: {edge.describe()})",
        )

    def cylindrical(self) -> "FaceQuery":
        """Keeps cylindrical faces."""
        return self.of_type(SURFACE_CYLINDRICAL)

    def normal_parallel(
        self, axis: Any, tolerance_deg: float = DEFAULT_ANGLE_TOLERANCE_DEG
    ) -> "FaceQuery":
        """Keeps planar faces whose plane normal lies along an axis, either way round.

        The sign of CATIA's plane normal is not the outward direction, so a face pointing
        +Z and one pointing -Z both match `(0, 0, 1)`. Rank with `extreme` to choose.

        Args:
            axis: The axis, as three numbers.
            tolerance_deg: The largest angle between normal and axis that still counts.

        Returns:
            A narrowed query; non-planar faces are dropped.
        """
        direction = _direction(axis, "axis")
        tolerance = _tolerance(tolerance_deg, "tolerance_deg")
        return self._where(
            lambda face: face.geometry.normal is not None
            and _angle_between_axes(face.geometry.normal, direction) <= tolerance,
            f"normal_parallel({direction}, {tolerance} deg)",
        )

    def radius_near(
        self, radius_mm: float, tolerance_mm: float = DEFAULT_LENGTH_TOLERANCE_MM
    ) -> "FaceQuery":
        """Keeps cylindrical faces of about one radius.

        Args:
            radius_mm: The radius.
            tolerance_mm: The largest difference that still counts.

        Returns:
            A narrowed query; faces with no radius are dropped.
        """
        target = _tolerance(radius_mm, "radius_mm")
        tolerance = _tolerance(tolerance_mm, "tolerance_mm")
        return self._where(
            lambda face: face.geometry.radius_mm is not None
            and abs(face.geometry.radius_mm - target) <= tolerance,
            f"radius_near({target} +- {tolerance} mm)",
        )

    def area_between(
        self, minimum_mm2: "float | None" = None, maximum_mm2: "float | None" = None
    ) -> "FaceQuery":
        """Keeps faces whose area lies within bounds (inclusive). Either bound may be omitted."""
        low = None if minimum_mm2 is None else _tolerance(minimum_mm2, "minimum_mm2")
        high = None if maximum_mm2 is None else _tolerance(maximum_mm2, "maximum_mm2")
        return self._where(
            lambda face: (low is None or face.geometry.area_mm2 >= low)
            and (high is None or face.geometry.area_mm2 <= high),
            f"area_between({low}, {high})",
        )

    def largest(self, tolerance_mm2: float = DEFAULT_AREA_TOLERANCE_MM2) -> "FaceQuery":
        """Keeps the face(s) of greatest area, and any tied within `tolerance_mm2`."""
        tolerance = _tolerance(tolerance_mm2, "tolerance_mm2")
        return self._best(lambda face: face.geometry.area_mm2, True, tolerance, "largest()")

    def smallest(self, tolerance_mm2: float = DEFAULT_AREA_TOLERANCE_MM2) -> "FaceQuery":
        """Keeps the face(s) of least area, and any tied within `tolerance_mm2`."""
        tolerance = _tolerance(tolerance_mm2, "tolerance_mm2")
        return self._best(lambda face: face.geometry.area_mm2, False, tolerance, "smallest()")


class EdgeQuery(_Query):
    """A query over edges, from `EdgeSnapshot.query()`."""

    _noun = "edge"

    def _position(self, element: Any) -> Point:
        geometry = element.geometry
        if geometry.center_mm is not None:
            return geometry.center_mm
        return geometry.mid_mm

    def _describe(self, element: Any) -> str:
        return str(element.describe())

    def of_type(self, curve_type: str) -> "EdgeQuery":
        """Keeps edges of one curve type (`geometry.facts.CURVE_*`)."""
        return self._where(
            lambda edge: edge.geometry.curve_type == curve_type, f"of_type({curve_type!r})"
        )

    def lines(self) -> "EdgeQuery":
        """Keeps straight edges."""
        return self.of_type(CURVE_LINE)

    def adjacent_to(
        self, face: Face, tolerance_mm: float = DEFAULT_ADJACENCY_TOLERANCE_MM
    ) -> "EdgeQuery":
        """Keeps the edges that bound `face`: its outer boundary and any holes in it.

        An edge is kept when its start, middle and end points all measure within
        `tolerance_mm` of the face itself (`Face.distance_to`) -- the bounded face, not its
        plane, so an edge of a neighbouring coplanar face is not kept, unlike
        `on_plane_of`. Profile edges of consumed sketches are never kept
        (`Edge.from_sketch`).

        Args:
            face: A `Face`, from a snapshot of the current model. Any surface type.
            tolerance_mm: How far from the face a sample point may measure.

        Returns:
            A narrowed query.

        Raises:
            ParameterTypeError: If `face` is not a `Face`.
            ValidationError: If `face` belongs to another Part.
            StaleSnapshotError: If `face` or an edge comes from an outdated snapshot.
        """
        if not isinstance(face, Face):
            raise ParameterTypeError(
                f"adjacent_to() takes a Face from part.topology.faces(), not "
                f"{type(face).__name__}."
            )
        tolerance = _tolerance(tolerance_mm, "tolerance_mm")
        for edge in self._elements:
            _require_same_part(face, edge)
        return self._where(
            lambda edge: _bounds(face, edge, tolerance),
            f"adjacent_to(face: {face.describe()})",
        )

    def solid(self) -> "EdgeQuery":
        """Drops the profile edges of consumed sketches, keeping the solid's own edges.

        Edges whose owner could not be told (`Edge.from_sketch is None`) are kept.
        """
        return self._where(lambda edge: edge.from_sketch is not True, "solid()")

    def circular(self) -> "EdgeQuery":
        """Keeps full circles and circular arcs."""
        return self._where(
            lambda edge: edge.geometry.curve_type in (CURVE_CIRCLE, CURVE_ARC), "circular()"
        )

    def parallel(
        self, axis: Any, tolerance_deg: float = DEFAULT_ANGLE_TOLERANCE_DEG
    ) -> "EdgeQuery":
        """Keeps straight edges running along an axis, either way round.

        Args:
            axis: The axis, as three numbers.
            tolerance_deg: The largest angle that still counts.

        Returns:
            A narrowed query; edges that are not straight are dropped.
        """
        direction = _direction(axis, "axis")
        tolerance = _tolerance(tolerance_deg, "tolerance_deg")
        return self._where(
            lambda edge: edge.geometry.direction is not None
            and _angle_between_axes(edge.geometry.direction, direction) <= tolerance,
            f"parallel({direction}, {tolerance} deg)",
        )

    def radius_near(
        self, radius_mm: float, tolerance_mm: float = DEFAULT_LENGTH_TOLERANCE_MM
    ) -> "EdgeQuery":
        """Keeps circles and arcs of about one radius.

        Args:
            radius_mm: The radius.
            tolerance_mm: The largest difference that still counts.

        Returns:
            A narrowed query; edges with no radius are dropped.
        """
        target = _tolerance(radius_mm, "radius_mm")
        tolerance = _tolerance(tolerance_mm, "tolerance_mm")
        return self._where(
            lambda edge: edge.geometry.radius_mm is not None
            and abs(edge.geometry.radius_mm - target) <= tolerance,
            f"radius_near({target} +- {tolerance} mm)",
        )

    def length_between(
        self, minimum_mm: "float | None" = None, maximum_mm: "float | None" = None
    ) -> "EdgeQuery":
        """Keeps edges whose length lies within bounds (inclusive). Either may be omitted."""
        low = None if minimum_mm is None else _tolerance(minimum_mm, "minimum_mm")
        high = None if maximum_mm is None else _tolerance(maximum_mm, "maximum_mm")
        return self._where(
            lambda edge: (low is None or edge.geometry.length_mm >= low)
            and (high is None or edge.geometry.length_mm <= high),
            f"length_between({low}, {high})",
        )

    def on_plane_of(
        self, face: Any, tolerance_mm: float = DEFAULT_LENGTH_TOLERANCE_MM
    ) -> "EdgeQuery":
        """Keeps edges lying in the plane of a planar face.

        An edge is kept when its measured start, middle and end points are all within
        `tolerance_mm` of the face's plane. This is a geometric fact about the plane, NOT
        face adjacency: it does not claim the edge bounds that face, and an edge of another
        coplanar face qualifies too, and so do the profile edges of a sketch drawn in that
        plane. For "the edges of this face" use `adjacent_to(face)`, which measures
        against the bounded face itself.

        Args:
            face: A planar `Face`, from a snapshot of the current model.
            tolerance_mm: How far off the plane a point may lie.

        Returns:
            A narrowed query.

        Raises:
            UnsupportedOperationError: If `face` does not measure as planar.
            StaleSnapshotError: If `face` comes from an outdated snapshot.
        """
        tolerance = _tolerance(tolerance_mm, "tolerance_mm")
        facts = face.geometry
        if facts.surface_type != SURFACE_PLANAR or facts.normal is None:
            raise UnsupportedOperationError(
                f"on_plane_of() needs a planar face; this face measures as "
                f"{facts.surface_type!r}."
            )
        center, normal = facts.center_mm, facts.normal

        def off_plane(point: Point) -> float:
            return abs(_dot((point[0] - center[0], point[1] - center[1],
                             point[2] - center[2]), normal))

        return self._where(
            lambda edge: all(
                off_plane(point) <= tolerance
                for point in (edge.geometry.start_mm, edge.geometry.mid_mm, edge.geometry.end_mm)
            ),
            f"on_plane_of(face at {center}, +- {tolerance} mm)",
        )

    def longest(self, tolerance_mm: float = DEFAULT_LENGTH_TOLERANCE_MM) -> "EdgeQuery":
        """Keeps the longest edge(s), and any tied within `tolerance_mm`."""
        tolerance = _tolerance(tolerance_mm, "tolerance_mm")
        return self._best(lambda edge: edge.geometry.length_mm, True, tolerance, "longest()")

    def shortest(self, tolerance_mm: float = DEFAULT_LENGTH_TOLERANCE_MM) -> "EdgeQuery":
        """Keeps the shortest edge(s), and any tied within `tolerance_mm`."""
        tolerance = _tolerance(tolerance_mm, "tolerance_mm")
        return self._best(lambda edge: edge.geometry.length_mm, False, tolerance, "shortest()")
