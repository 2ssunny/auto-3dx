"""Tests separating user parameters from CATIA's feature-internal ones.

Verified on a live session after creating one pad from one rectangular sketch:

    Parameters.Count                        = 18
    RootParameterSet.DirectParameters.Count = 3

The 15 extra entries are the feature's own dimensions
(`<Pad>\\FirstLimit\\Length`, `<Sketch>\\Coincidence.3\\Activity`, ...). They
are meaningful -- a formula driving pad thickness targets one of them -- so they
stay reachable through `list()`; they are just not the answer to "which
parameters does this Part have?".
"""

from collections.abc import Callable
from typing import Any

from auto_3dx.parameters.collection import ParameterCollection

USER_NAME = "AUTO3DX_WIDTH"
INTERNAL_NAME = "3D Shape1\\PartBody\\Pad.1\\FirstLimit\\Length"


def test_user_parameters_excludes_feature_internals(
    parameters_collection_factory: Callable[..., Any],
    length_parameter_factory: Callable[..., Any],
) -> None:
    """The feature-internal entry is in `list()` but not in `user_parameters()`."""
    internal = length_parameter_factory(name=INTERNAL_NAME, value=12.0)
    raw = parameters_collection_factory(
        items=[(INTERNAL_NAME, internal)],
        direct_items=[],
    )
    collection = ParameterCollection(raw)
    created = collection.create_length(USER_NAME, 60)

    assert collection.count == 2
    assert [p.name for p in collection.user_parameters()] == [created.name]


def test_user_names_returns_short_names(
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """Callers think in short names, not container-qualified ones."""
    collection = ParameterCollection(parameters_collection_factory(items=[]))
    collection.create_length(USER_NAME, 60)

    assert collection.user_names() == [USER_NAME]


def test_user_parameters_is_empty_for_a_bare_part(
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """A Part with only feature internals has no user parameters."""
    internal = type("Length", (), {"Name": INTERNAL_NAME, "Value": 12.0})()
    raw = parameters_collection_factory(
        items=[(INTERNAL_NAME, internal)],
        direct_items=[],
    )
    collection = ParameterCollection(raw)

    assert collection.count == 1
    assert collection.user_parameters() == []
    assert collection.user_names() == []


def test_created_parameters_appear_in_both_views(
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """An explicitly created parameter is a user parameter AND in the full list."""
    collection = ParameterCollection(parameters_collection_factory(items=[]))
    created = collection.create_length(USER_NAME, 60)

    assert created.name in [p.name for p in collection.list()]
    assert created.name in [p.name for p in collection.user_parameters()]


def test_internal_parameters_stay_reachable_by_name(
    parameters_collection_factory: Callable[..., Any],
    length_parameter_factory: Callable[..., Any],
) -> None:
    """Formulas target feature-internal parameters, so lookup must still work."""
    internal = length_parameter_factory(name=INTERNAL_NAME, value=12.0)
    raw = parameters_collection_factory(
        items=[(INTERNAL_NAME, internal)],
        direct_items=[],
    )
    collection = ParameterCollection(raw)

    found = collection.get(INTERNAL_NAME)

    assert found.value == 12.0
    assert found.short_name == "Length"
