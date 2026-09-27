"""Probe 46w: does `CircularPatternParameters = catCompleteCrown (1)` spread copies over 360?

One question only. Fixture: the 46t seed cube (centre (25, 0, 5)), rebuilt; the verified
Z-axis pattern call with 6 instances but a deliberately wrong 10-degree spacing. Then
`CircularPatternParameters` is read, set to 1, one update, the mass properties, and
`AngularRepartition.AngularSpacing.Value` / `InstancesCount.Value` read back. As a complete
crown the six copies sit 60 degrees apart and do not touch: volume 6000, COG (0, 0, 5).
At 10 degrees they would overlap and the COG would sit off the axis.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46w_circular_pattern_complete_crown.py
"""

from _micro import (
    delete, marker, require_blank_target, step, sweep, update_if_needed, verify_blank,
)

PREFIX = "AUTO3DX_P46W"
CAT_COMPLETE_CROWN = 1


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    seed = pattern = None
    try:
        plane = step("OriginElements.PlaneXY", lambda: raw.OriginElements.PlaneXY)
        sketches = step("MainBody.Sketches", lambda: raw.MainBody.Sketches)
        sketch = step("Sketches.Add(PlaneXY)", lambda: sketches.Add(plane))
        step("Sketch.Name = ...", lambda: setattr(sketch, "Name", f"{PREFIX}_SEED_SK"))
        factory = step("Sketch.OpenEdition", sketch.OpenEdition)
        for a, b, c, d in ((20, -5, 30, -5), (30, -5, 30, 5), (30, 5, 20, 5), (20, 5, 20, -5)):
            step(f"Factory2D.CreateLine({a}, {b}, {c}, {d})",
                 lambda a=a, b=b, c=c, d=d: factory.CreateLine(float(a), float(b), float(c),
                                                               float(d)))
        step("Sketch.CloseEdition", sketch.CloseEdition)
        seed = step("ShapeFactory.AddNewPad(sketch, 10)",
                    lambda: raw.ShapeFactory.AddNewPad(sketch, 10.0))
        step("Pad.Name = ...", lambda: setattr(seed, "Name", f"{PREFIX}_SEED"))
        step("Part.Update", raw.Update)
        pattern = step(
            "ShapeFactory.AddNewCircPattern(seed, 1, 6, 1, 10, 1, 1, XY, XY, False, 0, True)",
            lambda: raw.ShapeFactory.AddNewCircPattern(
                seed, 1, 6, 1.0, 10.0, 1, 1, plane, plane, False, 0.0, True))
        step("Pattern.Name = ...", lambda: setattr(pattern, "Name", f"{PREFIX}_PAT"))
        step("CircularPatternParameters (default)", lambda: pattern.CircularPatternParameters,
             fatal=False)
        step("CircularPatternParameters = 1",
             lambda: setattr(pattern, "CircularPatternParameters", CAT_COMPLETE_CROWN))
        step("CircularPatternParameters read back", lambda: pattern.CircularPatternParameters,
             fatal=False)
        step("Part.Update", raw.Update, fatal=False)
        step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw)), fatal=False)
        mass = step("[composite, verified] measurement.measure()",
                    part.measurement.measure, fatal=False)
        if mass is not None:
            cog = tuple(round(value, 3) for value in mass.cog_mm)
            marker(f"[RESULT] volume {mass.volume_mm3:.3f} cog {cog} "
                   "(complete crown: 6000, (0, 0, 5))")
        step("AngularRepartition.AngularSpacing.Value",
             lambda: pattern.AngularRepartition.AngularSpacing.Value, fatal=False)
        step("AngularRepartition.InstancesCount.Value",
             lambda: pattern.AngularRepartition.InstancesCount.Value, fatal=False)
    finally:
        if pattern is not None:
            delete(catia, pattern, f"{PREFIX}_PAT")
        if seed is not None:
            delete(catia, seed, f"{PREFIX}_SEED")
        sweep(catia, part, PREFIX)
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
