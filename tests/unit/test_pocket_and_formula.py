"""Tests for Pocket features and the Formula layer.

Both were verified live against B428_Cloud
(`scripts/probes/16_pocket_and_formula.py`):

    ShapeFactory.AddNewPocket(iSketch, iHeight)  -> Pocket, a structural twin
                                                    of Pad (same properties,
                                                    same FirstLimit depth)
    Relations.CreateFormula(iName, iComment, iOutputParameter, iFormulaBody)
    Parameters.GetNameToUseInRelation(iObject)   -> the name a body must use

A formula built that way really drives the model: with body
``'AUTO3DX_THICKNESS * 2'`` targeting a pad height, driver 12 gave 24 and
driver 20 gave 40.
"""

from collections.abc import Callable
from typing import Any

import pytest

from auto_3dx.errors import (
    AmbiguousNameError,
    FeatureConflictError,
    FeatureNotFoundError,
    FormulaNotFoundError,
    ParameterTypeError,
)
from auto_3dx.formulas.collection import FormulaCollection
from auto_3dx.geometry.part_design import POCKET_KIND, PartDesign, Pocket
from auto_3dx.geometry.sketch import SketchCollection
from auto_3dx.parameters.collection import ParameterCollection

SKETCH_NAME = "AUTO3DX_SKETCH"
POCKET_NAME = "AUTO3DX_POCKET"
PAD_NAME = "AUTO3DX_PAD"
FORMULA_NAME = "AUTO3DX_FORMULA"
DEPTH = 5.0


def _sketch(part_com: Any, selection: Any = None) -> Any:
    """Creates one sketch on the fake Part."""
    return SketchCollection(part_com, selection).create(SKETCH_NAME)


# --- Pocket ------------------------------------------------------------------


def test_create_pocket_calls_add_new_pocket(part_factory: Callable[..., Any]) -> None:
    """Pocket goes through `AddNewPocket`, not `AddNewPad`."""
    part_com = part_factory()
    design = PartDesign(part_com)
    sketch = _sketch(part_com)

    design.create_pocket(POCKET_NAME, sketch, DEPTH)

    assert part_com.ShapeFactory.add_new_pocket_calls == [(sketch.com_object, DEPTH)]
    assert part_com.ShapeFactory.add_new_pad_calls == []


def test_create_pocket_passes_a_float_depth(part_factory: Callable[..., Any]) -> None:
    """`iHeight` is a COM double, so an int must arrive as a float."""
    part_com = part_factory()
    design = PartDesign(part_com)

    design.create_pocket(POCKET_NAME, _sketch(part_com), 5)

    _, depth = part_com.ShapeFactory.add_new_pocket_calls[0]
    assert isinstance(depth, float)


def test_pocket_depth_reads_first_limit(part_factory: Callable[..., Any]) -> None:
    """Verified: `FirstLimit.Dimension.Value` equals the depth passed in."""
    part_com = part_factory()
    design = PartDesign(part_com)

    pocket = design.create_pocket(POCKET_NAME, _sketch(part_com), DEPTH)

    assert pocket.depth == DEPTH
    assert pocket.com_object.FirstLimit.Dimension.Value == DEPTH


def test_pocket_set_depth_writes_first_limit(part_factory: Callable[..., Any]) -> None:
    """Depth is written back through the same property."""
    part_com = part_factory()
    design = PartDesign(part_com)
    pocket = design.create_pocket(POCKET_NAME, _sketch(part_com), DEPTH)

    pocket.set_depth(9.0)

    assert pocket.com_object.FirstLimit.Dimension.Value == 9.0


def test_pads_and_pockets_do_not_leak_into_each_other(
    part_factory: Callable[..., Any],
) -> None:
    """Both live in `MainBody.Shapes`; only the wrapper type name separates them."""
    part_com = part_factory()
    design = PartDesign(part_com)
    sketch = _sketch(part_com)
    design.create_pad(PAD_NAME, sketch, 12.0)
    design.create_pocket(POCKET_NAME, sketch, DEPTH)

    assert [p.name for p in design.pads] == [PAD_NAME]
    assert [p.name for p in design.pockets] == [POCKET_NAME]
    assert POCKET_KIND == "Pocket"


def test_get_pocket_does_not_return_a_pad(part_factory: Callable[..., Any]) -> None:
    """A pad with the requested name must not satisfy a pocket lookup."""
    part_com = part_factory()
    design = PartDesign(part_com)
    design.create_pad(POCKET_NAME, _sketch(part_com), 12.0)

    with pytest.raises(FeatureNotFoundError):
        design.get_pocket(POCKET_NAME)


def test_ensure_pocket_updates_depth_on_the_same_sketch(
    part_factory: Callable[..., Any],
) -> None:
    """Same sketch, different depth -> update in place, no new feature."""
    part_com = part_factory()
    design = PartDesign(part_com)
    sketch = _sketch(part_com)
    design.create_pocket(POCKET_NAME, sketch, DEPTH)

    ensured = design.ensure_pocket(POCKET_NAME, sketch, 9.0)

    assert ensured.depth == 9.0
    assert len(part_com.ShapeFactory.add_new_pocket_calls) == 1


def test_ensure_pocket_refuses_a_different_sketch(
    part_factory: Callable[..., Any],
) -> None:
    """Re-pointing a pocket at another profile must be refused."""
    part_com = part_factory()
    sketches = SketchCollection(part_com)
    design = PartDesign(part_com)
    first = sketches.create(SKETCH_NAME)
    other = sketches.create("OTHER")
    design.create_pocket(POCKET_NAME, first, DEPTH)

    with pytest.raises(FeatureConflictError):
        design.ensure_pocket(POCKET_NAME, other, DEPTH)


def test_ensure_pocket_uses_absolute_tolerance(
    part_factory: Callable[..., Any],
) -> None:
    """Without `rel_tol=0.0` this tiny relative change would be skipped."""
    part_com = part_factory()
    design = PartDesign(part_com)
    sketch = _sketch(part_com)
    pocket = design.create_pocket(POCKET_NAME, sketch, 1_000_000.0)

    design.ensure_pocket(POCKET_NAME, sketch, 1_000_000.001)

    assert pocket.com_object.FirstLimit.Dimension.Value == 1_000_000.001


def test_remove_pocket_uses_the_selection(
    part_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
) -> None:
    """`Shapes` has no `Remove`; deletion goes through `Editor.Selection`."""
    part_com = part_factory()
    selection = selection_factory()
    design = PartDesign(part_com, selection)
    pocket = design.create_pocket(POCKET_NAME, _sketch(part_com, selection), DEPTH)
    selection.calls.clear()

    design.remove_pocket(POCKET_NAME)

    assert selection.calls[:3] == ["Clear", "Add", "Delete"]
    assert selection.deleted == [pocket.com_object]


def test_depth_parameter_targets_the_first_limit_dimension(
    part_factory: Callable[..., Any],
) -> None:
    """This is the object a formula drives."""
    part_com = part_factory()
    design = PartDesign(part_com)
    pad = design.create_pad(PAD_NAME, _sketch(part_com), 12.0)

    assert pad.depth_parameter().com_object is pad.com_object.FirstLimit.Dimension


def test_pad_keeps_its_height_alias(part_factory: Callable[..., Any]) -> None:
    """Generalising into SketchFeature must not break the existing Pad API."""
    part_com = part_factory()
    design = PartDesign(part_com)
    pad = design.create_pad(PAD_NAME, _sketch(part_com), 12.0)

    assert pad.height == 12.0
    pad.set_height(20.0)
    assert pad.height == 20.0
    assert pad.depth == 20.0


def test_pocket_is_a_sketch_feature(part_factory: Callable[..., Any]) -> None:
    """Pocket shares Pad's base, so it carries the same behaviour."""
    part_com = part_factory()
    design = PartDesign(part_com)
    sketch = _sketch(part_com)
    pocket = design.create_pocket(POCKET_NAME, sketch, DEPTH)

    assert isinstance(pocket, Pocket)
    assert pocket.sketch().com_object == sketch.com_object
    assert "Pocket" in repr(pocket)


# --- Formula -----------------------------------------------------------------


def _collection(part_com: Any) -> FormulaCollection:
    """Builds a formula collection over a fake Part."""
    return FormulaCollection(part_com)


def _driver(part_com: Any) -> Any:
    """Creates a user parameter to drive a formula."""
    return ParameterCollection(part_com.Parameters).create_length("THICKNESS", 12)


def test_relation_name_is_not_the_parameter_name(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """The container prefix is dropped -- building a body from `.name` breaks it."""
    part_com = part_factory(parameters=parameters_collection_factory(items=[]))
    driver = _driver(part_com)
    formulas = _collection(part_com)

    relation_name = formulas.relation_name(driver)

    assert driver.name == "3D Shape00422533\\THICKNESS"
    assert relation_name == "THICKNESS"
    assert relation_name != driver.name


def test_create_passes_the_arguments_in_com_order(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """`CreateFormula(iName, iComment, iOutputParameter, iFormulaBody)`."""
    part_com = part_factory(parameters=parameters_collection_factory(items=[]))
    target = _driver(part_com)
    formulas = _collection(part_com)

    formulas.create(FORMULA_NAME, target, "THICKNESS * 2", comment="why")

    assert part_com.Relations.create_calls == [
        (FORMULA_NAME, "why", target.com_object, "THICKNESS * 2")
    ]


def test_formula_body_reads_value(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """`Formula.Value` is the body text, not a number."""
    part_com = part_factory(parameters=parameters_collection_factory(items=[]))
    formulas = _collection(part_com)

    formula = formulas.create(FORMULA_NAME, _driver(part_com), "THICKNESS * 2")

    assert formula.body == "THICKNESS * 2"
    assert formula.activated is True


def test_ensure_reuses_an_identical_body(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """An unchanged body must not be rewritten."""
    part_com = part_factory(parameters=parameters_collection_factory(items=[]))
    target = _driver(part_com)
    formulas = _collection(part_com)
    formula = formulas.create(FORMULA_NAME, target, "THICKNESS * 2")

    formulas.ensure(FORMULA_NAME, target, "THICKNESS * 2")

    assert formula.com_object.modify_calls == []
    assert len(part_com.Relations.create_calls) == 1


def test_ensure_modifies_a_changed_body(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """A different body updates in place rather than creating a second formula."""
    part_com = part_factory(parameters=parameters_collection_factory(items=[]))
    target = _driver(part_com)
    formulas = _collection(part_com)
    formulas.create(FORMULA_NAME, target, "THICKNESS * 2")

    ensured = formulas.ensure(FORMULA_NAME, target, "THICKNESS * 3")

    assert ensured.body == "THICKNESS * 3"
    assert len(part_com.Relations.create_calls) == 1


def test_get_reports_a_missing_formula(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """A missing name is a lookup failure."""
    part_com = part_factory(parameters=parameters_collection_factory(items=[]))

    with pytest.raises(FormulaNotFoundError):
        _collection(part_com).get(FORMULA_NAME)


def test_ambiguous_formula_name_is_refused(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
    relations_factory: Callable[..., Any],
    formula_factory: Callable[..., Any],
) -> None:
    """Two formulas with one name have no single correct answer."""
    relations = relations_factory(
        items=[
            formula_factory(name=FORMULA_NAME, body="A"),
            formula_factory(name=FORMULA_NAME, body="B"),
        ]
    )
    part_com = part_factory(
        parameters=parameters_collection_factory(items=[]), relations=relations
    )

    with pytest.raises(AmbiguousNameError):
        _collection(part_com).get(FORMULA_NAME)


def test_remove_uses_a_one_based_index(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
    relations_factory: Callable[..., Any],
    formula_factory: Callable[..., Any],
) -> None:
    """`Relations.Remove` is 1-based; an off-by-one deletes the wrong formula."""
    relations = relations_factory(
        items=[
            formula_factory(name="FIRST", body="A"),
            formula_factory(name=FORMULA_NAME, body="B"),
        ]
    )
    part_com = part_factory(
        parameters=parameters_collection_factory(items=[]), relations=relations
    )

    _collection(part_com).remove(FORMULA_NAME)

    assert relations.remove_calls == [2]
    assert [f.Name for f in relations._items] == ["FIRST"]


@pytest.mark.parametrize("bad_body", ["", 1, None])
def test_create_rejects_an_unusable_body(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
    bad_body: Any,
) -> None:
    """A bad body must be refused before it reaches the model."""
    part_com = part_factory(parameters=parameters_collection_factory(items=[]))
    target = _driver(part_com)

    with pytest.raises(ParameterTypeError):
        _collection(part_com).create(FORMULA_NAME, target, bad_body)

    assert part_com.Relations.create_calls == []


def test_formula_operations_do_not_update_the_part(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """The caller decides when to update, so several edits can be batched."""
    part_com = part_factory(parameters=parameters_collection_factory(items=[]))
    target = _driver(part_com)
    formulas = _collection(part_com)

    formulas.create(FORMULA_NAME, target, "THICKNESS * 2")
    formulas.ensure(FORMULA_NAME, target, "THICKNESS * 3")
    formulas.remove(FORMULA_NAME)

    assert part_com.update_calls == 0
