"""Topology snapshots leave the user's CATIA selection as they found it.

Live evidence (2026-09-15, probe 38 and follow-up checks): capturing
`Selection.Item(i).Value`, searching, then `Clear()` plus `Add(value)` for each
captured value brings back a Pad-and-sketch selection and a six-`PlanarFace`
selection unchanged. A raw `Reference` given to `Add` was silently dropped, which is
why the restore is verified by reading `Count` back.
"""

import warnings
from typing import Any

import pytest
import pywintypes

from auto_3dx._generation import ModelGeneration
from auto_3dx.errors import AutomationError, SelectionNotRestoredWarning, ValidationError
from auto_3dx.geometry._topology_search import search_references
from auto_3dx.geometry.edges import EDGE_SEARCH_QUERY
from auto_3dx.geometry.faces import FACE_SEARCH_QUERY
from auto_3dx.geometry.topology import Topology

_HRESULT = -2147352567


def _com_error() -> pywintypes.com_error:
    return pywintypes.com_error(_HRESULT, "Exception occurred.", None, None)


class _Selected:
    """Fake `SelectedElement`: `Value` for user picks, `Reference` for search hits."""

    def __init__(self, value: Any = None, reference: Any = None) -> None:
        self.Value = value
        self.Reference = reference


class _Selection:
    """Fake `Selection` whose contents really change with Clear/Search/Add."""

    def __init__(self, user_values: "list[Any]", hits: "list[Any]") -> None:
        self.items = [_Selected(value=value) for value in user_values]
        self.hits = hits
        self.calls: list[str] = []
        self.search_error: BaseException | None = None
        self.capture_error: BaseException | None = None
        self.add_error: BaseException | None = None
        self.ignored_adds: set[int] = set()

    @property
    def Count(self) -> int:
        return len(self.items)

    def Item(self, index: int) -> _Selected:
        if self.capture_error is not None:
            raise self.capture_error
        self.calls.append("Item")
        return self.items[index - 1]

    def Clear(self) -> None:
        self.calls.append("Clear")
        self.items = []

    def Search(self, query: str) -> None:
        self.calls.append(f"Search:{query}")
        if self.search_error is not None:
            raise self.search_error
        self.items = [_Selected(reference=hit) for hit in self.hits]

    def Add(self, value: Any) -> None:
        self.calls.append("Add")
        if self.add_error is not None:
            raise self.add_error
        if id(value) in self.ignored_adds:
            return
        self.items.append(_Selected(value=value))


def _values(selection: _Selection) -> "list[Any]":
    return [item.Value for item in selection.items]


@pytest.mark.parametrize(
    ("method", "query"), [("edges", EDGE_SEARCH_QUERY), ("faces", FACE_SEARCH_QUERY)]
)
def test_snapshot_restores_a_non_empty_selection(method: str, query: str) -> None:
    pad, face = object(), object()
    hits = [object(), object(), object()]
    selection = _Selection([pad, face], hits)

    snapshot = getattr(Topology(selection, ModelGeneration()), method)()

    assert [item.com_object for item in snapshot] == hits
    assert _values(selection) == [pad, face]
    assert f"Search:{query}" in selection.calls


def test_empty_selection_is_left_empty() -> None:
    selection = _Selection([], [object()])

    references = search_references(selection, EDGE_SEARCH_QUERY)

    assert len(references) == 1
    assert selection.items == []
    assert "Add" not in selection.calls


def test_capture_happens_before_the_search_changes_anything() -> None:
    pad = object()
    selection = _Selection([pad], [object()])

    search_references(selection, EDGE_SEARCH_QUERY)

    first_clear = selection.calls.index("Clear")
    assert selection.calls[:first_clear] == ["Item"]


def test_unreadable_selection_refuses_the_search() -> None:
    selection = _Selection([object()], [object()])
    selection.capture_error = _com_error()

    with pytest.raises(AutomationError, match="not changed") as raised:
        search_references(selection, EDGE_SEARCH_QUERY)

    assert raised.value.hresult == _HRESULT
    assert selection.calls == []
    assert len(selection.items) == 1


def test_search_failure_still_restores_the_selection() -> None:
    pad = object()
    selection = _Selection([pad], [object()])
    selection.search_error = _com_error()

    with pytest.raises(AutomationError) as raised:
        search_references(selection, FACE_SEARCH_QUERY)

    assert raised.value.hresult == _HRESULT
    assert "In addition" not in str(raised.value)
    assert _values(selection) == [pad]


def test_search_failure_and_restore_failure_are_both_reported() -> None:
    selection = _Selection([object()], [object()])
    selection.search_error = _com_error()
    selection.add_error = _com_error()

    with pytest.raises(AutomationError, match="In addition, the CATIA selection could not"):
        search_references(selection, EDGE_SEARCH_QUERY)


def test_non_com_failure_restores_the_selection_and_propagates_unchanged() -> None:
    pad = object()
    selection = _Selection([pad], [object()])
    selection.search_error = KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        search_references(selection, EDGE_SEARCH_QUERY)

    assert _values(selection) == [pad]


def test_restore_that_raises_warns_and_keeps_the_snapshot() -> None:
    hit = object()
    selection = _Selection([object()], [hit])
    selection.add_error = _com_error()

    with pytest.warns(SelectionNotRestoredWarning, match="could not be restored"):
        references = search_references(selection, EDGE_SEARCH_QUERY)

    assert references == [hit]


def test_silently_dropped_add_warns_and_keeps_the_snapshot() -> None:
    """Live: CATIA ignored `Add(pad)` when the Pad's own faces were already selected."""
    kept, dropped, hit = object(), object(), object()
    selection = _Selection([kept, dropped], [hit])
    selection.ignored_adds.add(id(dropped))

    with pytest.warns(SelectionNotRestoredWarning, match="held 2 item\\(s\\) before the search but 1"):
        references = search_references(selection, EDGE_SEARCH_QUERY)

    assert references == [hit]
    assert _values(selection) == [kept]


def test_exact_restore_does_not_warn() -> None:
    selection = _Selection([object(), object()], [object()])

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        search_references(selection, FACE_SEARCH_QUERY)


def test_missing_selection_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        search_references(None, EDGE_SEARCH_QUERY)


def test_snapshot_does_not_advance_the_generation() -> None:
    generation = ModelGeneration()
    selection = _Selection([object()], [object()])

    Topology(selection, generation).edges()

    assert generation.value == 0
