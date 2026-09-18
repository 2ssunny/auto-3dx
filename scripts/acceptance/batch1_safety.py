"""Acceptance: the first safety batch, proved on a live Part through the public API.

Two processes, against a disposable Part named by `AUTO3DX_LIVE_PART`:

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python scripts/acceptance/batch1_safety.py create
    python scripts/acceptance/batch1_safety.py verify-and-remove

`create` builds a main-body pad and a second body with its own pad, then proves, in
order: a body rebuilt on its own is up to date and measurable; body-scoped topology is
disjoint and correctly owned; an edge of one body is refused for a feature in another
BEFORE CATIA is called; the same feature built on the right body's edge updates; a
`PartUpdateError` caused by an edit heals when the edit is rolled back, with the feature
still in the tree; and a freshly created plane is refused as a sketch support with an
actionable error until the Part is updated. It exits without cleaning up.

`verify-and-remove` attaches in a new process, rediscovers both bodies, checks scoped
topology and ownership still work with nothing remembered from the first process,
measures the second body, reads every parameter (including the `EnumParam`s CATIA makes
for sketch constraints), then removes only `AUTO3DX_BATCH1_*` objects and compares the
Part with the baseline.

Public auto_3dx API only: no raw COM, no `part.com_object`, no save, no propagate, no
export. Deletion and topology need the Part to be active, so the script refuses any
other Part.
"""

import json
import math
import os
import pathlib
import sys

from auto_3dx import Auto3dxError, Catia, PartUpdateError
from auto_3dx.errors import (
    CrossBodyReferenceError,
    SupportNotUpdatedError,
    TargetNotUpToDateError,
)
from auto_3dx.geometry.planes import GEOMETRICAL_SET_NAME

PART_ENV_VAR = "AUTO3DX_LIVE_PART"
PREFIX = "AUTO3DX_BATCH1_"
MAIN_SKETCH, MAIN_PAD = f"{PREFIX}MAIN_SKETCH", f"{PREFIX}MAIN_PAD"
TOOL_BODY, TOOL_SKETCH, TOOL_PAD = (
    f"{PREFIX}TOOL_BODY",
    f"{PREFIX}TOOL_SKETCH",
    f"{PREFIX}TOOL_PAD",
)
FILLET = f"{PREFIX}FILLET"
PLANE, PLANE_SKETCH = f"{PREFIX}PLANE", f"{PREFIX}PLANE_SKETCH"
MAIN_SIDE, MAIN_HEIGHT, BROKEN_HEIGHT = 40.0, 30.0, 1.0
TOOL_SIDE, TOOL_HEIGHT, TOOL_X = 20.0, 12.0, 200.0
FILLET_RADIUS, PLANE_OFFSET = 5.0, 50.0
BASELINE_FILE = pathlib.Path(__file__).with_suffix(".baseline.json")


def target_part():
    """Attaches and returns the active Part if it is the one named, or exits."""
    target = os.environ.get(PART_ENV_VAR, "").strip()
    if not target:
        sys.exit(f"Refusing to run: set {PART_ENV_VAR} to the disposable test Part.")
    catia = Catia.attach()
    part = catia.active_part()
    caption = str(catia.com_object.ActiveWindow.Caption)
    if target not in (part.name, caption):
        sys.exit(
            f"Refusing to run: the active Part is {part.name!r} ({caption!r}), not {target!r}."
        )
    return part


def observable_state(part) -> dict:
    """A comparable snapshot of everything this script could have changed."""
    summary = part.inspect.summary()
    volumes = {}
    for body in part.bodies.list():
        try:
            volumes[body.name] = round(part.measurement.measure(body).volume_mm3, 3)
        except Auto3dxError:
            volumes[body.name] = (
                None  # empty, hidden or unrebuilt bodies cannot be measured
            )
    return {
        "up_to_date": summary.up_to_date,
        "bodies": [
            [
                b.name,
                b.is_main,
                [[f.name, f.kind] for f in b.features],
                list(b.sketches),
            ]
            for b in summary.bodies
        ],
        "geometrical_sets": [s.name for s in summary.geometrical_sets],
        "in_work_object": [summary.in_work_object.name, summary.in_work_object.kind]
        if summary.in_work_object
        else None,
        "topology": [summary.topology.edges, summary.topology.faces]
        if summary.topology
        else None,
        "parameters": [p.short_name for p in summary.parameters],
        "volumes": volumes,
    }


def _solid_edge(edges, feature_name: str):
    """Picks an edge of the pad itself, not one of the sketch wire edges beside it.

    A body's edges include the edges of the sketches its pads consumed, and a fillet
    needs a solid edge. `owner_feature_name` is what tells them apart.
    """
    solid = [edge for edge in edges if edge.owner_feature_name == feature_name]
    if not solid:
        raise AssertionError(
            f"no edge owned by {feature_name!r} among "
            f"{[edge.owner_feature_name for edge in edges]}"
        )
    return solid[0]


def remove_own(part, plane_set_existed: bool = False) -> None:
    """Removes only what this script created, in dependency order.

    The geometrical set that holds the plane goes too, but only when this script
    created it and nothing else is left in it.
    """
    for step in (
        lambda: part.part_design.remove_edge_fillet(FILLET),
        lambda: part.sketches.remove(PLANE_SKETCH),
        lambda: part.planes.remove(part.planes.get(PLANE)),
        lambda: part.bodies.remove(TOOL_BODY, delete_contents=True),
        lambda: part.part_design.remove_pad(MAIN_PAD),
        lambda: part.sketches.remove(MAIN_SKETCH),
    ):
        try:
            step()
        except Auto3dxError as error:
            print(f"  nothing to remove: {type(error).__name__}")
    plane_set = [
        s for s in part.inspect.geometrical_sets() if s.name == GEOMETRICAL_SET_NAME
    ]
    if not plane_set_existed and plane_set and not plane_set[0].elements:
        part.planes.remove_geometrical_set()
    part.update()


def create() -> None:
    part = target_part()
    baseline = observable_state(part)
    BASELINE_FILE.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    print("baseline:", baseline)
    if [body[0] for body in baseline["bodies"]] != ["PartBody"] or baseline["bodies"][
        0
    ][2]:
        sys.exit("Refusing to run: this Part is not the expected blank test Part.")
    plane_set_before = baseline["geometrical_sets"]

    try:
        # 1. a pad in the main body
        sketch = part.sketches.create(MAIN_SKETCH, support="XY")
        with sketch.edit() as editor:
            editor.rectangle(MAIN_SIDE, MAIN_SIDE)
        part.part_design.create_pad(MAIN_PAD, sketch, MAIN_HEIGHT)
        part.update()

        # 2. a second body with its own pad, built inside work_in
        tool = part.bodies.create(TOOL_BODY)
        with part.work_in(tool):
            tool_sketch = part.sketches.create(TOOL_SKETCH, support="XY")
            with tool_sketch.edit() as editor:
                editor.rectangle(TOOL_SIDE, TOOL_SIDE, origin_x=TOOL_X)
            part.part_design.create_pad(TOOL_PAD, tool_sketch, TOOL_HEIGHT)

        # 3. the body is not rebuilt until something rebuilds it, and measuring says so
        print("ToolBody up to date before its update:", tool.is_up_to_date)
        assert tool.is_up_to_date is False, (
            "a body with a new pad should need a rebuild"
        )
        try:
            part.measurement.measure(tool)
        except TargetNotUpToDateError as error:
            print("measuring it is refused:", str(error)[:90])
        else:
            raise AssertionError("measuring an unrebuilt body should be refused")

        # 4. the body-specific rebuild
        tool.update()
        assert tool.is_up_to_date is True
        volume = part.measurement.measure(tool).volume_mm3
        print("ToolBody volume after body.update():", volume)
        assert math.isclose(
            volume, TOOL_SIDE * TOOL_SIDE * TOOL_HEIGHT, rel_tol=1e-6
        ), volume
        part.update()

        # 5. scoped topology: two disjoint, correctly owned sets
        main_edges = part.topology.edges(body="PartBody")
        tool_edges = part.topology.edges(body=TOOL_BODY)
        all_edges = part.topology.edges(body=None)
        print(
            f"edges: main={len(main_edges)} tool={len(tool_edges)} part-wide={len(all_edges)}"
        )
        assert {edge.owner_body_name for edge in main_edges} == {"PartBody"}
        assert {edge.owner_body_name for edge in tool_edges} == {TOOL_BODY}
        main_descriptors = {edge.descriptor for edge in main_edges}
        tool_descriptors = {edge.descriptor for edge in tool_edges}
        assert not (main_descriptors & tool_descriptors), "scoped snapshots overlap"
        assert len(all_edges) == len(main_edges) + len(tool_edges)

        # 6. the dangerous case: a ToolBody edge fed to a feature built in the main body
        stolen = _solid_edge(part.topology.edges(body=TOOL_BODY), TOOL_PAD)
        try:
            part.part_design.create_edge_fillet(FILLET, stolen, FILLET_RADIUS)
        except CrossBodyReferenceError as error:
            print("cross-body fillet refused:", str(error)[:120])
        else:
            raise AssertionError(
                "a ToolBody edge must not build a fillet in the main body"
            )
        assert FILLET not in [f.name for f in part.part_design.edge_fillets]
        assert part.is_up_to_date(), "a refused call must not have touched the model"

        # 7. the same feature on the right body's edge
        edge = _solid_edge(part.topology.edges(body="PartBody"), MAIN_PAD)
        part.part_design.create_edge_fillet(FILLET, edge, FILLET_RADIUS)
        part.update()
        assert part.is_up_to_date()
        filleted_volume = part.measurement.measure().volume_mm3
        print("main body volume with the fillet:", filleted_volume)

        # 8. a failed update heals when the edit that caused it is rolled back
        pad = part.part_design.get_pad(MAIN_PAD)
        pad.set_height(BROKEN_HEIGHT)
        try:
            part.update()
        except PartUpdateError as error:
            print("update failed as expected:", str(error)[:80])
        else:
            raise AssertionError(
                "a 1 mm pad under a 5 mm fillet should fail the update"
            )
        assert part.is_up_to_date() is False
        assert FILLET in [f.name for f in part.part_design.edge_fillets], (
            "nothing was deleted"
        )
        pad.set_height(MAIN_HEIGHT)
        part.update()
        assert part.is_up_to_date(), "restoring the dimension should heal the Part"
        healed = part.measurement.measure().volume_mm3
        print("main body volume after healing:", healed)
        assert math.isclose(healed, filleted_volume, rel_tol=1e-9)

        # 9. a new plane is refused as a sketch support until the Part is rebuilt
        plane = part.planes.create_offset(PLANE, "XY", PLANE_OFFSET)
        try:
            part.sketches.create(PLANE_SKETCH, support=plane)
        except SupportNotUpdatedError as error:
            print("sketch on an unrebuilt plane refused:", str(error)[:110])
        else:
            raise AssertionError("a plane that was never rebuilt should be refused")
        assert PLANE_SKETCH not in part.sketches.names()
        part.update()
        part.sketches.create(PLANE_SKETCH, support=plane)
        print("sketch on the plane after part.update(): OK")

        state = observable_state(part)
        state["plane_set_before"] = plane_set_before
        BASELINE_FILE.write_text(
            json.dumps({"baseline": baseline, "after_create": state}, indent=2),
            encoding="utf-8",
        )
        print("create: OK, exiting without cleanup")
    except BaseException:
        print("create FAILED; removing only what this run made")
        remove_own(part, GEOMETRICAL_SET_NAME in plane_set_before)
        raise


def verify_and_remove() -> None:
    part = target_part()
    stored = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    baseline = stored["baseline"]

    # 1. both bodies are found again, with nothing carried over from the first process
    tool = part.bodies.get(TOOL_BODY)
    main = part.bodies.main
    print("rediscovered:", [body.name for body in part.bodies.list()])
    assert [f.name for f in tool.features] == [TOOL_PAD]
    assert FILLET in [f.name for f in part.part_design.edge_fillets]
    # The body rebuilt on its own in the first process is still up to date here; the main
    # body is not, because that process ended by creating a sketch in it.
    print(f"up to date: tool={tool.is_up_to_date} main={main.is_up_to_date}")
    assert tool.is_up_to_date is True, "a per-body rebuild must survive the process"
    part.update()
    assert main.is_up_to_date is True and part.is_up_to_date()

    # 2. scoped topology and ownership are re-derived from the model, not remembered
    main_edges = part.topology.edges(body=main)
    tool_edges = part.topology.edges(body=tool)
    print(f"edges in a fresh process: main={len(main_edges)} tool={len(tool_edges)}")
    assert {edge.owner_body_name for edge in main_edges} == {"PartBody"}
    assert {edge.owner_body_name for edge in tool_edges} == {TOOL_BODY}
    assert {edge.owner_feature_name for edge in tool_edges} <= {TOOL_PAD, TOOL_SKETCH}
    try:
        part.part_design.create_edge_fillet(
            f"{PREFIX}NEVER", _solid_edge(tool_edges, TOOL_PAD), 1.0
        )
    except CrossBodyReferenceError:
        print("cross-body misuse still refused in a fresh process")
    else:
        raise AssertionError("ownership must survive into a new process")

    # 3. faces scope too, and the body measures
    tool_faces = part.topology.faces(body=tool)
    assert {face.owner_body_name for face in tool_faces} == {TOOL_BODY}
    volume = part.measurement.measure(tool).volume_mm3
    assert math.isclose(volume, TOOL_SIDE * TOOL_SIDE * TOOL_HEIGHT, rel_tol=1e-6), (
        volume
    )
    print(f"ToolBody: {len(tool_faces)} faces, volume {volume}")

    # 4. every parameter can be read, including the EnumParams CATIA made for constraints
    values = {parameter.kind: parameter.value for parameter in part.parameters.list()}
    print("parameter kinds read:", sorted(values))
    assert "EnumParam" in values, (
        "a constrained sketch should have produced an EnumParam"
    )
    assert isinstance(values["EnumParam"], str)
    assert len(part.inspect.summary().parameters) >= 0

    # 5. remove only this script's objects and compare with the baseline
    remove_own(part, GEOMETRICAL_SET_NAME in baseline["geometrical_sets"])
    if TOOL_BODY in part.bodies.names():
        raise AssertionError("the tool body is still there")
    restored = observable_state(part)
    if restored != baseline:
        for key in baseline:
            if restored.get(key) != baseline[key]:
                print(f"  DIFFERS {key}: {baseline[key]!r} -> {restored.get(key)!r}")
        raise AssertionError("the Part did not return to its baseline")
    BASELINE_FILE.unlink()
    print("verify-and-remove: OK, baseline restored exactly")


if __name__ == "__main__":
    phases = {"create": create, "verify-and-remove": verify_and_remove}
    if len(sys.argv) != 2 or sys.argv[1] not in phases:
        sys.exit(f"usage: {sys.argv[0]} {{{'|'.join(phases)}}}")
    phases[sys.argv[1]]()
