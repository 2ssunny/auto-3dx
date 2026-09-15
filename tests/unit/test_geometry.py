"""Unit tests for the geometry layer (`auto_3dx.geometry.sketch`/`part_design`).

See docs/conventions.md sections 1.2 (verified Sketch/Pad facts), 1.3 (the
`ensure_*` policy), 6.9 (`SketchEditor`/`Sketch`/`SketchCollection` contract)
and 6.10 (`Pad`/`PartDesign` contract). CATIA is never contacted here: every
COM object is one of the fakes from `tests/conftest.py`, identified purely by
`type(obj).__name__` (docs/conventions.md section 4).
"""

from collections.abc import Callable
from typing import Any

import pytest

from auto_3dx.errors import (
    FeatureConflictError,
    ParameterTypeError,
    SketchAlreadyExistsError,
    SketchSupportMismatchError,
    UnsupportedSupportError,
)
from auto_3dx.geometry.part_design import Pad, PartDesign
from auto_3dx.geometry.sketch import (
    SUPPORT_XY,
    SUPPORT_YZ,
    SUPPORT_ZX,
    Sketch,
    SketchCollection,
)

from tests.conftest import (
    UNRECOGNISED_AXIS_DATA,
    XY_AXIS_DATA,
    YZ_AXIS_DATA,
    ZX_AXIS_DATA,
)

AUTO3DX_TEST_SKETCH = "AUTO3DX_TEST_SKETCH"
AUTO3DX_TEST_PAD = "AUTO3DX_TEST_PAD"


# ---------------------------------------------------------------------------
# 1. create() calls Sketches.Add with the plane from OriginElements.PlaneXY,
#    then SETS Name -- and the name actually gets written.
# ---------------------------------------------------------------------------


def test_create_adds_on_the_xy_plane_and_writes_the_name(
    part_factory: Callable[..., Any],
) -> None:
    """`create(name, support="XY")` uses `OriginElements.PlaneXY` and renames."""
    part = part_factory()

    sketch = SketchCollection(part).create(AUTO3DX_TEST_SKETCH, support=SUPPORT_XY)

    assert part.MainBody.Sketches.add_calls == [part.OriginElements.PlaneXY]
    assert sketch.com_object.Name == AUTO3DX_TEST_SKETCH
    assert sketch.name == AUTO3DX_TEST_SKETCH


@pytest.mark.parametrize(
    "support, plane_attr",
    [(SUPPORT_YZ, "PlaneYZ"), (SUPPORT_ZX, "PlaneZX")],
)
def test_create_adds_on_the_requested_plane(
    part_factory: Callable[..., Any], support: str, plane_attr: str
) -> None:
    """`create()` picks the plane matching the requested support."""
    part = part_factory()

    SketchCollection(part).create(AUTO3DX_TEST_SKETCH, support=support)

    assert part.MainBody.Sketches.add_calls == [getattr(part.OriginElements, plane_attr)]


# ---------------------------------------------------------------------------
# 2. support() returns "XY"/"YZ"/"ZX" for the three verified axis tuples, and
#    None (not a guess, not an exception) for an unrecognised axis frame.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "axis_data, expected_support",
    [
        (XY_AXIS_DATA, SUPPORT_XY),
        (YZ_AXIS_DATA, SUPPORT_YZ),
        (ZX_AXIS_DATA, SUPPORT_ZX),
    ],
)
def test_support_identifies_the_three_verified_axis_frames(
    sketch_factory: Callable[..., Any],
    axis_data: tuple[float, ...],
    expected_support: str,
) -> None:
    """Each verified 9-tuple maps back to its support string."""
    sketch = Sketch(sketch_factory(axis_data=axis_data))

    assert sketch.support() == expected_support


def test_support_returns_none_for_an_unrecognised_axis_frame(
    sketch_factory: Callable[..., Any],
) -> None:
    """An axis frame matching none of the three verified supports is `None`."""
    sketch = Sketch(sketch_factory(axis_data=UNRECOGNISED_AXIS_DATA))

    assert sketch.support() is None


# ---------------------------------------------------------------------------
# 3 & 4. edit() closes exactly once on the happy path, and closes even when
#    the caller's block raises.
# ---------------------------------------------------------------------------


def test_edit_closes_the_edition_even_when_the_body_raises(
    sketch_factory: Callable[..., Any],
) -> None:
    """A raise inside `edit()`'s block must not leave the sketch open."""
    fake_sketch = sketch_factory()
    sketch = Sketch(fake_sketch)

    with pytest.raises(RuntimeError, match="boom"):
        with sketch.edit() as editor:
            editor.line(0, 0, 1, 1)
            raise RuntimeError("boom")

    assert fake_sketch.close_edition_calls == 1


def test_edit_closes_exactly_once_on_the_happy_path(
    sketch_factory: Callable[..., Any],
) -> None:
    """A normal `edit()` block opens once and closes exactly once."""
    fake_sketch = sketch_factory()
    sketch = Sketch(fake_sketch)

    with sketch.edit() as editor:
        editor.line(0, 0, 1, 1)

    assert fake_sketch.open_edition_calls == 1
    assert fake_sketch.close_edition_calls == 1


# ---------------------------------------------------------------------------
# 5 & 6. rectangle() emits exactly four lines forming a closed loop, and
#    honours origin_x/origin_y.
# ---------------------------------------------------------------------------


def test_rectangle_emits_four_lines_forming_a_closed_loop(
    sketch_factory: Callable[..., Any],
) -> None:
    """`rectangle(60, 40)` emits exactly the four closed-loop coordinate pairs."""
    fake_sketch = sketch_factory()
    sketch = Sketch(fake_sketch)

    with sketch.edit() as editor:
        editor.rectangle(60, 40)

    calls = fake_sketch.factory2d.line_calls
    assert calls == [
        (0.0, 0.0, 60.0, 0.0),
        (60.0, 0.0, 60.0, 40.0),
        (60.0, 40.0, 0.0, 40.0),
        (0.0, 40.0, 0.0, 0.0),
    ]
    last_end = calls[-1][2], calls[-1][3]
    first_start = calls[0][0], calls[0][1]
    assert last_end == first_start


def test_rectangle_honours_origin_x_and_origin_y(
    sketch_factory: Callable[..., Any],
) -> None:
    """A non-zero origin translates every corner of the rectangle."""
    fake_sketch = sketch_factory()
    sketch = Sketch(fake_sketch)

    with sketch.edit() as editor:
        editor.rectangle(60, 40, origin_x=10, origin_y=5)

    calls = fake_sketch.factory2d.line_calls
    assert calls == [
        (10.0, 5.0, 70.0, 5.0),
        (70.0, 5.0, 70.0, 45.0),
        (70.0, 45.0, 10.0, 45.0),
        (10.0, 45.0, 10.0, 5.0),
    ]


# ---------------------------------------------------------------------------
# 7. rectangle() rejects a bool or str width/height.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "width, height",
    [
        (True, 40),
        (60, False),
        ("60", 40),
        (60, "40"),
    ],
)
def test_rectangle_rejects_non_numeric_width_or_height(
    sketch_factory: Callable[..., Any], width: Any, height: Any
) -> None:
    """`bool` (an `int` subclass) and `str` must both be refused explicitly."""
    fake_sketch = sketch_factory()
    sketch = Sketch(fake_sketch)

    with sketch.edit() as editor:
        with pytest.raises(ParameterTypeError):
            editor.rectangle(width, height)

    assert fake_sketch.factory2d.line_calls == []


# ---------------------------------------------------------------------------
# 8. create() with an unsupported support string raises UnsupportedSupportError.
# ---------------------------------------------------------------------------


def test_create_rejects_an_unsupported_support_string(
    part_factory: Callable[..., Any],
) -> None:
    """An unknown support string is refused before ever touching `Sketches.Add`."""
    part = part_factory()

    with pytest.raises(UnsupportedSupportError):
        SketchCollection(part).create(AUTO3DX_TEST_SKETCH, support="DIAGONAL")

    assert part.MainBody.Sketches.add_calls == []


# ---------------------------------------------------------------------------
# 9. create() with an existing name raises SketchAlreadyExistsError and does
#    NOT call Sketches.Add.
# ---------------------------------------------------------------------------


def test_create_rejects_an_existing_name_without_calling_add(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
    sketches_factory: Callable[..., Any],
    body_factory: Callable[..., Any],
) -> None:
    """A duplicate name must be refused before reaching COM, like parameter creation."""
    existing = sketch_factory(name=AUTO3DX_TEST_SKETCH, axis_data=XY_AXIS_DATA)
    sketches = sketches_factory(items=[(existing.Name, existing)])
    part = part_factory(main_body=body_factory(sketches=sketches))

    with pytest.raises(SketchAlreadyExistsError):
        SketchCollection(part).create(AUTO3DX_TEST_SKETCH, support=SUPPORT_XY)

    assert sketches.add_calls == []


# ---------------------------------------------------------------------------
# 10. ensure() creates when absent; reuses when the name exists AND the axis
#    data matches (Sketches.Add is NOT called again); raises
#    SketchSupportMismatchError when the name exists on a different support.
# ---------------------------------------------------------------------------


def test_ensure_creates_when_absent(part_factory: Callable[..., Any]) -> None:
    """A missing name is created via `Sketches.Add`, exactly like `create()`."""
    part = part_factory()

    sketch = SketchCollection(part).ensure(AUTO3DX_TEST_SKETCH, support=SUPPORT_XY)

    assert sketch.name == AUTO3DX_TEST_SKETCH
    assert len(part.MainBody.Sketches.add_calls) == 1


def test_ensure_reuses_when_name_and_axis_data_match(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
    sketches_factory: Callable[..., Any],
    body_factory: Callable[..., Any],
) -> None:
    """A matching existing sketch is reused; `Sketches.Add` must not be called."""
    existing = sketch_factory(name=AUTO3DX_TEST_SKETCH, axis_data=XY_AXIS_DATA)
    sketches = sketches_factory(items=[(existing.Name, existing)])
    part = part_factory(main_body=body_factory(sketches=sketches))

    sketch = SketchCollection(part).ensure(AUTO3DX_TEST_SKETCH, support=SUPPORT_XY)

    assert sketch.com_object is existing
    assert sketches.add_calls == []


def test_ensure_raises_on_support_mismatch(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
    sketches_factory: Callable[..., Any],
    body_factory: Callable[..., Any],
) -> None:
    """An existing sketch on a different support is a conflict, not silently reused."""
    existing = sketch_factory(name=AUTO3DX_TEST_SKETCH, axis_data=XY_AXIS_DATA)
    sketches = sketches_factory(items=[(existing.Name, existing)])
    part = part_factory(main_body=body_factory(sketches=sketches))

    with pytest.raises(SketchSupportMismatchError):
        SketchCollection(part).ensure(AUTO3DX_TEST_SKETCH, support=SUPPORT_YZ)

    assert sketches.add_calls == []


# ---------------------------------------------------------------------------
# 11. Pad.height reads FirstLimit.Dimension.Value; set_height writes it.
# ---------------------------------------------------------------------------


def test_pad_height_reads_first_limit_dimension_value(
    pad_factory: Callable[..., Any],
) -> None:
    """`Pad.height` is a thin read of `FirstLimit.Dimension.Value`."""
    fake_pad = pad_factory(height=15.0)

    assert Pad(fake_pad).height == 15.0


def test_pad_set_height_writes_first_limit_dimension_value(
    pad_factory: Callable[..., Any],
) -> None:
    """`Pad.set_height()` writes `FirstLimit.Dimension.Value`."""
    fake_pad = pad_factory(height=15.0)
    pad = Pad(fake_pad)

    pad.set_height(30.0)

    assert fake_pad.FirstLimit.Dimension.Value == 30.0


# ---------------------------------------------------------------------------
# 12. create_pad() calls ShapeFactory.AddNewPad(sketch_com_object, float(height))
#    -- the height arrives as a float, and the raw COM sketch (not the
#    wrapper) is passed.
# ---------------------------------------------------------------------------


def test_create_pad_passes_the_raw_sketch_and_a_float_height(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
) -> None:
    """`AddNewPad` must receive the raw COM sketch object, not the `Sketch` wrapper."""
    fake_sketch = sketch_factory()
    part = part_factory()
    sketch = Sketch(fake_sketch)

    PartDesign(part).create_pad(AUTO3DX_TEST_PAD, sketch, 20)

    calls = part.ShapeFactory.add_new_pad_calls
    assert len(calls) == 1
    passed_sketch, passed_height = calls[0]
    assert passed_sketch is fake_sketch
    assert isinstance(passed_height, float)
    assert passed_height == 20.0


# ---------------------------------------------------------------------------
# 13. ensure_pad(): absent -> create; same sketch + same height -> reuse
#    without calling AddNewPad; same sketch + different height -> updates
#    FirstLimit.Dimension.Value without calling AddNewPad; different sketch
#    -> FeatureConflictError.
# ---------------------------------------------------------------------------


def test_ensure_pad_creates_when_absent(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
) -> None:
    """A missing pad name is created via `AddNewPad`."""
    fake_sketch = sketch_factory()
    part = part_factory()
    sketch = Sketch(fake_sketch)

    pad = PartDesign(part).ensure_pad(AUTO3DX_TEST_PAD, sketch, 20)

    assert pad.height == 20.0
    assert len(part.ShapeFactory.add_new_pad_calls) == 1


def test_ensure_pad_reuses_when_same_sketch_and_same_height(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
    pad_factory: Callable[..., Any],
    shapes_factory: Callable[..., Any],
    body_factory: Callable[..., Any],
) -> None:
    """A matching pad is reused as-is; `AddNewPad` must not be called."""
    fake_sketch = sketch_factory()
    existing_pad = pad_factory(name=AUTO3DX_TEST_PAD, sketch=fake_sketch, height=20.0)
    shapes = shapes_factory(items=[(existing_pad.Name, existing_pad)])
    part = part_factory(main_body=body_factory(shapes=shapes))
    sketch = Sketch(fake_sketch)

    pad = PartDesign(part).ensure_pad(AUTO3DX_TEST_PAD, sketch, 20)

    assert pad.com_object is existing_pad
    assert part.ShapeFactory.add_new_pad_calls == []


def test_ensure_pad_updates_height_when_same_sketch_different_height(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
    pad_factory: Callable[..., Any],
    shapes_factory: Callable[..., Any],
    body_factory: Callable[..., Any],
) -> None:
    """A different height on the same sketch updates `FirstLimit.Dimension.Value`."""
    fake_sketch = sketch_factory()
    existing_pad = pad_factory(name=AUTO3DX_TEST_PAD, sketch=fake_sketch, height=20.0)
    shapes = shapes_factory(items=[(existing_pad.Name, existing_pad)])
    part = part_factory(main_body=body_factory(shapes=shapes))
    sketch = Sketch(fake_sketch)

    pad = PartDesign(part).ensure_pad(AUTO3DX_TEST_PAD, sketch, 35)

    assert pad.height == 35.0
    assert existing_pad.FirstLimit.Dimension.Value == 35.0
    assert part.ShapeFactory.add_new_pad_calls == []


def test_ensure_pad_raises_feature_conflict_for_a_different_sketch(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
    pad_factory: Callable[..., Any],
    shapes_factory: Callable[..., Any],
    body_factory: Callable[..., Any],
) -> None:
    """An existing pad on a different sketch is a conflict, not silently repointed."""
    other_fake_sketch = sketch_factory(name="Other.1")
    existing_pad = pad_factory(name=AUTO3DX_TEST_PAD, sketch=other_fake_sketch, height=20.0)
    shapes = shapes_factory(items=[(existing_pad.Name, existing_pad)])
    part = part_factory(main_body=body_factory(shapes=shapes))
    requested_sketch = Sketch(sketch_factory(name="Requested.1"))

    with pytest.raises(FeatureConflictError):
        PartDesign(part).ensure_pad(AUTO3DX_TEST_PAD, requested_sketch, 20)

    assert part.ShapeFactory.add_new_pad_calls == []
    assert existing_pad.FirstLimit.Dimension.Value == 20.0


# ---------------------------------------------------------------------------
# 14. Nothing in the geometry layer calls Update() or Save().
# ---------------------------------------------------------------------------


def test_geometry_operations_never_call_update(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
) -> None:
    """Sketch/pad create+ensure operations leave `Part.Update()` uncalled.

    `part_factory`'s fake `Part.Save` raises `AssertionError` unconditionally
    (see conftest.py), so if any geometry operation below ever called `Save`
    this test would already fail loudly before reaching the final assertion.
    """
    part = part_factory()
    collection = SketchCollection(part)

    sketch = collection.create(AUTO3DX_TEST_SKETCH, support=SUPPORT_XY)
    with sketch.edit() as editor:
        editor.rectangle(60, 40)
    collection.ensure(AUTO3DX_TEST_SKETCH, support=SUPPORT_XY)

    part_design = PartDesign(part)
    part_design.create_pad(AUTO3DX_TEST_PAD, sketch, 20)
    part_design.ensure_pad(AUTO3DX_TEST_PAD, sketch, 20)
    part_design.ensure_pad(AUTO3DX_TEST_PAD, sketch, 35)

    assert part.update_calls == 0
