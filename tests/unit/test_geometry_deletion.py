"""Tests for deleting geometry through the editor's selection.

Neither `Body.Sketches` nor `Body.Shapes` exposes a `Remove` method -- verified
against the B428_Cloud type library and against a live session, where
`Shapes.Remove` raises `AttributeError`. Deletion therefore has to go through
`Editor.Selection` (`Clear` -> `Add` -> `Delete`), which is why the collections
are handed the editor's selection.

An earlier implementation called `Shapes.Remove(name)` by analogy with
`Parameters.Remove(name)`. No unit test covered deletion, so only the live
integration test caught it. These tests close that gap.
"""

from collections.abc import Callable
from typing import Any

import pytest

from auto_3dx.core.application import Catia
from auto_3dx.errors import Auto3dxError, FeatureNotFoundError, SketchNotFoundError
from auto_3dx.geometry.part_design import PartDesign
from auto_3dx.geometry.sketch import SketchCollection

SKETCH_NAME = "AUTO3DX_SKETCH"
PAD_NAME = "AUTO3DX_PAD"
RECT_WIDTH = 60.0
RECT_HEIGHT = 40.0
PAD_HEIGHT = 20.0


def test_sketches_fake_has_no_remove(
    sketches_factory: Callable[..., Any],
) -> None:
    """Pins the COM reality the deletion design is built on."""
    assert not hasattr(sketches_factory(), "Remove")


def test_shapes_fake_has_no_remove(shapes_factory: Callable[..., Any]) -> None:
    """Pins the COM reality that broke the first implementation."""
    assert not hasattr(shapes_factory(), "Remove")


def test_remove_sketch_uses_the_selection_sequence(
    part_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
) -> None:
    """Deletion must be Clear -> Add -> Delete on the raw sketch object."""
    part_com = part_factory()
    selection = selection_factory()
    sketches = SketchCollection(part_com, selection)
    created = sketches.create(SKETCH_NAME)

    sketches.remove(SKETCH_NAME)

    assert selection.calls[:3] == ["Clear", "Add", "Delete"]
    assert selection.deleted == [created.com_object]


def test_remove_sketch_clears_the_selection_afterwards(
    part_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
) -> None:
    """A left-over selection would widen the next delete."""
    selection = selection_factory()
    sketches = SketchCollection(part_factory(), selection)
    sketches.create(SKETCH_NAME)

    sketches.remove(SKETCH_NAME)

    assert selection.calls[-1] == "Clear"


def test_remove_sketch_without_a_selection_explains_itself(
    part_factory: Callable[..., Any],
) -> None:
    """A Part built without an editor selection cannot delete."""
    sketches = SketchCollection(part_factory())
    sketches.create(SKETCH_NAME)

    with pytest.raises(Auto3dxError) as caught:
        sketches.remove(SKETCH_NAME)

    assert "Selection" in str(caught.value)


def test_remove_sketch_reports_a_missing_name(
    part_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
) -> None:
    """A missing name is a lookup failure, not a deletion failure."""
    selection = selection_factory()
    sketches = SketchCollection(part_factory(), selection)

    with pytest.raises(SketchNotFoundError):
        sketches.remove("Nope")

    assert selection.calls == []


def test_remove_pad_uses_the_selection_sequence(
    part_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
) -> None:
    """Pads delete through the selection too, not through `Shapes.Remove`."""
    part_com = part_factory()
    selection = selection_factory()
    sketches = SketchCollection(part_com, selection)
    part_design = PartDesign(part_com, selection)
    sketch = sketches.create(SKETCH_NAME)
    with sketch.edit() as editor:
        editor.rectangle(RECT_WIDTH, RECT_HEIGHT)
    pad = part_design.create_pad(PAD_NAME, sketch, PAD_HEIGHT)
    selection.calls.clear()

    part_design.remove_pad(PAD_NAME)

    assert selection.calls[:3] == ["Clear", "Add", "Delete"]
    assert selection.deleted == [pad.com_object]


def test_remove_pad_without_a_selection_explains_itself(
    part_factory: Callable[..., Any],
) -> None:
    """Same failure mode as sketches, with the same actionable message."""
    part_com = part_factory()
    sketches = SketchCollection(part_com)
    part_design = PartDesign(part_com)
    sketch = sketches.create(SKETCH_NAME)
    part_design.create_pad(PAD_NAME, sketch, PAD_HEIGHT)

    with pytest.raises(Auto3dxError) as caught:
        part_design.remove_pad(PAD_NAME)

    assert "Selection" in str(caught.value)


def test_remove_pad_reports_a_missing_name(
    part_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
) -> None:
    """A missing pad name must not reach the selection."""
    selection = selection_factory()
    part_design = PartDesign(part_factory(), selection)

    with pytest.raises(FeatureNotFoundError):
        part_design.remove_pad("Nope")

    assert selection.calls == []


def test_failed_delete_is_converted_and_still_clears(
    part_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
    com_error_factory: Callable[[], BaseException],
) -> None:
    """A COM failure must surface as Auto3dxError and not leave a selection."""
    selection = selection_factory()
    selection.delete_exception = com_error_factory()
    sketches = SketchCollection(part_factory(), selection)
    sketches.create(SKETCH_NAME)

    with pytest.raises(Auto3dxError) as caught:
        sketches.remove(SKETCH_NAME)

    assert not isinstance(caught.value, SketchNotFoundError)
    assert selection.calls[-1] == "Clear"


def test_active_part_wires_the_editor_selection(
    application_factory: Callable[..., Any],
    editor_factory: Callable[..., Any],
    part_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
) -> None:
    """`Catia.active_part()` is what makes deletion available at all."""
    selection = selection_factory()
    part_com = part_factory()
    editor = editor_factory(active_object=part_com, selection=selection)
    part = Catia(application_factory(active_editor=editor)).active_part()

    sketch = part.sketches.create(SKETCH_NAME)
    part.sketches.remove(SKETCH_NAME)

    assert selection.deleted == [sketch.com_object]


def test_active_part_survives_an_editor_without_a_selection(
    application_factory: Callable[..., Any],
    part_factory: Callable[..., Any],
) -> None:
    """Reading and creating must not depend on the selection being available."""

    class EditorWithoutSelection:
        """Fake editor that refuses to hand over a Selection."""

        def __init__(self, active_object: Any) -> None:
            self.ActiveObject = active_object
            self.Name = "Editor1"

    part_com = part_factory()
    editor = EditorWithoutSelection(part_com)
    part = Catia(application_factory(active_editor=editor)).active_part()

    assert part.sketches.create(SKETCH_NAME).name == SKETCH_NAME
    with pytest.raises(Auto3dxError):
        part.sketches.remove(SKETCH_NAME)
