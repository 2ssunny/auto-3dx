"""Live round-trip for Shaft, Groove and Mirror.

"Verified" here means created AND `Part.Update()` succeeded. That distinction
matters: `AddNewStiffener` and `AddNewRectPattern` both return an object whose
update then fails, leaving a broken feature in the tree, which is why neither is
implemented (`docs/conventions.md` 1.2.2.1).

Everything created is removed in a `finally`, and the document is never saved.
A revolve feature does not cascade-delete its sketch, so the sketch is removed
explicitly.
"""

import sys

import pytest

pytestmark = pytest.mark.integration

if sys.platform != "win32":
    pytest.skip("Windows COM is required.", allow_module_level=True)

pytest.importorskip("pywintypes", reason="pywin32 is required.")

from auto_3dx import Catia  # noqa: E402
from auto_3dx.errors import (  # noqa: E402
    CatiaConnectionError,
    FeatureNotFoundError,
    NoActiveEditorError,
    NoActivePartError,
    SketchNotFoundError,
)
from auto_3dx.geometry.part_design import FULL_REVOLUTION  # noqa: E402

AXIS_SKETCH = "AUTO3DX_IT_AXIS_SKETCH"
SHAFT_NAME = "AUTO3DX_IT_SHAFT"
GROOVE_NAME = "AUTO3DX_IT_GROOVE"
MIRROR_NAME = "AUTO3DX_IT_MIRROR"


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


def _axis_sketch(part, name: str):
    """Builds a sketch with a profile clear of its centre line."""
    sketch = part.sketches.create(name, support="ZX")
    with sketch.edit() as editor:
        editor.rectangle(10.0, 6.0, origin_x=20.0, origin_y=0.0)
        axis = editor.line(0.0, 0.0, 0.0, 20.0)
    sketch.set_center_line(axis)
    part.update()
    return sketch


def _cleanup(part, feature_removals, sketch_names) -> None:
    """Removes features then sketches, tolerating anything already gone."""
    for method, name in feature_removals:
        try:
            getattr(part.part_design, method)(name)
        except FeatureNotFoundError:
            pass
    for name in sketch_names:
        try:
            part.sketches.remove(name)
        except SketchNotFoundError:
            pass
    part.update()


def test_shaft_round_trip(part) -> None:
    """A shaft revolves a profile and its angle can be driven."""
    body = part.com_object.MainBody
    shapes_before = body.Shapes.Count
    sketches_before = body.Sketches.Count
    if AXIS_SKETCH in part.sketches:
        pytest.skip(f"{AXIS_SKETCH} already exists; clean it up first.")

    try:
        sketch = _axis_sketch(part, AXIS_SKETCH)
        shaft = part.part_design.create_shaft(SHAFT_NAME, sketch)
        part.update()

        assert shaft.name == SHAFT_NAME
        assert shaft.sketch().name == AXIS_SKETCH
        assert shaft.first_angle == pytest.approx(FULL_REVOLUTION)
        assert shaft.second_angle == pytest.approx(0.0)
        assert SHAFT_NAME in [f.name for f in part.part_design.shafts]
        # A shaft must never be reported as a pad.
        assert SHAFT_NAME not in [f.name for f in part.part_design.pads]

        shaft.set_first_angle(90)
        part.update()
        assert shaft.first_angle == pytest.approx(90.0)

        # The angle is a real parameter, so a formula can drive it.
        reference = part.formulas.relation_name(shaft.first_angle_parameter())
        assert SHAFT_NAME in reference
    finally:
        _cleanup(part, [("remove_shaft", SHAFT_NAME)], [AXIS_SKETCH])

    assert body.Shapes.Count == shapes_before
    assert body.Sketches.Count == sketches_before


def test_groove_round_trip(part) -> None:
    """A groove revolves a profile to cut material."""
    body = part.com_object.MainBody
    shapes_before = body.Shapes.Count
    sketches_before = body.Sketches.Count
    name = f"{AXIS_SKETCH}_GROOVE"
    if name in part.sketches:
        pytest.skip(f"{name} already exists; clean it up first.")

    try:
        sketch = _axis_sketch(part, name)
        groove = part.part_design.create_groove(GROOVE_NAME, sketch)
        part.update()

        assert groove.name == GROOVE_NAME
        assert groove.first_angle == pytest.approx(FULL_REVOLUTION)
        assert GROOVE_NAME in [f.name for f in part.part_design.grooves]
        assert GROOVE_NAME not in [f.name for f in part.part_design.shafts]
    finally:
        _cleanup(part, [("remove_groove", GROOVE_NAME)], [name])

    assert body.Shapes.Count == shapes_before
    assert body.Sketches.Count == sketches_before


def test_mirror_round_trip(part) -> None:
    """A mirror takes an origin plane, so it needs no BRep reference."""
    body = part.com_object.MainBody
    shapes_before = body.Shapes.Count
    if shapes_before == 0:
        pytest.skip("The main body is empty; a mirror of nothing fails the update.")
    if MIRROR_NAME in [f.name for f in part.part_design.mirrors]:
        pytest.skip(f"{MIRROR_NAME} already exists; clean it up first.")

    try:
        mirror = part.part_design.create_mirror(MIRROR_NAME, support="YZ")
        part.update()

        assert mirror.name == MIRROR_NAME
        assert MIRROR_NAME in [f.name for f in part.part_design.mirrors]
    finally:
        _cleanup(part, [("remove_mirror", MIRROR_NAME)], [])

    assert body.Shapes.Count == shapes_before
