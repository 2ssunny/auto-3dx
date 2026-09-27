"""Probe 46f: does `Construction` read back after the edition closes?

One question only. Fixture: one sketch on XY, two lines; the second is marked
`Construction = True` inside the edition (the verified write from probe 27). The edition
is closed, then `Construction` is read on both lines.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46f_construction_read.py
"""

from _micro import delete, marker, require_blank_target, step, verify_blank

SKETCH_NAME = "AUTO3DX_P46F_CONSTRUCTION"


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
        real = step(
            "Factory2D.CreateLine(0, 0, 30, 0)", lambda: factory.CreateLine(0.0, 0.0, 30.0, 0.0)
        )
        helper = step(
            "Factory2D.CreateLine(0, 0, 0, 20)", lambda: factory.CreateLine(0.0, 0.0, 0.0, 20.0)
        )
        step("helper.Construction = True", lambda: setattr(helper, "Construction", True))
        step("Sketch.CloseEdition", sketch.CloseEdition)
        marker("[EDITION] closed; reading back")
        step("real.Construction", lambda: real.Construction, fatal=False)
        step("helper.Construction", lambda: helper.Construction, fatal=False)
    finally:
        if sketch is not None:
            delete(catia, sketch, SKETCH_NAME)
        verify_blank(part)


if __name__ == "__main__":
    main()
