"""Acceptance: Phase 3 operations, proved across two processes through the public API.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python scripts/acceptance/phase3_operations.py create
    python scripts/acceptance/phase3_operations.py verify-and-remove

`create` builds a flange-like disc with one bolt hole, then proves: a circular pattern
repeats that hole six times around Z and removes exactly five more holes' worth of
material; a boolean remove consumes a tool body and takes the expected volume with it; a
sketch constraint is removed without breaking the solver; and a fillet is suppressed and
reactivated with its geometry returning exactly. It exits without cleaning up.

`verify-and-remove` attaches in a new interpreter that built none of it, rediscovers every
one of those objects from the model, edits and re-checks them, then removes every
`AUTO3DX_PHASE3_*` object and compares the Part with the baseline.

Public auto_3dx API only: no raw COM anywhere, including the target check, which uses
`catia.active_window_title`. No save, no propagate, no export.
"""

import json
import math
import os
import pathlib
import sys

from auto_3dx import Auto3dxError, Catia
from auto_3dx.errors import (
    BooleanOperationError,
    ConstraintNotFoundError,
    CrossBodyReferenceError,
    StaleSnapshotError,
)
from auto_3dx.geometry.planes import GEOMETRICAL_SET_NAME

PART_ENV_VAR = "AUTO3DX_LIVE_PART"
PREFIX = "AUTO3DX_PHASE3_"
DISC_SKETCH, DISC_PAD = f"{PREFIX}DISC_SKETCH", f"{PREFIX}DISC_PAD"
TOP_PLANE = f"{PREFIX}TOP_PLANE"
HOLE_SKETCH, HOLE_POCKET = f"{PREFIX}HOLE_SKETCH", f"{PREFIX}HOLE_POCKET"
PATTERN, FILLET = f"{PREFIX}BOLT_CIRCLE", f"{PREFIX}FILLET"
TOOL_BODY, BOOLEAN = f"{PREFIX}TOOL", f"{PREFIX}CUT"
CON_SKETCH = f"{PREFIX}CON_SKETCH"
DISC_DIAMETER, DISC_HEIGHT = 120.0, 10.0
HOLE_RADIUS, HOLE_DEPTH, HOLE_X = 6.0, 20.0, 40.0
TOOL_RADIUS, TOOL_HEIGHT = 15.0, 40.0
INSTANCES, SPACING = 6, 60.0
HOLE_VOLUME = DISC_HEIGHT * math.pi * HOLE_RADIUS**2
OVERLAP_VOLUME = DISC_HEIGHT * math.pi * TOOL_RADIUS**2
BASELINE_FILE = pathlib.Path(__file__).with_suffix(".baseline.json")


def target_part():
    """Attaches and returns the active Part if it is the one named, or exits.

    The identity check uses only public API: the Part's Automation name and the session's
    active window title.
    """
    target = os.environ.get(PART_ENV_VAR, "").strip()
    if not target:
        sys.exit(f"Refusing to run: set {PART_ENV_VAR} to the disposable test Part.")
    catia = Catia.attach()
    part = catia.active_part()
    title = catia.active_window_title
    if target not in (part.name, title):
        sys.exit(
            f"Refusing to run: the active Part is {part.name!r} ({title!r}), not {target!r}."
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
            volumes[body.name] = None
    return {
        "up_to_date": summary.up_to_date,
        "features": [[f.name, f.kind] for f in summary.features],
        "sketches": list(summary.sketches),
        "bodies": [b.name for b in summary.bodies],
        "geometrical_sets": [s.name for s in summary.geometrical_sets],
        "parameters": [p.short_name for p in summary.parameters],
        "in_work_object": [summary.in_work_object.name, summary.in_work_object.kind]
        if summary.in_work_object
        else None,
        "volumes": volumes,
    }


def remove_own(part, plane_set_existed: bool = True) -> None:
    """Removes only what this script created, in dependency order."""
    for name in list(part.bodies.names()):
        if name.startswith(PREFIX):
            try:
                part.bodies.remove(name, delete_contents=True)
            except Auto3dxError as error:
                print(f"  body {name}: {type(error).__name__}")
    for step in (
        lambda: part.part_design.remove_boolean(BOOLEAN, delete_consumed_body=True),
        lambda: part.part_design.remove_circular_pattern(PATTERN),
        lambda: part.part_design.remove_edge_fillet(FILLET),
        lambda: part.part_design.remove_pocket(HOLE_POCKET),
        lambda: part.sketches.remove(HOLE_SKETCH),
        lambda: part.planes.remove(part.planes.get(TOP_PLANE)),
        lambda: part.part_design.remove_pad(DISC_PAD),
        lambda: part.sketches.remove(DISC_SKETCH),
        lambda: part.sketches.remove(CON_SKETCH),
    ):
        try:
            step()
        except Auto3dxError as error:
            print(f"  nothing to remove: {type(error).__name__}")
    sdk_set = [
        item for item in part.inspect.geometrical_sets() if item.name == GEOMETRICAL_SET_NAME
    ]
    if not plane_set_existed and sdk_set and not sdk_set[0].elements:
        part.planes.remove_geometrical_set()
    part.update()


def build_disc(part) -> None:
    """A flange-like disc with one bolt hole cut down into it."""
    sketch = part.sketches.create(DISC_SKETCH, support="XY")
    with sketch.edit() as editor:
        editor.circle(0.0, 0.0, DISC_DIAMETER / 2)
    part.part_design.create_pad(DISC_PAD, sketch, DISC_HEIGHT)
    part.update()
    plane = part.planes.create_offset(TOP_PLANE, "XY", DISC_HEIGHT)
    part.update()
    hole = part.sketches.create(HOLE_SKETCH, support=plane)
    with hole.edit() as editor:
        editor.circle(HOLE_X, 0.0, HOLE_RADIUS)
    part.part_design.create_pocket(HOLE_POCKET, hole, HOLE_DEPTH)
    part.update()


def check_circular_pattern(part) -> None:
    """One bolt hole becomes six around the centre."""
    print("-- circular pattern")
    one_hole = part.measurement.measure().volume_mm3
    seed = part.part_design.get_pocket(HOLE_POCKET)
    pattern = part.part_design.create_circular_pattern(PATTERN, seed, INSTANCES, SPACING)
    assert part.is_up_to_date() is False, "creation must not rebuild on its own"
    part.update()

    patterned = part.measurement.measure().volume_mm3
    removed = one_hole - patterned
    print(f"   {pattern.angular_instances} instances at {pattern.angular_spacing_deg} deg, "
          f"removed {removed:.3f} (five more holes = {(INSTANCES - 1) * HOLE_VOLUME:.3f})")
    assert math.isclose(removed, (INSTANCES - 1) * HOLE_VOLUME, rel_tol=1e-6)
    assert pattern.radial_instances == 1

    # The seed must belong to the body being patterned in.
    tool = part.bodies.create(f"{PREFIX}SEED_CHECK")
    with part.work_in(tool):
        sketch = part.sketches.create(f"{PREFIX}SEED_CHECK_SKETCH", support="XY")
        with sketch.edit() as editor:
            editor.circle(300.0, 0.0, 5.0)
        foreign_seed = part.part_design.create_pad(f"{PREFIX}SEED_CHECK_PAD", sketch, 5.0)
    tool.update()
    try:
        part.part_design.create_circular_pattern(
            f"{PREFIX}NEVER", foreign_seed, INSTANCES, SPACING
        )
    except CrossBodyReferenceError as error:
        print("   a seed from another body is refused:", str(error)[:90])
    else:
        raise AssertionError("a seed from another body must be refused")
    part.bodies.remove(f"{PREFIX}SEED_CHECK", delete_contents=True)
    part.update()


def check_boolean(part) -> None:
    """A tool body is subtracted from the disc and consumed by the operation."""
    print("-- boolean remove")
    before = part.measurement.measure().volume_mm3
    body = part.bodies.create(TOOL_BODY)
    with part.work_in(body):
        sketch = part.sketches.create(f"{TOOL_BODY}_SKETCH", support="XY")
        with sketch.edit() as editor:
            editor.circle(0.0, 0.0, TOOL_RADIUS)
        part.part_design.create_pad(f"{TOOL_BODY}_PAD", sketch, TOOL_HEIGHT)
    body.update()
    assert TOOL_BODY in part.bodies.names()

    try:
        part.part_design.create_boolean_remove(BOOLEAN, "PartBody")
    except BooleanOperationError as error:
        print("   a body cannot be its own tool:", str(error)[:80])
    else:
        raise AssertionError("the target body must not be usable as its own tool")

    operation = part.part_design.create_boolean_remove(BOOLEAN, TOOL_BODY)
    part.update()
    after = part.measurement.measure().volume_mm3
    print(f"   {operation.operation} using {operation.tool_body_name!r}: "
          f"{before:.3f} -> {after:.3f} (overlap = {OVERLAP_VOLUME:.3f})")
    assert math.isclose(before - after, OVERLAP_VOLUME, rel_tol=1e-3)
    assert TOOL_BODY not in part.bodies.names(), "the tool body is consumed"

    try:
        part.part_design.remove_boolean(BOOLEAN)
    except BooleanOperationError as error:
        print("   removal needs the consumed body acknowledged:", str(error)[:90])
    else:
        raise AssertionError("removing a boolean must require acknowledgement")


def check_constraints(part) -> None:
    """A constraint is removed without breaking the sketch solver."""
    print("-- constraint removal")
    sketch = part.sketches.create(CON_SKETCH, support="XY")
    with sketch.edit() as editor:
        first = editor.line(-90.0, -90.0, -50.0, -90.0)
        second = editor.line(-90.0, -70.0, -50.0, -70.0)
        third = editor.line(-90.0, -50.0, -50.0, -50.0)
        editor.parallel(first, second)
        editor.parallel(first, third)
    part.update()
    names = sketch.constraints.names()
    print(f"   constraints: {names}, broken {sketch.constraints.broken_count}")
    assert len(names) == 2

    sketch.constraints.remove(names[0])
    part.update()
    print(f"   after removing {names[0]!r}: {sketch.constraints.names()}, "
          f"broken {sketch.constraints.broken_count}")
    assert sketch.constraints.names() == names[1:]
    assert sketch.constraints.broken_count == 0
    assert part.is_up_to_date()

    try:
        sketch.constraints.remove(names[0])
    except ConstraintNotFoundError:
        print("   removing it twice is refused")
    else:
        raise AssertionError("a constraint cannot be removed twice")


def check_suppression(part) -> None:
    """A fillet is suppressed and reactivated, and old snapshots go stale."""
    print("-- feature suppression")
    solid_edges = [
        edge
        for edge in part.topology.edges(body="PartBody")
        if edge.owner_feature_name and not edge.owner_feature_name.endswith("_SKETCH")
    ]
    part.part_design.create_edge_fillet(FILLET, solid_edges[0], 2.0)
    part.update()
    fillet = part.part_design.get_edge_fillet(FILLET)
    filleted = part.measurement.measure().volume_mm3
    assert fillet.is_active is True

    snapshot = part.topology.edges()
    fillet.deactivate()
    assert part.is_up_to_date() is False, "suppression must not rebuild on its own"
    part.update()
    suppressed = part.measurement.measure().volume_mm3
    print(f"   suppressed: {filleted:.3f} -> {suppressed:.3f}, still in the tree: "
          f"{FILLET in [f.name for f in part.part_design.edge_fillets]}")
    assert suppressed > filleted
    assert fillet.is_active is False

    try:
        part.part_design.create_edge_fillet(f"{PREFIX}NEVER", snapshot[0], 1.0)
    except StaleSnapshotError:
        print("   a snapshot taken before the suppression is refused")
    else:
        raise AssertionError("an old topology snapshot must be refused")

    fillet.activate()
    part.update()
    assert fillet.is_active is True
    assert math.isclose(part.measurement.measure().volume_mm3, filleted, rel_tol=1e-9)
    print(f"   reactivated: volume back to {filleted:.3f}")


def create() -> None:
    part = target_part()
    baseline = observable_state(part)
    BASELINE_FILE.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    print("baseline:", baseline)
    if baseline["features"] or baseline["sketches"] or baseline["bodies"] != ["PartBody"]:
        sys.exit("Refusing to run: this Part is not the expected blank test Part.")
    plane_set_existed = GEOMETRICAL_SET_NAME in baseline["geometrical_sets"]

    try:
        build_disc(part)
        check_circular_pattern(part)
        check_boolean(part)
        check_constraints(part)
        check_suppression(part)
        print("create: OK, exiting without cleanup")
    except BaseException:
        print("create FAILED; removing only what this run made")
        remove_own(part, plane_set_existed)
        raise


def verify_and_remove() -> None:
    part = target_part()
    baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    plane_set_existed = GEOMETRICAL_SET_NAME in baseline["geometrical_sets"]
    print("this process built none of the geometry below")

    # 1. the circular pattern, rediscovered and edited
    pattern = part.part_design.get_circular_pattern(PATTERN)
    print(f"-- pattern {pattern.name!r}: {pattern.angular_instances} instances at "
          f"{pattern.angular_spacing_deg} deg")
    assert pattern.angular_instances == INSTANCES
    volume = part.measurement.measure().volume_mm3
    pattern.set_angular_instances(8)
    pattern.set_angular_spacing_deg(45.0)
    part.update()
    widened = part.measurement.measure().volume_mm3
    print(f"   8 instances at 45 deg: {volume:.3f} -> {widened:.3f}")
    assert math.isclose(volume - widened, 2 * HOLE_VOLUME, rel_tol=1e-6)
    pattern.set_angular_instances(INSTANCES)
    pattern.set_angular_spacing_deg(SPACING)
    part.update()

    # 2. the boolean and the body it consumed
    operation = part.part_design.get_boolean(BOOLEAN)
    print(f"-- boolean {operation.name!r} ({operation.operation}) consumed "
          f"{operation.tool_body_name!r}")
    assert operation.tool_body_name == TOOL_BODY
    assert TOOL_BODY not in part.bodies.names()

    # 3. the sketch and its remaining constraint
    sketch = part.sketches.get(CON_SKETCH)
    names = sketch.constraints.names()
    print(f"-- sketch {CON_SKETCH!r}: constraints {names}")
    assert len(names) == 1
    with sketch.edit():
        sketch.constraints.remove(names[0])
    part.update()
    assert sketch.constraints.count == 0
    assert sketch.constraints.broken_count == 0
    print("   removed the last one from inside an edit block; nothing broke")

    # 4. suppression, from a wrapper this process made
    fillet = part.part_design.get_edge_fillet(FILLET)
    filleted = part.measurement.measure().volume_mm3
    fillet.deactivate()
    part.update()
    suppressed = part.measurement.measure().volume_mm3
    assert suppressed > filleted
    fillet.activate()
    part.update()
    assert math.isclose(part.measurement.measure().volume_mm3, filleted, rel_tol=1e-9)
    print(f"-- fillet suppressed and restored: {filleted:.3f}")

    remove_own(part, plane_set_existed)
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
