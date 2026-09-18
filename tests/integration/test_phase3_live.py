"""Live checks for Phase 3: circular patterns, booleans, constraint removal, suppression.

Each test builds its own `AUTO3DX_IT_P3_*` objects on the disposable Part named by
`AUTO3DX_LIVE_PART`, proves one capability against the running CATIA, and removes exactly
what it made. Nothing is saved.

What only a live session can show:

* a circular pattern of a pocket removes exactly the extra holes' worth of material, and
  its instance count is editable afterwards;
* a boolean consumes its tool body, changes the target's volume by the expected amount,
  and cannot be removed without acknowledging that the consumed body goes too;
* a constraint is removed without breaking the sketch solver;
* a suppressed feature loses its geometric effect and gets it back, while older topology
  snapshots are refused.
"""

import math
import sys
from typing import Any

import pytest

pytestmark = pytest.mark.integration

if sys.platform != "win32":
    pytest.skip("Windows COM is required.", allow_module_level=True)

pytest.importorskip("pywintypes", reason="pywin32 is required.")

from auto_3dx import Catia  # noqa: E402
from auto_3dx.errors import (  # noqa: E402
    Auto3dxError,
    BooleanOperationError,
    CatiaConnectionError,
    ConstraintNotFoundError,
    CrossBodyReferenceError,
    NoActiveEditorError,
    NoActivePartError,
    StaleSnapshotError,
)
from auto_3dx.geometry.planes import GEOMETRICAL_SET_NAME  # noqa: E402

PREFIX = "AUTO3DX_IT_P3_"
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


def _skip_if_ours_exist(part: Any, names: "set[str]") -> None:
    existing = (
        set(part.sketches.names())
        | set(part.bodies.names())
        | {feature.name for feature in part.inspect.features()}
    )
    if names & existing:
        pytest.skip("Objects with this test's names already exist; they are not ours.")


def _build_disc_with_one_hole(part: Any) -> None:
    """A flange-like disc whose single bolt hole is the pattern seed."""
    sketch = part.sketches.create(DISC_SKETCH, support="XY")
    with sketch.edit() as editor:
        editor.circle(0.0, 0.0, DISC_DIAMETER / 2)
    part.part_design.create_pad(DISC_PAD, sketch, DISC_HEIGHT)
    part.update()
    # The pocket has to cut DOWN into the pad, so its sketch sits on a plane above it.
    plane = part.planes.create_offset(TOP_PLANE, "XY", DISC_HEIGHT)
    part.update()
    hole = part.sketches.create(HOLE_SKETCH, support=plane)
    with hole.edit() as editor:
        editor.circle(HOLE_X, 0.0, HOLE_RADIUS)
    part.part_design.create_pocket(HOLE_POCKET, hole, HOLE_DEPTH)
    part.update()


def _build_tool_body(part: Any) -> Any:
    body = part.bodies.create(TOOL_BODY)
    with part.work_in(body):
        sketch = part.sketches.create(f"{TOOL_BODY}_SKETCH", support="XY")
        with sketch.edit() as editor:
            editor.circle(0.0, 0.0, TOOL_RADIUS)
        part.part_design.create_pad(f"{TOOL_BODY}_PAD", sketch, TOOL_HEIGHT)
    body.update()
    return body


def _cleanup(part: Any, plane_set_existed: bool = True) -> None:
    for name in list(part.bodies.names()):
        if name.startswith(PREFIX):
            try:
                part.bodies.remove(name, delete_contents=True)
            except Auto3dxError:
                pass
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
        except Auto3dxError:
            pass
    sdk_set = [
        item for item in part.inspect.geometrical_sets() if item.name == GEOMETRICAL_SET_NAME
    ]
    if not plane_set_existed and sdk_set and not sdk_set[0].elements:
        part.planes.remove_geometrical_set()
    part.update()


def test_a_circular_pattern_repeats_a_pocket_around_the_z_axis(part: Any) -> None:
    _skip_if_ours_exist(part, {DISC_SKETCH, DISC_PAD, HOLE_POCKET, PATTERN})
    plane_set_existed = GEOMETRICAL_SET_NAME in [
        item.name for item in part.inspect.geometrical_sets()
    ]

    try:
        _build_disc_with_one_hole(part)
        one_hole = part.measurement.measure().volume_mm3

        seed = part.part_design.get_pocket(HOLE_POCKET)
        pattern = part.part_design.create_circular_pattern(PATTERN, seed, INSTANCES, SPACING)
        assert part.is_up_to_date() is False, "creation must not rebuild on its own"
        part.update()

        patterned = part.measurement.measure().volume_mm3
        assert one_hole - patterned == pytest.approx((INSTANCES - 1) * HOLE_VOLUME, rel=1e-6)
        assert pattern.angular_instances == INSTANCES
        assert pattern.angular_spacing_deg == pytest.approx(SPACING)
        assert pattern.radial_instances == 1

        # A fresh wrapper finds it by name and reads the same values.
        fresh = Catia.attach().active_part().part_design.get_circular_pattern(PATTERN)
        assert fresh.angular_instances == INSTANCES
        assert [item.name for item in part.part_design.circular_patterns] == [PATTERN]

        fresh.set_angular_instances(8)
        fresh.set_angular_spacing_deg(45.0)
        part.update()
        eight = part.measurement.measure().volume_mm3
        assert one_hole - eight == pytest.approx(7 * HOLE_VOLUME, rel=1e-6)
        assert part.part_design.get_circular_pattern(PATTERN).angular_instances == 8

        part.part_design.remove_circular_pattern(PATTERN)
        part.update()
        assert part.measurement.measure().volume_mm3 == pytest.approx(one_hole, rel=1e-9)
        assert HOLE_POCKET in [f.name for f in part.part_design.pockets], "the seed stays"
    finally:
        _cleanup(part, plane_set_existed)


def test_a_pattern_seed_from_another_body_is_refused(part: Any) -> None:
    _skip_if_ours_exist(part, {DISC_SKETCH, TOOL_BODY})

    try:
        _build_disc_with_one_hole(part)
        _build_tool_body(part)
        with part.work_in(TOOL_BODY):
            tool_pad = part.part_design.get_pad(f"{TOOL_BODY}_PAD")
        part.update()
        assert part.is_up_to_date()

        with pytest.raises(CrossBodyReferenceError):
            part.part_design.create_circular_pattern(PATTERN, tool_pad, INSTANCES, SPACING)
        assert part.part_design.circular_patterns == []
        assert part.is_up_to_date(), "a refused call must not have touched the model"
    finally:
        _cleanup(part, plane_set_existed=False)


def test_a_boolean_remove_consumes_its_tool_body(part: Any) -> None:
    _skip_if_ours_exist(part, {DISC_SKETCH, TOOL_BODY, BOOLEAN})

    try:
        _build_disc_with_one_hole(part)
        before = part.measurement.measure().volume_mm3
        _build_tool_body(part)
        assert TOOL_BODY in part.bodies.names()

        operation = part.part_design.create_boolean_remove(BOOLEAN, TOOL_BODY)
        part.update()

        after = part.measurement.measure().volume_mm3
        assert before - after == pytest.approx(OVERLAP_VOLUME, rel=1e-3)
        assert operation.tool_body_name == TOOL_BODY
        assert operation.operation == "Remove"
        # The tool body is consumed: it is no longer one of the Part's bodies.
        assert TOOL_BODY not in part.bodies.names()

        fresh = Catia.attach().active_part()
        rediscovered = fresh.part_design.get_boolean(BOOLEAN)
        assert rediscovered.tool_body_name == TOOL_BODY
        assert [item.name for item in fresh.part_design.boolean_operations] == [BOOLEAN]

        # Removal is refused until the caller accepts losing the consumed body.
        with pytest.raises(BooleanOperationError, match=TOOL_BODY):
            part.part_design.remove_boolean(BOOLEAN)
        assert BOOLEAN in [item.name for item in part.part_design.boolean_operations]

        part.part_design.remove_boolean(BOOLEAN, delete_consumed_body=True)
        part.update()
        assert part.part_design.boolean_operations == []
        assert part.measurement.measure().volume_mm3 == pytest.approx(before, rel=1e-9)
        assert TOOL_BODY not in part.bodies.names(), "the consumed body does not come back"
    finally:
        _cleanup(part, plane_set_existed=False)


def test_a_boolean_refuses_an_impossible_tool_body(part: Any) -> None:
    _skip_if_ours_exist(part, {DISC_SKETCH})

    try:
        _build_disc_with_one_hole(part)

        with pytest.raises(BooleanOperationError, match="own tool"):
            part.part_design.create_boolean_remove(BOOLEAN, "PartBody")
        with pytest.raises(BooleanOperationError):
            part.part_design.create_boolean_remove(BOOLEAN, "NO_SUCH_BODY")
        assert part.part_design.boolean_operations == []
        assert part.is_up_to_date()
    finally:
        _cleanup(part, plane_set_existed=False)


def test_a_constraint_is_removed_without_breaking_the_sketch(part: Any) -> None:
    _skip_if_ours_exist(part, {CON_SKETCH})

    try:
        sketch = part.sketches.create(CON_SKETCH, support="XY")
        with sketch.edit() as editor:
            first = editor.line(-90.0, -90.0, -50.0, -90.0)
            second = editor.line(-90.0, -70.0, -50.0, -70.0)
            third = editor.line(-90.0, -50.0, -50.0, -50.0)
            editor.parallel(first, second)
            editor.parallel(first, third)
        part.update()
        names = sketch.constraints.names()
        assert len(names) == 2

        # A fresh wrapper: nothing about the constraints is remembered in Python.
        fresh = Catia.attach().active_part().sketches.get(CON_SKETCH)
        fresh.constraints.remove(names[0])
        part.update()

        assert fresh.constraints.names() == names[1:]
        assert fresh.constraints.broken_count == 0
        assert part.is_up_to_date()

        with pytest.raises(ConstraintNotFoundError):
            fresh.constraints.remove(names[0])

        # Removing from inside an open edit block reuses that session.
        with fresh.edit():
            fresh.constraints.remove(fresh.constraints.list()[0])
        part.update()
        assert fresh.constraints.count == 0
        assert fresh.constraints.broken_count == 0
        assert part.is_up_to_date()
    finally:
        _cleanup(part)


def test_a_feature_is_suppressed_and_reactivated(part: Any) -> None:
    _skip_if_ours_exist(part, {DISC_SKETCH, FILLET})

    try:
        _build_disc_with_one_hole(part)
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
        assert fillet.is_active is False
        assert part.is_up_to_date() is False, "suppression must not rebuild on its own"
        part.update()

        suppressed = part.measurement.measure().volume_mm3
        assert suppressed > filleted, "the fillet's material comes back"
        assert FILLET in [f.name for f in part.part_design.edge_fillets], "still in the tree"

        # Suppression can change the whole solid, so older snapshots are refused.
        with pytest.raises(StaleSnapshotError):
            part.part_design.create_edge_fillet(f"{PREFIX}NEVER", snapshot[0], 1.0)

        fillet.activate()
        part.update()
        assert fillet.is_active is True
        assert part.measurement.measure().volume_mm3 == pytest.approx(filleted, rel=1e-9)

        # A fresh wrapper reads the same state from the model.
        fresh = Catia.attach().active_part().part_design.get_edge_fillet(FILLET)
        assert fresh.is_active is True
    finally:
        _cleanup(part, plane_set_existed=False)


def test_the_active_window_title_is_readable_without_raw_com(part: Any) -> None:
    catia = Catia.attach()

    title = catia.active_window_title

    assert isinstance(title, str) and title
