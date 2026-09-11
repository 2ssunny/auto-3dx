"""Live round-trip for shell, thickness and hole.

These are the face half of the topology-reference unlock. Fillet and chamfer
take an edge; these three take a face, and until faces could be named none of
them was reachable at all.

Each one gets its own pad, built and torn down independently, because they are
not compatible operations to stack on one solid: a shell hollows the body out
and a hole cuts into it, so sharing a pad would test their interaction rather
than each feature. Each also takes its own fresh face snapshot, which is the
discipline the library enforces anyway.

Everything created is removed in a `finally`. A failed update leaves the feature
in the tree and makes every later update fail until it is removed, so cleanup
runs even when a feature's update failed. The document is never saved.
"""

import sys
import uuid
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
    StaleSnapshotError,
)

RECTANGLE_SIDE = 40.0
PAD_HEIGHT = 20.0
SHELL_INTERNAL = 2.0
SHELL_EXTERNAL = 0.0
THICKNESS_OFFSET = 3.0
HOLE_DEPTH = 5.0


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


def _build_pad(part: Any, sketch_name: str, pad_name: str) -> None:
    """Builds the pad a face feature is applied to."""
    sketch = part.sketches.create(sketch_name, support="XY")
    with sketch.edit() as editor:
        editor.rectangle(RECTANGLE_SIDE, RECTANGLE_SIDE)
    part.update()
    part.part_design.create_pad(pad_name, sketch, PAD_HEIGHT)
    part.update()


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


def _run_face_feature(
    part: Any,
    label: str,
    build: Any,
    remove_method: str,
    listing: str,
) -> None:
    """Builds one face feature on its own pad, checks it, and tears it all down.

    Args:
        part: The `Part` wrapper.
        label: A short tag used to name every object this creates.
        build: Takes the feature name and a `Face`, and creates the feature.
        remove_method: The `PartDesign` method that removes it.
        listing: The `PartDesign` property that should list it.
    """
    token = uuid.uuid4().hex[:8].upper()
    sketch_name = f"AUTO3DX_IT_{label}_SKETCH_{token}"
    pad_name = f"AUTO3DX_IT_{label}_PAD_{token}"
    feature_name = f"AUTO3DX_IT_{label}_{token}"
    body = part.com_object.MainBody
    sketches_before = int(body.Sketches.Count)
    shapes_before = int(body.Shapes.Count)

    try:
        _build_pad(part, sketch_name, pad_name)

        snapshot = part.part_design.snapshot_faces()
        assert len(snapshot) > 0
        assert snapshot[0].descriptor
        assert snapshot[0].index == 1

        feature = build(feature_name, snapshot[0])
        part.update()

        assert feature.name == feature_name
        assert feature_name in [f.name for f in getattr(part.part_design, listing)]
        # A face feature must never be reported as a pad.
        assert feature_name not in [f.name for f in part.part_design.pads]

        # The snapshot is a generation behind now, and the library refuses it
        # rather than letting CATIA succeed or fail unpredictably.
        with pytest.raises(StaleSnapshotError):
            build(f"{feature_name}_AGAIN", snapshot[0])
    finally:
        _cleanup(
            part,
            [(remove_method, feature_name), ("remove_pad", pad_name)],
            sketch_name,
        )

    assert int(body.Sketches.Count) == sketches_before
    assert int(body.Shapes.Count) == shapes_before


def test_shell_round_trip(part: Any) -> None:
    """A shell hollows the solid out through the face it is given."""
    _run_face_feature(
        part,
        "SHELL",
        lambda name, face: part.part_design.create_shell(
            name, face, SHELL_INTERNAL, SHELL_EXTERNAL
        ),
        "remove_shell",
        "shells",
    )


def test_thickness_round_trip(part: Any) -> None:
    """A thickness offsets one face of the solid."""
    _run_face_feature(
        part,
        "THICK",
        lambda name, face: part.part_design.create_thickness(
            name, face, THICKNESS_OFFSET
        ),
        "remove_thickness",
        "thicknesses",
    )


def test_hole_round_trip(part: Any) -> None:
    """A hole cuts into the solid from the face it is given."""
    _run_face_feature(
        part,
        "HOLE",
        lambda name, face: part.part_design.create_hole(name, face, HOLE_DEPTH),
        "remove_hole",
        "holes",
    )


def test_face_snapshot_is_repeatable_while_unchanged(part: Any) -> None:
    """Two face searches in a row agree exactly, as the edge search does."""
    first = part.part_design.snapshot_faces()
    second = part.part_design.snapshot_faces()

    assert len(first) == len(second)
    assert [face.index for face in first] == [face.index for face in second]
    assert [face.descriptor for face in first] == [face.descriptor for face in second]
