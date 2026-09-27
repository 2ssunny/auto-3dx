"""Probe 46aa: is a face sketch's normal outward on a recessed face (a pocket floor)?

One question only. 46i/46j showed outward normals on the top, bottom and a side face of a
convex block. Fixture: the block with a 20x10 rectangular pocket 4 deep cut from its top
face (the verified 46k route: top-face sketch, default pocket direction), rebuilt. The
pocket floor is the planar face with a Z normal nearest (0, 0, 16). Uncertain call, marked:
`Sketches.Add(<floor Reference>)`, then its `GetAbsoluteAxisData`. Out of the material at
the floor is +Z (up into the empty pocket).

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46aa_face_sketch_on_pocket_floor.py
"""

from _micro import (
    block_fixture, delete, marker, planar_face, require_blank_target, step, sweep,
    update_if_needed, verify_blank,
)

PREFIX = "AUTO3DX_P46AA"


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    pad = top_sketch = pocket = floor_sketch = None
    try:
        pad, _ = block_fixture(part, f"{PREFIX}_BLOCK")
        top = planar_face(part, (0, 0, 1), (0, 0, 1))
        sketches = step("MainBody.Sketches", lambda: raw.MainBody.Sketches)
        top_sketch = step("Sketches.Add(top face Reference)", lambda: sketches.Add(top.com_object))
        step("Sketch.Name = ...", lambda: setattr(top_sketch, "Name", f"{PREFIX}_TOP_SK"))
        factory = step("Sketch.OpenEdition (top)", top_sketch.OpenEdition)
        for a, b, c, d in ((-10, -5, 10, -5), (10, -5, 10, 5), (10, 5, -10, 5), (-10, 5, -10, -5)):
            step(f"Factory2D.CreateLine({a}, {b}, {c}, {d})",
                 lambda a=a, b=b, c=c, d=d: factory.CreateLine(float(a), float(b), float(c),
                                                               float(d)))
        step("Sketch.CloseEdition (top)", top_sketch.CloseEdition)
        pocket = step("ShapeFactory.AddNewPocket(top sketch, 4)",
                      lambda: raw.ShapeFactory.AddNewPocket(top_sketch, 4.0))
        step("Pocket.Name = ...", lambda: setattr(pocket, "Name", f"{PREFIX}_POCKET"))
        step("Part.Update", raw.Update)
        floor = step("[composite, verified] faces().query().planar().normal_parallel(Z)"
                     ".nearest((0, 0, 16)).one()",
                     lambda: part.topology.faces(body=None).query().planar()
                     .normal_parallel((0, 0, 1)).nearest((0.0, 0.0, 16.0)).one())
        marker(f"[INFO] floor centre {floor.geometry.center_mm} area {floor.geometry.area_mm2}")
        floor_sketch = step("Sketches.Add(floor face Reference)",
                            lambda: sketches.Add(floor.com_object), fatal=False)
        if floor_sketch is None:
            return
        step("Sketch.Name = ...", lambda: setattr(floor_sketch, "Name", f"{PREFIX}_FLOOR_SK"))
        frame = step("floor sketch GetAbsoluteAxisData",
                     lambda: floor_sketch.GetAbsoluteAxisData([0.0] * 9), fatal=False)
        if frame is not None:
            u, v = frame[3:6], frame[6:9]
            normal = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2],
                      u[0] * v[1] - u[1] * v[0])
            marker(f"[RESULT] floor sketch normal {tuple(round(n, 6) for n in normal)} "
                   "(outward = (0, 0, 1))")
        step("Part.Update", raw.Update, fatal=False)
    finally:
        if floor_sketch is not None:
            delete(catia, floor_sketch, f"{PREFIX}_FLOOR_SK")
        if pocket is not None:
            delete(catia, pocket, f"{PREFIX}_POCKET")
        if top_sketch is not None:
            delete(catia, top_sketch, f"{PREFIX}_TOP_SK")
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        sweep(catia, part, PREFIX)
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
