"""`part.geometry`: engineering-intent finders composed from the semantic query system.

Each finder takes ONE fresh snapshot through `part.topology` (scoped exactly like it: the
`work_in` body by default, a named body, or `None` for the whole Part), builds a
`snapshot.query()` chain, and returns `one()`. So a finder:

* never picks an element by index, by descriptor, or by the first match;
* never reads a plane normal's sign as "outward" -- "top" is the planar face whose normal is
  parallel to Z, ranked by its centre's height (`extreme`), the rule Phase 4 established;
* raises `TopologyQueryNoMatchError` for nothing and `TopologyQueryAmbiguousError` for
  several, with the measured candidates in the message, exactly as `one()` does.

A finder's result is a normal `Face`/`Edge` of that snapshot: it goes stale on the next
model change like any other handle, so find again after a mutation.

    top = part.geometry.top_face()
    rim = part.geometry.find_edge(kind="circle", radius=3, on_plane_of=top)
"""

from typing import TYPE_CHECKING, Any

from auto_3dx.errors import ParameterTypeError
from auto_3dx.geometry.edges import Edge
from auto_3dx.geometry.faces import Face
from auto_3dx.geometry.facts import CURVE_ARC, CURVE_CIRCLE, CURVE_LINE
from auto_3dx.geometry.planes import OffsetPlane
from auto_3dx.geometry.query import (
    DEFAULT_ANGLE_TOLERANCE_DEG,
    DEFAULT_LENGTH_TOLERANCE_MM,
    EdgeQuery,
    FaceQuery,
)
from auto_3dx.geometry.topology import WORK_BODY
from auto_3dx.highlevel.directions import INTO_MATERIAL, OUT_OF_MATERIAL

if TYPE_CHECKING:
    from auto_3dx.core.part import Part

_AXES: "dict[str, tuple[float, float, float]]" = {
    "X": (1.0, 0.0, 0.0),
    "Y": (0.0, 1.0, 0.0),
    "Z": (0.0, 0.0, 1.0),
}
_SIDES: "dict[str, float]" = {"max": 1.0, "min": -1.0}

EDGE_KIND_LINE: str = "line"
EDGE_KIND_CIRCLE: str = "circle"
EDGE_KIND_ARC: str = "arc"
EDGE_KIND_CIRCULAR: str = "circular"
"""A full circle or an arc."""

_EDGE_KINDS: "frozenset[str]" = frozenset(
    {EDGE_KIND_LINE, EDGE_KIND_CIRCLE, EDGE_KIND_ARC, EDGE_KIND_CIRCULAR}
)

_PLANE_SIDES: "dict[str, bool]" = {INTO_MATERIAL: False, OUT_OF_MATERIAL: True}
"""Side -> `AddNewPlaneOffset` orientation for a face support (probes 47e, 47o)."""


def axis_vector(axis: Any) -> "tuple[float, float, float]":
    """Turns `"X"`/`"Y"`/`"Z"` (optionally `"+X"`/`"-Z"`) or three numbers into a vector.

    Raises:
        ParameterTypeError: If `axis` is none of those.
    """
    if isinstance(axis, str):
        text = axis.strip().upper()
        sign = -1.0 if text.startswith("-") else 1.0
        key = text.lstrip("+-")
        if key in _AXES and len(text) - len(key) <= 1:
            x, y, z = _AXES[key]
            return (sign * x, sign * y, sign * z)
    elif isinstance(axis, (tuple, list)) and len(axis) == 3:
        if all(not isinstance(v, bool) and isinstance(v, (int, float)) for v in axis):
            return (float(axis[0]), float(axis[1]), float(axis[2]))
    raise ParameterTypeError(
        f"An axis must be 'X', 'Y', 'Z' (optionally signed) or three numbers, not {axis!r}."
    )


def _extreme_vector(extreme: Any) -> "tuple[float, float, float]":
    """Turns `("Z", "max")` into `(0, 0, 1)`; also accepts a signed axis or a vector."""
    if isinstance(extreme, tuple) and len(extreme) == 2 and extreme[1] in _SIDES:
        x, y, z = axis_vector(extreme[0])
        sign = _SIDES[extreme[1]]
        return (sign * x, sign * y, sign * z)
    return axis_vector(extreme)


class PartGeometry:
    """Semantic face and edge finders for one Part. Obtain it as `part.geometry`."""

    def __init__(self, part: "Part") -> None:
        """Initializes the finders.

        Args:
            part: The `Part` whose `topology` the finders search.
        """
        self._part = part

    def faces(self, body: Any = WORK_BODY) -> FaceQuery:
        """A query over a fresh face snapshot, for chains no finder below covers."""
        return self._part.topology.faces(body=body).query()

    def edges(self, body: Any = WORK_BODY) -> EdgeQuery:
        """A query over the solid's edges in a fresh snapshot, for chains no finder covers.

        Profile edges of consumed sketches, which the search also returns, are dropped
        (`EdgeQuery.solid()`): they coincide with the solid's own edges and bound no face.
        `part.topology.edges(body).query()` keeps them.
        """
        return self._part.topology.edges(body=body).query().solid()

    def edges_of(self, face: Face) -> EdgeQuery:
        """The edges that bound `face`, measured (`part.topology.edges_of`)."""
        return self._part.topology.edges_of(face)

    def faces_of(self, edge: Edge) -> FaceQuery:
        """The faces `edge` bounds -- normally two -- measured (`part.topology.faces_of`)."""
        return self._part.topology.faces_of(edge)

    def top_face(self, axis: Any = "Z", body: Any = WORK_BODY) -> Face:
        """The planar face perpendicular to `axis` whose centre lies furthest along it.

        `planar() -> normal_parallel(axis) -> extreme(axis) -> one()`.

        Args:
            axis: The "up" axis. Defaults to `"Z"`.
            body: The snapshot scope, as for `part.topology.faces`.

        Raises:
            TopologyQueryNoMatchError: If no face matches.
            TopologyQueryAmbiguousError: If two faces tie for highest.
        """
        up = axis_vector(axis)
        return self.find_planar_face(normal_parallel=up, extreme=up, body=body)

    def bottom_face(self, axis: Any = "Z", body: Any = WORK_BODY) -> Face:
        """The planar face perpendicular to `axis` whose centre lies furthest against it."""
        up = axis_vector(axis)
        return self.find_planar_face(
            normal_parallel=up, extreme=(-up[0], -up[1], -up[2]), body=body
        )

    def find_planar_face(
        self,
        normal_parallel: Any = None,
        extreme: Any = None,
        nearest: Any = None,
        body: Any = WORK_BODY,
        tolerance_deg: float = DEFAULT_ANGLE_TOLERANCE_DEG,
    ) -> Face:
        """Finds exactly one planar face by orientation and position.

        Args:
            normal_parallel: An axis the face's normal is parallel to, either way round
                (`"Z"`, `"X"`, a vector).
            extreme: Keep the face(s) furthest along a direction: `("Z", "max")`,
                `("X", "min")`, `"-Y"` or a vector.
            nearest: Keep the face(s) whose centre is closest to `(x, y, z)`.
            body: The snapshot scope.
            tolerance_deg: The angle tolerance for `normal_parallel`.

        Returns:
            The one matching `Face`.

        Raises:
            ParameterTypeError: If an argument is malformed.
            TopologyQueryNoMatchError: If nothing matches.
            TopologyQueryAmbiguousError: If several faces still match.
        """
        query = self.faces(body).planar()
        if normal_parallel is not None:
            query = query.normal_parallel(axis_vector(normal_parallel), tolerance_deg)
        if extreme is not None:
            query = query.extreme(_extreme_vector(extreme))
        if nearest is not None:
            query = query.nearest(nearest)
        return query.one()

    def find_cylindrical_face(
        self,
        radius: "float | None" = None,
        nearest: Any = None,
        body: Any = WORK_BODY,
        tolerance_mm: float = DEFAULT_LENGTH_TOLERANCE_MM,
    ) -> Face:
        """Finds exactly one cylindrical face, such as a bore or a boss.

        Args:
            radius: Keep faces of about this radius.
            nearest: Keep the face(s) whose centre is closest to `(x, y, z)`.
            body: The snapshot scope.
            tolerance_mm: The radius tolerance.

        Raises:
            TopologyQueryNoMatchError / TopologyQueryAmbiguousError: As for `one()`.
        """
        query = self.faces(body).cylindrical()
        if radius is not None:
            query = query.radius_near(radius, tolerance_mm)
        if nearest is not None:
            query = query.nearest(nearest)
        return query.one()

    def find_edge(
        self,
        kind: "str | None" = None,
        radius: "float | None" = None,
        parallel: Any = None,
        on_plane_of: "Face | None" = None,
        nearest: Any = None,
        extreme: Any = None,
        body: Any = WORK_BODY,
        tolerance_mm: float = DEFAULT_LENGTH_TOLERANCE_MM,
        adjacent_to: "Face | None" = None,
    ) -> Edge:
        """Finds exactly one edge by type, size, orientation and position.

        Args:
            kind: `"line"`, `"circle"`, `"arc"` or `"circular"` (circle or arc).
            radius: Keep circles/arcs of about this radius.
            parallel: Keep straight edges along this axis.
            on_plane_of: Keep edges lying in this planar face's plane (a plane fact, not
                adjacency; see `EdgeQuery.on_plane_of`).
            adjacent_to: Keep edges that bound this face (measured adjacency; see
                `EdgeQuery.adjacent_to`).
            nearest: Keep the edge(s) closest to `(x, y, z)` (a circle's centre, otherwise
                the midpoint).
            extreme: Keep the edge(s) furthest along a direction, as for faces.
            body: The snapshot scope.
            tolerance_mm: The radius and plane tolerance.

        Raises:
            ParameterTypeError: If `kind` is unknown.
            TopologyQueryNoMatchError / TopologyQueryAmbiguousError: As for `one()`.
        """
        if kind is not None and kind not in _EDGE_KINDS:
            raise ParameterTypeError(f"kind must be one of {sorted(_EDGE_KINDS)}, not {kind!r}.")
        query = self.edges(body)
        if kind == EDGE_KIND_LINE:
            query = query.of_type(CURVE_LINE)
        elif kind == EDGE_KIND_CIRCLE:
            query = query.of_type(CURVE_CIRCLE)
        elif kind == EDGE_KIND_ARC:
            query = query.of_type(CURVE_ARC)
        elif kind == EDGE_KIND_CIRCULAR:
            query = query.circular()
        if radius is not None:
            query = query.radius_near(radius, tolerance_mm)
        if parallel is not None:
            query = query.parallel(axis_vector(parallel))
        if on_plane_of is not None:
            query = query.on_plane_of(on_plane_of, tolerance_mm)
        if adjacent_to is not None:
            query = query.adjacent_to(adjacent_to)
        if extreme is not None:
            query = query.extreme(_extreme_vector(extreme))
        if nearest is not None:
            query = query.nearest(nearest)
        return query.one()

    def offset_plane(
        self, name: str, *, face: Face, distance: float, side: str = OUT_OF_MATERIAL
    ) -> OffsetPlane:
        """Creates a reference plane parallel to a planar face, on a chosen side of it.

        `part.planes.create_offset(name, face, distance, orientation)` with the orientation
        that puts the plane on `side`: live, on a block's top, bottom and +X faces,
        orientation False went into the material and True out of it (probes 47e, 47o).
        The side is a material side, not the sign of the face's measured normal. Not
        rebuilt: after `part.update()`, `plane.origin` confirms where it went.

        Args:
            name: The plane's name.
            face: A planar `Face` of the solid, from a current snapshot.
            distance: How far from the face, in millimetres; positive.
            side: `"out_of_material"` (the default: above a top face) or
                `"into_material"`.

        Returns:
            The new `OffsetPlane`; sketch on it with `part.sketches.create(..., support=plane)`.

        Raises:
            ParameterTypeError: If `distance` is not positive or `side` is unknown.
            UnsupportedSupportError: If `face` is not planar.
            StaleSnapshotError: If `face` comes from an outdated snapshot.
            Auto3dxError: Whatever `part.planes.create_offset` raises.
        """
        if side not in _PLANE_SIDES:
            raise ParameterTypeError(
                f"side must be {OUT_OF_MATERIAL!r} or {INTO_MATERIAL!r}, not {side!r}."
            )
        if isinstance(distance, bool) or not isinstance(distance, (int, float)) or not (
            distance > 0
        ):
            raise ParameterTypeError(f"distance must be a positive number, not {distance!r}.")
        if not isinstance(face, Face):
            raise ParameterTypeError(
                f"face must be a Face from part.topology.faces(), not {type(face).__name__}."
            )
        return self._part.planes.create_offset(
            name, face, float(distance), _PLANE_SIDES[side]
        )

    def __repr__(self) -> str:
        """str: Debug representation; does not contact CATIA."""
        return "PartGeometry()"
