"""Live round-trip for the unit catalogue and the non-Length parameter types.

Only `Length` and `Angle` get a derived COM wrapper type; `Mass`, `Volume` and
every other magnitude arrive as a generic `Dimension`, and the only verified way
to tell those apart is `Dimension.Unit.Magnitude` (`docs/conventions.md` 1.1.2).
These tests pin that behaviour against a real session, since a fake COM object
cannot prove what CATIA actually returns.

They also pin the two refusals that matter: an unknown magnitude is rejected
before any COM call, and a `unit` argument is validated but never used to
convert a value.

Everything created is removed in a `finally`, and the document is never saved.
"""

import sys

import pytest

pytestmark = pytest.mark.integration

if sys.platform != "win32":
    pytest.skip("Windows COM is required.", allow_module_level=True)

pytest.importorskip("pywintypes", reason="pywin32 is required.")

from auto_3dx import Catia  # noqa: E402
from auto_3dx.errors import (  # noqa: E402
    CatiaConnectionError,
    NoActiveEditorError,
    NoActivePartError,
    ParameterNotFoundError,
    UnsupportedMagnitudeError,
    UnsupportedUnitError,
)
from auto_3dx.parameters import ANGLE_KIND, DIMENSION_KIND, LENGTH_KIND  # noqa: E402

ANGLE_NAME = "AUTO3DX_IT_ANGLE"
MASS_NAME = "AUTO3DX_IT_MASS"
VOLUME_NAME = "AUTO3DX_IT_VOLUME"
LENGTH_NAME = "AUTO3DX_IT_LENGTH"


@pytest.fixture
def part():
    """Yields the active Part, skipping when no suitable session is available."""
    try:
        catia = Catia.attach()
    except CatiaConnectionError as error:
        pytest.skip(f"No running 3DEXPERIENCE session: {error}")
    try:
        yield catia.active_part()
    except (NoActiveEditorError, NoActivePartError) as error:
        pytest.skip(f"No Part is being edited: {error}")


def _remove(part, *names: str) -> None:
    """Removes parameters, tolerating any that are already gone."""
    for name in names:
        try:
            part.parameters.remove(name)
        except ParameterNotFoundError:
            pass


def test_unit_catalogue_reports_real_magnitudes(part) -> None:
    """The catalogue enumerates this installation's own unit table."""
    units = part.parameters.units

    magnitudes = units.magnitudes()
    assert "Length" in magnitudes
    assert "Angle" in magnitudes
    assert "Mass" in magnitudes
    # The verified installation reports 339; assert only that it is a real table.
    assert len(magnitudes) > 100

    assert units.supports("Length", "mm")
    assert not units.supports("Length", "kg")
    assert "mm" in units.symbols("Length")
    # An unknown magnitude answers empty rather than raising.
    assert units.units("NotAMagnitude") == []


def test_unitless_types_round_trip(part) -> None:
    """Real, integer, string and boolean parameters carry no unit at all."""
    names = (
        "AUTO3DX_IT_REAL",
        "AUTO3DX_IT_INTEGER",
        "AUTO3DX_IT_STRING",
        "AUTO3DX_IT_BOOLEAN",
    )
    for name in names:
        if name in part.parameters:
            pytest.skip(f"{name} already exists; clean it up first.")

    try:
        real = part.parameters.create_real("AUTO3DX_IT_REAL", 2.5)
        integer = part.parameters.create_integer("AUTO3DX_IT_INTEGER", 7)
        text = part.parameters.create_string("AUTO3DX_IT_STRING", "hello")
        flag = part.parameters.create_boolean("AUTO3DX_IT_BOOLEAN", True)

        assert real.value == pytest.approx(2.5)
        assert integer.value == 7
        assert text.value == "hello"
        assert flag.value is True

        # None of these are dimensional, so they have neither unit nor magnitude.
        for parameter in (real, integer, text, flag):
            assert parameter.unit is None
            assert parameter.magnitude is None

        real.set(4.25)
        integer.set(9)
        text.set("bye")
        flag.set(False)
        assert part.parameters.get("AUTO3DX_IT_REAL").value == pytest.approx(4.25)
        assert part.parameters.get("AUTO3DX_IT_INTEGER").value == 9
        assert part.parameters.get("AUTO3DX_IT_STRING").value == "bye"
        assert part.parameters.get("AUTO3DX_IT_BOOLEAN").value is False
    finally:
        _remove(part, *names)


def test_magnitude_distinguishes_generic_dimensions(part) -> None:
    """A Mass and a Volume are both `Dimension`; only the magnitude separates them."""
    for name in (ANGLE_NAME, MASS_NAME, VOLUME_NAME, LENGTH_NAME):
        if name in part.parameters:
            pytest.skip(f"{name} already exists; clean it up first.")

    try:
        length = part.parameters.create_length(LENGTH_NAME, 10.0)
        angle = part.parameters.create_dimension(ANGLE_NAME, "Angle", 30.0)
        mass = part.parameters.create_dimension(MASS_NAME, "Mass", 2.0)
        volume = part.parameters.create_dimension(VOLUME_NAME, "Volume", 1.0)

        # Length and Angle are the only magnitudes with their own wrapper type.
        assert length.kind == LENGTH_KIND
        assert angle.kind == ANGLE_KIND
        assert mass.kind == DIMENSION_KIND
        assert volume.kind == DIMENSION_KIND

        # So the magnitude is what tells the two generic Dimensions apart.
        assert length.magnitude == "Length"
        assert angle.magnitude == "Angle"
        assert mass.magnitude == "Mass"
        assert volume.magnitude == "Volume"

        # Each one reports the unit CATIA chose for that magnitude.
        assert part.parameters.units.supports("Mass", mass.unit)
        assert part.parameters.units.supports("Volume", volume.unit)

        mass.set(3.0, mass.unit)
        assert part.parameters.get(MASS_NAME).value == pytest.approx(3.0)
    finally:
        _remove(part, ANGLE_NAME, MASS_NAME, VOLUME_NAME, LENGTH_NAME)


def test_unknown_magnitude_is_refused_before_any_com_call(part) -> None:
    """A magnitude absent from the catalogue never reaches CATIA."""
    count_before = part.parameters.count

    with pytest.raises(UnsupportedMagnitudeError):
        part.parameters.create_dimension("AUTO3DX_IT_BOGUS", "NotAMagnitude", 1.0)

    # Refused early means nothing was created, not even a half-built parameter.
    assert part.parameters.count == count_before
    assert "AUTO3DX_IT_BOGUS" not in part.parameters


def test_unit_argument_is_checked_but_never_converts(part) -> None:
    """`set` validates the unit against the magnitude and writes the raw value."""
    if MASS_NAME in part.parameters:
        pytest.skip(f"{MASS_NAME} already exists; clean it up first.")

    try:
        mass = part.parameters.create_dimension(MASS_NAME, "Mass", 2.0)

        # "lb" is a real unit, but CATIA stores this parameter in its own unit
        # and this library never converts, so the mismatch is refused.
        with pytest.raises(UnsupportedUnitError):
            mass.set(4.0, "lb")
        assert part.parameters.get(MASS_NAME).value == pytest.approx(2.0)

        # The parameter's own unit is accepted and the value goes in unchanged.
        mass.set(4.0, mass.unit)
        assert part.parameters.get(MASS_NAME).value == pytest.approx(4.0)
    finally:
        _remove(part, MASS_NAME)
