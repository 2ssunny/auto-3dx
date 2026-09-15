"""Tests for `auto_3dx.geometry.planes` and its wiring into `SketchCollection`.

Fake COM objects are defined here rather than reused from `tests/conftest.py`:
this module needs a `Part` exposing `HybridBodies`/`HybridShapeFactory`/
`InWorkObject`, none of which the shared `conftest.Part` fake has, and the
existing fakes are shared, class-level objects that must not be mutated from
here. `type(obj).__name__` is not load-bearing anywhere in `planes.py` (it
never scans a collection by kind), so plain classes are enough.
"""

from typing import Any

import pytest

from auto_3dx.errors import (
    ParameterNameError,
    ParameterTypeError,
    PartialCreationError,
    UnsupportedSupportError,
)
from auto_3dx.geometry.planes import GEOMETRICAL_SET_NAME, AnglePlane, OffsetPlane, PlaneCollection
from auto_3dx.geometry.sketch import SUPPORT_XY, SketchCollection

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeOriginPlane:
    """A raw `OriginElements.Plane*` plane: just a `DisplayName`."""

    def __init__(self, display_name: str) -> None:
        self.DisplayName = display_name


class FakeOriginElements:
    """Fake CATIA `OriginElements`, exposing the three origin planes."""

    def __init__(self) -> None:
        self.PlaneXY = FakeOriginPlane("xy plane")
        self.PlaneYZ = FakeOriginPlane("yz plane")
        self.PlaneZX = FakeOriginPlane("zx plane")


class FakeDimensionValue:
    """Fake CATIA dimension-like object exposing a `.Value` (e.g. `Offset`/`Angle`)."""

    def __init__(self, value: float) -> None:
        self.Value = value


class FakeHybridShape:
    """A generic raw hybrid shape (point/line/plane) as returned by the factory.

    `Name` is a plain property (not `__setattr__` magic) so every rename is
    recorded, in order, in the shared `calls` log passed at construction.
    """

    def __init__(self, calls: "list[Any]") -> None:
        self._calls = calls
        self._name: str | None = None

    @property
    def Name(self) -> "str | None":
        return self._name

    @Name.setter
    def Name(self, value: str) -> None:
        self._calls.append(("set_shape_name", value))
        self._name = value


class FakePlaneOffsetShape(FakeHybridShape):
    """Fake `HybridShapePlaneOffset`."""

    def __init__(self, calls: "list[Any]", plane: Any, offset: float, orientation: bool) -> None:
        super().__init__(calls)
        self.Plane = plane
        self.Offset = FakeDimensionValue(offset)
        self.orientation_given = orientation


class FakePlaneAngleShape(FakeHybridShape):
    """Fake `HybridShapePlaneAngle`."""

    def __init__(
        self, calls: "list[Any]", plane: Any, axis: Any, angle: float, orientation: bool
    ) -> None:
        super().__init__(calls)
        self.Plane = plane
        self.axis = axis
        self.Angle = FakeDimensionValue(angle)
        self.orientation_given = orientation


class FakePointCoord(FakeHybridShape):
    """Fake `HybridShapePointCoord`."""

    def __init__(self, calls: "list[Any]", x: float, y: float, z: float) -> None:
        super().__init__(calls)
        self.x, self.y, self.z = x, y, z


class FakeLinePtPt(FakeHybridShape):
    """Fake `HybridShapeLinePtPt`."""

    def __init__(self, calls: "list[Any]", start: Any, end: Any) -> None:
        super().__init__(calls)
        self.start = start
        self.end = end


class FakeHybridShapeFactory:
    """Fake CATIA `HybridShapeFactory`. Every call is recorded in `calls`."""

    def __init__(self, calls: "list[Any]") -> None:
        self._calls = calls

    def AddNewPlaneOffset(self, plane: Any, offset: float, orientation: bool) -> Any:
        self._calls.append(("AddNewPlaneOffset", plane, offset, orientation))
        return FakePlaneOffsetShape(self._calls, plane, offset, orientation)

    def AddNewPlaneAngle(self, plane: Any, axis: Any, angle: float, orientation: bool) -> Any:
        self._calls.append(("AddNewPlaneAngle", plane, axis, angle, orientation))
        return FakePlaneAngleShape(self._calls, plane, axis, angle, orientation)

    def AddNewPointCoord(self, x: float, y: float, z: float) -> Any:
        self._calls.append(("AddNewPointCoord", x, y, z))
        return FakePointCoord(self._calls, x, y, z)

    def AddNewLinePtPt(self, start: Any, end: Any) -> Any:
        self._calls.append(("AddNewLinePtPt", start, end))
        return FakeLinePtPt(self._calls, start, end)


class FakeHybridBody:
    """Fake CATIA `HybridBody` (a geometrical set)."""

    def __init__(self, calls: "list[Any]") -> None:
        self._calls = calls
        self._name: str | None = None
        self.appended: "list[Any]" = []

    @property
    def Name(self) -> "str | None":
        return self._name

    @Name.setter
    def Name(self, value: str) -> None:
        self._calls.append(("set_hybrid_body_name", value))
        self._name = value

    def AppendHybridShape(self, shape: Any) -> None:
        self._calls.append(("AppendHybridShape", shape))
        self.appended.append(shape)


class FakeHybridBodies:
    """Fake CATIA `HybridBodies` collection: only `Add()` is used here."""

    def __init__(self, calls: "list[Any]") -> None:
        self._calls = calls
        self.bodies: "list[FakeHybridBody]" = []

    def Add(self) -> FakeHybridBody:
        self._calls.append(("HybridBodies.Add",))
        body = FakeHybridBody(self._calls)
        self.bodies.append(body)
        return body


class FakeSketch:
    """Fake CATIA `Sketch`, as returned by `Sketches.Add`."""

    def __init__(self, plane: Any) -> None:
        self.support_plane = plane
        self._name: str | None = None

    @property
    def Name(self) -> "str | None":
        return self._name

    @Name.setter
    def Name(self, value: str) -> None:
        self._name = value


class FakeSketches:
    """Fake CATIA `Sketches` collection. `Add` records the plane it was given."""

    def __init__(self, calls: "list[Any]") -> None:
        self._calls = calls
        self.items: "list[FakeSketch]" = []

    def Add(self, plane: Any) -> FakeSketch:
        self._calls.append(("Sketches.Add", plane))
        sketch = FakeSketch(plane)
        self.items.append(sketch)
        return sketch

    @property
    def Count(self) -> int:
        return len(self.items)

    def Item(self, index: int) -> FakeSketch:
        return self.items[index - 1]


class FakeMainBody:
    """Fake CATIA `Body` (`Part.MainBody`). Identity is what matters here."""

    def __init__(self, sketches: FakeSketches) -> None:
        self.Sketches = sketches


class FakePart:
    """Fake CATIA `Part`, wired for both `PlaneCollection` and `SketchCollection`.

    `Update`/`Save`/`PLMPropagate` all raise `AssertionError`: no code path in
    `planes.py` may call any of them, so a test wiring this fake in gets an
    immediate, loud failure the moment that rule is ever broken.
    """

    def __init__(self) -> None:
        self.calls: "list[Any]" = []
        self.OriginElements = FakeOriginElements()
        self.MainBody = FakeMainBody(FakeSketches(self.calls))
        self.HybridBodies = FakeHybridBodies(self.calls)
        self.HybridShapeFactory = FakeHybridShapeFactory(self.calls)
        self._in_work_object: Any = self.MainBody

    @property
    def InWorkObject(self) -> Any:
        return self._in_work_object

    @InWorkObject.setter
    def InWorkObject(self, value: Any) -> None:
        self.calls.append(("set_InWorkObject", value))
        self._in_work_object = value

    def Update(self) -> None:
        raise AssertionError("Part.Update must never be called by geometry.planes.")

    def Save(self) -> None:
        raise AssertionError("Part.Save must never be called by geometry.planes.")

    def PLMPropagate(self) -> None:
        raise AssertionError("Part.PLMPropagate must never be called by geometry.planes.")


@pytest.fixture
def part() -> FakePart:
    """Returns a fresh fake `Part` wired for the planes tests."""
    return FakePart()


# ---------------------------------------------------------------------------
# create_offset
# ---------------------------------------------------------------------------


def test_create_offset_passes_the_exact_factory_arguments(part: FakePart) -> None:
    collection = PlaneCollection(part)
    plane = collection.create_offset("MyOffset", SUPPORT_XY, 30.0, orientation=True)

    add_calls = [call for call in part.calls if call[0] == "AddNewPlaneOffset"]
    assert add_calls == [("AddNewPlaneOffset", part.OriginElements.PlaneXY, 30.0, True)]
    assert isinstance(plane, OffsetPlane)
    assert plane.name == "MyOffset"
    assert plane.offset == 30.0
    assert plane.base_display_name == "xy plane"


def test_create_offset_defaults_orientation_to_false(part: FakePart) -> None:
    collection = PlaneCollection(part)
    collection.create_offset("MyOffset", SUPPORT_XY, 30.0)

    add_calls = [call for call in part.calls if call[0] == "AddNewPlaneOffset"]
    assert add_calls == [("AddNewPlaneOffset", part.OriginElements.PlaneXY, 30.0, False)]


def test_create_offset_reclaims_the_body_after_every_append_in_order(part: FakePart) -> None:
    collection = PlaneCollection(part)
    plane = collection.create_offset("MyOffset", SUPPORT_XY, 30.0)

    hybrid_body = part.HybridBodies.bodies[0]
    raw_shape = plane.com_object
    assert part.calls == [
        ("HybridBodies.Add",),
        ("set_hybrid_body_name", GEOMETRICAL_SET_NAME),
        ("set_InWorkObject", part.MainBody),
        ("AddNewPlaneOffset", part.OriginElements.PlaneXY, 30.0, False),
        ("set_shape_name", "MyOffset"),
        ("AppendHybridShape", raw_shape),
        ("set_InWorkObject", part.MainBody),
    ]
    assert hybrid_body.appended == [raw_shape]


def test_create_offset_reuses_the_same_geometrical_set_across_calls(part: FakePart) -> None:
    collection = PlaneCollection(part)
    collection.create_offset("Offset1", SUPPORT_XY, 10.0)
    collection.create_offset("Offset2", "YZ", 20.0)

    add_body_calls = [call for call in part.calls if call[0] == "HybridBodies.Add"]
    assert len(add_body_calls) == 1
    assert len(part.HybridBodies.bodies) == 1
    assert part.HybridBodies.bodies[0].appended[0].Name == "Offset1"
    assert part.HybridBodies.bodies[0].appended[1].Name == "Offset2"


def test_create_offset_accepts_an_existing_plane_as_the_base(part: FakePart) -> None:
    collection = PlaneCollection(part)
    base = collection.create_offset("Base", SUPPORT_XY, 10.0)
    collection.create_offset("Derived", base, 5.0)

    add_calls = [call for call in part.calls if call[0] == "AddNewPlaneOffset"]
    # The second offset plane is built directly on the first plane's raw
    # hybrid shape, not on an origin plane -- proving support accepts a
    # previously created Plane, not just the three origin-plane strings.
    assert add_calls[1] == ("AddNewPlaneOffset", base.com_object, 5.0, False)


def test_create_offset_rejects_an_unsupported_support(part: FakePart) -> None:
    collection = PlaneCollection(part)
    with pytest.raises(UnsupportedSupportError):
        collection.create_offset("MyOffset", "DIAGONAL", 30.0)
    assert part.calls == []


def test_create_offset_rejects_a_non_plane_non_string_support(part: FakePart) -> None:
    collection = PlaneCollection(part)
    with pytest.raises(UnsupportedSupportError):
        collection.create_offset("MyOffset", 42, 30.0)
    assert part.calls == []


@pytest.mark.parametrize("bad_offset", [True, False, "30", None, float("inf"), float("nan")])
def test_create_offset_rejects_bad_offset_before_any_com_call(
    part: FakePart, bad_offset: Any
) -> None:
    collection = PlaneCollection(part)
    with pytest.raises(ParameterTypeError):
        collection.create_offset("MyOffset", SUPPORT_XY, bad_offset)
    assert part.calls == []


def test_create_offset_rejects_a_non_bool_orientation_before_any_com_call(
    part: FakePart,
) -> None:
    collection = PlaneCollection(part)
    with pytest.raises(ParameterTypeError):
        collection.create_offset("MyOffset", SUPPORT_XY, 30.0, orientation=1)
    assert part.calls == []


def test_create_offset_rejects_a_bad_name_before_any_com_call(part: FakePart) -> None:
    collection = PlaneCollection(part)
    with pytest.raises(ParameterNameError):
        collection.create_offset("  bad  ", SUPPORT_XY, 30.0)
    assert part.calls == []


def test_create_offset_wraps_a_partial_rename_failure(part: FakePart) -> None:
    part.HybridShapeFactory.AddNewPlaneOffset = lambda plane, offset, orientation: (
        FakeHybridShapeRaisingOnRename()
    )
    collection = PlaneCollection(part)
    with pytest.raises(PartialCreationError):
        collection.create_offset("MyOffset", SUPPORT_XY, 30.0)


class FakeHybridShapeRaisingOnRename:
    """A hybrid shape whose `Name` setter always raises a COM error."""

    @property
    def Name(self) -> None:
        return None

    @Name.setter
    def Name(self, value: str) -> None:
        raise _make_com_error()


def _make_com_error() -> Any:
    import pywintypes

    return pywintypes.com_error(
        -2147352567,
        "Exception occurred.",
        (0, "CATIAHybridShape", "The method Name failed", None, 0, -2147467259),
        None,
    )


# ---------------------------------------------------------------------------
# create_angle
# ---------------------------------------------------------------------------


def test_create_angle_passes_the_exact_factory_arguments(part: FakePart) -> None:
    collection = PlaneCollection(part)
    plane = collection.create_angle(
        "MyAngle", SUPPORT_XY, 30.0, (0.0, 0.0, 0.0), (0.0, 100.0, 0.0), orientation=True
    )

    point_calls = [call for call in part.calls if call[0] == "AddNewPointCoord"]
    line_calls = [call for call in part.calls if call[0] == "AddNewLinePtPt"]
    angle_calls = [call for call in part.calls if call[0] == "AddNewPlaneAngle"]

    assert point_calls == [
        ("AddNewPointCoord", 0.0, 0.0, 0.0),
        ("AddNewPointCoord", 0.0, 100.0, 0.0),
    ]
    assert len(line_calls) == 1
    _, start_point, end_point = line_calls[0]
    assert isinstance(start_point, FakePointCoord) and isinstance(end_point, FakePointCoord)
    axis_line = plane.com_object.axis
    assert angle_calls == [
        ("AddNewPlaneAngle", part.OriginElements.PlaneXY, axis_line, 30.0, True)
    ]
    assert isinstance(plane, AnglePlane)
    assert plane.name == "MyAngle"
    assert plane.angle == 30.0
    assert plane.base_display_name == "xy plane"


def test_create_angle_builds_the_axis_from_two_points_and_a_line(part: FakePart) -> None:
    collection = PlaneCollection(part)
    collection.create_angle(
        "MyAngle", SUPPORT_XY, 30.0, (0.0, 0.0, 0.0), (0.0, 100.0, 0.0)
    )

    kinds = [type(shape).__name__ for shape in part.HybridBodies.bodies[0].appended]
    assert kinds == [
        "FakePointCoord",
        "FakePointCoord",
        "FakeLinePtPt",
        "FakePlaneAngleShape",
    ]
    names = [shape.Name for shape in part.HybridBodies.bodies[0].appended]
    assert names == ["MyAngle_AxisStart", "MyAngle_AxisEnd", "MyAngle_Axis", "MyAngle"]


def test_create_angle_reclaims_the_body_after_every_append_in_order(part: FakePart) -> None:
    collection = PlaneCollection(part)
    collection.create_angle(
        "MyAngle", SUPPORT_XY, 30.0, (0.0, 0.0, 0.0), (0.0, 100.0, 0.0)
    )

    appended = part.HybridBodies.bodies[0].appended
    start_point, end_point, axis_line, angle_plane = appended
    assert part.calls == [
        ("HybridBodies.Add",),
        ("set_hybrid_body_name", GEOMETRICAL_SET_NAME),
        ("set_InWorkObject", part.MainBody),
        ("AddNewPointCoord", 0.0, 0.0, 0.0),
        ("set_shape_name", "MyAngle_AxisStart"),
        ("AppendHybridShape", start_point),
        ("set_InWorkObject", part.MainBody),
        ("AddNewPointCoord", 0.0, 100.0, 0.0),
        ("set_shape_name", "MyAngle_AxisEnd"),
        ("AppendHybridShape", end_point),
        ("set_InWorkObject", part.MainBody),
        ("AddNewLinePtPt", start_point, end_point),
        ("set_shape_name", "MyAngle_Axis"),
        ("AppendHybridShape", axis_line),
        ("set_InWorkObject", part.MainBody),
        ("AddNewPlaneAngle", part.OriginElements.PlaneXY, axis_line, 30.0, False),
        ("set_shape_name", "MyAngle"),
        ("AppendHybridShape", angle_plane),
        ("set_InWorkObject", part.MainBody),
    ]


@pytest.mark.parametrize("bad_angle", [True, "30", None, float("inf"), float("nan")])
def test_create_angle_rejects_bad_angle_before_any_com_call(
    part: FakePart, bad_angle: Any
) -> None:
    collection = PlaneCollection(part)
    with pytest.raises(ParameterTypeError):
        collection.create_angle(
            "MyAngle", SUPPORT_XY, bad_angle, (0.0, 0.0, 0.0), (0.0, 100.0, 0.0)
        )
    assert part.calls == []


@pytest.mark.parametrize(
    "bad_point",
    [(0.0, 0.0), (0.0, 0.0, "z"), [0.0, 0.0, 0.0, 0.0], "not a point", (0.0, True, 0.0)],
)
def test_create_angle_rejects_a_malformed_axis_point_before_any_com_call(
    part: FakePart, bad_point: Any
) -> None:
    collection = PlaneCollection(part)
    with pytest.raises(ParameterTypeError):
        collection.create_angle("MyAngle", SUPPORT_XY, 30.0, bad_point, (0.0, 100.0, 0.0))
    assert part.calls == []


def test_create_angle_rejects_a_non_bool_orientation_before_any_com_call(part: FakePart) -> None:
    collection = PlaneCollection(part)
    with pytest.raises(ParameterTypeError):
        collection.create_angle(
            "MyAngle",
            SUPPORT_XY,
            30.0,
            (0.0, 0.0, 0.0),
            (0.0, 100.0, 0.0),
            orientation="False",
        )
    assert part.calls == []


# ---------------------------------------------------------------------------
# No Update/Save/PLMPropagate on any path
# ---------------------------------------------------------------------------


def test_planes_never_call_update_save_or_plm_propagate(part: FakePart) -> None:
    collection = PlaneCollection(part)
    collection.create_offset("MyOffset", SUPPORT_XY, 30.0)
    collection.create_angle(
        "MyAngle", SUPPORT_XY, 30.0, (0.0, 0.0, 0.0), (0.0, 100.0, 0.0)
    )
    # FakePart.Update/Save/PLMPropagate all raise AssertionError if reached;
    # simply completing the two creations above without raising proves it.


# ---------------------------------------------------------------------------
# SketchCollection interop: a plane object alongside the existing strings
# ---------------------------------------------------------------------------


def test_sketch_create_still_accepts_an_origin_plane_string(part: FakePart) -> None:
    sketches = SketchCollection(part)
    sketch = sketches.create("S1", support=SUPPORT_XY)

    add_calls = [call for call in part.calls if call[0] == "Sketches.Add"]
    assert add_calls == [("Sketches.Add", part.OriginElements.PlaneXY)]
    assert sketch.name == "S1"


def test_sketch_create_accepts_an_offset_plane_and_passes_its_raw_shape(part: FakePart) -> None:
    planes = PlaneCollection(part)
    plane = planes.create_offset("MyOffset", SUPPORT_XY, 30.0)

    sketches = SketchCollection(part)
    sketch = sketches.create("S2", support=plane)

    add_calls = [call for call in part.calls if call[0] == "Sketches.Add"]
    assert add_calls == [("Sketches.Add", plane.com_object)]
    # The raw hybrid shape reached Sketches.Add, not the Plane wrapper and
    # not some Reference-like stand-in.
    assert add_calls[0][1] is plane.com_object
    assert sketch.name == "S2"


def test_sketch_create_accepts_an_angle_plane(part: FakePart) -> None:
    planes = PlaneCollection(part)
    plane = planes.create_angle(
        "MyAngle", SUPPORT_XY, 30.0, (0.0, 0.0, 0.0), (0.0, 100.0, 0.0)
    )

    sketches = SketchCollection(part)
    sketches.create("S3", support=plane)

    add_calls = [call for call in part.calls if call[0] == "Sketches.Add"]
    assert add_calls == [("Sketches.Add", plane.com_object)]


def test_sketch_create_rejects_an_unsupported_object_as_support(part: FakePart) -> None:
    sketches = SketchCollection(part)
    with pytest.raises(UnsupportedSupportError):
        sketches.create("S4", support=object())
