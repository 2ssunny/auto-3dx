"""Plain-value results for reading a sketch back: element geometry, constraints, the frame.

Everything here is a frozen dataclass or pure arithmetic; nothing touches COM. The reads
that fill these values live in `geometry.sketch` and rest on probes 46a-46h, 46ab and 46ac
(`docs/phase5-api-design.md` section 3):

    Line2D.GetEndPoints(seed4)     -> (x1, y1, x2, y2)
    Circle2D.GetCenter(seed2)      -> (cx, cy)        (probe 43 failed only for want of a seed)
    Circle2D.Radius                -> r
    Circle2D.GetEndPoints(seed4)   -> start == end for a closed circle, distinct for an arc
    Point2D.GetCoordinates(seed2)  -> (x, y)
    <element>.Construction         -> bool
    Constraint.Mode                -> 0 driving, 1 driven
    Constraint.GetConstraintElement(i).DisplayName -> the constrained element's name

Each of them was verified with the sketch edition CLOSED. The first run of probe 46 read
geometry while an edition was open and left 3DEXPERIENCE unresponsive, so `geometry.sketch`
refuses a read during an open edition rather than finding out which read did it.

Coordinates are sketch-local millimetres. `SketchFrame` maps them to Part coordinates using
the sketch's own `GetAbsoluteAxisData`, which for a sketch on a face is the only way to know
where local (0, 0) is: live, it was a corner of the face, not its centre (probe 46j).
"""

import math
from dataclasses import dataclass

Point2 = tuple[float, float]
Point3 = tuple[float, float, float]

CLOSED_CURVE_TOLERANCE_MM: float = 1e-6
"""How close a circle's two end points must be for it to count as closed.

Live (probe 46ab) a closed circle reported its end points 2e-15 mm apart; an arc's are the
chord apart.
"""

_FRAME_AXIS_TOLERANCE: float = 1e-9


@dataclass(frozen=True)
class LineGeometry:
    """A sketch line, in sketch-local millimetres.

    Attributes:
        start: The start point `(x, y)`.
        end: The end point `(x, y)`.
    """

    start: Point2
    end: Point2

    @property
    def length_mm(self) -> float:
        """float: The distance from `start` to `end`."""
        return math.dist(self.start, self.end)


@dataclass(frozen=True)
class CircleGeometry:
    """A sketch circle or arc, in sketch-local millimetres.

    Attributes:
        center: The centre `(x, y)`.
        radius_mm: The radius.
        start: The start point `(x, y)`; equal to `end` for a closed circle.
        end: The end point `(x, y)`.
    """

    center: Point2
    radius_mm: float
    start: Point2
    end: Point2

    @property
    def is_closed(self) -> bool:
        """bool: `True` for a full circle, `False` for an arc (end points apart)."""
        return math.dist(self.start, self.end) <= CLOSED_CURVE_TOLERANCE_MM


@dataclass(frozen=True)
class PointGeometry:
    """A sketch point, in sketch-local millimetres.

    Attributes:
        position: The point `(x, y)`.
    """

    position: Point2


ElementGeometry = LineGeometry | CircleGeometry | PointGeometry


@dataclass(frozen=True)
class SketchElementInfo:
    """One element of a sketch with its geometry, as `Sketch.geometry()` reports it.

    Attributes:
        name: The name CATIA gave the element, its durable identity (`"Line.1"`).
        kind: The COM type name (`"Line2D"`, `"Circle2D"`, `"Point2D"`).
        construction: Whether it is construction geometry, excluded from profiles.
        geometry: Its `LineGeometry`, `CircleGeometry` or `PointGeometry`.
    """

    name: str
    kind: str
    construction: bool
    geometry: ElementGeometry


@dataclass(frozen=True)
class ConstraintInfo:
    """One constraint of a sketch, read back as plain values.

    Attributes:
        name: The constraint's name (`"Length.1"`, `"Parallelism.2"`).
        type_code: CATIA's `CatConstraintType`. Horizontal and vertical constraints read
            back as parallelism (8), as they always have (`docs/conventions.md` 1.2.4).
        mode: `"driving"` or `"driven"`.
        status: CATIA's `CatConstraintStatus`; 0 is satisfied.
        value: The dimension in millimetres or degrees for a dimensional constraint,
            `None` for a geometric one.
        first_element: The name of the first element it constrains, `None` when CATIA did
            not report one.
    """

    name: str
    type_code: int
    mode: str
    status: int
    value: "float | None"
    first_element: "str | None"


@dataclass(frozen=True)
class SketchFrame:
    """Where a sketch sits in the Part: its local origin and axes in Part coordinates.

    Read from `Sketch.GetAbsoluteAxisData`. `normal` is `x_axis x y_axis`; for a sketch the
    SDK put on a face it points out of that face's material (probes 46i, 46j, 46aa).

    Attributes:
        origin: Local (0, 0) in Part millimetres.
        x_axis: The local X direction, a unit vector.
        y_axis: The local Y direction, a unit vector.
    """

    origin: Point3
    x_axis: Point3
    y_axis: Point3

    @classmethod
    def from_axis_data(cls, axis_data: "tuple[float, ...]") -> "SketchFrame":
        """Builds a frame from the nine numbers `GetAbsoluteAxisData` returns.

        Args:
            axis_data: Origin, then local X, then local Y, three numbers each.

        Returns:
            The frame.

        Raises:
            ValueError: If there are not exactly nine numbers.
        """
        if len(axis_data) != 9:
            raise ValueError(f"Axis data must hold 9 numbers, not {len(axis_data)}.")
        values = [float(value) for value in axis_data]
        return cls(
            origin=(values[0], values[1], values[2]),
            x_axis=(values[3], values[4], values[5]),
            y_axis=(values[6], values[7], values[8]),
        )

    @property
    def normal(self) -> Point3:
        """tuple[float, float, float]: `x_axis x y_axis`, the side the sketch faces."""
        u, v = self.x_axis, self.y_axis
        return (
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        )

    def to_global(self, point: "tuple[float, float]") -> Point3:
        """Maps a sketch-local point to Part coordinates.

        Live (probe 46k) a circle drawn at local (10, 5) on a top-face sketch cut a bore
        centred exactly at `origin + 10 * x_axis + 5 * y_axis`.

        Args:
            point: Local `(u, v)` in millimetres.

        Returns:
            `(x, y, z)` in Part millimetres.
        """
        u, v = (float(value) for value in point)
        return (
            self.origin[0] + u * self.x_axis[0] + v * self.y_axis[0],
            self.origin[1] + u * self.x_axis[1] + v * self.y_axis[1],
            self.origin[2] + u * self.x_axis[2] + v * self.y_axis[2],
        )

    def to_local(self, point: "tuple[float, float, float]") -> Point2:
        """Maps a Part point to sketch-local coordinates, dropping its distance off-plane.

        Args:
            point: `(x, y, z)` in Part millimetres.

        Returns:
            Local `(u, v)`: the point projected onto the sketch plane.
        """
        delta = tuple(float(point[index]) - self.origin[index] for index in range(3))
        return (
            sum(delta[index] * self.x_axis[index] for index in range(3)),
            sum(delta[index] * self.y_axis[index] for index in range(3)),
        )

    def distance_from_plane(self, point: "tuple[float, float, float]") -> float:
        """Returns how far a Part point lies off the sketch plane, signed along `normal`.

        Args:
            point: `(x, y, z)` in Part millimetres.

        Returns:
            The signed distance in millimetres.
        """
        normal = self.normal
        return sum((float(point[index]) - self.origin[index]) * normal[index] for index in range(3))

    def normal_parallel_to(self, axis: Point3) -> "int | None":
        """Says whether the normal is along or against a unit axis, or neither.

        Args:
            axis: A unit vector, such as `(0, 0, 1)`.

        Returns:
            `1` when the normal points along `axis`, `-1` against it, `None` otherwise.
        """
        dot = sum(self.normal[index] * axis[index] for index in range(3))
        if abs(dot - 1.0) <= _FRAME_AXIS_TOLERANCE:
            return 1
        if abs(dot + 1.0) <= _FRAME_AXIS_TOLERANCE:
            return -1
        return None


@dataclass(frozen=True)
class SketchGeometry:
    """Everything `Sketch.geometry()` reads, as plain values and no COM objects.

    Attributes:
        name: The sketch's name.
        frame: Where the sketch sits in the Part.
        lines: Every `Line2D`, in collection order.
        circles: Every `Circle2D`, closed or arc, in collection order.
        points: Every `Point2D`, in collection order.
        constraints: Every constraint, in collection order.
        other_elements: `(name, kind)` of every element without verified reads, such as
            `("AbsoluteAxis", "Axis2D")` or a spline. Listed, never guessed at.
    """

    name: str
    frame: SketchFrame
    lines: "tuple[SketchElementInfo, ...]"
    circles: "tuple[SketchElementInfo, ...]"
    points: "tuple[SketchElementInfo, ...]"
    constraints: "tuple[ConstraintInfo, ...]"
    other_elements: "tuple[tuple[str, str], ...]"

    @property
    def profile_lines(self) -> "tuple[SketchElementInfo, ...]":
        """tuple[SketchElementInfo, ...]: The lines that are not construction geometry."""
        return tuple(line for line in self.lines if not line.construction)

    @property
    def profile_circles(self) -> "tuple[SketchElementInfo, ...]":
        """tuple[SketchElementInfo, ...]: The circles that are not construction geometry."""
        return tuple(circle for circle in self.circles if not circle.construction)
