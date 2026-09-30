"""Probe 47b: can a topology element be put into the CATIA selection (highlighted)?

One question only. The topology-search restore code records that a raw `Reference` passed
to `Selection.Add` was once silently dropped, while `SelectedElement.Value` objects came
back. Fixture: the block. From one `Search("Topology.Edge,all")` the first hit's
`Reference` and `Value` are kept; then, each marked and counted:
`Clear; Add(Reference); Count` and `Clear; Add(Value); Count`, and for a non-empty
selection `Item(1).Reference.DisplayName` against the edge's own name. Selection only; the
model is read before and after (feature count, IsUpToDate) to show it did not change.

    $env:AUTO3DX_LIVE_PART = "<disposable Part>"
    python -u scripts/probes/47b_highlight_reference_vs_value.py
"""

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

PREFIX = "AUTO3DX_P47B"


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    pad = None
    selection = step("Editor.Selection", lambda: catia.active_editor().Selection)
    try:
        pad, _ = block_fixture(part, f"{PREFIX}_BLOCK")
        step("Selection.Clear", selection.Clear)
        step("Selection.Search('Topology.Edge,all')", lambda: selection.Search("Topology.Edge,all"))
        item = step("Selection.Item(1)", lambda: selection.Item(1))
        reference = step("Item(1).Reference", lambda: item.Reference)
        value = step("Item(1).Value", lambda: item.Value)
        name = step("Reference.DisplayName", lambda: str(reference.DisplayName))
        before = (
            step("MainBody.Shapes.Count", lambda: int(raw.MainBody.Shapes.Count)),
            step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw))),
        )
        for label, obj in (("Reference", reference), ("Value", value)):
            step("Selection.Clear", selection.Clear)
            step(f"Selection.Add({label})", lambda obj=obj: selection.Add(obj), fatal=False)
            count = step("Selection.Count", lambda: int(selection.Count))
            marker(f"[RESULT] Add({label}) -> Count {count}")
            if count:
                back = step(
                    "Item(1).Reference.DisplayName",
                    lambda: str(selection.Item(1).Reference.DisplayName),
                    fatal=False,
                )
                marker(f"[RESULT] Add({label}) selected the same edge: {back == name}")
        step("Selection.Clear", selection.Clear)
        after = (
            step("MainBody.Shapes.Count", lambda: int(raw.MainBody.Shapes.Count)),
            step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw))),
        )
        marker(f"[RESULT] model unchanged by selection: {before == after}")
    finally:
        step("Selection.Clear", selection.Clear, fatal=False)
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        sweep(catia, part, PREFIX)
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
