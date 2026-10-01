"""Probe 42: body ownership of topology, per-body update, EnumParam, plane support.

Establishes the live facts the first safety batch needs, on the disposable Part named by
`AUTO3DX_LIVE_PART` and nowhere else:

1. Does any Automation route scope a topology search to one body, or say which body an
   edge belongs to?
2. Does `Part.Update()` rebuild a non-main body, and does `Part.UpdateObject(body)`?
3. What does measuring a body that is not up to date do?
4. What does an `EnumParam` expose instead of `Value`?
5. Can a newly created offset plane be told apart from an updated one before
   `Sketches.Add` fails on it?
6. Does restoring an upstream dimension heal a Part after `PartUpdateError`?

Everything this probe creates is named `AUTO3DX_P42_*` and is removed in `finally`.
Raw Automation is used deliberately here; that is what a probe is for. Nothing is saved.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python scripts/probes/42_body_scope_and_update.py
"""

import os
import sys
import traceback
from typing import Any

from auto_3dx import Auto3dxError, Catia

PREFIX = "AUTO3DX_P42_"
MAIN_SKETCH, MAIN_PAD = f"{PREFIX}MAIN_SKETCH", f"{PREFIX}MAIN_PAD"
TOOL_BODY, TOOL_SKETCH, TOOL_PAD = (
    f"{PREFIX}TOOL_BODY",
    f"{PREFIX}TOOL_SKETCH",
    f"{PREFIX}TOOL_PAD",
)
PLANE, PLANE_SKETCH = f"{PREFIX}PLANE", f"{PREFIX}PLANE_SKETCH"
CONSTRAINT_SKETCH = f"{PREFIX}CON_SKETCH"
FILLET = f"{PREFIX}FILLET"
MAIN_SIDE, MAIN_HEIGHT = 40.0, 30.0
TOOL_SIDE, TOOL_HEIGHT, TOOL_X = 20.0, 12.0, 200.0


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
        print(f"  {label}: FAILED {type(error).__name__}: {str(error)[:160]}")
        return None
    print(f"  {label}: {result}")
    return result


def build(part: Any) -> None:
    """Builds a main-body pad and a second body with its own pad."""
    sketch = part.sketches.create(MAIN_SKETCH, support="XY")
    with sketch.edit() as editor:
        editor.rectangle(MAIN_SIDE, MAIN_SIDE)
    part.part_design.create_pad(MAIN_PAD, sketch, MAIN_HEIGHT)
    part.update()

    tool = part.bodies.create(TOOL_BODY)
    with part.work_in(tool):
        tool_sketch = part.sketches.create(TOOL_SKETCH, support="XY")
        with tool_sketch.edit() as editor:
            editor.rectangle(TOOL_SIDE, TOOL_SIDE, origin_x=TOOL_X)
        part.part_design.create_pad(TOOL_PAD, tool_sketch, TOOL_HEIGHT)


def update_semantics(part: Any, raw: Any) -> None:
    """2 and 3: does a non-main body rebuild, and what does measuring a dirty one do?"""
    print("\n== 2. update semantics for a non-main body (no update called yet)")
    tool = part.bodies.get(TOOL_BODY)
    show("IsUpToDate(Part)", lambda: part.is_up_to_date())
    show("IsUpToDate(MainBody)", lambda: part.is_up_to_date(part.bodies.main))
    show("IsUpToDate(ToolBody)", lambda: part.is_up_to_date(tool))

    print("\n== 3. measuring a body that is not up to date")
    show("measure(ToolBody)", lambda: part.measurement.measure(tool).volume_mm3)

    print("\n-- after part.update()")
    show("part.update()", lambda: part.update())
    show("IsUpToDate(Part)", lambda: part.is_up_to_date())
    show("IsUpToDate(ToolBody)", lambda: part.is_up_to_date(tool))
    show("measure(ToolBody)", lambda: part.measurement.measure(tool).volume_mm3)

    print("\n-- raw Part.UpdateObject(body), the documented per-object rebuild")
    show("UpdateObject(ToolBody)", lambda: raw.UpdateObject(tool.com_object))
    show("IsUpToDate(ToolBody)", lambda: part.is_up_to_date(tool))
    show("measure(ToolBody)", lambda: part.measurement.measure(tool).volume_mm3)

    print("\n-- update while the body is the In-Work Object")
    previous = raw.InWorkObject
    try:
        raw.InWorkObject = tool.com_object
        show("Part.Update() in body context", lambda: raw.Update())
        show("IsUpToDate(ToolBody)", lambda: part.is_up_to_date(tool))
        show("measure(ToolBody)", lambda: part.measurement.measure(tool).volume_mm3)
    finally:
        raw.InWorkObject = previous
    show("IsUpToDate(Part)", lambda: part.is_up_to_date())


def body_update_only(part: Any, raw: Any) -> None:
    """2b: does `UpdateObject(body)` alone rebuild a body nothing else has updated?"""
    print("\n== 2b. UpdateObject on a body that has never been updated")
    tool = part.bodies.get(TOOL_BODY)
    show("IsUpToDate(Part)", lambda: part.is_up_to_date())
    show("IsUpToDate(ToolBody)", lambda: part.is_up_to_date(tool))
    in_work_before = str(raw.InWorkObject.Name)
    show("UpdateObject(ToolBody)", lambda: raw.UpdateObject(tool.com_object))
    show("IsUpToDate(ToolBody)", lambda: part.is_up_to_date(tool))
    show("measure(ToolBody)", lambda: part.measurement.measure(tool).volume_mm3)
    show("IsUpToDate(Part) (main body still dirty?)", lambda: part.is_up_to_date())
    print(f"  In-Work Object before={in_work_before} after={raw.InWorkObject.Name}")
    show("IsUpToDate(MainBody)", lambda: part.is_up_to_date(part.bodies.main))
    print("  -- and UpdateObject on a body that is already up to date")
    show("UpdateObject(ToolBody) again", lambda: raw.UpdateObject(tool.com_object))
    show("part.update() afterwards", lambda: part.update())


def enum_value_members(part: Any, raw: Any) -> None:
    """4b: how an EnumParam's value is actually read."""
    print("\n== 4b. reading an EnumParam value")
    sketch = part.sketches.create(CONSTRAINT_SKETCH, support="XY")
    with sketch.edit() as editor:
        first = editor.line(-80.0, -80.0, -40.0, -80.0)
        second = editor.line(-80.0, -70.0, -40.0, -70.0)
        editor.parallel(first, second)
    part.update()
    parameters = raw.Parameters
    for position in range(1, int(parameters.Count) + 1):
        parameter = parameters.Item(position)
        if type(parameter).__name__ != "EnumParam":
            continue
        print(f"  {parameter.Name[-50:]}")
        show("    ValueAsString()", lambda p=parameter: p.ValueAsString())
        show("    EnumeratedValues()", lambda p=parameter: p.EnumeratedValues())
        show(
            "    ValuateFromString? (not called)",
            lambda p=parameter: hasattr(p, "ValuateFromString"),
        )
        show(
            "    public members",
            lambda p=parameter: [
                member
                for member in dir(p)
                if member[:1].isupper() and not member.startswith("CLSID")
            ],
        )
        break
    show(
        "SDK Parameter.value on that EnumParam",
        lambda: [p.value for p in part.parameters.list() if p.kind == "EnumParam"][:1],
    )


def topology_ownership(part: Any, raw: Any, selection: Any) -> None:
    """1: can a search be scoped to a body, or an edge be traced back to one?"""
    print("\n== 1. topology ownership")
    main_body = raw.MainBody
    tool_body = part.bodies.get(TOOL_BODY).com_object

    def search(query: str) -> int:
        selection.Search(query)
        return int(selection.Count)

    selection.Clear()
    count = show(
        "Search('Topology.Edge,all') count", lambda: search("Topology.Edge,all")
    )
    if count:
        for position in (1, int(count)):
            item = selection.Item(position)
            print(
                f"  hit {position}: SelectedElement.Value type={type(item.Value).__name__}"
            )
            show(f"  hit {position} Value.Name", lambda item=item: item.Value.Name)
            show(
                f"  hit {position} Value.Parent.Name",
                lambda item=item: item.Value.Parent.Name,
            )
            show(
                f"  hit {position} Value.Parent.Parent.Name",
                lambda item=item: item.Value.Parent.Parent.Name,
            )
            show(f"  hit {position} LeafProduct", lambda item=item: item.LeafProduct)
            show(
                f"  hit {position} Reference.DisplayName",
                lambda item=item: str(item.Reference.DisplayName)[:160],
            )
            show(
                f"  hit {position} Reference.Name",
                lambda item=item: str(item.Reference.Name)[:160],
            )
            show(
                f"  hit {position} Reference.Parent type",
                lambda item=item: type(item.Reference.Parent).__name__,
            )
            show(
                f"  hit {position} Reference.Parent.Name",
                lambda item=item: item.Reference.Parent.Name,
            )
    selection.Clear()

    print("\n-- scoped search attempts, with one body selected first")
    for label, body in (("MainBody", main_body), ("ToolBody", tool_body)):
        for query in ("Topology.Edge,sel", "Topology.Edge,in", "Topology.Edge,all"):
            selection.Clear()
            try:
                selection.Add(body)
            except BaseException as error:
                print(f"  {label}: could not select ({type(error).__name__})")
                break
            show(f"  {label} + Search({query!r})", lambda q=query: search(q))
    selection.Clear()

    print("\n-- the owner chain above a topology reference")
    selection.Clear()
    search("Topology.Edge,all")
    for position in (1, int(selection.Count)):
        item = selection.Item(position)
        chain = []
        node = item.Reference.Parent
        for _ in range(4):
            if node is None:
                break
            try:
                chain.append(f"{type(node).__name__}:{node.Name}")
            except BaseException:
                chain.append(f"{type(node).__name__}:<no name>")
            try:
                node = node.Parent
            except BaseException:
                break
        print(f"  hit {position} Reference.Parent chain: {' -> '.join(chain)}")
    selection.Clear()

    print("\n-- does ,sel scope faces too, and what does each scoped hit own?")
    for label, body in (("MainBody", main_body), ("ToolBody", tool_body)):
        for query in ("Topology.Edge,sel", "Topology.Face,sel"):
            selection.Clear()
            selection.Add(body)
            count = show(f"  {label} + Search({query!r})", lambda q=query: search(q))
            owners = []
            for position in range(1, int(count or 0) + 1):
                try:
                    owners.append(str(selection.Item(position).Reference.Parent.Name))
                except BaseException as error:
                    owners.append(f"<{type(error).__name__}>")
            print(f"    owners: {sorted(set(owners))}")
    selection.Clear()

    print("\n-- does ,sel follow the selection or the In-Work Object?")
    previous = raw.InWorkObject
    try:
        raw.InWorkObject = tool_body
        selection.Clear()
        selection.Add(main_body)
        count = show(
            "  ToolBody in work + MainBody selected + ,sel",
            lambda: search("Topology.Edge,sel"),
        )
        owners = [
            str(selection.Item(position).Reference.Parent.Name)
            for position in range(1, int(count or 0) + 1)
        ]
        print(f"    owners: {sorted(set(owners))}")
    finally:
        raw.InWorkObject = previous
        selection.Clear()

    print("\n-- per-body search through each body's own selection-free route")
    for label, body in (("MainBody", main_body), ("ToolBody", tool_body)):
        show(
            f"  {label}.Shapes names",
            lambda body=body: [
                body.Shapes.Item(i).Name for i in range(1, int(body.Shapes.Count) + 1)
            ],
        )
        show(
            f"  CreateReferenceFromObject({label})",
            lambda body=body: type(raw.CreateReferenceFromObject(body)).__name__,
        )
    selection.Clear()


def enum_parameters(part: Any, raw: Any) -> None:
    """4: what an EnumParam exposes, using constraints to make CATIA create some."""
    print("\n== 4. EnumParam")
    # A sketch of its own: loose lines inside a sketch a Pad consumes break that Pad.
    sketch = part.sketches.create(CONSTRAINT_SKETCH, support="XY")
    with sketch.edit() as editor:
        first = editor.line(-80.0, -80.0, -40.0, -80.0)
        second = editor.line(-80.0, -70.0, -40.0, -70.0)
        editor.parallel(first, second)
    part.update()

    parameters = raw.Parameters
    count = int(parameters.Count)
    print(f"  Part.Parameters.Count = {count}")
    seen: set[str] = set()
    for position in range(1, count + 1):
        parameter = parameters.Item(position)
        kind = type(parameter).__name__
        if kind in seen and kind != "EnumParam":
            continue
        seen.add(kind)
        name = str(parameter.Name)
        line = f"  {kind} {name[-60:]}"
        for member in ("Value", "ValueAsString", "ValueAsInt", "ValuationType"):
            try:
                line += f" | {member}={getattr(parameter, member)!r}"
            except BaseException as error:
                line += f" | {member}=<{type(error).__name__}>"
        print(line)
    print("  SDK read of every parameter:")
    show("  part.parameters.list()", lambda: len(part.parameters.list()))
    show("  part.inspect.parameters()", lambda: len(part.inspect.parameters()))


def plane_support(part: Any, raw: Any) -> None:
    """5: is a not-yet-updated plane distinguishable before Sketches.Add fails?"""
    print("\n== 5. offset plane as a sketch support before any update")
    plane = part.planes.create_offset(PLANE, "XY", 50.0)
    show("IsUpToDate(Part) after creating the plane", lambda: part.is_up_to_date())
    show("IsUpToDate(plane)", lambda: part.is_up_to_date(plane))
    show("plane kind", lambda: type(plane.com_object).__name__)
    show(
        "sketches.create(support=plane) before update",
        lambda: part.sketches.create(PLANE_SKETCH, support=plane).name,
    )
    print("  -- after part.update()")
    show("part.update()", lambda: part.update())
    show("IsUpToDate(plane)", lambda: part.is_up_to_date(plane))
    show(
        "sketches.create(support=plane) after update",
        lambda: part.sketches.create(PLANE_SKETCH, support=plane).name,
    )
    show(
        "UpdateObject(plane) instead of a full update",
        lambda: raw.UpdateObject(plane.com_object),
    )


def healing(part: Any, raw: Any = None) -> None:
    """6: does restoring an upstream dimension heal the Part after PartUpdateError?"""
    print("\n== 6. PartUpdateError healing")
    edges = part.topology.edges()
    print(f"  edges before the fillet: {len(edges)}")
    main_edges = [edge for edge in edges if MAIN_PAD.lower() in edge.descriptor.lower()]
    print(f"  edges whose descriptor names {MAIN_PAD}: {len(main_edges)}")
    if not main_edges:
        print("  no main-body edge identified by descriptor; using the first edge")
        main_edges = [edges[0]]
    part.part_design.create_edge_fillet(FILLET, main_edges[0], 5.0)
    show("update after the fillet", lambda: part.update())
    show("measure(MainBody)", lambda: part.measurement.measure().volume_mm3)

    pad = part.part_design.get_pad(MAIN_PAD)
    show("pad height", lambda: pad.height)
    show("set pad height to 1", lambda: pad.set_height(1.0))
    show("update (expected to fail)", lambda: part.update())
    show("IsUpToDate(Part)", lambda: part.is_up_to_date())
    show(
        "fillet still present",
        lambda: FILLET in [f.name for f in part.part_design.edge_fillets],
    )
    show("restore pad height", lambda: pad.set_height(MAIN_HEIGHT))
    show("update again", lambda: part.update())
    show("IsUpToDate(Part)", lambda: part.is_up_to_date())
    show("measure(MainBody)", lambda: part.measurement.measure().volume_mm3)


def cleanup(part: Any) -> None:
    """Removes only what this probe created."""
    print("\n== cleanup")
    for step in (
        lambda: part.part_design.remove_edge_fillet(FILLET),
        lambda: part.sketches.remove(PLANE_SKETCH),
        lambda: part.sketches.remove(CONSTRAINT_SKETCH),
        lambda: part.planes.remove(part.planes.get(PLANE)),
        lambda: part.planes.remove_geometrical_set(),
        lambda: part.bodies.remove(TOOL_BODY, delete_contents=True),
        lambda: part.part_design.remove_pad(MAIN_PAD),
        lambda: part.sketches.remove(MAIN_SKETCH),
    ):
        try:
            step()
        except Auto3dxError as error:
            print(f"  skipped: {type(error).__name__}: {str(error)[:100]}")
        except BaseException:
            traceback.print_exc()
    try:
        part.update()
    except Auto3dxError as error:
        print(f"  update after cleanup failed: {error}")
    print(part.inspect.summary().render())


PHASES = ("update", "bodyupdate", "topology", "enum", "enumcall", "plane", "healing")


def main() -> None:
    wanted = sys.argv[1:] or list(PHASES)
    unknown = [phase for phase in wanted if phase not in PHASES]
    if unknown:
        sys.exit(f"unknown phase(s) {unknown}; choose from {list(PHASES)}")
    part = target_part()
    raw = part.com_object
    selection = Catia.attach().active_editor().Selection
    print(part.inspect.summary().render())
    previous_in_work = raw.InWorkObject
    held = [selection.Item(i).Value for i in range(1, int(selection.Count) + 1)]
    print(f"selection held by the user: {len(held)} item(s)")
    try:
        build(part)
        for phase in wanted:
            if phase == "update":
                update_semantics(part, raw)
            elif phase == "bodyupdate":
                body_update_only(part, raw)
            elif phase == "enumcall":
                enum_value_members(part, raw)
            elif phase == "topology":
                topology_ownership(part, raw, selection)
            elif phase == "enum":
                enum_parameters(part, raw)
            elif phase == "plane":
                plane_support(part, raw)
            else:
                healing(part)
    finally:
        try:
            raw.InWorkObject = previous_in_work
        except BaseException:
            traceback.print_exc()
        cleanup(part)
        try:
            selection.Clear()
            for value in held:
                selection.Add(value)
            print(f"selection restored: {int(selection.Count)} item(s)")
        except BaseException:
            traceback.print_exc()


if __name__ == "__main__":
    main()
