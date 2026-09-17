"""The one topology search, run so that the user's CATIA selection survives it.

`Selection.Search` is the only verified route from a solid to feature-usable edge and
face references (`docs/conventions.md` section 1.2.2.2), and it works by replacing the
editor's selection with every hit. Left alone, taking a snapshot would throw away
whatever the user had selected in the UI. The contract says a snapshot must not
(`docs/api-design.md` section 7), so the search runs between a capture and a restore:

    values = [Selection.Item(i).Value for i in 1..Count]    # capture
    Clear(); Search(query); Item(i).Reference for each hit  # the verified search
    Clear(); Add(value) for each captured value             # restore
    Count == len(values)                                    # verify

Live evidence (2026-09-15): a selection of a Pad and a sketch, and a selection of six
`PlanarFace` items, both came back in order with the same names and types. A raw
`Reference` handed to `Selection.Add` was silently dropped without an error, so a
restore that does not throw is not trusted: the count is read back and compared.

CATIA can refuse a restore silently. With a solid's faces selected followed by the Pad
that owns them, re-adding the faces succeeded and re-adding the Pad left the count
unchanged. By then the user's selection has already been replaced, so raising would
protect nothing and would only discard a valid snapshot. An incomplete restore after a
successful search is therefore a `SelectionNotRestoredWarning`, not an error. A
selection that cannot even be captured is refused before anything changes.
"""

import warnings
from typing import Any

import pywintypes

from auto_3dx._com import automation_error, format_hresult, hresult_of
from auto_3dx.errors import AutomationError, SelectionNotRestoredWarning
from auto_3dx.geometry.deletion import require_active_part, require_selection

_FIRST_COM_INDEX = 1
_WARNING_STACKLEVEL = 4
"""Points the warning at the caller of `part.topology.edges()` or `faces()`."""


def _capture_selection(selection: Any) -> "list[Any]":
    """Reads the value of every currently selected item, in order.

    Args:
        selection: The raw CATIA `Selection` COM object.

    Returns:
        One raw `SelectedElement.Value` per selected item.

    Raises:
        AutomationError: The selection could not be read. Nothing has been changed:
            the search is refused rather than run against a selection that could not
            be put back.
    """
    try:
        count = int(selection.Count)
        return [
            selection.Item(position).Value
            for position in range(_FIRST_COM_INDEX, count + _FIRST_COM_INDEX)
        ]
    except pywintypes.com_error as error:
        raise AutomationError(
            "Refused to search topology: the current CATIA selection could not be read "
            f"(HRESULT={format_hresult(hresult_of(error))}), so it could not be restored "
            "afterwards. The selection and the model were not changed.",
            hresult_of(error),
        ) from error


def _restore_selection(selection: Any, captured: "list[Any]") -> "str | None":
    """Puts a captured selection back and checks that it actually came back.

    Args:
        selection: The raw CATIA `Selection` COM object.
        captured: The values returned by `_capture_selection`.

    Returns:
        `None` when the selection holds the same number of items as before, or a
        sentence describing what went wrong.
    """
    try:
        selection.Clear()
        for value in captured:
            selection.Add(value)
        restored = int(selection.Count)
    except pywintypes.com_error as error:
        return (
            "the CATIA selection could not be restored "
            f"(HRESULT={format_hresult(hresult_of(error))})"
        )
    if restored != len(captured):
        return (
            f"the CATIA selection held {len(captured)} item(s) before the search but "
            f"{restored} after restoring it"
        )
    return None


def search_references(
    selection: Any, query: str, part_com_object: Any = None
) -> "list[Any]":
    """Runs one topology search and returns its references, preserving the selection.

    Args:
        selection: The raw CATIA `Selection` COM object of the editor editing the Part.
        query: The exact `Selection.Search` query, for example `"Topology.Edge,all"`.
        part_com_object: The raw Part being searched. When given, the search is refused
            unless that Part is the active one (`geometry.deletion.require_active_part`).

    Returns:
        One raw `Reference` per hit, in search order.

    Raises:
        ValidationError: `selection` is `None`.
        AutomationError: The selection could not be captured (nothing was changed),
            or the search failed. The model itself is never changed by a search.

    Warns:
        SelectionNotRestoredWarning: The search succeeded, but the selection did not
            come back exactly. The returned references are still valid.
    """
    require_selection(selection)
    require_active_part(part_com_object)
    captured = _capture_selection(selection)
    try:
        selection.Clear()
        selection.Search(query)
        count = int(selection.Count)
        references = [
            selection.Item(position).Reference
            for position in range(_FIRST_COM_INDEX, count + _FIRST_COM_INDEX)
        ]
    except pywintypes.com_error as search_error:
        problem = _restore_selection(selection, captured)
        failure = automation_error(search_error, f"running Selection.Search({query!r})")
        if problem is not None:
            failure = AutomationError(f"{failure} In addition, {problem}.", failure.hresult)
        raise failure from search_error
    except BaseException:
        # Not a CATIA failure, but the user's selection has already been replaced;
        # put it back on the way out without masking the original exception.
        _restore_selection(selection, captured)
        raise
    problem = _restore_selection(selection, captured)
    if problem is not None:
        warnings.warn(
            f"The topology search succeeded, but {problem}. Re-select in the CATIA UI "
            "if the selection matters; the snapshot is valid and the model was not "
            "changed.",
            SelectionNotRestoredWarning,
            stacklevel=_WARNING_STACKLEVEL,
        )
    return references
