"""Probe 47g: what does `Hole.Reverse()` do to a hole drilled from a top face?

One question only. Fixture: the block; a flat 6 mm hole 8 deep at (10, 5, 20) from the top
face (the SDK's attributes written explicitly), rebuilt: removes pi*9*8 = 226.195. Then
`GetDirection`, `Reverse()`, `GetDirection`, one update, IsUpToDate and the volume; then
`Reverse()` again and one update to restore. Pointing out of the material, the hole would
remove nothing (or the update would fail).

    $env:AUTO3DX_LIVE_PART = "<disposable Part>"
    python -u scripts/probes/47g_hole_reverse.py
"""

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

PREFIX = "AUTO3DX_P47G"
BLOCK_VOLUME = 48000.0


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    pad = hole = None

    def removed() -> "float | None":
        volume = step(
            "[composite] volume", lambda: part.measurement.measure().volume_mm3, fatal=False
        )
        return None if volume is None else BLOCK_VOLUME - volume

    try:
        pad, _ = block_fixture(part, f"{PREFIX}_BLOCK")
        top = planar_face(part, (0, 0, 1), (0, 0, 1))
        hole = step(
            "AddNewHoleFromPoint(10, 5, 20, top, 8)",
            lambda: raw.ShapeFactory.AddNewHoleFromPoint(10.0, 5.0, 20.0, top.com_object, 8.0),
        )
        step("Hole.Name = ...", lambda: setattr(hole, "Name", f"{PREFIX}_HOLE"))
        step("Diameter.Value = 6", lambda: setattr(hole.Diameter, "Value", 6.0))
        step("BottomType = 0", lambda: setattr(hole, "BottomType", 0))
        step("BottomLimit.LimitMode = 0", lambda: setattr(hole.BottomLimit, "LimitMode", 0))
        step("Part.Update", raw.Update)
        marker(f"[RESULT] normal: removed {removed()}")
        step("GetDirection", lambda: hole.GetDirection([0.0] * 3), fatal=False)
        step("Hole.Reverse()", hole.Reverse, fatal=False)
        step("GetDirection after Reverse", lambda: hole.GetDirection([0.0] * 3), fatal=False)
        step("GetOrigin after Reverse", lambda: hole.GetOrigin([0.0] * 3), fatal=False)
        step("Part.Update (reversed)", raw.Update, fatal=False)
        step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw)), fatal=False)
        marker(f"[RESULT] reversed: removed {removed()}")
        step("Hole.Reverse() back", hole.Reverse, fatal=False)
        step("Part.Update (restored)", raw.Update, fatal=False)
        marker(f"[RESULT] restored: removed {removed()}")
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
