"""Probe the Sketch -> Pad vertical slice against the running 3DEXPERIENCE session.

Signatures confirmed from this installation's type library:

    OriginElements.PlaneXY / PlaneYZ / PlaneZX  -> Plane
    Body.Sketches.Add(iPlane)                   -> Sketch
    Sketch.OpenEdition()                        -> Factory2D
    Factory2D.CreateLine(iX1, iY1, iX2, iY2)    -> Line2D
    Sketch.CloseEdition()                       -> void
    ShapeFactory.AddNewPad(iSketch, iHeight)    -> Pad

Open questions this probe answers:

    - Does `Sketches.Add` accept the raw Plane, or does it need a Reference?
    - Are sketch coordinates millimetres, matching `Length.Value`?
    - Does an unconstrained 4-line closed profile pad successfully?
    - What are the created objects' names and where do they land in the tree?
    - Can the Pad and Sketch be removed again through `Editor.Selection`?

Unlike the parameter probes, geometry may not come back out cleanly. Run this
only against a scratch Part. The document is NEVER saved.
"""

from typing import Any

from auto_3dx import Catia

SKETCH_WIDTH = 60.0
SKETCH_HEIGHT = 40.0
PAD_HEIGHT = 20.0


def describe(com_object: Any) -> str:
    """Returns a COM object's wrapper type name."""
    return type(com_object).__name__


def corners() -> list[tuple[float, float, float, float]]:
    """Returns the four line segments of a closed rectangle at the origin."""
    return [
        (0.0, 0.0, SKETCH_WIDTH, 0.0),
        (SKETCH_WIDTH, 0.0, SKETCH_WIDTH, SKETCH_HEIGHT),
        (SKETCH_WIDTH, SKETCH_HEIGHT, 0.0, SKETCH_HEIGHT),
        (0.0, SKETCH_HEIGHT, 0.0, 0.0),
    ]


def main() -> None:
    """Runs the probe against the active Part."""
    catia = Catia.attach()
    part = catia.active_part()
    raw = part.com_object
    body = raw.MainBody

    print("Part:", part.name)
    print("Body:", body.Name, describe(body))
    print("Sketches before:", body.Sketches.Count)
    print("Shapes before:", body.Shapes.Count)

    plane = raw.OriginElements.PlaneXY
    print("PlaneXY:", describe(plane), getattr(plane, "Name", "<no Name>"))

    print()
    print("--- create sketch ---")
    sketch = body.Sketches.Add(plane)
    print("sketch:", describe(sketch), sketch.Name)

    factory = sketch.OpenEdition()
    print("factory:", describe(factory))
    for x1, y1, x2, y2 in corners():
        line = factory.CreateLine(x1, y1, x2, y2)
        print(f"  line ({x1},{y1})-({x2},{y2}) -> {describe(line)}")
    sketch.CloseEdition()
    print("CloseEdition: OK")

    part.update()
    print("Part.Update() after sketch: OK")
    print("Sketches after:", body.Sketches.Count)

    print()
    print("--- create pad ---")
    pad = raw.ShapeFactory.AddNewPad(sketch, PAD_HEIGHT)
    print("pad:", describe(pad), pad.Name)
    part.update()
    print("Part.Update() after pad: OK")
    print("Shapes after:", body.Shapes.Count)
    for index in range(1, body.Shapes.Count + 1):
        shape = body.Shapes.Item(index)
        print(f"  shape[{index}] {shape.Name} ({describe(shape)})")

    print()
    print("--- cleanup attempt via Editor.Selection ---")
    selection = catia.active_editor().Selection
    for target, label in ((pad, "pad"), (sketch, "sketch")):
        try:
            selection.Clear()
            selection.Add(target)
            selection.Delete()
            print(f"  deleted {label}")
        except Exception as error:  # noqa: BLE001 - probing whether delete works
            print(f"  could NOT delete {label}: {type(error).__name__}: {error}")
    selection.Clear()

    part.update()
    print("Sketches at end:", body.Sketches.Count)
    print("Shapes at end:", body.Shapes.Count)
    print()
    print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
