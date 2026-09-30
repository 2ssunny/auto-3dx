"""Probe 47j (interactive): what does a HUMAN selection made in the CATIA UI look like?

One question per run: `python -u 47j_human_selection.py edge|face|feature`. Fixture: the
block. The probe clears the selection, prints what to click, and polls `Selection.Count`
(a read) every two seconds, for up to three minutes, printing a marker only when the count
changes. When something is selected it reads, for every item, only: `Type`,
`type(Value).__name__`, `type(Reference).__name__`, `Reference.DisplayName`, and whether
that name occurs in a fresh Part-wide edge/face snapshot of the same unchanged model -- the
link a public `Edge`/`Face` wrapper would be built from. The selection is cleared at the end.

    $env:AUTO3DX_LIVE_PART = "<disposable Part>"
    python -u scripts/probes/47j_human_selection.py edge
"""

import sys
import time

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

PREFIX = "AUTO3DX_P47J"
WAIT_SECONDS, POLL_SECONDS = 180, 2
WHAT = {
    "edge": "ONE EDGE of the block (click an edge in the 3D view)",
    "face": "ONE FACE of the block (click a face in the 3D view)",
    "feature": "the pad AUTO3DX_P47J_BLOCK in the specification tree",
}


def main() -> None:
    kind = sys.argv[1] if len(sys.argv) > 1 else "edge"
    if kind not in WHAT:
        sys.exit(f"choose one of {sorted(WHAT)}")
    catia, part = require_blank_target()
    pad = None
    selection = step("Editor.Selection", lambda: catia.active_editor().Selection)
    try:
        pad, _ = block_fixture(part, f"{PREFIX}_BLOCK")
        edges = step(
            "[composite, verified] topology.edges(body=None)",
            lambda: part.topology.edges(body=None),
        )
        faces = step(
            "[composite, verified] topology.faces(body=None)",
            lambda: part.topology.faces(body=None),
        )
        known = {edge.descriptor: "edge" for edge in edges}
        known.update({face.descriptor: "face" for face in faces})
        step("Selection.Clear", selection.Clear)
        marker(f"[HUMAN] In CATIA, select {WHAT[kind]} now. Waiting up to {WAIT_SECONDS} s.")
        deadline, last = time.monotonic() + WAIT_SECONDS, 0
        count = 0
        while time.monotonic() < deadline:
            count = int(selection.Count)
            if count != last:
                marker(f"[POLL] Selection.Count = {count}")
                last = count
            if count:
                time.sleep(POLL_SECONDS)  # let a multi-click selection settle
                count = step("Selection.Count (settled)", lambda: int(selection.Count))
                break
            time.sleep(POLL_SECONDS)
        if not count:
            marker("[RESULT] nothing was selected in time")
            return
        for index in range(1, count + 1):
            item = step(f"Selection.Item({index})", lambda index=index: selection.Item(index))
            step("Item.Type", lambda item=item: str(item.Type), fatal=False)
            value = step("Item.Value", lambda item=item: item.Value, fatal=False)
            if value is not None:
                marker(f"[RESULT] Value type {type(value).__name__}")
            reference = step("Item.Reference", lambda item=item: item.Reference, fatal=False)
            if reference is not None:
                marker(f"[RESULT] Reference type {type(reference).__name__}")
                name = step(
                    "Reference.DisplayName", lambda r=reference: str(r.DisplayName), fatal=False
                )
                marker(f"[RESULT] in the fresh snapshot as: {known.get(name, 'NOT FOUND')}")
        items = step(
            "[composite] part.selection.items()", lambda: part.selection.items(), fatal=False
        )
        for selected in items or []:
            marker(f"[RESULT] SDK: {selected.kind} -> {selected.describe()}")
    finally:
        step("Selection.Clear", selection.Clear, fatal=False)
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        sweep(catia, part, PREFIX)
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
