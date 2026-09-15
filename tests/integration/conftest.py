"""Session-level safety for the live integration suite.

Removal calls (`remove_*`) delete through the editor's `Selection` and clear it, so a
full run used to leave the user's CATIA selection empty: on 2026-09-15 an edge the user
had selected before the run was gone afterwards. Creating a pad also makes the new pad
the In-Work Object, and removing it does not hand the old one back. This fixture
captures the selection and the In-Work Object once, clears the selection so every test
starts from the empty selection several tests require, and restores both when the
session ends. CATIA can silently refuse a restore (see `geometry._topology_search`), so
the result is read back and a mismatch is reported as a warning in the test summary.

The fixture is inert when integration tests are deselected (the default) or no session
is running.
"""

import sys
import warnings
from collections.abc import Iterator
from typing import Any

import pytest


def _live_session() -> "tuple[Any, Any] | None":
    """Returns the active editor's raw `Selection` and raw Part, or `None` without one."""
    if sys.platform != "win32":
        return None
    try:
        import pywintypes

        from auto_3dx import Auto3dxError, Catia
    except ImportError:
        return None
    try:
        catia = Catia.attach()
        return catia.active_editor().Selection, catia.active_part().com_object
    except (Auto3dxError, pywintypes.com_error):
        return None


def _restore_in_work_object(raw_part: Any, original: Any) -> None:
    """Puts the captured In-Work Object back if a test moved it, and checks it."""
    import pywintypes

    try:
        if bool(raw_part.InWorkObject == original):
            return
        raw_part.InWorkObject = original
        restored = bool(raw_part.InWorkObject == original)
    except pywintypes.com_error as error:
        warnings.warn(f"Could not restore the In-Work Object: {error}", stacklevel=1)
        return
    if not restored:
        warnings.warn("The In-Work Object did not return to its original object.", stacklevel=1)


def _restore_selection(selection: Any, captured: "list[Any]") -> None:
    """Puts the captured selection back and checks the count."""
    import pywintypes

    try:
        selection.Clear()
        for value in captured:
            selection.Add(value)
        restored = int(selection.Count)
    except pywintypes.com_error as error:
        warnings.warn(f"Could not restore the user's CATIA selection: {error}", stacklevel=1)
        return
    if restored != len(captured):
        warnings.warn(
            f"The user's CATIA selection held {len(captured)} item(s) before the "
            f"integration run but {restored} after restoring it.",
            stacklevel=1,
        )


@pytest.fixture(scope="session", autouse=True)
def preserve_user_session_state() -> Iterator[None]:
    """Captures the selection and In-Work Object for the session, then restores them."""
    session = _live_session()
    if session is None:
        yield
        return
    import pywintypes

    selection, raw_part = session
    try:
        captured = [selection.Item(i).Value for i in range(1, int(selection.Count) + 1)]
        in_work_object = raw_part.InWorkObject
    except pywintypes.com_error as error:
        pytest.exit(
            f"Refusing to run: the current CATIA selection or In-Work Object could not be "
            f"read ({error}), so it could not be restored afterwards.",
            returncode=1,
        )
    selection.Clear()
    try:
        yield
    finally:
        if in_work_object is not None:
            _restore_in_work_object(raw_part, in_work_object)
        _restore_selection(selection, captured)
