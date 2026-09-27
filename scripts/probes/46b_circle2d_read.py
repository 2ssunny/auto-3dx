"""Probe 46b: can a closed circle's centre and radius be read after the edition closes?

One question only. Fixture: one sketch on XY holding one closed circle, centre (20, 15),
radius 4. The edition is closed BEFORE anything is read back. No update, no feature.

Probe 43 called `Circle2D.GetCenter()` with no argument and got a COM error. The type
library declares `GetCenter(oData)`, a seed-array out parameter, so it is called with a
two-item seed here. `Radius` was already read live in probe 43 and is read again only
to compare with the centre call on the same object.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46b_circle2d_read.py
"""

from _micro import delete, marker, require_blank_target, step, verify_blank

SKETCH_NAME = "AUTO3DX_P46B_CIRCLE"


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
        circle = step("Factory2D.CreateClosedCircle(20, 15, 4)",
                      lambda: factory.CreateClosedCircle(20.0, 15.0, 4.0))
        step("Sketch.CloseEdition", sketch.CloseEdition)
        marker("[EDITION] closed; reading back")
        step("Circle2D.GetCenter([0.0] * 2)", lambda: circle.GetCenter([0.0, 0.0]), fatal=False)
        step("Circle2D.Radius", lambda: circle.Radius, fatal=False)
    finally:
        if sketch is not None:
            delete(catia, sketch, SKETCH_NAME)
        verify_blank(part)


if __name__ == "__main__":
    main()
