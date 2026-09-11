"""Tests for wiring editor-hosted measurement services into ``Part``."""

from collections.abc import Callable
from typing import Any

import pytest

from auto_3dx.core.application import Catia
from auto_3dx.core.part import Part
from auto_3dx.errors import NoActiveEditorError
from auto_3dx.measurement import SolidMeasurement


def test_active_part_passes_its_editor_to_measurement(
    application_factory: Callable[..., Any],
    editor_factory: Callable[..., Any],
    part_factory: Callable[..., Any],
) -> None:
    """The measurement service must come from the Part's own editor."""
    fake_part = part_factory()
    fake_editor = editor_factory(active_object=fake_part)
    application = application_factory(active_editor=fake_editor)

    part = Catia(application).active_part()

    assert isinstance(part.measurement, SolidMeasurement)
    assert part.measurement.editor_com_object is fake_editor


def test_part_measurement_is_cached(
    editor_factory: Callable[..., Any],
    part_factory: Callable[..., Any],
) -> None:
    """Repeated access returns the same wrapper without rebuilding it."""
    fake_editor = editor_factory(active_object=part_factory())
    part = Part(fake_editor.ActiveObject, editor=fake_editor)

    assert part.measurement is part.measurement


def test_direct_part_without_editor_refuses_measurement(
    part_factory: Callable[..., Any],
) -> None:
    """A directly wrapped Part must not guess which editor owns it."""
    part = Part(part_factory())

    with pytest.raises(NoActiveEditorError, match="Editor.GetService"):
        _ = part.measurement


def test_each_listed_part_keeps_its_own_measurement_editor(
    application_factory: Callable[..., Any],
    editors_factory: Callable[..., Any],
    editor_factory: Callable[..., Any],
    part_factory: Callable[..., Any],
) -> None:
    """Listing or naming Parts must not cross-wire editor-hosted services."""
    first_editor = editor_factory(
        active_object=part_factory(name="First Part"),
        name="Editor1",
    )
    second_editor = editor_factory(
        active_object=part_factory(name="Second Part"),
        name="Editor2",
    )
    application = application_factory(
        editors=editors_factory(items=[first_editor, second_editor])
    )
    catia = Catia(application)

    parts = catia.parts()

    assert parts[0].measurement.editor_com_object is first_editor
    assert parts[1].measurement.editor_com_object is second_editor
    assert catia.part_named("Second Part").measurement.editor_com_object is second_editor
