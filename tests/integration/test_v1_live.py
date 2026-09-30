"""Live functional acceptance for v1: what an agent does, through the public API only.

Every stage builds its own `AUTO3DX_IT_V1_*` objects on the disposable Part named by
`AUTO3DX_LIVE_PART`, proves one engineering intent, and removes exactly what it made. No
stage uses `com_object`, a private member, an index or a descriptor. Nothing is saved,
propagated or exported.

Target safety, checked around every stage:

* the active Part must be the named target, and it must be BLANK (one body, no features,
  sketches, user parameters or geometrical sets, up to date) -- anything else stops the
  whole run (`pytest.exit`), because unknown objects are not ours to touch;
* after the stage, the active Part must still be the same CATIA object (the SDK's shared
  model generation is keyed by COM identity) and blank again after cleanup -- otherwise the
  run stops.

Each stage prints a flushed marker before its CATIA work, so a hang names its stage:

    python -u -m pytest tests/integration/test_v1_live.py -m integration -s -k <stage>

The human-selection stage waits for a person to click an edge in CATIA; it runs only when
`AUTO3DX_HUMAN=1`. Expected numbers come from the v1 micro-probes (47a-47o).
"""

import math
import os
import sys
import time
from typing import Any

import pytest

pytestmark = pytest.mark.integration

if sys.platform != "win32":
    pytest.skip("Windows COM is required.", allow_module_level=True)

pytest.importorskip("pywintypes", reason="pywin32 is required.")

from auto_3dx import Catia  # noqa: E402
from auto_3dx.errors import (  # noqa: E402
    Auto3dxError,
    CatiaConnectionError,
    NoActiveEditorError,
    NoActivePartError,
    SelectionCountError,
    StaleSnapshotError,
    TopologyQueryAmbiguousError,
    UnsupportedOperationError,
)
from auto_3dx.geometry import Counterbore, Countersink  # noqa: E402

PREFIX = "AUTO3DX_IT_V1_"
LENGTH, WIDTH, HEIGHT = 60.0, 40.0, 20.0
BLOCK_VOLUME = LENGTH * WIDTH * HEIGHT
TOLERANCE = 1e-3
HUMAN_WAIT_SECONDS = 180

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
    print(f"[V1 {time.strftime('%H:%M:%S')}] {text}", flush=True)


def _blank_problems(part: Any) -> "list[str]":
    summary = part.inspect.summary()
    problems = []
    if summary.features:
        problems.append(f"features {[f.name for f in summary.features]}")
    if summary.sketches:
        problems.append(f"sketches {list(summary.sketches)}")
    if summary.parameters:
        problems.append(f"parameters {[p.name for p in summary.parameters]}")
    if summary.geometrical_sets:
        problems.append(f"geometrical sets {[s.name for s in summary.geometrical_sets]}")
    if len(summary.bodies) != 1:
        problems.append(f"{len(summary.bodies)} bodies")
    if not summary.up_to_date:
        problems.append("not up to date")
    return problems


@pytest.fixture(scope="module", autouse=True)
def restore_hole_session_defaults() -> Any:
    """After the module, leaves CATIA's carried-over hole settings at a fresh session's."""
    yield
    try:
        part = Catia.attach().active_part()
    except Auto3dxError:
        return
    if part.name != os.environ.get("AUTO3DX_LIVE_PART", "").strip() or _blank_problems(part):
        return
    mark("module end: restore the session's hole defaults (simple, 12 mm, V, blind)")
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
    """The frozen, blank target Part; the run stops if either is not what it should be."""
    target = os.environ.get("AUTO3DX_LIVE_PART", "").strip()
    if not target:
        pytest.skip("Set AUTO3DX_LIVE_PART to the name of a disposable, blank Part.")
    try:
        catia = Catia.attach()
    except CatiaConnectionError as error:
        pytest.skip(f"No running 3DEXPERIENCE session: {error}")
    try:
        part = catia.active_part()
    except (NoActiveEditorError, NoActivePartError) as error:
        pytest.skip(f"No Part is being edited: {error}")
    if part.name != target:
        pytest.exit(f"STOP: the active Part is {part.name!r}, not the target {target!r}.", 3)
    problems = _blank_problems(part)
    if problems:
        pytest.exit(f"STOP: the target is not blank ({'; '.join(problems)}); not ours.", 3)
    frozen = part._generation  # harness only: one object per CATIA Part, by COM identity
    yield part
    _cleanup(part)
    again = Catia.attach().active_part()
    if again.name != target or again._generation is not frozen:
        pytest.exit("STOP: the target Part's identity changed during the stage.", 3)
    problems = _blank_problems(again)
    if problems:
        pytest.exit(f"STOP: cleanup left the target not blank ({'; '.join(problems)}).", 3)


def _cleanup(part: Any) -> None:
    """Removes only what this module made (by prefix), newest first, then rebuilds."""
    mark("cleanup")
    try:
        part.selection.clear()
    except Auto3dxError as error:
        mark(f"cleanup could not clear the selection: {error}")
    for info in reversed(part.inspect.features()):
        if info.name.startswith(PREFIX) and info.kind in _REMOVERS:
            try:
                getattr(part.part_design, _REMOVERS[info.kind])(info.name)
            except Auto3dxError as error:
                mark(f"cleanup could not remove {info.name}: {error}")
    for name in reversed(part.sketches.names()):
        if name.startswith(PREFIX):
            part.sketches.remove(name)
    planes = [plane for plane in part.planes.list() if plane.name.startswith(PREFIX)]
    for plane in reversed(planes):
        part.planes.remove(plane, force=True)
    if planes and not part.planes.list():
        part.planes.remove_geometrical_set(force=True)
    if not part.is_up_to_date():
        part.update()
    left = [f.name for f in part.inspect.features() if f.name.startswith(PREFIX)]
    left += [s for s in part.sketches.names() if s.startswith(PREFIX)]
    assert left == [], f"cleanup left {left}"
    mark("cleanup done")


def _block(part: Any, tag: str, constraints: str = "none") -> Any:
    """A 60x40x20 block centred on the origin, standing on XY, built with the intent API."""
    mark(f"{tag}: block sketch + rectangle ({constraints})")
    sketch = part.sketches.create(f"{PREFIX}{tag}_BLOCK_SK", support="XY")
    profile = sketch.centered_rectangle(width=LENGTH, height=WIDTH, constraints=constraints)
    mark(f"{tag}: pad")
    pad = part.bodies.main.features.pad(f"{PREFIX}{tag}_BLOCK", sketch, HEIGHT, direction="+Z")
    part.update()
    return pad, profile


def _volume(part: Any) -> float:
    return part.inspect.facts("volume")["volume"]


def _removed(part: Any) -> float:
    return BLOCK_VOLUME - _volume(part)


# --- 1: rectangle -> pad ---------------------------------------------------------------------


def test_v01_fully_constrained_rectangle_to_pad(part: Any) -> None:
    pad, profile = _block(part, "V01", constraints="fully")

    assert _volume(part) == pytest.approx(BLOCK_VOLUME, abs=TOLERANCE)
    assert len(profile.constraints) == 8 and len(profile.corners) == 4
    assert pad.length == pytest.approx(HEIGHT)


# --- 2: top face -> centered pocket ------------------------------------------------------------


def test_v02_top_face_centered_pocket(part: Any) -> None:
    _block(part, "V02")
    top = part.geometry.top_face(body="PartBody")

    mark("V02: centred rectangle on the top face, pocket into the material")
    sketch = part.sketches.create(f"{PREFIX}V02_FACE_SK", support=top)
    sketch.centered_rectangle(width=20.0, height=10.0, center=sketch.frame().to_local((0, 0, 20)))
    part.bodies.main.features.pocket(f"{PREFIX}V02_POCKET", sketch, 5.0, direction="into_material")
    part.update()

    assert _removed(part) == pytest.approx(20 * 10 * 5, abs=TOLERANCE)


# --- 3-4: positioned holes land where they were asked --------------------------------------------


def test_v03_off_centre_hole_on_a_rectangular_face(part: Any) -> None:
    _block(part, "V03")
    top = part.geometry.top_face(body="PartBody")

    mark("V03: hole at (17, -8) on the top face")
    hole = part.bodies.main.features.hole(
        f"{PREFIX}V03_HOLE", support=top, center=(17.0, -8.0), diameter=6.0, depth=8.0
    )
    assert hole.origin == pytest.approx((17.0, -8.0, HEIGHT))
    part.update()

    for _ in range(3):  # repeated readback agrees
        assert hole.origin == pytest.approx((17.0, -8.0, HEIGHT))
    bore = part.geometry.find_cylindrical_face(radius=3.0)
    assert bore.geometry.center_mm[:2] == pytest.approx((17.0, -8.0))
    assert _removed(part) == pytest.approx(math.pi * 9 * 8, abs=TOLERANCE)


def test_v04_off_centre_hole_on_a_circular_face_is_not_snapped(part: Any) -> None:
    mark("V04: disc r = 20, 10 high")
    sketch = part.sketches.create(f"{PREFIX}V04_DISC_SK", support="XY")
    sketch.circle(center=(0.0, 0.0), radius=20.0)
    part.bodies.main.features.pad(f"{PREFIX}V04_DISC", sketch, 10.0, direction="+Z")
    part.update()
    top = part.geometry.top_face(body="PartBody")

    mark("V04: hole requested at (8, 0) -- CATIA alone snaps it to (0, 0) (probe 47d)")
    hole = part.bodies.main.features.hole(
        f"{PREFIX}V04_HOLE", support=top, center=(8.0, 0.0), diameter=4.0, depth=5.0
    )
    assert hole.origin == pytest.approx((8.0, 0.0, 10.0))
    part.update()

    assert hole.origin == pytest.approx((8.0, 0.0, 10.0))
    bore = part.geometry.find_cylindrical_face(radius=2.0)
    assert bore.geometry.center_mm == pytest.approx((8.0, 0.0, 7.5), abs=TOLERANCE)


def test_v04b_centred_hole_on_a_circular_face(part: Any) -> None:
    sketch = part.sketches.create(f"{PREFIX}V04B_DISC_SK", support="XY")
    sketch.circle(center=(0.0, 0.0), radius=20.0)
    part.bodies.main.features.pad(f"{PREFIX}V04B_DISC", sketch, 10.0, direction="+Z")
    part.update()
    top = part.geometry.top_face(body="PartBody")

    mark("V04B: through hole at the centre")
    hole = part.bodies.main.features.hole(
        f"{PREFIX}V04B_HOLE", support=top, center=(0.0, 0.0), diameter=4.0, limit="through_all"
    )
    part.update()

    assert hole.origin == pytest.approx((0.0, 0.0, 10.0))
    assert _volume(part) == pytest.approx(math.pi * 400 * 10 - math.pi * 4 * 10, abs=1e-2)


# --- hole heads (probe 47h) ----------------------------------------------------------------------


def test_v04c_counterbored_and_countersunk_holes(part: Any) -> None:
    _block(part, "V04C")
    top = part.geometry.top_face(body="PartBody")

    mark("V04C: counterbore 12 x 4 on a 6 mm hole 10 deep")
    bored = part.bodies.main.features.hole(
        f"{PREFIX}V04C_CB",
        support=top,
        center=(-15.0, 0.0),
        diameter=6.0,
        depth=10.0,
        head=Counterbore(diameter=12.0, depth=4.0),
    )
    part.update()
    counterbore = math.pi * 9 * 10 + math.pi * 27 * 4
    assert _removed(part) == pytest.approx(counterbore, abs=1e-2)
    assert bored.head == Counterbore(12.0, 4.0)

    mark("V04C: countersink 90 degrees, 2 deep")
    top = part.geometry.top_face(body="PartBody")
    sunk = part.bodies.main.features.hole(
        f"{PREFIX}V04C_CS",
        support=top,
        center=(15.0, 0.0),
        diameter=6.0,
        depth=10.0,
        head=Countersink(depth=2.0, angle_deg=90.0),
    )
    part.update()
    assert _removed(part) == pytest.approx(counterbore + 328.819, abs=1e-2)
    assert sunk.hole_type == "countersunk"


# --- 5-6: fillet and chamfer on semantic edges -------------------------------------------------


def test_v05_fillet_on_a_semantic_edge(part: Any) -> None:
    _block(part, "V05")
    edge = part.geometry.find_edge(kind="line", parallel="Z", nearest=(30.0, 20.0, 10.0))

    part.bodies.main.features.fillet(f"{PREFIX}V05_FILLET", edges=edge, radius=3.0)
    part.update()

    assert _removed(part) == pytest.approx((1 - math.pi / 4) * 9 * HEIGHT, abs=TOLERANCE)


def test_v06_chamfer_on_an_edge_of_the_top_face(part: Any) -> None:
    _block(part, "V06")
    top = part.geometry.top_face(body="PartBody")
    edge = part.geometry.find_edge(parallel="X", adjacent_to=top, nearest=(0.0, -20.0, 20.0))

    part.bodies.main.features.chamfer(f"{PREFIX}V06_CHAMFER", edge=edge, length=2.0)
    part.update()

    assert _removed(part) == pytest.approx(0.5 * 2 * 2 * LENGTH, abs=1e-2)


# --- 7: full-circle circular pattern ---------------------------------------------------------------


def test_v07_full_circle_pattern_about_z(part: Any) -> None:
    _block(part, "V07")
    top = part.geometry.top_face(body="PartBody")
    hole = part.bodies.main.features.hole(
        f"{PREFIX}V07_HOLE", support=top, center=(12.0, 0.0), diameter=4.0, limit="through_all"
    )

    pattern = part.bodies.main.features.circular_pattern(
        f"{PREFIX}V07_PATTERN", feature=hole, instances=5, full_circle=True, axis="Z"
    )
    part.update()
    assert pattern.full_circle and pattern.spacing_deg == pytest.approx(72.0)
    assert _removed(part) == pytest.approx(5 * math.pi * 4 * HEIGHT, abs=1e-2)

    pattern.set_full_circle(8)
    part.update()
    assert pattern.spacing_deg == pytest.approx(45.0)
    assert _removed(part) == pytest.approx(8 * math.pi * 4 * HEIGHT, abs=1e-2)


# --- 8: edit the driving sketch dimension ------------------------------------------------------------


def test_v08_driving_the_rectangle_width_grows_the_solid(part: Any) -> None:
    _, profile = _block(part, "V08", constraints="fully")

    mark("V08: width 60 -> 70")
    profile.width_constraint.set_value(70.0)
    part.update()

    assert _volume(part) == pytest.approx(70 * WIDTH * HEIGHT, abs=TOLERANCE)
    assert part.inspect.facts("up_to_date")["up_to_date"] is True


# --- 9: targeted inspection ------------------------------------------------------------------------


def test_v09_targeted_inspection_reads_without_changing_anything(part: Any) -> None:
    _block(part, "V09")
    top = part.geometry.top_face(body="PartBody")
    part.bodies.main.features.hole(
        f"{PREFIX}V09_HOLE",
        support=top,
        center=(5.0, 5.0),
        diameter=6.0,
        depth=8.0,
        head=Counterbore(10.0, 3.0),
    )
    part.update()
    before = (part._generation.value, _volume(part))

    details = part.inspect.feature(f"{PREFIX}V09_HOLE")
    sketch = part.inspect.sketch(f"{PREFIX}V09_BLOCK_SK")

    assert details.kind == "Hole" and details.up_to_date
    assert details.parameters["diameter"] == pytest.approx(6.0)
    assert details.parameters["head"] == Counterbore(10.0, 3.0)
    assert details.parameters["origin"] == pytest.approx((5.0, 5.0, HEIGHT))
    assert len(sketch.lines) == 4
    assert (part._generation.value, _volume(part)) == before
    assert part.is_up_to_date()


# --- 10-11: semantic top face and true adjacency --------------------------------------------------


def test_v10_semantic_top_face_and_true_adjacency(part: Any) -> None:
    _block(part, "V10")
    top = part.geometry.top_face(body="PartBody")
    assert top.geometry.center_mm == pytest.approx((0.0, 0.0, HEIGHT))

    mark("V10: the top face's boundary")
    bounding = part.topology.edges_of(top).all()
    assert len(bounding) == 4
    assert all(abs(edge.geometry.mid_mm[2] - HEIGHT) < TOLERANCE for edge in bounding)

    mark("V10: the bottom face's boundary excludes the sketch profile under it")
    bottom = part.geometry.bottom_face(body="PartBody")
    assert len(part.topology.edges_of(bottom).all()) == 4
    assert len(part.topology.edges(body="PartBody").query().on_plane_of(bottom).all()) == 8

    mark("V10: the faces an edge bounds")
    edge = part.geometry.find_edge(parallel="X", adjacent_to=top, nearest=(0.0, -20.0, 20.0))
    centres = sorted(
        tuple(round(value, 3) for value in face.geometry.center_mm)
        for face in part.topology.faces_of(edge).all()
    )
    assert centres == [(0.0, -20.0, 10.0), (0.0, 0.0, 20.0)]


# --- 12: a human selects an edge ---------------------------------------------------------------------


def test_v12_a_human_selected_edge_is_an_ordinary_edge(part: Any) -> None:
    if os.environ.get("AUTO3DX_HUMAN") != "1":
        pytest.skip("Needs a person at CATIA: set AUTO3DX_HUMAN=1.")
    pad, _ = _block(part, "V12")
    part.selection.clear()
    volume = _volume(part)

    mark(f"[HUMAN] In CATIA, click ONE EDGE of {PREFIX}V12_BLOCK. Waiting {HUMAN_WAIT_SECONDS} s.")
    deadline = time.monotonic() + HUMAN_WAIT_SECONDS
    while time.monotonic() < deadline and part.selection.count == 0:
        time.sleep(2)
    time.sleep(2)  # let the click settle

    edge = part.selection.one_edge()
    mark(f"V12: selected {edge.describe()}")
    assert edge.owner_body_name == "PartBody"
    assert edge.from_sketch is False
    assert edge.geometry.curve_type == "line"
    assert edge.geometry.length_mm in (
        pytest.approx(LENGTH),
        pytest.approx(WIDTH),
        pytest.approx(HEIGHT),
    )

    mark("V12: the selected edge drives a feature")
    part.selection.clear()
    part.bodies.main.features.fillet(f"{PREFIX}V12_FILLET", edges=edge, radius=1.0)
    part.update()
    assert _volume(part) < volume
    with pytest.raises(StaleSnapshotError):
        edge.geometry.length_mm  # noqa: B018 - the model changed: the handle is stale
    assert pad.name == f"{PREFIX}V12_BLOCK"


# --- 13: the agent highlights an edge ----------------------------------------------------------------


def test_v13_agent_highlights_an_edge_without_changing_the_model(part: Any) -> None:
    _block(part, "V13")
    top = part.geometry.top_face(body="PartBody")
    edge = part.geometry.find_edge(parallel="X", adjacent_to=top, nearest=(0.0, -20.0, 20.0))
    before = (part._generation.value, _volume(part))

    mark("V13: highlight the edge")
    part.selection.set(edge)

    assert part.selection.count == 1
    selected = part.selection.one_edge()
    assert selected.geometry.start_mm == pytest.approx(edge.geometry.start_mm)
    assert selected.geometry.end_mm == pytest.approx(edge.geometry.end_mm)
    assert (part._generation.value, _volume(part)) == before
    assert part.is_up_to_date()
    part.selection.clear()
    assert part.selection.count == 0


# --- 14: reference plane -> sketch -> feature --------------------------------------------------------


def test_v14_reference_plane_from_a_face_carries_a_feature(part: Any) -> None:
    _block(part, "V14")
    top = part.geometry.top_face(body="PartBody")

    mark("V14: plane 10 mm out of the material from the top face")
    plane = part.geometry.offset_plane(f"{PREFIX}V14_PLANE", face=top, distance=10.0)
    part.update()
    assert plane.origin[2] == pytest.approx(HEIGHT + 10.0)

    mark("V14: circle on the plane, padded down to the block")
    sketch = part.sketches.create(f"{PREFIX}V14_BOSS_SK", support=plane)
    sketch.circle(center=sketch.frame().to_local((0.0, 0.0, HEIGHT + 10.0)), radius=5.0)
    part.bodies.main.features.pad(f"{PREFIX}V14_BOSS", sketch, 10.0, direction="-Z")
    part.update()

    assert _volume(part) == pytest.approx(BLOCK_VOLUME + math.pi * 25 * 10, abs=1e-2)


# --- 15: an ambiguous request fails safely ---------------------------------------------------------


def test_v15_ambiguity_is_an_error_and_changes_nothing(part: Any) -> None:
    _block(part, "V15")
    part.selection.clear()
    before = (
        part._generation.value,
        _volume(part),
        [f.name for f in part.inspect.features()],
    )

    with pytest.raises(TopologyQueryAmbiguousError):
        part.geometry.find_edge(kind="line", parallel="X")
    edges = part.geometry.edges(body="PartBody").parallel("X").all()
    assert len(edges) == 4
    with pytest.raises(UnsupportedOperationError):
        part.bodies.main.features.fillet(f"{PREFIX}V15_FILLET", edges=edges[:2], radius=1.0)
    with pytest.raises(SelectionCountError):
        part.selection.one_edge()

    after = (
        part._generation.value,
        _volume(part),
        [f.name for f in part.inspect.features()],
    )
    assert after == before
    assert part.is_up_to_date()
