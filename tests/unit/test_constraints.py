"""Tests for the sketch-constraint API (`auto_3dx.geometry.constraint`).

Verified live against B428_Cloud (probes 20/21/22, `docs/conventions.md`
1.2.4 and 6.14):

    Constraints.AddMonoEltCst(iCstType: int, iElem)         -> Constraint
    Constraints.AddBiEltCst(iCstType: int, iFirst, iSecond) -> Constraint
    Constraints.Count / Item(i) / BrokenConstraintsCount / UnUpdatedConstraintsCount
    Constraint: Name, Type, Status, Dimension, Mode

Two facts drive the whole design:

- Constraints only work INSIDE the open-edition session. After
  `CloseEdition()` every `AddMonoEltCst`/`AddBiEltCst` call raised
  `com_error`. That is why the creation methods live on `SketchEditor`
  (only reachable from `Sketch.edit()`), not on `Sketch`.
- The argument is the RAW `Line2D`/`Circle2D`, never a `Reference` -- a
  `Reference` was rejected. This is the opposite of Part Design, where
  `Chamfer`/`Fillet`/etc. need a `Reference`.

The requested type code and the resulting `Constraint.Type` can differ:
Horizontality (10) and Verticality (13) both normalize to Parallelism
(Type 8). Dimensional kinds (Length/Radius/Offset) carry a `Dimension` whose
`Value` is readable and writable; non-dimensional kinds raise on `.Dimension`
access, which the library must catch rather than let escape.
"""

from collections.abc import Callable
from typing import Any

import pytest
import pywintypes

from auto_3dx.errors import (
    AmbiguousNameError,
    Auto3dxError,
    ConstraintNotFoundError,
    ParameterTypeError,
    UnsupportedUnitError,
)
from auto_3dx.geometry.constraint import (
    CONSTRAINT_COINCIDENT,
    CONSTRAINT_DISTANCE,
    CONSTRAINT_HORIZONTAL,
    CONSTRAINT_LENGTH,
    CONSTRAINT_PARALLEL,
    CONSTRAINT_PERPENDICULAR,
    CONSTRAINT_RADIUS,
    CONSTRAINT_TANGENT,
    CONSTRAINT_VERTICAL,
    Constraint,
    ConstraintCollection,
)
from auto_3dx.geometry.sketch import SketchCollection
from auto_3dx.parameters.parameter import Parameter

from tests.conftest import (
    CONSTRAINT_DISTANCE_DEFAULT_VALUE,
    CONSTRAINT_LENGTH_DEFAULT_VALUE,
    CONSTRAINT_RADIUS_DEFAULT_VALUE,
)
from tests.conftest import Constraint as FakeConstraint
from tests.conftest import Constraints as FakeConstraints

SKETCH_NAME = "AUTO3DX_CONSTRAINT_SKETCH"


def _sketch(part_com: Any, selection: Any = None, name: str = SKETCH_NAME) -> Any:
    """Creates one sketch on the fake Part, ready to be `edit()`-ed."""
    return SketchCollection(part_com, selection).create(name)


# --- creation: mono-element constraints --------------------------------------


def test_horizontal_calls_add_mono_elt_cst_with_the_raw_line(
    part_factory: Callable[..., Any],
) -> None:
    """`horizontal(line)` must pass code 10 and the exact raw `Line2D`."""
    part_com = part_factory()
    sketch = _sketch(part_com)

    with sketch.edit() as editor:
        line = editor.line(0.0, 0.0, 10.0, 0.0)
        editor.horizontal(line)

    fake_constraints: FakeConstraints = sketch.com_object.Constraints
    assert fake_constraints.mono_calls == [(CONSTRAINT_HORIZONTAL, line.com_object)]
    # Identity, not just equality: no Reference wrapper was built around it.
    recorded_arg = fake_constraints.mono_calls[0][1]
    assert recorded_arg is line.com_object
    assert type(recorded_arg).__name__ != "Reference"


def test_vertical_calls_add_mono_elt_cst_with_the_raw_line(
    part_factory: Callable[..., Any],
) -> None:
    """`vertical(line)` must pass code 13 and the exact raw `Line2D`."""
    part_com = part_factory()
    sketch = _sketch(part_com)

    with sketch.edit() as editor:
        line = editor.line(0.0, 0.0, 0.0, 10.0)
        editor.vertical(line)

    fake_constraints: FakeConstraints = sketch.com_object.Constraints
    assert fake_constraints.mono_calls == [(CONSTRAINT_VERTICAL, line.com_object)]
    assert fake_constraints.mono_calls[0][1] is line.com_object


# --- creation: bi-element constraints ----------------------------------------


@pytest.mark.parametrize(
    ("method_name", "expected_code"),
    [
        ("perpendicular", CONSTRAINT_PERPENDICULAR),
        ("parallel", CONSTRAINT_PARALLEL),
        ("coincident", CONSTRAINT_COINCIDENT),
        ("tangent", CONSTRAINT_TANGENT),
    ],
)
def test_bi_element_constraints_call_add_bi_elt_cst_with_both_raw_elements(
    part_factory: Callable[..., Any],
    method_name: str,
    expected_code: int,
) -> None:
    """Each two-element constraint call must pass its code and both raw elements, in order."""
    part_com = part_factory()
    sketch = _sketch(part_com)

    with sketch.edit() as editor:
        first = editor.line(0.0, 0.0, 10.0, 0.0)
        second = editor.line(0.0, 0.0, 0.0, 10.0)
        getattr(editor, method_name)(first, second)

    fake_constraints: FakeConstraints = sketch.com_object.Constraints
    assert fake_constraints.bi_calls == [
        (expected_code, first.com_object, second.com_object)
    ]
    _, recorded_first, recorded_second = fake_constraints.bi_calls[0]
    assert recorded_first is first.com_object
    assert recorded_second is second.com_object


# --- the requested code and the resulting Type can differ -------------------


def test_horizontal_constraint_reports_type_parallelism_not_the_requested_code(
    part_factory: Callable[..., Any],
) -> None:
    """Pins the normalization: a horizontal constraint's `Type` is 8, not 10.

    Verified (docs/conventions.md 1.2.4): CATIA folds Horizontality (10) and
    Verticality (13) into Parallelism (Type 8). Nobody should later "fix" a
    lookup by matching on the requested code instead of the reported one.
    """
    part_com = part_factory()
    sketch = _sketch(part_com)

    with sketch.edit() as editor:
        line = editor.line(0.0, 0.0, 10.0, 0.0)
        constraint = editor.horizontal(line)

    assert constraint.type_code == 8
    assert constraint.type_code != CONSTRAINT_HORIZONTAL


def test_vertical_constraint_also_reports_type_parallelism(
    part_factory: Callable[..., Any],
) -> None:
    """Same normalization applies to Verticality (13 -> Type 8)."""
    part_com = part_factory()
    sketch = _sketch(part_com)

    with sketch.edit() as editor:
        line = editor.line(0.0, 0.0, 0.0, 10.0)
        constraint = editor.vertical(line)

    assert constraint.type_code == 8
    assert constraint.type_code != CONSTRAINT_VERTICAL


# --- dimensional constraints: creation + optional immediate write -----------


def test_length_with_a_value_creates_and_writes_the_dimension(
    part_factory: Callable[..., Any],
) -> None:
    """`length(line, 40)` must create the constraint AND set `Dimension.Value`."""
    part_com = part_factory()
    sketch = _sketch(part_com)

    with sketch.edit() as editor:
        line = editor.line(0.0, 0.0, 10.0, 0.0)
        constraint = editor.length(line, 40)

    assert constraint.com_object.Type == CONSTRAINT_LENGTH
    assert constraint.com_object.Dimension.Value == 40.0
    assert isinstance(constraint.com_object.Dimension.Value, float)


def test_length_without_a_value_creates_but_does_not_write_the_dimension(
    part_factory: Callable[..., Any],
) -> None:
    """`length(line)` must create the constraint and leave its dimension untouched."""
    part_com = part_factory()
    sketch = _sketch(part_com)

    with sketch.edit() as editor:
        line = editor.line(0.0, 0.0, 10.0, 0.0)
        constraint = editor.length(line)

    assert constraint.com_object.Dimension.Value == CONSTRAINT_LENGTH_DEFAULT_VALUE


def test_radius_with_a_value_creates_and_writes_the_dimension(
    part_factory: Callable[..., Any],
) -> None:
    """`radius(circle, 9)` must create the constraint AND set `Dimension.Value`."""
    part_com = part_factory()
    sketch = _sketch(part_com)

    with sketch.edit() as editor:
        circle = editor.circle(0.0, 0.0, 4.0)
        constraint = editor.radius(circle, 9)

    assert constraint.com_object.Type == CONSTRAINT_RADIUS
    assert constraint.com_object.Dimension.Value == 9.0


def test_radius_without_a_value_does_not_write_the_dimension(
    part_factory: Callable[..., Any],
) -> None:
    """`radius(circle)` must not touch the dimension it was created with."""
    part_com = part_factory()
    sketch = _sketch(part_com)

    with sketch.edit() as editor:
        circle = editor.circle(0.0, 0.0, 4.0)
        constraint = editor.radius(circle)

    assert constraint.com_object.Dimension.Value == CONSTRAINT_RADIUS_DEFAULT_VALUE


def test_distance_with_a_value_creates_and_writes_the_dimension(
    part_factory: Callable[..., Any],
) -> None:
    """`distance(a, b, 30)` must create the constraint AND set `Dimension.Value`."""
    part_com = part_factory()
    sketch = _sketch(part_com)

    with sketch.edit() as editor:
        first = editor.line(0.0, 0.0, 10.0, 0.0)
        second = editor.line(0.0, 5.0, 10.0, 5.0)
        constraint = editor.distance(first, second, 30)

    assert constraint.com_object.Type == CONSTRAINT_DISTANCE
    assert constraint.com_object.Dimension.Value == 30.0


def test_distance_without_a_value_does_not_write_the_dimension(
    part_factory: Callable[..., Any],
) -> None:
    """`distance(a, b)` must not touch the dimension it was created with."""
    part_com = part_factory()
    sketch = _sketch(part_com)

    with sketch.edit() as editor:
        first = editor.line(0.0, 0.0, 10.0, 0.0)
        second = editor.line(0.0, 5.0, 10.0, 5.0)
        constraint = editor.distance(first, second)

    assert constraint.com_object.Dimension.Value == CONSTRAINT_DISTANCE_DEFAULT_VALUE


# --- Constraint.value --------------------------------------------------------


def test_value_returns_the_dimension_value_for_a_dimensional_constraint(
    constraint_factory: Callable[..., FakeConstraint],
    length_parameter_factory: Callable[..., Any],
) -> None:
    """A dimensional constraint's `.value` reads through to `Dimension.Value`."""
    fake = constraint_factory(
        name="Length.3", type_code=CONSTRAINT_LENGTH, dimension=length_parameter_factory(value=45.0)
    )

    constraint = Constraint(fake)

    assert constraint.value == 45.0


def test_value_is_none_for_a_non_dimensional_constraint_and_does_not_raise(
    constraint_factory: Callable[..., FakeConstraint],
) -> None:
    """`.Dimension` raises on the real COM object for non-dimensional kinds.

    The library must catch that (it is a `pywintypes.com_error`, per the fake)
    and report `value is None` -- the raise must never escape to the caller.
    """
    fake = constraint_factory(name="Coincidence.8", type_code=CONSTRAINT_COINCIDENT, dimension=None)

    constraint = Constraint(fake)

    assert constraint.value is None


# --- Constraint.set_value validation -----------------------------------------


def test_set_value_rejects_a_bool(
    constraint_factory: Callable[..., FakeConstraint],
    length_parameter_factory: Callable[..., Any],
) -> None:
    """`bool` is a subclass of `int`, so `True` must not silently become `1.0`."""
    fake = constraint_factory(
        name="Length.3", type_code=CONSTRAINT_LENGTH, dimension=length_parameter_factory(value=40.0)
    )
    constraint = Constraint(fake)

    with pytest.raises(ParameterTypeError):
        constraint.set_value(True)  # type: ignore[arg-type]

    assert fake.Dimension.Value == 40.0


def test_set_value_rejects_a_non_numeric_value(
    constraint_factory: Callable[..., FakeConstraint],
    length_parameter_factory: Callable[..., Any],
) -> None:
    """A string value must be refused before it reaches the model."""
    fake = constraint_factory(
        name="Length.3", type_code=CONSTRAINT_LENGTH, dimension=length_parameter_factory(value=40.0)
    )
    constraint = Constraint(fake)

    with pytest.raises(ParameterTypeError):
        constraint.set_value("40")  # type: ignore[arg-type]


def test_set_value_rejects_an_unsupported_unit(
    constraint_factory: Callable[..., FakeConstraint],
    length_parameter_factory: Callable[..., Any],
) -> None:
    """Only millimetres are verified for constraint dimensions."""
    fake = constraint_factory(
        name="Length.3", type_code=CONSTRAINT_LENGTH, dimension=length_parameter_factory(value=40.0)
    )
    constraint = Constraint(fake)

    with pytest.raises(UnsupportedUnitError):
        constraint.set_value(45.0, unit="cm")


def test_set_value_rejects_an_unhashable_unit(
    constraint_factory: Callable[..., FakeConstraint],
    length_parameter_factory: Callable[..., Any],
) -> None:
    """`in` on a frozenset hashes its operand, so a list must not raise `TypeError`."""
    fake = constraint_factory(
        name="Length.3", type_code=CONSTRAINT_LENGTH, dimension=length_parameter_factory(value=40.0)
    )
    constraint = Constraint(fake)

    with pytest.raises(UnsupportedUnitError):
        constraint.set_value(45.0, unit=[])  # type: ignore[arg-type]


# --- Constraint.dimension_parameter -------------------------------------------


def test_dimension_parameter_wraps_the_raw_dimension_by_identity(
    constraint_factory: Callable[..., FakeConstraint],
    length_parameter_factory: Callable[..., Any],
) -> None:
    """This is what a `Formula` targets, so it must be the raw `Dimension` object."""
    dimension = length_parameter_factory(value=40.0)
    fake = constraint_factory(name="Length.3", type_code=CONSTRAINT_LENGTH, dimension=dimension)
    constraint = Constraint(fake)

    parameter = constraint.dimension_parameter()

    assert isinstance(parameter, Parameter)
    assert parameter.com_object is dimension


def test_dimension_parameter_on_a_non_dimensional_constraint_raises(
    constraint_factory: Callable[..., FakeConstraint],
) -> None:
    """A constraint with no `Dimension` cannot back a formula."""
    fake = constraint_factory(name="Coincidence.8", type_code=CONSTRAINT_COINCIDENT, dimension=None)
    constraint = Constraint(fake)

    with pytest.raises(ParameterTypeError):
        constraint.dimension_parameter()


# --- sketch.constraints (ConstraintCollection) -------------------------------


def test_sketch_constraints_reflects_created_constraints(
    part_factory: Callable[..., Any],
) -> None:
    """`sketch.constraints` must see what `SketchEditor` created, after `edit()` closes."""
    part_com = part_factory()
    sketch = _sketch(part_com)

    with sketch.edit() as editor:
        line = editor.line(0.0, 0.0, 10.0, 0.0)
        editor.horizontal(line)
        editor.length(line, 40)

    collection = sketch.constraints

    assert isinstance(collection, ConstraintCollection)
    assert collection.count == 2
    assert len(collection) == 2
    assert collection.names() == [c.name for c in collection.list()]
    assert [c.type_code for c in collection.list()] == [8, CONSTRAINT_LENGTH]


def test_sketch_constraints_exposes_broken_and_unupdated_counts(
    sketch_factory: Callable[..., Any],
    constraints_factory: Callable[..., FakeConstraints],
) -> None:
    """`broken_count`/`unupdated_count` read straight through to the fake COM object."""
    fake_constraints = constraints_factory(broken_count=2, unupdated_count=1)
    fake_sketch = sketch_factory(constraints=fake_constraints)

    collection = ConstraintCollection(fake_sketch)

    assert collection.broken_count == 2
    assert collection.unupdated_count == 1


def test_sketch_constraints_is_cached_across_accesses(
    part_factory: Callable[..., Any],
) -> None:
    """Matches the caching pattern used by `part.parameters`/`part.sketches`."""
    part_com = part_factory()
    sketch = _sketch(part_com)

    assert sketch.constraints is sketch.constraints


def test_get_returns_the_single_matching_constraint(
    sketch_factory: Callable[..., Any],
    constraint_factory: Callable[..., FakeConstraint],
    constraints_factory: Callable[..., FakeConstraints],
) -> None:
    """`get(name)` finds a constraint by its (COM-assigned) name."""
    target = constraint_factory(name="Length.3", type_code=CONSTRAINT_LENGTH)
    other = constraint_factory(name="Coincidence.8", type_code=CONSTRAINT_COINCIDENT)
    fake_sketch = sketch_factory(constraints=constraints_factory(items=[other, target]))

    found = ConstraintCollection(fake_sketch).get("Length.3")

    assert found.com_object is target


def test_get_missing_name_raises_constraint_not_found(
    sketch_factory: Callable[..., Any],
    constraints_factory: Callable[..., FakeConstraints],
) -> None:
    """A name with no match must raise `ConstraintNotFoundError`, not KeyError/COM error."""
    fake_sketch = sketch_factory(constraints=constraints_factory(items=[]))

    with pytest.raises(ConstraintNotFoundError):
        ConstraintCollection(fake_sketch).get("NoSuchConstraint")


def test_get_ambiguous_name_raises(
    sketch_factory: Callable[..., Any],
    constraint_factory: Callable[..., FakeConstraint],
    constraints_factory: Callable[..., FakeConstraints],
) -> None:
    """Two constraints sharing a name must refuse rather than guess."""
    first = constraint_factory(name="Parallelism.1", type_code=8)
    second = constraint_factory(name="Parallelism.1", type_code=8)
    fake_sketch = sketch_factory(constraints=constraints_factory(items=[first, second]))

    with pytest.raises(AmbiguousNameError):
        ConstraintCollection(fake_sketch).get("Parallelism.1")


def test_collection_len_iter_and_contains(
    sketch_factory: Callable[..., Any],
    constraint_factory: Callable[..., FakeConstraint],
    constraints_factory: Callable[..., FakeConstraints],
) -> None:
    """The collection protocol matches `ParameterCollection`/`SketchCollection`."""
    present = constraint_factory(name="Length.3", type_code=CONSTRAINT_LENGTH)
    fake_sketch = sketch_factory(constraints=constraints_factory(items=[present]))
    collection = ConstraintCollection(fake_sketch)

    assert len(collection) == 1
    assert [c.com_object for c in collection] == [present]
    assert "Length.3" in collection
    assert "NoSuchConstraint" not in collection


# --- outside edition: the trap -----------------------------------------------


def test_constraint_call_outside_edition_surfaces_as_auto3dx_error_mentioning_edit(
    part_factory: Callable[..., Any],
) -> None:
    """The single most important behaviour in this contract.

    Verified (docs/conventions.md 1.2.4): every `AddMonoEltCst`/`AddBiEltCst`
    call raises `com_error` once `CloseEdition()` has run. A raw `com_error`
    must never reach the caller (docs/conventions.md section 4, rule 5), and
    the message must point the caller at `edit()` -- this is the mistake users
    will make most often, so it must not read like a generic COM failure.
    """
    part_com = part_factory()
    sketch = _sketch(part_com)
    sketch.com_object.Constraints.outside_edition = True

    with sketch.edit() as editor:
        line = editor.line(0.0, 0.0, 10.0, 0.0)
        with pytest.raises(Auto3dxError) as caught:
            editor.horizontal(line)

    assert not isinstance(caught.value, pywintypes.com_error)
    assert "edit()" in str(caught.value)


def test_bi_element_constraint_call_outside_edition_also_wraps_the_error(
    part_factory: Callable[..., Any],
) -> None:
    """Same trap, for a two-element constraint call."""
    part_com = part_factory()
    sketch = _sketch(part_com)
    sketch.com_object.Constraints.outside_edition = True

    with sketch.edit() as editor:
        first = editor.line(0.0, 0.0, 10.0, 0.0)
        second = editor.line(0.0, 5.0, 10.0, 5.0)
        with pytest.raises(Auto3dxError) as caught:
            editor.parallel(first, second)

    assert not isinstance(caught.value, pywintypes.com_error)
    assert "edit()" in str(caught.value)


# --- creating constraints never updates the model ----------------------------


def test_creating_constraints_never_calls_part_update(
    part_factory: Callable[..., Any],
) -> None:
    """`SketchEditor` constraint methods must not call `Part.Update()`."""
    part_com = part_factory()
    sketch = _sketch(part_com)

    with sketch.edit() as editor:
        line = editor.line(0.0, 0.0, 10.0, 0.0)
        circle = editor.circle(0.0, 0.0, 4.0)
        second_line = editor.line(0.0, 5.0, 10.0, 5.0)
        editor.horizontal(line)
        editor.vertical(second_line)
        editor.parallel(line, second_line)
        editor.perpendicular(line, second_line)
        editor.coincident(line, second_line)
        editor.tangent(line, circle)
        editor.length(line, 40)
        editor.radius(circle, 9)
        editor.distance(line, second_line, 30)

    assert part_com.update_calls == 0
