"""Live acceptance for Phase 5: the intent API and the low-level capabilities under it.

Each test builds its own `AUTO3DX_IT_P5_*` objects on the disposable Part named by
`AUTO3DX_LIVE_PART`, through the public API only (no `com_object`), proves one stage, and
removes what it made by name. Nothing is saved. Every stage prints a flushed marker before
its CATIA work, so a hang can be attributed (run with `-s` and `python -u`):

    python -u -m pytest tests/integration/test_phase5_live.py -m integration -s -k <stage>

The expected numbers are the micro-probes' (`docs/api-design.md` Appendix A).

CATIA gives a new hole the settings of the previous one (probe 46q), including in the UI.
These stages make flat and through-all holes, so the module ends by making one hole with
the settings a fresh session starts with (diameter 12, V bottom, blind) and removing it,
through the public API, leaving the session's hole defaults as they were.
"""

import math
import sys
import time
from typing import Any

import pytest

pytestmark = pytest.mark.integration

if sys.platform != "win32":
    pytest.skip("Windows COM is required.", allow_module_level=True)

pytest.importorskip("pywintypes", reason="pywin32 is required.")

from auto_3dx import Catia, PartUpdateError  # noqa: E402
from auto_3dx.errors import (  # noqa: E402
    Auto3dxError,
    CatiaConnectionError,
    NoActiveEditorError,
    NoActivePartError,
    StaleSnapshotError,
    UnknownFactError,
    UnsupportedOperationError,
    UnsupportedSupportError,
    ValidationError,
)

PREFIX = "AUTO3DX_IT_P5_"
LENGTH, WIDTH, HEIGHT = 60.0, 40.0, 20.0
BLOCK_VOLUME = LENGTH * WIDTH * HEIGHT
TOLERANCE = 1e-3

_REMOVERS = {
    "Pad": "remove_pad",
    "Pocket": "remove_pocket",
    "Hole": "remove_hole",
    "ConstRadEdgeFillet": "remove_edge_fillet",
    "Chamfer": "remove_chamfer",
    "CircPattern": "remove_circular_pattern",
}


def mark(text: str) -> None:
    """Prints one flushed progress marker, so a hang names its stage."""
    print(f"[P5 {time.strftime('%H:%M:%S')}] {text}", flush=True)


@pytest.fixture(scope="module", autouse=True)
def restore_hole_session_defaults() -> Any:
    """After the module, leaves CATIA's carried-over hole settings at a fresh session's."""
    yield
    try:
        part = Catia.attach().active_part()
    except Auto3dxError:
        return
    mark("module end: restore the session's hole defaults (12 mm, V, blind)")
    try:
        _block(part, "RESTORE")
        top = part.geometry.top_face(body="PartBody")
        part.bodies.main.features.hole(
            f"{PREFIX}RESTORE_HOLE",
            support=top,
            center=(0.0, 0.0),
            diameter=12.0,
            depth=8.0,
            bottom="v",
        )
        part.update()
    finally:
        _cleanup(part)


@pytest.fixture
def part() -> Any:
    """Returns the active Part, skipping when no suitable session is available."""
    try:
        catia = Catia.attach()
    except CatiaConnectionError as error:
        pytest.skip(f"No running 3DEXPERIENCE session: {error}")
    try:
        part = catia.active_part()
    except (NoActiveEditorError, NoActivePartError) as error:
        pytest.skip(f"No Part is being edited: {error}")
    existing = set(part.sketches.names()) | {f.name for f in part.inspect.features()}
    if any(name.startswith(PREFIX) for name in existing):
        pytest.skip("Objects with this test's prefix already exist; they are not ours.")
    yield part
    _cleanup(part)


def _cleanup(part: Any) -> None:
    """Removes every feature and sketch this module made, newest first, then rebuilds."""
    mark("cleanup")
    for info in reversed(part.inspect.features()):
        if info.name.startswith(PREFIX) and info.kind in _REMOVERS:
            try:
                getattr(part.part_design, _REMOVERS[info.kind])(info.name)
            except Auto3dxError as error:
                mark(f"cleanup could not remove {info.name}: {error}")
    for name in reversed(part.sketches.names()):
        if name.startswith(PREFIX):
            part.sketches.remove(name)
    if not part.is_up_to_date():
        part.update()
    left = [f.name for f in part.inspect.features() if f.name.startswith(PREFIX)]
    left += [s for s in part.sketches.names() if s.startswith(PREFIX)]
    assert left == [], f"cleanup left {left}"
    mark("cleanup done")


def _block(part: Any, tag: str) -> Any:
    """A 60x40x20 block centred on the origin, standing on XY, built with the intent API."""
    mark(f"{tag}: block sketch + rectangle")
    sketch = part.sketches.create(f"{PREFIX}{tag}_BLOCK_SK", support="XY")
    sketch.centered_rectangle(width=LENGTH, height=WIDTH)
    mark(f"{tag}: pad")
    pad = part.bodies.main.features.pad(f"{PREFIX}{tag}_BLOCK", sketch, HEIGHT, direction="+Z")
    part.update()
    return pad


def _volume(part: Any) -> float:
    return part.inspect.facts("volume")["volume"]


# --- stages 1-2: rectangle -> pad -> targeted facts ------------------------------------------


def test_stage01_rectangle_pad_and_targeted_facts(part: Any) -> None:
    pad = _block(part, "S1")

    mark("S1: targeted facts")
    started = time.perf_counter()
    facts = part.inspect.facts("volume", "up_to_date", "feature_count", "surface_area")
    elapsed = time.perf_counter() - started
    mark(f"S1: facts took {elapsed:.3f}s")

    assert facts["volume"] == pytest.approx(BLOCK_VOLUME, abs=TOLERANCE)
    assert facts["up_to_date"] is True
    assert facts["feature_count"] == 1
    assert facts["surface_area"] == pytest.approx(2 * (60 * 40 + 60 * 20 + 40 * 20), abs=0.01)
    assert pad.length == pytest.approx(HEIGHT)


# --- stages 3-5: top face finder -> sketch on it -> pocket into the material -----------------


def test_stage03_top_face_sketch_and_pocket_into_material(part: Any) -> None:
    _block(part, "S3")

    mark("S3: top_face finder")
    top = part.geometry.top_face(body="PartBody")
    assert top.geometry.center_mm == pytest.approx((0.0, 0.0, HEIGHT))

    mark("S3: sketch on the top face")
    sketch = part.sketches.create(f"{PREFIX}S3_FACE_SK", support=top)
    assert sketch.created_on_face
    frame = sketch.frame()
    assert frame.normal == pytest.approx((0.0, 0.0, 1.0))
    local = frame.to_local((10.0, 5.0, HEIGHT))
    sketch.circle(center=local, radius=3.0)

    mark("S3: pocket into the material")
    part.bodies.main.features.pocket(f"{PREFIX}S3_POCKET", sketch, 4.0, direction="into_material")
    part.update()

    assert BLOCK_VOLUME - _volume(part) == pytest.approx(math.pi * 9 * 4, abs=TOLERANCE)
    bore = part.geometry.find_cylindrical_face(radius=3.0)
    assert bore.geometry.center_mm == pytest.approx((10.0, 5.0, HEIGHT - 2.0))


# --- stages 6-7: positioned hole, blind and through-all ---------------------------------------


def test_stage06_positioned_hole_blind_then_through_all(part: Any) -> None:
    _block(part, "S6")
    top = part.geometry.top_face(body="PartBody")

    mark("S6: positioned flat hole, 8 deep")
    hole = part.bodies.main.features.hole(
        f"{PREFIX}S6_HOLE", support=top, center=(10.0, 5.0), diameter=6.0, depth=8.0
    )
    part.update()
    assert hole.origin == pytest.approx((10.0, 5.0, HEIGHT))
    assert (hole.limit, hole.bottom) == ("blind", "flat")
    assert BLOCK_VOLUME - _volume(part) == pytest.approx(math.pi * 9 * 8, abs=TOLERANCE)

    mark("S6: through all")
    hole.set_limit("through_all")
    part.update()
    assert hole.limit == "through_all"
    assert BLOCK_VOLUME - _volume(part) == pytest.approx(math.pi * 9 * HEIGHT, abs=TOLERANCE)

    mark("S6: back to blind needs the depth again")
    hole.set_limit("blind", depth=8.0)
    part.update()
    assert BLOCK_VOLUME - _volume(part) == pytest.approx(math.pi * 9 * 8, abs=TOLERANCE)


def test_stage07_through_all_hole_at_creation(part: Any) -> None:
    _block(part, "S7")
    top = part.geometry.top_face(body="PartBody")

    mark("S7: through-all hole")
    part.bodies.main.features.hole(
        f"{PREFIX}S7_HOLE",
        support=top,
        center=(-10.0, -5.0),
        diameter=8.0,
        limit="through_all",
    )
    part.update()

    assert BLOCK_VOLUME - _volume(part) == pytest.approx(math.pi * 16 * HEIGHT, abs=TOLERANCE)


# --- stages 8-9: fillet and chamfer on edges found by meaning --------------------------------


def test_stage08_fillet_and_chamfer_on_semantic_edges(part: Any) -> None:
    _block(part, "S8")

    mark("S8: fillet the vertical edge at (+30, +20)")
    edge = part.geometry.find_edge(kind="line", parallel="Z", nearest=(30.0, 20.0, 10.0))
    fillet = part.bodies.main.features.fillet(f"{PREFIX}S8_FILLET", edges=[edge], radius=3.0)
    part.update()
    fillet_loss = (1 - math.pi / 4) * 9 * HEIGHT
    assert BLOCK_VOLUME - _volume(part) == pytest.approx(fillet_loss, abs=TOLERANCE)

    mark("S8: chamfer the vertical edge at (-30, -20), found again after the change")
    edge = part.geometry.find_edge(kind="line", parallel="Z", nearest=(-30.0, -20.0, 10.0))
    part.bodies.main.features.chamfer(f"{PREFIX}S8_CHAMFER", edge=edge, length=2.0)
    part.update()
    chamfer_loss = 0.5 * 2 * 2 * HEIGHT
    assert BLOCK_VOLUME - _volume(part) == pytest.approx(fillet_loss + chamfer_loss, abs=1e-2)

    mark("S8: edit the fillet radius through the property")
    fillet.radius = 4.0
    part.update()
    larger = (1 - math.pi / 4) * 16 * HEIGHT
    assert BLOCK_VOLUME - _volume(part) == pytest.approx(larger + chamfer_loss, abs=1e-2)


# --- stage 10: circular pattern of a hole, about Z and about a bore's axis --------------------


def test_stage10_circular_pattern_of_a_hole_about_z(part: Any) -> None:
    _block(part, "S10")
    top = part.geometry.top_face(body="PartBody")
    hole = part.bodies.main.features.hole(
        f"{PREFIX}S10_HOLE", support=top, center=(12.0, 0.0), diameter=4.0, limit="through_all"
    )

    mark("S10: pattern the hole 6 times over a full circle about Z")
    pattern = part.bodies.main.features.circular_pattern(
        f"{PREFIX}S10_PATTERN", feature=hole, instances=6, total_angle_deg=360, axis="Z"
    )
    part.update()
    one = math.pi * 4 * HEIGHT
    assert BLOCK_VOLUME - _volume(part) == pytest.approx(6 * one, abs=1e-2)
    assert pattern.spacing_deg == pytest.approx(60.0)

    mark("S10: four instances through the property")
    pattern.instances = 4
    part.update()
    assert BLOCK_VOLUME - _volume(part) == pytest.approx(4 * one, abs=1e-2)


def test_stage10b_circular_pattern_about_a_bore_axis(part: Any) -> None:
    _block(part, "S10B")
    top = part.geometry.top_face(body="PartBody")
    part.bodies.main.features.hole(
        f"{PREFIX}S10B_BORE",
        support=top,
        center=(-10.0, 0.0),
        diameter=8.0,
        limit="through_all",
    )
    part.update()
    top = part.geometry.top_face(body="PartBody")
    seed = part.bodies.main.features.hole(
        f"{PREFIX}S10B_SEED", support=top, center=(5.0, 0.0), diameter=4.0, limit="through_all"
    )
    part.update()

    mark("S10B: pattern the seed 4 x 90 degrees about the bore's axis at (-10, 0)")
    bore = part.geometry.find_cylindrical_face(radius=4.0)
    part.bodies.main.features.circular_pattern(
        f"{PREFIX}S10B_PATTERN", feature=seed, instances=4, spacing_deg=90.0, axis=bore
    )
    part.update()

    small = part.geometry.faces(body="PartBody").cylindrical().radius_near(2.0).all()
    centres = sorted(
        (round(f.geometry.center_mm[0], 3), round(f.geometry.center_mm[1], 3)) for f in small
    )
    assert centres == [(-25.0, 0.0), (-10.0, -15.0), (-10.0, 15.0), (5.0, 0.0)]


# --- stage 11: sketch geometry read back -----------------------------------------------------


def test_stage11_sketch_geometry_reads_back(part: Any) -> None:
    mark("S11: dimensioned rectangle + circle")
    sketch = part.sketches.create(f"{PREFIX}S11_SK", support="XY")
    profile = sketch.rectangle(
        width=12.0, height=8.0, origin=(-40.0, 20.0), constraints="dimensioned"
    )
    sketch.circle(center=(20.0, 15.0), radius=4.0)
    part.update()
    assert len(profile.constraints) == 6

    mark("S11: read back through a fresh lookup")
    result = part.sketches.get(f"{PREFIX}S11_SK").geometry()
    lines = {line.name: line.geometry for line in result.lines}
    assert len(lines) == 4
    assert profile.bottom.geometry().start == pytest.approx((-40.0, 20.0))
    assert profile.bottom.geometry().length_mm == pytest.approx(12.0)
    (circle,) = result.circles
    assert circle.geometry.center == pytest.approx((20.0, 15.0))
    assert circle.geometry.radius_mm == pytest.approx(4.0)
    assert circle.geometry.is_closed
    lengths = sorted(c.value for c in result.constraints if c.type_code == 5)
    assert lengths == pytest.approx([8.0, 12.0])
    assert all(c.status == 0 and c.mode == "driving" for c in result.constraints)
    assert {c.first_element for c in result.constraints} <= set(lines)


# --- stage 12: the plane-coincidence filter (adjacency stays unsupported) --------------------


def test_stage12_rim_edge_on_the_top_plane(part: Any) -> None:
    _block(part, "S12")
    top = part.geometry.top_face(body="PartBody")
    part.bodies.main.features.hole(
        f"{PREFIX}S12_HOLE",
        support=top,
        center=(0.0, 0.0),
        diameter=10.0,
        limit="through_all",
    )
    part.update()

    mark("S12: the rim circle lying in the top face's plane")
    top = part.geometry.top_face(body="PartBody")
    rim = part.geometry.find_edge(kind="circle", radius=5.0, on_plane_of=top)
    assert rim.geometry.center_mm == pytest.approx((0.0, 0.0, HEIGHT))


# --- stages 13-14: property edits, typed errors, recovery ------------------------------------


def test_stage13_property_edit_and_recovery(part: Any) -> None:
    pad = _block(part, "S13")
    edge = part.geometry.find_edge(kind="line", parallel="Z", nearest=(30.0, 20.0, 10.0))
    fillet = part.bodies.main.features.fillet(f"{PREFIX}S13_FILLET", edges=edge, radius=3.0)
    part.update()
    healthy = _volume(part)

    mark("S13: pad.length = 30 through the property, then back")
    pad.length = 30.0
    part.update()
    assert _volume(part) == pytest.approx(healthy * 1.5, abs=1e-2)
    pad.length = HEIGHT
    part.update()
    assert _volume(part) == pytest.approx(healthy, abs=TOLERANCE)

    mark("S13: a radius the solid cannot take fails the update; putting it back repairs it")
    fillet.radius = 500.0
    with pytest.raises(PartUpdateError):
        part.update()
    assert not part.is_up_to_date()
    fillet.radius = 3.0
    part.update()
    assert part.is_up_to_date()
    assert _volume(part) == pytest.approx(healthy, abs=TOLERANCE)


def test_stage14_typed_errors_leave_the_model_untouched(part: Any) -> None:
    _block(part, "S14")
    features_before = [f.name for f in part.inspect.features()]
    top = part.geometry.top_face(body="PartBody")
    xy_sketch = part.sketches.create(f"{PREFIX}S14_XY_SK", support="XY")
    xy_sketch.circle(center=(0.0, 0.0), radius=2.0)
    part.update()

    mark("S14: stale face")
    with pytest.raises(StaleSnapshotError):
        part.sketches.create(f"{PREFIX}S14_STALE_SK", support=top)

    mark("S14: material side of a sketch not created on a face")
    with pytest.raises(UnsupportedOperationError, match="created on a face"):
        part.bodies.main.features.pocket(
            f"{PREFIX}S14_P", xy_sketch, 2.0, direction="into_material"
        )

    mark("S14: reversed hole; unknown fact; two fillet edges")
    top = part.geometry.top_face(body="PartBody")
    with pytest.raises(UnsupportedOperationError):
        part.bodies.main.features.hole(
            f"{PREFIX}S14_H",
            support=top,
            center=(0, 0),
            diameter=4,
            depth=2,
            direction="out_of_material",
        )
    with pytest.raises(UnknownFactError):
        part.inspect.facts("colour")
    edge_a = part.geometry.find_edge(kind="line", parallel="Z", nearest=(30.0, 20.0, 10.0))
    edge_b = part.geometry.find_edge(kind="line", parallel="Z", nearest=(-30.0, 20.0, 10.0))
    with pytest.raises(UnsupportedOperationError, match="several edges"):
        part.bodies.main.features.fillet(f"{PREFIX}S14_F", edges=[edge_a, edge_b], radius=1.0)

    mark("S14: a curved face as a sketch support")
    part.bodies.main.features.hole(
        f"{PREFIX}S14_BORE", support=top, center=(0.0, 0.0), diameter=6.0, limit="through_all"
    )
    part.update()
    features_before = [f.name for f in part.inspect.features()]
    bore = part.geometry.find_cylindrical_face(radius=3.0)
    with pytest.raises(UnsupportedSupportError, match="planar"):
        part.sketches.create(f"{PREFIX}S14_CURVED_SK", support=bore)

    assert [f.name for f in part.inspect.features()] == features_before
    assert f"{PREFIX}S14_CURVED_SK" not in part.sketches
    assert part.is_up_to_date()

    mark("S14: a geometry read inside an open edition is refused before CATIA is asked")
    # Drawing the line is a real edit (the sketch then needs a rebuild); only the READ inside
    # the open edition is refused, which is what this checks.
    with pytest.raises(ValidationError, match="open for editing"):
        with xy_sketch.edit() as editor:
            editor.line(0.0, 0.0, 1.0, 0.0).geometry()
    part.update()
    assert part.is_up_to_date()
