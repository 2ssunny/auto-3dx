"""Probe sketch constraints -- the missing half of parametric modelling.

Type library (B428_Cloud):

    Constraints.AddMonoEltCst(iCstType: int, iElem)                 -> Constraint
    Constraints.AddBiEltCst(iCstType: int, iFirst, iSecond)         -> Constraint
    Constraints.Count / Item(i) / Remove(i) [1-based]
    Constraints.BrokenConstraintsCount / UnUpdatedConstraintsCount
    Constraint: Dimension, Status, Type, Mode, Name, ...

Constraint type values found in the type library:

    Reference 0   Distance 1   On 2   Concentricity 3   Tangency 4
    Length 5      Angle 6      Parallelism 8            AxisParallelism 9
    Horizontality 10           Perpendicularity 11      Verticality 13
    Radius 14     Symmetry 15  MidPoint 16

Open questions:
    - Does `iElem` want the raw `Line2D`, or a `Reference` from
      `Part.CreateReferenceFromObject`?
    - Does a dimensional constraint (Length) expose a writable `Dimension`?
      That is what makes a constraint drivable by a formula.
    - Does `BrokenConstraintsCount` give a usable health signal?

Success here means created AND `Part.Update()` succeeded -- see
`docs/conventions.md` 1.2.2.1 for why creation alone is not enough.

Creates and removes geometry in the ACTIVE Part. Never saves.
"""

from typing import Any

from auto_3dx import Catia
from auto_3dx.errors import PartUpdateError

SKETCH_NAME = "AUTO3DX_PROBE_CST"
CST_LENGTH = 5
CST_HORIZONTALITY = 10
CST_VERTICALITY = 13
CST_PERPENDICULARITY = 11


def describe(com_object: Any) -> str:
    """Returns a COM wrapper's type name."""
    return type(com_object).__name__


def attempt(label: str, action: Any) -> Any:
    """Runs one experiment and reports the outcome without stopping the probe."""
    try:
        result = action()
    except Exception as error:  # noqa: BLE001 - probing the real failure mode
        print(f"  {label}: FAILED {type(error).__name__}: {str(error)[:110]}")
        return None
    print(f"  {label}: OK -> {describe(result)}")
    return result


def main() -> None:
    """Runs the probe against the active Part."""
    catia = Catia.attach()
    part = catia.active_part()
    raw = part.com_object
    body = raw.MainBody
    selection = catia.active_editor().Selection

    print("Part:", part.name)
    print("sketches before:", body.Sketches.Count)

    try:
        sketch = part.sketches.create(SKETCH_NAME, support="XY")
        with sketch.edit() as editor:
            lines = editor.rectangle(40.0, 25.0)
        part.update()
        bottom, right, top, left = lines
        print("rectangle lines:", [describe(line) for line in lines])

        constraints = sketch.com_object.Constraints
        print("Constraints:", describe(constraints), "Count", constraints.Count)
        print("  auto-created by CATIA:", constraints.Count)

        print()
        print("--- 1. raw Line2D vs Reference ---")
        raw_cst = attempt(
            "AddMonoEltCst(Horizontality, raw Line2D)",
            lambda: constraints.AddMonoEltCst(CST_HORIZONTALITY, bottom),
        )
        reference = attempt(
            "CreateReferenceFromObject(Line2D)",
            lambda: raw.CreateReferenceFromObject(bottom),
        )
        ref_cst = None
        if raw_cst is None and reference is not None:
            ref_cst = attempt(
                "AddMonoEltCst(Horizontality, Reference)",
                lambda: constraints.AddMonoEltCst(CST_HORIZONTALITY, reference),
            )

        working = raw_cst if raw_cst is not None else ref_cst
        if working is None:
            print("  neither form accepted; constraints stay out of reach")
        else:
            print("  usable form:", "raw Line2D" if raw_cst is not None else "Reference")
            for attribute in ("Name", "Type", "Status", "Mode"):
                try:
                    print(f"    {attribute} = {getattr(working, attribute)!r}")
                except Exception:  # noqa: BLE001 - probing availability
                    print(f"    {attribute} unavailable")
            try:
                print(f"    Dimension -> {describe(working.Dimension)}")
            except Exception as error:  # noqa: BLE001 - expected for non-dimensional
                print(f"    Dimension -> none ({type(error).__name__})")

        print()
        print("--- 2. dimensional constraint (Length) ---")
        element = bottom if raw_cst is not None else reference
        length_cst = attempt(
            "AddMonoEltCst(Length, element)",
            lambda: constraints.AddMonoEltCst(CST_LENGTH, element),
        )
        if length_cst is not None:
            try:
                dimension = length_cst.Dimension
                print(f"    Dimension -> {describe(dimension)} Value={dimension.Value}")
                dimension.Value = 55.0
                part.update()
                print(f"    after set 55 -> {length_cst.Dimension.Value}")
                print("    THIS is what a formula can drive.")
            except Exception as error:  # noqa: BLE001 - probing availability
                print(f"    Dimension write FAILED: {type(error).__name__}: {error}")

        print()
        print("--- 3. two-element constraint ---")
        second = right if raw_cst is not None else raw.CreateReferenceFromObject(right)
        attempt(
            "AddBiEltCst(Perpendicularity, bottom, right)",
            lambda: constraints.AddBiEltCst(CST_PERPENDICULARITY, element, second),
        )

        print()
        print("--- 4. health signals ---")
        print("  Constraints.Count          :", constraints.Count)
        for attribute in ("BrokenConstraintsCount", "UnUpdatedConstraintsCount"):
            try:
                print(f"  {attribute}: {getattr(constraints, attribute)}")
            except Exception as error:  # noqa: BLE001 - probing availability
                print(f"  {attribute}: FAILED {type(error).__name__}")

        try:
            part.update()
        except PartUpdateError as error:
            print("  Part.Update(): FAILED ->", str(error)[:110])
            print("  VERDICT: created but INVALID")
        else:
            print("  Part.Update(): OK")
            print("  VERDICT: created AND valid -- verified.")
    finally:
        print()
        print("--- cleanup ---")
        selection.Clear()
        try:
            part.sketches.remove(SKETCH_NAME)
            print(f"  removed sketch {SKETCH_NAME}")
        except Exception as error:  # noqa: BLE001 - report, do not mask
            print(f"  sketch removal: {type(error).__name__}")
        try:
            part.update()
        except Exception as error:  # noqa: BLE001 - report, do not mask
            print(f"  update after cleanup FAILED: {type(error).__name__}")
        print("  sketches:", body.Sketches.Count, "| shapes:", body.Shapes.Count)
        print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
