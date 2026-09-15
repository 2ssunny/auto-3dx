"""Probe sketch name uniqueness and COM object identity.

A code review raised two questions the library's `ensure` logic depends on:

    - Can two sketches in one body carry the SAME name? If so, name-based
      lookup is ambiguous and `ensure` can reuse the wrong profile.
    - Can two COM wrappers be compared for object identity? `ensure_pad`
      currently compares `pad.Sketch.name` with the requested sketch's name;
      real identity would be stronger.

Also confirms the collection protocols the review flagged as unverified:
`Sketches.Count/Item`, `Shapes.Count/Item`, `GeometricElements.Count/Item`.

Creates and deletes geometry in the active Part. Never saves.
"""

from typing import Any

from auto_3dx import Catia

NAME = "AUTO3DX_DUP_SKETCH"
RECT_WIDTH = 20.0
RECT_HEIGHT = 10.0
PAD_HEIGHT = 5.0


def identity_report(first: Any, second: Any) -> str:
    """Describes every identity signal available for two COM wrappers."""
    lines = [
        f"  a is b            : {first is second}",
        f"  a == b            : {first == second}",
    ]
    for attribute in ("_oleobj_",):
        try:
            left = getattr(first, attribute)
            right = getattr(second, attribute)
            lines.append(f"  {attribute} ==        : {left == right}")
            lines.append(f"  {attribute} identity  : {left is right}")
        except Exception as error:  # noqa: BLE001 - probing availability
            lines.append(f"  {attribute}: FAILED {type(error).__name__}")
    return "\n".join(lines)


def main() -> None:
    """Runs the probe against the active Part."""
    catia = Catia.attach()
    part = catia.active_part()
    raw = part.com_object
    body = raw.MainBody
    selection = catia.active_editor().Selection
    plane = raw.OriginElements.PlaneXY

    created: list[Any] = []
    print("Part:", part.name)
    print("Sketches before:", body.Sketches.Count, "Shapes before:", body.Shapes.Count)

    try:
        first = body.Sketches.Add(plane)
        created.append(first)
        first.Name = NAME
        print(f"first sketch  : {first.Name!r}")

        second = body.Sketches.Add(plane)
        created.append(second)
        print(f"second sketch : {second.Name!r} (default)")

        print()
        print("--- can a duplicate name be assigned? ---")
        try:
            second.Name = NAME
            print(f"  ACCEPTED -> second.Name = {second.Name!r}")
            print(f"  first.Name still         = {first.Name!r}")
            names = [body.Sketches.Item(i).Name for i in range(1, body.Sketches.Count + 1)]
            print(f"  all names                = {names}")
            print(f"  Item({NAME!r}) resolves to -> {body.Sketches.Item(NAME).Name!r}")
        except Exception as error:  # noqa: BLE001 - probing the real failure mode
            print(f"  REJECTED: {type(error).__name__}: {str(error)[:110]}")

        print()
        print("--- COM identity: same sketch fetched twice ---")
        print(identity_report(body.Sketches.Item(1), body.Sketches.Item(1)))

        print()
        print("--- COM identity: two different sketches ---")
        print(identity_report(body.Sketches.Item(1), body.Sketches.Item(2)))

        print()
        print("--- pad.Sketch identity vs the sketch it was built from ---")
        factory = first.OpenEdition()
        factory.CreateLine(0.0, 0.0, RECT_WIDTH, 0.0)
        factory.CreateLine(RECT_WIDTH, 0.0, RECT_WIDTH, RECT_HEIGHT)
        factory.CreateLine(RECT_WIDTH, RECT_HEIGHT, 0.0, RECT_HEIGHT)
        factory.CreateLine(0.0, RECT_HEIGHT, 0.0, 0.0)
        first.CloseEdition()
        part.update()
        pad = raw.ShapeFactory.AddNewPad(first, PAD_HEIGHT)
        created.append(pad)
        part.update()
        print(identity_report(pad.Sketch, first))

        print()
        print("--- collection protocols the review called unverified ---")
        elements = first.GeometricElements
        print(f"  GeometricElements.Count = {elements.Count}")
        print(f"  GeometricElements.Item(1).Name = {elements.Item(1).Name!r}")
        print(f"  Sketches.Count = {body.Sketches.Count}, Item(1) ok = {body.Sketches.Item(1) is not None}")
        print(f"  Shapes.Count   = {body.Shapes.Count}, Item(1).Name = {body.Shapes.Item(1).Name!r}")
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
        print("Sketches at end:", body.Sketches.Count, "Shapes at end:", body.Shapes.Count)
        print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
