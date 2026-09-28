"""Tests for Phase 4: geometry facts and queries, direction, plane editing and guards, diagnostics.

The fakes return what probe 45 measured live (`docs/conventions.md` 1.13):

    MeasurableSurface.GetArea      -> square metres (0.0012 for a 60x20 face)
    MeasurableSurface.GetCOfG      -> millimetres
    MeasurablePlane.GetPlane(seed) -> (origin, u, v); raises on a curved face
    MeasurableCylinder.GetRadius   -> millimetres; raises on a planar face
    MeasurableCurve.GetPoints      -> (start, mid, end) in millimetres
    MeasurableCircle.GetRadius     -> raises on a straight edge
    DirectionOrientation           -> 0 along the sketch normal, 1 against it
    Part.IsUpToDate / IsInactive   -> per feature, after a failed update
"""

import math
from typing import Any

import pytest
import pywintypes

from auto_3dx.core.part import Part
from auto_3dx.errors import (
    AutomationError,
    ParameterTypeError,
    PartUpdateError,
    ReferenceInUseError,
    StaleSnapshotError,
    TopologyQueryAmbiguousError,
    TopologyQueryNoMatchError,
)
from auto_3dx.geometry.edges import Edge, EdgeSnapshot
from auto_3dx.geometry.faces import Face, FaceSnapshot
from auto_3dx.geometry.facts import (
    CURVE_ARC,
    CURVE_CIRCLE,
    CURVE_LINE,
    CURVE_UNKNOWN,
    SURFACE_CYLINDRICAL,
    SURFACE_PLANAR,
    SURFACE_UNKNOWN,
    GeometryMeasurer,
)
from auto_3dx.geometry.part_design import (
    DIRECTION_AGAINST_SKETCH_NORMAL,
    DIRECTION_ALONG_SKETCH_NORMAL,
    Pad,
    Pocket,
)
from auto_3dx.geometry.planes import AnglePlane, OffsetPlane, PlaneCollection
from auto_3dx._generation import ModelGeneration

E_FAIL = -2147467259


def _com_error() -> pywintypes.com_error:
    return pywintypes.com_error(
        -2147352567, "Exception occurred.", (0, "CATIA", "failed", None, 0, E_FAIL), None
    )


def _refuse(*_: Any) -> Any:
    raise _com_error()


# --- fake measurable geometry ------------------------------------------------------------------


class _Shape:
    """What one fake topology reference really is: the facts the measurables report."""

    def __init__(self, **facts: Any) -> None:
        self.facts = facts


def _plane_face(area_mm2: float, center: Any, u: Any, v: Any, origin: Any = (0, 0, 0)) -> _Shape:
    return _Shape(area=area_mm2 / 1e6, cog=center, perimeter=10.0, plane=(*origin, *u, *v))


def _cylinder_face(area_mm2: float, center: Any, radius: float) -> _Shape:
    return _Shape(area=area_mm2 / 1e6, cog=center, perimeter=10.0, radius=radius)


def _line(start: Any, end: Any) -> _Shape:
    mid = tuple((a + b) / 2 for a, b in zip(start, end))
    return _Shape(length=math.dist(start, end), points=(start, mid, end))


def _circle(center: Any, radius: float, angle: float = 360.0) -> _Shape:
    start = (center[0] + radius, center[1], center[2])
    return _Shape(
        length=2 * math.pi * radius * angle / 360.0,
        points=(start, (center[0], center[1] + radius, center[2]), start),
        circle_radius=radius,
        center=center,
        angle=angle,
    )


class _Typed:
    """A fake typed measurable: each getter answers only if the shape has that fact."""

    def __init__(self, shape: _Shape, interface: str) -> None:
        self._facts = shape.facts
        self._interface = interface

    def _fact(self, key: str) -> Any:
        if key not in self._facts:
            raise _com_error()
        return self._facts[key]

    def GetArea(self) -> float:  # noqa: N802 - COM method name
        return self._fact("area")

    def GetCOfG(self) -> Any:  # noqa: N802 - COM method name
        return self._fact("cog")

    def GetPerimeter(self) -> float:  # noqa: N802 - COM method name
        return self._fact("perimeter")

    def GetPlane(self, seed: Any) -> Any:  # noqa: N802 - COM method name
        return self._fact("plane")

    def GetRadius(self) -> float:  # noqa: N802 - COM method name
        if self._interface == "MeasurableCircle":
            return self._fact("circle_radius")
        if self._interface == "MeasurableSphere":
            return self._fact("radius")  # live, a sphere cast answered on a cylinder too
        return self._fact("radius")

    def GetAngle(self) -> float:  # noqa: N802 - COM method name
        if self._interface == "MeasurableCone":
            return self._fact("cone_angle")
        return self._fact("angle")

    def GetCenter(self) -> Any:  # noqa: N802 - COM method name
        if self._interface == "MeasurableSphere":
            return self._fact("sphere_center")
        return self._fact("center")

    def GetLength(self) -> float:  # noqa: N802 - COM method name
        return self._fact("length")

    def GetPoints(self, *seeds: Any) -> Any:  # noqa: N802 - COM method name
        return self._fact("points")


class _Service:
    def __init__(self) -> None:
        self.calls = 0

    def GetMeasurable(self, reference: Any, type_code: int) -> Any:  # noqa: N802
        self.calls += 1
        return reference


class _Editor:
    def __init__(self) -> None:
        self.service = _Service()

    def GetService(self, name: str) -> Any:  # noqa: N802 - COM method name
        assert name == "MeasurableService"
        return self.service


def _measurer() -> GeometryMeasurer:
    return GeometryMeasurer(_Editor(), cast=lambda item, interface: _Typed(item, interface))


def _face_snapshot(shapes: "list[_Shape]", generation: ModelGeneration) -> FaceSnapshot:
    measurer = _measurer()
    faces = [
        Face(shape, index, generation.value, measurer=measurer, model_generation=generation)
        for index, shape in enumerate(shapes, start=1)
    ]
    return FaceSnapshot(faces, generation.value)


def _edge_snapshot(shapes: "list[_Shape]", generation: ModelGeneration) -> EdgeSnapshot:
    measurer = _measurer()
    edges = [
        Edge(shape, index, generation.value, measurer=measurer, model_generation=generation)
        for index, shape in enumerate(shapes, start=1)
    ]
    return EdgeSnapshot(edges, generation.value)


X, Y, Z = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)


def _block_faces() -> "list[_Shape]":
    """A 60x40x20 block with an R5 through hole, as the live block measured."""
    top_area = 60 * 40 - math.pi * 25
    return [
        _cylinder_face(2 * math.pi * 5 * 20, (-15, 0, 10), 5.0),
        _plane_face(1200.0, (0, -20, 10), X, Z),
        _plane_face(800.0, (30, 0, 10), Y, Z),
        _plane_face(1200.0, (0, 20, 10), (-1, 0, 0), Z),
        _plane_face(800.0, (-30, 0, 10), (0, -1, 0), Z),
        _plane_face(top_area, (0.5, 0, 0), X, Y),  # bottom: its plane normal is +Z too
        _plane_face(top_area, (0.5, 0, 20), X, Y, origin=(0, 0, 20)),
    ]


# --- geometry facts -----------------------------------------------------------------------------


def test_a_planar_face_reports_area_in_mm2_centre_and_an_axis_normal() -> None:
    geometry = _measurer().face(_plane_face(1200.0, (0, -20, 10), X, Z))

    assert geometry.surface_type == SURFACE_PLANAR
    assert geometry.area_mm2 == pytest.approx(1200.0)
    assert geometry.center_mm == (0, -20, 10)
    assert geometry.normal == pytest.approx((0.0, -1.0, 0.0))
    assert geometry.radius_mm is None


def test_a_cylindrical_face_reports_its_radius() -> None:
    geometry = _measurer().face(_cylinder_face(628.3, (-15, 0, 10), 5.0))

    assert geometry.surface_type == SURFACE_CYLINDRICAL
    assert geometry.radius_mm == 5.0
    assert geometry.normal is None


def test_a_face_answering_cone_or_sphere_getters_is_not_called_cylindrical() -> None:
    """Only planes and cylinders were verified; anything else stays unknown."""
    cone = _Shape(area=0.001, cog=(0, 0, 0), perimeter=1.0, radius=5.0, cone_angle=30.0)
    sphere = _Shape(area=0.001, cog=(0, 0, 0), perimeter=1.0, radius=5.0, sphere_center=(0, 0, 0))

    assert _measurer().face(cone).surface_type == SURFACE_UNKNOWN
    assert _measurer().face(sphere).surface_type == SURFACE_UNKNOWN


def test_a_straight_edge_is_a_line_with_a_direction() -> None:
    geometry = _measurer().edge(_line((30, 20, 0), (30, 20, 20)))

    assert geometry.curve_type == CURVE_LINE
    assert geometry.length_mm == pytest.approx(20.0)
    assert geometry.direction == pytest.approx(Z)


def test_a_full_circle_and_an_arc_report_radius_centre_and_angle() -> None:
    circle = _measurer().edge(_circle((-15, 0, 20), 5.0))
    arc = _measurer().edge(_circle((27, -17, 0), 3.0, angle=90.0))

    assert (circle.curve_type, circle.radius_mm, circle.center_mm) == (
        CURVE_CIRCLE, 5.0, (-15, 0, 20),
    )
    assert (arc.curve_type, arc.angle_deg) == (CURVE_ARC, 90.0)


def test_a_curved_edge_that_is_not_circular_is_unknown() -> None:
    """A spline's span is shorter than its length, so it is not a line either."""
    spline = _Shape(length=12.0, points=((0, 0, 0), (5, 3, 0), (10, 0, 0)))

    assert _measurer().edge(spline).curve_type == CURVE_UNKNOWN


def test_a_measurable_that_cannot_be_read_at_all_raises() -> None:
    with pytest.raises(AutomationError):
        _measurer().face(_Shape())


def test_geometry_is_measured_once_and_reused() -> None:
    generation = ModelGeneration()
    measurer = _measurer()
    face = Face(_block_faces()[1], 1, 0, measurer=measurer, model_generation=generation)

    first = face.geometry
    calls = measurer._editor.service.calls
    second = face.geometry

    assert first is second
    assert measurer._editor.service.calls == calls


def test_geometry_of_a_stale_handle_is_refused() -> None:
    generation = ModelGeneration()
    face = _face_snapshot(_block_faces(), generation)[1]
    face.geometry  # cached while fresh

    generation.advance()

    with pytest.raises(StaleSnapshotError):
        face.geometry


def test_a_handle_without_a_measurer_says_how_to_get_one() -> None:
    edge = Edge(_line((0, 0, 0), (1, 0, 0)), 1)

    with pytest.raises(AutomationError, match="part.topology"):
        edge.geometry


def test_the_current_owner_alias_matches_owner_feature_name() -> None:
    edge = Edge(object(), 1, owner_feature_name="FILLET")

    assert edge.current_owner_feature_name == edge.owner_feature_name == "FILLET"


# --- face queries -------------------------------------------------------------------------------


def test_the_top_face_is_found_without_trusting_the_normal_sign() -> None:
    faces = _face_snapshot(_block_faces(), ModelGeneration())

    horizontal = faces.query().planar().normal_parallel(Z)
    top = horizontal.extreme(Z).one()

    assert horizontal.count() == 2
    assert top.geometry.center_mm[2] == 20


def test_equal_areas_are_a_tie_that_one_refuses() -> None:
    faces = _face_snapshot(_block_faces(), ModelGeneration())

    with pytest.raises(TopologyQueryAmbiguousError, match="2 faces"):
        faces.query().planar().normal_parallel(Z).largest().one()


def test_a_cylindrical_face_is_found_by_radius_with_a_tolerance() -> None:
    faces = _face_snapshot(_block_faces(), ModelGeneration())

    assert faces.query().cylindrical().radius_near(5.004, tolerance_mm=0.01).one().index == 1
    with pytest.raises(TopologyQueryNoMatchError):
        faces.query().cylindrical().radius_near(5.5, tolerance_mm=0.01).one()


def test_nearest_and_area_filters_pick_a_side_face() -> None:
    faces = _face_snapshot(_block_faces(), ModelGeneration())

    side = faces.query().planar().area_between(700, 900).nearest((40, 0, 10)).one()

    assert side.geometry.center_mm == (30, 0, 10)


def test_smallest_and_a_normal_tolerance() -> None:
    faces = _face_snapshot(_block_faces(), ModelGeneration())

    assert faces.query().planar().normal_parallel(X, tolerance_deg=0.5).count() == 2
    assert faces.query().planar().smallest().count() == 2


def test_first_returns_snapshot_order_and_refuses_an_empty_query() -> None:
    faces = _face_snapshot(_block_faces(), ModelGeneration())

    assert faces.query().planar().first().index == 2
    with pytest.raises(TopologyQueryNoMatchError):
        faces.query().radius_near(99.0).first()


def test_a_query_is_immutable() -> None:
    faces = _face_snapshot(_block_faces(), ModelGeneration())
    base = faces.query()

    base.planar()

    assert base.count() == 7


def test_a_query_over_a_stale_snapshot_raises() -> None:
    generation = ModelGeneration()
    faces = _face_snapshot(_block_faces(), generation)
    generation.advance()

    with pytest.raises(StaleSnapshotError):
        faces.query().planar().one()


@pytest.mark.parametrize(
    "call",
    [
        lambda q: q.normal_parallel((0, 0, 0)),
        lambda q: q.normal_parallel("up"),
        lambda q: q.radius_near(5.0, tolerance_mm=-1.0),
        lambda q: q.nearest((1, 2)),
        lambda q: q.extreme((0, float("nan"), 1)),
        lambda q: q.largest(tolerance_mm2=True),
    ],
)
def test_unusable_query_arguments_are_refused(call: Any) -> None:
    faces = _face_snapshot(_block_faces(), ModelGeneration())

    with pytest.raises(ParameterTypeError):
        call(faces.query())


def test_owned_by_filters_on_the_current_owner() -> None:
    generation = ModelGeneration()
    measurer = _measurer()
    faces = FaceSnapshot(
        [
            Face(_block_faces()[1], 1, 0, owner_feature_name="POCKET",
                 measurer=measurer, model_generation=generation),
            Face(_block_faces()[2], 2, 0, owner_feature_name="FILLET",
                 measurer=measurer, model_generation=generation),
        ]
    )

    assert faces.query().owned_by("FILLET").one().index == 2


# --- edge queries -------------------------------------------------------------------------------


def _block_edges() -> "list[_Shape]":
    return [
        _line((30, 20, 0), (30, 20, 20)),
        _line((-30, 20, 0), (-30, 20, 20)),
        _line((-30, -20, 0), (30, -20, 0)),
        _circle((-15, 0, 0), 5.0),
        _circle((-15, 0, 20), 5.0),
        _circle((27, -17, 20), 3.0, angle=90.0),
    ]


def test_a_hole_rim_is_found_by_radius_and_position() -> None:
    edges = _edge_snapshot(_block_edges(), ModelGeneration())

    rim = edges.query().circular().radius_near(5.0).nearest((-15, 0, 20)).one()

    assert rim.geometry.center_mm == (-15, 0, 20)


def test_two_rims_of_the_same_radius_are_ambiguous_until_positioned() -> None:
    edges = _edge_snapshot(_block_edges(), ModelGeneration())

    with pytest.raises(TopologyQueryAmbiguousError, match="2 edges"):
        edges.query().circular().radius_near(5.0).one()


def test_a_vertical_line_is_found_by_direction_either_way_round() -> None:
    edges = _edge_snapshot(_block_edges(), ModelGeneration())

    vertical = edges.query().lines().parallel((0, 0, -1))

    assert vertical.count() == 2
    assert vertical.nearest((30, 20, 10)).one().index == 1


def test_longest_shortest_and_length_bounds() -> None:
    edges = _edge_snapshot(_block_edges(), ModelGeneration())

    assert edges.query().lines().longest().one().index == 3
    assert edges.query().lines().shortest().count() == 2
    assert edges.query().length_between(19.0, 21.0).count() == 2


def test_arcs_count_as_circular_and_types_are_filterable() -> None:
    edges = _edge_snapshot(_block_edges(), ModelGeneration())

    assert edges.query().circular().count() == 3
    assert edges.query().of_type(CURVE_ARC).one().index == 6
    assert edges.query().extreme(Z).lines().count() == 0


# --- direction ----------------------------------------------------------------------------------


class _RawSketchFeature:
    def __init__(self, orientation: int) -> None:
        self.Name = "F"
        self.DirectionOrientation = orientation


def test_direction_reads_catias_orientation() -> None:
    assert Pad(_RawSketchFeature(0)).direction == DIRECTION_ALONG_SKETCH_NORMAL
    assert Pocket(_RawSketchFeature(1)).direction == DIRECTION_AGAINST_SKETCH_NORMAL


def test_set_direction_writes_without_rebuilding_and_advances_the_generation() -> None:
    generation = ModelGeneration()
    raw = _RawSketchFeature(1)
    pocket = Pocket(raw, generation)

    pocket.set_direction(DIRECTION_ALONG_SKETCH_NORMAL)

    assert raw.DirectionOrientation == 0
    assert generation.value == 1


def test_reverse_direction_flips_it() -> None:
    raw = _RawSketchFeature(0)

    Pad(raw).reverse_direction()

    assert raw.DirectionOrientation == 1


def test_an_unknown_direction_is_refused_before_catia() -> None:
    raw = _RawSketchFeature(0)

    with pytest.raises(ParameterTypeError):
        Pad(raw).set_direction("up")
    assert raw.DirectionOrientation == 0


def test_an_unknown_orientation_from_catia_is_not_guessed() -> None:
    with pytest.raises(AutomationError):
        Pad(_RawSketchFeature(7)).direction


class _Items:
    def __init__(self, parent: Any = None) -> None:
        self.items: "list[Any]" = []
        self.Parent = parent

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self.items)

    def Item(self, key: Any) -> Any:  # noqa: N802 - COM method name
        if isinstance(key, str):
            for item in self.items:
                if item.Name == key:
                    return item
            raise _com_error()
        return self.items[key - 1]


class _Factory:
    def __init__(self, body: Any) -> None:
        self._body = body

    def _add(self, sketch: Any, depth: float) -> Any:
        feature = _RawSketchFeature(0)
        self._body.Shapes.items.append(feature)
        return feature

    def AddNewPad(self, sketch: Any, height: float) -> Any:  # noqa: N802 - COM method name
        return self._add(sketch, height)

    def AddNewPocket(self, sketch: Any, depth: float) -> Any:  # noqa: N802 - COM method
        feature = self._add(sketch, depth)
        feature.DirectionOrientation = 1  # CATIA's pocket default (probe 45)
        return feature


class _RawBody:
    def __init__(self) -> None:
        self.Name = "PartBody"
        self.Shapes = _Items(self)
        self.Sketches = _Items(self)


class _PartForCreation:
    def __init__(self) -> None:
        self.Name = "3D Shape1"
        self.MainBody = _RawBody()
        self.ShapeFactory = _Factory(self.MainBody)
        self.InWorkObject = self.MainBody


class _Sketch:
    com_object = object()


def test_a_pocket_can_be_created_along_the_normal() -> None:
    from auto_3dx.geometry.part_design import PartDesign

    raw = _PartForCreation()
    pocket = PartDesign(raw).create_pocket(
        "CUT", _Sketch(), 10.0, direction=DIRECTION_ALONG_SKETCH_NORMAL
    )

    assert pocket.com_object.DirectionOrientation == 0


def test_without_a_direction_catias_default_is_kept() -> None:
    from auto_3dx.geometry.part_design import PartDesign

    raw = _PartForCreation()
    pocket = PartDesign(raw).create_pocket("CUT", _Sketch(), 10.0)

    assert pocket.direction == DIRECTION_AGAINST_SKETCH_NORMAL


def test_a_bad_direction_is_refused_before_anything_is_created() -> None:
    from auto_3dx.geometry.part_design import PartDesign

    raw = _PartForCreation()

    with pytest.raises(ParameterTypeError):
        PartDesign(raw).create_pad("P", _Sketch(), 10.0, direction="up")
    assert raw.MainBody.Shapes.items == []


# --- plane editing and the in-use guard ---------------------------------------------------------


class _Value:
    def __init__(self, value: float) -> None:
        self.Value = value


class _RawPlane:
    def __init__(self, name: str, frame: "tuple[float, ...]", **values: Any) -> None:
        self.Name = name
        self._frame = frame
        for member, value in values.items():
            setattr(self, member, _Value(value))

    def GetOrigin(self, seed: Any) -> Any:  # noqa: N802 - COM method name
        return self._frame[0:3]

    def GetFirstAxis(self, seed: Any) -> Any:  # noqa: N802 - COM method name
        return self._frame[3:6]

    def GetSecondAxis(self, seed: Any) -> Any:  # noqa: N802 - COM method name
        return self._frame[6:9]


class HybridShapePlaneOffset(_RawPlane):  # noqa: N801 - CATIA's own type name
    pass


class _RawSketchOnPlane:
    def __init__(self, name: str, frame: "tuple[float, ...]") -> None:
        self.Name = name
        self._frame = frame

    def GetAbsoluteAxisData(self, seed: Any) -> Any:  # noqa: N802 - COM method name
        return self._frame


LIFT_FRAME = (0.0, 0.0, 40.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)


class _PlanePart:
    def __init__(self, sketches: "list[Any]") -> None:
        body = _RawBody()
        body.Sketches.items.extend(sketches)
        self.Bodies = _Items(self)
        self.Bodies.items.append(body)
        self.HybridBodies = _Items(self)


def test_an_offset_plane_is_moved_without_rebuilding() -> None:
    generation = ModelGeneration()
    plane = OffsetPlane(HybridShapePlaneOffset("LIFT", LIFT_FRAME, Offset=40.0), generation)

    plane.set_offset(55.0)

    assert plane.offset == 55.0
    assert generation.value == 1


def test_an_angle_plane_is_turned_without_rebuilding() -> None:
    plane = AnglePlane(_RawPlane("TILT", LIFT_FRAME, Angle=30.0))

    plane.set_angle(45.0)

    assert plane.angle == 45.0


@pytest.mark.parametrize("value", [float("inf"), "far", True])
def test_an_unusable_plane_value_is_refused(value: Any) -> None:
    plane = OffsetPlane(HybridShapePlaneOffset("LIFT", LIFT_FRAME, Offset=40.0))

    with pytest.raises(ParameterTypeError):
        plane.set_offset(value)
    assert plane.offset == 40.0


def test_a_sketch_sitting_on_a_plane_is_a_dependent() -> None:
    raw_part = _PlanePart(
        [_RawSketchOnPlane("ON_IT", LIFT_FRAME), _RawSketchOnPlane("ELSEWHERE", (0,) * 9)]
    )
    collection = PlaneCollection(raw_part)
    plane = OffsetPlane(HybridShapePlaneOffset("LIFT", LIFT_FRAME, Offset=40.0))

    assert collection.dependents(plane) == ["ON_IT"]


def test_removing_a_plane_in_use_is_refused_before_catia() -> None:
    raw_part = _PlanePart([_RawSketchOnPlane("ON_IT", LIFT_FRAME)])

    class _Selection:
        deleted = False

        def Clear(self) -> None:  # noqa: N802 - COM method name
            raise AssertionError("nothing may be deleted")

    collection = PlaneCollection(raw_part, _Selection())
    plane = OffsetPlane(HybridShapePlaneOffset("LIFT", LIFT_FRAME, Offset=40.0))

    with pytest.raises(ReferenceInUseError, match="ON_IT"):
        collection.remove(plane)


def test_a_plane_nothing_sits_on_has_no_dependents() -> None:
    collection = PlaneCollection(_PlanePart([]))
    plane = OffsetPlane(HybridShapePlaneOffset("LIFT", LIFT_FRAME, Offset=40.0))

    assert collection.dependents(plane) == []


# --- update diagnostics -------------------------------------------------------------------------


class _Feature:
    def __init__(self, name: str) -> None:
        self.Name = name


class Pad_(_Feature):  # noqa: N801 - stands in for a CATIA type name
    pass


class _DiagnosedPart:
    """A Part whose per-feature status is what probe 45 saw after suppressing a pad."""

    def __init__(self, stale: "set[str]", inactive: "set[str]", fail: bool) -> None:
        self.Name = "3D Shape1"
        self.MainBody = _RawBody()
        self.MainBody.Shapes.items.extend(
            [Pad_("BLOCK_PAD"), _Feature("HOLE"), _Feature("FILLET")]
        )
        self.Bodies = _Items(self)
        self.Bodies.items.append(self.MainBody)
        self._stale, self._inactive, self._fail = stale, inactive, fail

    def IsUpToDate(self, item: Any) -> bool:  # noqa: N802 - COM method name
        return item is self or item.Name not in self._stale

    def IsInactive(self, item: Any) -> bool:  # noqa: N802 - COM method name
        return item.Name in self._inactive

    def Update(self) -> None:  # noqa: N802 - COM method name
        if self._fail:
            raise _com_error()


def test_a_healthy_model_has_no_update_issues() -> None:
    part = Part(_DiagnosedPart(set(), set(), fail=False))

    assert part.inspect.update_issues() == ()


def test_update_issues_report_state_not_cause() -> None:
    """The suppressed pad is reported inactive; the fillet is where the rebuild stopped."""
    part = Part(_DiagnosedPart({"FILLET"}, {"BLOCK_PAD"}, fail=True))

    issues = {issue.name: issue for issue in part.inspect.update_issues()}

    assert set(issues) == {"BLOCK_PAD", "FILLET"}
    assert (issues["BLOCK_PAD"].up_to_date, issues["BLOCK_PAD"].active) == (True, False)
    assert (issues["FILLET"].up_to_date, issues["FILLET"].active) == (False, True)
    assert issues["BLOCK_PAD"].kind == "Pad_"
    assert issues["FILLET"].body_name == "PartBody"


def test_a_failed_update_carries_the_issues_it_found() -> None:
    part = Part(_DiagnosedPart({"FILLET"}, {"BLOCK_PAD"}, fail=True))

    with pytest.raises(PartUpdateError) as failure:
        part.update()

    assert {issue.name for issue in failure.value.issues} == {"BLOCK_PAD", "FILLET"}


def test_diagnostics_that_cannot_be_read_never_replace_the_update_error() -> None:
    raw = _DiagnosedPart({"FILLET"}, set(), fail=True)
    raw.IsInactive = _refuse
    part = Part(raw)

    with pytest.raises(PartUpdateError) as failure:
        part.update()

    assert failure.value.issues == ()


def test_a_part_update_error_still_defaults_to_no_issues() -> None:
    assert PartUpdateError("failed").issues == ()


# --- Owner fallback: body membership when the Parent walk does not reach a body ---


class _Named:
    def __init__(self, name: str, parent: Any = None) -> None:
        self.Name = name
        self.Parent = parent


class _Collection:
    def __init__(self, items: "list[Any]") -> None:
        self._items = items
        self.Count = len(items)

    def Item(self, index: int) -> Any:  # noqa: N802 - COM spelling
        return self._items[index - 1]


class Body:
    """Named like the COM class so the Parent walk recognises it."""

    def __init__(self, name: str, shapes: "list[str]", sketches: "list[str]") -> None:
        self.Name = name
        self.Parent = None
        self.Shapes = _Collection([_Named(n) for n in shapes])
        self.Sketches = _Collection([_Named(n) for n in sketches])


class _PartWithBodies:
    def __init__(self, bodies: "list[Body]") -> None:
        self.Bodies = _Collection(bodies)


def _wrapper_chain(feature_name: str) -> _Named:
    """A reference whose Parent chain is generic wrappers that never reach a body."""
    top = _Named("CATIABase2")
    top.Parent = top
    return _Named("edge", parent=_Named(feature_name, parent=_Named("CATIABase1", top)))


def test_owner_walk_that_reaches_a_body_ignores_the_fallback() -> None:
    from auto_3dx.geometry._topology_search import BodyIndex, owner_of

    body = Body("PartBody", ["Pad.1"], [])
    reference = _Named("edge", parent=_Named("Pad.1", parent=_Named("Shapes", body)))
    index = BodyIndex(_PartWithBodies([Body("Other", ["Pad.1"], [])]))
    owner, name, feature = owner_of(reference, index)
    assert owner is body and name == "PartBody" and feature == "Pad.1"


def test_owner_falls_back_to_the_one_body_holding_the_feature() -> None:
    from auto_3dx.geometry._topology_search import BodyIndex, owner_of

    main = Body("PartBody", ["PAD"], ["SKETCH"])
    tool = Body("TOOL", ["TOOL_PAD"], ["TOOL_SKETCH"])
    index = BodyIndex(_PartWithBodies([main, tool]))
    owner, name, feature = owner_of(_wrapper_chain("SKETCH"), index)
    assert owner is main and name == "PartBody" and feature == "SKETCH"
    assert owner_of(_wrapper_chain("TOOL_SKETCH"), index)[1] == "TOOL"


def test_owner_stays_unknown_when_the_name_is_ambiguous_or_absent() -> None:
    from auto_3dx.geometry._topology_search import BodyIndex, owner_of

    index = BodyIndex(
        _PartWithBodies([Body("A", ["Sketch.1"], []), Body("B", [], ["Sketch.1"])])
    )
    assert owner_of(_wrapper_chain("Sketch.1"), index) == (None, None, "Sketch.1")
    assert owner_of(_wrapper_chain("Missing"), index) == (None, None, "Missing")
    assert owner_of(_wrapper_chain("Sketch.1")) == (None, None, "Sketch.1")


def test_an_unreadable_part_leaves_the_owner_unknown() -> None:
    from auto_3dx.geometry._topology_search import BodyIndex, owner_of

    class _Broken:
        @property
        def Bodies(self) -> Any:  # noqa: N802 - COM spelling
            raise _com_error()

    assert owner_of(_wrapper_chain("PAD"), BodyIndex(_Broken()))[:2] == (None, None)
