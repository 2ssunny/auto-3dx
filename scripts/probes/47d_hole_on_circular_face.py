"""Probe 47d: where does a positioned hole land on a planar face bounded only by a circle?

One question only. Phase 5 left a known issue: on such a face an off-centre
`AddNewHoleFromPoint` may be created at the circle's centre instead. Fixture: a disc, a
closed circle r = 20 at the origin padded 10 (its top face is bounded by one circular
edge), rebuilt. Then, each marked: `AddNewHoleFromPoint(8, 0, 10, top, 5)` with the
attributes the SDK writes (Diameter 4, BottomType 0 flat, LimitMode 0 blind),
`GetOrigin` before and after one `Part.Update()`, the measured bore centre, and -- to see
WHY -- the hole's positioning sketch read back after its edition is closed: its frame,
element names/types, point coordinates, and every constraint's name/type/element names.

    $env:AUTO3DX_LIVE_PART = "<disposable Part>"
    python -u scripts/probes/47d_hole_on_circular_face.py
"""

from _micro import (
    delete,
    marker,
    planar_face,
    require_blank_target,
    step,
    sweep,
    update_if_needed,
    verify_blank,
)

PREFIX = "AUTO3DX_P47D"


def disc(part, name):  # noqa: ANN001, ANN201 - probe helper
    raw = part.com_object
    plane = step("OriginElements.PlaneXY", lambda: raw.OriginElements.PlaneXY)
    sketches = step("MainBody.Sketches", lambda: raw.MainBody.Sketches)
    sketch = step("Sketches.Add(PlaneXY)", lambda: sketches.Add(plane))
    step("Sketch.Name = ...", lambda: setattr(sketch, "Name", f"{name}_SK"))
    factory = step("Sketch.OpenEdition", sketch.OpenEdition)
    step("CreateClosedCircle(0, 0, 20)", lambda: factory.CreateClosedCircle(0.0, 0.0, 20.0))
    step("Sketch.CloseEdition", sketch.CloseEdition)
    pad = step("AddNewPad(sketch, 10)", lambda: raw.ShapeFactory.AddNewPad(sketch, 10.0))
    step("Pad.Name = ...", lambda: setattr(pad, "Name", name))
    step("Part.Update", raw.Update)
    return pad


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    pad = hole = None
    try:
        pad = disc(part, f"{PREFIX}_DISC")
        top = planar_face(part, (0, 0, 1), (0, 0, 1))
        hole = step(
            "AddNewHoleFromPoint(8, 0, 10, top, 5)",
            lambda: raw.ShapeFactory.AddNewHoleFromPoint(8.0, 0.0, 10.0, top.com_object, 5.0),
        )
        step("Hole.Name = ...", lambda: setattr(hole, "Name", f"{PREFIX}_HOLE"))
        step("Diameter.Value = 4", lambda: setattr(hole.Diameter, "Value", 4.0))
        step("BottomType = 0", lambda: setattr(hole, "BottomType", 0))
        step("BottomLimit.LimitMode = 0", lambda: setattr(hole.BottomLimit, "LimitMode", 0))
        step("GetOrigin (before update)", lambda: hole.GetOrigin([0.0] * 3), fatal=False)
        step("Part.Update", raw.Update, fatal=False)
        step("GetOrigin (after update)", lambda: hole.GetOrigin([0.0] * 3), fatal=False)
        bore = step(
            "[composite, verified] faces().query().cylindrical().radius_near(2).one()",
            lambda: part.topology.faces(body=None).query().cylindrical().radius_near(2.0).one(),
            fatal=False,
        )
        if bore is not None:
            marker(f"[RESULT] bore centre {bore.geometry.center_mm} (requested x=8, y=0)")

        sketch = step("Hole.Sketch", lambda: hole.Sketch, fatal=False)
        if sketch is None:
            return
        step("hole sketch Name", lambda: str(sketch.Name), fatal=False)
        step(
            "hole sketch GetAbsoluteAxisData",
            lambda: sketch.GetAbsoluteAxisData([0.0] * 9),
            fatal=False,
        )
        elements = step("hole sketch GeometricElements", lambda: sketch.GeometricElements)
        count = step("GeometricElements.Count", lambda: int(elements.Count))
        for index in range(1, count + 1):
            item = step(
                f"GeometricElements.Item({index})", lambda index=index: elements.Item(index)
            )
            kind = type(item).__name__
            name = step("element Name", lambda item=item: str(item.Name), fatal=False)
            marker(f"[RESULT] element {index}: {name} ({kind})")
            if kind == "Point2D":
                step(
                    "Point2D.GetCoordinates",
                    lambda item=item: item.GetCoordinates([0.0] * 2),
                    fatal=False,
                )
        constraints = step("hole sketch Constraints", lambda: sketch.Constraints)
        count = step("Constraints.Count", lambda: int(constraints.Count))
        for index in range(1, count + 1):
            constraint = step(
                f"Constraints.Item({index})", lambda index=index: constraints.Item(index)
            )
            step("Constraint.Name", lambda c=constraint: str(c.Name), fatal=False)
            step("Constraint.Type", lambda c=constraint: int(c.Type), fatal=False)
            step("Constraint.Mode", lambda c=constraint: int(c.Mode), fatal=False)
            for position in (1, 2):
                step(
                    f"GetConstraintElement({position}).DisplayName",
                    lambda c=constraint, position=position: str(
                        c.GetConstraintElement(position).DisplayName
                    ),
                    fatal=False,
                )
    finally:
        if hole is not None:
            delete(catia, hole, f"{PREFIX}_HOLE")
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_DISC")
        sweep(catia, part, PREFIX)
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
