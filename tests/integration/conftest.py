"""Session-level safety for the live integration suite.

Removal calls (`remove_*`) delete through the editor's `Selection` and clear it, so a
full run used to leave the user's CATIA selection empty: on 2026-09-15 an edge the user
had selected before the run was gone afterwards. This fixture captures the selection
once, clears it so every test starts from the empty selection several tests require, and
restores it when the session ends. CATIA can silently refuse a restore (see
`geometry._topology_search`), so the count is read back and a mismatch is reported as a
warning in the test summary.

The fixture is inert when integration tests are deselected (the default) or no session
is running.
"""

import sys
import warnings
from collections.abc import Iterator
from typing import Any

import pytest


def _live_selection() -> Any:
    """Returns the active editor's raw `Selection`, or `None` without a usable session."""
    if sys.platform != "win32":
        return None
    try:
        import pywintypes

        from auto_3dx import Auto3dxError, Catia
    except ImportError:
        return None
    try:
        return Catia.attach().active_editor().Selection
    except (Auto3dxError, pywintypes.com_error):
        return None


@pytest.fixture(scope="session", autouse=True)
def preserve_user_selection() -> Iterator[None]:
    """Captures and clears the user's selection for the session, then restores it."""
    selection = _live_selection()
    if selection is None:
        yield
        return
    import pywintypes

    try:
        captured = [selection.Item(i).Value for i in range(1, int(selection.Count) + 1)]
    except pywintypes.com_error as error:
        pytest.exit(
            f"Refusing to run: the current CATIA selection could not be read ({error}), so "
            "it could not be restored afterwards.",
            returncode=1,
        )
    selection.Clear()
    try:
        yield
    finally:
        try:
            selection.Clear()
            for value in captured:
                selection.Add(value)
            restored = int(selection.Count)
        except pywintypes.com_error as error:
            warnings.warn(f"Could not restore the user's CATIA selection: {error}", stacklevel=1)
        else:
            if restored != len(captured):
                warnings.warn(
                    f"The user's CATIA selection held {len(captured)} item(s) before the "
                    f"integration run but {restored} after restoring it.",
                    stacklevel=1,
                )
