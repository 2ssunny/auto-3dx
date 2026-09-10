"""Live creation/ensure/removal round-trip against a running 3DEXPERIENCE session.

Requires an open Part editor. Everything this test creates is removed again in a
`finally` block, and the document is never saved.
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
    ParameterAlreadyExistsError,
    ParameterNotFoundError,
)
from auto_3dx.parameters.parameter import LENGTH_KIND, MILLIMETRE  # noqa: E402

CREATED_NAME = "AUTO3DX_IT_CREATED"
ENSURED_NAME = "AUTO3DX_IT_ENSURED"
INITIAL_VALUE = 25.0
UPDATED_VALUE = 77.0


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


def test_create_ensure_and_remove_round_trip(part) -> None:
    """A created Length survives an update, then is removed without a trace."""
    parameters = part.parameters
    names_before = set(parameters.names())
    for name in (CREATED_NAME, ENSURED_NAME):
        if name in parameters:
            pytest.skip(f"{name} already exists in this model; clean it up first.")

    try:
        created = parameters.create_length(CREATED_NAME, INITIAL_VALUE)
        part.update()

        # CATIA stores a qualified name, so only short_name matches the request.
        assert created.short_name == CREATED_NAME
        assert created.name.endswith(CREATED_NAME)
        assert created.kind == LENGTH_KIND
        assert created.unit == MILLIMETRE
        assert created.value == pytest.approx(INITIAL_VALUE)
        assert CREATED_NAME in parameters

        # CATIA would happily create a second parameter with the same name.
        with pytest.raises(ParameterAlreadyExistsError):
            parameters.create_length(CREATED_NAME, 999.0)
        matching = [
            parameter
            for parameter in parameters.list()
            if parameter.short_name == CREATED_NAME
        ]
        assert len(matching) == 1

        ensured = parameters.ensure_length(CREATED_NAME, UPDATED_VALUE)
        part.update()
        assert ensured.value == pytest.approx(UPDATED_VALUE)

        fresh = parameters.ensure_length(ENSURED_NAME, INITIAL_VALUE)
        part.update()
        assert fresh.short_name == ENSURED_NAME
        assert fresh.value == pytest.approx(INITIAL_VALUE)
    finally:
        for name in (CREATED_NAME, ENSURED_NAME):
            try:
                parameters.remove(name)
            except ParameterNotFoundError:
                pass
        part.update()

    assert set(parameters.names()) == names_before
