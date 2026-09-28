"""Probe 46s: can a new hole be fully configured before its first update?

One question only. The writes are individually verified (`Diameter` in probe 43,
`BottomType` in 46o/46r, `LimitMode` in 46n), but 43 and 46n wrote after a rebuild. Here all
three are written right after `AddNewHoleFromPoint`, before any `Part.Update()`:
`Diameter = 6`, `BottomType = 0` (flat), `LimitMode = 2` (through all). One update, then the
volume: a 6 mm hole through the 20 mm block removes pi * 9 * 20 = 565.487 mm3. The
session's carried-over bottom type is put back to V afterwards on a second, throwaway hole.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46s_hole_configured_before_update.py
"""

from _micro import (
    block_fixture,
    delete,
    marker,
    planar_face,
    require_blank_target,
    step,
    update_if_needed,
    verify_blank,
)

PREFIX = "AUTO3DX_P46S"


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    pad = hole = restore = None
    try:
        pad, _ = block_fixture(part, f"{PREFIX}_BLOCK")
        top = planar_face(part, (0, 0, 1), (0, 0, 1))
        shape_factory = step("Part.ShapeFactory", lambda: raw.ShapeFactory)
        hole = step(
            "ShapeFactory.AddNewHoleFromPoint(10, 5, 20, top, 8)",
            lambda: shape_factory.AddNewHoleFromPoint(10.0, 5.0, 20.0, top.com_object, 8.0),
        )
        step("Hole.Name = ...", lambda: setattr(hole, "Name", f"{PREFIX}_HOLE"))
        step("Hole.Diameter.Value = 6", lambda: setattr(hole.Diameter, "Value", 6.0))
        step("Hole.BottomType = 0", lambda: setattr(hole, "BottomType", 0))
        step("Hole.BottomLimit.LimitMode = 2", lambda: setattr(hole.BottomLimit, "LimitMode", 2))
        step("Part.Update", raw.Update, fatal=False)
        step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw)), fatal=False)
        volume = step(
            "[composite, verified] measurement.measure().volume_mm3",
            lambda: part.measurement.measure().volume_mm3,
            fatal=False,
        )
        if volume is not None:
            marker(f"[RESULT] removed {48000.0 - volume:.3f} mm3 (expected 565.487)")
        step("Hole.Diameter.Value read back", lambda: hole.Diameter.Value, fatal=False)
        step("Hole.GetOrigin", lambda: hole.GetOrigin([0.0] * 3), fatal=False)
        restore = step(
            "ShapeFactory.AddNewHoleFromPoint (restore the V default)",
            lambda: shape_factory.AddNewHoleFromPoint(-10.0, -5.0, 20.0, top.com_object, 5.0),
        )
        step("restore.Name = ...", lambda: setattr(restore, "Name", f"{PREFIX}_RESTORE"))
        step("restore.BottomType = 1", lambda: setattr(restore, "BottomType", 1))
    finally:
        if restore is not None:
            delete(catia, restore, f"{PREFIX}_RESTORE")
        if hole is not None:
            delete(catia, hole, f"{PREFIX}_HOLE")
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
