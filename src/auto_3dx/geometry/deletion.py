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

from auto_3dx._com import hresult_of
from auto_3dx.errors import AutomationError, InactivePartError, ValidationError

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
        raise ValidationError(_NO_SELECTION_MESSAGE)
    return selection


def require_active_part(part_com_object: Any) -> None:
    """Refuses a Selection-based operation unless the Part is the active one.

    `Selection.Search` through a non-active Part's editor was observed to search the
    active Part instead (2026-09-17: five open Parts all reported the active Part's
    topology), so Selection-dependent deletion, topology search and visibility are
    refused for any other Part until a verified per-editor path exists.

    The check is `Part.Application.ActiveEditor.ActiveObject == Part`: COM identity of
    Parts is verified live and read `True` only for the active Part, three reads in a
    row, while `ActiveEditor.Selection == selection` read `False` even for the active
    Part and cannot be used.

    Args:
        part_com_object: The raw CATIA `Part`, or `None` when the caller has none (a
            standalone wrapper built without one is not checked).

    Raises:
        InactivePartError: If the Part is not the active one, or that cannot be confirmed.
    """
    if part_com_object is None:
        return
    try:
        application = part_com_object.Application
    except AttributeError:
        # Only a test double lacks `Application`; every CATIA object exposes it.
        return
    except pywintypes.com_error as error:
        raise InactivePartError(
            "Refused: could not confirm that this Part is the active one "
            f"(HRESULT reading Part.Application{_hresult_suffix(error)})."
        ) from error
    try:
        editor = application.ActiveEditor
        active_object = editor.ActiveObject if editor is not None else None
        is_active = active_object is not None and bool(active_object == part_com_object)
    except pywintypes.com_error as error:
        raise InactivePartError(
            "Refused: could not confirm that this Part is the active one"
            f"{_hresult_suffix(error)}."
        ) from error
    if not is_active:
        try:
            name = str(part_com_object.Name)
        except pywintypes.com_error:
            name = "<unknown>"
        raise InactivePartError(
            f"Part {name!r} is not the active Part. Deletion, topology search and "
            "visibility go through the editor's Selection, which acts on the active "
            "editor, so they are refused here. Activate the Part in CATIA and retry."
        )


def delete_via_selection(
    selection: Any, com_object: Any, description: str, part_com_object: Any = None
) -> None:
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
        part_com_object: The raw Part the object belongs to. When given, the deletion
            is refused unless that Part is the active one (`require_active_part`).

    Raises:
        Auto3dxError: If `selection` is ``None``, the deletion failed, or the
            deletion succeeded but the trailing ``Selection.Clear()`` failed.
    """
    require_selection(selection)
    require_active_part(part_com_object)
    try:
        selection.Clear()
        selection.Add(com_object)
        selection.Delete()
    except pywintypes.com_error as delete_error:
        delete_suffix = _hresult_suffix(delete_error)
        try:
            selection.Clear()
        except pywintypes.com_error as cleanup_error:
            raise AutomationError(
                f"Could not delete {description}.{delete_suffix} The "
                f"selection could also not be cleared afterward"
                f"{_hresult_suffix(cleanup_error)}, so the selection may "
                "still be dirty.",
                hresult_of(delete_error),
            ) from delete_error
        raise AutomationError(
            f"Could not delete {description}.{delete_suffix}", hresult_of(delete_error)
        ) from delete_error
    else:
        try:
            selection.Clear()
        except pywintypes.com_error as cleanup_error:
            raise AutomationError(
                f"Deleted {description}, but the selection could not be "
                f"cleared afterward{_hresult_suffix(cleanup_error)}. The "
                "selection may still be dirty and could widen a later delete.",
                hresult_of(cleanup_error),
            ) from cleanup_error
