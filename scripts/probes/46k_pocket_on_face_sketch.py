"""Probe 46k: does a pocket on a top-face sketch cut into the material where expected?

One question only. Fixture: the 60x40x20 block; a sketch on its top face (verified in
46i: frame (0,0,20 | X | Y), outward normal). One closed circle at LOCAL (10, 5), r = 3,
drawn inside the edition, which is then closed. Then `AddNewPocket(sketch, 4)` with
CATIA's default direction (against the sketch normal, which 46i/46j showed is outward, so
it should cut into the material), one `Part.Update()`, and a volume measurement.

Expected if the frame maps local (u, v) to origin + u*X + v*Y and the default cuts inward:
removed = pi * 3^2 * 4 = 113.097 mm3, and the new cylindrical face centred at (10, 5, 18).

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46k_pocket_on_face_sketch.py
"""

import math

from _micro import (
    block_fixture, delete, marker, planar_face, require_blank_target, step,
    update_if_needed, verify_blank,
)

PREFIX = "AUTO3DX_P46K"


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    pad = face_sketch = pocket = None
    try:
        pad, _ = block_fixture(part, f"{PREFIX}_BLOCK")
        before = step("[composite, verified] measurement.measure().volume_mm3",
                      lambda: part.measurement.measure().volume_mm3)
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
        step("Pocket.DirectionOrientation (default)", lambda: pocket.DirectionOrientation)
        step("Part.Update", raw.Update)
        after = step("[composite, verified] measurement.measure().volume_mm3",
                     lambda: part.measurement.measure().volume_mm3)
        marker(f"[RESULT] removed {before - after:.3f} mm3; a full cut is "
               f"{math.pi * 9 * 4:.3f}")
        bore = step("[composite, verified] faces().query().cylindrical().one()",
                    lambda: part.topology.faces(body=None).query().cylindrical().one())
        marker(f"[RESULT] bore centre {bore.geometry.center_mm} radius {bore.geometry.radius_mm}")
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
