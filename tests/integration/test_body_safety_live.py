"""Live checks for the first safety batch, on the disposable Part named by `AUTO3DX_LIVE_PART`.

Each test builds its own `AUTO3DX_IT_SAFETY_*` objects, proves one safety property against
the running CATIA, and removes exactly what it made. Nothing is saved.

What is pinned here is behaviour that only a live session can show:

* a topology snapshot scoped to a body holds that body's edges, and a feature refuses an
  edge belonging to another body before CATIA is called;
* a body created inside `work_in` needs its own rebuild, cannot be measured before it, and
  is measurable after `body.update()`;
* a plane that has not been rebuilt is refused as a sketch support instead of failing with
  an opaque COM error;
* an update broken by an edit heals when the edit is rolled back, with nothing deleted.
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
    CrossBodyReferenceError,
    NoActiveEditorError,
    NoActivePartError,
    SupportNotUpdatedError,
    TargetNotUpToDateError,
)
from auto_3dx.geometry.planes import GEOMETRICAL_SET_NAME  # noqa: E402

PREFIX = "AUTO3DX_IT_SAFETY_"
MAIN_SKETCH, MAIN_PAD = f"{PREFIX}MAIN_SKETCH", f"{PREFIX}MAIN_PAD"
TOOL_BODY, TOOL_SKETCH, TOOL_PAD = (
    f"{PREFIX}TOOL_BODY",
    f"{PREFIX}TOOL_SKETCH",
    f"{PREFIX}TOOL_PAD",
)
FILLET, PLANE, PLANE_SKETCH = (
    f"{PREFIX}FILLET",
    f"{PREFIX}PLANE",
    f"{PREFIX}PLANE_SKETCH",
)
MAIN_SIDE, MAIN_HEIGHT, BROKEN_HEIGHT = 40.0, 30.0, 1.0
TOOL_SIDE, TOOL_HEIGHT, TOOL_X = 20.0, 12.0, 300.0
FILLET_RADIUS, PLANE_OFFSET = 5.0, 50.0


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
    existing = set(part.bodies.names()) | set(part.sketches.names())
    if names & existing:
        pytest.skip("Objects with this test's names already exist; they are not ours.")


def _solid_edge(edges: Any, feature_name: str) -> Any:
    """Picks an edge of the pad itself; a body's edges include its sketches' wire edges."""
    solid = [edge for edge in edges if edge.owner_feature_name == feature_name]
    assert solid, f"no edge owned by {feature_name!r}"
    return solid[0]


def _build_main_pad(part: Any) -> None:
    sketch = part.sketches.create(MAIN_SKETCH, support="XY")
    with sketch.edit() as editor:
        editor.rectangle(MAIN_SIDE, MAIN_SIDE)
    part.part_design.create_pad(MAIN_PAD, sketch, MAIN_HEIGHT)
    part.update()


def _build_tool_body(part: Any) -> Any:
    tool = part.bodies.create(TOOL_BODY)
    with part.work_in(tool):
        sketch = part.sketches.create(TOOL_SKETCH, support="XY")
        with sketch.edit() as editor:
            editor.rectangle(TOOL_SIDE, TOOL_SIDE, origin_x=TOOL_X)
        part.part_design.create_pad(TOOL_PAD, sketch, TOOL_HEIGHT)
    return tool


def _cleanup(part: Any, plane_set_existed: bool = True) -> None:
    for step in (
        lambda: part.part_design.remove_edge_fillet(FILLET),
        lambda: part.sketches.remove(PLANE_SKETCH),
        lambda: part.planes.remove(part.planes.get(PLANE)),
        lambda: part.bodies.remove(TOOL_BODY, delete_contents=True),
        lambda: part.part_design.remove_pad(MAIN_PAD),
        lambda: part.sketches.remove(MAIN_SKETCH),
    ):
        try:
            step()
        except Auto3dxError:
            pass
    sdk_set = [
        item
        for item in part.inspect.geometrical_sets()
        if item.name == GEOMETRICAL_SET_NAME
    ]
    if not plane_set_existed and sdk_set and not sdk_set[0].elements:
        part.planes.remove_geometrical_set()
    part.update()


def test_topology_is_scoped_to_a_body_and_another_body_s_edge_is_refused(
    part: Any,
) -> None:
    _skip_if_ours_exist(part, {TOOL_BODY, MAIN_SKETCH, TOOL_SKETCH})
    before = part.inspect.summary()

    try:
        _build_main_pad(part)
        tool = _build_tool_body(part)
        tool.update()
        part.update()

        main_edges = part.topology.edges(body="PartBody")
        tool_edges = part.topology.edges(body=tool)
        part_wide = part.topology.edges(body=None)
        assert {edge.owner_body_name for edge in main_edges} == {"PartBody"}
        assert {edge.owner_body_name for edge in tool_edges} == {TOOL_BODY}
        assert len(part_wide) == len(main_edges) + len(tool_edges)
        assert not {e.descriptor for e in main_edges} & {
            e.descriptor for e in tool_edges
        }

        # Inside a work context a snapshot follows that body, like sketches and features.
        with part.work_in(tool):
            assert {edge.owner_body_name for edge in part.topology.edges()} == {
                TOOL_BODY
            }

        # Faces scope the same way.
        assert {face.owner_body_name for face in part.topology.faces(body=tool)} == {
            TOOL_BODY
        }

        # The dangerous case: CATIA accepts this and fails the NEXT update instead.
        stolen = _solid_edge(part.topology.edges(body=tool), TOOL_PAD)
        with pytest.raises(CrossBodyReferenceError):
            part.part_design.create_edge_fillet(FILLET, stolen, FILLET_RADIUS)
        assert FILLET not in [feature.name for feature in part.part_design.edge_fillets]
        assert part.is_up_to_date(), "a refused call must not have touched the model"

        # The same feature on an edge of the body being built in.
        edge = _solid_edge(part.topology.edges(body="PartBody"), MAIN_PAD)
        part.part_design.create_edge_fillet(FILLET, edge, FILLET_RADIUS)
        part.update()
        assert part.is_up_to_date()
        assert FILLET in [feature.name for feature in part.part_design.edge_fillets]
    finally:
        _cleanup(part)

    after = part.inspect.summary()
    assert [(b.name, b.features, b.sketches) for b in after.bodies] == [
        (b.name, b.features, b.sketches) for b in before.bodies
    ]


def test_a_body_needs_its_own_update_before_it_can_be_measured(part: Any) -> None:
    _skip_if_ours_exist(part, {TOOL_BODY, TOOL_SKETCH})
    before = part.inspect.in_work_object()

    try:
        tool = _build_tool_body(part)
        assert tool.is_up_to_date is False

        with pytest.raises(TargetNotUpToDateError):
            part.measurement.measure(tool)

        tool.update()
        assert tool.is_up_to_date is True
        volume = part.measurement.measure(tool).volume_mm3
        assert volume == pytest.approx(TOOL_SIDE * TOOL_SIDE * TOOL_HEIGHT, rel=1e-6)

        # A fresh wrapper finds the same rebuilt body: nothing was remembered in Python.
        fresh = Catia.attach().active_part()
        assert fresh.bodies.get(TOOL_BODY).is_up_to_date is True
        assert fresh.measurement.measure(
            fresh.bodies.get(TOOL_BODY)
        ).volume_mm3 == pytest.approx(volume)
    finally:
        _cleanup(part)

    assert TOOL_BODY not in part.bodies.names()
    assert part.inspect.in_work_object() == before


def test_a_plane_is_refused_as_a_sketch_support_until_the_part_is_updated(
    part: Any,
) -> None:
    _skip_if_ours_exist(part, {PLANE_SKETCH})
    if PLANE in part.planes.names():
        pytest.skip("A plane with this test's name already exists; it is not ours.")
    plane_set_existed = GEOMETRICAL_SET_NAME in [
        item.name for item in part.inspect.geometrical_sets()
    ]

    try:
        plane = part.planes.create_offset(PLANE, "XY", PLANE_OFFSET)
        with pytest.raises(SupportNotUpdatedError):
            part.sketches.create(PLANE_SKETCH, support=plane)
        assert PLANE_SKETCH not in part.sketches.names(), "nothing was created"

        part.update()
        sketch = part.sketches.create(PLANE_SKETCH, support=plane)
        assert sketch.name == PLANE_SKETCH
    finally:
        _cleanup(part, plane_set_existed)

    assert PLANE_SKETCH not in part.sketches.names()


def test_an_update_broken_by_an_edit_heals_when_the_edit_is_rolled_back(
    part: Any,
) -> None:
    """Rolling the edit back is the first move after PartUpdateError, not deletion."""
    _skip_if_ours_exist(part, {MAIN_SKETCH})
    if FILLET in [feature.name for feature in part.part_design.edge_fillets]:
        pytest.skip("A fillet with this test's name already exists; it is not ours.")

    try:
        _build_main_pad(part)
        edge = _solid_edge(part.topology.edges(body="PartBody"), MAIN_PAD)
        part.part_design.create_edge_fillet(FILLET, edge, FILLET_RADIUS)
        part.update()
        volume = part.measurement.measure().volume_mm3

        pad = part.part_design.get_pad(MAIN_PAD)
        pad.set_height(BROKEN_HEIGHT)
        with pytest.raises(PartUpdateError):
            part.update()
        assert part.is_up_to_date() is False
        assert FILLET in [feature.name for feature in part.part_design.edge_fillets]

        pad.set_height(MAIN_HEIGHT)
        part.update()
        assert part.is_up_to_date()
        assert FILLET in [feature.name for feature in part.part_design.edge_fillets]
        healed = part.measurement.measure().volume_mm3
        assert math.isclose(healed, volume, rel_tol=1e-9)
    finally:
        _cleanup(part)

    assert MAIN_PAD not in [feature.name for feature in part.part_design.pads]
