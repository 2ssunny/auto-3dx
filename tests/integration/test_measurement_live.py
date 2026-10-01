"""Live integration checks for the read-only measurement API.

The default assertions deliberately do not assume what the user currently has
open in 3DEXPERIENCE.  When the disposable baseline block can be identified
from its own user parameters and a single Pad, the test additionally verifies
that the service's SI volume was converted to cubic millimetres correctly.

This module never creates or deletes model objects, and never saves the Part.
"""

import math
import sys
from typing import Any

import pytest

pytestmark = pytest.mark.integration

if sys.platform != "win32":
    pytest.skip("Windows COM is required.", allow_module_level=True)

pytest.importorskip("pywintypes", reason="pywin32 is required.")

from auto_3dx import Catia  # noqa: E402
from auto_3dx.errors import (  # noqa: E402
    Auto3dxError,
    CatiaConnectionError,
    NoActiveEditorError,
    NoActivePartError,
)

_BASELINE_PARAMETER_NAMES = ("AUTO3DX_WIDTH", "AUTO3DX_HEIGHT", "AUTO3DX_THICKNESS")


@pytest.fixture
def part() -> Any:
    """Yield the active Part, skipping when no usable session is available."""
    try:
        catia = Catia.attach()
    except CatiaConnectionError as error:
        pytest.skip(f"No running 3DEXPERIENCE session: {error}")

    try:
        active_part = catia.active_part()
    except (NoActiveEditorError, NoActivePartError) as error:
        pytest.skip(f"No Part is being edited: {error}")
    return active_part


def _identified_baseline_volume(part: Any) -> float | None:
    """Return the expected baseline volume when the open model proves it is safe.

    The parameter names are project-local conventions, so a missing name,
    duplicate name, non-positive value, extra shape, or non-single-Pad model
    simply means that the generic measurement assertions should be used.
    No COM failure encountered while trying to identify the optional baseline
    is allowed to turn an otherwise useful generic measurement test into a
    false failure.
    """
    try:
        user_parameters = part.parameters.user_parameters()
        values: dict[str, float] = {}
        for parameter_name in _BASELINE_PARAMETER_NAMES:
            matches = [
                parameter
                for parameter in user_parameters
                if parameter.short_name == parameter_name or parameter.name == parameter_name
            ]
            if len(matches) != 1:
                return None
            value = float(matches[0].value)
            if not math.isfinite(value) or value <= 0.0:
                return None
            values[parameter_name] = value

        body = part.com_object.MainBody
        if body.Shapes.Count != 1:
            return None
        pads = part.part_design.pads
        if len(pads) != 1:
            return None
        if not math.isclose(
            pads[0].height,
            values["AUTO3DX_THICKNESS"],
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            return None
    except (Auto3dxError, AttributeError, TypeError, ValueError):
        return None

    return (
        values["AUTO3DX_WIDTH"]
        * values["AUTO3DX_HEIGHT"]
        * values["AUTO3DX_THICKNESS"]
    )


def test_measurement_reports_coherent_values_and_safe_unit_conversion(part: Any) -> None:
    """Measure the active solid and verify units without assuming its identity."""
    body = part.com_object.MainBody
    if int(body.Shapes.Count) == 0:
        pytest.skip("The main body is empty; CATIA cannot measure it.")
    measurement = part.measurement

    properties = measurement.measure(body)
    assert math.isfinite(properties.volume_mm3)
    assert math.isfinite(properties.area_mm2)
    assert math.isfinite(properties.mass_kg)
    assert properties.volume_mm3 > 0.0
    assert properties.area_mm2 > 0.0
    assert properties.mass_kg >= 0.0
    assert len(properties.cog_mm) == 3
    assert all(math.isfinite(value) for value in properties.cog_mm)

    # The service is read-only and deterministic for an unchanged model.
    repeated = measurement.measure(body)
    assert repeated.volume_mm3 == pytest.approx(properties.volume_mm3)
    assert repeated.area_mm2 == pytest.approx(properties.area_mm2)
    assert repeated.mass_kg == pytest.approx(properties.mass_kg)
    assert repeated.cog_mm == pytest.approx(properties.cog_mm)

    expected_volume = _identified_baseline_volume(part)
    if expected_volume is not None:
        # The parameters are in mm and the public measurement field is mm3;
        # this condition is what makes the conversion assertion model-safe.
        assert properties.volume_mm3 == pytest.approx(expected_volume, rel=1e-9, abs=1e-6)
