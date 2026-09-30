"""Probe 47m: can `Hole.SetOrigin(x, y, z)` move a hole CATIA snapped to a circle's centre?

One question only. 47d: on a disc's top face (bounded by one circle) a hole requested at
(8, 0, 10) was created at (0, 0, 10) -- `GetOrigin` read the centre already before any
update, and its positioning sketch held one unconstrained point at (0, 0). Fixture: 47d's
disc and hole. Then, each marked: `SetOrigin(8, 0, 10)` (typelib member, never called
live), `GetOrigin`, the positioning sketch point's coordinates, one `Part.Update()`,
`GetOrigin`, and the measured bore centre.

    $env:AUTO3DX_LIVE_PART = "<disposable Part>"
    python -u scripts/probes/47m_hole_set_origin.py
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

PREFIX = "AUTO3DX_P47M"


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    pad = hole = None
    try:
        plane = step("OriginElements.PlaneXY", lambda: raw.OriginElements.PlaneXY)
        sketch = step("Sketches.Add(PlaneXY)", lambda: raw.MainBody.Sketches.Add(plane))
        step("Sketch.Name = ...", lambda: setattr(sketch, "Name", f"{PREFIX}_DISC_SK"))
        factory = step("Sketch.OpenEdition", sketch.OpenEdition)
        step("CreateClosedCircle(0, 0, 20)", lambda: factory.CreateClosedCircle(0.0, 0.0, 20.0))
        step("Sketch.CloseEdition", sketch.CloseEdition)
        pad = step("AddNewPad(sketch, 10)", lambda: raw.ShapeFactory.AddNewPad(sketch, 10.0))
        step("Pad.Name = ...", lambda: setattr(pad, "Name", f"{PREFIX}_DISC"))
        step("Part.Update", raw.Update)
        top = planar_face(part, (0, 0, 1), (0, 0, 1))
        hole = step(
            "AddNewHoleFromPoint(8, 0, 10, top, 5)",
            lambda: raw.ShapeFactory.AddNewHoleFromPoint(8.0, 0.0, 10.0, top.com_object, 5.0),
        )
        step("Hole.Name = ...", lambda: setattr(hole, "Name", f"{PREFIX}_HOLE"))
        step("Diameter.Value = 4", lambda: setattr(hole.Diameter, "Value", 4.0))
        step("BottomType = 0", lambda: setattr(hole, "BottomType", 0))
        step("BottomLimit.LimitMode = 0", lambda: setattr(hole.BottomLimit, "LimitMode", 0))
        step("GetOrigin (as created)", lambda: hole.GetOrigin([0.0] * 3))
        step("Hole.SetOrigin(8, 0, 10)", lambda: hole.SetOrigin(8.0, 0.0, 10.0), fatal=False)
        step("GetOrigin (after SetOrigin)", lambda: hole.GetOrigin([0.0] * 3), fatal=False)
        point = step(
            "positioning sketch Point.1",
            lambda: hole.Sketch.GeometricElements.Item("Point.1"),
            fatal=False,
        )
        if point is not None:
            step("Point.1 GetCoordinates", lambda: point.GetCoordinates([0.0] * 2), fatal=False)
        step("Part.Update", raw.Update, fatal=False)
        step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw)), fatal=False)
        step("GetOrigin (after update)", lambda: hole.GetOrigin([0.0] * 3), fatal=False)
        bore = step(
            "[composite, verified] cylindrical radius 2",
            lambda: part.topology.faces(body=None).query().cylindrical().radius_near(2.0).one(),
            fatal=False,
        )
        if bore is not None:
            marker(f"[RESULT] bore centre {bore.geometry.center_mm} (requested x = 8, y = 0)")
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
