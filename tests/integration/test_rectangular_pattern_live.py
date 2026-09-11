"""Live round-trip for the public rectangular-pattern adapter.

The test creates only uniquely named temporary Sketch/Pad geometry, updates
the rectangular pattern, and removes the pattern through the public cleanup
API before removing its source geometry. It never saves or propagates.

It also checks that the copies actually went where the caller asked. A pattern
that updates but points the wrong way is worse than no pattern, and no COM
property reads the direction back, so the check is a measurement: the centroid
of the material the pattern ADDED follows from a mass balance on volume and
centre of gravity, and comparing it with the pad's own centroid gives the
displacement, sign included. That is the same method that established the
plane-to-axis mapping in the first place (`docs/conventions.md` 1.2.5).
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
)

RECTANGLE_WIDTH_MM = 20.0
RECTANGLE_HEIGHT_MM = 15.0
PAD_HEIGHT_MM = 8.0
# Deliberately far apart, so every copy lands clear of whatever the open Part
# already contains and the added volume is exactly three whole copies. Overlap
# would make the mass balance describe a partial copy instead.
PATTERN_SPACING_X_MM = 200.0
PATTERN_SPACING_Y_MM = 200.0
PATTERN_COUNT = 2

PAD_CENTROID_MM = (RECTANGLE_WIDTH_MM / 2.0, RECTANGLE_HEIGHT_MM / 2.0, PAD_HEIGHT_MM / 2.0)
ONE_COPY_VOLUME_MM3 = RECTANGLE_WIDTH_MM * RECTANGLE_HEIGHT_MM * PAD_HEIGHT_MM


def _added_centroid_mm(before: Any, after: Any) -> "tuple[float, float, float] | None":
    """Returns the centroid of the material one operation added to the body.

    Args:
        before: The `MassProperties` measured before the operation.
        after: The `MassProperties` measured after it.

    Returns:
        The added material's centroid in millimetres, or `None` when nothing
        measurable was added.
    """
    added = after.volume_mm3 - before.volume_mm3
    if added <= 0.0:
        return None
    return tuple(
        (after.volume_mm3 * after.cog_mm[axis] - before.volume_mm3 * before.cog_mm[axis])
        / added
        for axis in range(3)
    )


@pytest.fixture
def part() -> Any:
    """Return the active Part, skipping when no suitable session is available."""
    try:
        catia = Catia.attach()
    except CatiaConnectionError as error:
        pytest.skip(f"No running 3DEXPERIENCE session: {error}")
    try:
        return catia.active_part()
    except (NoActiveEditorError, NoActivePartError) as error:
        pytest.skip(f"No Part is being edited: {error}")


def test_rectangular_pattern_create_update_and_cleanup(part: Any) -> None:
    """Create, update, and remove a two-direction Pad pattern."""
    token = uuid.uuid4().hex[:8].upper()
    sketch_name = f"AUTO3DX_IT_PATTERN_SKETCH_{token}"
    pad_name = f"AUTO3DX_IT_PATTERN_PAD_{token}"
    body = part.com_object.MainBody
    sketches_before = int(body.Sketches.Count)
    shapes_before = int(body.Shapes.Count)
    sketch = None
    pad = None
    pattern = None

    try:
        sketch = part.sketches.create(sketch_name, support="XY")
        with sketch.edit() as editor:
            editor.rectangle(RECTANGLE_WIDTH_MM, RECTANGLE_HEIGHT_MM)
        part.update()

        pad = part.part_design.create_pad(pad_name, sketch, PAD_HEIGHT_MM)
        part.update()
        before = part.measurement.measure(body)

        pattern = part.part_design.create_rectangular_pattern(
            pad,
            number_in_direction_1=PATTERN_COUNT,
            number_in_direction_2=PATTERN_COUNT,
            spacing_in_direction_1=PATTERN_SPACING_X_MM,
            spacing_in_direction_2=PATTERN_SPACING_Y_MM,
            direction_1="X",
            direction_2="Y",
        )
        part.update()

        assert type(pattern.com_object).__name__ == "RectPattern"
        assert int(body.Shapes.Count) > shapes_before

        # Two counts in each direction means three added copies, at
        # (+x, 0), (0, +y) and (+x, +y) from the original, so their combined
        # centroid sits two thirds of each spacing away along each axis.
        after = part.measurement.measure(body)
        centroid = _added_centroid_mm(before, after)
        assert centroid is not None
        added_copies = (after.volume_mm3 - before.volume_mm3) / ONE_COPY_VOLUME_MM3
        if math.isclose(added_copies, 3.0, rel_tol=0.0, abs_tol=1e-6):
            # Only a clean three copies lets the centroid be predicted exactly;
            # if the open Part happens to overlap a copy, the round trip above
            # still stands and only this direction check is skipped.
            assert centroid[0] - PAD_CENTROID_MM[0] == pytest.approx(
                2.0 * PATTERN_SPACING_X_MM / 3.0, abs=1e-3
            )
            assert centroid[1] - PAD_CENTROID_MM[1] == pytest.approx(
                2.0 * PATTERN_SPACING_Y_MM / 3.0, abs=1e-3
            )
            assert centroid[2] - PAD_CENTROID_MM[2] == pytest.approx(0.0, abs=1e-3)
    finally:
        if pattern is not None:
            try:
                part.part_design.remove_rectangular_pattern(pattern)
            except Auto3dxError:
                pass
        if pad is not None:
            try:
                part.part_design.remove_pad(pad_name)
            except Auto3dxError:
                pass
        if sketch is not None:
            try:
                part.sketches.remove(sketch_name)
            except Auto3dxError:
                pass
        part.update()

    assert int(body.Sketches.Count) == sketches_before
    assert int(body.Shapes.Count) == shapes_before
