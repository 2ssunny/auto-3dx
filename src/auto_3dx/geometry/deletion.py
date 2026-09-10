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
    "Deleting geometry requires the editor's Selection, which this object was "
    "not given. Obtain the Part through Catia.active_part() so the editor's "
    "Selection is wired in."
)


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
    with the deleted object still selected.

    Args:
        selection: The raw CATIA ``Selection`` COM object.
        com_object: The raw COM object to delete.
        description: What is being deleted, for the error message (e.g.
            ``"sketch 'Base'"``).

    Raises:
        Auto3dxError: If `selection` is ``None`` or the deletion failed.
    """
    require_selection(selection)
    try:
        selection.Clear()
        selection.Add(com_object)
        selection.Delete()
    except pywintypes.com_error as error:
        hresult = error.args[0] if error.args else None
        suffix = (
            f" (HRESULT: {hresult & 0xFFFFFFFF:#010x})"
            if isinstance(hresult, int)
            else ""
        )
        raise Auto3dxError(f"Could not delete {description}.{suffix}") from error
    finally:
        # Leaving the deleted object selected would affect the next delete.
        try:
            selection.Clear()
        except pywintypes.com_error:
            pass
