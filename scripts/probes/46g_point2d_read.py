"""Probe 46g: does `Point2D.GetCoordinates(seed)` read a point after the edition closes?

One question only. Fixture: one sketch on XY holding one point (-5, 7.5). The edition
is closed before the read.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46g_point2d_read.py
"""

from _micro import delete, marker, require_blank_target, step, verify_blank

SKETCH_NAME = "AUTO3DX_P46G_POINT"


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
        point = step("Factory2D.CreatePoint(-5, 7.5)", lambda: factory.CreatePoint(-5.0, 7.5))
        step("Sketch.CloseEdition", sketch.CloseEdition)
        marker("[EDITION] closed; reading back")
        step("Point2D.GetCoordinates([0.0] * 2)",
             lambda: point.GetCoordinates([0.0, 0.0]), fatal=False)
    finally:
        if sketch is not None:
            delete(catia, sketch, SKETCH_NAME)
        verify_blank(part)


if __name__ == "__main__":
    main()
