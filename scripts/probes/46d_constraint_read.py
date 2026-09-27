"""Probe 46d: can a dimensional constraint's type, mode, status and value be read back?

One question only. Fixture: one sketch on XY holding one line (0,0)-(30,0) and one
length constraint on it, created inside the edition exactly as the verified
`SketchEditor.length()` path does (`Constraints.AddMonoEltCst(5, line)`). The edition is
closed BEFORE anything is read back. No update, no feature.

`Type`, `Status` and `Dimension.Value` are already read by `Constraint`; `Mode` (driving
or driven, `CatConstraintMode`) is the new read.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46d_constraint_read.py
"""

from _micro import delete, marker, require_blank_target, step, verify_blank

SKETCH_NAME = "AUTO3DX_P46D_CONSTRAINT"
CONSTRAINT_LENGTH = 5


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    sketch = None
    try:
        plane = step("OriginElements.PlaneXY", lambda: raw.OriginElements.PlaneXY)
        sketches = step("MainBody.Sketches", lambda: raw.MainBody.Sketches)
        sketch = step("Sketches.Add(PlaneXY)", lambda: sketches.Add(plane))
        step("Sketch.Name = ...", lambda: setattr(sketch, "Name", SKETCH_NAME))
        constraints = step("Sketch.Constraints", lambda: sketch.Constraints)
        factory = step("Sketch.OpenEdition", sketch.OpenEdition)
        line = step(
            "Factory2D.CreateLine(0, 0, 30, 0)", lambda: factory.CreateLine(0.0, 0.0, 30.0, 0.0)
        )
        constraint = step(
            "Constraints.AddMonoEltCst(length, line)",
            lambda: constraints.AddMonoEltCst(CONSTRAINT_LENGTH, line),
        )
        step("Sketch.CloseEdition", sketch.CloseEdition)
        marker("[EDITION] closed; reading back")
        step("Constraint.Name", lambda: constraint.Name, fatal=False)
        step("Constraint.Type", lambda: constraint.Type, fatal=False)
        step("Constraint.Mode", lambda: constraint.Mode, fatal=False)
        step("Constraint.Status", lambda: constraint.Status, fatal=False)
        dimension = step("Constraint.Dimension", lambda: constraint.Dimension, fatal=False)
        if dimension is not None:
            step("Dimension.Value", lambda: dimension.Value, fatal=False)
        step("Constraints.Count", lambda: constraints.Count, fatal=False)
    finally:
        if sketch is not None:
            delete(catia, sketch, SKETCH_NAME)
        verify_blank(part)


if __name__ == "__main__":
    main()
