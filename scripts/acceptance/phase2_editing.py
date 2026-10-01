"""Acceptance: editing an existing model through the public API, across two processes.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python scripts/acceptance/phase2_editing.py create
    python scripts/acceptance/phase2_editing.py verify-and-remove

`create` builds a sketch, a pad and a fillet, then proves, in order: a sketch element is
found again by its CATIA name and accepted by a NEW constraint; an existing feature's
dimensions are edited through public setters, rebuilt, measured, seen by a fresh wrapper
and rolled back; `work_at(feature)` puts an existing feature in work, a feature created
there lands immediately after it, and the previous In-Work Object comes back -- including
when the block raises; and a formula that reads a user parameter blocks that parameter's
removal without CATIA ever writing a `deleted_*` orphan. It exits without cleaning up.

`verify-and-remove` attaches in a new interpreter that drew none of it and repeats the
four capabilities against the model alone, then removes every `AUTO3DX_PHASE2_*` object
and compares the Part with the baseline.

Public auto_3dx API only: no raw COM, no `part.com_object`, no private members, no save,
no propagate, no export. Deletion and topology need the Part to be active, so the script
refuses any other Part.
"""

import json
import math
import os
import pathlib
import sys

from auto_3dx import Auto3dxError, Catia
from auto_3dx.errors import (
    ParameterInUseError,
    ParameterTypeError,
    SketchElementNotFoundError,
)

PART_ENV_VAR = "AUTO3DX_LIVE_PART"
PREFIX = "AUTO3DX_PHASE2_"
SKETCH, PAD, FILLET = f"{PREFIX}SKETCH", f"{PREFIX}PAD", f"{PREFIX}FILLET"
GUIDE_SKETCH = f"{PREFIX}GUIDE_SKETCH"
INSERT_SKETCH, INSERT_PAD = f"{PREFIX}INSERT_SKETCH", f"{PREFIX}INSERT_PAD"
PARAMETER, FORMULA = f"{PREFIX}PARAM", f"{PREFIX}FORMULA"
SIDE, HEIGHT = 40.0, 30.0
FILLET_RADIUS, WIDER_RADIUS = 4.0, 8.0
INSERT_SIDE, INSERT_HEIGHT, INSERT_X = 10.0, 6.0, 120.0
BASELINE_FILE = pathlib.Path(__file__).with_suffix(".baseline.json")


def target_part():
    """Attaches and returns the active Part if it is the one named, or exits."""
    target = os.environ.get(PART_ENV_VAR, "").strip()
    if not target:
        sys.exit(f"Refusing to run: set {PART_ENV_VAR} to the disposable test Part.")
    catia = Catia.attach()
    part = catia.active_part()
    caption = catia.active_window_title
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
            volumes[body.name] = None
    return {
        "up_to_date": summary.up_to_date,
        "features": [[f.name, f.kind] for f in summary.features],
        "sketches": list(summary.sketches),
        "parameters": [p.short_name for p in summary.parameters],
        "formulas": part.formulas.names(),
        "bodies": [b.name for b in summary.bodies],
        "geometrical_sets": [s.name for s in summary.geometrical_sets],
        "in_work_object": [summary.in_work_object.name, summary.in_work_object.kind]
        if summary.in_work_object
        else None,
        "volumes": volumes,
    }


def solid_edge(part, feature_name: str):
    """An edge of one feature: a body's edges include its sketches' wire edges."""
    edges = [
        edge
        for edge in part.topology.edges(body="PartBody")
        if edge.owner_feature_name == feature_name
    ]
    if not edges:
        raise AssertionError(f"no edge owned by {feature_name!r}")
    return edges[0]


def remove_own(part) -> None:
    """Removes only what this script created, in dependency order."""
    for step in (
        lambda: part.formulas.remove(FORMULA),
        lambda: part.parameters.remove(PARAMETER),
        lambda: part.part_design.remove_edge_fillet(FILLET),
        lambda: part.part_design.remove_pad(INSERT_PAD),
        lambda: part.sketches.remove(INSERT_SKETCH),
        lambda: part.part_design.remove_pad(PAD),
        lambda: part.sketches.remove(SKETCH),
        lambda: part.sketches.remove(GUIDE_SKETCH),
    ):
        try:
            step()
        except Auto3dxError as error:
            print(f"  nothing to remove: {type(error).__name__}")
    part.update()


def check_element_rediscovery(part) -> None:
    """A sketch element is found by name and accepted by a new constraint."""
    print("-- sketch element rediscovery")
    fresh_sketch = Catia.attach().active_part().sketches.get(GUIDE_SKETCH)
    print("   element names in the model:", fresh_sketch.element_names())
    first = fresh_sketch.get_element("Line.1")
    second = fresh_sketch.get_element("Line.2")
    print(f"   rediscovered {first.name!r} ({first.kind}) and {second.name!r}")
    assert first.kind == "Line2D"
    circle = fresh_sketch.get_element("Circle.1")
    print(f"   {circle.name!r} radius = {circle.radius}")
    try:
        fresh_sketch.get_element("Line.99")
    except SketchElementNotFoundError as error:
        print("   a missing name is reported:", str(error)[:70])
    else:
        raise AssertionError("a missing element name should be refused")
    try:
        circle.radius and first.radius
    except ParameterTypeError:
        print("   a line has no radius, and says so")
    before = fresh_sketch.constraints.count
    with fresh_sketch.edit() as editor:
        constraint = editor.parallel(first, second)
    part.update()
    after = fresh_sketch.constraints.count
    print(f"   constraint {constraint.name!r} from rediscovered elements, count "
          f"{before} -> {after}")
    # The point is that CATIA accepted the rediscovered elements and named the result.
    # The count only grows the first time: asking for the same parallelism again leaves
    # the existing one in place rather than adding a duplicate (live, second process).
    assert constraint.name
    assert after >= max(before, 1)
    assert part.is_up_to_date()


def check_feature_editing(part) -> None:
    """An existing fillet's radius is edited, rebuilt, measured, seen fresh, rolled back."""
    print("-- existing feature editing")
    fillet = part.part_design.get_edge_fillet(FILLET)
    pad = part.part_design.get_pad(PAD)
    original_radius, original_height = fillet.radius, pad.height
    volume_before = part.measurement.measure().volume_mm3
    print(f"   radius={original_radius} pad height={original_height} volume={volume_before}")

    fillet.set_radius(WIDER_RADIUS)
    assert fillet.radius == WIDER_RADIUS
    # A setter never rebuilds: until part.update() runs, either the Part is out of date
    # or the geometry is unchanged. Measuring an out-of-date solid is refused (Phase 1).
    try:
        unrebuilt = part.measurement.measure().volume_mm3
    except Auto3dxError as error:
        print("   before update, measuring is refused:", type(error).__name__)
    else:
        assert math.isclose(unrebuilt, volume_before, rel_tol=1e-9), (
            "the setter rebuilt the model on its own"
        )
        print("   before update, the geometry is unchanged:", unrebuilt)
    part.update()
    volume_after = part.measurement.measure().volume_mm3
    print(f"   radius -> {fillet.radius}, volume -> {volume_after}")
    assert volume_after < volume_before, "a bigger fillet removes more material"

    fresh = Catia.attach().active_part().part_design.get_edge_fillet(FILLET)
    assert fresh.radius == WIDER_RADIUS
    print("   a fresh wrapper reads", fresh.radius)

    fillet.set_radius(original_radius)
    part.update()
    healed = part.measurement.measure().volume_mm3
    assert math.isclose(healed, volume_before, rel_tol=1e-9)
    print(f"   rolled back to {fillet.radius}, volume {healed}")


def check_work_at(part) -> None:
    """An existing feature becomes the work position, and the tree shows where it landed."""
    print("-- work_at(feature)")
    before_tree = [feature.name for feature in part.inspect.features()]
    before_iwo = part.inspect.in_work_object()
    print("   tree before:", before_tree)
    print("   In-Work Object before:", before_iwo.name if before_iwo else None)

    pad = part.part_design.get_pad(PAD)
    # In a second process the previous run's insertion is still there; it is ours, so it
    # is removed and rebuilt rather than skipped.
    for step in (
        lambda: part.part_design.remove_pad(INSERT_PAD),
        lambda: part.sketches.remove(INSERT_SKETCH),
    ):
        try:
            step()
        except Auto3dxError:
            pass
    part.update()
    before_tree = [feature.name for feature in part.inspect.features()]
    sketch = part.sketches.create(INSERT_SKETCH, support="XY")
    with sketch.edit() as editor:
        editor.rectangle(INSERT_SIDE, INSERT_SIDE, origin_x=INSERT_X)

    with part.work_at(pad):
        inside = part.inspect.in_work_object()
        print("   In-Work Object inside:", inside.name if inside else None)
        assert inside is not None and inside.name == PAD
        part.part_design.create_pad(INSERT_PAD, sketch, INSERT_HEIGHT)
    part.update()

    after_iwo = part.inspect.in_work_object()
    after_tree = [feature.name for feature in part.inspect.features()]
    print("   tree after:", after_tree)
    print("   In-Work Object after:", after_iwo.name if after_iwo else None)
    assert after_iwo is not None and before_iwo is not None
    assert after_iwo.name == before_iwo.name, "the previous In-Work Object must come back"
    assert after_tree.index(INSERT_PAD) == after_tree.index(PAD) + 1, (
        "CATIA inserts the new feature immediately after the In-Work feature"
    )
    assert part.is_up_to_date()

    try:
        with part.work_at(pad):
            raise RuntimeError("deliberate failure inside work_at")
    except RuntimeError:
        restored = part.inspect.in_work_object()
        assert restored is not None and restored.name == after_iwo.name
        print("   In-Work Object restored after an exception:", restored.name)

    try:
        with part.work_at(part.bodies.main):
            pass
    except ParameterTypeError:
        print("   a body is refused by work_at: work_in(body) is the right call")
    else:
        raise AssertionError("work_at must not accept a body")


def check_dependency_guard(part, expect_existing: bool = False) -> None:
    """A formula that reads a parameter blocks its removal."""
    print("-- parameter dependency guard")
    if not expect_existing:
        part.parameters.create_length(PARAMETER, 12.0)
        source = part.formulas.relation_name(part.parameters.get(PARAMETER))
        part.formulas.create(FORMULA, part.part_design.get_pad(PAD).depth_parameter(),
                             f"{source} * 2")
        part.update()

    formula = part.formulas.get(FORMULA)
    print(f"   formula {formula.name!r} body {formula.body!r} inputs {formula.inputs()}")
    dependents = part.parameters.dependents(PARAMETER)
    print("   dependents of the parameter:", [item.name for item in dependents])
    assert [item.name for item in dependents] == [FORMULA]

    try:
        part.parameters.remove(PARAMETER)
    except ParameterInUseError as error:
        print("   removal refused:", str(error)[:100])
    else:
        raise AssertionError("removing a parameter a formula reads must be refused")

    assert PARAMETER in [p.short_name for p in part.inspect.parameters()]
    assert FORMULA in part.formulas.names()
    assert part.formulas.get(FORMULA).body == formula.body
    assert "deleted_" not in part.formulas.get(FORMULA).body
    assert part.is_up_to_date()
    print("   parameter, formula body and rebuild state all intact")


def create() -> None:
    part = target_part()
    baseline = observable_state(part)
    BASELINE_FILE.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    print("baseline:", baseline)
    if baseline["features"] or baseline["sketches"] or baseline["bodies"] != ["PartBody"]:
        sys.exit("Refusing to run: this Part is not the expected blank test Part.")

    try:
        # A sketch whose elements are the ones rediscovered later, kept out of any feature.
        guide = part.sketches.create(GUIDE_SKETCH, support="XY")
        with guide.edit() as editor:
            editor.line(-90.0, -90.0, -50.0, -90.0)
            editor.line(-90.0, -70.0, -50.0, -70.0)
            editor.circle(-70.0, -40.0, 5.0)
        part.update()
        del guide  # the Python objects that drew the geometry are gone from here on

        sketch = part.sketches.create(SKETCH, support="XY")
        with sketch.edit() as editor:
            editor.rectangle(SIDE, SIDE)
        part.part_design.create_pad(PAD, sketch, HEIGHT)
        part.update()
        part.part_design.create_edge_fillet(FILLET, solid_edge(part, PAD), FILLET_RADIUS)
        part.update()

        check_element_rediscovery(part)
        check_feature_editing(part)
        check_work_at(part)
        check_dependency_guard(part)

        print("create: OK, exiting without cleanup")
    except BaseException:
        print("create FAILED; removing only what this run made")
        remove_own(part)
        raise


def verify_and_remove() -> None:
    part = target_part()
    baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    print("this process drew none of the geometry below")

    check_element_rediscovery(part)
    check_feature_editing(part)
    check_work_at(part)
    check_dependency_guard(part, expect_existing=True)

    # The lifecycle the guard is protecting: remove the formula, then the parameter.
    part.formulas.remove(FORMULA)
    assert part.parameters.dependents(PARAMETER) == []
    part.parameters.remove(PARAMETER)
    assert PARAMETER not in [p.short_name for p in part.inspect.parameters()]
    print("   with the formula gone, the parameter removes normally")

    remove_own(part)
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
