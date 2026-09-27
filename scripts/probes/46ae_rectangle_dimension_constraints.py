"""Probe 46ae: can the 46ad rectangle also take two length constraints?

One question only. 46ad verified the four H/V constraints on one rectangle. Here two
length constraints are added after them, bottom = 12 and left = 8 (the lengths already
drawn), with `Dimension.Value` written as the verified `SketchEditor.length(line, value)`
does. The first run of probe 46 left CATIA busy while building a rectangle
with several constraints on it (and reading geometry inside the edition); the call was
never identified. Each constraint kind here is individually verified (probes 20-22), but
never four on one closed profile. Fixture: one sketch on XY, the four lines
`SketchEditor.rectangle(12, 8, -40, 20)` draws. Inside the edition, each marked:
horizontal(bottom), horizontal(top), vertical(right), vertical(left). Then CloseEdition,
one `Part.Update()`, and each constraint's `Type` and `Status` (reads after the edition).

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46ae_rectangle_dimension_constraints.py
"""

from _micro import delete, marker, require_blank_target, step, verify_blank

SKETCH_NAME = "AUTO3DX_P46AE_RECT"
HORIZONTAL, VERTICAL, LENGTH = 10, 13, 5


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
        x0, y0, x1, y1 = -40.0, 20.0, -28.0, 28.0
        bottom = step("CreateLine bottom", lambda: factory.CreateLine(x0, y0, x1, y0))
        right = step("CreateLine right", lambda: factory.CreateLine(x1, y0, x1, y1))
        top = step("CreateLine top", lambda: factory.CreateLine(x1, y1, x0, y1))
        left = step("CreateLine left", lambda: factory.CreateLine(x0, y1, x0, y0))
        made = []
        for label, kind, line in (("horizontal(bottom)", HORIZONTAL, bottom),
                                  ("horizontal(top)", HORIZONTAL, top),
                                  ("vertical(right)", VERTICAL, right),
                                  ("vertical(left)", VERTICAL, left)):
            made.append(step(f"Constraints.AddMonoEltCst({label})",
                             lambda kind=kind, line=line: constraints.AddMonoEltCst(kind, line)))
        for label, line, value in (("bottom", bottom, 12.0), ("left", left, 8.0)):
            constraint = step(f"Constraints.AddMonoEltCst(length({label}))",
                              lambda line=line: constraints.AddMonoEltCst(LENGTH, line))
            dimension = step("Constraint.Dimension", lambda constraint=constraint:
                             constraint.Dimension)
            step(f"Dimension.Value = {value}", lambda dimension=dimension, value=value:
                 setattr(dimension, "Value", value))
            made.append(constraint)
        step("Sketch.CloseEdition", sketch.CloseEdition)
        marker("[EDITION] closed")
        step("Part.Update", raw.Update, fatal=False)
        step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw)), fatal=False)
        step("Constraints.Count", lambda: int(constraints.Count), fatal=False)
        for constraint in made:
            step("Constraint.Name", lambda constraint=constraint: constraint.Name, fatal=False)
            step("Constraint.Type", lambda constraint=constraint: constraint.Type, fatal=False)
            step("Constraint.Status", lambda constraint=constraint: constraint.Status, fatal=False)
        step("bottom.GetEndPoints (after update)", lambda: bottom.GetEndPoints([0.0] * 4),
             fatal=False)
    finally:
        if sketch is not None:
            delete(catia, sketch, SKETCH_NAME)
        verify_blank(part)


if __name__ == "__main__":
    main()
