"""Probe 46o: does `Hole.BottomType = catFlatHoleBottom (0)` give a flat-bottomed hole?

One question only. Fixture: 46m's (block, `AddNewHoleFromPoint(10, 5, 20, top, 8)`,
rebuilt). 46m showed the default removes 1035.372 mm3 = a 12 x 8 cylinder plus a 120-degree
drill point. Here `BottomType` and `BottomAngle.Value` are read, `BottomType = 0` is
written, one `Part.Update()`, and the volume: a flat hole removes pi * 36 * 8 = 904.779.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46o_hole_flat_bottom.py
"""

import math

from _micro import (
    block_fixture, delete, marker, planar_face, require_blank_target, step,
    update_if_needed, verify_blank,
)

PREFIX = "AUTO3DX_P46O"
CAT_FLAT_BOTTOM = 0


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
        step("Hole.BottomType (default)", lambda: hole.BottomType, fatal=False)
        step("Hole.BottomAngle.Value (default)", lambda: hole.BottomAngle.Value, fatal=False)
        step("Hole.Type (default)", lambda: hole.Type, fatal=False)
        step("Hole.BottomType = 0", lambda: setattr(hole, "BottomType", CAT_FLAT_BOTTOM))
        step("Hole.BottomType read back", lambda: hole.BottomType, fatal=False)
        step("Part.Update", raw.Update, fatal=False)
        step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw)), fatal=False)
        volume = step("[composite, verified] measurement.measure().volume_mm3",
                      lambda: part.measurement.measure().volume_mm3, fatal=False)
        if volume is not None:
            marker(f"[RESULT] removed {48000.0 - volume:.3f} mm3; flat 12 x 8 is "
                   f"{math.pi * 36 * 8:.3f}")
    finally:
        if hole is not None:
            delete(catia, hole, f"{PREFIX}_HOLE")
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
