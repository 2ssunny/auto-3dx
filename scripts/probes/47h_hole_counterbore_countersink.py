"""Probe 47h: counterbored and countersunk holes -- which members, and what volume?

One question per run (pass `counterbore` or `countersink`), never both at once:
`Type = catCounterboredHole (2)` with `HeadDiameter`/`HeadDepth`, or
`Type = catCountersunkHole (3)` with `CounterSunkMode`, `HeadAngle`, `HeadDepth`.
Fixture: the block; a flat 6 mm hole 10 deep at (10, 5, 20) from the top face. Expected
removals: counterbore 12 x 4 -> pi*9*10 + pi*(36-9)*4 = 622.035. Countersink 90 degrees,
2 deep (mode 0 = depth + angle) -> head radius 5: pi*9*10 + (pi*2/3*(25+15+9) - pi*9*2)
= 328.819.

    $env:AUTO3DX_LIVE_PART = "<disposable Part>"
    python -u scripts/probes/47h_hole_counterbore_countersink.py counterbore
"""

import sys

from _micro import (
    block_fixture,
    delete,
    marker,
    planar_face,
    require_blank_target,
    step,
    sweep,
    update_if_needed,
    verify_blank,
)

PREFIX = "AUTO3DX_P47H"
BLOCK_VOLUME = 48000.0


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "counterbore"
    if which not in ("counterbore", "countersink"):
        sys.exit("choose counterbore or countersink")
    catia, part = require_blank_target()
    raw = part.com_object
    pad = hole = None
    try:
        pad, _ = block_fixture(part, f"{PREFIX}_BLOCK")
        top = planar_face(part, (0, 0, 1), (0, 0, 1))
        hole = step(
            "AddNewHoleFromPoint(10, 5, 20, top, 10)",
            lambda: raw.ShapeFactory.AddNewHoleFromPoint(10.0, 5.0, 20.0, top.com_object, 10.0),
        )
        step("Hole.Name = ...", lambda: setattr(hole, "Name", f"{PREFIX}_HOLE"))
        step("Diameter.Value = 6", lambda: setattr(hole.Diameter, "Value", 6.0))
        step("BottomType = 0", lambda: setattr(hole, "BottomType", 0))
        step("BottomLimit.LimitMode = 0", lambda: setattr(hole.BottomLimit, "LimitMode", 0))
        if which == "counterbore":
            step("Type = 2", lambda: setattr(hole, "Type", 2))
            step(
                "HeadDiameter.Value = 12",
                lambda: setattr(hole.HeadDiameter, "Value", 12.0),
                fatal=False,
            )
            step("HeadDepth.Value = 4", lambda: setattr(hole.HeadDepth, "Value", 4.0), fatal=False)
            expected = 622.035
        else:
            step("Type = 3", lambda: setattr(hole, "Type", 3))
            step("CounterSunkMode (default)", lambda: int(hole.CounterSunkMode), fatal=False)
            step("CounterSunkMode = 0", lambda: setattr(hole, "CounterSunkMode", 0), fatal=False)
            step(
                "HeadAngle.Value = 90", lambda: setattr(hole.HeadAngle, "Value", 90.0), fatal=False
            )
            step("HeadDepth.Value = 2", lambda: setattr(hole.HeadDepth, "Value", 2.0), fatal=False)
            expected = 328.819
        step("Type read back", lambda: int(hole.Type), fatal=False)
        step("Part.Update", raw.Update, fatal=False)
        step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw)), fatal=False)
        for member in ("HeadDiameter", "HeadDepth", "HeadAngle", "Diameter"):
            step(f"{member}.Value", lambda member=member: getattr(hole, member).Value, fatal=False)
        volume = step(
            "[composite] volume", lambda: part.measurement.measure().volume_mm3, fatal=False
        )
        if volume is not None:
            marker(f"[RESULT] {which}: removed {BLOCK_VOLUME - volume:.3f} (expected {expected})")
        step(
            "Type = 0 (restore the session default)", lambda: setattr(hole, "Type", 0), fatal=False
        )
    finally:
        if hole is not None:
            delete(catia, hole, f"{PREFIX}_HOLE")
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        sweep(catia, part, PREFIX)
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
