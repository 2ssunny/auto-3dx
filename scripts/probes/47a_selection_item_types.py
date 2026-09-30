"""Probe 47a: what does a selected item report -- `Type`, and the types of `Value`/`Reference`?

One question only, read-only on a fixture. Fixture: the 60x40x20 block, rebuilt. The
selection is filled by the verified route (`Selection.Search("Topology.Edge,all")`, then
`"Topology.Face,all"`, then `Selection.Add(pad)` and `Selection.Add(sketch)`), and for the
first item of each only these are read, each marked: `Item(1).Type`,
`type(Item(1).Value).__name__`, `type(Item(1).Reference).__name__`,
`Item(1).Reference.DisplayName`. Nothing is stringified: only type names and plain values
are printed. The selection is cleared afterwards (it was empty before, checked).

    $env:AUTO3DX_LIVE_PART = "<disposable Part>"
    python -u scripts/probes/47a_selection_item_types.py
"""

from typing import Any

from _micro import (
    block_fixture,
    delete,
    marker,
    require_blank_target,
    step,
    sweep,
    update_if_needed,
    verify_blank,
)

PREFIX = "AUTO3DX_P47A"


def describe_first(selection: Any, label: str) -> None:
    count = step(f"{label}: Selection.Count", lambda: int(selection.Count))
    marker(f"[RESULT] {label}: {count} item(s)")
    if not count:
        return
    item = step(f"{label}: Selection.Item(1)", lambda: selection.Item(1))
    step(f"{label}: Item(1).Type", lambda: str(item.Type), fatal=False)
    value = step(f"{label}: Item(1).Value", lambda: item.Value, fatal=False)
    if value is not None:
        marker(f"[RESULT] {label}: Value type {type(value).__name__}")
    reference = step(f"{label}: Item(1).Reference", lambda: item.Reference, fatal=False)
    if reference is not None:
        marker(f"[RESULT] {label}: Reference type {type(reference).__name__}")
        step(f"{label}: Reference.DisplayName", lambda: str(reference.DisplayName), fatal=False)


def main() -> None:
    catia, part = require_blank_target()
    pad = sketch = None
    selection = step("Editor.Selection", lambda: catia.active_editor().Selection)
    step("Selection.Count (before, must be 0)", lambda: int(selection.Count))
    try:
        pad, sketch = block_fixture(part, f"{PREFIX}_BLOCK")
        for label, query in (("edges", "Topology.Edge,all"), ("faces", "Topology.Face,all")):
            step("Selection.Clear", selection.Clear)
            step(f"Selection.Search({query!r})", lambda query=query: selection.Search(query))
            describe_first(selection, label)
        for label, obj in (("pad", pad), ("sketch", sketch)):
            step("Selection.Clear", selection.Clear)
            step(f"Selection.Add({label})", lambda obj=obj: selection.Add(obj))
            describe_first(selection, label)
        step("Selection.Clear", selection.Clear)
    finally:
        step("Selection.Clear", selection.Clear, fatal=False)
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        sweep(catia, part, PREFIX)
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
