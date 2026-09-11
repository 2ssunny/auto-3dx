"""Probe 20 follow-up: add constraints while the sketch is still in edition.

Probe 20 added constraints AFTER `CloseEdition()` and every call failed. It also
saw `Constraints.Count == 0` on a freshly drawn rectangle, even though a sketch
consumed by a pad does carry auto-created `Coincidence` constraints. Both point
at the same suspicion: constraints belong INSIDE the open-edition session.

This probe tries, in order:

    A. constraint on the raw Line2D, inside edition
    B. constraint on a Reference built from the raw Line2D, inside edition
    C. constraint on a Reference built from sketch.GeometricElements.Item(i)
    D. after edition closes, re-read Constraints.Count

Success means created AND `Part.Update()` succeeded.

Creates and removes geometry in the ACTIVE Part. Never saves.
"""

from typing import Any

from auto_3dx import Catia
from auto_3dx.errors import PartUpdateError

SKETCH_NAME = "AUTO3DX_PROBE_CST2"
CST_HORIZONTALITY = 10
CST_LENGTH = 5


def describe(com_object: Any) -> str:
    """Returns a COM wrapper's type name."""
    return type(com_object).__name__


def attempt(label: str, action: Any) -> Any:
    """Runs one experiment and reports the outcome without stopping the probe."""
    try:
        result = action()
    except Exception as error:  # noqa: BLE001 - probing the real failure mode
        print(f"  {label}: FAILED {type(error).__name__}: {str(error)[:100]}")
        return None
    print(f"  {label}: OK -> {describe(result)}")
    return result


def main() -> None:
    """Runs the probe against the active Part."""
    catia = Catia.attach()
    part = catia.active_part()
    raw = part.com_object
    body = raw.MainBody

    print("Part:", part.name)
    print("sketches before:", body.Sketches.Count)

    working: Any = None
    try:
        sketch = part.sketches.create(SKETCH_NAME, support="XY")
        com_sketch = sketch.com_object
        constraints = com_sketch.Constraints

        with sketch.edit() as editor:
            lines = editor.line(0.0, 0.0, 40.0, 0.0), editor.line(40.0, 0.0, 40.0, 25.0)
            bottom = lines[0]
            print("inside edition, Constraints.Count =", constraints.Count)

            print()
            print("--- A. raw Line2D, inside edition ---")
            working = attempt(
                "AddMonoEltCst(Horizontality, Line2D)",
                lambda: constraints.AddMonoEltCst(CST_HORIZONTALITY, bottom),
            )

            if working is None:
                print()
                print("--- B. Reference(Line2D), inside edition ---")
                reference = attempt(
                    "CreateReferenceFromObject(Line2D)",
                    lambda: raw.CreateReferenceFromObject(bottom),
                )
                if reference is not None:
                    working = attempt(
                        "AddMonoEltCst(Horizontality, Reference)",
                        lambda: constraints.AddMonoEltCst(CST_HORIZONTALITY, reference),
                    )

            if working is None:
                print()
                print("--- C. Reference(GeometricElements.Item(i)), inside edition ---")
                elements = com_sketch.GeometricElements
                print("  GeometricElements.Count =", elements.Count)
                for index in range(1, elements.Count + 1):
                    element = elements.Item(index)
                    if describe(element) != "Line2D":
                        continue
                    reference = raw.CreateReferenceFromObject(element)
                    working = attempt(
                        f"AddMonoEltCst(Horizontality, Ref(Item({index})={element.Name!r}))",
                        lambda r=reference: constraints.AddMonoEltCst(
                            CST_HORIZONTALITY, r
                        ),
                    )
                    if working is not None:
                        break

            if working is not None:
                print()
                print("--- dimensional constraint on the same element ---")
                length = attempt(
                    "AddMonoEltCst(Length, same element)",
                    lambda: constraints.AddMonoEltCst(CST_LENGTH, bottom),
                )
                if length is not None:
                    try:
                        dimension = length.Dimension
                        print(f"    Dimension {describe(dimension)} = {dimension.Value}")
                    except Exception as error:  # noqa: BLE001 - probing availability
                        print(f"    Dimension unavailable: {type(error).__name__}")

        print()
        print("--- D. after CloseEdition ---")
        print("  Constraints.Count        :", constraints.Count)
        print("  BrokenConstraintsCount   :", constraints.BrokenConstraintsCount)
        for index in range(1, constraints.Count + 1):
            item = constraints.Item(index)
            print(f"    [{index}] {item.Name!r} Type={item.Type} Status={item.Status}")

        try:
            part.update()
        except PartUpdateError as error:
            print("  Part.Update(): FAILED ->", str(error)[:100])
            print("  VERDICT: INVALID")
        else:
            print("  Part.Update(): OK")
            print("  VERDICT: verified" if working is not None else "  VERDICT: no constraint added")
    finally:
        print()
        print("--- cleanup ---")
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
