"""Live round-trip for edge fillets and chamfers.

These were the first face-or-edge features this project could reach at all, and
they gate roughly eighty more, so they are worth pinning against a real session
rather than only against fakes.

Three measured behaviours are asserted here because no fake can prove them:

* an edge snapshot is taken from the solid as it stands, and the edge count
  CHANGES once a fillet is added, which is why a snapshot must be re-taken
  rather than reused as an identity;
* a reused snapshot really does fail against a live model, which is what the
  library's staleness guard exists to turn into a clear error;
* a chamfer survives the update in the mode this library hardcodes.

Everything created is removed in a `finally`. A failed update leaves the feature
in the tree and poisons every later update until it is removed, so cleanup runs
even for a feature whose update failed. The document is never saved.
"""

import sys
import uuid
import warnings
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
    SelectionNotRestoredWarning,
    StaleSnapshotError,
)
from auto_3dx.geometry.part_design import (  # noqa: E402
    CHAMFER_ORIENTATION_0,
    CHAMFER_PROPAGATION_0,
)

RECTANGLE_SIDE = 24.0
PAD_HEIGHT = 14.0
FILLET_RADIUS = 1.0
CHAMFER_LENGTH = 1.5
CHAMFER_ANGLE = 45.0


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


def _cleanup(part: Any, removals: "list[tuple[str, str]]", sketch_name: str) -> None:
    """Removes features then the sketch, tolerating anything already gone."""
    for method, name in removals:
        try:
            getattr(part.part_design, method)(name)
        except Auto3dxError:
            pass
    try:
        part.sketches.remove(sketch_name)
    except Auto3dxError:
        pass
    part.update()


def test_edge_fillets_and_chamfer_round_trip(part: Any) -> None:
    """Two fillets and a chamfer on one pad, then the model back as it was."""
    token = uuid.uuid4().hex[:8].upper()
    sketch_name = f"AUTO3DX_IT_EDGE_SKETCH_{token}"
    pad_name = f"AUTO3DX_IT_EDGE_PAD_{token}"
    first_fillet = f"AUTO3DX_IT_FILLET_A_{token}"
    second_fillet = f"AUTO3DX_IT_FILLET_B_{token}"
    chamfer_name = f"AUTO3DX_IT_CHAMFER_{token}"
    body = part.com_object.MainBody
    sketches_before = int(body.Sketches.Count)
    shapes_before = int(body.Shapes.Count)
    removals = [
        ("remove_chamfer", chamfer_name),
        ("remove_edge_fillet", second_fillet),
        ("remove_edge_fillet", first_fillet),
        ("remove_pad", pad_name),
    ]

    try:
        sketch = part.sketches.create(sketch_name, support="XY")
        with sketch.edit() as editor:
            editor.rectangle(RECTANGLE_SIDE, RECTANGLE_SIDE)
        part.update()
        part.part_design.create_pad(pad_name, sketch, PAD_HEIGHT)
        part.update()

        snapshot = part.topology.edges()
        assert len(snapshot) > 0
        # The descriptor is the BRep string; it is opaque and cannot be stored
        # and resolved later, but it must at least be readable for logging.
        assert snapshot[0].descriptor
        assert snapshot[0].index == 1
        edges_before = len(snapshot)

        fillet = part.part_design.create_edge_fillet(
            first_fillet, snapshot[0], FILLET_RADIUS
        )
        part.update()
        assert fillet.name == first_fillet
        assert first_fillet in [feature.name for feature in part.part_design.edge_fillets]
        assert first_fillet not in [feature.name for feature in part.part_design.chamfers]
        assert first_fillet not in [feature.name for feature in part.part_design.pads]

        # The snapshot is now a generation behind, and reusing it against a
        # live model genuinely fails -- measured on a plain cube, for the next
        # edge, the middle edge and the last edge alike. The guard turns that
        # coin flip into a clear error before anything reaches COM.
        with pytest.raises(StaleSnapshotError):
            part.part_design.create_edge_fillet(
                second_fillet, snapshot[1], FILLET_RADIUS
            )

        # A fillet changes the topology, so the edge count moves. That is why a
        # snapshot describes one model state and an index is not an identity.
        refreshed = part.topology.edges()
        assert len(refreshed) != edges_before

        second = part.part_design.create_edge_fillet(
            second_fillet, refreshed[0], FILLET_RADIUS
        )
        part.update()
        assert second.name == second_fillet

        refreshed = part.topology.edges()

        chamfer = part.part_design.create_chamfer(
            chamfer_name,
            refreshed[0],
            CHAMFER_LENGTH,
            CHAMFER_ANGLE,
            CHAMFER_PROPAGATION_0,
            CHAMFER_ORIENTATION_0,
        )
        part.update()
        assert chamfer.name == chamfer_name
        assert chamfer_name in [feature.name for feature in part.part_design.chamfers]
        assert chamfer_name not in [
            feature.name for feature in part.part_design.edge_fillets
        ]
    finally:
        _cleanup(part, removals, sketch_name)

    assert int(body.Sketches.Count) == sketches_before
    assert int(body.Shapes.Count) == shapes_before


def test_snapshot_is_repeatable_while_the_model_is_unchanged(part: Any) -> None:
    """Two searches in a row agree exactly, which is what makes an index usable."""
    first = part.topology.edges()
    second = part.topology.edges()

    assert len(first) == len(second)
    assert [edge.index for edge in first] == [edge.index for edge in second]
    assert [edge.descriptor for edge in first] == [edge.descriptor for edge in second]


def _selected(selection: Any) -> "list[tuple[str, str]]":
    """Reads the selection as (name, type) pairs, in order."""
    return [
        (str(selection.Item(i).Value.Name), type(selection.Item(i).Value).__name__)
        for i in range(1, int(selection.Count) + 1)
    ]


def test_snapshots_restore_the_user_selection_and_stay_usable(part: Any) -> None:
    """A non-empty selection survives both searches, and the references still build."""
    selection = Catia.attach().active_editor().Selection
    if int(selection.Count) != 0:
        pytest.skip("The user has something selected; this test only restores to empty.")
    token = uuid.uuid4().hex[:8].upper()
    sketch_name = f"AUTO3DX_IT_SEL_SKETCH_{token}"
    pad_name = f"AUTO3DX_IT_SEL_PAD_{token}"
    fillet_name = f"AUTO3DX_IT_SEL_FILLET_{token}"
    body = part.com_object.MainBody
    sketches_before = int(body.Sketches.Count)
    shapes_before = int(body.Shapes.Count)
    removals = [("remove_edge_fillet", fillet_name), ("remove_pad", pad_name)]

    try:
        sketch = part.sketches.create(sketch_name, support="XY")
        with sketch.edit() as editor:
            editor.rectangle(RECTANGLE_SIDE, RECTANGLE_SIDE)
        pad = part.part_design.create_pad(pad_name, sketch, PAD_HEIGHT)
        part.update()

        # Features and sketches, the objects a user picks in the tree.
        selection.Clear()
        selection.Add(pad.com_object)
        selection.Add(sketch.com_object)
        before = _selected(selection)
        assert [kind for _, kind in before] == ["Pad", "Sketch"]
        with warnings.catch_warnings():
            warnings.simplefilter("error", SelectionNotRestoredWarning)
            part.topology.faces()
        assert _selected(selection) == before

        # Topology items, what a user picks in the 3D view.
        selection.Clear()
        selection.Search("Topology.Face,all")
        before = _selected(selection)
        assert len(before) > 1
        with warnings.catch_warnings():
            warnings.simplefilter("error", SelectionNotRestoredWarning)
            part.topology.faces()
        assert _selected(selection) == before

        # Known CATIA limit: straight after a search, faces plus the Pad that owns
        # them can be selected, but once the faces are re-added the Pad is silently
        # refused. The snapshot must still be returned, with a warning.
        selection.Clear()
        selection.Search("Topology.Face,all")
        face_count = int(selection.Count)
        selection.Add(pad.com_object)
        assert int(selection.Count) == face_count + 1
        with pytest.warns(SelectionNotRestoredWarning):
            edges = part.topology.edges()
        assert len(edges) > 0

        # References read before the restore must still drive a feature.
        part.part_design.create_edge_fillet(fillet_name, edges[0], FILLET_RADIUS)
        part.update()
        assert part.is_up_to_date()
    finally:
        selection.Clear()
        _cleanup(part, removals, sketch_name)

    assert int(selection.Count) == 0
    assert int(body.Sketches.Count) == sketches_before
    assert int(body.Shapes.Count) == shapes_before
