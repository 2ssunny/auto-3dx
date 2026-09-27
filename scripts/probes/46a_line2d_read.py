"""Probe 46a: can `Line2D.GetEndPoints` read a line's coordinates after the edition closes?

One question only. Fixture: one sketch on XY holding one line from (10, 5) to (40, 25).
The edition is closed BEFORE anything is read back. No update, no feature, no constraint.

Probe 43 listed `Line2D`'s dispatch members and found no coordinate accessor, but the
type library declares `Line2D.GetEndPoints(oEndPoints)` (four doubles, seed-array out
parameter, the convention `GetAbsoluteAxisData` already uses).

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46a_line2d_read.py
"""

from _micro import delete, marker, require_blank_target, step, verify_blank

SKETCH_NAME = "AUTO3DX_P46A_LINE"


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    sketch = None
    try:
        plane = step("OriginElements.PlaneXY", lambda: raw.OriginElements.PlaneXY)
        sketches = step("MainBody.Sketches", lambda: raw.MainBody.Sketches)
        sketch = step("Sketches.Add(PlaneXY)", lambda: sketches.Add(plane))
        step("Sketch.Name = ...", lambda: setattr(sketch, "Name", SKETCH_NAME))
        factory = step("Sketch.OpenEdition", sketch.OpenEdition)
        line = step("Factory2D.CreateLine(10, 5, 40, 25)",
                    lambda: factory.CreateLine(10.0, 5.0, 40.0, 25.0))
        step("Sketch.CloseEdition", sketch.CloseEdition)
        marker("[EDITION] closed; reading back")
        step("Line2D.GetEndPoints([0.0] * 4)",
             lambda: line.GetEndPoints([0.0, 0.0, 0.0, 0.0]), fatal=False)
    finally:
        if sketch is not None:
            delete(catia, sketch, SKETCH_NAME)
        verify_blank(part)


if __name__ == "__main__":
    main()
