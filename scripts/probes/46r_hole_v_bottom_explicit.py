"""Probe 46r: can a V (drill point) bottom be set explicitly, and what does it remove?

One question only. 46q showed a new hole inherits the last hole's `BottomType`; the session
now defaults to flat (0) because 46o wrote it. Fixture: the block; one
`AddNewHoleFromPoint(10, 5, 20, top, 8)`. Then `BottomType = 1` is written, `BottomAngle.Value`
read, one `Part.Update()`, and the volume: 46m measured 1035.372 mm3 for a 12 mm, 8 deep,
120-degree-point hole. This also leaves the session's carried-over default as V again, as
it was before probe 46o.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46r_hole_v_bottom_explicit.py
"""

from _micro import (
    block_fixture, delete, marker, planar_face, require_blank_target, step,
    update_if_needed, verify_blank,
)

PREFIX = "AUTO3DX_P46R"
CAT_V_BOTTOM = 1


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
        step("Hole.BottomType (inherited)", lambda: hole.BottomType, fatal=False)
        step("Hole.BottomType = 1", lambda: setattr(hole, "BottomType", CAT_V_BOTTOM))
        step("Hole.BottomType read back", lambda: hole.BottomType, fatal=False)
        step("Hole.BottomAngle.Value", lambda: hole.BottomAngle.Value, fatal=False)
        step("Part.Update", raw.Update, fatal=False)
        volume = step("[composite, verified] measurement.measure().volume_mm3",
                      lambda: part.measurement.measure().volume_mm3, fatal=False)
        if volume is not None:
            marker(f"[RESULT] removed {48000.0 - volume:.3f} mm3 (46m default V: 1035.372)")
    finally:
        if hole is not None:
            delete(catia, hole, f"{PREFIX}_HOLE")
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
