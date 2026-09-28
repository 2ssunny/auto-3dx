"""Probe 46ab: what does `GetEndPoints` report for a CLOSED circle?

One question only. 46c showed an open arc reports its two end points through
`GetEndPoints`. To tell a closed circle from an arc from reads alone, the same call is made
on a closed circle (centre (20, 15), r 4) after the edition closes. Nothing else is read.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46ab_closed_circle_end_points.py
"""

from _micro import delete, marker, require_blank_target, step, verify_blank

SKETCH_NAME = "AUTO3DX_P46AB_CIRCLE"


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
        circle = step(
            "Factory2D.CreateClosedCircle(20, 15, 4)",
            lambda: factory.CreateClosedCircle(20.0, 15.0, 4.0),
        )
        step("Sketch.CloseEdition", sketch.CloseEdition)
        marker("[EDITION] closed; reading back")
        step(
            "Circle2D.GetEndPoints([0.0] * 4) (closed)",
            lambda: circle.GetEndPoints([0.0] * 4),
            fatal=False,
        )
    finally:
        if sketch is not None:
            delete(catia, sketch, SKETCH_NAME)
        verify_blank(part)


if __name__ == "__main__":
    main()
