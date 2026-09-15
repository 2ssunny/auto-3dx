"""Unit tests for `auto_3dx.core.application.Catia` and `auto_3dx.core.part.Part`.

See docs/conventions.md sections 6.3 and 6.4.
"""

from collections.abc import Callable
from typing import Any

import pytest

from auto_3dx.core.application import Catia
from auto_3dx.core.part import Part as PartWrapper
from auto_3dx.errors import NoActiveEditorError, NoActivePartError, PartUpdateError
from auto_3dx.parameters.collection import ParameterCollection


def test_catia_active_part_returns_part_wrapper_for_fake_part(
    application_factory: Callable[..., Any],
    editor_factory: Callable[..., Any],
    part_factory: Callable[..., Any],
) -> None:
    """`active_part()` wraps a fake `Part` ActiveObject into a `Part` wrapper."""
    fake_part = part_factory()
    fake_editor = editor_factory(active_object=fake_part)
    fake_app = application_factory(active_editor=fake_editor)

    part = Catia(fake_app).active_part()

    assert isinstance(part, PartWrapper)
    assert part.com_object is fake_part


def test_catia_active_part_assembly_context_raises_no_active_part_error(
    application_factory: Callable[..., Any],
    editor_factory: Callable[..., Any],
    vpm_root_occurrence_factory: Callable[..., Any],
) -> None:
    """An assembly-context ActiveObject raises `NoActivePartError` naming the real type."""
    fake_root = vpm_root_occurrence_factory()
    fake_editor = editor_factory(active_object=fake_root)
    fake_app = application_factory(active_editor=fake_editor)

    with pytest.raises(NoActivePartError) as exc_info:
        Catia(fake_app).active_part()

    assert "VPMRootOccurrence" in str(exc_info.value)


def test_catia_active_editor_none_raises_no_active_editor_error(
    application_factory: Callable[..., Any],
) -> None:
    """`active_editor()` raises `NoActiveEditorError` when `ActiveEditor` is `None`."""
    fake_app = application_factory(active_editor=None)

    with pytest.raises(NoActiveEditorError):
        Catia(fake_app).active_editor()


def test_part_parameters_returns_parameter_collection(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """`Part.parameters` returns a `ParameterCollection` wrapping the raw `Parameters`."""
    fake_parameters = parameters_collection_factory(items=[])
    fake_part = part_factory(parameters=fake_parameters)

    part = PartWrapper(fake_part)

    assert isinstance(part.parameters, ParameterCollection)
    assert part.parameters.com_object is fake_parameters


def test_part_parameters_is_cached_across_accesses(
    part_factory: Callable[..., Any],
    parameters_collection_factory: Callable[..., Any],
) -> None:
    """Accessing `Part.parameters` twice reads the underlying COM property once."""
    fake_parameters = parameters_collection_factory(items=[])
    fake_part = part_factory(parameters=fake_parameters)
    part = PartWrapper(fake_part)

    first = part.parameters
    second = part.parameters

    assert first is second
    assert fake_part.parameters_access_count == 1


def test_part_update_calls_update_once(part_factory: Callable[..., Any]) -> None:
    """`Part.update()` calls the underlying `Update()` exactly once."""
    fake_part = part_factory()
    part = PartWrapper(fake_part)

    part.update()

    assert fake_part.update_calls == 1


def test_part_update_raises_part_update_error_when_update_fails(
    part_factory: Callable[..., Any], com_error_factory: Callable[[], Any]
) -> None:
    """`Part.update()` raises `PartUpdateError` when the underlying `Update()` fails."""
    fake_part = part_factory()
    fake_part.update_exception = com_error_factory()
    part = PartWrapper(fake_part)

    with pytest.raises(PartUpdateError):
        part.update()


def test_part_update_never_calls_save(part_factory: Callable[..., Any]) -> None:
    """`Part.update()` never calls `Save`.

    The fake `Part.Save` raises `AssertionError` unconditionally, so any
    accidental call fails this test loudly rather than silently succeeding.
    """
    fake_part = part_factory()
    part = PartWrapper(fake_part)

    part.update()
