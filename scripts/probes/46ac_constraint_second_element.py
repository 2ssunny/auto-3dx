"""Probe 46ac: does `GetConstraintElement(2)` name the second element of a two-element constraint?

One question only. 46e verified element 1 of a length constraint. Fixture: one sketch on
XY, two lines (0,0)-(30,0) and (0,0)-(0,20), one perpendicularity constraint between them
(`AddBiEltCst(11, first, second)`, the verified `SketchEditor.perpendicular` path). The
edition is closed, then `GetConstraintElement(1)` and `(2)` are read with their
`DisplayName` only.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46ac_constraint_second_element.py
"""

from _micro import delete, marker, require_blank_target, step, verify_blank

SKETCH_NAME = "AUTO3DX_P46AC_ELEMENTS"
CONSTRAINT_PERPENDICULAR = 11


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
        first = step(
            "Factory2D.CreateLine(0, 0, 30, 0)", lambda: factory.CreateLine(0.0, 0.0, 30.0, 0.0)
        )
        second = step(
            "Factory2D.CreateLine(0, 0, 0, 20)", lambda: factory.CreateLine(0.0, 0.0, 0.0, 20.0)
        )
        constraint = step(
            "Constraints.AddBiEltCst(perpendicular, first, second)",
            lambda: constraints.AddBiEltCst(CONSTRAINT_PERPENDICULAR, first, second),
        )
        step("Sketch.CloseEdition", sketch.CloseEdition)
        marker("[EDITION] closed; reading back")
        step("first.Name", lambda: first.Name, fatal=False)
        step("second.Name", lambda: second.Name, fatal=False)
        for number in (1, 2):
            element = step(
                f"Constraint.GetConstraintElement({number})",
                lambda number=number: constraint.GetConstraintElement(number),
                fatal=False,
            )
            if element is not None:
                step(
                    f"element {number}.DisplayName",
                    lambda element=element: element.DisplayName,
                    fatal=False,
                )
    finally:
        if sketch is not None:
            delete(catia, sketch, SKETCH_NAME)
        verify_blank(part)


if __name__ == "__main__":
    main()
