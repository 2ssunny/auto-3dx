"""Probe 47e: can an offset reference plane be built from a planar face, and which side?

One question only. `PlaneCollection.create_offset` passes its support's `com_object` to
`HybridShapeFactory.AddNewPlaneOffset(support, offset, orientation)`; with a `Face` that is
the face's `Reference`, a call never made live. Fixture: the block (top face z = 20).
Marked composite steps: `part.planes.create_offset(name, top_face, 5.0, orientation)` for
orientation False and True, one update each, then the plane's frame (`GetOrigin`,
`GetFirstAxis`, `GetSecondAxis`). Outward from the top face is +Z, so a plane at z = 25 is
"away from the material". The planes and the SDK's geometrical set are removed afterwards
(the set did not exist before: the blank baseline has none).

    $env:AUTO3DX_LIVE_PART = "<disposable Part>"
    python -u scripts/probes/47e_plane_offset_from_face.py
"""

from _micro import (
    block_fixture,
    delete,
    marker,
    planar_face,
    require_blank_target,
    step,
    sweep,
    update_if_needed,
    verify_blank,
)

PREFIX = "AUTO3DX_P47E"


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    pad = None
    made = []
    try:
        pad, _ = block_fixture(part, f"{PREFIX}_BLOCK")
        for orientation in (False, True):
            top = planar_face(part, (0, 0, 1), (0, 0, 1))
            name = f"{PREFIX}_PLANE_{int(orientation)}"
            plane = step(
                f"[composite] planes.create_offset({name}, top face, 5.0, {orientation})",
                lambda top=top, name=name, orientation=orientation: part.planes.create_offset(
                    name, top, 5.0, orientation
                ),
                fatal=False,
            )
            if plane is None:
                continue
            made.append(plane)
            step("Part.Update", raw.Update, fatal=False)
            step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw)), fatal=False)
            origin = step(
                "plane.GetOrigin",
                lambda p=plane: plane.com_object.GetOrigin([0.0] * 3),
                fatal=False,
            )
            step(
                "plane.GetFirstAxis", lambda: plane.com_object.GetFirstAxis([0.0] * 3), fatal=False
            )
            step(
                "plane.GetSecondAxis",
                lambda: plane.com_object.GetSecondAxis([0.0] * 3),
                fatal=False,
            )
            step("plane.offset", lambda: plane.offset, fatal=False)
            marker(f"[RESULT] orientation={orientation}: origin {origin} (top face is z = 20)")
    finally:
        for plane in reversed(made):
            step(
                "[composite] planes.remove(plane, force=True)",
                lambda plane=plane: part.planes.remove(plane, force=True),
                fatal=False,
            )
        if made:
            step(
                "[composite] planes.remove_geometrical_set(force=True)",
                lambda: part.planes.remove_geometrical_set(force=True),
                fatal=False,
            )
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        sweep(catia, part, PREFIX)
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
