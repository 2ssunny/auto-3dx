"""Probe 46q: are a new hole's defaults fixed, or carried over from the last hole made?

One question only. In 46m a fresh hole came out with `BottomType` 1 (V, 120 degrees) and
`Diameter` 12. 46o then set `BottomType = 0` on its hole, and in 46p a hole made without
touching `BottomType` removed exactly a flat cylinder. Fixture: the block; one
`AddNewHoleFromPoint(10, 5, 20, top, 8)`; only reads follow (`BottomType`,
`BottomAngle.Value`, `Diameter.Value`, `Type`). No attribute is written, no update is made
with the hole.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46q_hole_defaults_are_sticky.py
"""

from _micro import (
    block_fixture, delete, planar_face, require_blank_target, step, update_if_needed,
    verify_blank,
)

PREFIX = "AUTO3DX_P46Q"


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
        step("Hole.BottomType", lambda: hole.BottomType, fatal=False)
        step("Hole.BottomAngle.Value", lambda: hole.BottomAngle.Value, fatal=False)
        step("Hole.Diameter.Value", lambda: hole.Diameter.Value, fatal=False)
        step("Hole.Type", lambda: hole.Type, fatal=False)
    finally:
        if hole is not None:
            delete(catia, hole, f"{PREFIX}_HOLE")
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
