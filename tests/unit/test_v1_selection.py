"""v1 `part.selection`: the user's CATIA selection read into SDK wrappers, and highlighting.

The fakes follow probes 47a/47b: `Selection.Item(i).Type` names the kind ("...Edge",
"...Face", "Pad", "Sketch", "Part"); `.Reference` works for topology and features and fails
for a sketch; `.Value` works for all; `Selection.Add(reference)` selects exactly that edge.
Ownership is modelled with `Parent` chains ending in a `Body`, as probe 42 measured them.
"""

from typing import Any

import pytest

from auto_3dx._generation import ModelGeneration
from auto_3dx.core.part import Part
from auto_3dx.errors import (
    AutomationError,
    ParameterTypeError,
    SelectionCountError,
    SelectionOutsidePartError,
    SelectionTypeError,
    StaleSnapshotError,
    ValidationError,
)
from auto_3dx.geometry import (
    SELECTED_EDGE,
    SELECTED_FACE,
    SELECTED_FEATURE,
    SELECTED_PART,
    SELECTED_SKETCH,
    SELECTED_VERTEX,
    Edge,
    Face,
)
from auto_3dx.geometry.part_design import Pad as PadWrapper
from auto_3dx.geometry.selection import classify
from auto_3dx.geometry.sketch import Sketch as SketchWrapper
from tests.conftest import make_com_error
from tests.unit.test_phase4 import X, Y, _Editor, _line, _measurer, _plane_face


class _Items:
    def __init__(self, parent: Any = None) -> None:
        self.items: "list[Any]" = []
        self.Parent = parent

    @property
    def Count(self) -> int:  # noqa: N802
        return len(self.items)

    def Item(self, key: Any) -> Any:  # noqa: N802
        if isinstance(key, str):
            return next(item for item in self.items if item.Name == key)
        return self.items[key - 1]


class Body:  # noqa: N801 - CATIA's type name
    def __init__(self, name: str) -> None:
        self.Name = name
        self.Shapes = _Items(self)
        self.Sketches = _Items(self)


class Pad:  # noqa: N801
    def __init__(self, name: str, body: Body) -> None:
        self.Name = name
        self.Parent = body.Shapes
        body.Shapes.items.append(self)


class Sketch:  # noqa: N801
    def __init__(self, name: str, body: Body) -> None:
        self.Name = name
        self.Parent = body.Sketches
        body.Sketches.items.append(self)


class _RawPart:
    def __init__(self, name: str = "3D Shape1") -> None:
        self.Name = name
        self.Bodies = _Items(self)
        self.body = Body("PartBody")
        self.Bodies.items.append(self.body)
        self.MainBody = self.body
        self.pad = Pad("Pad.1", self.body)
        self.sketch = Sketch("Sketch.1", self.body)


def _topology(shape: Any, owner: Any) -> Any:
    shape.Parent = owner
    return shape


class _SelItem:
    def __init__(self, type_name: str, value: Any, reference: Any = None) -> None:
        self.Type = type_name
        self.Value = value
        self._reference = reference

    @property
    def Reference(self) -> Any:  # noqa: N802
        if self._reference is None:
            raise make_com_error()  # probe 47a: a sketch's Reference fails
        return self._reference


class _Selection:
    def __init__(self, items: "list[_SelItem] | None" = None) -> None:
        self.items = list(items or [])
        self.log: "list[str]" = []
        self.drop: "set[int]" = set()

    @property
    def Count(self) -> int:  # noqa: N802
        return len(self.items)

    def Item(self, position: int) -> _SelItem:  # noqa: N802
        return self.items[position - 1]

    def Clear(self) -> None:  # noqa: N802
        self.log.append("Clear")
        self.items = []

    def Add(self, value: Any) -> None:  # noqa: N802
        self.log.append("Add")
        if id(value) in self.drop:
            return  # CATIA dropping an item silently
        self.items.append(_SelItem("Added", value, value))


def _part(raw: _RawPart, selection: Any) -> Part:
    built = Part(raw, selection=selection, editor=_Editor())
    built._measurer = _measurer()  # the fake measurables, as in test_phase4
    return built


def _setup(items: "list[_SelItem] | None" = None) -> "tuple[Part, _RawPart, _Selection]":
    raw = _RawPart()
    selection = _Selection(items)
    return _part(raw, selection), raw, selection


def _edge_item(raw: _RawPart, start: Any = (-30, -20, 20), end: Any = (30, -20, 20)) -> _SelItem:
    return _SelItem("RectilinearTriDimFeatEdge", object(), _topology(_line(start, end), raw.pad))


def _face_item(raw: _RawPart) -> _SelItem:
    face = _topology(_plane_face(2400.0, (0, 0, 20), X, Y, origin=(0, 0, 20)), raw.pad)
    return _SelItem("PlanarFace", object(), face)


# --- classification ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("type_name", "kind"),
    [
        ("RectilinearTriDimFeatEdge", SELECTED_EDGE),
        ("CircularTriDimFeatEdge", SELECTED_EDGE),
        ("PlanarFace", SELECTED_FACE),
        ("CylindricalFace", SELECTED_FACE),
        ("TriDimFeatVertexOrBiDimFeatVertex", "vertex"),
        ("Pad", SELECTED_FEATURE),
        ("Hole", SELECTED_FEATURE),
        ("Sketch", SELECTED_SKETCH),
        ("Part", SELECTED_PART),
        ("Body", "body"),
        ("HybridShapePlaneOffset", "other"),
    ],
)
def test_a_selected_type_name_is_classified(type_name: str, kind: str) -> None:
    assert classify(type_name) == kind


# --- reading -------------------------------------------------------------------------------------


def test_the_one_selected_edge_is_an_ordinary_current_edge() -> None:
    raw = _RawPart()
    selection = _Selection([_edge_item(raw)])
    part = _part(raw, selection)

    edge = part.selection.one_edge()

    assert isinstance(edge, Edge)
    assert (edge.owner_body_name, edge.owner_feature_name, edge.from_sketch) == (
        "PartBody",
        "Pad.1",
        False,
    )
    assert edge.owner_body is raw.body
    assert edge._belongs_to(part._generation)
    assert edge.geometry.length_mm == pytest.approx(60.0)
    assert "line edge, length 60.000 mm" in part.selection.one().describe()


def test_reading_changes_neither_the_selection_nor_the_model() -> None:
    raw = _RawPart()
    selection = _Selection([_edge_item(raw)])
    part = _part(raw, selection)
    before = part._generation.value

    part.selection.items()
    part.selection.one_edge()
    assert len(part.selection) == 1

    assert selection.log == []
    assert part._generation.value == before


def test_a_selected_edge_goes_stale_like_any_snapshot_element() -> None:
    raw = _RawPart()
    part = _part(raw, _Selection([_edge_item(raw)]))
    edge = part.selection.one_edge()

    part._generation.advance()

    with pytest.raises(StaleSnapshotError):
        edge.geometry


def test_a_selected_face_feature_and_sketch_become_their_wrappers() -> None:
    part, raw, selection = _setup()
    selection.items = [_face_item(raw)]
    assert isinstance(part.selection.one_face(), Face)

    selection.items = [_SelItem("Pad", raw.pad, object())]
    feature = part.selection.one_feature()
    assert isinstance(feature, PadWrapper) and feature.name == "Pad.1"

    selection.items = [_SelItem("Sketch", raw.sketch)]
    sketch = part.selection.one_sketch()  # never reads Reference, which fails for a sketch
    assert isinstance(sketch, SketchWrapper) and sketch.name == "Sketch.1"


def test_nothing_or_several_selected_is_a_count_error() -> None:
    part, raw, selection = _setup()

    with pytest.raises(SelectionCountError) as nothing:
        part.selection.one_edge()
    assert nothing.value.count == 0

    selection.items = [_edge_item(raw), _edge_item(raw, (-30, 20, 20), (30, 20, 20))]
    with pytest.raises(SelectionCountError, match="2 are selected") as several:
        part.selection.one_edge()
    assert several.value.count == 2
    assert len(part.selection.edges()) == 2


def test_the_wrong_kind_is_a_type_error_that_names_what_was_selected() -> None:
    part, raw, selection = _setup()
    selection.items = [_face_item(raw)]

    with pytest.raises(SelectionTypeError, match="planar face") as caught:
        part.selection.one_edge()
    assert (caught.value.expected, caught.value.actual) == ("edge", ("face",))

    selection.items = [_edge_item(raw), _face_item(raw)]
    with pytest.raises(SelectionTypeError):
        part.selection.edges()


def test_unwrapped_kinds_are_reported_not_coerced() -> None:
    part, raw, selection = _setup()

    class Vertex:  # noqa: N801
        Name = "Vertex.1"

    selection.items = [_SelItem("TriDimFeatVertex", Vertex())]
    item = part.selection.one()
    assert (item.kind, item.element) == (SELECTED_VERTEX, None)
    with pytest.raises(SelectionTypeError):
        part.selection.one_edge()

    selection.items = [_SelItem("Part", raw)]
    assert part.selection.one().kind == SELECTED_PART


# --- ownership -----------------------------------------------------------------------------------


def test_an_edge_of_another_part_is_refused() -> None:
    part, _, selection = _setup()
    stranger = _RawPart("3D Shape2")
    selection.items = [_edge_item(stranger)]

    with pytest.raises(SelectionOutsidePartError, match="3D Shape1"):
        part.selection.one_edge()


def test_a_feature_of_another_part_is_refused_even_with_the_same_name() -> None:
    part, _, selection = _setup()
    stranger = _RawPart("3D Shape2")
    selection.items = [_SelItem("Pad", stranger.pad, object())]  # also named "Pad.1"

    with pytest.raises(SelectionOutsidePartError):
        part.selection.one_feature()


def test_the_selected_part_must_be_this_part() -> None:
    part, _, selection = _setup()
    selection.items = [_SelItem("Part", _RawPart("3D Shape2"))]

    with pytest.raises(SelectionOutsidePartError):
        part.selection.items()


def test_a_broken_parent_chain_is_resolved_by_identity_not_by_name() -> None:
    part, raw, selection = _setup()

    class AnyObject:  # noqa: N801 - the generic wrapper seen live for consumed sketches
        Parent = None

    raw.sketch.Parent = AnyObject()
    selection.items = [_SelItem("Sketch", raw.sketch)]
    assert part.selection.one_sketch().name == "Sketch.1"

    impostor = Sketch("Sketch.1", Body("Elsewhere"))
    impostor.Parent = AnyObject()
    selection.items = [_SelItem("Sketch", impostor)]
    with pytest.raises(SelectionOutsidePartError):
        part.selection.one_sketch()


# --- highlighting --------------------------------------------------------------------------------


def _snapshot_edge(part: Part, raw: _RawPart) -> Edge:
    return Edge(
        _topology(_line((0, 0, 0), (0, 0, 20)), raw.pad),
        1,
        part._generation.value,
        owner_body=raw.body,
        model_generation=part._generation,
    )


def test_set_highlights_exactly_the_elements_without_touching_the_model() -> None:
    part, raw, selection = _setup([_face_item(_RawPart())])
    edge = _snapshot_edge(part, raw)
    before = part._generation.value

    part.selection.set(edge, part.part_design.get_pad("Pad.1"))

    assert selection.log == ["Clear", "Add", "Add"]
    assert [item.Value for item in selection.items] == [edge.com_object, raw.pad]
    assert part._generation.value == before


def test_add_reports_an_item_catia_dropped() -> None:
    part, raw, selection = _setup()
    edge = _snapshot_edge(part, raw)
    selection.drop.add(id(edge.com_object))

    with pytest.raises(AutomationError, match="0 of the 1"):
        part.selection.add(edge)


def test_nothing_is_cleared_when_an_element_is_refused() -> None:
    part, raw, selection = _setup([_face_item(_RawPart())])
    edge = _snapshot_edge(part, raw)
    foreign = Edge(_line((0, 0, 0), (1, 0, 0)), 1, 0, model_generation=ModelGeneration())
    part._generation.advance()

    with pytest.raises(StaleSnapshotError):
        part.selection.set(edge)
    with pytest.raises(ValidationError, match="another Part"):
        part.selection.set(foreign)
    with pytest.raises(ParameterTypeError):
        part.selection.set("Pad.1")
    assert selection.log == []
    assert len(selection.items) == 1


def test_clear_deselects_everything() -> None:
    part, raw, selection = _setup([_edge_item(_RawPart())])

    part.selection.clear()

    assert selection.items == [] and selection.log == ["Clear"]


def test_there_is_no_selection_without_an_editor_selection() -> None:
    part = Part(_RawPart())

    with pytest.raises(ValidationError):
        part.selection.items()
