"""Acceptance: a Multi-sections Solid survives the Python process that created it.

Run in two separate processes against a disposable test Part, named explicitly:

    $env:AUTO3DX_LIVE_PART = "<name of a disposable test Part>"
    python scripts/acceptance/multi_section_solid_lifecycle.py create [rectangle|circle]
    python scripts/acceptance/multi_section_solid_lifecycle.py verify-and-remove

The section shape defaults to `rectangle`. Two rectangles of different proportions
failed `Part.Update()` both in probe 40 and through this script (2026-09-17), while a
NACA spline+line pair built, so `circle` gives a smallest case with no corners.

`create` records the baseline, builds a closed rectangle on XY, an offset plane (with
the update CATIA needs before a sketch can go on it), a closed rectangle on that plane
and a Multi-sections Solid between them, checks it, and exits WITHOUT cleaning up.
`verify-and-remove` attaches fresh, finds the feature by name, checks it and its
sections, removes the feature, the section sketches and the one plane `create` made,
updates, and compares the result with the recorded baseline.

Public auto_3dx API only: no raw COM, no save, no propagate, no export. The Part is
chosen by name, never "whatever is active", and the script refuses to run without it.
"""

import json
import math
import os
import pathlib
import sys

from auto_3dx import Catia
from auto_3dx.errors import (
    FeatureNotFoundError,
    PartUpdateError,
    PlaneNotFoundError,
    SketchNotFoundError,
)

PART_ENV_VAR = "AUTO3DX_LIVE_PART"
ROOT_SKETCH = "AUTO3DX_ACC_MSS_ROOT"
TIP_PLANE = "AUTO3DX_ACC_MSS_TIP_PLANE"
TIP_SKETCH = "AUTO3DX_ACC_MSS_TIP"
SOLID_NAME = "AUTO3DX_ACC_MSS_SOLID"
ROOT_WIDTH, ROOT_HEIGHT = 40.0, 20.0
TIP_WIDTH, TIP_HEIGHT = 30.0, 15.0
ROOT_RADIUS, TIP_RADIUS = 20.0, 12.0
SHAPES = ("rectangle", "circle")
TIP_OFFSET = 30.0
BASELINE_FILE = pathlib.Path(__file__).with_suffix(".baseline.json")


def target_part():
    """Attaches and returns the Part named by AUTO3DX_LIVE_PART, or exits."""
    name = os.environ.get(PART_ENV_VAR, "").strip()
    if not name:
        sys.exit(f"Refusing to run: set {PART_ENV_VAR} to the name of a disposable test Part.")
    return Catia.attach().part_named(name)


def observable_state(part) -> dict:
    """The structure this acceptance promises to restore."""
    summary = part.inspect.summary()
    mass = part.measurement.measure()
    return {
        "up_to_date": summary.up_to_date,
        "features": [[f.name, f.kind] for f in summary.features],
        "sketches": list(summary.sketches),
        "geometrical_sets": [
            [s.name, [[e.name, e.kind] for e in s.elements]] for s in summary.geometrical_sets
        ],
        "topology": [summary.topology.edges, summary.topology.faces] if summary.topology else None,
        "volume_mm3": round(mass.volume_mm3, 3),
        "area_mm2": round(mass.area_mm2, 3),
    }


def remove_own(part) -> None:
    """Removes exactly what this acceptance made, and nothing else, then rebuilds."""
    try:
        part.part_design.remove_multi_section_solid(SOLID_NAME)
    except FeatureNotFoundError:
        pass
    for name in (TIP_SKETCH, ROOT_SKETCH):
        try:
            part.sketches.remove(name)
        except SketchNotFoundError:
            print(f"sketch {name!r} is already gone (removed with the feature)")
    try:
        part.planes.remove(part.planes.get(TIP_PLANE))
    except PlaneNotFoundError:
        pass
    try:
        part.update()
    except PartUpdateError as error:
        print("update after cleanup FAILED:", error)
        raise


def draw_section(sketch, shape: str, is_root: bool) -> None:
    """Draws one closed section profile of the chosen shape."""
    with sketch.edit() as editor:
        if shape == "circle":
            editor.circle(0.0, 0.0, ROOT_RADIUS if is_root else TIP_RADIUS)
        else:
            width, height = (ROOT_WIDTH, ROOT_HEIGHT) if is_root else (TIP_WIDTH, TIP_HEIGHT)
            editor.rectangle(width, height)


def create(shape: str = "rectangle") -> None:
    part = target_part()
    baseline = observable_state(part)
    BASELINE_FILE.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    print("baseline:", baseline)
    try:
        build(part, baseline, shape)
    except BaseException:
        print("create FAILED; removing only what this run made")
        remove_own(part)
        print("state after cleanup:", observable_state(part))
        raise


def build(part, baseline: dict, shape: str) -> None:
    print("section shape:", shape)
    root = part.sketches.create(ROOT_SKETCH, support="XY")
    draw_section(root, shape, is_root=True)
    part.update()
    plane = part.planes.create_offset(TIP_PLANE, "XY", TIP_OFFSET)
    part.update()
    tip = part.sketches.create(TIP_SKETCH, support=plane)
    draw_section(tip, shape, is_root=False)
    part.update()

    solid = part.part_design.create_multi_section_solid(SOLID_NAME, sections=[root, tip])
    part.update()

    state = observable_state(part)
    print("feature  :", solid.name)
    print("kind     :", [f for f in state["features"] if f[0] == SOLID_NAME])
    print("sections :", solid.section_names())
    print("state    :", state)
    assert state["up_to_date"], "the Part did not rebuild"
    assert [SOLID_NAME, "Loft"] in state["features"]
    assert state["topology"] != baseline["topology"], "topology did not change"
    assert math.isfinite(state["volume_mm3"])
    assert state["volume_mm3"] > baseline["volume_mm3"], "no material was added"
    print("create: OK, exiting without cleanup")


def verify_and_remove() -> None:
    part = target_part()
    baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))

    solid = part.part_design.get_multi_section_solid(SOLID_NAME)
    print("rediscovered:", solid, "sections:", solid.section_names())
    assert solid.section_names() == [ROOT_SKETCH, TIP_SKETCH]
    assert part.is_up_to_date()

    remove_own(part)

    try:
        part.part_design.get_multi_section_solid(SOLID_NAME)
    except FeatureNotFoundError:
        print("feature is gone")
    else:
        raise AssertionError("the feature is still in the model")

    restored = observable_state(part)
    print("restored:", restored)
    if restored != baseline:
        for key in baseline:
            if restored.get(key) != baseline[key]:
                print(f"  DIFFERS {key}: {baseline[key]!r} -> {restored.get(key)!r}")
        raise AssertionError("the Part did not return to its baseline")
    BASELINE_FILE.unlink()
    print("verify-and-remove: OK, baseline restored exactly")


if __name__ == "__main__":
    usage = f"usage: {sys.argv[0]} create [{'|'.join(SHAPES)}] | verify-and-remove"
    if len(sys.argv) >= 2 and sys.argv[1] == "create" and len(sys.argv) <= 3:
        chosen = sys.argv[2] if len(sys.argv) == 3 else "rectangle"
        if chosen not in SHAPES:
            sys.exit(usage)
        create(chosen)
    elif sys.argv[1:] == ["verify-and-remove"]:
        verify_and_remove()
    else:
        sys.exit(usage)
