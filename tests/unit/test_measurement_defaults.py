"""Tests that ordinary measurement needs no raw COM object (`docs/api-design.md` 9).

Measuring used to require `part.measurement.measure(part.com_object.MainBody)`: the
one normal workflow in the SDK that forced a caller through the escape hatch.
`measure()` now defaults to the Part's main body, which live tests had already
measured correctly, and an explicit item still works for anything else.
"""

import warnings
from typing import Any

import pytest
import pywintypes

from auto_3dx.core.part import Part
from auto_3dx.errors import Auto3dxError, ValidationError
from auto_3dx.measurement.inertia import INERTIA_SERVICE_NAME, SolidMeasurement

VOLUME_M3 = 2.88e-05
VOLUME_MM3 = 28800.0
HRESULT_EXCEPTION_OCCURRED = -2147352567


class _Inertia:
    """Fake `Inertia` reporting a 60x40x12 mm block in CATIA's SI units."""

    def GetVolume(self) -> float:  # noqa: N802 - COM method name
        return VOLUME_M3

    def GetArea(self) -> float:  # noqa: N802 - COM method name
        return 0.0

    def GetMass(self) -> float:  # noqa: N802 - COM method name
        return 0.0

    def GetCOGPosition(self) -> "tuple[float, float, float]":  # noqa: N802
        return (0.030, 0.020, 0.006)


class _InertiaService:
    """Fake `InertiaService` recording what it was asked to measure."""

    def __init__(self) -> None:
        self.measured: list[Any] = []

    def GetInertiaElement(self, item: Any) -> _Inertia:  # noqa: N802
        self.measured.append(item)
        return _Inertia()


class _Editor:
    """Fake `Editor` handing out the inertia service."""

    def __init__(self) -> None:
        self.service = _InertiaService()
        self.requested: list[str] = []

    def GetService(self, name: str) -> Any:  # noqa: N802 - COM method name
        self.requested.append(name)
        return self.service


class _RawPart:
    """Fake CATIA `Part` exposing a main body."""

    def __init__(self) -> None:
        self.MainBody = object()
        self.Name = "3D Shape1"


def test_measure_with_no_item_measures_the_default_target() -> None:
    """The default is what ordinary use relies on."""
    editor = _Editor()
    body = object()

    result = SolidMeasurement(editor, lambda: body).measure()

    assert editor.service.measured == [body]
    assert result.volume_mm3 == pytest.approx(VOLUME_MM3)


def test_the_default_target_is_read_at_every_call() -> None:
    """A body replaced after the measurement object was built is still measured."""
    editor = _Editor()
    bodies = iter([object(), object()])
    measurement = SolidMeasurement(editor, lambda: next(bodies))

    measurement.measure()
    measurement.measure()

    assert len(set(map(id, editor.service.measured))) == 2


def test_an_explicit_item_overrides_the_default() -> None:
    """Measuring something other than the main body still works."""
    editor = _Editor()
    default_body = object()
    other = object()

    SolidMeasurement(editor, lambda: default_body).measure(other)

    assert editor.service.measured == [other]


def test_measure_without_an_item_or_default_is_rejected_before_com() -> None:
    """A usage error is a validation error, and nothing reaches CATIA."""
    editor = _Editor()

    with pytest.raises(ValidationError, match="part.measurement"):
        SolidMeasurement(editor).measure()

    assert editor.requested == []


def test_a_com_failure_reading_the_default_target_is_mapped() -> None:
    """Reading `MainBody` can fail in COM, and must not leak `com_error`."""

    def failing_target() -> Any:
        raise pywintypes.com_error(HRESULT_EXCEPTION_OCCURRED, "Exception occurred.", None, None)

    with pytest.raises(Auto3dxError) as caught:
        SolidMeasurement(_Editor(), failing_target).measure()

    assert isinstance(caught.value.__cause__, pywintypes.com_error)


def test_part_measurement_measures_the_main_body_by_default() -> None:
    """`part.measurement.measure()` is the whole ordinary call."""
    raw = _RawPart()
    editor = _Editor()
    part = Part(raw, editor=editor)

    part.measurement.measure()

    assert editor.requested == [INERTIA_SERVICE_NAME]
    assert editor.service.measured == [raw.MainBody]


def test_com_object_is_the_escape_hatch() -> None:
    """The measurement object follows the one escape-hatch name every wrapper uses."""
    editor = _Editor()

    assert SolidMeasurement(editor).com_object is editor


def test_the_old_escape_hatch_name_still_works_but_warns() -> None:
    """The alias keeps existing callers working until 1.0."""
    editor = _Editor()
    measurement = SolidMeasurement(editor)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert measurement.editor_com_object is editor

    assert [warning.category for warning in caught] == [DeprecationWarning]
