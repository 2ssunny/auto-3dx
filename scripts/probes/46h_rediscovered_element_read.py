"""Probe 46h: do geometry reads work on an element found again by name?

One question only. Fixture: one sketch on XY holding one line (10,5)-(40,25) and one
closed circle (20,15) r4, edition closed. The probe then attaches again, finds the sketch
through `MainBody.Sketches`, lists `GeometricElements` by index (names and COM type names
only), and reads `GetEndPoints` / `GetCenter` on the elements fetched by
`GeometricElements.Item(name)` -- the rediscovery path `sketch.get_element(name)` uses.
No reads are made on element kinds other than `Line2D` and `Circle2D`.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46h_rediscovered_element_read.py
"""

from auto_3dx import Catia

from _micro import delete, marker, require_blank_target, step, verify_blank

SKETCH_NAME = "AUTO3DX_P46H_REDISCOVER"


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    sketch = None
    try:
        plane = step("OriginElements.PlaneXY", lambda: raw.OriginElements.PlaneXY)
        sketches = step("MainBody.Sketches", lambda: raw.MainBody.Sketches)
        sketch = step("Sketches.Add(PlaneXY)", lambda: sketches.Add(plane))
        step("Sketch.Name = ...", lambda: setattr(sketch, "Name", SKETCH_NAME))
        factory = step("Sketch.OpenEdition", sketch.OpenEdition)
        step(
            "Factory2D.CreateLine(10, 5, 40, 25)", lambda: factory.CreateLine(10.0, 5.0, 40.0, 25.0)
        )
        step(
            "Factory2D.CreateClosedCircle(20, 15, 4)",
            lambda: factory.CreateClosedCircle(20.0, 15.0, 4.0),
        )
        step("Sketch.CloseEdition", sketch.CloseEdition)
        marker("[EDITION] closed; rediscovering through a new attach")
        fresh_part = step("Catia.attach().part_named", lambda: Catia.attach().part_named(part.name))
        fresh_sketches = step(
            "MainBody.Sketches (fresh)", lambda: fresh_part.com_object.MainBody.Sketches
        )
        fresh = step("Sketches.Item(name)", lambda: fresh_sketches.Item(SKETCH_NAME))
        elements = step("Sketch.GeometricElements", lambda: fresh.GeometricElements)
        count = step("GeometricElements.Count", lambda: int(elements.Count))
        names = []
        for index in range(1, count + 1):
            item = step(
                f"GeometricElements.Item({index})", lambda index=index: elements.Item(index)
            )
            name = step(f"Item({index}).Name", lambda item=item: item.Name)
            marker(f"[INFO] element {index}: {name} ({type(item).__name__})")
            names.append((name, type(item).__name__))
        for name, kind in names:
            if kind not in ("Line2D", "Circle2D"):
                continue
            item = step(f"GeometricElements.Item({name!r})", lambda name=name: elements.Item(name))
            if kind == "Line2D":
                step(
                    f"{name}.GetEndPoints",
                    lambda item=item: item.GetEndPoints([0.0] * 4),
                    fatal=False,
                )
            else:
                step(f"{name}.GetCenter", lambda item=item: item.GetCenter([0.0] * 2), fatal=False)
                step(f"{name}.Radius", lambda item=item: item.Radius, fatal=False)
    finally:
        if sketch is not None:
            delete(catia, sketch, SKETCH_NAME)
        verify_blank(part)


if __name__ == "__main__":
    main()
