"""Geometric facts about topology: what a face or an edge actually is, and where.

A topology snapshot says WHICH edges and faces exist; this module says what they are, so
an agent can pick "the circular edge of radius 5 near (-15, 0, 20)" instead of `edges[7]`.
Every fact comes from CATIA's `MeasurableService` and was verified live (probe 45,
`docs/conventions.md` 1.13):

    service = Editor.GetService("MeasurableService")
    item    = service.GetMeasurable(reference, CATMeasurableType)   # a MeasurableInContext
    typed   = CastTo(item, "MeasurablePlane" | "MeasurableCylinder" | ...)

The second argument of `GetMeasurable` is a `CATMeasurableType` (Circle=2, Cone=3, Curve=4,
Cylinder=5, Line=6, Plane=7, Sphere=9, Surface=10). Probe 31 passed an item-type code there
instead, which is why nothing measured then.

What the live run established, and what this module therefore does:

* **Units are mixed.** `GetArea` is in square METRES (a 60x20 face read 0.0012) while
  `GetCOfG`, `GetPerimeter`, `GetRadius`, `GetLength`, `GetPoints` and `GetPlane` are in
  millimetres. Areas are converted; nothing else is.
* **Casting never fails; the typed getter does.** Any face casts to `MeasurablePlane`, but
  `GetPlane` raises on a cylinder. So a type is recognised by the getter that only that
  geometry answers:

      planar       GetPlane succeeds
      cylindrical  GetPlane fails, Cylinder.GetRadius succeeds, Cone.GetAngle fails and
                   Sphere.GetCenter fails (Sphere.GetRadius wrongly succeeds on a cylinder,
                   so it is never used)
      line         Circle.GetRadius fails, and the start/mid/end points from
                   Curve.GetPoints are collinear with |end - start| equal to the length
      circle/arc   Circle.GetRadius succeeds; GetAngle is 360 for a full circle
      unknown      anything else -- cones, spheres, tori and splines were not exercised,
                   so they are reported as unknown rather than guessed

* **A plane normal is not the outward normal.** `GetPlane` returns the face's plane frame
  `(origin, u, v)`; `u x v` pointed +Z for BOTH the top and the bottom face of a block. The
  normal is therefore exposed as an axis whose sign is not guaranteed, and queries compare
  it sign-insensitively.
* **Point-to-face distance measures the BOUNDED face.** `GetMeasurable(face, 1)` is a
  `MeasurableBetween`, and `DistanceMinToPoint(x, y, z)` returns `(distance, x, y, z)` of
  the closest point (probe 47l): 0 on the face, 5 for a point 5 mm above it, and 10 for a
  point in the face's plane 10 mm beyond its edge -- the face, not its plane. That is what
  makes true face/edge adjacency measurable (`geometry.query`).
* **`MeasureService.GetMeasureItem` is not used.** Its `GetMeasureSurfaceType` and
  `GetMeasureEdgeType` returned "unknown" for every face and edge tried.

Measuring reads only: live, the feature tree, rebuild state and geometrical sets were the
same afterwards. It costs roughly 5-10 ms per element, so facts are computed on first
access and never for elements nobody asks about.
"""

import dataclasses
import math
from collections.abc import Callable
from typing import Any

import pywintypes

from auto_3dx._com import automation_error
from auto_3dx.errors import AutomationError

MEASURABLE_SERVICE_NAME: str = "MeasurableService"
"""The `Editor.GetService` name that answers `GetMeasurable`."""

_MEASURABLE_BETWEEN = 1
_MEASURABLE_CIRCLE = 2
_MEASURABLE_CONE = 3
_MEASURABLE_CURVE = 4
_MEASURABLE_CYLINDER = 5
_MEASURABLE_PLANE = 7
_MEASURABLE_SPHERE = 9
_MEASURABLE_SURFACE = 10
_SQUARE_METRES_TO_SQUARE_MILLIMETRES = 1_000_000.0
_FULL_TURN_DEGREES = 360.0
_ANGLE_TOLERANCE_DEGREES = 1e-6
_LINE_TOLERANCE_MM = 1e-6
_LINE_RELATIVE_TOLERANCE = 1e-9
_PLANE_SEED = [0.0] * 9
_POINT_SEED = [0.0] * 3

SURFACE_PLANAR: str = "planar"
"""A face whose `MeasurablePlane.GetPlane` answers."""

SURFACE_CYLINDRICAL: str = "cylindrical"
"""A face that answers `MeasurableCylinder.GetRadius` and no plane, cone or sphere getter."""

SURFACE_UNKNOWN: str = "unknown"
"""Any other face. Cones, spheres and tori were not exercised live."""

CURVE_LINE: str = "line"
"""A straight edge: collinear start/mid/end points whose span equals its length."""

CURVE_CIRCLE: str = "circle"
"""A full circle: `MeasurableCircle.GetAngle` of 360 degrees."""

CURVE_ARC: str = "arc"
"""A circular arc: `MeasurableCircle` answers with an angle below 360 degrees."""

CURVE_UNKNOWN: str = "unknown"
"""Any other edge. Splines and conics were not exercised live."""

Point = tuple[float, float, float]


@dataclasses.dataclass(frozen=True)
class FaceGeometry:
    """What a face is, as `MeasurableService` reported it.

    Attributes:
        surface_type: `SURFACE_PLANAR`, `SURFACE_CYLINDRICAL` or `SURFACE_UNKNOWN`.
        area_mm2: The face's area, converted from the square metres CATIA reports.
        center_mm: The face's centre of gravity, in millimetres.
        perimeter_mm: The length of the face's boundary, in millimetres.
        normal: For a planar face, the unit normal of its plane. Its SIGN IS NOT
            GUARANTEED to point out of the solid (live, a block's top and bottom faces both
            reported +Z), so treat it as an axis. `None` for any other face.
        plane_origin_mm: For a planar face, the origin of the plane frame CATIA reports.
        radius_mm: For a cylindrical face, its radius. `None` otherwise.
    """

    surface_type: str
    area_mm2: float
    center_mm: Point
    perimeter_mm: float
    normal: "Point | None" = None
    plane_origin_mm: "Point | None" = None
    radius_mm: "float | None" = None


@dataclasses.dataclass(frozen=True)
class EdgeGeometry:
    """What an edge is, as `MeasurableService` reported it.

    Attributes:
        curve_type: `CURVE_LINE`, `CURVE_CIRCLE`, `CURVE_ARC` or `CURVE_UNKNOWN`.
        length_mm: The edge's length, in millimetres.
        start_mm: One end of the edge.
        mid_mm: The point halfway along the edge.
        end_mm: The other end. Equal to `start_mm` for a full circle.
        direction: For a line, the unit vector from `start_mm` to `end_mm`. `None`
            otherwise.
        radius_mm: For a circle or an arc, its radius. `None` otherwise.
        center_mm: For a circle or an arc, its centre. `None` otherwise.
        angle_deg: For a circle or an arc, the angle it spans. `None` otherwise.
    """

    curve_type: str
    length_mm: float
    start_mm: Point
    mid_mm: Point
    end_mm: Point
    direction: "Point | None" = None
    radius_mm: "float | None" = None
    center_mm: "Point | None" = None
    angle_deg: "float | None" = None


def _cast_to(item: Any, interface: str) -> Any:
    """Casts a `MeasurableInContext` to the typed interface that carries the getters.

    Args:
        item: What `GetMeasurable` returned.
        interface: The typed interface name, for example `"MeasurablePlane"`.

    Returns:
        The typed dispatch.
    """
    import win32com.client

    return win32com.client.CastTo(item, interface)


def _point(values: Any) -> Point:
    x, y, z = (float(value) for value in values)
    return (x, y, z)


def _distance(a: Point, b: Point) -> float:
    return math.dist(a, b)


def _unit(vector: Point) -> "Point | None":
    length = math.hypot(*vector)
    if length == 0.0:
        return None
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def _cross(a: Point, b: Point) -> Point:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


class GeometryMeasurer:
    """Measures faces and edges through one editor's `MeasurableService`.

    Built by `Part` from the editor that edits it, so each Part measures through its own
    editor. The service is fetched on first use and cached for the life of this object.
    """

    def __init__(
        self, editor_com_object: Any, cast: "Callable[[Any, str], Any] | None" = None
    ) -> None:
        """Initializes the measurer without contacting CATIA.

        Args:
            editor_com_object: The raw `Editor` whose `GetService` answers
                `MEASURABLE_SERVICE_NAME`.
            cast: Turns a `MeasurableInContext` into a typed interface. The default uses
                `win32com.client.CastTo`; tests pass a fake.
        """
        self._editor = editor_com_object
        self._cast = cast if cast is not None else _cast_to
        self._service: Any = None

    def _measurable(self, reference: Any, type_code: int, interface: str) -> Any:
        """Returns `reference` measured as one typed interface.

        Raises:
            AutomationError: If the service cannot be reached or refuses the reference.
        """
        if self._service is None:
            try:
                service = self._editor.GetService(MEASURABLE_SERVICE_NAME)
            except pywintypes.com_error as error:
                raise automation_error(error, "requesting the measurable service") from error
            if service is None:
                raise AutomationError(
                    f"Editor.GetService({MEASURABLE_SERVICE_NAME!r}) returned no service."
                )
            self._service = service
        try:
            item = self._service.GetMeasurable(reference, type_code)
        except pywintypes.com_error as error:
            raise automation_error(error, "measuring a topology reference") from error
        try:
            return self._cast(item, interface)
        except (pywintypes.com_error, TypeError, ValueError) as error:
            raise AutomationError(
                f"The measurable could not be read as {interface}."
            ) from error

    @staticmethod
    def _answers(call: Callable[[], Any]) -> Any:
        """Returns what a typed getter answers, or `None` when it refuses.

        A refusal is how CATIA says the geometry is not that type (probe 45), so it is a
        result here, not an error.
        """
        try:
            return call()
        except pywintypes.com_error:
            return None

    def face(self, reference: Any) -> FaceGeometry:
        """Measures one face.

        Args:
            reference: The face's raw `Reference`, from a `FaceSnapshot`.

        Returns:
            Its `FaceGeometry`.

        Raises:
            AutomationError: If the face cannot be measured at all.
        """
        surface = self._measurable(reference, _MEASURABLE_SURFACE, "MeasurableSurface")
        try:
            area = float(surface.GetArea()) * _SQUARE_METRES_TO_SQUARE_MILLIMETRES
            center = _point(surface.GetCOfG())
            perimeter = float(surface.GetPerimeter())
        except pywintypes.com_error as error:
            raise automation_error(error, "measuring a face") from error

        plane = self._measurable(reference, _MEASURABLE_PLANE, "MeasurablePlane")
        frame = self._answers(lambda: plane.GetPlane(list(_PLANE_SEED)))
        if frame is not None:
            values = [float(value) for value in frame]
            origin = (values[0], values[1], values[2])
            normal = _unit(_cross(
                (values[3], values[4], values[5]), (values[6], values[7], values[8])
            ))
            return FaceGeometry(
                SURFACE_PLANAR, area, center, perimeter, normal=normal, plane_origin_mm=origin
            )

        cylinder = self._measurable(reference, _MEASURABLE_CYLINDER, "MeasurableCylinder")
        radius = self._answers(cylinder.GetRadius)
        if radius is not None:
            cone = self._measurable(reference, _MEASURABLE_CONE, "MeasurableCone")
            sphere = self._measurable(reference, _MEASURABLE_SPHERE, "MeasurableSphere")
            if self._answers(cone.GetAngle) is None and self._answers(sphere.GetCenter) is None:
                return FaceGeometry(
                    SURFACE_CYLINDRICAL, area, center, perimeter, radius_mm=float(radius)
                )
        return FaceGeometry(SURFACE_UNKNOWN, area, center, perimeter)

    def edge(self, reference: Any) -> EdgeGeometry:
        """Measures one edge.

        Args:
            reference: The edge's raw `Reference`, from an `EdgeSnapshot`.

        Returns:
            Its `EdgeGeometry`.

        Raises:
            AutomationError: If the edge cannot be measured at all.
        """
        curve = self._measurable(reference, _MEASURABLE_CURVE, "MeasurableCurve")
        try:
            length = float(curve.GetLength())
            start, mid, end = (
                _point(values)
                for values in curve.GetPoints(
                    list(_POINT_SEED), list(_POINT_SEED), list(_POINT_SEED)
                )
            )
        except pywintypes.com_error as error:
            raise automation_error(error, "measuring an edge") from error

        circle = self._measurable(reference, _MEASURABLE_CIRCLE, "MeasurableCircle")
        radius = self._answers(circle.GetRadius)
        if radius is not None:
            center = self._answers(circle.GetCenter)
            angle = self._answers(circle.GetAngle)
            full = angle is not None and abs(float(angle) - _FULL_TURN_DEGREES) <= (
                _ANGLE_TOLERANCE_DEGREES
            )
            return EdgeGeometry(
                CURVE_CIRCLE if full else CURVE_ARC,
                length,
                start,
                mid,
                end,
                radius_mm=float(radius),
                center_mm=_point(center) if center is not None else None,
                angle_deg=float(angle) if angle is not None else None,
            )

        span = _distance(start, end)
        halfway: Point = (
            (start[0] + end[0]) / 2,
            (start[1] + end[1]) / 2,
            (start[2] + end[2]) / 2,
        )
        # Absolute for small parts, relative for large ones: live values carried float
        # noise of ~1e-14 mm (a 20 mm edge read 19.999999999999996).
        tolerance = max(_LINE_TOLERANCE_MM, length * _LINE_RELATIVE_TOLERANCE)
        if (
            span > 0.0
            and abs(span - length) <= tolerance
            and _distance(mid, halfway) <= tolerance
        ):
            direction = _unit((end[0] - start[0], end[1] - start[1], end[2] - start[2]))
            return EdgeGeometry(CURVE_LINE, length, start, mid, end, direction=direction)
        return EdgeGeometry(CURVE_UNKNOWN, length, start, mid, end)

    def point_distance(self, reference: Any) -> "Callable[[Point], float]":
        """Returns a function measuring the shortest distance from a point to one face.

        The face is measured once (`GetMeasurable(reference, 1)` as `MeasurableBetween`);
        each call of the returned function is one `DistanceMinToPoint`. Live (probe 47l)
        the distance is to the bounded face, not to its underlying surface.

        Args:
            reference: The face's raw `Reference`, from a `FaceSnapshot`.

        Returns:
            `distance(point) -> float`, in millimetres, for a point in Part millimetres.

        Raises:
            AutomationError: If the face cannot be measured (now, or when the function
                is called).
        """
        between = self._measurable(reference, _MEASURABLE_BETWEEN, "MeasurableBetween")

        def distance(point: Point) -> float:
            try:
                answer = between.DistanceMinToPoint(
                    float(point[0]), float(point[1]), float(point[2])
                )
            except pywintypes.com_error as error:
                raise automation_error(error, "measuring a point-to-face distance") from error
            try:
                return float(answer[0])
            except (TypeError, IndexError, ValueError) as error:
                raise AutomationError(
                    "MeasurableBetween.DistanceMinToPoint returned no usable distance."
                ) from error

        return distance

    def __repr__(self) -> str:
        """str: Debug representation; does not contact CATIA."""
        return "GeometryMeasurer()"
