"""Tests for plane removal and for reaching the plane collection from a Part.

Creating model content with no way to remove it is incomplete, and it is worse
than usual here: an angled plane leaves two points and a line behind as separate
hybrid shapes, so deleting the plane alone is not enough to put a model back the
way it was. Both removal paths are pinned here.
"""

from typing import Any

import pytest

from auto_3dx.core.part import Part
from auto_3dx.errors import Auto3dxError, ParameterTypeError
from auto_3dx.geometry.planes import GEOMETRICAL_SET_NAME, Plane, PlaneCollection


class _NoSaveOrUpdate:
    """Base fake that fails the test if a forbidden method is ever called."""

    def Update(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("Update() must never be called by the plane layer.")

    def Save(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("Save() must never be called.")

    def PLMPropagate(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("PLMPropagate() must never be called.")


class _Body(_NoSaveOrUpdate):
    """Fake `Body`, used only as the in-work object to reclaim."""

    def __init__(self) -> None:
        self.Name = "PartBody"


class _Collection:
    """Fake 1-based COM collection."""

    def __init__(self, items: "list[Any]") -> None:
        self._items = items

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self._items)

    def Item(self, index: int) -> Any:  # noqa: N802 - COM method name
        return self._items[index - 1]


class _HybridBody(_NoSaveOrUpdate):
    """Fake geometrical set."""

    def __init__(self) -> None:
        self.Name = "GeometricalSet.1"
        self.appended: list[Any] = []

    def AppendHybridShape(self, shape: Any) -> None:  # noqa: N802 - COM method name
        self.appended.append(shape)

    @property
    def HybridShapes(self) -> _Collection:  # noqa: N802 - COM property name
        return _Collection(self.appended)


class _HybridBodies:
    """Fake `Part.HybridBodies`: created sets are also findable by `Count`/`Item`."""

    def __init__(self) -> None:
        self.created: list[_HybridBody] = []

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self.created)

    def Item(self, index: int) -> _HybridBody:  # noqa: N802 - COM method name
        return self.created[index - 1]

    def Add(self) -> _HybridBody:  # noqa: N802 - COM method name
        hybrid_body = _HybridBody()
        self.created.append(hybrid_body)
        return hybrid_body


class HybridShapePlaneOffset(_NoSaveOrUpdate):
    """Fake hybrid plane shape; the class name is the kind CATIA reports."""

    def __init__(self, name: str = "PLANE") -> None:
        self.Name = name


class _HybridShapeFactory:
    """Fake `HybridShapeFactory`, returning a shape for every plane request."""

    def AddNewPlaneOffset(  # noqa: N802 - COM method name
        self, iPlane: Any, iOffset: float, iOrientation: bool  # noqa: N803
    ) -> HybridShapePlaneOffset:
        return HybridShapePlaneOffset("OFFSET")


class _OriginElements:
    """Fake `Part.OriginElements`."""

    def __init__(self) -> None:
        self.PlaneXY = object()
        self.PlaneYZ = object()
        self.PlaneZX = object()


class _Part(_NoSaveOrUpdate):
    """Fake `Part` exposing everything the plane collection reads."""

    def __init__(self) -> None:
        self.MainBody = _Body()
        self.HybridBodies = _HybridBodies()
        self.HybridShapeFactory = _HybridShapeFactory()
        self.OriginElements = _OriginElements()
        self.InWorkObject: Any = self.MainBody
        self.Name = "3D Shape1"


class _Selection:
    """Fake `Editor.Selection` recording the Clear/Add/Delete deletion sequence.

    Given the `_Part`, `Delete` really removes the object from it: the plane layer
    now finds its geometrical set by enumerating the Part, so a fake that only
    records the call would still report a deleted set as present.
    """

    def __init__(self, part: "Any | None" = None) -> None:
        self.calls: list[str] = []
        self.added: list[Any] = []
        self._part = part

    def Clear(self) -> None:  # noqa: N802 - COM method name
        self.calls.append("Clear")

    def Add(self, item: Any) -> None:  # noqa: N802 - COM method name
        self.calls.append("Add")
        self.added.append(item)

    def Delete(self) -> None:  # noqa: N802 - COM method name
        self.calls.append("Delete")
        if self._part is None:
            return
        for item in self.added:
            if item in self._part.HybridBodies.created:
                self._part.HybridBodies.created.remove(item)


def test_remove_deletes_the_plane_through_the_selection() -> None:
    """Deletion goes through the editor's Selection, as it does everywhere here."""
    part = _Part()
    selection = _Selection()
    planes = PlaneCollection(part, selection)
    plane = planes.create_offset("P", "XY", 30.0)

    planes.remove(plane)

    assert selection.added == [plane.com_object]
    assert selection.calls == ["Clear", "Add", "Delete", "Clear"]


def test_remove_reclaims_the_body_afterwards() -> None:
    """Deleting from a geometrical set leaves it in work, same as appending does."""
    part = _Part()
    planes = PlaneCollection(part, _Selection())
    plane = planes.create_offset("P", "XY", 30.0)
    part.InWorkObject = part.HybridBodies.created[0]

    planes.remove(plane)

    assert part.InWorkObject is part.MainBody


def test_remove_refuses_something_that_is_not_a_plane() -> None:
    """A wrong argument is rejected before it can reach the Selection."""
    selection = _Selection()
    planes = PlaneCollection(_Part(), selection)

    with pytest.raises(ParameterTypeError):
        planes.remove("not a plane")
    assert selection.calls == []


def test_remove_without_a_selection_is_an_auto3dx_error() -> None:
    """A Part built without an editor cannot delete, and says so."""
    planes = PlaneCollection(_Part())
    plane = planes.create_offset("P", "XY", 30.0)

    with pytest.raises(Auto3dxError):
        planes.remove(plane)


def test_remove_geometrical_set_leaves_no_set_behind_for_the_next_create() -> None:
    """After removal the Part has no such set, so a later create builds a fresh one."""
    part = _Part()
    selection = _Selection(part)
    planes = PlaneCollection(part, selection)
    planes.create_offset("P", "XY", 30.0)
    created_set = part.HybridBodies.created[0]
    assert part.HybridBodies.Count == 1

    planes.remove_geometrical_set()
    assert selection.added == [created_set]
    assert part.HybridBodies.Count == 0
    assert planes.names() == []

    planes.create_offset("Q", "XY", 30.0)
    assert part.HybridBodies.Count == 1
    assert part.HybridBodies.created[0] is not created_set
    assert planes.names() == ["Q"]


def test_remove_geometrical_set_does_nothing_when_none_was_created() -> None:
    """Safe to call in a `finally` before anything has been built."""
    selection = _Selection()
    planes = PlaneCollection(_Part(), selection)

    planes.remove_geometrical_set()

    assert selection.calls == []


def test_the_geometrical_set_is_named_for_this_library() -> None:
    """A set appearing in someone's tree should say where it came from."""
    part = _Part()
    planes = PlaneCollection(part, _Selection())
    planes.create_offset("P", "XY", 30.0)

    assert part.HybridBodies.created[0].Name == GEOMETRICAL_SET_NAME
    assert "auto_3dx" in GEOMETRICAL_SET_NAME


def test_part_exposes_a_cached_plane_collection() -> None:
    """One collection per Part: a second would create a second geometrical set."""
    part = Part(_Part(), selection=_Selection())

    first = part.planes
    second = part.planes

    assert isinstance(first, PlaneCollection)
    assert first is second


def test_part_gives_the_plane_collection_its_selection() -> None:
    """Without the wiring, removal would fail on a Part obtained the normal way."""
    raw_part = _Part()
    selection = _Selection()
    part = Part(raw_part, selection=selection)

    plane = part.planes.create_offset("P", "XY", 30.0)
    part.planes.remove(plane)

    assert selection.added == [plane.com_object]


def test_a_plane_wrapper_exposes_its_raw_shape() -> None:
    """`Sketches.Add` takes the raw hybrid shape, so it has to be reachable."""
    planes = PlaneCollection(_Part(), _Selection())

    plane = planes.create_offset("P", "XY", 30.0)

    assert isinstance(plane, Plane)
    assert isinstance(plane.com_object, HybridShapePlaneOffset)
