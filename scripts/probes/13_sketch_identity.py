"""Probe what a Sketch can report about itself, for `ensure` semantics.

`Sketch` exposes no `Support`/`Plane` property, so an `ensure` that must refuse
to reuse a sketch built on the wrong plane needs another way to recover the
support. The candidates are `GetAbsoluteAxisData` and `AbsoluteAxis`.

Questions:

    - Is `Sketch.Name` writable, so sketches can be addressed by a stable name?
    - Does `GetAbsoluteAxisData` work from Python, and does it distinguish
      XY / YZ / ZX supports?
    - Can the sketch's geometry be read back through `GeometricElements`, so
      key dimensions can be compared?
    - What can a `Pad` report -- in particular, can its height be read back?

Creates and deletes geometry in the active Part. Never saves.
"""

from typing import Any

from auto_3dx import Catia

SUPPORTS = ("PlaneXY", "PlaneYZ", "PlaneZX")
AXIS_DATA_SLOTS = 9
RECT_WIDTH = 30.0
RECT_HEIGHT = 20.0
PAD_HEIGHT = 15.0


def readable(com_object: Any) -> list[str]:
    """Returns the readable COM property names for an object's wrapper type."""
    names: set[str] = set()
    for base in type(com_object).__mro__:
        mapping = base.__dict__.get("_prop_map_get_")
        if isinstance(mapping, dict):
            names.update(map(str, mapping))
    return sorted(names)


def axis_data(sketch: Any) -> Any:
    """Attempts to read a sketch's absolute axis data."""
    try:
        return sketch.GetAbsoluteAxisData([0.0] * AXIS_DATA_SLOTS)
    except Exception as error:  # noqa: BLE001 - probing whether the call works
        return f"FAILED {type(error).__name__}: {error}"


def main() -> None:
    """Runs the probe against the active Part."""
    catia = Catia.attach()
    part = catia.active_part()
    raw = part.com_object
    body = raw.MainBody
    origin = raw.OriginElements
    selection = catia.active_editor().Selection

    created: list[Any] = []
    print("Part:", part.name)
    print("Sketches before:", body.Sketches.Count)

    try:
        print()
        print("--- axis data per support ---")
        for support in SUPPORTS:
            plane = getattr(origin, support)
            sketch = body.Sketches.Add(plane)
            created.append(sketch)
            wanted = f"AUTO3DX_PROBE_{support}"
            sketch.Name = wanted
            print(f"{support}:")
            print(f"  Name writable -> {sketch.Name!r} (wanted {wanted!r})")
            print(f"  axis data     -> {axis_data(sketch)}")

        print()
        print("--- geometry read-back ---")
        sketch = created[0]
        factory = sketch.OpenEdition()
        factory.CreateLine(0.0, 0.0, RECT_WIDTH, 0.0)
        factory.CreateLine(RECT_WIDTH, 0.0, RECT_WIDTH, RECT_HEIGHT)
        factory.CreateLine(RECT_WIDTH, RECT_HEIGHT, 0.0, RECT_HEIGHT)
        factory.CreateLine(0.0, RECT_HEIGHT, 0.0, 0.0)
        sketch.CloseEdition()
        part.update()

        elements = sketch.GeometricElements
        print("GeometricElements:", type(elements).__name__, "Count", elements.Count)
        for index in range(1, elements.Count + 1):
            element = elements.Item(index)
            print(f"  [{index}] {element.Name!r} ({type(element).__name__})")

        print()
        print("--- pad read-back ---")
        pad = raw.ShapeFactory.AddNewPad(sketch, PAD_HEIGHT)
        part.update()
        print("pad:", pad.Name, type(pad).__name__)
        print("pad readable:", readable(pad))
        for candidate in ("FirstLimit", "SecondLimit", "IsSymmetric", "Sketch"):
            try:
                value = getattr(pad, candidate)
                extra = ""
                if candidate.endswith("Limit"):
                    extra = f" Dimension={value.Dimension.Value}"
                print(f"  {candidate} -> {type(value).__name__}{extra}")
            except Exception as error:  # noqa: BLE001 - probing availability
                print(f"  {candidate} -> FAILED {type(error).__name__}")
        created.append(pad)
    finally:
        print()
        print("--- cleanup ---")
        for target in reversed(created):
            try:
                selection.Clear()
                selection.Add(target)
                selection.Delete()
            except Exception as error:  # noqa: BLE001 - cascade delete may have removed it
                print(f"  skip: {type(error).__name__}")
        selection.Clear()
        part.update()
        print("Sketches at end:", body.Sketches.Count)
        print("Shapes at end:", body.Shapes.Count)
        print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
