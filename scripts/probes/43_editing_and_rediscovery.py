"""Probe 43: editing existing features, rediscovering sketch elements, work_at, dependencies.

Establishes the live facts Phase 2 needs, on the disposable Part named by
`AUTO3DX_LIVE_PART` and nowhere else:

1. Which dimension of each existing Part Design feature can be read AND written through
   Automation, survive `Part.Update()`, and change the geometry?
2. Can a sketch element created in an earlier session be found again by its CATIA name
   and reused in a new constraint?
3. What does CATIA actually do when an existing feature is made the In-Work Object and a
   new feature is created: where does the new feature land in the tree?
4. How can the formulas that reference a user parameter be found, and what happens today
   when that parameter is removed anyway?

Everything this probe creates is named `AUTO3DX_P43_*` and is removed in `finally`.
Raw Automation is used deliberately here; that is what a probe is for. Nothing is saved.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python scripts/probes/43_editing_and_rediscovery.py [phase ...]
"""

import os
import sys
import traceback
from typing import Any

from auto_3dx import Auto3dxError, Catia

PREFIX = "AUTO3DX_P43_"
SKETCH, PAD = f"{PREFIX}SKETCH", f"{PREFIX}PAD"
SECOND_SKETCH, SECOND_PAD = f"{PREFIX}SKETCH2", f"{PREFIX}PAD2"
FILLET, CHAMFER = f"{PREFIX}FILLET", f"{PREFIX}CHAMFER"
HOLE, SHELL, THICKNESS = f"{PREFIX}HOLE", f"{PREFIX}SHELL", f"{PREFIX}THICKNESS"
ELEMENT_SKETCH = f"{PREFIX}ELEMENT_SKETCH"
PARAMETER, FORMULA = f"{PREFIX}L", f"{PREFIX}FORMULA"
SIDE, HEIGHT = 40.0, 30.0


def target_part() -> Any:
    """Attaches and returns the active Part if it is the one named, or exits."""
    target = os.environ.get("AUTO3DX_LIVE_PART", "").strip()
    if not target:
        sys.exit("Refusing to run: set AUTO3DX_LIVE_PART to the disposable test Part.")
    catia = Catia.attach()
    part = catia.active_part()
    caption = str(catia.com_object.ActiveWindow.Caption)
    if target not in (part.name, caption):
        sys.exit(
            f"Refusing to run: the active Part is {part.name!r} ({caption!r}), not {target!r}."
        )
    return part


def show(label: str, call: Any) -> Any:
    """Prints what one experiment returned, or how it failed."""
    try:
        result = call()
    except BaseException as error:  # a probe records failures instead of stopping
        print(f"  {label}: FAILED {type(error).__name__}: {str(error)[:150]}")
        return None
    print(f"  {label}: {result!r}")
    return result


def members(com_object: Any) -> "list[str]":
    """The public-looking members of a COM wrapper, for the inventory."""
    return [
        name
        for name in dir(com_object)
        if name[:1].isupper() and not name.startswith("CLSID")
    ]


def solid_edge(part: Any, feature_name: str) -> Any:
    """An edge of one feature; a body's edges include its sketches' wire edges."""
    edges = [
        edge
        for edge in part.topology.edges(body="PartBody")
        if edge.owner_feature_name == feature_name
    ]
    return edges[0]


def build_block(part: Any) -> None:
    """A plain block to hang the edge/face features on."""
    sketch = part.sketches.create(SKETCH, support="XY")
    with sketch.edit() as editor:
        editor.rectangle(SIDE, SIDE)
    part.part_design.create_pad(PAD, sketch, HEIGHT)
    part.update()


def dimension_inventory(part: Any, raw: Any) -> None:
    """1: which dimensions of which features can actually be read and written."""
    print("\n== 1. feature dimension inventory")

    def probe_feature(label: str, feature: Any, candidates: "tuple[str, ...]") -> None:
        com_object = feature.com_object
        print(f"\n-- {label}: {type(com_object).__name__}")
        print(f"   members: {members(com_object)}")
        for candidate in candidates:
            try:
                holder = getattr(com_object, candidate)
            except BaseException as error:
                print(f"   {candidate}: absent ({type(error).__name__})")
                continue
            kind = type(holder).__name__
            try:
                value = holder.Value
            except BaseException as error:
                print(f"   {candidate}: {kind}, no .Value ({type(error).__name__})")
                continue
            print(f"   {candidate}: {kind}, Value={value}")

    before = part.measurement.measure().volume_mm3
    print(f"  block volume: {before}")

    fillet = part.part_design.create_edge_fillet(FILLET, solid_edge(part, PAD), 4.0)
    part.update()
    probe_feature("ConstRadEdgeFillet", fillet, ("Radius", "Propagation", "EdgesToFillet"))
    filleted = part.measurement.measure().volume_mm3
    show("  write Radius = 8", lambda: setattr(fillet.com_object.Radius, "Value", 8.0))
    show("  update", lambda: part.update())
    show("  read back", lambda: fillet.com_object.Radius.Value)
    after = show("  volume", lambda: part.measurement.measure().volume_mm3)
    print(f"  volume changed: {filleted} -> {after}")
    show(
        "  fresh wrapper sees it",
        lambda: Catia.attach()
        .active_part()
        .part_design.get_edge_fillet(FILLET)
        .com_object.Radius.Value,
    )
    show("  remove fillet", lambda: part.part_design.remove_edge_fillet(FILLET))
    part.update()

    chamfer = part.part_design.create_chamfer(
        CHAMFER,
        solid_edge(part, PAD),
        length1=2.0,
        length2_or_angle=45.0,
        propagation=0,
        orientation=0,
    )
    part.update()
    probe_feature("Chamfer", chamfer, ("Length1", "Length2", "Angle", "Mode", "Propagation"))
    show("  write Length1 = 5", lambda: setattr(chamfer.com_object.Length1, "Value", 5.0))
    show("  write Angle = 30", lambda: setattr(chamfer.com_object.Angle, "Value", 30.0))
    show("  update", lambda: part.update())
    show("  read Length1", lambda: chamfer.com_object.Length1.Value)
    show("  read Angle", lambda: chamfer.com_object.Angle.Value)
    show("  volume", lambda: part.measurement.measure().volume_mm3)
    show("  remove chamfer", lambda: part.part_design.remove_chamfer(CHAMFER))
    part.update()

    faces = part.topology.faces(body="PartBody")
    hole = part.part_design.create_hole(HOLE, faces[0], 5.0)
    part.update()
    probe_feature("Hole", hole, ("Diameter", "Depth", "BottomLimit", "HoleStyle", "Type"))
    show("  write Diameter = 12", lambda: setattr(hole.com_object.Diameter, "Value", 12.0))
    show("  update", lambda: part.update())
    show("  read Diameter", lambda: hole.com_object.Diameter.Value)
    show("  volume", lambda: part.measurement.measure().volume_mm3)
    show("  write Depth = 9", lambda: setattr(hole.com_object.Depth, "Value", 9.0))
    show("  update", lambda: part.update())
    show("  read Depth", lambda: hole.com_object.Depth.Value)
    show("  volume", lambda: part.measurement.measure().volume_mm3)
    show("  remove hole", lambda: part.part_design.remove_hole(HOLE))
    part.update()

    faces = part.topology.faces(body="PartBody")
    shell = part.part_design.create_shell(SHELL, faces[0], 2.0, 0.0)
    part.update()
    probe_feature("Shell", shell, ("InternalThickness", "ExternalThickness", "FacesToRemove"))
    show(
        "  write InternalThickness = 4",
        lambda: setattr(shell.com_object.InternalThickness, "Value", 4.0),
    )
    show("  update", lambda: part.update())
    show("  read InternalThickness", lambda: shell.com_object.InternalThickness.Value)
    show("  volume", lambda: part.measurement.measure().volume_mm3)
    show("  remove shell", lambda: part.part_design.remove_shell(SHELL))
    part.update()

    faces = part.topology.faces(body="PartBody")
    thickness = part.part_design.create_thickness(THICKNESS, faces[0], 3.0)
    part.update()
    probe_feature("Thickness", thickness, ("Thickness", "Value", "FacesToThicken"))
    show("  volume", lambda: part.measurement.measure().volume_mm3)
    show("  remove thickness", lambda: part.part_design.remove_thickness(THICKNESS))
    part.update()

    print("\n-- Pad (already exposed) and RectPattern for completeness")
    pad = part.part_design.get_pad(PAD)
    print(f"   Pad members: {members(pad.com_object)}")


def dimension_inventory_second_pass(part: Any, raw: Any) -> None:
    """1b: the members the first pass showed but did not exercise."""
    print("\n== 1b. second pass: Hole.BottomLimit, Thickness.Offset, Length2, External")

    faces = part.topology.faces(body="PartBody")
    hole = part.part_design.create_hole(HOLE, faces[0], 5.0)
    part.update()
    limit = hole.com_object.BottomLimit
    print(f"  BottomLimit members: {members(limit)}")
    show("  BottomLimit.Dimension.Value", lambda: limit.Dimension.Value)
    show("  BottomLimit.LimitMode", lambda: limit.LimitMode)
    volume = show("  volume", lambda: part.measurement.measure().volume_mm3)
    show("  write BottomLimit.Dimension = 12", lambda: setattr(limit.Dimension, "Value", 12.0))
    show("  update", lambda: part.update())
    show("  read back", lambda: hole.com_object.BottomLimit.Dimension.Value)
    after = show("  volume", lambda: part.measurement.measure().volume_mm3)
    print(f"  volume changed: {volume} -> {after}")
    show(
        "  fresh wrapper sees it",
        lambda: Catia.attach()
        .active_part()
        .part_design.get_hole(HOLE)
        .com_object.BottomLimit.Dimension.Value,
    )
    show("  remove hole", lambda: part.part_design.remove_hole(HOLE))
    part.update()

    faces = part.topology.faces(body="PartBody")
    thickness = part.part_design.create_thickness(THICKNESS, faces[0], 3.0)
    part.update()
    offset = thickness.com_object.Offset
    print(f"  Thickness.Offset type: {type(offset).__name__}")
    show("  Offset.Value", lambda: offset.Value)
    volume = show("  volume", lambda: part.measurement.measure().volume_mm3)
    show("  write Offset = 6", lambda: setattr(offset, "Value", 6.0))
    show("  update", lambda: part.update())
    show("  read back", lambda: thickness.com_object.Offset.Value)
    after = show("  volume", lambda: part.measurement.measure().volume_mm3)
    print(f"  volume changed: {volume} -> {after}")
    show(
        "  fresh wrapper sees it",
        lambda: Catia.attach()
        .active_part()
        .part_design.get_thickness(THICKNESS)
        .com_object.Offset.Value,
    )
    show("  remove thickness", lambda: part.part_design.remove_thickness(THICKNESS))
    part.update()

    chamfer = part.part_design.create_chamfer(
        CHAMFER,
        solid_edge(part, PAD),
        length1=2.0,
        length2_or_angle=45.0,
        propagation=0,
        orientation=0,
    )
    part.update()
    show("  Length2 before", lambda: chamfer.com_object.Length2.Value)
    show("  write Length2 = 3", lambda: setattr(chamfer.com_object.Length2, "Value", 3.0))
    show("  update", lambda: part.update())
    show("  read Length2", lambda: chamfer.com_object.Length2.Value)
    show("  volume", lambda: part.measurement.measure().volume_mm3)
    show("  remove chamfer", lambda: part.part_design.remove_chamfer(CHAMFER))
    part.update()

    faces = part.topology.faces(body="PartBody")
    shell = part.part_design.create_shell(SHELL, faces[0], 2.0, 0.0)
    part.update()
    volume = show("  volume", lambda: part.measurement.measure().volume_mm3)
    show(
        "  write ExternalThickness = 1.5",
        lambda: setattr(shell.com_object.ExternalThickness, "Value", 1.5),
    )
    show("  update", lambda: part.update())
    show("  read ExternalThickness", lambda: shell.com_object.ExternalThickness.Value)
    after = show("  volume", lambda: part.measurement.measure().volume_mm3)
    print(f"  volume changed: {volume} -> {after}")
    show("  remove shell", lambda: part.part_design.remove_shell(SHELL))
    part.update()

    print("  -- Shaft/Groove angle (already exposed) and RectPattern")
    print("   RectPattern check skipped: creation needs a feature to pattern")


def sketch_elements(part: Any, raw: Any) -> None:
    """2: rediscovering sketch geometry by name and reusing it."""
    print("\n== 2. sketch element rediscovery")
    sketch = part.sketches.create(ELEMENT_SKETCH, support="XY")
    with sketch.edit() as editor:
        editor.line(-90.0, -90.0, -50.0, -90.0)
        editor.line(-90.0, -80.0, -50.0, -80.0)
        editor.circle(-70.0, -60.0, 5.0)
    part.update()
    print("  names after creation:", part.sketches.get(ELEMENT_SKETCH).element_names())

    # A fresh wrapper: nothing from the editing session above is reused.
    fresh = Catia.attach().active_part().sketches.get(ELEMENT_SKETCH)
    elements = fresh.com_object.GeometricElements
    print(f"  GeometricElements.Count = {elements.Count}")
    for index in range(1, int(elements.Count) + 1):
        item = elements.Item(index)
        print(f"   {index}: {type(item).__name__} {item.Name!r}")
    first_name = str(elements.Item(1).Name)
    show("  Item(name) works", lambda: type(elements.Item(first_name)).__name__)
    show("  Item(missing name)", lambda: elements.Item("NoSuchElement.99").Name)

    line = elements.Item(first_name)
    print(f"  line members: {members(line)}")
    show("  GetCoordinates", lambda: _coordinates(line))
    circle = [
        elements.Item(index)
        for index in range(1, int(elements.Count) + 1)
        if type(elements.Item(index)).__name__ == "Circle2D"
    ]
    if circle:
        print(f"  circle members: {members(circle[0])}")
        show("  Radius", lambda: circle[0].Radius)
        show("  CenterCoordinates", lambda: _coordinates(circle[0]))

    print("  -- reuse in a NEW constraint, inside edit()")
    second = [
        elements.Item(index)
        for index in range(1, int(elements.Count) + 1)
        if type(elements.Item(index)).__name__ == "Line2D"
    ]
    with fresh.edit() as editor:
        show(
            "  parallel(rediscovered, rediscovered)",
            lambda: editor.parallel(second[0], second[1]).name,
        )
    show("  update", lambda: part.update())
    show("  constraint count", lambda: fresh.constraints.count)
    show(
        "  element access WITHOUT edit(): read name",
        lambda: elements.Item(first_name).Name,
    )


def _coordinates(element: Any) -> Any:
    """Tries the verified coordinate readers of a 2D element."""
    for member in ("GetCoordinates", "GetCenter"):
        reader = getattr(element, member, None)
        if reader is None:
            continue
        try:
            return member, reader()
        except BaseException as error:
            return member, f"<{type(error).__name__}>"
    return None


def work_at(part: Any, raw: Any) -> None:
    """3: what CATIA does when an existing feature is made the In-Work Object."""
    print("\n== 3. feature as In-Work Object")
    part.part_design.create_edge_fillet(FILLET, solid_edge(part, PAD), 4.0)
    part.update()
    print("  tree before:", [f.name for f in part.inspect.features()])
    print("  IWO before:", part.inspect.in_work_object())

    pad = part.part_design.get_pad(PAD)
    show("  set InWorkObject = the pad", lambda: setattr(raw, "InWorkObject", pad.com_object))
    print("  IWO inside:", part.inspect.in_work_object())

    sketch = part.sketches.create(SECOND_SKETCH, support="XY")
    with sketch.edit() as editor:
        editor.rectangle(10.0, 10.0, origin_x=120.0)
    show("  create a pad while the first pad is IWO", lambda: part.part_design.create_pad(
        SECOND_PAD, sketch, 5.0
    ).name)
    print("  IWO after creating:", part.inspect.in_work_object())
    show("  update", lambda: part.update())
    print("  tree after:", [f.name for f in part.inspect.features()])
    print("  body sketches:", part.bodies.main.sketch_names)
    show("  is_up_to_date", lambda: part.is_up_to_date())
    show("  volume", lambda: part.measurement.measure().volume_mm3)

    print("  -- restore and clean up this phase")
    raw.InWorkObject = raw.MainBody
    show("  remove the second pad", lambda: part.part_design.remove_pad(SECOND_PAD))
    show("  remove the fillet", lambda: part.part_design.remove_edge_fillet(FILLET))
    part.update()
    print("  tree restored:", [f.name for f in part.inspect.features()])


def dependencies(part: Any, raw: Any) -> None:
    """4: finding the formulas that reference a parameter, and what removal does today."""
    print("\n== 4. parameter dependencies")
    part.parameters.create_length(PARAMETER, 12.0)
    pad = part.part_design.get_pad(PAD)
    driven = pad.depth_parameter()
    source = part.formulas.relation_name(part.parameters.get(PARAMETER))
    print(f"  target={part.formulas.relation_name(driven)!r} source={source!r}")
    formula = part.formulas.create(FORMULA, driven, f"{source} * 2")
    part.update()
    print(f"  formula body: {formula.body!r}, inputs: {formula.input_count}")
    print(f"  pad height now: {pad.height}")

    relations = raw.Relations
    print(f"  Relations members: {members(relations)}")
    raw_formula = formula.com_object
    print(f"  Formula members: {members(raw_formula)}")
    for member in ("NbInParameters", "GetInParameter", "InParameters", "Parameters"):
        show(f"  Formula.{member}", lambda m=member: getattr(raw_formula, m))
    for index in range(1, 4):
        show(f"  GetInParameter({index})", lambda i=index: raw_formula.GetInParameter(i).Name)
    show("  OutputParameter", lambda: raw_formula.OutputParameter.Name)

    user = part.parameters.get(PARAMETER)
    print(f"  Parameter members: {members(user.com_object)}")
    show("  Parameter.OptionalRelation", lambda: user.com_object.OptionalRelation)
    show(
        "  OptionalRelation of the DRIVEN parameter",
        lambda: pad.depth_parameter().com_object.OptionalRelation.Name,
    )

    print("  -- what removing a referenced parameter does today (the unsafe case)")
    show("  remove the parameter", lambda: part.parameters.remove(PARAMETER))
    show("  formula still listed", lambda: part.formulas.names())
    show("  formula body now", lambda: part.formulas.get(FORMULA).body)
    show("  formula inputs now", lambda: part.formulas.get(FORMULA).input_count)
    show("  part up to date", lambda: part.is_up_to_date())
    show("  update", lambda: part.update())
    show("  pad height now", lambda: pad.height)


def cleanup(part: Any, raw: Any) -> None:
    """Removes only what this probe created."""
    print("\n== cleanup")
    try:
        raw.InWorkObject = raw.MainBody
    except BaseException:
        traceback.print_exc()
    for step in (
        lambda: part.formulas.remove(FORMULA),
        lambda: part.parameters.remove(PARAMETER),
        lambda: part.part_design.remove_edge_fillet(FILLET),
        lambda: part.part_design.remove_chamfer(CHAMFER),
        lambda: part.part_design.remove_hole(HOLE),
        lambda: part.part_design.remove_shell(SHELL),
        lambda: part.part_design.remove_thickness(THICKNESS),
        lambda: part.part_design.remove_pad(SECOND_PAD),
        lambda: part.sketches.remove(SECOND_SKETCH),
        lambda: part.part_design.remove_pad(PAD),
        lambda: part.sketches.remove(SKETCH),
        lambda: part.sketches.remove(ELEMENT_SKETCH),
    ):
        try:
            step()
        except Auto3dxError as error:
            print(f"  skipped: {type(error).__name__}: {str(error)[:80]}")
        except BaseException:
            traceback.print_exc()
    try:
        part.update()
    except Auto3dxError as error:
        print(f"  update after cleanup failed: {error}")
    print(part.inspect.summary().render())


PHASES = ("dims", "dims2", "elements", "workat", "deps")


def main() -> None:
    wanted = sys.argv[1:] or list(PHASES)
    unknown = [phase for phase in wanted if phase not in PHASES]
    if unknown:
        sys.exit(f"unknown phase(s) {unknown}; choose from {list(PHASES)}")
    part = target_part()
    raw = part.com_object
    selection = Catia.attach().active_editor().Selection
    held = [selection.Item(i).Value for i in range(1, int(selection.Count) + 1)]
    previous_in_work = raw.InWorkObject
    print(part.inspect.summary().render())
    try:
        build_block(part)
        for phase in wanted:
            if phase == "dims":
                dimension_inventory(part, raw)
            elif phase == "dims2":
                dimension_inventory_second_pass(part, raw)
            elif phase == "elements":
                sketch_elements(part, raw)
            elif phase == "workat":
                work_at(part, raw)
            else:
                dependencies(part, raw)
    finally:
        try:
            raw.InWorkObject = previous_in_work
        except BaseException:
            traceback.print_exc()
        cleanup(part, raw)
        try:
            selection.Clear()
            for value in held:
                selection.Add(value)
            print(f"selection restored: {int(selection.Count)} item(s)")
        except BaseException:
            traceback.print_exc()


if __name__ == "__main__":
    main()
