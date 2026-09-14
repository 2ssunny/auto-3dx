"""Tests that `geometry.planes` advances a shared `ModelGeneration` correctly.

Fake COM objects are copied (trimmed to what these tests exercise) from
`tests/unit/test_user_planes.py` rather than imported from it or from
`tests/conftest.py`: this module needs a `Part` exposing `HybridBodies`/
`HybridShapeFactory`/`InWorkObject`, none of which the shared `conftest.Part`
fake has, and `test_user_planes.py`'s fakes are internal to that module.

Pins (see the module docstring in `src/auto_3dx/geometry/planes.py` and
`docs/api-design.md` section 5):
    - `create_offset`, `create_angle`, `remove` and `remove_geometrical_set`
      each advance a shared generation by exactly one.
    - A validation failure before any COM call does not advance it.
    - An operation that raises part way through a multi-COM-call sequence
      still advances it exactly once.
    - `remove_geometrical_set` with nothing created touches no COM and does
      not advance it.
    - Every plane wrapper `PlaneCollection` returns shares its generation
      object with the collection.
    - The In-Work Object reclaim sequence is unchanged (already asserted by
      `test_user_planes.py`/`test_plane_removal.py`; this module does not
      duplicate that, only confirms nothing here broke it).
"""

from typing import Any

import pytest

from auto_3dx._generation import ModelGeneration
from auto_3dx.errors import (
    Auto3dxError,
    ParameterNameError,
    ParameterTypeError,
    PartialCreationError,
    UnsupportedSupportError,
)
from auto_3dx.geometry.planes import AnglePlane, OffsetPlane, PlaneCollection

# ---------------------------------------------------------------------------
# Fakes (trimmed copy of tests/unit/test_user_planes.py's fakes)
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
    """A generic raw hybrid shape (point/line/plane) as returned by the factory."""

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


class FakePlaneAngleShape(FakeHybridShape):
    """Fake `HybridShapePlaneAngle`."""

    def __init__(
        self, calls: "list[Any]", plane: Any, axis: Any, angle: float, orientation: bool
    ) -> None:
        super().__init__(calls)
        self.Plane = plane
        self.axis = axis
        self.Angle = FakeDimensionValue(angle)


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


class FakeMainBody:
    """Fake CATIA `Body` (`Part.MainBody`). Identity is what matters here."""


class FakePart:
    """Fake CATIA `Part`, wired for `PlaneCollection` only.

    `Update`/`Save`/`PLMPropagate` all raise `AssertionError`: no code path in
    `planes.py` may call any of them.
    """

    def __init__(self) -> None:
        self.calls: "list[Any]" = []
        self.OriginElements = FakeOriginElements()
        self.MainBody = FakeMainBody()
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


class FakeSelection:
    """Fake `Editor.Selection` recording the Clear/Add/Delete deletion sequence."""

    def __init__(self) -> None:
        self.calls: "list[str]" = []
        self.added: "list[Any]" = []

    def Clear(self) -> None:
        self.calls.append("Clear")

    def Add(self, item: Any) -> None:
        self.calls.append("Add")
        self.added.append(item)

    def Delete(self) -> None:
        self.calls.append("Delete")


class FakeHybridShapeRaisingOnRename:
    """A hybrid shape whose `Name` setter always raises a COM error, used to

    prove a mid-operation failure still advances the generation exactly once.
    """

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


@pytest.fixture
def part() -> FakePart:
    """Returns a fresh fake `Part` wired for the plane-generation tests."""
    return FakePart()


@pytest.fixture
def generation() -> ModelGeneration:
    """Returns a fresh, standalone `ModelGeneration` to pass into a collection."""
    return ModelGeneration()


# ---------------------------------------------------------------------------
# create_offset
# ---------------------------------------------------------------------------


def test_create_offset_advances_the_generation_by_exactly_one(
    part: FakePart, generation: ModelGeneration
) -> None:
    collection = PlaneCollection(part, generation=generation)

    collection.create_offset("MyOffset", "XY", 30.0)

    assert generation.value == 1


def test_create_offset_shares_the_generation_with_its_returned_plane(
    part: FakePart, generation: ModelGeneration
) -> None:
    collection = PlaneCollection(part, generation=generation)

    plane = collection.create_offset("MyOffset", "XY", 30.0)

    assert isinstance(plane, OffsetPlane)
    assert plane._generation is generation


def test_create_offset_validation_failure_does_not_advance_the_generation(
    part: FakePart, generation: ModelGeneration
) -> None:
    collection = PlaneCollection(part, generation=generation)

    with pytest.raises(ParameterNameError):
        collection.create_offset("  bad  ", "XY", 30.0)
    with pytest.raises(ParameterTypeError):
        collection.create_offset("MyOffset", "XY", True)
    with pytest.raises(UnsupportedSupportError):
        collection.create_offset("MyOffset", "DIAGONAL", 30.0)

    assert generation.value == 0
    assert part.calls == []


def test_create_offset_advances_once_even_when_the_rename_fails_part_way_through(
    part: FakePart, generation: ModelGeneration
) -> None:
    part.HybridShapeFactory.AddNewPlaneOffset = lambda plane, offset, orientation: (
        FakeHybridShapeRaisingOnRename()
    )
    collection = PlaneCollection(part, generation=generation)

    with pytest.raises(PartialCreationError):
        collection.create_offset("MyOffset", "XY", 30.0)

    assert generation.value == 1


def test_create_offset_advances_a_generation_shared_across_multiple_calls(
    part: FakePart, generation: ModelGeneration
) -> None:
    collection = PlaneCollection(part, generation=generation)

    collection.create_offset("Offset1", "XY", 10.0)
    collection.create_offset("Offset2", "YZ", 20.0)

    assert generation.value == 2


# ---------------------------------------------------------------------------
# create_angle
# ---------------------------------------------------------------------------


def test_create_angle_advances_the_generation_by_exactly_one_despite_many_com_calls(
    part: FakePart, generation: ModelGeneration
) -> None:
    collection = PlaneCollection(part, generation=generation)

    collection.create_angle(
        "MyAngle", "XY", 30.0, (0.0, 0.0, 0.0), (0.0, 100.0, 0.0)
    )

    # Four AddNew* calls plus four renames/appends happened, all as one
    # logical model change.
    add_new_calls = [
        call
        for call in part.calls
        if call[0] in ("AddNewPointCoord", "AddNewLinePtPt", "AddNewPlaneAngle")
    ]
    assert len(add_new_calls) == 4
    assert generation.value == 1


def test_create_angle_shares_the_generation_with_its_returned_plane(
    part: FakePart, generation: ModelGeneration
) -> None:
    collection = PlaneCollection(part, generation=generation)

    plane = collection.create_angle(
        "MyAngle", "XY", 30.0, (0.0, 0.0, 0.0), (0.0, 100.0, 0.0)
    )

    assert isinstance(plane, AnglePlane)
    assert plane._generation is generation


def test_create_angle_validation_failure_does_not_advance_the_generation(
    part: FakePart, generation: ModelGeneration
) -> None:
    collection = PlaneCollection(part, generation=generation)

    with pytest.raises(ParameterTypeError):
        collection.create_angle(
            "MyAngle", "XY", True, (0.0, 0.0, 0.0), (0.0, 100.0, 0.0)
        )
    with pytest.raises(ParameterTypeError):
        collection.create_angle(
            "MyAngle", "XY", 30.0, (0.0, 0.0), (0.0, 100.0, 0.0)
        )

    assert generation.value == 0
    assert part.calls == []


def test_create_angle_advances_once_when_a_middle_step_raises_part_way_through(
    part: FakePart, generation: ModelGeneration
) -> None:
    # The axis line creation (the third of four AddNew* calls) fails; the two
    # points before it were already created in CATIA, so the model did change.
    def _raise_on_line(start: Any, end: Any) -> Any:
        raise _make_com_error()

    part.HybridShapeFactory.AddNewLinePtPt = _raise_on_line
    collection = PlaneCollection(part, generation=generation)

    with pytest.raises(Auto3dxError):
        collection.create_angle(
            "MyAngle", "XY", 30.0, (0.0, 0.0, 0.0), (0.0, 100.0, 0.0)
        )

    assert generation.value == 1


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


def test_remove_advances_the_generation_by_exactly_one(
    part: FakePart, generation: ModelGeneration
) -> None:
    selection = FakeSelection()
    collection = PlaneCollection(part, selection, generation=generation)
    plane = collection.create_offset("MyOffset", "XY", 30.0)
    assert generation.value == 1

    collection.remove(plane)

    assert generation.value == 2


def test_remove_rejecting_a_non_plane_does_not_advance_the_generation(
    part: FakePart, generation: ModelGeneration
) -> None:
    selection = FakeSelection()
    collection = PlaneCollection(part, selection, generation=generation)

    with pytest.raises(ParameterTypeError):
        collection.remove("not a plane")

    assert generation.value == 0
    assert selection.calls == []


# ---------------------------------------------------------------------------
# remove_geometrical_set
# ---------------------------------------------------------------------------


def test_remove_geometrical_set_advances_the_generation_by_exactly_one(
    part: FakePart, generation: ModelGeneration
) -> None:
    selection = FakeSelection()
    collection = PlaneCollection(part, selection, generation=generation)
    collection.create_offset("MyOffset", "XY", 30.0)
    assert generation.value == 1

    collection.remove_geometrical_set()

    assert generation.value == 2


def test_remove_geometrical_set_with_nothing_created_touches_no_com_and_does_not_advance(
    part: FakePart, generation: ModelGeneration
) -> None:
    selection = FakeSelection()
    collection = PlaneCollection(part, selection, generation=generation)

    collection.remove_geometrical_set()

    assert generation.value == 0
    assert part.calls == []
    assert selection.calls == []


# ---------------------------------------------------------------------------
# In-work-object discipline is unchanged
# ---------------------------------------------------------------------------


def test_create_offset_still_reclaims_the_main_body_in_the_same_order(
    part: FakePart, generation: ModelGeneration
) -> None:
    """Regression guard: threading a generation through must not disturb the

    In-Work Object sequence verified live (probe 36) -- a regression here
    would make every later Pad fail. `test_user_planes.py`'s equivalent test
    (without a generation) already pins this in full; this only confirms
    passing an explicit `generation` does not change the sequence.
    """
    collection = PlaneCollection(part, generation=generation)

    plane = collection.create_offset("MyOffset", "XY", 30.0)

    hybrid_body = part.HybridBodies.bodies[0]
    raw_shape = plane.com_object
    assert part.calls == [
        ("HybridBodies.Add",),
        ("set_hybrid_body_name", "auto_3dx_Planes"),
        ("set_InWorkObject", part.MainBody),
        ("AddNewPlaneOffset", part.OriginElements.PlaneXY, 30.0, False),
        ("set_shape_name", "MyOffset"),
        ("AppendHybridShape", raw_shape),
        ("set_InWorkObject", part.MainBody),
    ]
    assert hybrid_body.appended == [raw_shape]
