"""Live sketch/pad round-trip against a running 3DEXPERIENCE session.

Requires an open Part editor. Everything this test creates is removed again in
a `finally` block, and the document is never saved (docs/conventions.md: Save
is never called on any code path).

NOTE: the basename here is deliberately `test_geometry_live.py`, not
`test_geometry.py` -- there are no `__init__.py` files under `tests/`, so a
duplicate basename between `tests/unit` and `tests/integration` breaks
collection.
"""

import sys

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
)
from auto_3dx.geometry.sketch import SUPPORT_XY  # noqa: E402

SKETCH_NAME = "AUTO3DX_IT_SKETCH"
PAD_NAME = "AUTO3DX_IT_PAD"
INITIAL_HEIGHT = 20.0
UPDATED_HEIGHT = 35.0
RECTANGLE_WIDTH = 60.0
RECTANGLE_HEIGHT = 40.0


@pytest.fixture
def part():
    """Yields the active Part, skipping when no suitable session is available."""
    try:
        catia = Catia.attach()
    except CatiaConnectionError as error:
        pytest.skip(f"No running 3DEXPERIENCE session: {error}")
    try:
        yield catia.active_part()
    except (NoActiveEditorError, NoActivePartError) as error:
        pytest.skip(f"No Part is being edited: {error}")


def test_ensure_sketch_rectangle_pad_round_trip(part) -> None:
    """`ensure` a sketch, draw a rectangle, pad it, then `ensure_pad` a new height."""
    raw_body = part.com_object.MainBody
    sketches_count_before = raw_body.Sketches.Count
    shapes_count_before = raw_body.Shapes.Count

    if SKETCH_NAME in part.sketches:
        pytest.skip(f"{SKETCH_NAME} already exists in this model; clean it up first.")
    existing_pad_names = {pad.name for pad in part.part_design.pads}
    if PAD_NAME in existing_pad_names:
        pytest.skip(f"{PAD_NAME} already exists in this model; clean it up first.")

    try:
        sketch = part.sketches.ensure(SKETCH_NAME, support=SUPPORT_XY)
        assert sketch.support() == SUPPORT_XY

        with sketch.edit() as editor:
            editor.rectangle(RECTANGLE_WIDTH, RECTANGLE_HEIGHT)
        part.update()

        pad = part.part_design.create_pad(PAD_NAME, sketch, INITIAL_HEIGHT)
        part.update()

        assert pad.height == pytest.approx(INITIAL_HEIGHT)
        assert pad.sketch().name == sketch.name

        pad = part.part_design.ensure_pad(PAD_NAME, sketch, UPDATED_HEIGHT)
        part.update()

        assert pad.height == pytest.approx(UPDATED_HEIGHT)
    finally:
        # Deleting a Pad cascade-deletes its Sketch (verified,
        # docs/conventions.md 1.2: Shapes 1->0, Sketches 1->0), so the sketch
        # removal below may legitimately fail with the sketch already gone.
        try:
            part.part_design.remove_pad(PAD_NAME)
        except Auto3dxError:
            pass
        try:
            part.sketches.remove(SKETCH_NAME)
        except Auto3dxError:
            pass
        part.update()

    assert raw_body.Sketches.Count == sketches_count_before
    assert raw_body.Shapes.Count == shapes_count_before
