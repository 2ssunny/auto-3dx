"""Probe 46i: does `Sketches.Add` accept a planar face Reference, and which frame results?

One question only. Fixture: one 60x40x20 block standing on XY, centred on the origin,
rebuilt. The top face is found with the verified Phase 4 query (planar, normal parallel to
Z, extreme +Z) -- its `Reference` comes from `Selection.Search`, the only verified route.

Uncertain calls, each marked: `Sketches.Add(<face Reference>)`, then
`GetAbsoluteAxisData` on the new sketch, then one `Part.Update()` with the empty sketch in
the tree. No geometry is drawn and no feature is built on the sketch.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46i_sketch_on_planar_face.py
"""

from _micro import (
    block_fixture,
    delete,
    marker,
    planar_face,
    require_blank_target,
    step,
    update_if_needed,
    verify_blank,
)

PREFIX = "AUTO3DX_P46I"


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    pad = face_sketch = None
    try:
        pad, _ = block_fixture(part, f"{PREFIX}_BLOCK")
        top = planar_face(part, (0, 0, 1), (0, 0, 1))
        marker(f"[INFO] top face centre {top.geometry.center_mm} normal {top.geometry.normal}")
        sketches = step("MainBody.Sketches", lambda: raw.MainBody.Sketches)
        face_sketch = step(
            "Sketches.Add(top face Reference)", lambda: sketches.Add(top.com_object), fatal=False
        )
        if face_sketch is None:
            return
        step("Sketch.Name = ...", lambda: setattr(face_sketch, "Name", f"{PREFIX}_TOP_SK"))
        step(
            "Sketch.GetAbsoluteAxisData([0.0] * 9)",
            lambda: face_sketch.GetAbsoluteAxisData([0.0] * 9),
            fatal=False,
        )
        step("Part.Update", raw.Update, fatal=False)
        step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw)), fatal=False)
    finally:
        if face_sketch is not None:
            delete(catia, face_sketch, f"{PREFIX}_TOP_SK")
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
