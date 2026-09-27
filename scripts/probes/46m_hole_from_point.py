"""Probe 46m: does `AddNewHoleFromPoint(x, y, z, face, depth)` place a hole at (x, y, z)?

One question only. Fixture: the 60x40x20 block, rebuilt; its top face from the verified
query. Uncertain calls, each marked: `ShapeFactory.AddNewHoleFromPoint(10, 5, 20, top, 8)`
(type library: five arguments, doubles and a Reference), then reads of `Diameter.Value`,
`BottomLimit.LimitMode`, `BottomLimit.Dimension.Value` and `GetOrigin(seed3)`, one
`Part.Update()`, and the measured bore.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46m_hole_from_point.py
"""

import math

from _micro import (
    block_fixture, delete, marker, planar_face, require_blank_target, step,
    update_if_needed, verify_blank,
)

PREFIX = "AUTO3DX_P46M"


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
        diameter = step("Hole.Diameter.Value", lambda: hole.Diameter.Value, fatal=False)
        step("Hole.BottomLimit.LimitMode", lambda: hole.BottomLimit.LimitMode, fatal=False)
        step("Hole.BottomLimit.Dimension.Value",
             lambda: hole.BottomLimit.Dimension.Value, fatal=False)
        step("Hole.GetOrigin([0.0] * 3) before update",
             lambda: hole.GetOrigin([0.0] * 3), fatal=False)
        step("Part.Update", raw.Update)
        step("Hole.GetOrigin([0.0] * 3) after update",
             lambda: hole.GetOrigin([0.0] * 3), fatal=False)
        volume = step("[composite, verified] measurement.measure().volume_mm3",
                      lambda: part.measurement.measure().volume_mm3)
        if diameter is not None:
            marker(f"[RESULT] removed {48000.0 - volume:.3f} mm3; a flat {diameter} x 8 "
                   f"cylinder is {math.pi * (diameter / 2) ** 2 * 8:.3f}")
        bore = step("[composite, verified] faces().query().cylindrical().one()",
                    lambda: part.topology.faces(body=None).query().cylindrical().one())
        marker(f"[RESULT] bore centre {bore.geometry.center_mm} radius {bore.geometry.radius_mm}")
    finally:
        if hole is not None:
            delete(catia, hole, f"{PREFIX}_HOLE")
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
