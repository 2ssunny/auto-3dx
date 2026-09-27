"""Probe 46u: can a cylindrical face be a circular pattern's rotation centre and axis?

One question only. Fixture: the 46t seed cube (centre (25, 0, 5), 1000 mm3) and a hub pad,
a circle of r = 5 at (50, 40) padded 10 (785.398 mm3), both in the main body, rebuilt. The
hub's cylindrical face comes from the verified query. Uncertain call:
`AddNewCircPattern(seed, 1, 4, 1.0, 90.0, 1, 1, hub_face, hub_face, False, 0.0, True)`,
one update, the mass properties. If the pattern turns about the hub axis, the four seed
copies are centred on (50, 40), none touches the hub, so the whole body has volume
4785.398 and COG (50, 40, 5).

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46u_circular_pattern_cylinder_axis.py
"""

from _micro import delete, marker, require_blank_target, step, update_if_needed, verify_blank

PREFIX = "AUTO3DX_P46U"


def pad_from(part, name, draw, height):
    raw = part.com_object
    plane = step("OriginElements.PlaneXY", lambda: raw.OriginElements.PlaneXY)
    sketches = step("MainBody.Sketches", lambda: raw.MainBody.Sketches)
    sketch = step("Sketches.Add(PlaneXY)", lambda: sketches.Add(plane))
    step("Sketch.Name = ...", lambda: setattr(sketch, "Name", f"{name}_SK"))
    factory = step("Sketch.OpenEdition", sketch.OpenEdition)
    draw(factory)
    step("Sketch.CloseEdition", sketch.CloseEdition)
    pad = step(
        f"ShapeFactory.AddNewPad(sketch, {height})",
        lambda: raw.ShapeFactory.AddNewPad(sketch, height),
    )
    step("Pad.Name = ...", lambda: setattr(pad, "Name", name))
    return pad


def square(factory):
    for a, b, c, d in ((20, -5, 30, -5), (30, -5, 30, 5), (30, 5, 20, 5), (20, 5, 20, -5)):
        step(
            f"Factory2D.CreateLine({a}, {b}, {c}, {d})",
            lambda a=a, b=b, c=c, d=d: factory.CreateLine(float(a), float(b), float(c), float(d)),
        )


def hub_circle(factory):
    step(
        "Factory2D.CreateClosedCircle(50, 40, 5)",
        lambda: factory.CreateClosedCircle(50.0, 40.0, 5.0),
    )


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    seed = hub = pattern = None
    try:
        seed = pad_from(part, f"{PREFIX}_SEED", square, 10.0)
        hub = pad_from(part, f"{PREFIX}_HUB", hub_circle, 10.0)
        step("Part.Update", raw.Update)
        mass = step("[composite, verified] measurement.measure()", part.measurement.measure)
        marker(f"[INFO] seed + hub volume {mass.volume_mm3:.3f} cog {mass.cog_mm}")
        face = step(
            "[composite, verified] faces().query().cylindrical().radius_near(5).one()",
            lambda: part.topology.faces(body=None)
            .query()
            .cylindrical()
            .radius_near(5.0, 0.01)
            .one(),
        )
        marker(f"[INFO] hub face centre {face.geometry.center_mm}")
        pattern = step(
            "ShapeFactory.AddNewCircPattern(seed, 1, 4, 1, 90, 1, 1, hub, hub, False, 0, True)",
            lambda: raw.ShapeFactory.AddNewCircPattern(
                seed, 1, 4, 1.0, 90.0, 1, 1, face.com_object, face.com_object, False, 0.0, True
            ),
            fatal=False,
        )
        if pattern is not None:
            step("Pattern.Name = ...", lambda: setattr(pattern, "Name", f"{PREFIX}_PAT"))
            step("Part.Update", raw.Update, fatal=False)
            step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw)), fatal=False)
            mass = step(
                "[composite, verified] measurement.measure()", part.measurement.measure, fatal=False
            )
            if mass is not None:
                cog = tuple(round(value, 3) for value in mass.cog_mm)
                marker(
                    f"[RESULT] volume {mass.volume_mm3:.3f} cog {cog} "
                    "(about the hub axis: 4785.398, (50, 40, 5))"
                )
    finally:
        if pattern is not None:
            delete(catia, pattern, f"{PREFIX}_PAT")
        if hub is not None:
            delete(catia, hub, f"{PREFIX}_HUB")
        if seed is not None:
            delete(catia, seed, f"{PREFIX}_SEED")
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
