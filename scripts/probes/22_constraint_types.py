"""Probe the constraint types needed for a fully constrained sketch.

Probe 21 established the rule: constraints only work INSIDE the open-edition
session, and they take the raw `Line2D`/`Circle2D`, not a `Reference`.

This probe sweeps the types a real parametric sketch needs, on a rectangle plus
a circle, and records which are accepted and what CATIA normalises them into
(`Horizontality` came back as `Parallelism`, `Type=8`).

Success means created AND `Part.Update()` succeeded.

Creates and removes geometry in the ACTIVE Part. Never saves.
"""

from typing import Any

from auto_3dx import Catia
from auto_3dx.errors import PartUpdateError

SKETCH_NAME = "AUTO3DX_PROBE_CST3"

MONO = {
    "Horizontality": 10,
    "Verticality": 13,
    "Length": 5,
    "Radius": 14,
}
BI = {
    "Perpendicularity": 11,
    "Parallelism": 8,
    "Distance": 1,
    "On": 2,
    "Concentricity": 3,
    "Tangency": 4,
}


def main() -> None:
    """Runs the probe against the active Part."""
    catia = Catia.attach()
    part = catia.active_part()
    raw = part.com_object
    body = raw.MainBody
    results: list[tuple[str, str, str]] = []

    print("Part:", part.name)
    try:
        sketch = part.sketches.create(SKETCH_NAME, support="XY")
        constraints = sketch.com_object.Constraints

        with sketch.edit() as editor:
            bottom = editor.line(0.0, 0.0, 40.0, 0.0)
            right = editor.line(40.0, 0.0, 40.0, 25.0)
            top = editor.line(40.0, 25.0, 0.0, 25.0)
            left = editor.line(0.0, 25.0, 0.0, 0.0)
            circle = editor.circle(20.0, 12.0, 4.0)

            targets = {
                "Horizontality": bottom,
                "Verticality": right,
                "Length": top,
                "Radius": circle,
            }
            for label, code in MONO.items():
                element = targets[label]
                try:
                    made = constraints.AddMonoEltCst(code, element)
                except Exception as error:  # noqa: BLE001 - probing failure mode
                    results.append((label, "FAILED", type(error).__name__))
                    continue
                results.append(
                    (label, "OK", f"{made.Name!r} Type={made.Type} Status={made.Status}")
                )

            pairs = {
                "Perpendicularity": (bottom, right),
                "Parallelism": (bottom, top),
                "Distance": (bottom, top),
                "On": (left, bottom),
                "Concentricity": (circle, circle),
                "Tangency": (circle, bottom),
            }
            for label, code in BI.items():
                first, second = pairs[label]
                try:
                    made = constraints.AddBiEltCst(code, first, second)
                except Exception as error:  # noqa: BLE001 - probing failure mode
                    results.append((label, "FAILED", type(error).__name__))
                    continue
                results.append(
                    (label, "OK", f"{made.Name!r} Type={made.Type} Status={made.Status}")
                )

        print()
        print(f"{'type':20s} {'result':8s} detail")
        for label, status, detail in results:
            print(f"{label:20s} {status:8s} {detail}")

        print()
        print("Constraints.Count        :", constraints.Count)
        print("BrokenConstraintsCount   :", constraints.BrokenConstraintsCount)
        print("UnUpdatedConstraintsCount:", constraints.UnUpdatedConstraintsCount)

        print()
        print("--- dimensional constraints: write the Dimension ---")
        for index in range(1, constraints.Count + 1):
            item = constraints.Item(index)
            try:
                dimension = item.Dimension
            except Exception:  # noqa: BLE001 - non-dimensional constraints have none
                continue
            before = dimension.Value
            try:
                dimension.Value = before + 5.0
                print(f"  {item.Name!r}: {before} -> {item.Dimension.Value}  (writable)")
                dimension.Value = before
            except Exception as error:  # noqa: BLE001 - probing availability
                print(f"  {item.Name!r}: write FAILED {type(error).__name__}")

        try:
            part.update()
        except PartUpdateError as error:
            print()
            print("Part.Update(): FAILED ->", str(error)[:110])
            print("VERDICT: INVALID")
        else:
            print()
            print("Part.Update(): OK -- VERDICT: verified")
            print("Broken after update:", constraints.BrokenConstraintsCount)
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
