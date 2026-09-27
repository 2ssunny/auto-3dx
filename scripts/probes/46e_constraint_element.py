"""Probe 46e: does `Constraint.GetConstraintElement(1)` name the element it constrains?

One question only. Fixture: one sketch on XY, one line (0,0)-(30,0), one length
constraint on it (the verified `AddMonoEltCst(5, line)` path). The edition is closed
before the read. The read is `GetConstraintElement(1)` and then only the returned
object's type name and `DisplayName`/`Name`, compared with the line's own name.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46e_constraint_element.py
"""

from _micro import delete, marker, require_blank_target, step, verify_blank

SKETCH_NAME = "AUTO3DX_P46E_ELEMENT"
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
        line = step("Factory2D.CreateLine(0, 0, 30, 0)",
                    lambda: factory.CreateLine(0.0, 0.0, 30.0, 0.0))
        constraint = step("Constraints.AddMonoEltCst(length, line)",
                          lambda: constraints.AddMonoEltCst(CONSTRAINT_LENGTH, line))
        step("Sketch.CloseEdition", sketch.CloseEdition)
        marker("[EDITION] closed; reading back")
        step("Line2D.Name", lambda: line.Name, fatal=False)
        element = step("Constraint.GetConstraintElement(1)",
                       lambda: constraint.GetConstraintElement(1), fatal=False)
        if element is not None:
            marker(f"[INFO] element type {type(element).__name__}")
            step("element.DisplayName", lambda: element.DisplayName, fatal=False)
            step("element.Name", lambda: element.Name, fatal=False)
    finally:
        if sketch is not None:
            delete(catia, sketch, SKETCH_NAME)
        verify_blank(part)


if __name__ == "__main__":
    main()
