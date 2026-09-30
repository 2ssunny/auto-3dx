"""Probe 47f: does `BottomLimit.LimitMode = catUpToNextLimit (1)` stop at the next face?

One question only. Fixture: a 60x40x20 block on XY and, separated by a 10 mm gap, a second
60x40x10 block from z = 30 to 40 (sketched on a verified offset plane at z = 30). A 6 mm
flat hole is drilled at (0, 0) from the upper block's top face (z = 40) with LimitMode 1,
updated, measured; then LimitMode 2 (the verified through-all) for comparison. Up to next
should remove only the upper block's 10 mm, pi*9*10 = 282.743; up to last removes both
blocks' material, pi*9*30 = 848.230.

    $env:AUTO3DX_LIVE_PART = "<disposable Part>"
    python -u scripts/probes/47f_hole_up_to_next.py
"""

import math

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

PREFIX = "AUTO3DX_P47F"


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    lower = upper = hole = plane = None
    try:
        lower, _ = block_fixture(part, f"{PREFIX}_LOWER")
        plane = step(
            "[composite, verified] planes.create_offset(XY, 30)",
            lambda: part.planes.create_offset(f"{PREFIX}_PLANE", "XY", 30.0),
        )
        step("Part.Update", raw.Update)
        sketch = step(
            "[composite, verified] sketches.create(on plane)",
            lambda: part.sketches.create(f"{PREFIX}_UPPER_SK", support=plane),
        )
        step(
            "[composite, verified] centered_rectangle(60, 40)",
            lambda: sketch.centered_rectangle(60.0, 40.0),
        )
        upper = step(
            "[composite, verified] create_pad(upper, 10)",
            lambda: part.part_design.create_pad(f"{PREFIX}_UPPER", sketch, 10.0),
        )
        step("Part.Update", raw.Update)
        base = step(
            "[composite, verified] measure volume",
            lambda: part.measurement.measure().volume_mm3,
        )
        top = planar_face(part, (0, 0, 1), (0, 0, 1))
        marker(f"[INFO] upper top face centre {top.geometry.center_mm}")
        hole = step(
            "AddNewHoleFromPoint(0, 0, 40, top, 5)",
            lambda: raw.ShapeFactory.AddNewHoleFromPoint(0.0, 0.0, 40.0, top.com_object, 5.0),
        )
        step("Hole.Name = ...", lambda: setattr(hole, "Name", f"{PREFIX}_HOLE"))
        step("Diameter.Value = 6", lambda: setattr(hole.Diameter, "Value", 6.0))
        step("BottomType = 0", lambda: setattr(hole, "BottomType", 0))
        for mode in (1, 2):
            step(
                f"BottomLimit.LimitMode = {mode}",
                lambda mode=mode: setattr(hole.BottomLimit, "LimitMode", mode),
            )
            step("LimitMode read back", lambda: int(hole.BottomLimit.LimitMode), fatal=False)
            step("Part.Update", raw.Update, fatal=False)
            step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw)), fatal=False)
            volume = step(
                "[composite] measure volume",
                lambda: part.measurement.measure().volume_mm3,
                fatal=False,
            )
            if volume is not None:
                marker(
                    f"[RESULT] LimitMode {mode}: removed {base - volume:.3f} "
                    f"(10 mm: {math.pi * 90:.3f}; 30 mm: {math.pi * 270:.3f})"
                )
            step(
                "BottomLimit.Dimension.Value",
                lambda: hole.BottomLimit.Dimension.Value,
                fatal=False,
            )
    finally:
        if hole is not None:
            delete(catia, hole, f"{PREFIX}_HOLE")
        if upper is not None:
            step(
                "[composite] remove_pad(upper)",
                lambda: part.part_design.remove_pad(f"{PREFIX}_UPPER"),
                fatal=False,
            )
        if lower is not None:
            delete(catia, lower, f"{PREFIX}_LOWER")
        sweep(catia, part, PREFIX)
        if plane is not None:
            step(
                "[composite] planes.remove(force)",
                lambda: part.planes.remove(part.planes.get(f"{PREFIX}_PLANE"), force=True),
                fatal=False,
            )
            step(
                "[composite] remove_geometrical_set",
                lambda: part.planes.remove_geometrical_set(force=True),
                fatal=False,
            )
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
