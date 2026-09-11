"""Integration smoke test: read, set, update, and restore a real Length parameter.

Requires a running 3DEXPERIENCE session with a Part active in the editor,
containing a Length parameter named `AUTO3DX_TEST_LENGTH`. Run explicitly
with `pytest -m integration`; excluded from the default unit test run.

Save and any PLM propagate API are never called anywhere in this module.
"""

import sys

import pytest

pytestmark = pytest.mark.integration

if sys.platform != "win32":
    pytest.skip("Integration tests require Windows.", allow_module_level=True)

pytest.importorskip("pywintypes", reason="pywin32 is not available.")

from auto_3dx.core.application import Catia  # noqa: E402
from auto_3dx.errors import (  # noqa: E402
    CatiaConnectionError,
    NoActivePartError,
    ParameterNotFoundError,
)

TEST_PARAMETER_NAME = "AUTO3DX_TEST_LENGTH"
TEST_VALUE = 150.0

_MISSING_PART_MESSAGE = (
    "No active Part found. Open a Part (not an assembly) in 3DEXPERIENCE and "
    "try again."
)
_MISSING_PARAMETER_MESSAGE = (
    f"Parameter {TEST_PARAMETER_NAME!r} not found on the active Part. Add a "
    f"Length parameter named {TEST_PARAMETER_NAME!r} to the open Part and try "
    "again."
)


@pytest.fixture
def catia() -> Catia:
    """Attaches to a running 3DEXPERIENCE session, or skips if none is available."""
    try:
        return Catia.attach()
    except CatiaConnectionError as error:
        pytest.skip(f"No running 3DEXPERIENCE session to attach to: {error}")


def test_parameter_roundtrip_set_update_and_restore(catia: Catia) -> None:
    """Sets the test Length parameter, updates the Part, and restores the original value.

    The restore happens in a `finally` block so a failed assertion still
    leaves the model in its original state.
    """
    try:
        part = catia.active_part()
    except NoActivePartError:
        pytest.skip(_MISSING_PART_MESSAGE)

    try:
        parameter = part.parameters.get(TEST_PARAMETER_NAME)
    except ParameterNotFoundError:
        pytest.skip(_MISSING_PARAMETER_MESSAGE)

    original_value = parameter.value

    try:
        parameter.set(TEST_VALUE)
        part.update()

        updated_value = part.parameters.get(TEST_PARAMETER_NAME).value
        assert updated_value == TEST_VALUE
    finally:
        parameter.set(original_value)
        part.update()
