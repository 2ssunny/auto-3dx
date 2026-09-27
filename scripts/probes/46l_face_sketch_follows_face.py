"""Probe 46l: does a face-supported sketch follow its face when the solid changes?

One question only. Fixture: exactly 46k's (block, top-face sketch, circle at local
(10, 5) r3, pocket 4 with the default direction), rebuilt. Then the pad's height is
written 20 -> 30 through `FirstLimit.Dimension.Value` (the verified `Pad.set_height`
route), one `Part.Update()`, and the sketch frame, the volume and the bore centre are read.
The height is then written back to 20 and rebuilt before cleanup.

If the sketch follows the face: frame origin z = 30, removed volume unchanged (113.097),
bore centre (10, 5, 28).

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46l_face_sketch_follows_face.py
"""

from _micro import (
    block_fixture, delete, marker, planar_face, require_blank_target, step,
    update_if_needed, verify_blank,
)

PREFIX = "AUTO3DX_P46L"


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    pad = face_sketch = pocket = None
    try:
        pad, _ = block_fixture(part, f"{PREFIX}_BLOCK")
        top = planar_face(part, (0, 0, 1), (0, 0, 1))
        sketches = step("MainBody.Sketches", lambda: raw.MainBody.Sketches)
        face_sketch = step("Sketches.Add(top face Reference)", lambda: sketches.Add(top.com_object))
        step("Sketch.Name = ...", lambda: setattr(face_sketch, "Name", f"{PREFIX}_TOP_SK"))
        factory = step("Sketch.OpenEdition (face sketch)", face_sketch.OpenEdition)
        step("Factory2D.CreateClosedCircle(10, 5, 3)",
             lambda: factory.CreateClosedCircle(10.0, 5.0, 3.0))
        step("Sketch.CloseEdition (face sketch)", face_sketch.CloseEdition)
        shape_factory = step("Part.ShapeFactory", lambda: raw.ShapeFactory)
        pocket = step("ShapeFactory.AddNewPocket(face sketch, 4)",
                      lambda: shape_factory.AddNewPocket(face_sketch, 4.0))
        step("Pocket.Name = ...", lambda: setattr(pocket, "Name", f"{PREFIX}_POCKET"))
        step("Part.Update", raw.Update)
        dimension = step("Pad.FirstLimit.Dimension", lambda: pad.FirstLimit.Dimension)
        step("Dimension.Value = 30", lambda: setattr(dimension, "Value", 30.0))
        step("Part.Update (height 30)", raw.Update, fatal=False)
        step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw)), fatal=False)
        step("face sketch GetAbsoluteAxisData",
             lambda: face_sketch.GetAbsoluteAxisData([0.0] * 9), fatal=False)
        volume = step("[composite, verified] measurement.measure().volume_mm3",
                      lambda: part.measurement.measure().volume_mm3, fatal=False)
        if volume is not None:
            marker(f"[RESULT] removed {60 * 40 * 30 - volume:.3f} mm3 at height 30")
        bore = step("[composite, verified] faces().query().cylindrical().one()",
                    lambda: part.topology.faces(body=None).query().cylindrical().one(),
                    fatal=False)
        if bore is not None:
            marker(f"[RESULT] bore centre {bore.geometry.center_mm}")
        step("Dimension.Value = 20", lambda: setattr(dimension, "Value", 20.0))
        step("Part.Update (height 20)", raw.Update, fatal=False)
    finally:
        if pocket is not None:
            delete(catia, pocket, f"{PREFIX}_POCKET")
        if face_sketch is not None:
            delete(catia, face_sketch, f"{PREFIX}_TOP_SK")
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
