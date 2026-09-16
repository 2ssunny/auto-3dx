"""Planes and their geometrical set are found in the live Part, not remembered.

The first live validation exposed the gap these tests pin: a `PlaneCollection`
kept the geometrical set it had created in an attribute, so a collection built in
a later process (or a second one in this process) could neither see the planes
already in the model nor clean them up, and would happily add a second set beside
the first. Discovery goes through `Part.HybridBodies` `Count`/`Item(i)` and the
set's `HybridShapes`, both live-verified (probe 38).
"""

from typing import Any

import pytest

from auto_3dx.errors import AmbiguousNameError, PlaneNotFoundError
from auto_3dx.geometry.planes import (
    GEOMETRICAL_SET_NAME,
    AnglePlane,
    OffsetPlane,
    PlaneCollection,
)

OFFSET_MM = 30.0


class _Collection:
    """Fake 1-based COM collection, as `HybridBodies` and `HybridShapes` are."""

    def __init__(self, items: "list[Any]") -> None:
        self._items = items

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self._items)

    def Item(self, index: int) -> Any:  # noqa: N802 - COM method name
        return self._items[index - 1]


class HybridShapePlaneOffset:
    """Fake offset plane; the class name is the kind CATIA reports."""

    def __init__(self, name: str, offset: float = OFFSET_MM) -> None:
        self.Name = name
        self.Offset = type("Value", (), {"Value": offset})()


class HybridShapePlaneAngle:
    """Fake angle plane."""

    def __init__(self, name: str) -> None:
        self.Name = name


class HybridShapePointCoord:
    """Fake axis point: in the set, but not a plane."""

    def __init__(self, name: str) -> None:
        self.Name = name


class HybridShapeLinePtPt:
    """Fake axis line: in the set, but not a plane."""

    def __init__(self, name: str) -> None:
        self.Name = name


class _HybridBody:
    """Fake geometrical set."""

    def __init__(self, name: str, shapes: "list[Any] | None" = None) -> None:
        self.Name = name
        self.appended: list[Any] = list(shapes or [])

    def AppendHybridShape(self, shape: Any) -> None:  # noqa: N802 - COM method name
        self.appended.append(shape)

    @property
    def HybridShapes(self) -> _Collection:  # noqa: N802 - COM property name
        return _Collection(self.appended)


class _HybridBodies:
    """Fake `Part.HybridBodies` that both creates and enumerates sets."""

    def __init__(self, existing: "list[_HybridBody] | None" = None) -> None:
        self.bodies: list[_HybridBody] = list(existing or [])
        self.add_calls = 0

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self.bodies)

    def Item(self, index: int) -> _HybridBody:  # noqa: N802 - COM method name
        return self.bodies[index - 1]

    def Add(self) -> _HybridBody:  # noqa: N802 - COM method name
        self.add_calls += 1
        body = _HybridBody("GeometricalSet.1")
        self.bodies.append(body)
        return body


class _OriginElements:
    def __init__(self) -> None:
        self.PlaneXY = object()
        self.PlaneYZ = object()
        self.PlaneZX = object()


class _ShapeFactory:
    def AddNewPlaneOffset(  # noqa: N802 - COM method name
        self, iPlane: Any, iOffset: float, iOrientation: bool  # noqa: N803
    ) -> HybridShapePlaneOffset:
        return HybridShapePlaneOffset("NEW_PLANE", iOffset)


class _Part:
    """Fake CATIA `Part` wired for `PlaneCollection`."""

    def __init__(self, hybrid_bodies: _HybridBodies) -> None:
        self.MainBody = object()
        self.OriginElements = _OriginElements()
        self.HybridBodies = hybrid_bodies
        self.HybridShapeFactory = _ShapeFactory()
        self.InWorkObject: Any = self.MainBody

    def Update(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("The plane layer must never rebuild.")

    def Save(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("Save() must never be called.")


class _Selection:
    """Fake editor `Selection` recording what was deleted."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.deleted: list[Any] = []

    def Clear(self) -> None:  # noqa: N802 - COM method name
        self.added = []

    def Add(self, com_object: Any) -> None:  # noqa: N802 - COM method name
        self.added.append(com_object)

    def Delete(self) -> None:  # noqa: N802 - COM method name
        self.deleted.extend(self.added)


def _populated_set() -> _HybridBody:
    """A set as an earlier process would have left it: two planes and an axis."""
    return _HybridBody(
        GEOMETRICAL_SET_NAME,
        [
            HybridShapePlaneOffset("TOP"),
            HybridShapePointCoord("TILT_AxisStart"),
            HybridShapePointCoord("TILT_AxisEnd"),
            HybridShapeLinePtPt("TILT_Axis"),
            HybridShapePlaneAngle("TILT"),
        ],
    )


def _collection(*bodies: _HybridBody) -> "tuple[PlaneCollection, _Part, _Selection]":
    hybrid_bodies = _HybridBodies(list(bodies))
    part = _Part(hybrid_bodies)
    selection = _Selection()
    return PlaneCollection(part, selection), part, selection


def test_list_finds_planes_created_before_this_collection_existed() -> None:
    planes, _, _ = _collection(_populated_set())

    found = planes.list()

    assert [plane.name for plane in found] == ["TOP", "TILT"]
    assert isinstance(found[0], OffsetPlane)
    assert isinstance(found[1], AnglePlane)


def test_list_skips_the_axis_points_and_line_of_an_angle_plane() -> None:
    """They live in the set but are not planes; `remove_geometrical_set` clears them."""
    planes, _, _ = _collection(_populated_set())

    assert [plane.name for plane in planes.list()] == ["TOP", "TILT"]


def test_names_matches_list_order() -> None:
    planes, _, _ = _collection(_populated_set())

    assert planes.names() == [plane.name for plane in planes.list()]


def test_list_is_empty_and_creates_nothing_when_the_set_is_absent() -> None:
    planes, part, _ = _collection()

    assert planes.list() == []
    assert planes.names() == []
    assert part.HybridBodies.add_calls == 0


def test_a_set_with_another_name_is_not_this_modules_set() -> None:
    planes, _, _ = _collection(_HybridBody("SomeoneElse", [HybridShapePlaneOffset("X")]))

    assert planes.names() == []


def test_get_returns_the_plane_and_reads_its_value() -> None:
    planes, _, _ = _collection(_populated_set())

    plane = planes.get("TOP")

    assert isinstance(plane, OffsetPlane)
    assert plane.offset == OFFSET_MM


def test_get_raises_plane_not_found_and_lists_what_is_there() -> None:
    planes, _, _ = _collection(_populated_set())

    with pytest.raises(PlaneNotFoundError, match="TOP"):
        planes.get("MISSING")


def test_get_refuses_to_guess_between_two_planes_of_one_name() -> None:
    planes, _, _ = _collection(
        _HybridBody(
            GEOMETRICAL_SET_NAME,
            [HybridShapePlaneOffset("DUPLICATE"), HybridShapePlaneOffset("DUPLICATE")],
        )
    )

    with pytest.raises(AmbiguousNameError):
        planes.get("DUPLICATE")


def test_two_sets_of_the_same_name_are_refused_rather_than_guessed() -> None:
    planes, _, _ = _collection(_populated_set(), _populated_set())

    with pytest.raises(AmbiguousNameError, match=GEOMETRICAL_SET_NAME):
        planes.list()


def test_creating_reuses_the_existing_set_instead_of_adding_a_second() -> None:
    """The lifecycle gap: a new collection used to add a set beside the old one."""
    planes, part, _ = _collection(_populated_set())

    planes.create_offset("ANOTHER", "XY", OFFSET_MM)

    assert part.HybridBodies.add_calls == 0
    assert part.HybridBodies.Count == 1
    assert planes.names() == ["TOP", "TILT", "ANOTHER"]


def test_creating_makes_the_set_once_and_finds_it_again_afterwards() -> None:
    planes, part, _ = _collection()

    planes.create_offset("FIRST", "XY", OFFSET_MM)
    planes.create_offset("SECOND", "XY", OFFSET_MM)

    assert part.HybridBodies.add_calls == 1
    assert planes.names() == ["FIRST", "SECOND"]


def test_remove_geometrical_set_removes_one_this_collection_never_created() -> None:
    existing = _populated_set()
    planes, part, selection = _collection(existing)

    planes.remove_geometrical_set()

    assert selection.deleted == [existing]
    assert part.InWorkObject is part.MainBody


def test_remove_geometrical_set_does_nothing_when_there_is_no_set() -> None:
    planes, _, selection = _collection()
    before = planes.snapshot_generation if hasattr(planes, "snapshot_generation") else None

    planes.remove_geometrical_set()

    assert selection.deleted == []
    assert before is None or before == 0


def test_lookup_is_read_only_and_does_not_advance_the_generation() -> None:
    from auto_3dx._generation import ModelGeneration

    generation = ModelGeneration()
    hybrid_bodies = _HybridBodies([_populated_set()])
    planes = PlaneCollection(_Part(hybrid_bodies), _Selection(), generation)

    planes.list()
    planes.names()
    planes.get("TOP")

    assert generation.value == 0


def test_found_planes_share_the_parts_generation() -> None:
    from auto_3dx._generation import ModelGeneration

    generation = ModelGeneration()
    hybrid_bodies = _HybridBodies([_populated_set()])
    planes = PlaneCollection(_Part(hybrid_bodies), _Selection(), generation)

    plane = planes.get("TOP")
    generation.advance()

    # The wrapper shares the counter, so it is refused by the same staleness rule
    # every other wrapper obeys rather than carrying a private one stuck at zero.
    assert plane._generation is generation
