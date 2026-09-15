"""Tests for the shared model generation across parameters and formulas.

`docs/api-design.md` section 5.2 states the rule these tests pin: **a
parameter write advances the generation even when the parameter drives
nothing**, because the SDK cannot tell whether it feeds a formula that feeds
a feature dimension. Before this module's changes, nothing in
`auto_3dx.parameters` or `auto_3dx.formulas` advanced the counter at all.

`ModelGeneration` itself (the counter, `mutation()`, `require_current`) is
already pinned by `tests/unit/test_model_generation.py`. This module pins
the wiring on top of it:

- Every mutating parameter/formula operation advances a generation shared
  with the owning collection.
- A request rejected before any COM call (a duplicate name, a kind
  mismatch, a bad value) leaves the generation untouched.
- A `Parameter`/`Formula` returned by a collection shares that collection's
  generation object, so writing through the returned wrapper advances the
  collection's own counter.
- Read-only calls never advance it.

Each test builds one `ModelGeneration` and passes it explicitly into the
collection (or wrapper) under test, then asserts on `.value` directly,
rather than going through `StaleSnapshotError` machinery that belongs to
the topology layer.
"""

from collections.abc import Callable
from typing import Any

import pytest

from auto_3dx._generation import ModelGeneration
from auto_3dx.errors import (
    AmbiguousNameError,
    FormulaAlreadyExistsError,
    FormulaNotFoundError,
    ParameterAlreadyExistsError,
    ParameterNameError,
    ParameterNotFoundError,
    ParameterTypeError,
    UnsupportedMagnitudeError,
    UnsupportedUnitError,
)
from auto_3dx.formulas.collection import FormulaCollection
from auto_3dx.formulas.formula import Formula
from auto_3dx.parameters.collection import ParameterCollection
from auto_3dx.parameters.parameter import Parameter

NAME = "AUTO3DX_SPAN"
FORMULA_NAME = "AUTO3DX_FORMULA"


# --- Helpers -------------------------------------------------------------------


def _parameters(
    parameters_collection_factory: Callable[..., Any],
    generation: ModelGeneration,
    items: "list[tuple[str, Any]] | None" = None,
) -> ParameterCollection:
    """Builds a `ParameterCollection` over a fresh fake `Parameters`, sharing `generation`."""
    raw = parameters_collection_factory(items or [])
    return ParameterCollection(raw, generation)


def _formulas(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
    generation: ModelGeneration,
    relations: Any = None,
) -> "tuple[FormulaCollection, Any]":
    """Builds a `FormulaCollection` over a fresh fake `Part`, sharing `generation`."""
    kwargs: dict[str, Any] = {"parameters": parameters_collection_factory(items=[])}
    if relations is not None:
        kwargs["relations"] = relations
    part_com = part_factory(**kwargs)
    return FormulaCollection(part_com, generation), part_com


def _driver(part_com: Any) -> Any:
    """Creates a user Length parameter to drive a formula.

    Deliberately built through its own, unrelated `ParameterCollection` (as
    `tests/unit/test_pocket_and_formula.py` does): the formula generation
    under test must not be perturbed by setting up its target.
    """
    return ParameterCollection(part_com.Parameters).create_length("THICKNESS", 12)


# --- ParameterCollection: create_* ----------------------------------------------


@pytest.mark.parametrize(
    "method_name,args",
    [
        ("create_length", (NAME, 25)),
        ("create_real", (NAME, 1.5)),
        ("create_integer", (NAME, 2)),
        ("create_string", (NAME, "x")),
        ("create_boolean", (NAME, True)),
        ("create_dimension", (NAME, "Mass", 3.0)),
    ],
)
def test_every_create_advances_the_generation_exactly_once(
    parameters_collection_factory: Callable[..., Any],
    method_name: str,
    args: tuple,
) -> None:
    """Every `create_*` method shares the same underlying `_create`, one advance each."""
    generation = ModelGeneration()
    collection = _parameters(parameters_collection_factory, generation)

    getattr(collection, method_name)(*args)

    assert generation.value == 1


def test_create_length_duplicate_name_does_not_advance_the_generation(
    parameters_collection_factory: Callable[..., Any],
    fake_length: Any,
) -> None:
    """The pre-create existence check rejects the call before any COM call."""
    generation = ModelGeneration()
    collection = _parameters(
        parameters_collection_factory, generation, items=[(fake_length.Name, fake_length)]
    )

    with pytest.raises(ParameterAlreadyExistsError):
        collection.create_length(fake_length.Name, 25)

    assert generation.value == 0


def test_create_length_rejects_unusable_name_without_advancing(
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """A name validation failure is rejected before the existence check even runs."""
    generation = ModelGeneration()
    collection = _parameters(parameters_collection_factory, generation)

    with pytest.raises(ParameterNameError):
        collection.create_length("bad\\name", 25)

    assert generation.value == 0


def test_create_dimension_rejects_unsupported_magnitude_without_advancing(
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """An unrecognised magnitude is rejected before any COM call."""
    generation = ModelGeneration()
    collection = _parameters(parameters_collection_factory, generation)

    with pytest.raises(UnsupportedMagnitudeError):
        collection.create_dimension(NAME, "Bogus", 1.0)

    assert generation.value == 0


# --- ParameterCollection: ensure_* -----------------------------------------------


@pytest.mark.parametrize(
    "method_name,args",
    [
        ("ensure_length", (NAME, 25)),
        ("ensure_real", (NAME, 1.5)),
        ("ensure_integer", (NAME, 2)),
        ("ensure_string", (NAME, "x")),
        ("ensure_boolean", (NAME, True)),
        ("ensure_dimension", (NAME, "Mass", 3.0)),
    ],
)
def test_every_ensure_creating_advances_the_generation_once(
    parameters_collection_factory: Callable[..., Any],
    method_name: str,
    args: tuple,
) -> None:
    """`ensure_*` on an absent name delegates to `create_*`: one advance, not two."""
    generation = ModelGeneration()
    collection = _parameters(parameters_collection_factory, generation)

    getattr(collection, method_name)(*args)

    assert generation.value == 1


def test_ensure_length_setting_advances_the_generation_once(
    parameters_collection_factory: Callable[..., Any],
    fake_length: Any,
) -> None:
    """`ensure_*` on an existing name delegates to `Parameter.set`: one advance."""
    generation = ModelGeneration()
    collection = _parameters(
        parameters_collection_factory, generation, items=[(fake_length.Name, fake_length)]
    )

    collection.ensure_length(fake_length.Name, 250)

    assert generation.value == 1


def test_ensure_real_setting_advances_the_generation_once(
    parameters_collection_factory: Callable[..., Any],
    real_param_factory: Callable[..., Any],
) -> None:
    """Same as `ensure_length`, for the `RealParam` kind."""
    generation = ModelGeneration()
    existing = real_param_factory(name=NAME, value=1.0)
    collection = _parameters(parameters_collection_factory, generation, items=[(NAME, existing)])

    collection.ensure_real(NAME, 9.0)

    assert generation.value == 1


def test_ensure_integer_setting_advances_the_generation_once(
    parameters_collection_factory: Callable[..., Any],
    int_param_factory: Callable[..., Any],
) -> None:
    """Same as `ensure_length`, for the `IntParam` kind."""
    generation = ModelGeneration()
    existing = int_param_factory(name=NAME, value=1)
    collection = _parameters(parameters_collection_factory, generation, items=[(NAME, existing)])

    collection.ensure_integer(NAME, 9)

    assert generation.value == 1


def test_ensure_string_setting_advances_the_generation_once(
    parameters_collection_factory: Callable[..., Any],
    str_param_factory: Callable[..., Any],
) -> None:
    """Same as `ensure_length`, for the `StrParam` kind."""
    generation = ModelGeneration()
    existing = str_param_factory(name=NAME, value="a")
    collection = _parameters(parameters_collection_factory, generation, items=[(NAME, existing)])

    collection.ensure_string(NAME, "b")

    assert generation.value == 1


def test_ensure_boolean_setting_advances_the_generation_once(
    parameters_collection_factory: Callable[..., Any],
    bool_param_factory: Callable[..., Any],
) -> None:
    """Same as `ensure_length`, for the `BoolParam` kind."""
    generation = ModelGeneration()
    existing = bool_param_factory(name=NAME, value=False)
    collection = _parameters(parameters_collection_factory, generation, items=[(NAME, existing)])

    collection.ensure_boolean(NAME, True)

    assert generation.value == 1


def test_ensure_dimension_setting_advances_the_generation_once(
    parameters_collection_factory: Callable[..., Any],
    dimension_fake_factory: Callable[..., Any],
) -> None:
    """Same as `ensure_length`, for a generic `Dimension` (`Mass`) kind."""
    generation = ModelGeneration()
    existing = dimension_fake_factory("Dimension", NAME, 1.0, "Mass", "kg", "Kilogram")
    collection = _parameters(parameters_collection_factory, generation, items=[(NAME, existing)])

    collection.ensure_dimension(NAME, "Mass", 9.0)

    assert generation.value == 1


def test_ensure_length_type_mismatch_does_not_advance_the_generation(
    parameters_collection_factory: Callable[..., Any],
    fake_real: Any,
) -> None:
    """A kind mismatch is rejected by `check_existing`, before any write."""
    generation = ModelGeneration()
    collection = _parameters(
        parameters_collection_factory, generation, items=[(fake_real.Name, fake_real)]
    )

    with pytest.raises(ParameterTypeError):
        collection.ensure_length(fake_real.Name, 250)

    assert generation.value == 0


# --- ParameterCollection: set / remove -------------------------------------------


def test_collection_set_advances_the_generation(
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """`ParameterCollection.set` delegates to `Parameter.set`: exactly one advance."""
    generation = ModelGeneration()
    collection = _parameters(parameters_collection_factory, generation)
    collection.create_length(NAME, 25)
    before = generation.value

    collection.set(NAME, 99)

    assert generation.value == before + 1


def test_remove_advances_the_generation(
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """Removing a parameter changes the model, same as adding one."""
    generation = ModelGeneration()
    collection = _parameters(parameters_collection_factory, generation)
    collection.create_length(NAME, 25)
    before = generation.value

    collection.remove(NAME)

    assert generation.value == before + 1


def test_remove_missing_name_does_not_advance_the_generation(
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """The lookup that precedes removal fails before any COM call is made."""
    generation = ModelGeneration()
    collection = _parameters(parameters_collection_factory, generation)

    with pytest.raises(ParameterNotFoundError):
        collection.remove(NAME)

    assert generation.value == 0


# --- Parameter.set ---------------------------------------------------------------


def test_parameter_set_advances_the_generation(fake_length: Any) -> None:
    """`Parameter.set` advances whatever generation it was constructed with."""
    generation = ModelGeneration()
    parameter = Parameter(fake_length, generation)

    parameter.set(150)

    assert generation.value == 1


def test_parameter_set_rejects_bad_value_without_advancing(fake_length: Any) -> None:
    """`bool` is rejected before the COM write is attempted."""
    generation = ModelGeneration()
    parameter = Parameter(fake_length, generation)

    with pytest.raises(ParameterTypeError):
        parameter.set(True)

    assert generation.value == 0


def test_parameter_set_rejects_mismatched_unit_without_advancing(fake_length: Any) -> None:
    """A unit mismatch is rejected before the COM write is attempted."""
    generation = ModelGeneration()
    parameter = Parameter(fake_length, generation)

    with pytest.raises(UnsupportedUnitError):
        parameter.set(150, unit="inch")

    assert generation.value == 0


# --- Returned Parameter wrappers share the collection's generation --------------


def test_created_parameter_shares_the_collection_generation(
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """Writing through a `create_*` wrapper advances the owning collection's counter."""
    generation = ModelGeneration()
    collection = _parameters(parameters_collection_factory, generation)
    created = collection.create_length(NAME, 25)
    before = generation.value

    created.set(99)

    assert generation.value == before + 1


def test_get_returns_a_parameter_sharing_the_generation(
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """`get` must not build a `Parameter` with its own, unshared generation."""
    generation = ModelGeneration()
    collection = _parameters(parameters_collection_factory, generation)
    collection.create_length(NAME, 25)
    before = generation.value

    collection.get(NAME).set(42)

    assert generation.value == before + 1


def test_list_returns_parameters_sharing_the_generation(
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """Same as `get`, for `list`."""
    generation = ModelGeneration()
    collection = _parameters(parameters_collection_factory, generation)
    collection.create_length(NAME, 25)
    before = generation.value

    [parameter] = collection.list()
    parameter.set(42)

    assert generation.value == before + 1


def test_user_parameters_returns_parameters_sharing_the_generation(
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """Same as `get`, for `user_parameters`."""
    generation = ModelGeneration()
    collection = _parameters(parameters_collection_factory, generation)
    collection.create_length(NAME, 25)
    before = generation.value

    [parameter] = collection.user_parameters()
    parameter.set(42)

    assert generation.value == before + 1


# --- ParameterCollection / Parameter reads never advance ------------------------


def test_parameter_reads_do_not_advance_the_generation(
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """Every read-only call listed in `docs/api-design.md` section 5.2 leaves it alone."""
    generation = ModelGeneration()
    collection = _parameters(parameters_collection_factory, generation)
    collection.create_length(NAME, 25)
    after_create = generation.value

    collection.list()
    collection.names()
    collection.user_parameters()
    collection.user_names()
    _ = collection.count
    _ = NAME in collection
    parameter = collection.get(NAME)
    _ = parameter.value
    _ = parameter.unit
    _ = parameter.magnitude
    _ = parameter.kind
    _ = parameter.name
    _ = parameter.short_name
    parameter.info()

    assert generation.value == after_create


# --- FormulaCollection: create ---------------------------------------------------


def test_formula_create_advances_the_generation(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """`CreateFormula` is a mutation like any other creation."""
    generation = ModelGeneration()
    formulas, part_com = _formulas(part_factory, parameters_collection_factory, generation)
    target = _driver(part_com)

    formulas.create(FORMULA_NAME, target, "THICKNESS * 2")

    assert generation.value == 1


def test_formula_create_duplicate_name_does_not_advance_the_generation(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """The pre-create existence check rejects the call before any COM call."""
    generation = ModelGeneration()
    formulas, part_com = _formulas(part_factory, parameters_collection_factory, generation)
    target = _driver(part_com)
    formulas.create(FORMULA_NAME, target, "THICKNESS * 2")
    before = generation.value

    with pytest.raises(FormulaAlreadyExistsError):
        formulas.create(FORMULA_NAME, target, "THICKNESS * 3")

    assert generation.value == before


def test_formula_create_rejects_empty_body_without_advancing(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """Body validation happens before the existence check and before any COM call."""
    generation = ModelGeneration()
    formulas, part_com = _formulas(part_factory, parameters_collection_factory, generation)
    target = _driver(part_com)

    with pytest.raises(ParameterTypeError):
        formulas.create(FORMULA_NAME, target, "")

    assert generation.value == 0


# --- FormulaCollection: ensure ---------------------------------------------------


def test_formula_ensure_creating_advances_the_generation_once(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """`ensure` on an absent name delegates to `create`: one advance, not two."""
    generation = ModelGeneration()
    formulas, part_com = _formulas(part_factory, parameters_collection_factory, generation)
    target = _driver(part_com)

    formulas.ensure(FORMULA_NAME, target, "THICKNESS * 2")

    assert generation.value == 1


def test_formula_ensure_modifying_advances_the_generation_once(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """`ensure` on a changed body delegates to `Formula.modify`: one advance."""
    generation = ModelGeneration()
    formulas, part_com = _formulas(part_factory, parameters_collection_factory, generation)
    target = _driver(part_com)
    formulas.create(FORMULA_NAME, target, "THICKNESS * 2")
    before = generation.value

    formulas.ensure(FORMULA_NAME, target, "THICKNESS * 3")

    assert generation.value == before + 1


def test_formula_ensure_reusing_unchanged_body_does_not_advance_the_generation(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """Neither branch of `ensure` runs when the body is already identical."""
    generation = ModelGeneration()
    formulas, part_com = _formulas(part_factory, parameters_collection_factory, generation)
    target = _driver(part_com)
    formulas.create(FORMULA_NAME, target, "THICKNESS * 2")
    before = generation.value

    formulas.ensure(FORMULA_NAME, target, "THICKNESS * 2")

    assert generation.value == before


# --- FormulaCollection: remove ---------------------------------------------------


def test_formula_remove_advances_the_generation(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """Removing a formula changes the model, same as adding one."""
    generation = ModelGeneration()
    formulas, part_com = _formulas(part_factory, parameters_collection_factory, generation)
    target = _driver(part_com)
    formulas.create(FORMULA_NAME, target, "THICKNESS * 2")
    before = generation.value

    formulas.remove(FORMULA_NAME)

    assert generation.value == before + 1


def test_formula_remove_missing_name_does_not_advance_the_generation(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """The enumeration that precedes removal fails before any COM call is made."""
    generation = ModelGeneration()
    formulas, _ = _formulas(part_factory, parameters_collection_factory, generation)

    with pytest.raises(FormulaNotFoundError):
        formulas.remove(FORMULA_NAME)

    assert generation.value == 0


def test_formula_remove_ambiguous_name_does_not_advance_the_generation(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
    relations_factory: Callable[..., Any],
    formula_factory: Callable[..., Any],
) -> None:
    """Two matching formulas refuse the removal before any COM call is made."""
    generation = ModelGeneration()
    relations = relations_factory(
        items=[
            formula_factory(name=FORMULA_NAME, body="A"),
            formula_factory(name=FORMULA_NAME, body="B"),
        ]
    )
    formulas, _ = _formulas(
        part_factory, parameters_collection_factory, generation, relations=relations
    )

    with pytest.raises(AmbiguousNameError):
        formulas.remove(FORMULA_NAME)

    assert generation.value == 0


# --- Formula.modify / rename / activate / deactivate -----------------------------


def test_formula_modify_advances_the_generation(formula_factory: Callable[..., Any]) -> None:
    """`Formula.modify` advances whatever generation it was constructed with."""
    generation = ModelGeneration()
    formula = Formula(formula_factory(), generation)

    formula.modify("X * 2")

    assert generation.value == 1


def test_formula_modify_rejects_empty_body_without_advancing(
    formula_factory: Callable[..., Any],
) -> None:
    """An empty body is rejected before the COM write is attempted."""
    generation = ModelGeneration()
    formula = Formula(formula_factory(), generation)

    with pytest.raises(ParameterTypeError):
        formula.modify("")

    assert generation.value == 0


def test_formula_rename_advances_the_generation(formula_factory: Callable[..., Any]) -> None:
    """A formula can drive geometry, so renaming it counts as a mutation too."""
    generation = ModelGeneration()
    formula = Formula(formula_factory(), generation)

    formula.rename("RENAMED")

    assert generation.value == 1


def test_formula_rename_rejects_bad_name_without_advancing(
    formula_factory: Callable[..., Any],
) -> None:
    """An unusable name is rejected before the COM rename is attempted."""
    generation = ModelGeneration()
    formula = Formula(formula_factory(), generation)

    with pytest.raises(ParameterNameError):
        formula.rename("bad\\name")

    assert generation.value == 0


def test_formula_activate_advances_the_generation(formula_factory: Callable[..., Any]) -> None:
    """Activating a formula can start it driving a feature dimension again."""
    generation = ModelGeneration()
    formula = Formula(formula_factory(), generation)

    formula.activate()

    assert generation.value == 1


def test_formula_deactivate_advances_the_generation(formula_factory: Callable[..., Any]) -> None:
    """Deactivating a formula can stop it driving a feature dimension."""
    generation = ModelGeneration()
    formula = Formula(formula_factory(), generation)

    formula.deactivate()

    assert generation.value == 1


# --- Returned Formula wrappers share the collection's generation ----------------


def test_created_formula_shares_the_collection_generation(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """Writing through a `create` wrapper advances the owning collection's counter."""
    generation = ModelGeneration()
    formulas, part_com = _formulas(part_factory, parameters_collection_factory, generation)
    target = _driver(part_com)
    created = formulas.create(FORMULA_NAME, target, "THICKNESS * 2")
    before = generation.value

    created.modify("THICKNESS * 3")

    assert generation.value == before + 1


def test_formula_from_get_shares_the_generation(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """`get` must not build a `Formula` with its own, unshared generation."""
    generation = ModelGeneration()
    formulas, part_com = _formulas(part_factory, parameters_collection_factory, generation)
    target = _driver(part_com)
    formulas.create(FORMULA_NAME, target, "THICKNESS * 2")
    before = generation.value

    formulas.get(FORMULA_NAME).activate()

    assert generation.value == before + 1


def test_formula_from_list_shares_the_generation(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """Same as `get`, for `list`."""
    generation = ModelGeneration()
    formulas, part_com = _formulas(part_factory, parameters_collection_factory, generation)
    target = _driver(part_com)
    formulas.create(FORMULA_NAME, target, "THICKNESS * 2")
    before = generation.value

    [formula] = formulas.list()
    formula.deactivate()

    assert generation.value == before + 1


# --- FormulaCollection / Formula reads never advance ----------------------------


def test_formula_reads_do_not_advance_the_generation(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """Every read-only call listed in `docs/api-design.md` section 5.2 leaves it alone."""
    generation = ModelGeneration()
    formulas, part_com = _formulas(part_factory, parameters_collection_factory, generation)
    target = _driver(part_com)
    formulas.create(FORMULA_NAME, target, "THICKNESS * 2")
    after_create = generation.value

    formulas.list()
    formulas.names()
    _ = formulas.count
    _ = FORMULA_NAME in formulas
    formulas.relation_name(target)
    formula = formulas.get(FORMULA_NAME)
    _ = formula.body
    _ = formula.comment
    _ = formula.activated
    _ = formula.input_count
    _ = formula.name

    assert generation.value == after_create
