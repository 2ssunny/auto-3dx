"""Unit tests for `auto_3dx.parameters.collection.ParameterCollection`.

See docs/conventions.md section 6.6: the underlying CATIA `Parameters`
collection is 1-based, and an empty collection (`Count == 0`) is a normal,
valid state -- not an error.
"""

from collections.abc import Callable
from typing import Any

import pytest

from auto_3dx.errors import ParameterNotFoundError
from auto_3dx.parameters.collection import ParameterCollection
from auto_3dx.parameters.parameter import Parameter


def test_collection_count_reflects_fake_collection(
    parameters_collection_factory: Callable[..., Any],
    length_parameter_factory: Callable[..., Any],
) -> None:
    """`count` mirrors the underlying `Parameters.Count`."""
    fake = parameters_collection_factory(
        items=[("A", length_parameter_factory(name="A")), ("B", length_parameter_factory(name="B"))]
    )
    collection = ParameterCollection(fake)

    assert collection.count == 2


def test_collection_len_reflects_fake_collection(
    parameters_collection_factory: Callable[..., Any],
    length_parameter_factory: Callable[..., Any],
) -> None:
    """`__len__` mirrors `count`."""
    fake = parameters_collection_factory(items=[("A", length_parameter_factory(name="A"))])
    collection = ParameterCollection(fake)

    assert len(collection) == 1


def test_collection_list_uses_1_based_item_indices(
    parameters_collection_factory: Callable[..., Any],
    length_parameter_factory: Callable[..., Any],
) -> None:
    """`list()` calls `Item(1)` and `Item(2)` for a 2-element collection, never `Item(0)`.

    This pins the off-by-one trap: the CATIA `Parameters` collection is
    1-based, unlike a Python list.
    """
    first = length_parameter_factory(name="A")
    second = length_parameter_factory(name="B")
    fake = parameters_collection_factory(items=[("A", first), ("B", second)])
    collection = ParameterCollection(fake)

    result = collection.list()

    assert fake.item_calls == [1, 2]
    assert 0 not in fake.item_calls
    assert [p.com_object for p in result] == [first, second]


def test_collection_list_empty_collection_returns_empty_list_without_raising(
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """`Count == 0` returns `[]` and does not raise.

    This is a real current state of the open model (a Part with no
    parameters yet), not a hypothetical edge case.
    """
    fake = parameters_collection_factory(items=[])
    collection = ParameterCollection(fake)

    assert collection.list() == []
    assert fake.item_calls == []


def test_collection_get_missing_name_raises_parameter_not_found_error(
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """`get("missing")` raises `ParameterNotFoundError`."""
    fake = parameters_collection_factory(items=[])
    collection = ParameterCollection(fake)

    with pytest.raises(ParameterNotFoundError):
        collection.get("missing")


def test_collection_names_returns_names_in_list_order(
    parameters_collection_factory: Callable[..., Any],
    length_parameter_factory: Callable[..., Any],
) -> None:
    """`names()` returns each parameter's `name`, in `list()` order."""
    fake = parameters_collection_factory(
        items=[("A", length_parameter_factory(name="A")), ("B", length_parameter_factory(name="B"))]
    )
    collection = ParameterCollection(fake)

    assert collection.names() == ["A", "B"]


def test_collection_contains_existing_name_is_true(
    parameters_collection_factory: Callable[..., Any],
    length_parameter_factory: Callable[..., Any],
) -> None:
    """`__contains__` is `True` for a name that exists."""
    fake = parameters_collection_factory(items=[("A", length_parameter_factory(name="A"))])
    collection = ParameterCollection(fake)

    assert "A" in collection


def test_collection_contains_missing_name_is_false(
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """`__contains__` is `False` for a name that does not exist."""
    fake = parameters_collection_factory(items=[])
    collection = ParameterCollection(fake)

    assert "missing" not in collection


def test_collection_contains_non_str_argument_is_false(
    parameters_collection_factory: Callable[..., Any],
    length_parameter_factory: Callable[..., Any],
) -> None:
    """`__contains__` returns `False` (not an error) for a non-`str` argument."""
    fake = parameters_collection_factory(items=[("A", length_parameter_factory(name="A"))])
    collection = ParameterCollection(fake)

    assert 123 not in collection
    assert None not in collection


def test_collection_iter_yields_parameter_wrappers(
    parameters_collection_factory: Callable[..., Any],
    length_parameter_factory: Callable[..., Any],
) -> None:
    """`__iter__` yields `Parameter` wrappers in `list()` order."""
    fake = parameters_collection_factory(
        items=[("A", length_parameter_factory(name="A")), ("B", length_parameter_factory(name="B"))]
    )
    collection = ParameterCollection(fake)

    items = list(collection)

    assert all(isinstance(item, Parameter) for item in items)
    assert [item.name for item in items] == ["A", "B"]


def test_collection_set_delegates_to_parameter_and_does_not_call_update(
    parameters_collection_factory: Callable[..., Any],
    length_parameter_factory: Callable[..., Any],
    part_factory: Callable[..., Any],
) -> None:
    """`set(name, value)` delegates to the parameter and never calls `Part.Update()`."""
    fake_length = length_parameter_factory(name="A", value=10.0)
    fake = parameters_collection_factory(items=[("A", fake_length)])
    collection = ParameterCollection(fake)
    part = part_factory()

    collection.set("A", 150)

    assert fake_length.Value == 150.0
    assert part.update_calls == 0
