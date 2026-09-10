"""Deleting geometry through the editor's selection.

Neither ``Body.Sketches`` nor ``Body.Shapes`` exposes a ``Remove`` method -- both
offer only ``Item``, ``GetItem`` and ``GetBoundary`` (``Sketches`` adds ``Add``).
Verified against the B428_Cloud type library and against a live session, where
``Shapes.Remove`` raises ``AttributeError``.

The only verified way to delete geometry is ``Editor.Selection``:

    Selection.Clear() -> Selection.Add(object) -> Selection.Delete()

That makes deletion an *editor* capability rather than a Part one, so the
collections need the editor's ``Selection`` handed to them. A collection built
without one can still read and create; only deletion is unavailable.
"""

from typing import Any

import pywintypes

from auto_3dx.errors import Auto3dxError

_NO_SELECTION_MESSAGE = (
    "Deleting geometry requires the editor's Selection, which is not "
    "available here. This happens either because the object was constructed "
    "without a selection, or because the current 3DEXPERIENCE session did "
    "not supply one even through Catia.active_part()."
)


def _hresult_suffix(error: pywintypes.com_error) -> str:
    """Renders a COM error's HRESULT as a hex suffix for an error message.

    Args:
        error: The caught `pywintypes.com_error`.

    Returns:
        A string like `" (HRESULT: 0x80020009)"`, or `""` if unavailable.
    """
    hresult = error.args[0] if error.args else None
    if not isinstance(hresult, int):
        return ""
    return f" (HRESULT: {hresult & 0xFFFFFFFF:#010x})"


def require_selection(selection: Any) -> Any:
    """Returns the selection, or explains why deletion is unavailable.

    Args:
        selection: The raw CATIA ``Selection`` COM object, or ``None``.

    Returns:
        The selection unchanged.

    Raises:
        Auto3dxError: If `selection` is ``None``.
    """
    if selection is None:
        raise Auto3dxError(_NO_SELECTION_MESSAGE)
    return selection


def delete_via_selection(selection: Any, com_object: Any, description: str) -> None:
    """Deletes one COM object through the editor's selection.

    The selection is cleared both before and after the delete so a stale
    selection can never widen what gets removed, and so the model is not left
    with the deleted object still selected. A failure of that trailing clear
    is never swallowed: if it is left silent, the caller believes the editor
    is clean when a stale selection actually remains and could widen a later
    delete. When both the delete and the trailing clear fail, the delete
    failure is what gets raised (chained), with a note that the selection may
    still be dirty -- the primary failure must not be masked by the cleanup
    failure.

    Args:
        selection: The raw CATIA ``Selection`` COM object.
        com_object: The raw COM object to delete.
        description: What is being deleted, for the error message (e.g.
            ``"sketch 'Base'"``).

    Raises:
        Auto3dxError: If `selection` is ``None``, the deletion failed, or the
            deletion succeeded but the trailing ``Selection.Clear()`` failed.
    """
    require_selection(selection)
    try:
        selection.Clear()
        selection.Add(com_object)
        selection.Delete()
    except pywintypes.com_error as delete_error:
        delete_suffix = _hresult_suffix(delete_error)
        try:
            selection.Clear()
        except pywintypes.com_error as cleanup_error:
            raise Auto3dxError(
                f"Could not delete {description}.{delete_suffix} The "
                f"selection could also not be cleared afterward"
                f"{_hresult_suffix(cleanup_error)}, so the selection may "
                "still be dirty."
            ) from delete_error
        raise Auto3dxError(f"Could not delete {description}.{delete_suffix}") from delete_error
    else:
        try:
            selection.Clear()
        except pywintypes.com_error as cleanup_error:
            raise Auto3dxError(
                f"Deleted {description}, but the selection could not be "
                f"cleared afterward{_hresult_suffix(cleanup_error)}. The "
                "selection may still be dirty and could widen a later delete."
            ) from cleanup_error
