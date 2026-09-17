"""Acceptance: a NACA wing as a Multi-sections Solid, through the public API only.

Root NACA 2415 (chord 150 mm) on XY, tip NACA 2412 (chord 100 mm) on a +300 mm offset
plane, joined by `part.part_design.create_multi_section_solid`. Run the phases in
separate processes against a disposable test Part, named explicitly:

    $env:AUTO3DX_LIVE_PART = "<name of a disposable test Part>"
    python scripts/acceptance/naca_wing_multi_section_solid.py create
    python scripts/acceptance/naca_wing_multi_section_solid.py verify
    python scripts/acceptance/naca_wing_multi_section_solid.py remove

Each profile is ONE closed spline: from the sharp trailing edge along the upper surface
to the leading edge and back along the lower surface to the same trailing-edge point,
49 control points, no line and no constraints. That is exactly how the raw wing that
built was made (read back 2026-09-17). An open trailing edge closed by a separate line
-- two corners per section -- FAILED `Part.Update()` through this API, like two
rectangles did, while corner-free sections (circles, this closed spline) built.

The acceptance objects are prefixed `AUTO3DX_ACC_WING_` and the whole wing is shifted
`LEADING_EDGE_X_MM` along X, so it can live beside a wing someone already built in the
same Part without sharing names or merging into it. Only these objects are removed.

Public auto_3dx API only: no raw COM, no save, no propagate, no export.
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
ROOT_SKETCH = "AUTO3DX_ACC_WING_ROOT_NACA2415"
TIP_PLANE = "AUTO3DX_ACC_WING_TIP_PLANE"
TIP_SKETCH = "AUTO3DX_ACC_WING_TIP_NACA2412"
SOLID_NAME = "AUTO3DX_ACC_WING_SOLID_LOFT"
LEADING_EDGE_X_MM = 400.0
ROOT_PROFILE, ROOT_CHORD_MM = "2415", 150.0
TIP_PROFILE, TIP_CHORD_MM = "2412", 100.0
SPAN_MM = 300.0
POINTS_PER_SURFACE = 25  # 25 + 25 sharing the leading edge = 49 control points
BASELINE_FILE = pathlib.Path(__file__).with_suffix(".baseline.json")

# NACA four-digit thickness polynomial, closed (sharp) trailing edge form: the
# coefficients sum to zero, so the thickness is zero at x = 1.
_A0, _A1, _A2, _A3, _A4 = 0.2969, -0.1260, -0.3516, 0.2843, -0.1036
_THICKNESS_SCALE = 5.0


def naca_surfaces(code: str, chord: float) -> "tuple[list, list]":
    """Returns (upper, lower) surface points from leading to trailing edge, in mm."""
    camber = int(code[0]) / 100.0
    camber_position = int(code[1]) / 10.0
    thickness = int(code[2:]) / 100.0
    upper, lower = [], []
    for index in range(POINTS_PER_SURFACE):
        beta = math.pi * index / (POINTS_PER_SURFACE - 1)
        x = 0.5 * (1.0 - math.cos(beta))  # cosine spacing: dense at both edges
        half = _THICKNESS_SCALE * thickness * (
            _A0 * math.sqrt(x) + _A1 * x + _A2 * x**2 + _A3 * x**3 + _A4 * x**4
        )
        if camber and x < camber_position:
            yc = camber / camber_position**2 * (2 * camber_position * x - x**2)
            slope = 2 * camber / camber_position**2 * (camber_position - x)
        elif camber:
            yc = camber / (1 - camber_position) ** 2 * (
                1 - 2 * camber_position + 2 * camber_position * x - x**2
            )
            slope = 2 * camber / (1 - camber_position) ** 2 * (camber_position - x)
        else:
            yc, slope = 0.0, 0.0
        theta = math.atan(slope)
        upper.append((chord * (x - half * math.sin(theta)), chord * (yc + half * math.cos(theta))))
        lower.append((chord * (x + half * math.sin(theta)), chord * (yc - half * math.cos(theta))))
    return upper, lower


def airfoil_points(code: str, chord: float) -> "list[tuple[float, float]]":
    """One closed loop of control points: TE -> upper -> LE -> lower -> the same TE."""
    upper, lower = naca_surfaces(code, chord)
    around = list(reversed(upper)) + lower[1:]
    # Snap both ends onto the one sharp trailing-edge point, so the spline is closed
    # exactly rather than to within floating-point noise.
    around[0] = around[-1] = (chord, 0.0)
    return [(x + LEADING_EDGE_X_MM, y) for x, y in around]


def draw_airfoil(sketch, code: str, chord: float) -> None:
    """Draws one airfoil as a single closed spline."""
    with sketch.edit() as editor:
        editor.spline(airfoil_points(code, chord))


def target_part():
    """Attaches and returns the Part named by AUTO3DX_LIVE_PART, or exits."""
    name = os.environ.get(PART_ENV_VAR, "").strip()
    if not name:
        sys.exit(f"Refusing to run: set {PART_ENV_VAR} to the name of a disposable test Part.")
    return Catia.attach().part_named(name)


def observable_state(part) -> dict:
    summary = part.inspect.summary()
    mass = part.measurement.measure()
    return {
        "up_to_date": summary.up_to_date,
        "features": [[f.name, f.kind] for f in summary.features],
        "sketches": list(summary.sketches),
        "planes": part.planes.names(),
        "topology": [summary.topology.edges, summary.topology.faces] if summary.topology else None,
        "volume_mm3": round(mass.volume_mm3, 3),
        "area_mm2": round(mass.area_mm2, 3),
    }


def remove_own(part) -> None:
    """Removes exactly what this acceptance made, and nothing else, then rebuilds."""
    try:
        part.part_design.remove_multi_section_solid(SOLID_NAME)
    except FeatureNotFoundError:
        print("wing is not there")
    for name in (TIP_SKETCH, ROOT_SKETCH):
        try:
            part.sketches.remove(name)
        except SketchNotFoundError:
            print(f"sketch {name!r} is already gone (removed with the wing)")
    try:
        part.planes.remove(part.planes.get(TIP_PLANE))
    except PlaneNotFoundError:
        pass
    try:
        part.update()
    except PartUpdateError as error:
        print("update after cleanup FAILED:", error)
        raise


def create() -> None:
    part = target_part()
    baseline = observable_state(part)
    BASELINE_FILE.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    print("baseline:", baseline)
    try:
        build(part)
    except BaseException:
        print("create FAILED; removing only what this run made")
        remove_own(part)
        print("state after cleanup:", observable_state(part))
        raise


def build(part) -> None:
    root = part.sketches.create(ROOT_SKETCH, support="XY")
    draw_airfoil(root, ROOT_PROFILE, ROOT_CHORD_MM)
    part.update()
    plane = part.planes.create_offset(TIP_PLANE, "XY", SPAN_MM)
    part.update()
    tip = part.sketches.create(TIP_SKETCH, support=plane)
    draw_airfoil(tip, TIP_PROFILE, TIP_CHORD_MM)
    part.update()

    wing = part.part_design.create_multi_section_solid(SOLID_NAME, sections=[root, tip])
    part.update()
    print("wing:", wing, "sections:", wing.section_names())
    print("state:", observable_state(part))
    print("create: done, exiting without cleanup")


def verify() -> None:
    part = target_part()
    baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))

    root = part.sketches.get(ROOT_SKETCH)
    tip_plane = part.planes.get(TIP_PLANE)
    tip = part.sketches.get(TIP_SKETCH)
    wing = part.part_design.get_multi_section_solid(SOLID_NAME)
    summary = part.inspect.summary()
    mass = part.measurement.measure()

    print("root sketch   :", root.name, "support:", root.support())
    print("tip plane     :", tip_plane.name, "offset:", tip_plane.offset)
    print("tip sketch    :", tip.name, "support:", tip.support())
    print("wing          :", wing.name, "sections:", wing.section_names())
    print("feature       :", [f for f in summary.features if f.name == SOLID_NAME])
    print("up_to_date    :", part.is_up_to_date())
    print("topology      :", summary.topology)
    print("volume_mm3    :", round(mass.volume_mm3, 3))
    print("area_mm2      :", round(mass.area_mm2, 3))
    print("cog_mm        :", mass.cog_mm)

    assert root.support() == "XY"
    assert tip_plane.offset == SPAN_MM
    tip_support = tip.support()
    if tip_support is None:
        # support() refuses to guess when two planes share one frame -- as they do when
        # another +300 mm XY offset plane already exists in this Part.
        same_frame = [
            plane.name
            for plane in part.planes.list()
            if plane.base_display_name == tip_plane.base_display_name
            and getattr(plane, "offset", None) == SPAN_MM
        ]
        print("tip support    : ambiguous between planes sharing its frame:", same_frame)
        assert TIP_PLANE in same_frame and len(same_frame) > 1
        assert tip.axis_data()[2] == SPAN_MM
    else:
        assert tip_support.name == TIP_PLANE
    assert wing.section_names() == [ROOT_SKETCH, TIP_SKETCH]
    assert any(f.name == SOLID_NAME and f.kind == "Loft" for f in summary.features)
    assert part.is_up_to_date()
    assert summary.topology is not None
    assert [summary.topology.edges, summary.topology.faces] != baseline["topology"]
    assert mass.volume_mm3 > baseline["volume_mm3"]
    assert mass.area_mm2 > baseline["area_mm2"]
    print("verify: OK")


def remove() -> None:
    part = target_part()
    baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    remove_own(part)
    restored = observable_state(part)
    print("restored:", restored)
    if restored != baseline:
        for key in baseline:
            if restored.get(key) != baseline[key]:
                print(f"  DIFFERS {key}: {baseline[key]!r} -> {restored.get(key)!r}")
        raise AssertionError("the Part did not return to its baseline")
    BASELINE_FILE.unlink()
    print("remove: OK, baseline restored exactly")


if __name__ == "__main__":
    phases = {"create": create, "verify": verify, "remove": remove}
    if len(sys.argv) != 2 or sys.argv[1] not in phases:
        sys.exit(f"usage: {sys.argv[0]} {{{'|'.join(phases)}}}")
    phases[sys.argv[1]]()
