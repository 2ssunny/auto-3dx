"""Tests for Multi-Body support: bodies, the work-in-body context, visibility, the guard.

The fakes behave as probe 41 measured the live model (`docs/conventions.md` 1.9):

    Part.Bodies.Add()           -> a Body named "Body.N" that becomes the In-Work Object
    Body.Sketches.Add(plane)    -> a sketch in THAT body
    ShapeFactory.AddNewPad/Pocket -> a feature in the In-Work Body, which then becomes the
                                   In-Work Object
    Selection.VisProperties     -> SetShow(0/1) on the selected objects, GetShow() -> (0, s)
    Selection.Delete() on a body -> the body goes, with everything in it
    Part.Application.ActiveEditor.ActiveObject == Part only for the active Part

`Part.Update`/`Save` raise, so nothing here may rebuild or save.
"""

from typing import Any

import pytest
import pywintypes

from auto_3dx.core.part import Part
from auto_3dx.errors import (
    AmbiguousNameError,
    AutomationError,
    BodyAlreadyExistsError,
    BodyNotFoundError,
    BodyRemovalError,
    FeatureNotFoundError,
    InactivePartError,
    ParameterNameError,
    ParameterTypeError,
    PartialCreationError,
)
from auto_3dx.geometry._topology_search import search_references
from auto_3dx.geometry.bodies import Body
from auto_3dx.geometry.deletion import delete_via_selection, require_active_part
from auto_3dx.geometry.edges import EDGE_SEARCH_QUERY

SHOW, NO_SHOW = 0, 1
PAD_HEIGHT = 10.0
E_FAIL = -2147467259


def _com_error() -> pywintypes.com_error:
    return pywintypes.com_error(
        -2147352567,
        "Exception occurred.",
        (0, "CATIA", "failed", None, 0, E_FAIL),
        None,
    )


class _Items:
    """Fake 1-based COM collection."""

    def __init__(self) -> None:
        self.items: list[Any] = []

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self.items)

    def Item(self, index: int) -> Any:  # noqa: N802 - COM method name
        return self.items[index - 1]


class Sketch:
    """Fake raw `Sketch`."""

    def __init__(self, name: str, plane: Any) -> None:
        self.Name = name
        self.plane = plane


class _Sketches(_Items):
    """Fake `Body.Sketches`: `Add` lands in this body, as probe 41 measured."""

    def Add(self, plane: Any) -> Sketch:  # noqa: N802 - COM method name
        sketch = Sketch(f"Sketch.{len(self.items) + 1}", plane)
        self.items.append(sketch)
        return sketch


class Pad:
    def __init__(self, name: str, sketch: Any) -> None:
        self.Name = name
        self.sketch = sketch


class Pocket(Pad):
    pass


class _RawBody:
    """Fake raw `Body`."""

    def __init__(self, name: str) -> None:
        self.Name = name
        self.Shapes = _Items()
        self.Sketches = _Sketches()
        self.HybridBodies = _Items()


class _Bodies(_Items):
    def __init__(self, part: "_Part") -> None:
        super().__init__()
        self._part = part
        self.add_calls = 0

    def Add(self) -> _RawBody:  # noqa: N802 - COM method name
        self.add_calls += 1
        body = _RawBody(f"Body.{len(self.items) + 1}")
        self.items.append(body)
        self._part._in_work = body  # CATIA makes the new body the In-Work Object
        return body


class _ShapeFactory:
    """Builds features in the In-Work Body, then makes the feature the In-Work Object."""

    def __init__(self, part: "_Part") -> None:
        self._part = part
        self.calls: list[tuple[str, Any]] = []

    def _add(self, kind: type, sketch: Any) -> Any:
        body = self._part.body_of(self._part._in_work)
        self.calls.append((kind.__name__, body))
        feature = kind(f"{kind.__name__}.{len(body.Shapes.items) + 1}", sketch)
        body.Shapes.items.append(feature)
        self._part._in_work = feature
        return feature

    def AddNewPad(self, sketch: Any, height: float) -> Pad:  # noqa: N802 - COM method name
        return self._add(Pad, sketch)

    def AddNewPocket(self, sketch: Any, depth: float) -> Pocket:  # noqa: N802 - COM method
        return self._add(Pocket, sketch)


class _OriginElements:
    def __init__(self) -> None:
        self.PlaneXY = object()
        self.PlaneYZ = object()
        self.PlaneZX = object()


class _Editor:
    def __init__(self, active_object: Any) -> None:
        self.ActiveObject = active_object


class _Application:
    def __init__(self) -> None:
        self.ActiveEditor: Any = None


class _Part:
    """Fake CATIA `Part` with a main body, extra bodies and an In-Work Object."""

    def __init__(self, name: str = "3D Shape1", active: bool = True) -> None:
        self.Name = name
        self.MainBody = _RawBody("PartBody")
        self.Bodies = _Bodies(self)
        self.Bodies.items.append(self.MainBody)
        self.ShapeFactory = _ShapeFactory(self)
        self.OriginElements = _OriginElements()
        self._in_work: Any = self.MainBody
        self.in_work_writes: list[Any] = []
        self.in_work_write_error: BaseException | None = None
        self.Application = _Application()
        self.Application.ActiveEditor = _Editor(self if active else object())

    @property
    def InWorkObject(self) -> Any:  # noqa: N802 - COM property name
        return self._in_work

    @InWorkObject.setter
    def InWorkObject(self, value: Any) -> None:  # noqa: N802 - COM property name
        if self.in_work_write_error is not None:
            raise self.in_work_write_error
        self.in_work_writes.append(value)
        self._in_work = value

    def body_of(self, obj: Any) -> _RawBody:
        for body in self.Bodies.items:
            if obj is body or obj in body.Shapes.items or obj in body.Sketches.items:
                return body
        raise AssertionError("object is in no body")

    def Update(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("Nothing here may rebuild.")

    def Save(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("Nothing here may save.")


class _Selected:
    def __init__(self, value: Any) -> None:
        self.Value = value
        self.Reference = value


class _VisProperties:
    def __init__(self, selection: "_Selection") -> None:
        self._selection = selection

    def SetShow(self, state: int) -> None:  # noqa: N802 - COM method name
        for item in self._selection.items:
            self._selection.shown[id(item.Value)] = state

    def GetShow(self) -> "tuple[int, int]":  # noqa: N802 - COM method name
        first = self._selection.items[0].Value
        return (0, self._selection.shown.get(id(first), SHOW))


class _Selection:
    def __init__(self, part: _Part) -> None:
        self._part = part
        self.items: list[_Selected] = []
        self.shown: dict[int, Any] = {}
        self.calls: list[str] = []

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self.items)

    def Item(self, index: int) -> _Selected:  # noqa: N802 - COM method name
        return self.items[index - 1]

    def Clear(self) -> None:  # noqa: N802 - COM method name
        self.calls.append("Clear")
        self.items = []

    def Add(self, value: Any) -> None:  # noqa: N802 - COM method name
        self.calls.append("Add")
        self.items.append(_Selected(value))

    def Search(self, query: str) -> None:  # noqa: N802 - COM method name
        self.calls.append("Search")

    def Delete(self) -> None:  # noqa: N802 - COM method name
        self.calls.append("Delete")
        for item in self.items:
            if item.Value in self._part.Bodies.items:
                self._part.Bodies.items.remove(item.Value)

    @property
    def VisProperties(self) -> _VisProperties:  # noqa: N802 - COM property name
        return _VisProperties(self)


def _part(active: bool = True) -> "tuple[Part, _Part, _Selection]":
    raw = _Part(active=active)
    selection = _Selection(raw)
    return Part(raw, selection=selection), raw, selection


def _sketch_in(part: Part, name: str) -> Any:
    return part.sketches.create(name, support="XY")


# --- the body collection ----------------------------------------------------------------------


def test_the_main_body_is_listed_and_marked_by_identity() -> None:
    part, raw, _ = _part()

    bodies = part.bodies.list()

    assert [body.name for body in bodies] == ["PartBody"]
    assert bodies[0].is_main
    assert part.bodies.main.name == "PartBody"


def test_create_names_the_body_and_puts_the_previous_in_work_object_back() -> None:
    part, raw, _ = _part()
    generation = part.part_design.snapshot_generation

    body = part.bodies.create("LEDTray")

    assert isinstance(body, Body)
    assert body.name == "LEDTray"
    assert not body.is_main
    assert part.bodies.names() == ["PartBody", "LEDTray"]
    assert raw.InWorkObject is raw.MainBody
    assert part.part_design.snapshot_generation == generation + 1


def test_a_body_created_elsewhere_is_found_by_name() -> None:
    part, raw, _ = _part()
    raw.Bodies.items.append(_RawBody("FROM_ANOTHER_PROCESS"))

    assert part.bodies.get("FROM_ANOTHER_PROCESS").name == "FROM_ANOTHER_PROCESS"
    with pytest.raises(BodyNotFoundError, match="PartBody"):
        part.bodies.get("MISSING")
    raw.Bodies.items.append(_RawBody("FROM_ANOTHER_PROCESS"))
    with pytest.raises(AmbiguousNameError):
        part.bodies.get("FROM_ANOTHER_PROCESS")


def test_create_refuses_a_taken_or_unusable_name_before_catia_is_called() -> None:
    part, raw, _ = _part()
    part.bodies.create("LEDTray")

    with pytest.raises(BodyAlreadyExistsError):
        part.bodies.create("LEDTray")
    with pytest.raises(ParameterNameError):
        part.bodies.create("  ")
    assert raw.Bodies.add_calls == 1


def test_a_failed_rename_is_partial_and_still_restores_the_in_work_object() -> None:
    part, raw, _ = _part()

    class _UnrenamableBody:
        def __init__(self) -> None:
            self.Shapes, self.Sketches, self.HybridBodies = (
                _Items(),
                _Sketches(),
                _Items(),
            )

        @property
        def Name(self) -> str:  # noqa: N802 - COM property name
            return "Body.2"

        @Name.setter
        def Name(self, value: str) -> None:  # noqa: N802 - COM property name
            raise _com_error()

    def add_unrenamable() -> Any:
        body = _UnrenamableBody()
        raw.Bodies.items.append(body)
        raw._in_work = body
        return body

    raw.Bodies.Add = add_unrenamable  # type: ignore[method-assign]

    with pytest.raises(PartialCreationError, match="Body.2"):
        part.bodies.create("LEDTray")
    assert raw.InWorkObject is raw.MainBody


# --- working in a body ---------------------------------------------------------------------------


def test_work_in_targets_the_body_and_restores_the_in_work_object() -> None:
    part, raw, _ = _part()
    tray = part.bodies.create("LEDTray")

    with part.work_in(tray) as target:
        assert target.name == "LEDTray"
        assert raw.InWorkObject is tray.com_object

    assert raw.InWorkObject is raw.MainBody


def test_work_in_accepts_a_body_name() -> None:
    part, raw, _ = _part()
    part.bodies.create("LEDTray")

    with part.work_in("LEDTray"):
        assert raw.InWorkObject.Name == "LEDTray"
    assert raw.InWorkObject is raw.MainBody


def test_sketches_and_features_go_into_the_work_body_and_are_found_there() -> None:
    part, raw, _ = _part()
    tray = part.bodies.create("LEDTray")

    with part.work_in(tray):
        sketch = _sketch_in(part, "TRAY_SKETCH")
        part.part_design.create_pad("TRAY_PAD", sketch, PAD_HEIGHT)
        # The pad moved the In-Work Object; the next feature still goes to the body.
        pocket_sketch = _sketch_in(part, "TRAY_POCKET_SKETCH")
        part.part_design.create_pocket("TRAY_POCKET", pocket_sketch, PAD_HEIGHT)
        assert part.part_design.get_pad("TRAY_PAD").name == "TRAY_PAD"

    raw_tray = tray.com_object
    assert [item.Name for item in raw_tray.Shapes.items] == ["TRAY_PAD", "TRAY_POCKET"]
    assert [item.Name for item in raw_tray.Sketches.items] == [
        "TRAY_SKETCH",
        "TRAY_POCKET_SKETCH",
    ]
    assert raw.MainBody.Shapes.items == []
    assert raw.MainBody.Sketches.items == []
    assert [body for _, body in raw.ShapeFactory.calls] == [raw_tray, raw_tray]
    assert [f.name for f in tray.features] == ["TRAY_PAD", "TRAY_POCKET"]
    assert tray.sketch_names == ("TRAY_SKETCH", "TRAY_POCKET_SKETCH")
    with pytest.raises(FeatureNotFoundError):
        part.part_design.get_pad("TRAY_PAD")  # outside the block: the main body


def test_outside_work_in_nothing_touches_the_in_work_object() -> None:
    """Existing scripts keep exactly the behaviour they had."""
    part, raw, _ = _part()
    sketch = _sketch_in(part, "BASE_SKETCH")

    part.part_design.create_pad("BASE_PAD", sketch, PAD_HEIGHT)

    assert raw.in_work_writes == []
    assert [item.Name for item in raw.MainBody.Shapes.items] == ["BASE_PAD"]


def test_the_in_work_object_is_restored_when_the_block_raises() -> None:
    part, raw, _ = _part()
    tray = part.bodies.create("LEDTray")

    with pytest.raises(ParameterNameError):
        with part.work_in(tray):
            part.sketches.create("  ", support="XY")

    assert raw.InWorkObject is raw.MainBody


def test_nested_blocks_restore_in_order() -> None:
    part, raw, _ = _part()
    tray = part.bodies.create("LEDTray")
    floor = part.bodies.create("ElectronicsFloor")

    with part.work_in(tray):
        with part.work_in(floor):
            sketch = _sketch_in(part, "FLOOR_SKETCH")
            assert raw.InWorkObject is floor.com_object
        assert raw.InWorkObject is tray.com_object
    assert raw.InWorkObject is raw.MainBody
    assert floor.com_object.Sketches.items == [sketch.com_object]


def test_a_failed_restore_after_an_error_is_noted_not_substituted() -> None:
    part, raw, _ = _part()
    tray = part.bodies.create("LEDTray")

    with pytest.raises(ParameterNameError) as raised:
        with part.work_in(tray):
            raw.in_work_write_error = _com_error()
            part.sketches.create("  ", support="XY")

    assert any("could not be restored" in note for note in raised.value.__notes__)


def test_a_failed_restore_after_a_clean_block_raises() -> None:
    part, raw, _ = _part()
    tray = part.bodies.create("LEDTray")

    with pytest.raises(AutomationError, match="could not be restored"):
        with part.work_in(tray):
            raw.in_work_write_error = _com_error()


@pytest.mark.parametrize("target", [42, None])
def test_work_in_refuses_something_that_is_not_a_body(target: Any) -> None:
    part, raw, _ = _part()

    with pytest.raises(ParameterTypeError):
        with part.work_in(target):
            pass
    assert raw.in_work_writes == []


def test_work_in_refuses_a_body_of_another_part_and_a_missing_body() -> None:
    part, raw, _ = _part()
    other, _, _ = _part()
    foreign = other.bodies.create("Elsewhere")

    with pytest.raises(ParameterTypeError, match="another Part"):
        with part.work_in(foreign):
            pass
    with pytest.raises(BodyNotFoundError):
        with part.work_in("MISSING"):
            pass
    assert raw.InWorkObject is raw.MainBody


# --- visibility ------------------------------------------------------------------------------------


def test_hide_and_show_act_on_that_body_only_and_restore_the_selection() -> None:
    part, raw, selection = _part()
    tray = part.bodies.create("LEDTray")
    floor = part.bodies.create("ElectronicsFloor")
    user_pick = object()
    selection.items = [_Selected(user_pick)]
    generation = part.part_design.snapshot_generation

    tray.hide()

    assert tray.is_visible is False
    assert floor.is_visible is True
    tray.show()
    assert tray.is_visible is True
    assert [item.Value for item in selection.items] == [user_pick]
    assert part.part_design.snapshot_generation == generation + 2


def test_an_unknown_show_state_is_not_guessed() -> None:
    part, _, selection = _part()
    tray = part.bodies.create("LEDTray")
    selection.shown[id(tray.com_object)] = 7

    with pytest.raises(AutomationError, match="unknown state"):
        tray.is_visible  # noqa: B018 - the property read is the test


def test_visibility_is_refused_on_a_part_that_is_not_active() -> None:
    part, raw, selection = _part(active=False)
    raw.Bodies.items.append(_RawBody("LEDTray"))
    tray = part.bodies.get("LEDTray")

    with pytest.raises(InactivePartError):
        tray.hide()
    assert selection.calls == []


# --- removal -----------------------------------------------------------------------------------------


def test_the_main_body_is_never_removed() -> None:
    part, raw, selection = _part()

    with pytest.raises(BodyRemovalError, match="main body"):
        part.bodies.remove("PartBody", delete_contents=True)
    assert selection.calls == []


def test_a_body_with_content_is_removed_only_when_told() -> None:
    part, raw, selection = _part()
    tray = part.bodies.create("LEDTray")
    with part.work_in(tray):
        part.part_design.create_pad(
            "TRAY_PAD", _sketch_in(part, "TRAY_SKETCH"), PAD_HEIGHT
        )

    with pytest.raises(BodyRemovalError, match="1 features, 1 sketches"):
        part.bodies.remove("LEDTray")
    assert part.bodies.names() == ["PartBody", "LEDTray"]

    part.bodies.remove("LEDTray", delete_contents=True)
    assert part.bodies.names() == ["PartBody"]


def test_an_empty_body_is_removed_and_the_in_work_object_kept() -> None:
    part, raw, _ = _part()
    part.bodies.create("Empty")

    part.bodies.remove("Empty")

    assert part.bodies.names() == ["PartBody"]
    assert raw.InWorkObject is raw.MainBody


def test_a_body_without_geometrical_sets_reports_them_as_none() -> None:
    """Live, `Body.HybridBodies` is `None` for a body with no geometrical sets."""
    part, raw, _ = _part()
    tray = part.bodies.create("LEDTray")
    tray.com_object.HybridBodies = None
    with part.work_in(tray):
        part.part_design.create_pad(
            "TRAY_PAD", _sketch_in(part, "TRAY_SKETCH"), PAD_HEIGHT
        )

    with pytest.raises(BodyRemovalError, match="0 geometrical sets"):
        part.bodies.remove("LEDTray")
    part.bodies.remove("LEDTray", delete_contents=True)
    assert part.bodies.names() == ["PartBody"]


def test_removing_the_in_work_body_hands_the_in_work_object_to_the_main_body() -> None:
    part, raw, _ = _part()
    tray = part.bodies.create("LEDTray")
    raw._in_work = tray.com_object

    part.bodies.remove("LEDTray")

    assert raw.InWorkObject is raw.MainBody


def test_removal_is_refused_on_a_part_that_is_not_active() -> None:
    part, raw, selection = _part(active=False)
    raw.Bodies.items.append(_RawBody("LEDTray"))

    with pytest.raises(InactivePartError):
        part.bodies.remove("LEDTray")
    assert part.bodies.names() == ["PartBody", "LEDTray"]
    assert selection.calls == []


# --- the active-Part guard on Selection-based operations -------------------------------------------------


def test_the_guard_passes_the_active_part_and_refuses_another() -> None:
    require_active_part(_Part(active=True))
    with pytest.raises(InactivePartError, match="not the active Part"):
        require_active_part(_Part(active=False))


def test_the_guard_refuses_when_there_is_no_active_editor() -> None:
    raw = _Part()
    raw.Application.ActiveEditor = None

    with pytest.raises(InactivePartError):
        require_active_part(raw)


def test_the_guard_skips_objects_without_an_application() -> None:
    """Only a test double lacks `Application`; the check is skipped for it."""
    require_active_part(object())
    require_active_part(None)


def test_deletion_on_an_inactive_part_touches_no_selection() -> None:
    raw = _Part(active=False)
    selection = _Selection(raw)

    with pytest.raises(InactivePartError):
        delete_via_selection(selection, object(), "sketch 'X'", raw)
    assert selection.calls == []


def test_topology_search_on_an_inactive_part_touches_no_selection() -> None:
    raw = _Part(active=False)
    selection = _Selection(raw)

    with pytest.raises(InactivePartError):
        search_references(selection, EDGE_SEARCH_QUERY, raw)
    assert selection.calls == []


def test_part_topology_is_refused_when_the_part_is_not_active() -> None:
    part, _, selection = _part(active=False)

    with pytest.raises(InactivePartError):
        part.topology.edges()
    assert selection.calls == []


def test_inspection_reports_no_topology_for_a_part_that_is_not_active() -> None:
    """Counting through its editor would count the active Part, so no number is given."""
    part, _, selection = _part(active=False)

    assert part.inspect.topology() is None
    assert selection.calls == []
