"""Probe 46n: does `BottomLimit.LimitMode = catUpToLastLimit (2)` make a hole go through?

One question only. Fixture: 46m's (block, `AddNewHoleFromPoint(10, 5, 20, top, 8)`,
rebuilt). Then `BottomLimit.LimitMode = 2`, one `Part.Update()`, and the volume. Through
the whole 20 mm block a 12 mm hole removes pi * 36 * 20 = 2261.947 mm3 (a through hole has
no drill point left in the material). The mode is written back to 0 before cleanup.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46n_hole_through_all.py
"""

import math

from _micro import (
    block_fixture, delete, marker, planar_face, require_blank_target, step,
    update_if_needed, verify_blank,
)

PREFIX = "AUTO3DX_P46N"
CAT_UP_TO_LAST = 2
CAT_OFFSET = 0


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    pad = hole = None
    try:
        pad, _ = block_fixture(part, f"{PREFIX}_BLOCK")
        top = planar_face(part, (0, 0, 1), (0, 0, 1))
        shape_factory = step("Part.ShapeFactory", lambda: raw.ShapeFactory)
        hole = step("ShapeFactory.AddNewHoleFromPoint(10, 5, 20, top, 8)",
                    lambda: shape_factory.AddNewHoleFromPoint(10.0, 5.0, 20.0, top.com_object, 8.0))
        step("Hole.Name = ...", lambda: setattr(hole, "Name", f"{PREFIX}_HOLE"))
        step("Part.Update", raw.Update)
        limit = step("Hole.BottomLimit", lambda: hole.BottomLimit)
        step("BottomLimit.LimitMode = 2", lambda: setattr(limit, "LimitMode", CAT_UP_TO_LAST))
        step("BottomLimit.LimitMode read back", lambda: limit.LimitMode, fatal=False)
        step("Part.Update (through all)", raw.Update, fatal=False)
        step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw)), fatal=False)
        volume = step("[composite, verified] measurement.measure().volume_mm3",
                      lambda: part.measurement.measure().volume_mm3, fatal=False)
        if volume is not None:
            marker(f"[RESULT] removed {48000.0 - volume:.3f} mm3; through 20 mm is "
                   f"{math.pi * 36 * 20:.3f}")
        step("BottomLimit.Dimension.Value (while through)",
             lambda: limit.Dimension.Value, fatal=False)
        step("BottomLimit.LimitMode = 0", lambda: setattr(limit, "LimitMode", CAT_OFFSET))
        step("Part.Update (blind again)", raw.Update, fatal=False)
        volume = step("[composite, verified] measurement.measure().volume_mm3",
                      lambda: part.measurement.measure().volume_mm3, fatal=False)
        if volume is not None:
            marker(f"[RESULT] blind again: removed {48000.0 - volume:.3f} mm3 (46m: 1035.372)")
    finally:
        if hole is not None:
            delete(catia, hole, f"{PREFIX}_HOLE")
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
