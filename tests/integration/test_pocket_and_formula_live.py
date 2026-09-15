"""Live pocket and formula round-trip against a running 3DEXPERIENCE session.

Requires an open Part editor with a pad present, since a formula needs something
to drive. Everything created here is removed again in a `finally` block, and the
document is never saved.

Two cleanup facts this test encodes (both verified, both surprising):

    - Removing a Pocket does NOT cascade-delete its sketch, unlike removing a
      Pad. The sketch has to be removed separately.
    - Removing a formula does NOT revert the value it last computed. The
      target keeps that value, so the original has to be written back.
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
    FormulaNotFoundError,
    NoActiveEditorError,
    NoActivePartError,
    SketchNotFoundError,
)

SKETCH_NAME = "AUTO3DX_IT_PKT_SKETCH"
POCKET_NAME = "AUTO3DX_IT_POCKET"
FORMULA_NAME = "AUTO3DX_IT_FORMULA"
DRIVER_NAME = "AUTO3DX_IT_DRIVER"
POCKET_DEPTH = 4.0
DRIVER_VALUE = 7.0


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


def test_pocket_round_trip(part) -> None:
    """A pocket is created, measured, resized and removed without a trace."""
    body = part.com_object.MainBody
    shapes_before = body.Shapes.Count
    sketches_before = body.Sketches.Count
    for name in (SKETCH_NAME, POCKET_NAME):
        if name in part.sketches or name in [p.name for p in part.part_design.pockets]:
            pytest.skip(f"{name} already exists in this model; clean it up first.")

    try:
        sketch = part.sketches.create(SKETCH_NAME, support="XY")
        with sketch.edit() as editor:
            editor.rectangle(12.0, 8.0, origin_x=2.0, origin_y=2.0)
        part.update()

        pocket = part.part_design.create_pocket(POCKET_NAME, sketch, POCKET_DEPTH)
        part.update()
        assert pocket.depth == pytest.approx(POCKET_DEPTH)
        assert pocket.sketch().name == SKETCH_NAME
        assert POCKET_NAME in [p.name for p in part.part_design.pockets]
        # A pocket must never show up among the pads.
        assert POCKET_NAME not in [p.name for p in part.part_design.pads]

        resized = part.part_design.ensure_pocket(POCKET_NAME, sketch, 6.0)
        part.update()
        assert resized.depth == pytest.approx(6.0)
    finally:
        try:
            part.part_design.remove_pocket(POCKET_NAME)
        except FeatureNotFoundError:
            pass
        # Removing a pocket does NOT take its sketch with it, unlike a pad.
        try:
            part.sketches.remove(SKETCH_NAME)
        except SketchNotFoundError:
            pass
        part.update()

    assert body.Shapes.Count == shapes_before
    assert body.Sketches.Count == sketches_before


def test_formula_drives_a_pad(part) -> None:
    """A formula built from `relation_name` actually recomputes the model."""
    pads = part.part_design.pads
    if not pads:
        pytest.skip("No pad in this Part for a formula to drive.")
    if FORMULA_NAME in part.formulas or DRIVER_NAME in part.parameters:
        pytest.skip("Leftover test objects in this model; clean them up first.")

    pad = pads[0]
    original_height = pad.height
    try:
        driver = part.parameters.create_length(DRIVER_NAME, DRIVER_VALUE)
        target = pad.depth_parameter()

        # The body must use relation_name(), not Parameter.name.
        driver_reference = part.formulas.relation_name(driver)
        assert driver_reference != driver.name

        formula = part.formulas.create(
            FORMULA_NAME, target, f"{driver_reference} * 2", comment="auto-3dx test"
        )
        part.update()
        assert formula.body == f"{driver_reference} * 2"
        assert formula.activated is True
        assert pad.height == pytest.approx(DRIVER_VALUE * 2)

        driver.set(DRIVER_VALUE + 1)
        part.update()
        assert pad.height == pytest.approx((DRIVER_VALUE + 1) * 2)
    finally:
        try:
            part.formulas.remove(FORMULA_NAME)
        except FormulaNotFoundError:
            pass
        # Removing the formula leaves its last computed value behind.
        pad.set_height(original_height)
        try:
            part.parameters.remove(DRIVER_NAME)
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass
        part.update()

    assert pad.height == pytest.approx(original_height)
    assert FORMULA_NAME not in part.formulas
