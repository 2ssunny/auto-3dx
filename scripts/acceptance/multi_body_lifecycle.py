"""Acceptance: two bodies with their own features survive the process that made them.

Run in two separate processes against a disposable test Part, named explicitly by its
`Part.Name` or by its exact 3DEXPERIENCE title (the active window caption):

    $env:AUTO3DX_LIVE_PART = "AUTO3DX_MULTIBODY_TEST"
    python scripts/acceptance/multi_body_lifecycle.py create
    python scripts/acceptance/multi_body_lifecycle.py verify-and-remove

`create` records a baseline, builds `AUTO3DX_BODY_A` and `AUTO3DX_BODY_B`, each with a
sketch and a pad made inside `part.work_in(body)`, checks that the In-Work Object came
back after each block, that each pad is in its own body and the Part is up to date,
hides and shows body A, and exits WITHOUT cleaning up. `verify-and-remove` attaches fresh,
finds both bodies by name, checks their contents, hides and shows them again, removes
only these two bodies (with their contents), and compares the Part with the baseline.

Public auto_3dx API only: no raw COM, no save, no propagate, no export. Deletion and
visibility need the Part to be active, so the script refuses any other.
"""

import json
import math
import os
import pathlib
import sys

from auto_3dx import Auto3dxError, Catia
from auto_3dx.errors import BodyNotFoundError

PART_ENV_VAR = "AUTO3DX_LIVE_PART"
BODY_A, BODY_B = "AUTO3DX_BODY_A", "AUTO3DX_BODY_B"
A_SIDE, A_HEIGHT = 20.0, 10.0
B_SIDE, B_HEIGHT, B_X = 30.0, 12.0, 100.0
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
    return part, catia


def observable_state(part, catia) -> dict:
    summary = part.inspect.summary()
    volumes = {}
    for body in part.bodies.list():
        try:
            volumes[body.name] = round(part.measurement.measure(body).volume_mm3, 3)
        except Auto3dxError:
            volumes[body.name] = None  # empty or hidden bodies cannot be measured
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
        "volumes": volumes,
    }


def build_body(part, name: str, side: float, height: float, origin_x: float) -> None:
    body = part.bodies.create(name)
    before = part.inspect.in_work_object()
    with part.work_in(body):
        sketch = part.sketches.create(f"{name}_SKETCH", support="XY")
        with sketch.edit() as editor:
            editor.rectangle(side, side, origin_x=origin_x)
        part.part_design.create_pad(f"{name}_PAD", sketch, height)
    assert part.inspect.in_work_object() == before, (
        "work_in did not restore the In-Work Object"
    )
    part.update()


def remove_own(part) -> None:
    for name in (BODY_B, BODY_A):
        try:
            part.bodies.remove(name, delete_contents=True)
        except BodyNotFoundError:
            pass
    part.update()


def create() -> None:
    part, catia = target_part()
    baseline = observable_state(part, catia)
    BASELINE_FILE.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    print("baseline:", baseline)
    try:
        build_body(part, BODY_A, A_SIDE, A_HEIGHT, 0.0)
        build_body(part, BODY_B, B_SIDE, B_HEIGHT, B_X)
        body_a, body_b = part.bodies.get(BODY_A), part.bodies.get(BODY_B)
        assert [f.name for f in body_a.features] == [f"{BODY_A}_PAD"]
        assert [f.name for f in body_b.features] == [f"{BODY_B}_PAD"]
        assert part.is_up_to_date()
        body_a.hide()
        assert body_a.is_visible is False and body_b.is_visible is True
        body_a.show()
        assert body_a.is_visible is True
        state = observable_state(part, catia)
        print("state:", state)
        print("create: OK, exiting without cleanup")
    except BaseException:
        print("create FAILED; removing only what this run made")
        remove_own(part)
        raise


def verify_and_remove() -> None:
    part, catia = target_part()
    baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))

    body_a, body_b = part.bodies.get(BODY_A), part.bodies.get(BODY_B)
    print(
        "rediscovered:", body_a, [f.name for f in body_a.features], body_a.sketch_names
    )
    print(
        "rediscovered:", body_b, [f.name for f in body_b.features], body_b.sketch_names
    )
    assert not body_a.is_main and not body_b.is_main
    assert [(f.name, f.kind) for f in body_a.features] == [(f"{BODY_A}_PAD", "Pad")]
    assert [(f.name, f.kind) for f in body_b.features] == [(f"{BODY_B}_PAD", "Pad")]
    assert body_a.sketch_names == (f"{BODY_A}_SKETCH",)
    volume_a = part.measurement.measure(body_a).volume_mm3
    assert math.isclose(volume_a, A_SIDE * A_SIDE * A_HEIGHT, rel_tol=1e-6), volume_a
    assert part.is_up_to_date()
    for body in (body_a, body_b):
        body.hide()
        assert body.is_visible is False
        body.show()
        assert body.is_visible is True
    print("show/hide again: OK")

    remove_own(part)
    restored = observable_state(part, catia)
    print("restored:", restored)
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
