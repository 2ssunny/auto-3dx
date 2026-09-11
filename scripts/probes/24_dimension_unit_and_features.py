"""Probe `Dimension.Unit` and the remaining sketch-based Part Design features.

Probe 23 showed that only `Length` and `Angle` come back as derived wrapper
types; every other magnitude (`Mass`, `Time`, `Volume`, ...) is a generic
`Dimension`. So `type(obj).__name__` cannot tell Mass from Time, and the
magnitude must come from somewhere else. `Dimension.Unit` is the candidate.

Also retries the three features that are still unimplemented:

    AddNewRib(iSketch, iCenterCurve)        profile swept along a path
    AddNewSlot(iSketch, iCenterCurve)       the cut version
    AddNewStiffener(iSketch)                failed update last time
    AddNewRectPattern(..., iDir1, iDir2)    failed update last time

Verified means created AND `Part.Update()` succeeded.

Creates and removes content in the ACTIVE Part. Never saves.
"""

from typing import Any

from auto_3dx import Catia
from auto_3dx.errors import PartUpdateError

PREFIX = "AUTO3DX_P24_"


def describe(com_object: Any) -> str:
    """Returns a COM wrapper's type name."""
    return type(com_object).__name__


def attempt(label: str, action: Any) -> Any:
    """Runs one experiment and reports the outcome without stopping the probe."""
    try:
        result = action()
    except Exception as error:  # noqa: BLE001 - probing the real failure mode
        print(f"  {label}: FAILED {type(error).__name__}: {str(error)[:90]}")
        return None
    print(f"  {label}: created -> {describe(result)}")
    return result


def main() -> None:
    """Runs the probe against the active Part."""
    catia = Catia.attach()
    part = catia.active_part()
    raw = part.com_object
    body = raw.MainBody
    factory = raw.ShapeFactory
    selection = catia.active_editor().Selection
    parameters = part.parameters.com_object

    print("Part:", part.name)
    print("shapes:", body.Shapes.Count, "| sketches:", body.Sketches.Count)

    made_parameters: list[str] = []
    created: list[Any] = []
    sketches: list[str] = []

    try:
        print()
        print("--- 1. Dimension.Unit -> magnitude and symbol ---")
        for magnitude in ("Length", "Angle", "Mass", "Volume"):
            name = f"{PREFIX}{magnitude.upper()}"
            made = raw.Parameters.CreateDimension(name, magnitude, 1.0)
            made_parameters.append(made.Name)
            line = f"  {magnitude:8s} kind={describe(made):10s}"
            try:
                unit = made.Unit
                line += f" Unit.Magnitude={unit.Magnitude!r} Unit.Symbol={unit.Symbol!r}"
                line += f" Unit.Name={unit.Name!r}"
            except Exception as error:  # noqa: BLE001 - probing availability
                line += f" Unit FAILED {type(error).__name__}"
            print(line)

        print()
        print("--- 2. AddNewRib / AddNewSlot (profile + path) ---")
        profile = part.sketches.create(f"{PREFIX}PROFILE", support="YZ")
        sketches.append(f"{PREFIX}PROFILE")
        with profile.edit() as editor:
            editor.rectangle(6.0, 6.0)
        path = part.sketches.create(f"{PREFIX}PATH", support="XY")
        sketches.append(f"{PREFIX}PATH")
        with path.edit() as editor:
            editor.line(0.0, 0.0, 50.0, 0.0)
        part.update()

        rib = attempt(
            "AddNewRib(profile, path)",
            lambda: factory.AddNewRib(profile.com_object, path.com_object),
        )
        if rib is not None:
            created.append(rib)
            try:
                part.update()
                print("    Part.Update(): OK -- VERIFIED")
            except PartUpdateError as error:
                print(f"    Part.Update(): FAILED {str(error)[:80]} -- NOT verified")

        print()
        print("--- 3. AddNewStiffener retry ---")
        stiff = part.sketches.create(f"{PREFIX}STIFF", support="YZ")
        sketches.append(f"{PREFIX}STIFF")
        with stiff.edit() as editor:
            # Open profile crossing the existing solid.
            editor.line(-30.0, 0.0, 30.0, 30.0)
        part.update()
        stiffener = attempt(
            "AddNewStiffener(sketch)",
            lambda: factory.AddNewStiffener(stiff.com_object),
        )
        if stiffener is not None:
            created.append(stiffener)
            try:
                part.update()
                print("    Part.Update(): OK -- VERIFIED")
            except PartUpdateError as error:
                print(f"    Part.Update(): FAILED {str(error)[:80]} -- NOT verified")

        print()
        print("--- 4. AddNewRectPattern: what works as a direction? ---")
        pads = part.part_design.pads
        if not pads:
            print("  no pad to pattern; skipping")
        else:
            pad_com = pads[0].com_object
            line_sketch = part.sketches.create(f"{PREFIX}DIR", support="XY")
            sketches.append(f"{PREFIX}DIR")
            with line_sketch.edit() as editor:
                direction_line = editor.line(0.0, 0.0, 10.0, 0.0)
            part.update()
            candidates = {
                "raw Line2D": direction_line,
                "Reference(Line2D)": raw.CreateReferenceFromObject(direction_line),
                "Reference(PlaneYZ)": raw.CreateReferenceFromObject(
                    raw.OriginElements.PlaneYZ
                ),
            }
            for label, direction in candidates.items():
                pattern = attempt(
                    f"AddNewRectPattern(dir={label})",
                    lambda d=direction: factory.AddNewRectPattern(
                        pad_com, 2, 1, 60.0, 60.0, 1, 1, d, d, False, False, 0.0
                    ),
                )
                if pattern is None:
                    continue
                created.append(pattern)
                try:
                    part.update()
                    print("    Part.Update(): OK -- VERIFIED")
                    break
                except PartUpdateError as error:
                    print(f"    Part.Update(): FAILED {str(error)[:70]} -- NOT verified")
    finally:
        print()
        print("--- cleanup ---")
        for target in reversed(created):
            try:
                selection.Clear()
                selection.Add(target)
                selection.Delete()
            except Exception as error:  # noqa: BLE001 - report, do not mask
                print(f"  delete {describe(target)}: {type(error).__name__}")
        selection.Clear()
        for name in sketches:
            try:
                part.sketches.remove(name)
            except Exception:  # noqa: BLE001 - may have cascaded away
                pass
        for name in made_parameters:
            try:
                raw.Parameters.Remove(name)
            except Exception:  # noqa: BLE001 - report, do not mask
                print(f"  remove parameter {name!r} failed")
        try:
            part.update()
        except Exception as error:  # noqa: BLE001 - report, do not mask
            print(f"  update after cleanup FAILED: {type(error).__name__}")
        print("  shapes:", body.Shapes.Count, "| sketches:", body.Sketches.Count)
        print("  parameters:", part.parameters.count, part.parameters.user_names())
        print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
