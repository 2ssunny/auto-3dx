"""Probe 47l: does `GetMeasurable(face, CAAMeasurableBetween=1)` measure point-to-FACE distance?

One question only. Probe 46z asked the measurable service for type 7 (plane) and cast the
result to `MeasurableBetween`; the call failed with "Invalid number of parameters",
consistent with calling a MeasurablePlane dispatch id. The type library lists
`CAAMeasurableBetween = 1` as its own measurable type. Fixture: the block (top face z = 20,
x in [-30, 30], y in [-20, 20]). Each marked: `GetService("MeasurableService")`,
`GetMeasurable(top, 1)`, `CastTo(..., "MeasurableBetween")`, then `DistanceMinToPoint` for
(0, 0, 20) on the face -> 0; (0, 0, 25) above it -> 5; (40, 0, 20) in its plane but outside
the face -> 10 if the face is bounded, 0 if its plane is used. Read-only.

    $env:AUTO3DX_LIVE_PART = "<disposable Part>"
    python -u scripts/probes/47l_measurable_between.py
"""

import win32com.client

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

PREFIX = "AUTO3DX_P47L"
CAA_MEASURABLE_BETWEEN = 1


def main() -> None:
    catia, part = require_blank_target()
    pad = None
    try:
        pad, _ = block_fixture(part, f"{PREFIX}_BLOCK")
        top = planar_face(part, (0, 0, 1), (0, 0, 1))
        editor = step("Catia.active_editor", catia.active_editor)
        service = step(
            "Editor.GetService('MeasurableService')",
            lambda: editor.GetService("MeasurableService"),
        )
        item = step(
            "MeasurableService.GetMeasurable(top, 1)",
            lambda: service.GetMeasurable(top.com_object, CAA_MEASURABLE_BETWEEN),
            fatal=False,
        )
        if item is None:
            return
        marker(f"[INFO] measurable type {type(item).__name__}")
        between = step(
            "CastTo(item, 'MeasurableBetween')",
            lambda: win32com.client.CastTo(item, "MeasurableBetween"),
            fatal=False,
        )
        if between is None:
            return
        for label, point, expected in (
            ("on the face", (0.0, 0.0, 20.0), "0"),
            ("5 mm above", (0.0, 0.0, 25.0), "5"),
            ("in plane, 10 mm outside", (40.0, 0.0, 20.0), "10 if bounded, 0 if plane"),
        ):
            result = step(
                f"DistanceMinToPoint{point}",
                lambda point=point: between.DistanceMinToPoint(*point),
                fatal=False,
            )
            marker(f"[RESULT] {label}: {result!r} (expected {expected})")
    finally:
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        sweep(catia, part, PREFIX)
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
