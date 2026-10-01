"""Acceptance: a bearing bracket modelled and modified by GEOMETRY, across two processes.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python scripts/acceptance/phase4_geometry.py create
    python scripts/acceptance/phase4_geometry.py verify-and-remove

`create` builds a base plate, a boss on an offset plane, a through bore cut up from XY with
an explicit direction, two mounting holes by circular pattern, a notch by boolean remove,
and a fillet on the boss rim -- then proves, in order: every feature is classified as
supported; the boss top, the bore rim and the base's top face are found by geometry alone;
a pocket's direction decides whether it cuts; moving the boss plane moves the boss; the
plane cannot be deleted while the boss sketch sits on it; and an invalid upstream edit is
diagnosed and healed by rolling it back. It exits without cleaning up.

`verify-and-remove` attaches in a new interpreter, asks the same geometric questions of the
model it finds, makes one more geometry-selected edit, then removes every
`AUTO3DX_PHASE4_*` object and compares the Part with the baseline.

Public auto_3dx API only: no raw COM, no private members, no topology index, no BRep or
descriptor string. No save, no propagate, no export.
"""

import json
import math
import os
import pathlib
import sys

from auto_3dx import Auto3dxError, Catia, PartUpdateError
from auto_3dx.errors import ReferenceInUseError, TopologyQueryAmbiguousError
from auto_3dx.geometry.facts import CURVE_CIRCLE, SURFACE_CYLINDRICAL
from auto_3dx.geometry.part_design import (
    DIRECTION_AGAINST_SKETCH_NORMAL,
    DIRECTION_ALONG_SKETCH_NORMAL,
)
from auto_3dx.geometry.planes import GEOMETRICAL_SET_NAME

PART_ENV_VAR = "AUTO3DX_LIVE_PART"
PREFIX = "AUTO3DX_PHASE4_"
BASE_SKETCH, BASE_PAD = f"{PREFIX}BASE_SKETCH", f"{PREFIX}BASE_PAD"
BOSS_PLANE, BOSS_SKETCH, BOSS_PAD = f"{PREFIX}BOSS_PLANE", f"{PREFIX}BOSS_SKETCH", f"{PREFIX}BOSS_PAD"
BORE_SKETCH, BORE = f"{PREFIX}BORE_SKETCH", f"{PREFIX}BORE"
MOUNT_SKETCH, MOUNT, MOUNTS = f"{PREFIX}MOUNT_SKETCH", f"{PREFIX}MOUNT", f"{PREFIX}MOUNTS"
SLOT_SKETCH, SLOT = f"{PREFIX}SLOT_SKETCH", f"{PREFIX}SLOT"
TOOL_BODY, NOTCH = f"{PREFIX}TOOL", f"{PREFIX}NOTCH"
RIM_FILLET, CORNER_FILLET = f"{PREFIX}RIM_FILLET", f"{PREFIX}CORNER_FILLET"

BASE_LENGTH, BASE_WIDTH, BASE_HEIGHT = 80.0, 50.0, 10.0
BOSS_X, BOSS_RADIUS, BOSS_HEIGHT = 20.0, 12.0, 15.0
BORE_RADIUS = 6.0
MOUNT_Y, MOUNT_RADIUS = 18.0, 3.0
SLOT_X, SLOT_RADIUS, SLOT_DEPTH = -25.0, 4.0, 5.0
LOWERED_PLANE = 8.0
Z = (0.0, 0.0, 1.0)
BASELINE_FILE = pathlib.Path(__file__).with_suffix(".baseline.json")


def target_part():
    """Attaches and returns the active Part if it is the one named, or exits."""
    target = os.environ.get(PART_ENV_VAR, "").strip()
    if not target:
        sys.exit(f"Refusing to run: set {PART_ENV_VAR} to the disposable test Part.")
    catia = Catia.attach()
    part = catia.active_part()
    title = catia.active_window_title
    if target not in (part.name, title):
        sys.exit(f"Refusing to run: the active Part is {part.name!r} ({title!r}), not {target!r}.")
    return part


def observable_state(part) -> dict:
    """A comparable snapshot of everything this script could have changed."""
    summary = part.inspect.summary()
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
    }


def remove_own(part, plane_set_existed: bool = True) -> None:
    """Removes only what this script created, in dependency order."""
    for step in (
        lambda: part.part_design.get_pad(BOSS_PAD).set_height(BOSS_HEIGHT),
        lambda: part.part_design.remove_boolean(NOTCH, delete_consumed_body=True),
        lambda: part.part_design.remove_edge_fillet(CORNER_FILLET),
        lambda: part.part_design.remove_edge_fillet(RIM_FILLET),
        lambda: part.part_design.remove_pocket(SLOT),
        lambda: part.part_design.remove_circular_pattern(MOUNTS),
        lambda: part.part_design.remove_pocket(MOUNT),
        lambda: part.part_design.remove_pocket(BORE),
        lambda: part.part_design.remove_pad(BOSS_PAD),
        lambda: part.planes.remove(part.planes.get(BOSS_PLANE)),
        lambda: part.part_design.remove_pad(BASE_PAD),
    ):
        try:
            step()
        except Auto3dxError as error:
            print(f"  nothing to remove: {type(error).__name__}")
    for name in list(part.bodies.names()):
        if name.startswith(PREFIX):
            part.bodies.remove(name, delete_contents=True)
    for sketch in (SLOT_SKETCH, MOUNT_SKETCH, BORE_SKETCH, BOSS_SKETCH, BASE_SKETCH):
        try:
            part.sketches.remove(sketch)
        except Auto3dxError:
            pass
    sets = [s for s in part.inspect.geometrical_sets() if s.name == GEOMETRICAL_SET_NAME]
    if not plane_set_existed and sets and not sets[0].elements:
        part.planes.remove_geometrical_set()
    part.update()


def circle_pocket(part, sketch_name, name, x, y, radius, depth, direction):
    sketch = part.sketches.create(sketch_name, support="XY")
    with sketch.edit() as editor:
        editor.circle(x, y, radius)
    return part.part_design.create_pocket(name, sketch, depth, direction=direction)


def build(part) -> None:
    """The bracket, built entirely through the public API."""
    base = part.sketches.create(BASE_SKETCH, support="XY")
    with base.edit() as editor:
        editor.rectangle(
            BASE_LENGTH, BASE_WIDTH, origin_x=-BASE_LENGTH / 2, origin_y=-BASE_WIDTH / 2
        )
    part.part_design.create_pad(BASE_PAD, base, BASE_HEIGHT)
    part.update()

    plane = part.planes.create_offset(BOSS_PLANE, "XY", BASE_HEIGHT)
    part.update()
    boss = part.sketches.create(BOSS_SKETCH, support=plane)
    with boss.edit() as editor:
        editor.circle(BOSS_X, 0.0, BOSS_RADIUS)
    part.part_design.create_pad(BOSS_PAD, boss, BOSS_HEIGHT)
    part.update()

    # The bore is cut UP from XY through base and boss: an explicit direction, not a plane
    # on the far side.
    circle_pocket(part, BORE_SKETCH, BORE, BOSS_X, 0.0, BORE_RADIUS, 100.0,
                  DIRECTION_ALONG_SKETCH_NORMAL)
    mount = circle_pocket(part, MOUNT_SKETCH, MOUNT, 0.0, MOUNT_Y, MOUNT_RADIUS, 100.0,
                          DIRECTION_ALONG_SKETCH_NORMAL)
    part.update()
    part.part_design.create_circular_pattern(MOUNTS, mount, 2, 180.0)
    part.update()

    tool = part.bodies.create(TOOL_BODY)
    with part.work_in(tool):
        sketch = part.sketches.create(f"{TOOL_BODY}_SKETCH", support="XY")
        with sketch.edit() as editor:
            editor.rectangle(10.0, 10.0, origin_x=-BASE_LENGTH / 2, origin_y=-BASE_WIDTH / 2)
        part.part_design.create_pad(f"{TOOL_BODY}_PAD", sketch, 30.0)
    tool.update()
    part.part_design.create_boolean_remove(NOTCH, TOOL_BODY)
    part.update()


def check_classification(part) -> None:
    print("-- inspection classification")
    features = part.inspect.features()
    print("   ", [(f.name[len(PREFIX):], f.kind, f.supported) for f in features])
    unsupported = [f.name for f in features if not f.supported]
    assert not unsupported, f"reported as unsupported: {unsupported}"
    kinds = {f.kind for f in features}
    assert {"CircPattern", "Remove"} <= kinds, kinds


def boss_top(part):
    """The highest horizontal face: the top of the boss."""
    return (
        part.topology.faces(body="PartBody").query()
        .planar().normal_parallel(Z).extreme(Z).one()
    )


def bore_rim(part, z: float):
    """The bore's rim at height z: circular, radius 6, near the bore axis."""
    return (
        part.topology.edges(body="PartBody").query()
        .circular().radius_near(BORE_RADIUS, 0.01).nearest((BOSS_X, 0.0, z)).one()
    )


def check_selection(part) -> None:
    print("-- selection by geometry")
    faces = part.topology.faces(body="PartBody")
    horizontal = faces.query().planar().normal_parallel(Z)
    print(f"   horizontal faces: {horizontal.count()}")
    top = boss_top(part)
    print(f"   boss top: centre {top.geometry.center_mm}, area {top.geometry.area_mm2:.3f}")
    assert math.isclose(top.geometry.center_mm[2], BASE_HEIGHT + BOSS_HEIGHT, abs_tol=1e-6)
    expected = math.pi * (BOSS_RADIUS**2 - BORE_RADIUS**2)
    assert math.isclose(top.geometry.area_mm2, expected, rel_tol=1e-6)

    base_top = horizontal.nearest((0.0, 0.0, BASE_HEIGHT)).one()
    print(f"   base top: centre {base_top.geometry.center_mm}, "
          f"area {base_top.geometry.area_mm2:.3f}")
    assert math.isclose(base_top.geometry.center_mm[2], BASE_HEIGHT, abs_tol=1e-6)

    bore = faces.query().cylindrical().radius_near(BORE_RADIUS, 0.01).one()
    assert bore.geometry.surface_type == SURFACE_CYLINDRICAL
    mounts = faces.query().cylindrical().radius_near(MOUNT_RADIUS, 0.01)
    print(f"   bore wall radius {bore.geometry.radius_mm}, mounting holes {mounts.count()}")
    assert mounts.count() == 2, "the pattern made two mounting holes"
    try:
        mounts.one()
    except TopologyQueryAmbiguousError:
        print("   two equal mounting holes: one() refuses to choose between them")

    rim = bore_rim(part, BASE_HEIGHT + BOSS_HEIGHT)
    assert rim.geometry.curve_type == CURVE_CIRCLE
    print(f"   bore rim at the boss top: centre {rim.geometry.center_mm}")

    outer = (
        part.topology.edges(body="PartBody").query()
        .circular().radius_near(BOSS_RADIUS, 0.01)
        .nearest((BOSS_X, 0.0, BASE_HEIGHT + BOSS_HEIGHT)).one()
    )
    volume = part.measurement.measure().volume_mm3
    part.part_design.create_edge_fillet(RIM_FILLET, outer, 2.0)
    part.update()
    after = part.measurement.measure().volume_mm3
    print(f"   filleted the boss's outer top rim: volume {volume:.3f} -> {after:.3f}")
    assert after < volume


def check_direction(part) -> None:
    print("-- pocket direction")
    volume = part.measurement.measure().volume_mm3
    slot = circle_pocket(part, SLOT_SKETCH, SLOT, SLOT_X, 0.0, SLOT_RADIUS, SLOT_DEPTH, None)
    part.update()
    print(f"   default direction {slot.direction}: removed "
          f"{volume - part.measurement.measure().volume_mm3:.3f}")
    assert slot.direction == DIRECTION_AGAINST_SKETCH_NORMAL
    assert math.isclose(part.measurement.measure().volume_mm3, volume, rel_tol=1e-12)
    slot.reverse_direction()
    part.update()
    removed = volume - part.measurement.measure().volume_mm3
    print(f"   reversed to {slot.direction}: removed {removed:.3f}")
    assert math.isclose(removed, math.pi * SLOT_RADIUS**2 * SLOT_DEPTH, rel_tol=1e-9)


def check_plane(part) -> None:
    print("-- reference plane edit and protection")
    plane = part.planes.get(BOSS_PLANE)
    plane.set_offset(LOWERED_PLANE)
    part.update()
    top = boss_top(part)
    print(f"   plane {plane.offset} -> boss top now at z={top.geometry.center_mm[2]}")
    assert math.isclose(top.geometry.center_mm[2], LOWERED_PLANE + BOSS_HEIGHT, abs_tol=1e-6)

    print(f"   sketches on the plane: {part.planes.dependents(plane)}")
    try:
        part.planes.remove(plane)
    except ReferenceInUseError as error:
        print("   deleting it is refused:", str(error)[:90])
    else:
        raise AssertionError("an in-use plane must not be deleted")
    assert BOSS_PLANE in part.planes.names()
    assert BOSS_SKETCH in part.sketches.names()
    assert part.is_up_to_date()


def check_diagnostics(part) -> None:
    print("-- update diagnostics")
    boss = part.part_design.get_pad(BOSS_PAD)
    previous = boss.height
    boss.set_height(1.0)
    try:
        part.update()
    except PartUpdateError as error:
        issues = error.issues
        print("   update failed; CATIA reports:",
              [(i.name[len(PREFIX):], i.up_to_date, i.active) for i in issues])
        assert any(not issue.up_to_date for issue in issues)
    else:
        raise AssertionError("a 1 mm boss under a 2 mm rim fillet should not rebuild")
    boss.set_height(previous)
    part.update()
    assert part.is_up_to_date()
    assert part.inspect.update_issues() == ()
    print("   rolled back, rebuilt, no issues left")


def create() -> None:
    part = target_part()
    baseline = observable_state(part)
    BASELINE_FILE.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    print("baseline:", baseline)
    if baseline["features"] or baseline["sketches"] or baseline["bodies"] != ["PartBody"]:
        sys.exit("Refusing to run: this Part is not the expected blank test Part.")
    plane_set_existed = GEOMETRICAL_SET_NAME in baseline["geometrical_sets"]
    try:
        build(part)
        check_classification(part)
        check_selection(part)
        check_direction(part)
        check_plane(part)
        check_diagnostics(part)
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

    check_classification(part)
    top = boss_top(part)
    print(f"-- boss top rediscovered at z={top.geometry.center_mm[2]}")
    assert math.isclose(top.geometry.center_mm[2], LOWERED_PLANE + BOSS_HEIGHT, abs_tol=1e-6)
    rim = bore_rim(part, LOWERED_PLANE + BOSS_HEIGHT)
    print(f"   bore rim rediscovered, radius {rim.geometry.radius_mm}")
    assert part.planes.get(BOSS_PLANE).offset == LOWERED_PLANE
    assert part.part_design.get_pocket(BORE).direction == DIRECTION_ALONG_SKETCH_NORMAL
    assert part.part_design.get_pocket(SLOT).direction == DIRECTION_ALONG_SKETCH_NORMAL
    print("   plane offset and pocket directions read back from the model")

    corner = (
        part.topology.edges(body="PartBody").query()
        .lines().parallel(Z)
        .nearest((BASE_LENGTH / 2, BASE_WIDTH / 2, BASE_HEIGHT / 2)).one()
    )
    volume = part.measurement.measure().volume_mm3
    part.part_design.create_edge_fillet(CORNER_FILLET, corner, 3.0)
    part.update()
    print(f"-- filleted the (+X, +Y) corner found by geometry: volume {volume:.3f} -> "
          f"{part.measurement.measure().volume_mm3:.3f}")
    assert part.measurement.measure().volume_mm3 < volume

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
