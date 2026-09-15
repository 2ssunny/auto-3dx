"""Probe whether Part Design features can be driven WITHOUT fragile BRep names.

`ShapeFactory` exposes 90 `AddNew*` methods but most take a face or an edge:

    AddNewEdgeFilletWithConstantRadius(iEdgeToFillet, iPropagMode, iRadius)
    AddNewChamfer(iObjectToChamfer, iPropagation, iMode, iOrientation, iLength1, iLength2OrAngle)
    AddNewMirror(iMirroringElement)
    AddNewShell(iFaceToRemove, iInternalThickness, iExternalThickness)
    AddNewThickness(iFaceToThicken, iOffset)

The usual way to name a face or edge is a BRep string like
``FSur:(Face:(Brp:(Pad.1;2);None:();Cf11:());...)``, which breaks whenever the
model is rebuilt. That fragility is why none of these are implemented yet.

This probe tests the alternative: pass a WHOLE addressable object instead.

    - `AddNewMirror` should accept an origin plane -- fully addressable.
    - Fillet/Chamfer in CATIA often accept the FEATURE itself plus a propagation
      mode, meaning "every edge of this pad", which needs no BRep name.
    - `Part.CreateReferenceFromObject` may wrap such an object as a `Reference`.

Whatever works here decides how much of the remaining 88 features is reachable.

Creates and removes geometry in the ACTIVE Part. Never saves.
"""

from typing import Any

from auto_3dx import Catia

PAD_NAME = "AUTO3DX_BASE_PAD"
FILLET_RADIUS = 2.0
CHAMFER_LENGTH = 1.5
CHAMFER_ANGLE = 45.0


def describe(com_object: Any) -> str:
    """Returns a COM wrapper's type name."""
    return type(com_object).__name__


def attempt(label: str, action: Any) -> Any:
    """Runs one experiment and reports the outcome without stopping the probe."""
    try:
        result = action()
    except Exception as error:  # noqa: BLE001 - probing the real failure mode
        message = str(error)
        print(f"  {label}: FAILED {type(error).__name__}: {message[:130]}")
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
    pads = part.part_design.pads
    if not pads:
        raise SystemExit("This probe needs an existing pad to work on.")
    pad = pads[0]
    print("pad:", pad.name, "height", pad.height)

    created: list[Any] = []

    try:
        print()
        print("--- 1. can a whole feature become a Reference? ---")
        reference = attempt(
            "CreateReferenceFromObject(pad)",
            lambda: raw.CreateReferenceFromObject(pad.com_object),
        )
        if reference is not None:
            for attribute in ("Name", "DisplayName"):
                try:
                    print(f"    {attribute} = {getattr(reference, attribute)!r}")
                except Exception as error:  # noqa: BLE001 - probing availability
                    print(f"    {attribute} -> FAILED {type(error).__name__}")

        print()
        print("--- 2. FindObjectByName ---")
        for name in (PAD_NAME, "PartBody", "xy plane"):
            attempt(f"FindObjectByName({name!r})", lambda n=name: raw.FindObjectByName(n))

        print()
        print("--- 3. AddNewMirror on an origin plane (no BRep name needed) ---")
        plane = raw.OriginElements.PlaneYZ
        mirror = attempt("AddNewMirror(PlaneYZ)", lambda: factory.AddNewMirror(plane))
        if mirror is not None:
            created.append(mirror)
            attempt("  Part.Update()", part.update)
            print("    shapes now:", body.Shapes.Count)

        print()
        print("--- 4. fillet ALL edges of a feature (propagation mode) ---")
        # iPropagMode: try the documented CatFilletEdgePropagation values.
        for mode in (1, 0, 2):
            target = reference if reference is not None else pad.com_object
            fillet = attempt(
                f"AddNewEdgeFilletWithConstantRadius(pad, mode={mode}, r={FILLET_RADIUS})",
                lambda m=mode, t=target: factory.AddNewEdgeFilletWithConstantRadius(
                    t, m, FILLET_RADIUS
                ),
            )
            if fillet is not None:
                created.append(fillet)
                attempt("  Part.Update()", part.update)
                print("    shapes now:", body.Shapes.Count)
                break

        print()
        print("--- 5. chamfer a whole feature ---")
        target = reference if reference is not None else pad.com_object
        chamfer = attempt(
            "AddNewChamfer(pad, 1, 0, 1, length, angle)",
            lambda: factory.AddNewChamfer(
                target, 1, 0, 1, CHAMFER_LENGTH, CHAMFER_ANGLE
            ),
        )
        if chamfer is not None:
            created.append(chamfer)
            attempt("  Part.Update()", part.update)

        print()
        print("--- 6. what does a BRep name look like here? ---")
        # Not creating anything -- just seeing whether a face can be named at all.
        attempt(
            "CreateReferenceFromBRepName('FSur:(Face:(Brp:(AUTO3DX_BASE_PAD;2))...)', pad)",
            lambda: raw.CreateReferenceFromBRepName(
                "FSur:(Face:(Brp:(AUTO3DX_BASE_PAD;2);None:();Cf11:());None:();Cf11:())",
                pad.com_object,
            ),
        )
    finally:
        print()
        print("--- cleanup ---")
        for target_object in reversed(created):
            try:
                selection.Clear()
                selection.Add(target_object)
                selection.Delete()
                print(f"  deleted {describe(target_object)}")
            except Exception as error:  # noqa: BLE001 - report, do not mask
                print(f"  could NOT delete {describe(target_object)}: {type(error).__name__}")
        selection.Clear()
        try:
            part.update()
        except Exception as error:  # noqa: BLE001 - report, do not mask
            print(f"  update after cleanup FAILED: {type(error).__name__}: {error}")
        print("  shapes:", body.Shapes.Count, "| sketches:", body.Sketches.Count)
        print("  pad height:", part.part_design.pads[0].height if part.part_design.pads else "-")
        print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
