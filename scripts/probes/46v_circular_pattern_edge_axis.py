"""Probe 46v: can a linear edge be a circular pattern's rotation centre and axis?

One question only. Fixture: the 46t seed cube (x 20..30, y -5..5, z 0..10), rebuilt. Its
vertical edge at (30, 5) comes from the verified edge query (lines parallel to Z nearest
(30, 5, 5)). Uncertain call: `AddNewCircPattern(seed, 1, 4, 1.0, 90.0, 1, 1, edge, edge,
False, 0.0, True)`, one update, the mass properties. About that edge the four copies only
touch along it: volume 4000, COG (30, 5, 5).

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46v_circular_pattern_edge_axis.py
"""

from _micro import (
    delete, marker, require_blank_target, step, sweep, update_if_needed, verify_blank,
)

PREFIX = "AUTO3DX_P46V"


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
        edge = step("[composite, verified] edges().query().lines().parallel(Z).nearest((30,5,5))"
                    ".one()",
                    lambda: part.topology.edges(body=None).query().lines().parallel((0, 0, 1))
                    .nearest((30.0, 5.0, 5.0)).one())
        marker(f"[INFO] edge {edge.geometry.start_mm} -> {edge.geometry.end_mm}")
        pattern = step(
            "ShapeFactory.AddNewCircPattern(seed, 1, 4, 1, 90, 1, 1, edge, edge, False, 0, True)",
            lambda: raw.ShapeFactory.AddNewCircPattern(
                seed, 1, 4, 1.0, 90.0, 1, 1, edge.com_object, edge.com_object, False, 0.0,
                True),
            fatal=False)
        if pattern is not None:
            step("Pattern.Name = ...", lambda: setattr(pattern, "Name", f"{PREFIX}_PAT"))
            step("Part.Update", raw.Update, fatal=False)
            step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw)), fatal=False)
            mass = step("[composite, verified] measurement.measure()",
                        part.measurement.measure, fatal=False)
            if mass is not None:
                cog = tuple(round(value, 3) for value in mass.cog_mm)
                marker(f"[RESULT] volume {mass.volume_mm3:.3f} cog {cog} "
                       "(about the edge: 4000, (30, 5, 5))")
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
