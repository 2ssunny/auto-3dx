"""Probe `AddNewPocket` and `Relations.CreateFormula`.

Type library signatures (B428_Cloud):

    ShapeFactory.AddNewPocket(iSketch, iHeight)          -> Pocket
    Relations.CreateFormula(iName, iComment,
                            iOutputParameter, iFormulaBody)  -> Formula
    Relations.Count / Item(i) / Remove(i) / GetItem(name)
    Parameters.GetNameToUseInRelation(iObject)           -> str
    Formula: Value, Activated, Comment, NbInParameters, NbOutParameters
             Activate / Deactivate / Modify / Rename / GetInParameter / GetOutParameter

Questions:
    - Does `AddNewPocket` mirror `AddNewPad` exactly (sketch + depth)?
    - What wrapper type comes back, and does it expose `FirstLimit` too?
    - What does `GetNameToUseInRelation` return for a user parameter and for a
      feature-internal one?
    - Does `CreateFormula` drive a pad's height from a user parameter, and does
      the height actually change after `Part.Update()`?

Creates and removes geometry and a formula in the ACTIVE Part. Never saves.
"""

from typing import Any

from auto_3dx import Catia

POCKET_SKETCH = "AUTO3DX_PROBE_POCKET_SKETCH"
POCKET_NAME = "AUTO3DX_PROBE_POCKET"
POCKET_DEPTH = 5.0
FORMULA_NAME = "AUTO3DX_PROBE_FORMULA"
DRIVER_PARAMETER = "AUTO3DX_THICKNESS"


def describe(com_object: Any) -> str:
    """Returns a COM wrapper's type name."""
    return type(com_object).__name__


def readable(com_object: Any) -> list[str]:
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
    selection = catia.active_editor().Selection
    parameters = part.parameters

    print("Part:", part.name)
    print("shapes before:", body.Shapes.Count, "| sketches before:", body.Sketches.Count)
    print("user parameters:", parameters.user_names())

    created: list[Any] = []
    formula_made = False

    try:
        print()
        print("--- AddNewPocket ---")
        sketch = part.sketches.create(POCKET_SKETCH, support="XY")
        created.append(sketch.com_object)
        with sketch.edit() as editor:
            editor.rectangle(20.0, 15.0, origin_x=5.0, origin_y=5.0)
        part.update()

        pocket = raw.ShapeFactory.AddNewPocket(sketch.com_object, POCKET_DEPTH)
        created.append(pocket)
        pocket.Name = POCKET_NAME
        part.update()
        print("  pocket:", describe(pocket), pocket.Name)
        print("  readable:", readable(pocket))
        try:
            print("  FirstLimit.Dimension.Value =", pocket.FirstLimit.Dimension.Value)
        except Exception as error:  # noqa: BLE001 - probing availability
            print(f"  FirstLimit FAILED: {type(error).__name__}")
        print("  shapes now:", body.Shapes.Count)

        print()
        print("--- GetNameToUseInRelation ---")
        raw_parameters = parameters.com_object
        driver = parameters.get(DRIVER_PARAMETER)
        print("  user parameter    ->", repr(
            raw_parameters.GetNameToUseInRelation(driver.com_object)
        ))
        pad = part.part_design.get_pad("AUTO3DX_BASE_PAD")
        target = pad.com_object.FirstLimit.Dimension
        print("  pad FirstLimit    ->", repr(
            raw_parameters.GetNameToUseInRelation(target)
        ))

        print()
        print("--- Relations.CreateFormula ---")
        relations = raw.Relations
        print("  relations:", describe(relations), "Count", relations.Count)
        driver_name = raw_parameters.GetNameToUseInRelation(driver.com_object)
        body_text = f"{driver_name} * 2"
        print(f"  body: {body_text!r}")
        print(f"  height before: {pad.height}")

        formula = relations.CreateFormula(
            FORMULA_NAME, "auto-3dx probe", target, body_text
        )
        formula_made = True
        part.update()
        print("  formula:", describe(formula), formula.Name)
        print("  readable:", readable(formula))
        for attribute in ("Value", "Activated", "Comment", "NbInParameters"):
            try:
                print(f"    {attribute} = {getattr(formula, attribute)!r}")
            except Exception:  # noqa: BLE001 - probing availability
                print(f"    {attribute} unavailable")
        print(f"  height after : {pad.height}   (expect {driver.value} * 2)")

        print()
        print("--- driving the formula ---")
        driver.set(20.0)
        part.update()
        print(f"  driver = {driver.value} -> pad height = {pad.height}")
        driver.set(12.0)
        part.update()
        print(f"  driver = {driver.value} -> pad height = {pad.height}")
    finally:
        print()
        print("--- cleanup ---")
        if formula_made:
            try:
                relations = raw.Relations
                for index in range(relations.Count, 0, -1):
                    if relations.Item(index).Name == FORMULA_NAME:
                        relations.Remove(index)
                        print("  removed formula")
            except Exception as error:  # noqa: BLE001 - report, do not mask
                print(f"  formula cleanup FAILED: {type(error).__name__}: {error}")
        for target_object in reversed(created):
            try:
                selection.Clear()
                selection.Add(target_object)
                selection.Delete()
            except Exception as error:  # noqa: BLE001 - cascade delete may have removed it
                print(f"  skip: {type(error).__name__}")
        selection.Clear()
        try:
            part.update()
        except Exception as error:  # noqa: BLE001 - report, do not mask
            print(f"  update after cleanup FAILED: {type(error).__name__}")
        print("  shapes:", body.Shapes.Count, "| sketches:", body.Sketches.Count)
        print("  relations:", raw.Relations.Count)
        print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
