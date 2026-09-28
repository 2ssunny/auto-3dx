"""Probe 46t: which rotation axis do the YZ and ZX origin planes give a circular pattern?

One question only. Probe 44 verified PlaneXY -> Z but could not identify the axis for YZ
and ZX on its disc. Fixture: one 10 mm cube pad (x 20..30, y -5..5, z 0..10; centre
(25, 0, 5)), rebuilt. For each origin plane in turn, the call probe 44 already made live
(`AddNewCircPattern(seed, 1, 4, 1.0, 90.0, 1, 1, plane, plane, False, 0.0, True)`),
one update, the centre of gravity, then the pattern is deleted and the Part rebuilt.
XY is repeated as the control. Four 90-degree copies put the COG on the axis:
Z -> (0, 0, 5), X -> (25, 0, 0), Y -> (0, 0, 0).

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46t_circular_pattern_origin_axes.py
"""

from _micro import delete, marker, require_blank_target, step, update_if_needed, verify_blank

PREFIX = "AUTO3DX_P46T"


def cube(part, name):
    raw = part.com_object
    plane = step("OriginElements.PlaneXY", lambda: raw.OriginElements.PlaneXY)
    sketches = step("MainBody.Sketches", lambda: raw.MainBody.Sketches)
    sketch = step("Sketches.Add(PlaneXY)", lambda: sketches.Add(plane))
    step("Sketch.Name = ...", lambda: setattr(sketch, "Name", f"{name}_SK"))
    factory = step("Sketch.OpenEdition", sketch.OpenEdition)
    for a, b, c, d in ((20, -5, 30, -5), (30, -5, 30, 5), (30, 5, 20, 5), (20, 5, 20, -5)):
        step(
            f"Factory2D.CreateLine({a}, {b}, {c}, {d})",
            lambda a=a, b=b, c=c, d=d: factory.CreateLine(float(a), float(b), float(c), float(d)),
        )
    step("Sketch.CloseEdition", sketch.CloseEdition)
    pad = step(
        "ShapeFactory.AddNewPad(sketch, 10)", lambda: raw.ShapeFactory.AddNewPad(sketch, 10.0)
    )
    step("Pad.Name = ...", lambda: setattr(pad, "Name", name))
    step("Part.Update", raw.Update)
    return pad


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    seed = None
    try:
        seed = cube(part, f"{PREFIX}_SEED")
        mass = step("[composite, verified] measurement.measure()", part.measurement.measure)
        marker(f"[INFO] seed volume {mass.volume_mm3:.3f} cog {mass.cog_mm}")
        origin = step("Part.OriginElements", lambda: raw.OriginElements)
        for label in ("PlaneYZ", "PlaneZX", "PlaneXY"):
            plane = step(f"OriginElements.{label}", lambda label=label: getattr(origin, label))
            pattern = step(
                f"ShapeFactory.AddNewCircPattern(seed, 1, 4, 1, 90, 1, 1, {label}, {label}, "
                "False, 0, True)",
                lambda plane=plane: raw.ShapeFactory.AddNewCircPattern(
                    seed, 1, 4, 1.0, 90.0, 1, 1, plane, plane, False, 0.0, True
                ),
                fatal=False,
            )
            if pattern is None:
                continue
            name = f"{PREFIX}_PAT_{label}"
            step(
                "Pattern.Name = ...",
                lambda pattern=pattern, name=name: setattr(pattern, "Name", name),
            )
            if step("Part.Update", raw.Update, fatal=False) is None and not bool(
                raw.IsUpToDate(raw)
            ):
                marker(f"[RESULT] {label}: update failed")
            else:
                mass = step(
                    "[composite, verified] measurement.measure()",
                    part.measurement.measure,
                    fatal=False,
                )
                if mass is not None:
                    cog = tuple(round(value, 3) for value in mass.cog_mm)
                    marker(f"[RESULT] {label}: volume {mass.volume_mm3:.3f} cog {cog}")
            delete(catia, pattern, name)
            step("Part.Update", raw.Update, fatal=False)
    finally:
        if seed is not None:
            delete(catia, seed, f"{PREFIX}_SEED")
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
