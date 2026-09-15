"""Tests for `auto_3dx.measurement.inertia`.

Fakes and fixtures are defined here rather than in `tests/conftest.py`
(off-limits for this layer) -- the existing conftest fixtures cover parameter/
sketch/feature COM shapes, not the Editor/InertiaService shapes this module
needs.

Verified against a live B428_Cloud session (`scripts/probes/30_measurement.py`):
a measured 60x40x12 mm block read `volume=2.88e-05 m3`,
`cog=(0.030, 0.020, 0.006) m` -- exactly 28800 mm3 at (30, 20, 6) mm. That
concrete case pins the SI-to-millimetre conversion below.

`InertiaBoxService` is not covered here because it is not part of the API: the
same `GetBoundingBox` call that once returned a real box later returned all
zeros on the same unchanged model, so it was removed rather than shipped.
"""

from typing import Any

import pytest
import pywintypes

from auto_3dx.errors import Auto3dxError
from auto_3dx.measurement.inertia import (
    INERTIA_SERVICE_NAME,
    MassProperties,
    SolidMeasurement,
)

# --- Fakes -------------------------------------------------------------------


def make_com_error() -> pywintypes.com_error:
    """Builds a realistic `pywintypes.com_error`, as raised by a failed COM call.

    Mirrors `tests/conftest.py::make_com_error` (duplicated here rather than
    imported, since this module owns its own fixtures per the task's file
    boundaries).
    """
    return pywintypes.com_error(
        -2147352567,
        "Exception occurred.",
        (0, "CATIAInertia", "The method failed", None, 0, -2147467259),
        None,
    )


class _NoUpdateOrSave:
    """Base fake that fails the test if `Update`/`Save`/`PLMPropagate` is ever called.

    None of `SolidMeasurement`'s methods have any business calling these --
    measurement is read-only -- so any subclass inheriting this and getting
    one of these calls proves a regression.
    """

    def Update(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("SolidMeasurement must never call Update().")

    def Save(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("SolidMeasurement must never call Save().")

    def PLMPropagate(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("SolidMeasurement must never call PLMPropagate().")


class FakeInertia(_NoUpdateOrSave):
    """Fake `Inertia` COM object: fixed volume/area/mass/COG, all in metres/kg."""

    def __init__(
        self,
        volume_m3: float,
        area_m2: float,
        mass_kg: float,
        cog_m: "tuple[float, float, float]",
    ) -> None:
        self._volume_m3 = volume_m3
        self._area_m2 = area_m2
        self._mass_kg = mass_kg
        self._cog_m = cog_m

    def GetVolume(self) -> float:  # noqa: N802 - COM method name
        return self._volume_m3

    def GetArea(self) -> float:  # noqa: N802 - COM method name
        return self._area_m2

    def GetMass(self) -> float:  # noqa: N802 - COM method name
        return self._mass_kg

    def GetCOGPosition(self) -> "tuple[float, float, float]":  # noqa: N802
        # pywin32 returns the three "out" parameters as a tuple rather than
        # mutating anything -- this fake mirrors that verified behaviour.
        return self._cog_m


class FakeInertiaService(_NoUpdateOrSave):
    """Fake `InertiaService`: hands back one fixed `FakeInertia`, or raises."""

    def __init__(self, inertia: Any = None, failure: BaseException | None = None) -> None:
        self._inertia = inertia
        self._failure = failure
        self.calls: "list[Any]" = []

    def GetInertiaElement(self, item: Any) -> Any:  # noqa: N802 - COM method name
        self.calls.append(item)
        if self._failure is not None:
            raise self._failure
        return self._inertia


class FakeEditor(_NoUpdateOrSave):
    """Fake `Editor` COM object: routes `GetService` to whichever fakes are configured."""

    def __init__(
        self,
        inertia_service: Any = None,
        service_failure: BaseException | None = None,
    ) -> None:
        self._services = {INERTIA_SERVICE_NAME: inertia_service}
        self._service_failure = service_failure
        self.get_service_calls: "list[str]" = []

    def GetService(self, name: str) -> Any:  # noqa: N802 - COM method name
        self.get_service_calls.append(name)
        if self._service_failure is not None:
            raise self._service_failure
        return self._services.get(name)


# A dummy "selectable" item -- SolidMeasurement never inspects it, only
# passes it through, so any sentinel object plays this role.
SOME_BODY = object()


# --- measure() ----------------------------------------------------------------


def test_measure_converts_si_units_for_the_verified_block() -> None:
    """The live-verified 60x40x12 mm block: 2.88e-05 m3 -> 28800 mm3, COG in mm."""
    inertia = FakeInertia(
        volume_m3=2.88e-05,
        area_m2=0.0,
        mass_kg=0.0,
        cog_m=(0.030, 0.020, 0.006),
    )
    editor = FakeEditor(inertia_service=FakeInertiaService(inertia))
    measurement = SolidMeasurement(editor)

    result = measurement.measure(SOME_BODY)

    assert result == MassProperties(
        volume_mm3=28800.0,
        area_mm2=0.0,
        mass_kg=0.0,
        cog_mm=(30.0, 20.0, 6.0),
    )


def test_measure_converts_area_and_passes_mass_through_unconverted() -> None:
    """Area scales by 1e6 (mm2/m2); mass has no length dimension to convert."""
    inertia = FakeInertia(
        volume_m3=1.0,
        area_m2=0.01,
        mass_kg=2.5,
        cog_m=(0.0, 0.0, 0.0),
    )
    editor = FakeEditor(inertia_service=FakeInertiaService(inertia))
    measurement = SolidMeasurement(editor)

    result = measurement.measure(SOME_BODY)

    assert result.area_mm2 == pytest.approx(10_000.0)
    assert result.mass_kg == pytest.approx(2.5)


def test_measure_passes_the_item_through_to_get_inertia_element() -> None:
    inertia = FakeInertia(volume_m3=0.0, area_m2=0.0, mass_kg=0.0, cog_m=(0.0, 0.0, 0.0))
    service = FakeInertiaService(inertia)
    editor = FakeEditor(inertia_service=service)
    measurement = SolidMeasurement(editor)

    measurement.measure(SOME_BODY)

    assert service.calls == [SOME_BODY]


def test_get_service_is_called_with_the_verified_inertia_service_name() -> None:
    inertia = FakeInertia(volume_m3=0.0, area_m2=0.0, mass_kg=0.0, cog_m=(0.0, 0.0, 0.0))
    editor = FakeEditor(inertia_service=FakeInertiaService(inertia))
    measurement = SolidMeasurement(editor)

    measurement.measure(SOME_BODY)

    assert editor.get_service_calls == [INERTIA_SERVICE_NAME]


def test_inertia_service_is_fetched_once_and_cached() -> None:
    """Re-fetching the service on every call would be a wasted COM round trip."""
    inertia = FakeInertia(volume_m3=0.0, area_m2=0.0, mass_kg=0.0, cog_m=(0.0, 0.0, 0.0))
    editor = FakeEditor(inertia_service=FakeInertiaService(inertia))
    measurement = SolidMeasurement(editor)

    measurement.measure(SOME_BODY)
    measurement.measure(SOME_BODY)

    assert editor.get_service_calls == [INERTIA_SERVICE_NAME]


# --- COM error mapping --------------------------------------------------------


def test_get_service_com_error_is_wrapped_for_measure() -> None:
    editor = FakeEditor(service_failure=make_com_error())
    measurement = SolidMeasurement(editor)

    with pytest.raises(Auto3dxError):
        measurement.measure(SOME_BODY)



def test_missing_inertia_service_is_reported_as_auto3dx_error() -> None:
    measurement = SolidMeasurement(FakeEditor())

    with pytest.raises(Auto3dxError, match="InertiaService"):
        measurement.measure(SOME_BODY)



def test_malformed_cog_is_reported_as_auto3dx_error() -> None:
    inertia = FakeInertia(1.0, 1.0, 1.0, (0.0, 0.0))
    measurement = SolidMeasurement(
        FakeEditor(inertia_service=FakeInertiaService(inertia))
    )

    with pytest.raises(Auto3dxError, match="mass-property"):
        measurement.measure(SOME_BODY)



def test_get_inertia_element_com_error_is_wrapped() -> None:
    service = FakeInertiaService(failure=make_com_error())
    editor = FakeEditor(inertia_service=service)
    measurement = SolidMeasurement(editor)

    with pytest.raises(Auto3dxError):
        measurement.measure(SOME_BODY)



def test_com_error_never_escapes_measure() -> None:
    """A COM failure surfaces as Auto3dxError, never as the raw com_error."""
    service = FakeInertiaService(failure=make_com_error())
    editor = FakeEditor(inertia_service=service)
    measurement = SolidMeasurement(editor)

    try:
        measurement.measure(SOME_BODY)
    except pywintypes.com_error:
        pytest.fail("pywintypes.com_error escaped measure() unwrapped.")
    except Auto3dxError:
        pass



# --- no Update()/Save()/PLMPropagate() ----------------------------------------


def test_measure_never_calls_update_or_save() -> None:
    """If SolidMeasurement ever called Update/Save/PLMPropagate, the fakes would raise."""
    inertia = FakeInertia(volume_m3=1.0, area_m2=1.0, mass_kg=1.0, cog_m=(0.0, 0.0, 0.0))
    editor = FakeEditor(inertia_service=FakeInertiaService(inertia))
    measurement = SolidMeasurement(editor)

    # No AssertionError from _NoUpdateOrSave means none of those methods fired.
    measurement.measure(SOME_BODY)


