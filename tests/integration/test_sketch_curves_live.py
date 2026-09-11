"""Live integration checks for curved sketch geometry.

The test exercises the already-verified Factory2D paths for a closed circle,
an open arc, and a spline made from control points.  It updates the Part once
while the temporary sketch exists, then removes that sketch through the
editor's Selection in a ``finally`` block.  The document is never saved.
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
    CatiaConnectionError,
    NoActiveEditorError,
    NoActivePartError,
    SketchNotFoundError,
)


@pytest.fixture
def part() -> Any:
    """Yield the active Part, skipping when no usable session is available."""
    try:
        catia = Catia.attach()
    except CatiaConnectionError as error:
        pytest.skip(f"No running 3DEXPERIENCE session: {error}")

    try:
        active_part = catia.active_part()
    except (NoActiveEditorError, NoActivePartError) as error:
        pytest.skip(f"No Part is being edited: {error}")
    return active_part


def test_curved_sketch_geometry_round_trip(part: Any) -> None:
    """Create verified curved geometry, update the Part, and remove the sketch."""
    sketch_name = f"AUTO3DX_IT_CURVES_{uuid.uuid4().hex[:12]}"
    sketches = part.com_object.MainBody.Sketches
    sketches_before = sketches.Count
    sketch = None

    try:
        if sketch_name in part.sketches:
            pytest.skip(f"Temporary sketch name already exists: {sketch_name}")

        sketch = part.sketches.create(sketch_name, support="XY")
        with sketch.edit() as editor:
            closed_circle = editor.circle(20.0, 20.0, 5.0)
            open_arc = editor.arc(40.0, 20.0, 5.0, 0.0, math.pi)
            spline = editor.spline(
                [(0.0, 40.0), (10.0, 50.0), (20.0, 40.0)]
            )
            editor.set_construction(open_arc)
            editor.set_construction(spline)

        assert type(closed_circle).__name__ == "Circle2D"
        assert closed_circle.Radius == pytest.approx(5.0)
        assert type(open_arc).__name__ == "Circle2D"
        assert open_arc.Radius == pytest.approx(5.0)
        assert open_arc.StartPoint is not None
        assert open_arc.EndPoint is not None

        assert type(spline).__name__ == "Spline2D"
        assert spline.GetNumberOfControlPoints() == pytest.approx(3.0)
        assert type(spline.StartPoint).__name__ == "ControlPoint2D"
        assert type(spline.EndPoint).__name__ == "ControlPoint2D"

        part.update()
        assert sketch_name in part.sketches
    finally:
        if sketch is not None:
            try:
                # Sketches has no Remove method; this public call uses the
                # verified editor Selection.Clear/Add/Delete sequence.
                part.sketches.remove(sketch_name)
            except SketchNotFoundError:
                pass
            part.update()

    assert sketches.Count == sketches_before
