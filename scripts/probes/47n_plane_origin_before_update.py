"""Probe 47n: does a new offset plane report its origin BEFORE `Part.Update()`?

One question only. Probe 47e read `GetOrigin` of a face-offset plane after an update:
orientation False put it at z = 15 below a block's top face (z = 20), True at z = 25. To pick
a side without rebuilding the whole Part, the SDK would read the origin right after
creation. Fixture: the block. Each marked: `part.planes.create_offset(name, top, 5.0, False)`,
`plane.GetOrigin` (no update yet), `Part.IsUpToDate`, one `Part.Update()`, `plane.GetOrigin`.
The same z before and after means the pre-update read is usable.

    $env:AUTO3DX_LIVE_PART = "<disposable Part>"
    python -u scripts/probes/47n_plane_origin_before_update.py
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

PREFIX = "AUTO3DX_P47N"


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    pad = plane = None
    try:
        pad, _ = block_fixture(part, f"{PREFIX}_BLOCK")
        top = planar_face(part, (0, 0, 1), (0, 0, 1))
        plane = step(
            "[composite] planes.create_offset(top face, 5.0, False)",
            lambda: part.planes.create_offset(f"{PREFIX}_PLANE", top, 5.0, False),
        )
        before = step(
            "plane.GetOrigin (before update)",
            lambda: plane.com_object.GetOrigin([0.0] * 3),
            fatal=False,
        )
        step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw)), fatal=False)
        step("Part.Update", raw.Update, fatal=False)
        after = step(
            "plane.GetOrigin (after update)",
            lambda: plane.com_object.GetOrigin([0.0] * 3),
            fatal=False,
        )
        marker(f"[RESULT] before update {before}; after update {after} (47e: z = 15)")
    finally:
        if plane is not None:
            step(
                "[composite] planes.remove(plane, force=True)",
                lambda: part.planes.remove(plane, force=True),
                fatal=False,
            )
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
