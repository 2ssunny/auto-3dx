"""Probe 46x: which way does a circular pattern turn, and does `iIsReversedRotationAxis` flip it?

One question only. Fixture: the 46t seed cube (centre (25, 0, 5)), rebuilt. The verified
Z-axis call with 2 instances 90 degrees apart, once with `iIsReversedRotationAxis = False`
(the value every SDK pattern uses today) and once with `True`, each updated, measured and
deleted. The copy lands at (0, 25, 5) for a counter-clockwise turn seen from +Z (COG
(12.5, 12.5, 5)) or at (0, -25, 5) for clockwise (COG (12.5, -12.5, 5)).

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46x_circular_pattern_rotation_sense.py
"""

from _micro import (
    delete,
    marker,
    require_blank_target,
    step,
    sweep,
    update_if_needed,
    verify_blank,
)

PREFIX = "AUTO3DX_P46X"


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    seed = None
    try:
        plane = step("OriginElements.PlaneXY", lambda: raw.OriginElements.PlaneXY)
        sketches = step("MainBody.Sketches", lambda: raw.MainBody.Sketches)
        sketch = step("Sketches.Add(PlaneXY)", lambda: sketches.Add(plane))
        step("Sketch.Name = ...", lambda: setattr(sketch, "Name", f"{PREFIX}_SEED_SK"))
        factory = step("Sketch.OpenEdition", sketch.OpenEdition)
        for a, b, c, d in ((20, -5, 30, -5), (30, -5, 30, 5), (30, 5, 20, 5), (20, 5, 20, -5)):
            step(
                f"Factory2D.CreateLine({a}, {b}, {c}, {d})",
                lambda a=a, b=b, c=c, d=d: factory.CreateLine(
                    float(a), float(b), float(c), float(d)
                ),
            )
        step("Sketch.CloseEdition", sketch.CloseEdition)
        seed = step(
            "ShapeFactory.AddNewPad(sketch, 10)", lambda: raw.ShapeFactory.AddNewPad(sketch, 10.0)
        )
        step("Pad.Name = ...", lambda: setattr(seed, "Name", f"{PREFIX}_SEED"))
        step("Part.Update", raw.Update)
        for reversed_axis in (False, True):
            pattern = step(
                f"ShapeFactory.AddNewCircPattern(seed, 1, 2, 1, 90, 1, 1, XY, XY, "
                f"{reversed_axis}, 0, True)",
                lambda reversed_axis=reversed_axis: raw.ShapeFactory.AddNewCircPattern(
                    seed, 1, 2, 1.0, 90.0, 1, 1, plane, plane, reversed_axis, 0.0, True
                ),
            )
            name = f"{PREFIX}_PAT_{int(reversed_axis)}"
            step(
                "Pattern.Name = ...",
                lambda pattern=pattern, name=name: setattr(pattern, "Name", name),
            )
            step("Part.Update", raw.Update, fatal=False)
            mass = step(
                "[composite, verified] measurement.measure()", part.measurement.measure, fatal=False
            )
            if mass is not None:
                cog = tuple(round(value, 3) for value in mass.cog_mm)
                marker(f"[RESULT] reversed={reversed_axis}: volume {mass.volume_mm3:.3f} cog {cog}")
            delete(catia, pattern, name)
            step("Part.Update", raw.Update, fatal=False)
    finally:
        if seed is not None:
            delete(catia, seed, f"{PREFIX}_SEED")
        sweep(catia, part, PREFIX)
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
