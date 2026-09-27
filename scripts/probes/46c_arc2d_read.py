"""Probe 46c: can an open arc's geometry be read after the edition closes?

One question only. Fixture: one sketch on XY holding one open arc made by
`Factory2D.CreateCircle(cx=-20, cy=-10, r=6, start=0, end=pi/2)`. The edition is closed
BEFORE anything is read back. No update, no feature.

The arc's end points also answer an open question from probe 27: whether the start/end
parameters are radians. If they are, the end points are (-14, -10) and (-20, -4).

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46c_arc2d_read.py
"""

import math

from _micro import delete, marker, require_blank_target, step, verify_blank

SKETCH_NAME = "AUTO3DX_P46C_ARC"


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
        arc = step("Factory2D.CreateCircle(-20, -10, 6, 0, pi/2)",
                   lambda: factory.CreateCircle(-20.0, -10.0, 6.0, 0.0, math.pi / 2))
        step("Sketch.CloseEdition", sketch.CloseEdition)
        marker("[EDITION] closed; reading back")
        step("arc GetCenter([0.0] * 2)", lambda: arc.GetCenter([0.0, 0.0]), fatal=False)
        step("arc Radius", lambda: arc.Radius, fatal=False)
        step("arc GetEndPoints([0.0] * 4)", lambda: arc.GetEndPoints([0.0] * 4), fatal=False)
    finally:
        if sketch is not None:
            delete(catia, sketch, SKETCH_NAME)
        verify_blank(part)


if __name__ == "__main__":
    main()
