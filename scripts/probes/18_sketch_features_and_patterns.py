"""Probe the sketch-only solid features and the pattern features.

Probe 17 established that fillet/chamfer genuinely need an edge object, so they
stay out of reach. This probe covers what might still be reachable:

    AddNewShaft(iSketch)       revolve -- needs an axis, so the sketch's
                               CenterLine (writable) is the candidate
    AddNewGroove(iSketch)      revolved cut
    AddNewStiffener(iSketch)
    AddNewRectPattern(iShapeToCopy, nb1, nb2, step1, step2, pos1, pos2,
                      iDir1, iDir2, rev1, rev2, rotAngle)
    AddNewCircPattern(... iRotationCenter, iRotationAxis ...)

For the patterns the open question is what `iDir1`/`iDir2` accept. If an origin
plane or a sketch line works, patterns are reachable without BRep names.

Creates and removes geometry in the ACTIVE Part. Never saves.
"""

from typing import Any

from auto_3dx import Catia

SHAFT_SKETCH = "AUTO3DX_PROBE_SHAFT_SK"
STIFF_SKETCH = "AUTO3DX_PROBE_STIFF_SK"


def describe(com_object: Any) -> str:
    """Returns a COM wrapper's type name."""
    return type(com_object).__name__


def attempt(label: str, action: Any) -> Any:
    """Runs one experiment and reports the outcome without stopping the probe."""
    try:
        result = action()
    except Exception as error:  # noqa: BLE001 - probing the real failure mode
        print(f"  {label}: FAILED {type(error).__name__}: {str(error)[:120]}")
        return None
    print(f"  {label}: OK -> {describe(result)}")
    return result


def main() -> None:
    """Runs the probe against the active Part."""
    catia = Catia.attach()
    part = catia.active_part()
    raw = part.com_object
    body = raw.MainBody
    factory = raw.ShapeFactory
    selection = catia.active_editor().Selection

    print("Part:", part.name)
    print("shapes:", body.Shapes.Count, "| sketches:", body.Sketches.Count)

    created: list[Any] = []
    sketches_made: list[str] = []

    try:
        print()
        print("--- 1. AddNewShaft: profile plus a CenterLine axis ---")
        shaft_sketch = part.sketches.create(SHAFT_SKETCH, support="ZX")
        sketches_made.append(SHAFT_SKETCH)
        with shaft_sketch.edit() as editor:
            # A profile offset from the axis, so revolving it makes a ring.
            editor.rectangle(10.0, 6.0, origin_x=20.0, origin_y=0.0)
            axis = editor.line(0.0, 0.0, 0.0, 20.0)
        attempt(
            "set Sketch.CenterLine",
            lambda: setattr(shaft_sketch.com_object, "CenterLine", axis),
        )
        part.update()
        shaft = attempt(
            "AddNewShaft(sketch)", lambda: factory.AddNewShaft(shaft_sketch.com_object)
        )
        if shaft is not None:
            created.append(shaft)
            attempt("  Part.Update()", part.update)
            print("    shapes now:", body.Shapes.Count)
            for attribute in ("FirstAngle", "SecondAngle", "Sketch", "Name"):
                try:
                    print(f"    {attribute} -> {describe(getattr(shaft, attribute))}")
                except Exception:  # noqa: BLE001 - probing availability
                    print(f"    {attribute} unavailable")

        print()
        print("--- 2. AddNewStiffener ---")
        stiff_sketch = part.sketches.create(STIFF_SKETCH, support="YZ")
        sketches_made.append(STIFF_SKETCH)
        with stiff_sketch.edit() as editor:
            editor.line(0.0, 0.0, 30.0, 30.0)
        part.update()
        stiffener = attempt(
            "AddNewStiffener(sketch)",
            lambda: factory.AddNewStiffener(stiff_sketch.com_object),
        )
        if stiffener is not None:
            created.append(stiffener)
            attempt("  Part.Update()", part.update)

        print()
        print("--- 3. pattern directions: what does iDir accept? ---")
        pads = part.part_design.pads
        if not pads:
            print("  no pad to pattern; skipping")
        else:
            pad_com = pads[0].com_object
            candidates = {
                "PlaneYZ": raw.OriginElements.PlaneYZ,
                "Reference(PlaneYZ)": attempt(
                    "CreateReferenceFromObject(PlaneYZ)",
                    lambda: raw.CreateReferenceFromObject(raw.OriginElements.PlaneYZ),
                ),
            }
            for label, direction in candidates.items():
                if direction is None:
                    continue
                pattern = attempt(
                    f"AddNewRectPattern(dir1={label})",
                    lambda d=direction: factory.AddNewRectPattern(
                        pad_com, 2, 1, 30.0, 30.0, 1, 1, d, d, False, False, 0.0
                    ),
                )
                if pattern is not None:
                    created.append(pattern)
                    attempt("  Part.Update()", part.update)
                    print("    shapes now:", body.Shapes.Count)
                    break
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
        for name in sketches_made:
            try:
                part.sketches.remove(name)
                print(f"  deleted sketch {name}")
            except Exception as error:  # noqa: BLE001 - may have cascaded away
                print(f"  sketch {name}: {type(error).__name__}")
        try:
            part.update()
        except Exception as error:  # noqa: BLE001 - report, do not mask
            print(f"  update after cleanup FAILED: {type(error).__name__}: {error}")
        print("  shapes:", body.Shapes.Count, "| sketches:", body.Sketches.Count)
        print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
