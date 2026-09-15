"""Probe what direction a `Reference(plane)` actually gives `AddNewRectPattern`.

Probe 25 found that `AddNewRectPattern` only survives `Part.Update()` when
`iDir1`/`iDir2` are a `Reference` built from an origin plane -- a raw `Line2D`
and a `Reference` to one both failed. But "it updates" is not the same as
"the copies went where the caller asked". Patterns are useless, and dangerous,
if the direction is a guess.

This probe reads the pattern back through `RectPatternParameters` (the pattern
exposes its own parameters) and compares the three origin planes, so the mapping
from plane to axis can be recorded instead of assumed.

Creates and removes content in the ACTIVE Part. Never saves.
"""

from typing import Any

from auto_3dx import Catia
from auto_3dx.errors import PartUpdateError

PREFIX = "AUTO3DX_P26_"
STEP = 60.0


def describe(com_object: Any) -> str:
    """Returns a COM wrapper's type name."""
    return type(com_object).__name__


def readable(com_object: Any) -> "list[str]":
    """Returns readable COM property names for a wrapper type."""
    names: set[str] = set()
    for base in type(com_object).__mro__:
        mapping = base.__dict__.get("_prop_map_get_")
        if isinstance(mapping, dict):
            names.update(map(str, mapping))
    return sorted(names)


def main() -> None:
    """Runs the probe against the active Part."""
    catia = Catia.attach()
    part = catia.active_part()
    raw = part.com_object
    body = raw.MainBody
    factory = raw.ShapeFactory
    selection = catia.active_editor().Selection

    pads = part.part_design.pads
    if not pads:
        raise SystemExit("This probe needs an existing pad to pattern.")
    pad_com = pads[0].com_object

    print("Part:", part.name)
    print("shapes:", body.Shapes.Count)

    for support in ("PlaneXY", "PlaneYZ", "PlaneZX"):
        print()
        print(f"--- direction = Reference({support}) ---")
        created: Any = None
        try:
            plane = getattr(raw.OriginElements, support)
            reference = raw.CreateReferenceFromObject(plane)
            created = factory.AddNewRectPattern(
                pad_com, 2, 1, STEP, STEP, 1, 1, reference, reference, False, False, 0.0
            )
            print("  created:", describe(created))
            try:
                part.update()
            except PartUpdateError as error:
                print(f"  Update FAILED ({str(error)[:60]}) -- NOT verified")
                continue
            print("  Update OK. shapes now:", body.Shapes.Count)
            print("  readable:", readable(created))
            for attribute in (
                "RectPatternParameters",
                "FirstDirectionRepartition",
                "SecondDirectionRepartition",
                "FirstDirectionReference",
                "Name",
            ):
                try:
                    value = getattr(created, attribute)
                    extra = ""
                    if hasattr(value, "Name"):
                        extra = f" Name={value.Name!r}"
                    print(f"    {attribute} -> {describe(value)}{extra}")
                except Exception as error:  # noqa: BLE001 - probing availability
                    print(f"    {attribute} -> unavailable ({type(error).__name__})")
            # The pattern's own spacing/count parameters show what CATIA used.
            for name in part.parameters.names():
                if created.Name in name:
                    parameter = part.parameters.get(name)
                    print(f"    param {parameter.short_name!r} = {parameter.value!r}")
        except Exception as error:  # noqa: BLE001 - probing the real failure mode
            print(f"  FAILED {type(error).__name__}: {str(error)[:90]}")
        finally:
            if created is not None:
                try:
                    selection.Clear()
                    selection.Add(created)
                    selection.Delete()
                    selection.Clear()
                    part.update()
                except Exception as error:  # noqa: BLE001 - report, do not mask
                    print(f"  cleanup failed: {type(error).__name__}")

    print()
    print("final shapes:", body.Shapes.Count, "| sketches:", body.Sketches.Count)
    print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
