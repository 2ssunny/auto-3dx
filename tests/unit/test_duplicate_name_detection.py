"""Tests that duplicate-name detection survives CATIA's qualified names.

These pin a regression the unit suite missed entirely. `CreateDimension` stores
a container-qualified name, so a parameter created as `"Span"` reports
`"3D Shape1\\Span"`. While the existence check compared only `Parameter.name`
against the requested string, every check against a freshly created parameter
silently found nothing: a second `create_length("Span", ...)` created a second
parameter instead of raising, and `ensure_length` did the same. Every existing
test passed because each one seeded the fake with an already-unqualified name,
which is the one case the comparison happened to get right.

The other half of the contract is that only user parameters are searched. A
feature's own dimensions are exposed under the feature path
(`Pad.1\\FirstLimit\\Length`), so matching their short names would refuse a
legitimate user parameter named `"Length"`.
"""

from collections.abc import Callable
from typing import Any

import pytest

from auto_3dx.errors import (
    AmbiguousNameError,
    ParameterAlreadyExistsError,
    ParameterNameError,
)
from auto_3dx.parameters.collection import ParameterCollection


@pytest.fixture
def empty_collection(
    parameters_collection_factory: Callable[..., Any],
) -> ParameterCollection:
    """A collection with no parameters, as a freshly opened Part has."""
    return ParameterCollection(parameters_collection_factory([]))


def test_create_refuses_a_name_it_just_created_itself(
    empty_collection: ParameterCollection,
) -> None:
    """The name CATIA stored is qualified, but the caller's name still matches."""
    created = empty_collection.create_length("Span", 25.0)
    assert created.name == "3D Shape00422533\\Span"

    with pytest.raises(ParameterAlreadyExistsError):
        empty_collection.create_length("Span", 999.0)

    # Refused before COM, so no second parameter exists.
    assert len(empty_collection.com_object.create_calls) == 1
    assert empty_collection.count == 1


def test_create_refuses_a_qualified_name_outright(
    empty_collection: ParameterCollection,
) -> None:
    """A container separator is a name error, checked before existence is.

    `get` and `remove` accept either form, but creation takes the short name
    only: CATIA would accept the separator and store a parameter whose name is
    indistinguishable from a qualified one.
    """
    empty_collection.create_length("Span", 25.0)

    with pytest.raises(ParameterNameError):
        empty_collection.create_length("3D Shape00422533\\Span", 999.0)
    assert len(empty_collection.com_object.create_calls) == 1


def test_ensure_updates_the_parameter_it_just_created(
    empty_collection: ParameterCollection,
) -> None:
    """`ensure` must find the qualified parameter and set it, not add a second."""
    created = empty_collection.create_length("Span", 25.0)

    ensured = empty_collection.ensure_length("Span", 40.0)

    assert ensured.com_object is created.com_object
    assert ensured.value == pytest.approx(40.0)
    assert len(empty_collection.com_object.create_calls) == 1
    assert empty_collection.count == 1


def test_ensure_called_twice_creates_exactly_one_parameter(
    empty_collection: ParameterCollection,
) -> None:
    """Repeated `ensure` is the idempotent path callers rely on."""
    first = empty_collection.ensure_length("Span", 25.0)
    second = empty_collection.ensure_length("Span", 25.0)

    assert first.com_object is second.com_object
    assert empty_collection.count == 1


def test_create_dimension_refuses_a_name_it_just_created(
    empty_collection: ParameterCollection,
) -> None:
    """The same discipline applies to the non-Length magnitudes."""
    empty_collection.create_dimension("Load", "Mass", 2.0)

    with pytest.raises(ParameterAlreadyExistsError):
        empty_collection.create_dimension("Load", "Mass", 9.0)


def test_create_ignores_a_feature_internal_short_name_collision(
    parameters_collection_factory: Callable[..., Any],
    length_parameter_factory: Callable[..., Any],
) -> None:
    """A pad's own `...\\FirstLimit\\Length` must not block a user's `"Length"`."""
    internal = length_parameter_factory(name="Pad.1\\FirstLimit\\Length", value=10.0)
    collection = ParameterCollection(
        parameters_collection_factory(
            [("Pad.1\\FirstLimit\\Length", internal)],
            direct_items=[],
        )
    )

    created = collection.create_length("Length", 25.0)

    assert created.short_name == "Length"
    assert collection.com_object.create_calls == [("Length", "Length", 25.0)]


def test_two_user_parameters_with_one_name_are_ambiguous(
    parameters_collection_factory: Callable[..., Any],
    length_parameter_factory: Callable[..., Any],
) -> None:
    """CATIA accepts duplicates, so the library must refuse to guess between them."""
    first = length_parameter_factory(name="3D Shape1\\Span", value=10.0)
    second = length_parameter_factory(name="3D Shape1\\Span", value=20.0)
    items = [("3D Shape1\\Span", first), ("3D Shape1\\Span", second)]
    collection = ParameterCollection(
        parameters_collection_factory(items, direct_items=items)
    )

    with pytest.raises(AmbiguousNameError):
        collection.create_length("Span", 30.0)
    with pytest.raises(AmbiguousNameError):
        collection.ensure_length("Span", 30.0)
