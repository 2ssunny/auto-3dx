"""Probe 46z2: does `MeasurableBetween.DistanceMinToPoint` measure to the bounded face?

One question only. 46z called `DistanceMinToPoint(x, y, z)` and CATIA answered "Invalid
number of parameters": the late-bound call needs its four by-reference outputs
(distance, closest x, y, z) passed as seeds, as `GetPlane`/`GetPoints` already do. This
repeats 46z with that call form only. 46y showed a face-scoped selection search returns no boundary edges,
so the remaining candidate for an honest "does this edge lie on this face" test is a
point-to-face distance. That is only useful if the distance is to the FACE (bounded), not
to its infinite plane. Fixture: the 60x40x20 block, rebuilt; its top face (z = 20, x in
[-30, 30], y in [-20, 20]) from the verified query. Each call marked:
`Editor.GetService("MeasurableService")`, `GetMeasurable(top, 7)` (7 = Plane, the code the
SDK already uses), `CastTo(..., "MeasurableBetween")`, then `DistanceMinToPoint` for:
(0, 0, 20) on the face -> 0; (0, 0, 25) above it -> 5; (40, 0, 20) in its plane but 10 mm
outside the face -> 10 if bounded, 0 if the plane is used. Read-only.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46z2_face_point_distance_seeded.py
"""

import win32com.client

from _micro import (
    block_fixture, delete, marker, planar_face, require_blank_target, step, sweep,
    update_if_needed, verify_blank,
)

PREFIX = "AUTO3DX_P46Z2"
MEASURABLE_PLANE = 7


def main() -> None:
    catia, part = require_blank_target()
    pad = None
    try:
        pad, _ = block_fixture(part, f"{PREFIX}_BLOCK")
        top = planar_face(part, (0, 0, 1), (0, 0, 1))
        editor = step("Catia.active_editor", catia.active_editor)
        service = step("Editor.GetService('MeasurableService')",
                       lambda: editor.GetService("MeasurableService"))
        item = step("MeasurableService.GetMeasurable(top, 7)",
                    lambda: service.GetMeasurable(top.com_object, MEASURABLE_PLANE))
        between = step("CastTo(item, 'MeasurableBetween')",
                       lambda: win32com.client.CastTo(item, "MeasurableBetween"), fatal=False)
        if between is None:
            return
        for label, point, expected in (
            ("on the face", (0.0, 0.0, 20.0), "0"),
            ("5 mm above", (0.0, 0.0, 25.0), "5"),
            ("in plane, 10 mm outside", (40.0, 0.0, 20.0), "10 if bounded, 0 if plane"),
        ):
            result = step(f"DistanceMinToPoint{point} + 4 out seeds",
                          lambda point=point: between.DistanceMinToPoint(*point, 0.0, 0.0, 0.0, 0.0), fatal=False)
            marker(f"[RESULT] {label}: {result!r} (expected {expected})")
    finally:
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        sweep(catia, part, PREFIX)
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
