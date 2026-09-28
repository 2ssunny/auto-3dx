"""Live checks for Phase 4: geometry facts, geometry queries, direction, planes, diagnostics.

Each test builds its own `AUTO3DX_IT_P4_*` objects on the disposable Part named by
`AUTO3DX_LIVE_PART`, proves one capability against the running CATIA, and removes exactly
what it made. Nothing is saved.

No test here picks a face or an edge by its position in a snapshot or by its BRep name:
every selection is a geometry query, which is the point of Phase 4.
"""

import math
import sys
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
    ReferenceInUseError,
    StaleSnapshotError,
    TopologyQueryAmbiguousError,
    TopologyQueryNoMatchError,
)
from auto_3dx.geometry.facts import (  # noqa: E402
    CURVE_CIRCLE,
    CURVE_LINE,
    SURFACE_CYLINDRICAL,
    SURFACE_PLANAR,
)
from auto_3dx.geometry.part_design import (  # noqa: E402
    DIRECTION_AGAINST_SKETCH_NORMAL,
    DIRECTION_ALONG_SKETCH_NORMAL,
)
from auto_3dx.geometry.planes import GEOMETRICAL_SET_NAME  # noqa: E402

PREFIX = "AUTO3DX_IT_P4_"
BLOCK_SKETCH, BLOCK_PAD = f"{PREFIX}BLOCK_SKETCH", f"{PREFIX}BLOCK_PAD"
HOLE_SKETCH, HOLE_POCKET = f"{PREFIX}HOLE_SKETCH", f"{PREFIX}HOLE_POCKET"
SLOT_SKETCH, SLOT_POCKET = f"{PREFIX}SLOT_SKETCH", f"{PREFIX}SLOT_POCKET"
FILLET = f"{PREFIX}FILLET"
LIFT_PLANE, LIFT_SKETCH, LIFT_PAD = f"{PREFIX}LIFT_PLANE", f"{PREFIX}LIFT_SKETCH", f"{PREFIX}LIFT_PAD"
LENGTH, WIDTH, HEIGHT = 60.0, 40.0, 20.0
HOLE_RADIUS, HOLE_X = 5.0, -15.0
Z = (0.0, 0.0, 1.0)


@pytest.fixture
def part() -> Any:
    """Returns the active Part, skipping when no suitable session is available."""
    try:
        catia = Catia.attach()
    except CatiaConnectionError as error:
        pytest.skip(f"No running 3DEXPERIENCE session: {error}")
    try:
        return catia.active_part()
    except (NoActiveEditorError, NoActivePartError) as error:
        pytest.skip(f"No Part is being edited: {error}")


def _skip_if_ours_exist(part: Any) -> None:
    existing = set(part.sketches.names()) | {f.name for f in part.inspect.features()}
    if any(name.startswith(PREFIX) for name in existing):
        pytest.skip("Objects with this test's prefix already exist; they are not ours.")


def _build_block_with_hole(part: Any, height: float = HEIGHT) -> None:
    """A 60x40 block on XY with a through hole cut UP from XY -- no offset plane needed."""
    sketch = part.sketches.create(BLOCK_SKETCH, support="XY")
    with sketch.edit() as editor:
        editor.rectangle(LENGTH, WIDTH, origin_x=-LENGTH / 2, origin_y=-WIDTH / 2)
    part.part_design.create_pad(BLOCK_PAD, sketch, height)
    part.update()
    hole = part.sketches.create(HOLE_SKETCH, support="XY")
    with hole.edit() as editor:
        editor.circle(HOLE_X, 0.0, HOLE_RADIUS)
    part.part_design.create_pocket(
        HOLE_POCKET, hole, 100.0, direction=DIRECTION_ALONG_SKETCH_NORMAL
    )
    part.update()


def _cleanup(part: Any, plane_set_existed: bool = True) -> None:
    for step in (
        lambda: part.part_design.get_pad(BLOCK_PAD).activate(),
        lambda: part.part_design.remove_edge_fillet(FILLET),
        lambda: part.part_design.remove_pocket(SLOT_POCKET),
        lambda: part.sketches.remove(SLOT_SKETCH),
        lambda: part.part_design.remove_pad(LIFT_PAD),
        lambda: part.sketches.remove(LIFT_SKETCH),
        lambda: part.planes.remove(part.planes.get(LIFT_PLANE)),
        lambda: part.part_design.remove_pocket(HOLE_POCKET),
        lambda: part.sketches.remove(HOLE_SKETCH),
        lambda: part.part_design.remove_pad(BLOCK_PAD),
        lambda: part.sketches.remove(BLOCK_SKETCH),
    ):
        try:
            step()
        except Auto3dxError:
            pass
    sets = [s for s in part.inspect.geometrical_sets() if s.name == GEOMETRICAL_SET_NAME]
    if not plane_set_existed and sets and not sets[0].elements:
        part.planes.remove_geometrical_set()
    part.update()


def test_faces_and_edges_are_measured_and_selected_by_geometry(part: Any) -> None:
    _skip_if_ours_exist(part)

    try:
        _build_block_with_hole(part)
        faces = part.topology.faces(body="PartBody")
        edges = part.topology.edges(body="PartBody")

        # The top face: planar, horizontal, and the highest such face.
        horizontal = faces.query().planar().normal_parallel(Z)
        assert horizontal.count() == 2, "top and bottom are both horizontal"
        with pytest.raises(TopologyQueryAmbiguousError):
            horizontal.largest().one()  # equal areas: one() refuses to choose
        top = horizontal.extreme(Z).one()
        assert top.geometry.surface_type == SURFACE_PLANAR
        assert top.geometry.center_mm[2] == pytest.approx(HEIGHT)
        expected_area = LENGTH * WIDTH - math.pi * HOLE_RADIUS**2
        assert top.geometry.area_mm2 == pytest.approx(expected_area, rel=1e-9)

        # The hole wall and the hole's top rim.
        wall = faces.query().cylindrical().radius_near(HOLE_RADIUS, tolerance_mm=0.01).one()
        assert wall.geometry.surface_type == SURFACE_CYLINDRICAL
        assert wall.geometry.center_mm[0] == pytest.approx(HOLE_X)
        rim = (
            edges.query()
            .circular()
            .radius_near(HOLE_RADIUS, tolerance_mm=0.01)
            .nearest((HOLE_X, 0.0, HEIGHT))
            .one()
        )
        assert rim.geometry.curve_type == CURVE_CIRCLE
        assert rim.geometry.center_mm == pytest.approx((HOLE_X, 0.0, HEIGHT))

        # An outer vertical edge, chosen by direction and position, filleted.
        corner = (
            edges.query()
            .lines()
            .parallel(Z)
            .nearest((LENGTH / 2, WIDTH / 2, HEIGHT / 2))
            .one()
        )
        assert corner.geometry.curve_type == CURVE_LINE
        assert corner.geometry.length_mm == pytest.approx(HEIGHT)

        # A query that matches nothing says so instead of returning None.
        with pytest.raises(TopologyQueryNoMatchError):
            edges.query().circular().radius_near(99.0).one()

        volume = part.measurement.measure().volume_mm3
        part.part_design.create_edge_fillet(FILLET, corner, 4.0)
        part.update()
        assert part.measurement.measure().volume_mm3 < volume
    finally:
        _cleanup(part)


def test_geometry_from_an_old_snapshot_is_refused_and_a_new_one_finds_the_same_intent(
    part: Any,
) -> None:
    _skip_if_ours_exist(part)

    try:
        _build_block_with_hole(part)
        faces = part.topology.faces(body="PartBody")
        top = faces.query().planar().normal_parallel(Z).extreme(Z).one()
        assert top.geometry.center_mm[2] == pytest.approx(HEIGHT)

        # Change the solid upstream and rebuild.
        part.part_design.get_pad(BLOCK_PAD).set_height(30.0)
        part.update()

        fresh_face = faces.query()
        with pytest.raises(StaleSnapshotError):
            fresh_face.planar().one()

        # The same intent, asked again of a new snapshot, finds the moved face.
        moved = part.topology.faces(body="PartBody").query().planar().normal_parallel(Z)
        top_now = moved.extreme(Z).one()
        assert top_now.geometry.center_mm[2] == pytest.approx(30.0)
        rim_now = (
            part.topology.edges(body="PartBody").query()
            .circular().radius_near(HOLE_RADIUS, 0.01).nearest((HOLE_X, 0.0, 30.0)).one()
        )
        assert rim_now.geometry.center_mm[2] == pytest.approx(30.0)

        # A fresh wrapper measures the same face the same way.
        again = (
            Catia.attach().active_part().topology.faces(body="PartBody").query()
            .planar().normal_parallel(Z).extreme(Z).one()
        )
        assert again.geometry.area_mm2 == pytest.approx(top_now.geometry.area_mm2)
    finally:
        _cleanup(part)


def test_a_pocket_direction_decides_whether_it_cuts(part: Any) -> None:
    _skip_if_ours_exist(part)

    try:
        _build_block_with_hole(part)
        solid = part.measurement.measure().volume_mm3
        slot = part.sketches.create(SLOT_SKETCH, support="XY")
        with slot.edit() as editor:
            editor.circle(15.0, 0.0, 4.0)

        # CATIA's default for a pocket goes against the sketch normal: below XY, where
        # there is no material. It creates and updates, and removes nothing.
        pocket = part.part_design.create_pocket(SLOT_POCKET, slot, 10.0)
        part.update()
        assert pocket.direction == DIRECTION_AGAINST_SKETCH_NORMAL
        assert part.measurement.measure().volume_mm3 == pytest.approx(solid, rel=1e-12)

        pocket.reverse_direction()
        assert part.is_up_to_date() is False, "setting the direction must not rebuild"
        part.update()
        assert pocket.direction == DIRECTION_ALONG_SKETCH_NORMAL
        removed = solid - part.measurement.measure().volume_mm3
        assert removed == pytest.approx(math.pi * 16.0 * 10.0, rel=1e-9)

        fresh = Catia.attach().active_part().part_design.get_pocket(SLOT_POCKET)
        assert fresh.direction == DIRECTION_ALONG_SKETCH_NORMAL
    finally:
        _cleanup(part)


def test_a_pad_created_against_the_normal_goes_the_other_way(part: Any) -> None:
    _skip_if_ours_exist(part)

    try:
        sketch = part.sketches.create(BLOCK_SKETCH, support="XY")
        with sketch.edit() as editor:
            editor.rectangle(LENGTH, WIDTH, origin_x=-LENGTH / 2, origin_y=-WIDTH / 2)
        pad = part.part_design.create_pad(
            BLOCK_PAD, sketch, HEIGHT, direction=DIRECTION_AGAINST_SKETCH_NORMAL
        )
        part.update()
        assert pad.direction == DIRECTION_AGAINST_SKETCH_NORMAL
        assert part.measurement.measure().cog_mm[2] == pytest.approx(-HEIGHT / 2)
        pad.set_direction(DIRECTION_ALONG_SKETCH_NORMAL)
        part.update()
        assert part.measurement.measure().cog_mm[2] == pytest.approx(HEIGHT / 2)
    finally:
        _cleanup(part)


def test_an_offset_plane_is_edited_and_protected_while_a_sketch_uses_it(part: Any) -> None:
    _skip_if_ours_exist(part)
    plane_set_existed = GEOMETRICAL_SET_NAME in [
        s.name for s in part.inspect.geometrical_sets()
    ]

    try:
        plane = part.planes.create_offset(LIFT_PLANE, "XY", 40.0)
        part.update()
        sketch = part.sketches.create(LIFT_SKETCH, support=plane)
        with sketch.edit() as editor:
            editor.circle(0.0, 0.0, 6.0)
        part.part_design.create_pad(LIFT_PAD, sketch, 5.0)
        part.update()
        assert part.measurement.measure().cog_mm[2] == pytest.approx(42.5)

        plane.set_offset(55.0)
        assert part.is_up_to_date() is False, "set_offset must not rebuild"
        part.update()
        assert plane.offset == pytest.approx(55.0)
        assert part.measurement.measure().cog_mm[2] == pytest.approx(57.5)
        fresh = Catia.attach().active_part().planes.get(LIFT_PLANE)
        assert fresh.offset == pytest.approx(55.0)

        # The plane holds a sketch: deleting it is refused and nothing changes.
        assert part.planes.dependents(plane) == [LIFT_SKETCH]
        with pytest.raises(ReferenceInUseError, match=LIFT_SKETCH):
            part.planes.remove(plane)
        assert LIFT_PLANE in part.planes.names()
        assert LIFT_SKETCH in part.sketches.names()
        assert LIFT_PAD in [p.name for p in part.part_design.pads]
        assert part.is_up_to_date()
        with pytest.raises(ReferenceInUseError):
            part.planes.remove_geometrical_set()

        # Removing the dependents first makes the plane free to go.
        part.part_design.remove_pad(LIFT_PAD)  # takes its sketch with it
        part.update()
        assert part.planes.dependents(plane) == []
        part.planes.remove(plane)
        part.update()
        assert LIFT_PLANE not in part.planes.names()
        assert part.is_up_to_date()
    finally:
        _cleanup(part, plane_set_existed)


def test_update_issues_show_what_catia_reports_after_a_failure(part: Any) -> None:
    _skip_if_ours_exist(part)

    try:
        _build_block_with_hole(part)
        edge = (
            part.topology.edges(body="PartBody").query()
            .lines().parallel(Z).nearest((LENGTH / 2, WIDTH / 2, HEIGHT / 2)).one()
        )
        part.part_design.create_edge_fillet(FILLET, edge, 4.0)
        part.update()
        assert part.inspect.update_issues() == ()

        pad = part.part_design.get_pad(BLOCK_PAD)
        pad.deactivate()
        with pytest.raises(PartUpdateError) as failure:
            part.update()

        issues = {issue.name: issue for issue in part.inspect.update_issues()}
        assert issues[BLOCK_PAD].active is False, "the suppressed pad is reported"
        assert issues[FILLET].up_to_date is False, "the fillet is where it stopped"
        attached = {issue.name for issue in failure.value.issues}
        assert {BLOCK_PAD, FILLET} <= attached

        pad.activate()
        part.update()
        assert part.inspect.update_issues() == ()
        assert part.is_up_to_date()
    finally:
        _cleanup(part)
