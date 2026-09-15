"""Probe `AddNewSlot` and the pattern features -- the last untested candidates.

Probe 24 verified Rib (profile + path) and left these open:

    AddNewSlot(iSketch, iCenterCurve)   never tried -- Rib's cutting twin
    AddNewRectPattern(iShapeToCopy, nb1, nb2, step1, step2, pos1, pos2,
                      iDir1, iDir2, rev1, rev2, rotAngle)
    AddNewCircPattern(... iRotationCenter, iRotationAxis ...)

For the patterns the open question is what `iDir1`/`iDir2` actually accept. A
plane was rejected (update failed). This tries a sketch line, a Reference to
one, and an axis from `OriginElements`.

Verified means created AND `Part.Update()` succeeded -- `docs/conventions.md`
1.2.2.1 explains why creation alone is not enough.

Creates and removes content in the ACTIVE Part. Never saves.
"""

from typing import Any

from auto_3dx import Catia
from auto_3dx.errors import PartUpdateError

PREFIX = "AUTO3DX_P25_"


def describe(com_object: Any) -> str:
    """Returns a COM wrapper's type name."""
    return type(com_object).__name__


def verify(label: str, part: Any, made: Any) -> bool:
    """Reports whether a created feature also survives an update."""
    if made is None:
        return False
    try:
        part.update()
    except PartUpdateError as error:
        print(f"    {label}: created but Update FAILED ({str(error)[:60]}) -- NOT verified")
        return False
    print(f"    {label}: created AND Update OK -- VERIFIED")
    return True


def attempt(label: str, action: Any) -> Any:
    """Runs one experiment and reports the outcome without stopping the probe."""
    try:
        result = action()
    except Exception as error:  # noqa: BLE001 - probing the real failure mode
        print(f"  {label}: FAILED {type(error).__name__}: {str(error)[:80]}")
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

    print("Part:", part.name)
    print("shapes:", body.Shapes.Count, "| sketches:", body.Sketches.Count)

    created: list[Any] = []
    sketches: list[str] = []

    try:
        print()
        print("--- 1. AddNewSlot (profile + path), Rib's cutting twin ---")
        profile = part.sketches.create(f"{PREFIX}PROF", support="YZ")
        sketches.append(f"{PREFIX}PROF")
        with profile.edit() as editor:
            editor.rectangle(5.0, 5.0)
        path = part.sketches.create(f"{PREFIX}PATH", support="XY")
        sketches.append(f"{PREFIX}PATH")
        with path.edit() as editor:
            editor.line(0.0, 0.0, 50.0, 0.0)
        part.update()
        slot = attempt(
            "AddNewSlot(profile, path)",
            lambda: factory.AddNewSlot(profile.com_object, path.com_object),
        )
        if slot is not None:
            created.append(slot)
            verify("slot", part, slot)

        print()
        print("--- 2. AddNewRectPattern: direction candidates ---")
        pads = part.part_design.pads
        if not pads:
            print("  no pad to pattern; skipping")
        else:
            pad_com = pads[0].com_object
            direction_sketch = part.sketches.create(f"{PREFIX}DIR", support="XY")
            sketches.append(f"{PREFIX}DIR")
            with direction_sketch.edit() as editor:
                direction_line = editor.line(0.0, 0.0, 10.0, 0.0)
            part.update()

            candidates: dict[str, Any] = {"raw Line2D": direction_line}
            try:
                candidates["Reference(Line2D)"] = raw.CreateReferenceFromObject(
                    direction_line
                )
            except Exception:  # noqa: BLE001 - probing availability
                pass
            try:
                axis = raw.OriginElements.PlaneXY
                candidates["Reference(PlaneXY)"] = raw.CreateReferenceFromObject(axis)
            except Exception:  # noqa: BLE001 - probing availability
                pass

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
                if verify(f"pattern[{label}]", part, pattern):
                    break
                # Remove the broken pattern before trying the next candidate.
                try:
                    selection.Clear()
                    selection.Add(pattern)
                    selection.Delete()
                    selection.Clear()
                    created.remove(pattern)
                    part.update()
                except Exception as error:  # noqa: BLE001 - report, do not mask
                    print(f"    could not undo: {type(error).__name__}")
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
        try:
            part.update()
            print("  update after cleanup: OK")
        except Exception as error:  # noqa: BLE001 - report, do not mask
            print(f"  update after cleanup FAILED: {type(error).__name__}")
        print("  shapes:", body.Shapes.Count, "| sketches:", body.Sketches.Count)
        print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
