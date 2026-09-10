"""Tests for Length parameter creation, `ensure`, and removal.

The behaviours pinned here were established by probing a real B428_Cloud
session (see `scripts/probes/11_create_dimension.py`):

    - `CreateDimension` stores the name container-qualified, so the created
      parameter's `name` is not the string that was passed in.
    - A duplicate name is silently ACCEPTED, producing two parameters reporting
      the same name. The library must refuse before reaching COM.
    - An empty name is silently auto-numbered (`Length.3`).
    - A name containing `"\\"` is accepted and becomes indistinguishable from a
      qualified name.
"""

from collections.abc import Callable
from typing import Any

import pytest

from auto_3dx.errors import (
    ParameterAlreadyExistsError,
    ParameterNameError,
    ParameterNotFoundError,
    ParameterTypeError,
    UnsupportedUnitError,
)
from auto_3dx.parameters.collection import ParameterCollection
from auto_3dx.parameters.parameter import LENGTH_MAGNITUDE, Parameter


@pytest.fixture
def empty_collection(
    parameters_collection_factory: Callable[..., Any],
) -> ParameterCollection:
    """A collection with no parameters, as the currently open Part has."""
    return ParameterCollection(parameters_collection_factory([]))


def test_create_length_passes_the_verified_magnitude(
    empty_collection: ParameterCollection,
) -> None:
    """The magnitude must be the capitalised `"Length"`, not `"LENGTH"`."""
    empty_collection.create_length("Span", 25)

    assert empty_collection.com_object.create_calls == [("Span", LENGTH_MAGNITUDE, 25.0)]
    assert LENGTH_MAGNITUDE == "Length"


def test_create_length_returns_a_qualified_name_and_short_name(
    empty_collection: ParameterCollection,
) -> None:
    """`name` keeps CATIA's qualified form; `short_name` gives back the request."""
    created = empty_collection.create_length("Span", 25)

    assert created.name == "3D Shape00422533\\Span"
    assert created.short_name == "Span"


def test_create_length_coerces_int_to_float(
    empty_collection: ParameterCollection,
) -> None:
    """CATIA's `iValue` is a double, so an int must arrive as a float."""
    empty_collection.create_length("Span", 25)

    _, _, value = empty_collection.com_object.create_calls[0]
    assert isinstance(value, float)


def test_create_length_refuses_an_existing_name_without_touching_com(
    parameters_collection_factory: Callable[..., Any],
    fake_length: Any,
) -> None:
    """The duplicate guard must fire before COM, or the model gains a twin.

    CATIA accepts the duplicate and creates a second parameter with the same
    name, so reaching COM at all is the bug.
    """
    raw = parameters_collection_factory([(fake_length.Name, fake_length)])
    collection = ParameterCollection(raw)

    with pytest.raises(ParameterAlreadyExistsError):
        collection.create_length(fake_length.Name, 25)

    assert raw.create_calls == []
    assert collection.count == 1


@pytest.mark.parametrize(
    "name",
    ["", "  ", " Span", "Span ", "Part\\Span", "\\Span"],
)
def test_create_length_rejects_unusable_names(
    empty_collection: ParameterCollection,
    name: str,
) -> None:
    """An empty name is auto-numbered and a backslash forges a qualified name."""
    with pytest.raises(ParameterNameError):
        empty_collection.create_length(name, 25)

    assert empty_collection.com_object.create_calls == []


def test_create_length_rejects_a_non_string_name(
    empty_collection: ParameterCollection,
) -> None:
    """A non-str name must not be stringified into the model."""
    with pytest.raises(ParameterNameError):
        empty_collection.create_length(1, 25)  # type: ignore[arg-type]

    assert empty_collection.com_object.create_calls == []


def test_create_length_rejects_a_bool_value(
    empty_collection: ParameterCollection,
) -> None:
    """`bool` is a subclass of `int`, so it must be refused explicitly."""
    with pytest.raises(ParameterTypeError):
        empty_collection.create_length("Span", True)  # type: ignore[arg-type]

    assert empty_collection.com_object.create_calls == []


def test_create_length_rejects_an_unsupported_unit(
    empty_collection: ParameterCollection,
) -> None:
    """Only millimetres are verified against this installation."""
    with pytest.raises(UnsupportedUnitError):
        empty_collection.create_length("Span", 25, unit="inch")

    assert empty_collection.com_object.create_calls == []


def test_create_length_does_not_update_the_part(
    empty_collection: ParameterCollection,
    part_factory: Callable[..., Any],
) -> None:
    """Creation is batchable; the caller decides when to update."""
    part = part_factory(parameters=empty_collection.com_object)
    empty_collection.create_length("Span", 25)

    assert part.update_calls == 0


def test_ensure_length_creates_when_absent(
    empty_collection: ParameterCollection,
) -> None:
    """A missing name is created."""
    ensured = empty_collection.ensure_length("Span", 25)

    assert ensured.short_name == "Span"
    assert empty_collection.com_object.create_calls == [
        ("Span", LENGTH_MAGNITUDE, 25.0)
    ]


def test_ensure_length_sets_when_present(
    parameters_collection_factory: Callable[..., Any],
    fake_length: Any,
) -> None:
    """An existing Length is updated in place, not duplicated."""
    raw = parameters_collection_factory([(fake_length.Name, fake_length)])
    collection = ParameterCollection(raw)

    ensured = collection.ensure_length(fake_length.Name, 250)

    assert raw.create_calls == []
    assert fake_length.Value == 250.0
    assert ensured.name == fake_length.Name
    assert collection.count == 1


def test_ensure_length_refuses_to_repurpose_another_kind(
    parameters_collection_factory: Callable[..., Any],
    fake_real: Any,
) -> None:
    """A name held by a different kind must not be silently overwritten."""
    raw = parameters_collection_factory([(fake_real.Name, fake_real)])
    collection = ParameterCollection(raw)
    original = fake_real.Value

    with pytest.raises(ParameterTypeError) as caught:
        collection.ensure_length(fake_real.Name, 250)

    assert "Real" in str(caught.value)
    assert fake_real.Value == original
    assert raw.create_calls == []


def test_remove_deletes_by_the_authoritative_name(
    empty_collection: ParameterCollection,
) -> None:
    """Removal must target CATIA's stored name, not the caller's short one."""
    empty_collection.create_length("Span", 25)

    empty_collection.remove("Span")

    assert empty_collection.com_object.remove_calls == ["3D Shape00422533\\Span"]
    assert empty_collection.count == 0


def test_remove_reports_a_missing_name(
    empty_collection: ParameterCollection,
) -> None:
    """A missing name is a lookup failure, not a COM fault."""
    with pytest.raises(ParameterNotFoundError):
        empty_collection.remove("Nope")

    assert empty_collection.com_object.remove_calls == []


def test_short_name_equals_name_when_unqualified(fake_length: Any) -> None:
    """A parameter added through the CATIA f(x) dialog reports a bare name."""
    parameter = Parameter(fake_length)

    assert "\\" not in parameter.name
    assert parameter.short_name == parameter.name


def test_info_carries_both_names(
    empty_collection: ParameterCollection,
) -> None:
    """Structured output exposes the qualified and the short name."""
    created = empty_collection.create_length("Span", 25)

    info = created.info()

    assert info.name == "3D Shape00422533\\Span"
    assert info.short_name == "Span"
    assert info.kind == "Length"
    assert info.value == 25.0
    assert info.unit == "mm"
