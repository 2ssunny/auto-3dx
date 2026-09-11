"""Probe `AddNewGroove` -- the revolved cut, twin of `AddNewShaft`.

Probe 18 established the shaft recipe: a profile offset from an axis, with the
axis assigned to `Sketch.CenterLine`. Groove takes the same single argument
(`AddNewGroove(iSketch)`), so the same recipe should apply.

It also established that a successful `AddNew*` call does NOT mean the feature
is valid -- Stiffener and RectPattern both returned an object whose
`Part.Update()` then failed. So this probe treats "created AND updated" as the
only success, and reports the two apart.

Creates and removes geometry in the ACTIVE Part. Never saves.
"""

from typing import Any

from auto_3dx import Catia
from auto_3dx.errors import PartUpdateError

GROOVE_SKETCH = "AUTO3DX_PROBE_GROOVE_SK"


def describe(com_object: Any) -> str:
    """Returns a COM wrapper's type name."""
    return type(com_object).__name__


def main() -> None:
    """Runs the probe against the active Part."""
    catia = Catia.attach()
    part = catia.active_part()
    raw = part.com_object
    body = raw.MainBody
    selection = catia.active_editor().Selection

    print("Part:", part.name)
    print("shapes:", body.Shapes.Count, "| sketches:", body.Sketches.Count)

    created: list[Any] = []
    try:
        sketch = part.sketches.create(GROOVE_SKETCH, support="ZX")
        with sketch.edit() as editor:
            # Small profile overlapping the existing pad, offset from the axis.
            editor.rectangle(4.0, 4.0, origin_x=10.0, origin_y=0.0)
            axis = editor.line(0.0, 0.0, 0.0, 20.0)
        sketch.com_object.CenterLine = axis
        part.update()
        print("sketch + centerline: OK")

        groove = raw.ShapeFactory.AddNewGroove(sketch.com_object)
        created.append(groove)
        print("AddNewGroove: created ->", describe(groove))
        for attribute in ("FirstAngle", "SecondAngle", "Sketch", "Name"):
            try:
                print(f"   {attribute} -> {describe(getattr(groove, attribute))}")
            except Exception:  # noqa: BLE001 - probing availability
                print(f"   {attribute} unavailable")

        try:
            part.update()
        except PartUpdateError as error:
            print("Part.Update(): FAILED ->", str(error)[:110])
            print("VERDICT: created but INVALID -- not verified.")
        else:
            print("Part.Update(): OK")
            print("shapes now:", body.Shapes.Count)
            print("VERDICT: created AND valid -- verified.")
    finally:
        print()
        print("--- cleanup ---")
        for target in reversed(created):
            try:
                selection.Clear()
                selection.Add(target)
                selection.Delete()
                print(f"  deleted {describe(target)}")
            except Exception as error:  # noqa: BLE001 - report, do not mask
                print(f"  could NOT delete {describe(target)}: {type(error).__name__}")
        selection.Clear()
        try:
            part.sketches.remove(GROOVE_SKETCH)
            print(f"  deleted sketch {GROOVE_SKETCH}")
        except Exception as error:  # noqa: BLE001 - may have cascaded away
            print(f"  sketch: {type(error).__name__}")
        try:
            part.update()
        except Exception as error:  # noqa: BLE001 - report, do not mask
            print(f"  update after cleanup FAILED: {type(error).__name__}")
        print("  shapes:", body.Shapes.Count, "| sketches:", body.Sketches.Count)
        print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
