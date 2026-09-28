"""Probe 44: circular patterns, multi-body booleans, constraint deletion, feature activity.

Establishes the live facts Phase 3 needs, on the disposable Part named by
`AUTO3DX_LIVE_PART` and nowhere else:

1. What does `ShapeFactory.AddNewCircPattern` actually take, which axis does an origin
   plane reference produce, and which of its parameters can be edited afterwards?
2. Which boolean operations work, what do they do to the tool body, and what happens when
   the boolean feature is deleted?
3. Can a constraint be removed safely, and does it need an edition session?
4. Which feature kinds expose a usable `Activity`, and what does suppressing an upstream
   feature do to a downstream one?

Everything this probe creates is named `AUTO3DX_P44_*` and is removed in `finally`.
Raw Automation is used deliberately here; that is what a probe is for. Nothing is saved.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python scripts/probes/44_pattern_boolean_activity.py [phase ...]
"""

import inspect
import os
import sys
import traceback
from typing import Any

from auto_3dx import Auto3dxError, Catia

PREFIX = "AUTO3DX_P44_"
DISC_SKETCH, DISC_PAD = f"{PREFIX}DISC_SKETCH", f"{PREFIX}DISC_PAD"
HOLE_SKETCH, HOLE_POCKET = f"{PREFIX}HOLE_SKETCH", f"{PREFIX}HOLE_POCKET"
TOOL_BODY, TOOL_SKETCH, TOOL_PAD = f"{PREFIX}TOOL", f"{PREFIX}TOOL_SKETCH", f"{PREFIX}TOOL_PAD"
CON_SKETCH = f"{PREFIX}CON_SKETCH"
TOP_PLANE = f"{PREFIX}TOP_PLANE"
FILLET = f"{PREFIX}FILLET"
DISC_SIDE, DISC_HEIGHT = 120.0, 10.0
HOLE_RADIUS, HOLE_DEPTH, HOLE_X = 6.0, 20.0, 40.0
TOOL_RADIUS, TOOL_HEIGHT = 15.0, 40.0


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
    """The public-looking members of a COM wrapper."""
    return [
        name
        for name in dir(com_object)
        if name[:1].isupper() and not name.startswith("CLSID")
    ]


def signature_of(factory: Any, method: str) -> str:
    """Reads the generated pywin32 wrapper so the real argument names are visible."""
    try:
        return inspect.getsource(getattr(type(factory), method))
    except BaseException as error:
        return f"<unavailable: {type(error).__name__}: {error}>"


def build_disc(part: Any) -> None:
    """A flange-like disc with one bolt hole, the seed for the circular pattern."""
    sketch = part.sketches.create(DISC_SKETCH, support="XY")
    with sketch.edit() as editor:
        editor.circle(0.0, 0.0, DISC_SIDE / 2)
    part.part_design.create_pad(DISC_PAD, sketch, DISC_HEIGHT)
    part.update()
    # The pocket must cut DOWN into the pad, so its sketch sits on a plane above the disc.
    plane = part.planes.create_offset(TOP_PLANE, "XY", DISC_HEIGHT)
    part.update()
    hole_sketch = part.sketches.create(HOLE_SKETCH, support=plane)
    with hole_sketch.edit() as editor:
        editor.circle(HOLE_X, 0.0, HOLE_RADIUS)
    part.part_design.create_pocket(HOLE_POCKET, hole_sketch, HOLE_DEPTH)
    part.update()
    print(f"  seed: disc + one hole, volume {part.measurement.measure().volume_mm3}")


def circular_pattern(part: Any, raw: Any) -> None:
    """1: the circular-pattern call, its axis, and which parameters can be edited."""
    print("\n== 1. circular pattern")
    factory = raw.ShapeFactory
    print("  AddNewCircPattern source:")
    print(signature_of(factory, "AddNewCircPattern"))

    volume_one_hole = part.measurement.measure().volume_mm3
    removed_one = DISC_HEIGHT * 3.141592653589793 * HOLE_RADIUS**2
    print(f"  volume with one hole: {volume_one_hole} (one hole removes ~{removed_one:.3f})")

    origin = raw.OriginElements
    # iShapeToCopy, radial copies, angular copies, radial step, angular step,
    # position along radial, position along angular, rotation centre, rotation axis,
    # reversed axis, rotation angle, radius aligned.
    for label, centre, axis in (
        ("PlaneXY / PlaneXY", origin.PlaneXY, origin.PlaneXY),
        ("PlaneYZ / PlaneYZ", origin.PlaneYZ, origin.PlaneYZ),
        ("PlaneZX / PlaneZX", origin.PlaneZX, origin.PlaneZX),
    ):
        print(f"\n-- rotation centre and axis from {label}")
        pocket = part.part_design.get_pocket(HOLE_POCKET)
        pattern = show(
            "   AddNewCircPattern(pocket, 1, 6, 1.0, 60.0, 1, 1, centre, axis, False, 0.0, True)",
            lambda c=centre, a=axis: factory.AddNewCircPattern(
                pocket.com_object, 1, 6, 1.0, 60.0, 1, 1, c, a, False, 0.0, True
            ),
        )
        if pattern is None:
            continue
        show("   rename", lambda p=pattern: setattr(p, "Name", f"{PREFIX}CIRC"))
        try:
            part.update()
            rebuilt = True
        except Auto3dxError as error:
            rebuilt = False
            print(f"   update FAILED: {str(error)[:90]}")
        print(f"   update succeeded: {rebuilt}")
        volume = show("   volume", lambda: part.measurement.measure().volume_mm3)
        if volume is not None:
            print(f"   removed since one hole: {volume_one_hole - volume:.3f} "
                  f"(five more holes would be {5 * removed_one:.3f})")
        print(f"   type: {type(pattern).__name__}")
        print(f"   members: {members(pattern)}")
        show("   topology", lambda: part.inspect.topology())

        if not rebuilt:
            show("   delete the failed pattern", lambda p=pattern: _delete(part, p, "pattern"))
            show("   update after delete", lambda: part.update())
            continue
        if label != "PlaneXY / PlaneXY":
            # Only the Z-axis case is carried further; the others exist to show the mapping.
            show("   delete", lambda p=pattern: _delete(part, p, "circular pattern"))
            show("   update", lambda: part.update())
            continue

        for member in ("AngularRepartition", "RadialRepartition", "RotationCenter",
                       "ItemToCopy", "RotationAxis"):
            kind = show(f"   {member}", lambda m=member, p=pattern: type(getattr(p, m)).__name__)
            if kind is not None and "Repartition" in member:
                repartition = getattr(pattern, member)
                print(f"     members: {members(repartition)}")
                show("     InstancesCount.Value", lambda r=repartition: r.InstancesCount.Value)
                show("     AngularSpacing.Value", lambda r=repartition: r.AngularSpacing.Value)

        print("   -- editing the instance count and the spacing")
        repartition = pattern.AngularRepartition
        show("   write InstancesCount = 8",
             lambda r=repartition: setattr(r.InstancesCount, "Value", 8))
        show("   update", lambda: part.update())
        show("   read back", lambda p=pattern: p.AngularRepartition.InstancesCount.Value)
        eight = show("   volume", lambda: part.measurement.measure().volume_mm3)
        if eight is not None:
            print(f"   removed since one hole: {volume_one_hole - eight:.3f} "
                  f"(seven more holes would be {7 * removed_one:.3f})")
        show("   write AngularSpacing = 45",
             lambda r=repartition: setattr(r.AngularSpacing, "Value", 45.0))
        show("   update", lambda: part.update())
        show("   read spacing", lambda p=pattern: p.AngularRepartition.AngularSpacing.Value)
        show("   volume", lambda: part.measurement.measure().volume_mm3)

        print("   -- rediscovery")
        shapes = raw.MainBody.Shapes
        print("   shapes:", [(shapes.Item(i).Name, type(shapes.Item(i)).__name__)
                             for i in range(1, int(shapes.Count) + 1)])
        fresh = Catia.attach().active_part()
        print("   fresh inspect:", [(f.name, f.kind) for f in fresh.inspect.features()])

        print("   -- removing the pattern")
        show("   delete", lambda p=pattern: _delete(part, p, "circular pattern"))
        show("   update", lambda: part.update())
        show("   volume", lambda: part.measurement.measure().volume_mm3)
        print("   shapes after:", [shapes.Item(i).Name
                                   for i in range(1, int(shapes.Count) + 1)])


def _delete(part: Any, com_object: Any, description: str) -> None:
    """Deletes one raw object through the SDK's own selection helper."""
    from auto_3dx.geometry.deletion import delete_via_selection

    delete_via_selection(
        Catia.attach().active_editor().Selection,
        com_object,
        description,
        part.com_object,
    )


def _build_tool_body(part: Any, name: str, x: float = 0.0) -> Any:
    """A cylindrical tool body for a boolean experiment."""
    body = part.bodies.create(name)
    with part.work_in(body):
        sketch = part.sketches.create(f"{name}_SKETCH", support="XY")
        with sketch.edit() as editor:
            editor.circle(x, 0.0, TOOL_RADIUS)
        part.part_design.create_pad(f"{name}_PAD", sketch, TOOL_HEIGHT)
    body.update()
    return body


def booleans(part: Any, raw: Any) -> None:
    """2: which boolean operations work, and what they do to the tool body."""
    print("\n== 2. boolean operations")
    factory = raw.ShapeFactory
    for method in ("AddNewRemove", "AddNewAdd", "AddNewAssemble", "AddNewIntersect",
                   "AddNewTrim", "AddNewUnion"):
        print(f"  -- {method} available: {hasattr(factory, method)}")
    print("  AddNewRemove source:")
    print(signature_of(factory, "AddNewRemove"))

    for method in ("AddNewRemove", "AddNewAdd", "AddNewIntersect", "AddNewAssemble"):
        if not hasattr(factory, method):
            print(f"\n-- {method}: absent in this release")
            continue
        name = f"{PREFIX}{method[6:].upper()}_TOOL"
        print(f"\n-- {method} with tool body {name}")
        try:
            tool = _build_tool_body(part, name)
        except Auto3dxError as error:
            print(f"   could not build the tool body: {error}")
            continue
        show("   target volume before",
             lambda: part.measurement.measure(part.bodies.main).volume_mm3)
        show("   tool volume", lambda: part.measurement.measure(tool).volume_mm3)
        show("   InBooleanOperation before", lambda: tool.com_object.InBooleanOperation)
        raw.InWorkObject = raw.MainBody
        result = show(f"   {method}(tool)",
                      lambda m=method: getattr(factory, m)(tool.com_object))
        if result is None:
            continue
        print(f"   result type: {type(result).__name__}, members: {members(result)}")
        show("   result name", lambda: result.Name)
        show("   update", lambda: part.update())
        show("   target volume after",
             lambda: part.measurement.measure(part.bodies.main).volume_mm3)
        show("   InBooleanOperation after", lambda: tool.com_object.InBooleanOperation)
        show("   bodies now", lambda: part.bodies.names())
        show("   main body features", lambda: [f.name for f in part.bodies.main.features])
        for member in ("AffectedBody", "ToolBody", "Body", "BodyToAdd", "BodyToRemove"):
            show(f"   result.{member}", lambda m=member: getattr(result, m).Name)

        print("   -- deleting the boolean feature")
        show("   delete", lambda: _delete(part, result, f"{method} feature"))
        show("   update", lambda: part.update())
        show("   bodies after delete", lambda: part.bodies.names())
        show("   target volume after delete",
             lambda: part.measurement.measure(part.bodies.main).volume_mm3)
        try:
            part.bodies.remove(name, delete_contents=True)
            part.update()
        except Auto3dxError as error:
            print(f"   tool body cleanup: {type(error).__name__}: {str(error)[:80]}")
        print("   bodies at end of this case:", part.bodies.names())


def constraints(part: Any, raw: Any) -> None:
    """3: removing a constraint, with and without an edition session."""
    print("\n== 3. constraint deletion")
    sketch = part.sketches.create(CON_SKETCH, support="XY")
    with sketch.edit() as editor:
        first = editor.line(-90.0, -90.0, -50.0, -90.0)
        second = editor.line(-90.0, -70.0, -50.0, -70.0)
        third = editor.line(-90.0, -50.0, -50.0, -50.0)
        editor.parallel(first, second)
        editor.parallel(first, third)
        editor.horizontal(first)
    part.update()
    raw_sketch = sketch.com_object
    collection = raw_sketch.Constraints
    print(f"  Constraints members: {members(collection)}")
    print("  constraints:", [(collection.Item(i).Name, type(collection.Item(i)).__name__)
                             for i in range(1, int(collection.Count) + 1)])
    print("  Remove source:")
    print(signature_of(collection, "Remove"))
    show("  Item(name) works", lambda: collection.Item(sketch.constraints.names()[0]).Name)

    print("  -- removing with the sketch closed")
    show("  Remove(1)", lambda: collection.Remove(1))
    show("  count", lambda: int(raw_sketch.Constraints.Count))
    show("  broken", lambda: int(raw_sketch.Constraints.BrokenConstraintsCount))
    show("  update", lambda: part.update())
    show("  is_up_to_date", lambda: part.is_up_to_date())

    print("  -- removing inside OpenEdition/CloseEdition")
    show("  OpenEdition", lambda: type(raw_sketch.OpenEdition()).__name__)
    show("  Remove(1)", lambda: raw_sketch.Constraints.Remove(1))
    show("  CloseEdition", lambda: raw_sketch.CloseEdition())
    show("  update", lambda: part.update())
    show("  count", lambda: int(raw_sketch.Constraints.Count))
    show("  broken", lambda: int(raw_sketch.Constraints.BrokenConstraintsCount))
    show("  is_up_to_date", lambda: part.is_up_to_date())


def activity(part: Any, raw: Any) -> None:
    """4: which features expose a usable Activity, and what suppression does downstream."""
    print("\n== 4. feature activity")
    # After the pocket, the disc's edges belong to the latest solid feature, so the seed
    # is picked by "not a sketch wire edge" rather than by a specific feature name.
    solid_edges = [
        edge
        for edge in part.topology.edges(body="PartBody")
        if edge.owner_feature_name and not edge.owner_feature_name.endswith("_SKETCH")
    ]
    print(f"  solid edge owners: {sorted({e.owner_feature_name for e in solid_edges})}")
    part.part_design.create_edge_fillet(FILLET, solid_edges[0], 2.0)
    part.update()

    candidates = {
        "Pad": part.part_design.get_pad(DISC_PAD),
        "Pocket": part.part_design.get_pocket(HOLE_POCKET),
        "Fillet": part.part_design.get_edge_fillet(FILLET),
    }
    for label, feature in candidates.items():
        com_object = feature.com_object
        print(f"\n-- {label} {feature.name}")
        print(f"   has Activity member: {hasattr(com_object, 'Activity')}")
        holder = show("   GetItem('Activity')",
                      lambda c=com_object: type(c.GetItem("Activity")).__name__)
        if holder is None:
            path = f"{raw.Name}\\PartBody\\{feature.name}\\Activity"
            show(f"   Parameters.Item({path!r})",
                 lambda p=path: type(raw.Parameters.Item(p)).__name__)

    print("\n-- the Parent chain above a feature (can a wrapper find its own Part?)")
    node = candidates["Fillet"].com_object
    for step in range(6):
        try:
            node = node.Parent
        except BaseException as error:
            print(f"   step {step}: no Parent ({type(error).__name__})")
            break
        try:
            name = node.Name
        except BaseException:
            name = "<no name>"
        has_parameters = hasattr(node, "Parameters")
        print(f"   step {step}: {type(node).__name__} {name!r} Parameters={has_parameters}")
        if has_parameters:
            break

    print("\n-- suppressing the fillet")
    fillet = candidates["Fillet"]

    def activity_of(feature: Any) -> Any:
        """The Activity BoolParam of one feature, found by its parameter path."""
        return raw.Parameters.Item(f"{raw.Name}\PartBody\{feature.name}\Activity")

    suffix = f"\{fillet.name}\Activity"
    matches = [
        str(raw.Parameters.Item(i).Name)
        for i in range(1, int(raw.Parameters.Count) + 1)
        if str(raw.Parameters.Item(i).Name).endswith(suffix)
    ]
    print(f"  scanning Parameters for the Activity of this feature found: {matches}")
    activity_parameter = activity_of(fillet)
    show("  Activity.Value", lambda: activity_parameter.Value)
    volume = show("  volume", lambda: part.measurement.measure().volume_mm3)
    show("  set Activity = False", lambda: setattr(activity_parameter, "Value", False))
    show("  is_up_to_date before update", lambda: part.is_up_to_date())
    show("  update", lambda: part.update())
    suppressed = show("  volume", lambda: part.measurement.measure().volume_mm3)
    print(f"  volume {volume} -> {suppressed}")
    show("  still in the tree", lambda: [f.name for f in part.inspect.features()])
    show("  set Activity = True", lambda: setattr(activity_parameter, "Value", True))
    show("  update", lambda: part.update())
    show("  volume", lambda: part.measurement.measure().volume_mm3)

    print("\n-- suppressing an UPSTREAM feature that a downstream one depends on")
    pad_activity = activity_of(candidates["Pad"])
    show("  set Pad Activity = False", lambda: setattr(pad_activity, "Value", False))
    show("  update", lambda: part.update())
    show("  is_up_to_date", lambda: part.is_up_to_date())
    show("  features", lambda: [f.name for f in part.inspect.features()])
    show("  fillet Activity now", lambda: activity_parameter.Value)
    show("  volume", lambda: part.measurement.measure().volume_mm3)
    show("  restore Pad Activity", lambda: setattr(pad_activity, "Value", True))
    show("  update", lambda: part.update())
    show("  volume", lambda: part.measurement.measure().volume_mm3)
    show("  is_up_to_date", lambda: part.is_up_to_date())


def cleanup(part: Any, raw: Any) -> None:
    """Removes only what this probe created."""
    print("\n== cleanup")
    try:
        raw.InWorkObject = raw.MainBody
    except BaseException:
        traceback.print_exc()
    for name in list(part.bodies.names()):
        if name.startswith(PREFIX):
            try:
                part.bodies.remove(name, delete_contents=True)
            except Auto3dxError as error:
                print(f"  body {name}: {type(error).__name__}: {str(error)[:70]}")
    for step in (
        lambda: part.part_design.remove_edge_fillet(FILLET),
        lambda: part.part_design.remove_pocket(HOLE_POCKET),
        lambda: part.sketches.remove(HOLE_SKETCH),
        lambda: part.part_design.remove_pad(DISC_PAD),
        lambda: part.sketches.remove(DISC_SKETCH),
        lambda: part.sketches.remove(CON_SKETCH),
        lambda: part.planes.remove(part.planes.get(TOP_PLANE)),
        lambda: part.planes.remove_geometrical_set(),
    ):
        try:
            step()
        except Auto3dxError as error:
            print(f"  skipped: {type(error).__name__}: {str(error)[:70]}")
        except BaseException:
            traceback.print_exc()
    try:
        part.update()
    except Auto3dxError as error:
        print(f"  update after cleanup failed: {error}")
    print(part.inspect.summary().render())


PHASES = ("circ", "bool", "constraints", "activity")


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
        build_disc(part)
        for phase in wanted:
            if phase == "circ":
                circular_pattern(part, raw)
            elif phase == "bool":
                booleans(part, raw)
            elif phase == "constraints":
                constraints(part, raw)
            else:
                activity(part, raw)
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
