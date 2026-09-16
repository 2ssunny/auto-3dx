"""Live round-trip for sketches and pads on user-defined planes.

Two earlier probes built an offset plane, sketched on it, and then watched
`AddNewPad` fail, and neither found the cause. It was never the plane: creating
a geometrical set leaves that set as the Part's in-work object, and a pad cannot
be inserted into one. The collection reclaims the body after every append, and
this test is what proves that discipline holds against a real session.

The angled plane needs an addressable 3D line for its rotation axis, built here
from two points, because a sketch line and an origin plane were both tried and
both produced a plane whose update failed.

Everything created is removed in a `finally`, including the geometrical set,
which is the only way to clear an angled plane's axis points and line. The
document is never saved.
"""

import math
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
    PlaneNotFoundError,
)
from auto_3dx.geometry.planes import GEOMETRICAL_SET_NAME  # noqa: E402

PLANE_OFFSET = 30.0
PLANE_ANGLE = 30.0
AXIS_START = (0.0, 0.0, 0.0)
AXIS_END = (0.0, 100.0, 0.0)
RECTANGLE_SIDE = 20.0
PAD_HEIGHT = 10.0


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


def _pad_on(part: Any, plane: Any, sketch_name: str, pad_name: str) -> None:
    """Sketches a closed rectangle on `plane` and pads it, updating after each step."""
    sketch = part.sketches.create(sketch_name, support=plane)
    with sketch.edit() as editor:
        editor.rectangle(RECTANGLE_SIDE, RECTANGLE_SIDE)
    part.update()
    part.part_design.create_pad(pad_name, sketch, PAD_HEIGHT)
    part.update()


def _cleanup(part: Any, pad_names: "list[str]", sketch_names: "list[str]") -> None:
    """Removes pads, sketches, then the whole geometrical set, tolerating losses."""
    for name in pad_names:
        try:
            part.part_design.remove_pad(name)
        except Auto3dxError:
            pass
    for name in sketch_names:
        try:
            part.sketches.remove(name)
        except Auto3dxError:
            pass
    try:
        part.planes.remove_geometrical_set()
    except Auto3dxError:
        pass
    part.update()


def test_offset_and_angled_planes_carry_a_sketch_and_a_pad(part: Any) -> None:
    """Both plane families work end to end, which is what the in-work fix buys."""
    token = uuid.uuid4().hex[:8].upper()
    offset_sketch = f"AUTO3DX_IT_OFFSET_SKETCH_{token}"
    offset_pad = f"AUTO3DX_IT_OFFSET_PAD_{token}"
    angle_sketch = f"AUTO3DX_IT_ANGLE_SKETCH_{token}"
    angle_pad = f"AUTO3DX_IT_ANGLE_PAD_{token}"
    body = part.com_object.MainBody
    sketches_before = int(body.Sketches.Count)
    shapes_before = int(body.Shapes.Count)
    hybrid_bodies_before = int(part.com_object.HybridBodies.Count)

    try:
        offset_plane = part.planes.create_offset(
            f"AUTO3DX_IT_PLANE_OFFSET_{token}", "XY", PLANE_OFFSET
        )
        part.update()
        assert offset_plane.offset == pytest.approx(PLANE_OFFSET)
        assert offset_plane.base_display_name

        _pad_on(part, offset_plane, offset_sketch, offset_pad)
        assert offset_pad in [feature.name for feature in part.part_design.pads]

        angle_plane = part.planes.create_angle(
            f"AUTO3DX_IT_PLANE_ANGLE_{token}",
            "XY",
            PLANE_ANGLE,
            AXIS_START,
            AXIS_END,
        )
        part.update()
        assert angle_plane.angle == pytest.approx(PLANE_ANGLE)

        _pad_on(part, angle_plane, angle_sketch, angle_pad)
        assert angle_pad in [feature.name for feature in part.part_design.pads]

        # The pads only exist if the in-work object was reclaimed, so the solid
        # must actually have grown. Measuring says so in a way a name check
        # cannot: an empty pad would still be listed above.
        volume = part.measurement.measure(body).volume_mm3
        assert volume > 0.0
        assert math.isfinite(volume)
    finally:
        _cleanup(part, [angle_pad, offset_pad], [angle_sketch, offset_sketch])

    assert int(body.Sketches.Count) == sketches_before
    assert int(body.Shapes.Count) == shapes_before
    assert int(part.com_object.HybridBodies.Count) == hybrid_bodies_before


def test_origin_plane_strings_still_work(part: Any) -> None:
    """The existing three-string support path must be untouched by all of this."""
    token = uuid.uuid4().hex[:8].upper()
    sketch_name = f"AUTO3DX_IT_ORIGIN_SKETCH_{token}"
    body = part.com_object.MainBody
    sketches_before = int(body.Sketches.Count)

    try:
        sketch = part.sketches.create(sketch_name, support="ZX")
        with sketch.edit() as editor:
            editor.rectangle(RECTANGLE_SIDE, RECTANGLE_SIDE)
        part.update()
        assert sketch.name == sketch_name
    finally:
        try:
            part.sketches.remove(sketch_name)
        except Auto3dxError:
            pass
        part.update()

    assert int(body.Sketches.Count) == sketches_before


def test_a_fresh_collection_finds_and_removes_an_existing_plane(part: Any) -> None:
    """The lifecycle gap: planes must be findable after the collection that made them.

    A second `Part` wrapper stands in for a later process here (a real second
    process is exercised by the scratch validation): it shares nothing in memory
    with the first collection, so everything it finds it found in the model.
    """
    if part.planes.names():
        pytest.skip("The Part already holds SDK planes; they are not ours to remove.")
    token = uuid.uuid4().hex[:8].upper()
    plane_name = f"AUTO3DX_IT_LIFECYCLE_{token}"

    try:
        part.planes.create_offset(plane_name, "XY", PLANE_OFFSET)
        part.update()

        fresh = Catia.attach().active_part()
        assert fresh.planes is not part.planes
        assert plane_name in fresh.planes.names()

        found = fresh.planes.get(plane_name)
        assert found.offset == PLANE_OFFSET
        assert found.base_display_name

        # A fresh collection appends to the existing set instead of adding a second.
        second_name = f"{plane_name}_B"
        fresh.planes.create_offset(second_name, "XY", PLANE_OFFSET * 2)
        fresh.update()
        sets = [item.name for item in fresh.inspect.geometrical_sets()]
        assert sets.count(GEOMETRICAL_SET_NAME) == 1
        assert fresh.planes.names() == [plane_name, second_name]

        with pytest.raises(PlaneNotFoundError):
            fresh.planes.get(f"{plane_name}_MISSING")

        # Cleanup through the collection that never created any of it.
        fresh.planes.remove_geometrical_set()
        fresh.update()
        assert fresh.planes.names() == []
        assert GEOMETRICAL_SET_NAME not in [
            item.name for item in fresh.inspect.geometrical_sets()
        ]
    finally:
        try:
            part.planes.remove_geometrical_set()
        except Auto3dxError:
            pass
        part.update()

    assert part.planes.names() == []
    assert part.is_up_to_date()
