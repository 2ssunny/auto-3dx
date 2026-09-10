"""Regression tests for the geometry code-review fixes.

Each premise below was verified against a live B428_Cloud session
(`scripts/probes/14_identity_and_duplicates.py`):

    - Two sketches in one body CAN carry the same name: `Sketch.Name` is
      writable and CATIA does not reject a duplicate. `Sketches.Item(name)`
      then returns one of them arbitrarily.
    - COM identity comparison works through `==` (never `is`): two wrappers for
      the same underlying object compare equal, different objects do not, and
      `pad.Sketch == original_sketch` is True.

None of these defects were caught by the original geometry tests, so they are
pinned explicitly here.
"""

from collections.abc import Callable
from typing import Any

import pytest

from auto_3dx.errors import (
    AmbiguousNameError,
    Auto3dxError,
    FeatureConflictError,
    PartialCreationError,
    SketchAlreadyExistsError,
    SketchNotFoundError,
)
from auto_3dx.geometry.part_design import PartDesign
from auto_3dx.geometry.sketch import SketchCollection

SHARED_NAME = "AUTO3DX_SHARED"
PAD_NAME = "AUTO3DX_PAD"
BIG_HEIGHT = 1_000_000.0
BIG_HEIGHT_NUDGED = 1_000_000.001


def _collections(part_com: Any, selection: Any = None) -> tuple[Any, Any]:
    """Builds a sketch collection and a part design over one fake Part."""
    return SketchCollection(part_com, selection), PartDesign(part_com, selection)


# --- 1. Float comparison must be absolute, not relative -----------------------


def test_ensure_pad_updates_a_tiny_relative_height_difference(
    part_factory: Callable[..., Any],
) -> None:
    """`math.isclose` without `rel_tol=0.0` would call these two heights equal.

    Python's default `rel_tol=1e-09` scales with magnitude, so at 1e6 mm a 1
    micron change is silently treated as "already correct" and the requested
    update never reaches the model.
    """
    part_com = part_factory()
    sketches, part_design = _collections(part_com)
    sketch = sketches.create(SHARED_NAME)
    pad = part_design.create_pad(PAD_NAME, sketch, BIG_HEIGHT)

    part_design.ensure_pad(PAD_NAME, sketch, BIG_HEIGHT_NUDGED)

    assert pad.com_object.FirstLimit.Dimension.Value == BIG_HEIGHT_NUDGED


def test_ensure_pad_does_not_rewrite_an_identical_height(
    part_factory: Callable[..., Any],
) -> None:
    """An unchanged height must not produce a spurious model write."""
    part_com = part_factory()
    sketches, part_design = _collections(part_com)
    sketch = sketches.create(SHARED_NAME)
    pad = part_design.create_pad(PAD_NAME, sketch, 20.0)
    pad.com_object.FirstLimit.Dimension.write_calls = 0

    part_design.ensure_pad(PAD_NAME, sketch, 20.0)

    assert pad.com_object.FirstLimit.Dimension.Value == 20.0


# --- 2. Duplicate names must be refused, not resolved arbitrarily -------------


def _two_sketches_sharing_a_name(part_com: Any, selection: Any = None) -> SketchCollection:
    """Creates two sketches with the same name, as CATIA permits."""
    sketches = SketchCollection(part_com, selection)
    first = sketches.create(SHARED_NAME)
    second = sketches.create("OTHER")
    second.rename(SHARED_NAME)
    assert first.name == second.name
    return sketches


def test_get_refuses_an_ambiguous_sketch_name(
    part_factory: Callable[..., Any],
) -> None:
    """Two sketches share the name, so no single answer is correct."""
    sketches = _two_sketches_sharing_a_name(part_factory())

    with pytest.raises(AmbiguousNameError):
        sketches.get(SHARED_NAME)


def test_ensure_refuses_an_ambiguous_sketch_name_without_creating(
    part_factory: Callable[..., Any],
) -> None:
    """An ambiguous name must change nothing at all."""
    part_com = part_factory()
    sketches = _two_sketches_sharing_a_name(part_com)
    add_calls_before = len(part_com.MainBody.Sketches.add_calls)

    with pytest.raises(AmbiguousNameError):
        sketches.ensure(SHARED_NAME)

    assert len(part_com.MainBody.Sketches.add_calls) == add_calls_before


def test_get_pad_refuses_an_ambiguous_pad_name(
    part_factory: Callable[..., Any],
) -> None:
    """Pads inherit the same ambiguity risk as sketches."""
    part_com = part_factory()
    sketches, part_design = _collections(part_com)
    sketch = sketches.create(SHARED_NAME)
    part_design.create_pad(PAD_NAME, sketch, 10.0)
    second = part_design.create_pad("OTHER_PAD", sketch, 10.0)
    second.com_object.Name = PAD_NAME

    with pytest.raises(AmbiguousNameError):
        part_design.get_pad(PAD_NAME)


def test_ensure_pad_refuses_an_ambiguous_name_without_mutating(
    part_factory: Callable[..., Any],
) -> None:
    """Neither a new pad nor a height change may result from ambiguity."""
    part_com = part_factory()
    sketches, part_design = _collections(part_com)
    sketch = sketches.create(SHARED_NAME)
    first = part_design.create_pad(PAD_NAME, sketch, 10.0)
    second = part_design.create_pad("OTHER_PAD", sketch, 10.0)
    second.com_object.Name = PAD_NAME
    add_calls_before = len(part_com.ShapeFactory.add_new_pad_calls)

    with pytest.raises(AmbiguousNameError):
        part_design.ensure_pad(PAD_NAME, sketch, 99.0)

    assert len(part_com.ShapeFactory.add_new_pad_calls) == add_calls_before
    assert first.height == 10.0
    assert second.height == 10.0


# --- 3. Existence must be positive evidence, never a caught exception ---------


def test_create_refuses_a_duplicate_even_when_item_lookup_fails(
    part_factory: Callable[..., Any],
    sketches_factory: Callable[..., Any],
    body_factory: Callable[..., Any],
    com_error_factory: Callable[[], BaseException],
) -> None:
    """A COM failure on `Item(name)` must not be read as "does not exist".

    Deciding absence from a raised exception is fail-open: a transient COM
    error would make a retried `create` add a SECOND sketch with the same name.
    Enumeration still sees the existing one, so creation must be refused.
    """
    sketches_com = sketches_factory(item_by_name_exception=com_error_factory())
    part_com = part_factory(main_body=body_factory(sketches=sketches_com))
    sketches = SketchCollection(part_com)
    sketches_com._items.append((SHARED_NAME, _named_sketch(SHARED_NAME)))

    with pytest.raises(SketchAlreadyExistsError):
        sketches.create(SHARED_NAME)

    assert sketches_com.add_calls == []


def test_enumeration_failure_is_not_reported_as_not_found(
    part_factory: Callable[..., Any],
    sketches_factory: Callable[..., Any],
    body_factory: Callable[..., Any],
    com_error_factory: Callable[[], BaseException],
) -> None:
    """A COM failure while enumerating is a fault, not proof of absence."""
    sketches_com = sketches_factory(enumeration_exception=com_error_factory())
    part_com = part_factory(main_body=body_factory(sketches=sketches_com))
    sketches = SketchCollection(part_com)

    with pytest.raises(Auto3dxError) as caught:
        sketches.get(SHARED_NAME)

    assert not isinstance(caught.value, SketchNotFoundError)


def _named_sketch(name: str) -> Any:
    """Builds a bare fake sketch carrying `name`, for pre-seeding a collection."""
    from tests.conftest import Sketch as FakeSketch

    return FakeSketch(name=name)


# --- 4. `ensure_pad` must compare sketch identity, not name ------------------


def test_ensure_pad_rejects_a_different_sketch_with_the_same_name(
    part_factory: Callable[..., Any],
) -> None:
    """A forged name must not let a pad be re-pointed at another profile."""
    part_com = part_factory()
    sketches, part_design = _collections(part_com)
    original = sketches.create(SHARED_NAME)
    impostor = sketches.create("IMPOSTOR")
    part_design.create_pad(PAD_NAME, original, 10.0)
    impostor.rename(SHARED_NAME)

    with pytest.raises(FeatureConflictError):
        part_design.ensure_pad(PAD_NAME, impostor, 10.0)


def test_ensure_pad_accepts_a_second_wrapper_for_the_same_sketch(
    part_factory: Callable[..., Any],
) -> None:
    """COM hands out a fresh wrapper each time; `==` is what identifies it."""
    part_com = part_factory()
    sketches, part_design = _collections(part_com)
    sketch = sketches.create(SHARED_NAME)
    part_design.create_pad(PAD_NAME, sketch, 10.0)

    from auto_3dx.geometry.sketch import Sketch

    # A real session hands back a fresh wrapper for the same CATIA object each
    # time, so identity must not rely on `is`.
    other_wrapper = Sketch(sketch.com_object.another_wrapper())
    assert other_wrapper.com_object is not sketch.com_object
    assert other_wrapper.com_object == sketch.com_object

    ensured = part_design.ensure_pad(PAD_NAME, other_wrapper, 25.0)

    assert ensured.height == 25.0


# --- 5. `edit()` must refuse re-entry ----------------------------------------


def test_edit_refuses_re_entry_before_a_second_open(
    part_factory: Callable[..., Any],
) -> None:
    """Nested OpenEdition is unverified and would mismatch the closes."""
    part_com = part_factory()
    sketches, _ = _collections(part_com)
    sketch = sketches.create(SHARED_NAME)

    with sketch.edit():
        with pytest.raises(Auto3dxError):
            with sketch.edit():
                pass

    assert sketch.com_object.open_edition_calls == 1
    assert sketch.com_object.close_edition_calls == 1


def test_edit_is_reusable_after_the_block_raises(
    part_factory: Callable[..., Any],
) -> None:
    """A failed block must not lock the sketch out of editing forever."""
    part_com = part_factory()
    sketches, _ = _collections(part_com)
    sketch = sketches.create(SHARED_NAME)

    with pytest.raises(RuntimeError):
        with sketch.edit():
            raise RuntimeError("boom")

    with sketch.edit() as editor:
        editor.line(0.0, 0.0, 1.0, 0.0)

    assert sketch.com_object.open_edition_calls == 2
    assert sketch.com_object.close_edition_calls == 2


# --- 6. Selection cleanup failure must surface -------------------------------


def test_cleanup_clear_failure_is_reported(
    part_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
    com_error_factory: Callable[[], BaseException],
) -> None:
    """A successful delete with a failed clear leaves a dirty live selection."""
    selection = selection_factory()
    part_com = part_factory()
    sketches = SketchCollection(part_com, selection)
    sketches.create(SHARED_NAME)
    selection.clear_exception = com_error_factory()
    selection.failing_clear_ordinal = 2  # the trailing cleanup Clear

    with pytest.raises(Auto3dxError) as caught:
        sketches.remove(SHARED_NAME)

    assert "clear" in str(caught.value).lower()


def test_delete_failure_wins_over_cleanup_failure(
    part_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
    com_error_factory: Callable[[], BaseException],
) -> None:
    """The primary failure must not be masked by the cleanup failure."""
    selection = selection_factory()
    part_com = part_factory()
    sketches = SketchCollection(part_com, selection)
    sketches.create(SHARED_NAME)
    selection.delete_exception = com_error_factory()
    selection.clear_exception = com_error_factory()
    selection.failing_clear_ordinal = 2

    with pytest.raises(Auto3dxError) as caught:
        sketches.remove(SHARED_NAME)

    assert "delete" in str(caught.value).lower()


# --- 7. Partial creation must be reported, not silently left behind ----------


def test_sketch_name_write_failure_reports_the_leftover(
    part_factory: Callable[..., Any],
    sketches_factory: Callable[..., Any],
    body_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
    com_error_factory: Callable[[], BaseException],
) -> None:
    """`Sketches.Add` already mutated the model before the name write failed."""
    sketches_com = sketches_factory(added_name_write_exception=com_error_factory())
    part_com = part_factory(main_body=body_factory(sketches=sketches_com))
    selection = selection_factory()
    sketches = SketchCollection(part_com, selection)

    with pytest.raises(PartialCreationError) as caught:
        sketches.create(SHARED_NAME)

    # The default name is what is actually left in the model.
    assert "Sketch" in str(caught.value)
    # Rollback is unsafe (deleting a pad cascade-deletes its sketch), so the
    # library must report rather than delete.
    assert selection.deleted == []


def test_pad_name_write_failure_reports_the_leftover(
    part_factory: Callable[..., Any],
    shape_factory_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
    com_error_factory: Callable[[], BaseException],
) -> None:
    """`AddNewPad` already added solid material before the name write failed."""
    part_com = part_factory()
    part_com.ShapeFactory = shape_factory_factory(
        shapes=part_com.MainBody.Shapes,
        pad_name_write_exception=com_error_factory(),
    )
    selection = selection_factory()
    sketches, part_design = _collections(part_com, selection)
    sketch = sketches.create(SHARED_NAME)

    with pytest.raises(PartialCreationError) as caught:
        part_design.create_pad(PAD_NAME, sketch, 10.0)

    assert "Pad" in str(caught.value)
    assert selection.deleted == []


# --- 8. Malformed axis data must become a library error ----------------------


@pytest.mark.parametrize("bad", [None, 42])
def test_axis_data_rejects_a_non_iterable_result(
    sketch_factory: Callable[..., Any],
    bad: Any,
) -> None:
    """A raw `TypeError` would leak an implementation detail to the caller."""
    from auto_3dx.geometry.sketch import Sketch

    sketch = Sketch(sketch_factory(axis_data_result=bad))

    with pytest.raises(Auto3dxError):
        sketch.axis_data()


def test_support_returns_none_for_a_wrong_length_result(
    sketch_factory: Callable[..., Any],
) -> None:
    """A wrong length is "unrecognised", not an error and not a guess."""
    from auto_3dx.geometry.sketch import Sketch

    sketch = Sketch(sketch_factory(axis_data_result=(0.0, 0.0, 0.0)))

    assert sketch.support() is None


def test_support_rejects_non_numeric_axis_entries(
    sketch_factory: Callable[..., Any],
) -> None:
    """Nine non-numeric entries must not crash inside `math.isclose`."""
    from auto_3dx.geometry.sketch import Sketch

    sketch = Sketch(sketch_factory(axis_data_result=tuple("abcdefghi")))

    with pytest.raises(Auto3dxError):
        sketch.support()
