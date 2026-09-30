"""Probe 47k (diagnostic): which "read" leaves an empty Part not up to date?

Observed 2026-10-01 on a fresh, empty Part: it read up to date, then after a session of
reads -- `inspect.summary()` (whose topology search captures and restores the selection,
which held the Part object itself), `Selection.Item(1).Value` with the Part selected, and
`Part.Relations.Count` -- `IsUpToDate(Part)` read False while `IsUpToDate(MainBody)` read
True, with nothing created. This probe restores the state with one `Part.Update()` on the
empty Part, then runs each suspect on its own and reads `IsUpToDate(Part)` after it:

1. `Part.Relations.Count`
2. `Selection.Item(1).Value` and its `Name`, with the Part selected
3. `part.topology.edges()` -- search with the Part selected, then selection restore
4. `part.inspect.summary()`

The selection starts as the user left it (the Part) and is left that way. Nothing is
created; the only mutation is `Part.Update()` on the empty Part, repeated whenever a step
dirtied it so the next step starts clean.

    $env:AUTO3DX_LIVE_PART = "<disposable Part>"
    python -u scripts/probes/47k_what_dirties_the_part.py
"""

import os
import sys
from typing import Any

from auto_3dx import Catia

from _micro import marker, step


def main() -> None:
    target = os.environ.get("AUTO3DX_LIVE_PART", "").strip()
    catia = step("Catia.attach", Catia.attach)
    part = step("Catia.active_part", catia.active_part)
    if step("Part.Name", lambda: part.name) != target:
        sys.exit("Refusing: the active Part is not the named target.")
    raw = part.com_object
    main_body = step("Part.MainBody", lambda: raw.MainBody)
    empty = (
        step("Shapes.Count", lambda: int(main_body.Shapes.Count)) == 0
        and step("Sketches.Count", lambda: int(main_body.Sketches.Count)) == 0
        and step("HybridBodies.Count", lambda: int(raw.HybridBodies.Count)) == 0
    )
    if not empty:
        sys.exit("Refusing: the target is not empty.")
    selection = step("Editor.Selection", lambda: catia.active_editor().Selection)

    def up_to_date(label: str) -> bool:
        value = step(f"IsUpToDate(Part) after {label}", lambda: bool(raw.IsUpToDate(raw)))
        marker(f"[RESULT] after {label}: up to date = {value}")
        return value

    def clean() -> None:
        if not up_to_date("check"):
            step("Part.Update (empty Part)", raw.Update)
            up_to_date("Part.Update")

    clean()
    marker(f"[INFO] selection count {step('Selection.Count', lambda: int(selection.Count))}")

    step("Part.Relations.Count", lambda: int(raw.Relations.Count))
    up_to_date("Relations.Count")
    clean()

    if int(selection.Count):
        item: Any = step("Selection.Item(1)", lambda: selection.Item(1))
        value = step("Item(1).Value", lambda: item.Value)
        step("Value.Name", lambda: str(value.Name))
        up_to_date("reading the selected Part's Value")
        clean()

    step("[composite] part.topology.edges() (capture, search, restore)",
         lambda: part.topology.edges())
    up_to_date("topology.edges()")
    marker(f"[INFO] selection count {step('Selection.Count', lambda: int(selection.Count))}")
    clean()

    step("[composite] part.inspect.summary()", lambda: part.inspect.summary())
    up_to_date("inspect.summary()")
    clean()


if __name__ == "__main__":
    main()
