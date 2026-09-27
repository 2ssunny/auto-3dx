"""Probe 46p: does a hole on a side face drill into the material by default?

One question only. Fixture: the 60x40x20 block, rebuilt; its +X side face (centre
(30, 0, 10), outward +X) from the verified query. Uncertain calls: `AddNewHoleFromPoint(
30, 0, 10, side, 6)`, `GetDirection(seed3)` before and after one `Part.Update()`, and the
volume. Into the material, a default (12 mm, 120-degree point) hole 6 deep removes
pi*36*6 + pi*36*3.4641/3 = 808.186 mm3; pointing out of the block it removes nothing.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46p_hole_side_face_direction.py
"""

from _micro import (
    block_fixture, delete, marker, planar_face, require_blank_target, step,
    update_if_needed, verify_blank,
)

PREFIX = "AUTO3DX_P46P"


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    pad = hole = None
    try:
        pad, _ = block_fixture(part, f"{PREFIX}_BLOCK")
        side = planar_face(part, (1, 0, 0), (1, 0, 0))
        marker(f"[INFO] side face centre {side.geometry.center_mm}")
        shape_factory = step("Part.ShapeFactory", lambda: raw.ShapeFactory)
        hole = step("ShapeFactory.AddNewHoleFromPoint(30, 0, 10, side, 6)",
                    lambda: shape_factory.AddNewHoleFromPoint(30.0, 0.0, 10.0, side.com_object, 6.0))
        step("Hole.Name = ...", lambda: setattr(hole, "Name", f"{PREFIX}_HOLE"))
        step("Hole.GetDirection([0.0] * 3) before update",
             lambda: hole.GetDirection([0.0] * 3), fatal=False)
        step("Part.Update", raw.Update, fatal=False)
        step("Hole.GetDirection([0.0] * 3) after update",
             lambda: hole.GetDirection([0.0] * 3), fatal=False)
        step("Hole.GetOrigin([0.0] * 3)", lambda: hole.GetOrigin([0.0] * 3), fatal=False)
        volume = step("[composite, verified] measurement.measure().volume_mm3",
                      lambda: part.measurement.measure().volume_mm3, fatal=False)
        if volume is not None:
            marker(f"[RESULT] removed {48000.0 - volume:.3f} mm3 (into the material: 808.186)")
        bore = step("[composite, verified] faces().query().cylindrical().one()",
                    lambda: part.topology.faces(body=None).query().cylindrical().one(),
                    fatal=False)
        if bore is not None:
            marker(f"[RESULT] bore centre {bore.geometry.center_mm}")
    finally:
        if hole is not None:
            delete(catia, hole, f"{PREFIX}_HOLE")
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
