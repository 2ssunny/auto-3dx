"""Live round-trip for sketch constraints and the full parametric chain.

The chain this pins is the point of the whole library:

    user parameter -> formula -> sketch dimensional constraint -> geometry

Verified live: driving the parameter to 50 then 75 moved the constrained sketch
width to 50.0 then 75.0, with `BrokenConstraintsCount` staying at 0.

Constraints only work inside the edition session, so every constraint call here
sits inside `sketch.edit()`. Everything created is removed in a `finally`, and
the document is never saved.
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
    FeatureNotFoundError,
    FormulaNotFoundError,
    NoActiveEditorError,
    NoActivePartError,
    ParameterNotFoundError,
    SketchNotFoundError,
)

SKETCH_NAME = "AUTO3DX_IT_CST_SKETCH"
PAD_NAME = "AUTO3DX_IT_CST_PAD"
DRIVER_NAME = "AUTO3DX_IT_CST_DRIVER"
FORMULA_NAME = "AUTO3DX_IT_CST_FORMULA"
WIDTH = 40.0
HEIGHT = 25.0


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


def _cleanup(part) -> None:
    """Removes everything this module creates, tolerating what is already gone."""
    try:
        part.formulas.remove(FORMULA_NAME)
    except FormulaNotFoundError:
        pass
    try:
        part.part_design.remove_pad(PAD_NAME)
    except FeatureNotFoundError:
        pass
    try:
        part.sketches.remove(SKETCH_NAME)
    except SketchNotFoundError:
        pass
    try:
        part.parameters.remove(DRIVER_NAME)
    except ParameterNotFoundError:
        pass
    part.update()


def test_constrained_sketch_round_trip(part) -> None:
    """A rectangle can be constrained and its dimensions read back."""
    body = part.com_object.MainBody
    sketches_before = body.Sketches.Count
    if SKETCH_NAME in part.sketches:
        pytest.skip(f"{SKETCH_NAME} already exists; clean it up first.")

    try:
        sketch = part.sketches.create(SKETCH_NAME, support="XY")
        with sketch.edit() as editor:
            bottom = editor.line(0.0, 0.0, WIDTH, 0.0)
            right = editor.line(WIDTH, 0.0, WIDTH, HEIGHT)
            top = editor.line(WIDTH, HEIGHT, 0.0, HEIGHT)
            editor.line(0.0, HEIGHT, 0.0, 0.0)
            editor.horizontal(bottom)
            editor.vertical(right)
            editor.perpendicular(bottom, right)
            width = editor.length(bottom, WIDTH)
            height = editor.distance(bottom, top, HEIGHT)
        part.update()

        assert sketch.constraints.count >= 5
        assert sketch.constraints.broken_count == 0
        assert width.value == pytest.approx(WIDTH)
        assert height.value == pytest.approx(HEIGHT)
        # Horizontality is normalised into Parallelism, so never look a
        # constraint up by the code that was requested.
        assert width.type_code == 5
        assert width.name in sketch.constraints.names()
    finally:
        _cleanup(part)

    assert body.Sketches.Count == sketches_before


def test_constraints_outside_edition_are_refused(part) -> None:
    """The trap users hit first: a constraint call after the block exited."""
    if SKETCH_NAME in part.sketches:
        pytest.skip(f"{SKETCH_NAME} already exists; clean it up first.")

    try:
        sketch = part.sketches.create(SKETCH_NAME, support="XY")
        with sketch.edit() as editor:
            line = editor.line(0.0, 0.0, WIDTH, 0.0)
        part.update()

        # `editor` is still a live object, but the sketch is closed.
        with pytest.raises(Auto3dxError) as caught:
            editor.horizontal(line)
        assert "edit()" in str(caught.value)
    finally:
        _cleanup(part)


def test_formula_drives_a_sketch_constraint(part) -> None:
    """The full chain: parameter -> formula -> constraint -> geometry."""
    body = part.com_object.MainBody
    sketches_before = body.Sketches.Count
    shapes_before = body.Shapes.Count
    if SKETCH_NAME in part.sketches or DRIVER_NAME in part.parameters:
        pytest.skip("Leftover test objects in this model; clean them up first.")

    try:
        driver = part.parameters.create_length(DRIVER_NAME, 50.0)
        sketch = part.sketches.create(SKETCH_NAME, support="XY")
        with sketch.edit() as editor:
            bottom = editor.line(0.0, 0.0, WIDTH, 0.0)
            right = editor.line(WIDTH, 0.0, WIDTH, HEIGHT)
            top = editor.line(WIDTH, HEIGHT, 0.0, HEIGHT)
            editor.line(0.0, HEIGHT, 0.0, 0.0)
            editor.perpendicular(bottom, right)
            width = editor.length(bottom, WIDTH)
            editor.distance(bottom, top, HEIGHT)
        part.update()

        part.part_design.create_pad(PAD_NAME, sketch, 8.0)
        part.update()

        part.formulas.create(
            FORMULA_NAME,
            width.dimension_parameter(),
            part.formulas.relation_name(driver),
            comment="auto-3dx test",
        )
        part.update()
        assert sketch.constraints.get(width.name).value == pytest.approx(50.0)

        driver.set(75.0)
        part.update()
        assert sketch.constraints.get(width.name).value == pytest.approx(75.0)
        assert sketch.constraints.broken_count == 0
    finally:
        _cleanup(part)

    assert body.Sketches.Count == sketches_before
    assert body.Shapes.Count == shapes_before
