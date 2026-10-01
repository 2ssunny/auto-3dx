"""Probe the Multi-sections Solid (Part Design Loft) creation and read-back path.

A raw experiment already built a solid wing between two NACA sections with:

    loft = part.ShapeFactory.AddNewLoft()
    loft.HybridShape.AddSectionToLoft(root_reference, 1, None)
    loft.HybridShape.AddSectionToLoft(tip_reference, 1, None)
    part.Update()

Signatures from the generated type libraries:

    ShapeFactory.AddNewLoft() -> Loft           (D8431606-E4B5-11D1-A5D3-00A0C95752ED)
    Loft: Name (r/w), HybridShape -> HybridShape, Parent, GetItem
    HybridShapeLoft (87EE735C-DF70-11D1-8556-0060941979CE):
        AddSectionToLoft(iCrv, iOri, iPoint)
        GetSectionFromLoft(iRank, oCrv, oOri, oPoint)
        RemoveSection(iSection)
        GetNbOfGuides()      -- there is no section-count member

Before this becomes public API, the smallest deterministic case answers what the
wrapper depends on: the live kind name, which section argument works (a Reference or
the raw Sketch), how the In-Work Object moves, whether the loft is found again by
enumerating MainBody.Shapes, whether its sections can be read back and counted, and
whether deleting it cascades to its section sketches.

Setup and cleanup go through the public API; only the Loft calls are raw. A feature
whose update fails stays in the tree and breaks every later update, so the loft is
deleted in `finally` whatever happens. Never saves.

The first run of this probe (2026-09-17) ran against whichever Part was active, which was
not a test Part, and its cleanup removed the whole `auto_3dx_Planes` set -- deleting a
plane another workflow's sketch sat on. It now works only on the Part named by
`AUTO3DX_LIVE_PART`, and removes only the one plane it created.
"""

import os
import sys
from typing import Any

from auto_3dx import Catia
from auto_3dx.errors import Auto3dxError

PART_ENV_VAR = "AUTO3DX_LIVE_PART"
PREFIX = "AUTO3DX_P40_"
ROOT_SKETCH = f"{PREFIX}ROOT"
TIP_PLANE = f"{PREFIX}TIP_PLANE"
TIP_SKETCH = f"{PREFIX}TIP"
LOFT_NAME = f"{PREFIX}LOFT"
ROOT_WIDTH, ROOT_HEIGHT = 40.0, 20.0
TIP_WIDTH, TIP_HEIGHT = 30.0, 15.0
TIP_OFFSET = 30.0
SECTION_ORIENTATION = 1
MAX_RANK_TRIED = 3
_FAILED = object()


def attempt(label: str, call: Any) -> Any:
    """Runs one call and prints its result or its failure."""
    try:
        value = call()
    except Exception as error:  # noqa: BLE001 - probing
        print(f"  {label}: FAILED {type(error).__name__}: {str(error)[:140]}")
        return _FAILED
    print(f"  {label}: {value!r}"[:230])
    return value


def describe(value: Any) -> str:
    """Names a COM value without assuming what it is."""
    if value is None:
        return "None"
    name = getattr(value, "Name", None)
    display = getattr(value, "DisplayName", None)
    return f"{type(value).__name__}(Name={name!r}, DisplayName={display!r})"


def in_work(raw_part: Any) -> str:
    """Reads the In-Work Object for the log."""
    obj = raw_part.InWorkObject
    return describe(obj)


def main() -> None:
    target = os.environ.get(PART_ENV_VAR, "").strip()
    if not target:
        sys.exit(f"Refusing to run: set {PART_ENV_VAR} to the name of a disposable test Part.")
    catia = Catia.attach()
    part = catia.part_named(target)
    if catia.active_part().name != target:
        sys.exit(f"Refusing to run: activate {target!r} first; selection deletes act there.")
    raw_part = part.com_object
    selection = catia.active_editor().Selection

    before = part.inspect.summary()
    print("baseline features :", [(f.name, f.kind) for f in before.features])
    print("baseline sketches :", list(before.sketches))
    print("baseline topology :", before.topology)
    print("baseline volume   :", round(part.measurement.measure().volume_mm3, 3))
    print("baseline in-work  :", before.in_work_object)

    loft = None
    try:
        root = part.sketches.create(ROOT_SKETCH, support="XY")
        with root.edit() as editor:
            editor.rectangle(ROOT_WIDTH, ROOT_HEIGHT)
        part.update()
        plane = part.planes.create_offset(TIP_PLANE, "XY", TIP_OFFSET)
        part.update()
        tip = part.sketches.create(TIP_SKETCH, support=plane)
        with tip.edit() as editor:
            editor.rectangle(TIP_WIDTH, TIP_HEIGHT)
        part.update()
        print("\nsetup up_to_date  :", part.is_up_to_date())

        print("\n=== 1. AddNewLoft ===")
        print("  in-work before    :", in_work(raw_part))
        loft = attempt("ShapeFactory.AddNewLoft()", lambda: raw_part.ShapeFactory.AddNewLoft())
        if loft is _FAILED:
            loft = None
            return
        print("  type(loft)        :", type(loft).__name__)
        print("  loft.Name         :", loft.Name)
        print("  in-work after     :", in_work(raw_part))
        hybrid = attempt("loft.HybridShape", lambda: loft.HybridShape)
        print("  type(HybridShape) :", type(hybrid).__name__)

        print("\n=== 2. AddSectionToLoft with a Reference ===")
        root_ref = attempt(
            "CreateReferenceFromObject(root)",
            lambda: raw_part.CreateReferenceFromObject(root.com_object),
        )
        tip_ref = attempt(
            "CreateReferenceFromObject(tip)",
            lambda: raw_part.CreateReferenceFromObject(tip.com_object),
        )
        attempt(
            "AddSectionToLoft(root_ref, 1, None)",
            lambda: hybrid.AddSectionToLoft(root_ref, SECTION_ORIENTATION, None),
        )
        attempt(
            "AddSectionToLoft(tip_ref, 1, None)",
            lambda: hybrid.AddSectionToLoft(tip_ref, SECTION_ORIENTATION, None),
        )
        print("  in-work after sections:", in_work(raw_part))

        print("\n=== 3. Rename and update ===")
        attempt("loft.Name = LOFT_NAME", lambda: setattr(loft, "Name", LOFT_NAME))
        print("  loft.Name         :", loft.Name)
        updated = attempt("part.update()", part.update)
        print("  is_up_to_date     :", part.is_up_to_date())
        if updated is _FAILED:
            print("  update failed; skipping the solid checks")
        else:
            after = part.inspect.summary()
            print("  features          :", [(f.name, f.kind, f.supported) for f in after.features])
            print("  topology          :", after.topology)
            print("  in-work           :", after.in_work_object)
            mass = part.measurement.measure()
            print("  volume_mm3        :", round(mass.volume_mm3, 3))
            print("  area_mm2          :", round(mass.area_mm2, 3))

        print("\n=== 4. Rediscovery through MainBody.Shapes ===")
        shapes = raw_part.MainBody.Shapes
        found = None
        for index in range(1, int(shapes.Count) + 1):
            item = shapes.Item(index)
            print(f"  Shapes.Item({index}): {type(item).__name__} {item.Name!r}")
            if item.Name == LOFT_NAME:
                found = item
        print("  found == loft     :", found is not None and bool(found == loft))

        print("\n=== 5. Section read-back on the rediscovered loft ===")
        if found is not None:
            found_hybrid = attempt("found.HybridShape", lambda: found.HybridShape)
            for rank in range(0, MAX_RANK_TRIED + 1):
                result = attempt(
                    f"GetSectionFromLoft({rank})",
                    lambda rank=rank: found_hybrid.GetSectionFromLoft(rank),
                )
                if result is _FAILED or result is None:
                    continue
                parts = result if isinstance(result, tuple) else (result,)
                for position, value in enumerate(parts):
                    print(f"    out[{position}]: {describe(value)}")
                    if hasattr(value, "Name"):
                        print(f"      == root sketch: {bool(value == root.com_object)}"
                              f"  == tip sketch: {bool(value == tip.com_object)}")
    finally:
        print("\n=== 6. Delete the loft, then see what it took with it ===")
        if loft is not None:
            try:
                selection.Clear()
                selection.Add(loft)
                selection.Delete()
                selection.Clear()
                print("  loft deleted through Selection")
            except Exception as error:  # noqa: BLE001 - probing
                print(f"  loft delete FAILED {type(error).__name__}: {error}")
        print("  sketches now      :", list(part.inspect.sketches()))
        # Only what this probe made: never the whole geometrical set, which can hold
        # planes other work depends on.
        for cleanup in (
            lambda: part.sketches.remove(TIP_SKETCH),
            lambda: part.sketches.remove(ROOT_SKETCH),
            lambda: part.planes.remove(part.planes.get(TIP_PLANE)),
        ):
            try:
                cleanup()
            except Auto3dxError as error:
                print("  cleanup note:", type(error).__name__, str(error)[:120])
        part.update()

    final = part.inspect.summary()
    print("\nfinal features    :", [(f.name, f.kind) for f in final.features])
    print("final sketches    :", list(final.sketches))
    print("final sets        :", [s.name for s in final.geometrical_sets])
    print("final topology    :", final.topology)
    print("final in-work     :", final.in_work_object)
    print("final volume      :", round(part.measurement.measure().volume_mm3, 3))
    print("final up_to_date  :", final.up_to_date)
    print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
