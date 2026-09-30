"""Probe 47o: does orientation False always offset AGAINST the face's measured plane normal?

One question only. Probe 47e: on a block's top face (z = 20), whose measured plane normal
(`GetPlane` u x v) is +Z, orientation False put the offset plane at z = 15, i.e. against
that normal. Probe 45 measured the BOTTOM face's normal as +Z too. If the rule is "False =
against the measured normal", the bottom face's plane goes to z = -5 (outside the block)
and the +X side face's plane goes to x = 30 - 5 * nx. Fixture: the block. For the bottom
face and the +X face, each marked: the face's measured normal, `create_offset(face, 5,
False)`; then one `Part.Update()` and each plane's `GetOrigin`.

    $env:AUTO3DX_LIVE_PART = "<disposable Part>"
    python -u scripts/probes/47o_plane_offset_side_rule.py
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

PREFIX = "AUTO3DX_P47O"


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    pad = None
    made = []
    try:
        pad, _ = block_fixture(part, f"{PREFIX}_BLOCK")
        cases = []
        for label, axis, extreme in (
            ("bottom", (0, 0, 1), (0, 0, -1)),
            ("+X side", (1, 0, 0), (1, 0, 0)),
        ):
            face = planar_face(part, axis, extreme)
            normal = step(f"{label}: face normal", lambda face=face: face.geometry.normal)
            centre = step(f"{label}: face centre", lambda face=face: face.geometry.center_mm)
            plane = step(
                f"[composite] planes.create_offset({label}, 5.0, False)",
                lambda face=face, label=label: part.planes.create_offset(
                    f"{PREFIX}_{label[:2].strip('+')}", face, 5.0, False
                ),
                fatal=False,
            )
            if plane is not None:
                made.append(plane)
                cases.append((label, normal, centre, plane))
        step("Part.Update", raw.Update, fatal=False)
        step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw)), fatal=False)
        for label, normal, centre, plane in cases:
            origin = step(
                f"{label}: plane.GetOrigin",
                lambda plane=plane: plane.com_object.GetOrigin([0.0] * 3),
                fatal=False,
            )
            if origin is not None:
                shift = sum((origin[i] - centre[i]) * normal[i] for i in range(3))
                marker(
                    f"[RESULT] {label}: normal {normal}, centre {centre}, plane origin {origin}, "
                    f"signed shift along normal {shift:+.3f} (rule predicts -5)"
                )
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
