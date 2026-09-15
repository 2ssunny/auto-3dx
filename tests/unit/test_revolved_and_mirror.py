"""Tests for Shaft, Groove and Mirror features.

All three were verified live against B428_Cloud (probes 17/18/19), where
"verified" means created AND `Part.Update()` succeeded -- `AddNewStiffener` and
`AddNewRectPattern` both returned an object whose update then failed, which is
why neither is implemented (`docs/conventions.md` 1.2.2.1).

    AddNewShaft(iSketch)            -> Shaft
    AddNewGroove(iSketch)           -> Groove
    AddNewMirror(iMirroringElement) -> Mirror   (an origin plane works)

Revolve features have no `FirstLimit`; they carry `FirstAngle`/`SecondAngle`
`Angle` objects, defaulting to 360.0/0.0 degrees.
"""

from collections.abc import Callable
from typing import Any

import pytest

from auto_3dx.errors import (
    FeatureConflictError,
    FeatureNotFoundError,
    ParameterTypeError,
    PartialCreationError,
    UnsupportedSupportError,
    UnsupportedUnitError,
)
from auto_3dx.geometry.part_design import (
    FULL_REVOLUTION,
    Groove,
    Mirror,
    PartDesign,
    Shaft,
)
from auto_3dx.geometry.sketch import SketchCollection

SKETCH_NAME = "AUTO3DX_AXIS_SKETCH"
SHAFT_NAME = "AUTO3DX_SHAFT"
GROOVE_NAME = "AUTO3DX_GROOVE"
MIRROR_NAME = "AUTO3DX_MIRROR"
PAD_NAME = "AUTO3DX_PAD"


def _sketch(part_com: Any, selection: Any = None, name: str = SKETCH_NAME) -> Any:
    """Creates a sketch with a centre line, as a revolve feature requires."""
    sketches = SketchCollection(part_com, selection)
    sketch = sketches.create(name)
    with sketch.edit() as editor:
        # Profile offset from the axis, then the axis itself.
        editor.rectangle(10.0, 6.0, origin_x=20.0, origin_y=0.0)
        axis = editor.line(0.0, 0.0, 0.0, 20.0)
    sketch.set_center_line(axis)
    return sketch


# --- creation ----------------------------------------------------------------


def test_set_center_line_writes_the_sketch_axis(part_factory: Callable[..., Any]) -> None:
    """A revolve needs an axis, and this is how it is supplied."""
    part_com = part_factory()
    sketch = _sketch(part_com)

    assert sketch.com_object.CenterLine is not None


def test_create_shaft_passes_the_raw_sketch(part_factory: Callable[..., Any]) -> None:
    """`AddNewShaft` takes the COM object, not the wrapper, and the name is set."""
    part_com = part_factory()
    design = PartDesign(part_com)
    sketch = _sketch(part_com)

    shaft = design.create_shaft(SHAFT_NAME, sketch)

    assert part_com.ShapeFactory.add_new_shaft_calls == [sketch.com_object]
    assert shaft.name == SHAFT_NAME
    assert isinstance(shaft, Shaft)


def test_create_groove_uses_its_own_factory_method(
    part_factory: Callable[..., Any],
) -> None:
    """A groove must not be created through `AddNewShaft`."""
    part_com = part_factory()
    design = PartDesign(part_com)
    sketch = _sketch(part_com)

    groove = design.create_groove(GROOVE_NAME, sketch)

    assert part_com.ShapeFactory.add_new_groove_calls == [sketch.com_object]
    assert part_com.ShapeFactory.add_new_shaft_calls == []
    assert isinstance(groove, Groove)


def test_create_mirror_passes_the_requested_plane(
    part_factory: Callable[..., Any],
) -> None:
    """A mirror is built from a plane, not a sketch."""
    part_com = part_factory()
    design = PartDesign(part_com)

    mirror = design.create_mirror(MIRROR_NAME, support="YZ")

    assert part_com.ShapeFactory.add_new_mirror_calls == [
        part_com.OriginElements.PlaneYZ
    ]
    assert isinstance(mirror, Mirror)
    assert mirror.name == MIRROR_NAME


def test_create_mirror_rejects_an_unknown_support(
    part_factory: Callable[..., Any],
) -> None:
    """Only the three origin planes are addressable."""
    part_com = part_factory()
    design = PartDesign(part_com)

    with pytest.raises(UnsupportedSupportError):
        design.create_mirror(MIRROR_NAME, support="XZ")

    assert part_com.ShapeFactory.add_new_mirror_calls == []


# --- angles ------------------------------------------------------------------


def test_new_shaft_defaults_to_a_full_revolution(
    part_factory: Callable[..., Any],
) -> None:
    """Verified defaults for a freshly created revolve feature."""
    part_com = part_factory()
    shaft = PartDesign(part_com).create_shaft(SHAFT_NAME, _sketch(part_com))

    assert shaft.first_angle == FULL_REVOLUTION == 360.0
    assert shaft.second_angle == 0.0


def test_set_first_angle_writes_a_float(part_factory: Callable[..., Any]) -> None:
    """`Angle.Value` is a COM double, so an int must arrive as a float."""
    part_com = part_factory()
    shaft = PartDesign(part_com).create_shaft(SHAFT_NAME, _sketch(part_com))

    shaft.set_first_angle(90)

    assert shaft.com_object.FirstAngle.Value == 90.0
    assert isinstance(shaft.com_object.FirstAngle.Value, float)


def test_set_second_angle_writes_the_second_angle_only(
    part_factory: Callable[..., Any],
) -> None:
    """The two angles must not be confused with each other."""
    part_com = part_factory()
    shaft = PartDesign(part_com).create_shaft(SHAFT_NAME, _sketch(part_com))

    shaft.set_second_angle(30)

    assert shaft.second_angle == 30.0
    assert shaft.first_angle == FULL_REVOLUTION


def test_set_angle_rejects_a_bool(part_factory: Callable[..., Any]) -> None:
    """`bool` is a subclass of `int`, so `True` must not become 1.0 degrees."""
    part_com = part_factory()
    shaft = PartDesign(part_com).create_shaft(SHAFT_NAME, _sketch(part_com))

    with pytest.raises(ParameterTypeError):
        shaft.set_first_angle(True)  # type: ignore[arg-type]

    assert shaft.first_angle == FULL_REVOLUTION


def test_set_angle_rejects_a_non_numeric_value(
    part_factory: Callable[..., Any],
) -> None:
    """A string angle must be refused before it reaches the model."""
    part_com = part_factory()
    shaft = PartDesign(part_com).create_shaft(SHAFT_NAME, _sketch(part_com))

    with pytest.raises(ParameterTypeError):
        shaft.set_first_angle("90")  # type: ignore[arg-type]


def test_set_angle_rejects_an_unsupported_unit(
    part_factory: Callable[..., Any],
) -> None:
    """Only degrees are verified against this installation."""
    part_com = part_factory()
    shaft = PartDesign(part_com).create_shaft(SHAFT_NAME, _sketch(part_com))

    with pytest.raises(UnsupportedUnitError):
        shaft.set_first_angle(90, unit="rad")


def test_set_angle_rejects_an_unhashable_unit(
    part_factory: Callable[..., Any],
) -> None:
    """`in` on a frozenset hashes its operand, so a list must not raise TypeError."""
    part_com = part_factory()
    shaft = PartDesign(part_com).create_shaft(SHAFT_NAME, _sketch(part_com))

    with pytest.raises(UnsupportedUnitError):
        shaft.set_first_angle(90, unit=[])  # type: ignore[arg-type]


def test_first_angle_parameter_targets_the_angle_object(
    part_factory: Callable[..., Any],
) -> None:
    """This is what a formula drives, so it must be the raw FirstAngle."""
    part_com = part_factory()
    shaft = PartDesign(part_com).create_shaft(SHAFT_NAME, _sketch(part_com))

    assert (
        shaft.first_angle_parameter().com_object is shaft.com_object.FirstAngle
    )


# --- kinds do not leak -------------------------------------------------------


def test_feature_kinds_stay_separate(part_factory: Callable[..., Any]) -> None:
    """All five kinds share `MainBody.Shapes`; only the type name separates them."""
    part_com = part_factory()
    design = PartDesign(part_com)
    sketch = _sketch(part_com)
    design.create_pad(PAD_NAME, sketch, 12.0)
    design.create_pocket("AUTO3DX_POCKET", sketch, 5.0)
    design.create_shaft(SHAFT_NAME, sketch)
    design.create_groove(GROOVE_NAME, sketch)
    design.create_mirror(MIRROR_NAME)

    assert [f.name for f in design.pads] == [PAD_NAME]
    assert [f.name for f in design.pockets] == ["AUTO3DX_POCKET"]
    assert [f.name for f in design.shafts] == [SHAFT_NAME]
    assert [f.name for f in design.grooves] == [GROOVE_NAME]
    assert [f.name for f in design.mirrors] == [MIRROR_NAME]


def test_get_shaft_does_not_return_a_pad(part_factory: Callable[..., Any]) -> None:
    """A pad holding the requested name must not satisfy a shaft lookup."""
    part_com = part_factory()
    design = PartDesign(part_com)
    design.create_pad(SHAFT_NAME, _sketch(part_com), 12.0)

    with pytest.raises(FeatureNotFoundError):
        design.get_shaft(SHAFT_NAME)


# --- ensure ------------------------------------------------------------------


def test_ensure_shaft_creates_when_absent(part_factory: Callable[..., Any]) -> None:
    """A missing shaft is created."""
    part_com = part_factory()
    design = PartDesign(part_com)

    design.ensure_shaft(SHAFT_NAME, _sketch(part_com))

    assert len(part_com.ShapeFactory.add_new_shaft_calls) == 1


def test_ensure_shaft_reuses_the_same_sketch(part_factory: Callable[..., Any]) -> None:
    """A name match on the same sketch must not create a second shaft."""
    part_com = part_factory()
    design = PartDesign(part_com)
    sketch = _sketch(part_com)
    design.create_shaft(SHAFT_NAME, sketch)

    design.ensure_shaft(SHAFT_NAME, sketch)

    assert len(part_com.ShapeFactory.add_new_shaft_calls) == 1


def test_ensure_shaft_accepts_another_wrapper_for_the_same_sketch(
    part_factory: Callable[..., Any],
) -> None:
    """COM hands out a fresh wrapper each time, so identity must use `==`."""
    from auto_3dx.geometry.sketch import Sketch

    part_com = part_factory()
    design = PartDesign(part_com)
    sketch = _sketch(part_com)
    design.create_shaft(SHAFT_NAME, sketch)
    other = Sketch(sketch.com_object.another_wrapper())
    assert other.com_object is not sketch.com_object

    design.ensure_shaft(SHAFT_NAME, other)

    assert len(part_com.ShapeFactory.add_new_shaft_calls) == 1


def test_ensure_shaft_refuses_a_different_sketch(
    part_factory: Callable[..., Any],
) -> None:
    """Re-pointing a shaft at another profile must be refused."""
    part_com = part_factory()
    design = PartDesign(part_com)
    first = _sketch(part_com)
    other = _sketch(part_com, name="AUTO3DX_OTHER_SKETCH")
    design.create_shaft(SHAFT_NAME, first)

    with pytest.raises(FeatureConflictError):
        design.ensure_shaft(SHAFT_NAME, other)


def test_ensure_shaft_leaves_angles_alone(part_factory: Callable[..., Any]) -> None:
    """Required by conventions 6.13: `ensure` must never touch the angles."""
    part_com = part_factory()
    design = PartDesign(part_com)
    sketch = _sketch(part_com)
    shaft = design.create_shaft(SHAFT_NAME, sketch)
    shaft.set_first_angle(90)

    design.ensure_shaft(SHAFT_NAME, sketch)

    assert shaft.first_angle == 90.0


def test_ensure_mirror_reuses_without_comparing_the_plane(
    part_factory: Callable[..., Any],
) -> None:
    """A known limitation, not a bug.

    There is no verified way to read a `Mirror`'s plane back, so a name match
    reuses the existing mirror even if a different support is requested. The
    docstring on `ensure_mirror` says so; this test pins the behaviour so the
    limitation is visible rather than surprising.
    """
    part_com = part_factory()
    design = PartDesign(part_com)
    design.create_mirror(MIRROR_NAME, support="YZ")

    design.ensure_mirror(MIRROR_NAME, support="ZX")

    assert len(part_com.ShapeFactory.add_new_mirror_calls) == 1


# --- removal and failure modes ----------------------------------------------


@pytest.mark.parametrize(
    ("create", "remove", "name"),
    [
        ("create_shaft", "remove_shaft", SHAFT_NAME),
        ("create_groove", "remove_groove", GROOVE_NAME),
    ],
)
def test_remove_revolved_feature_uses_the_selection(
    part_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
    create: str,
    remove: str,
    name: str,
) -> None:
    """`Shapes` has no `Remove`; deletion goes through `Editor.Selection`."""
    part_com = part_factory()
    selection = selection_factory()
    design = PartDesign(part_com, selection)
    feature = getattr(design, create)(name, _sketch(part_com, selection))
    selection.calls.clear()

    getattr(design, remove)(name)

    assert selection.calls[:3] == ["Clear", "Add", "Delete"]
    assert selection.deleted == [feature.com_object]


def test_remove_mirror_uses_the_selection(
    part_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
) -> None:
    """Mirrors delete the same way."""
    part_com = part_factory()
    selection = selection_factory()
    design = PartDesign(part_com, selection)
    mirror = design.create_mirror(MIRROR_NAME)
    selection.calls.clear()

    design.remove_mirror(MIRROR_NAME)

    assert selection.deleted == [mirror.com_object]


def test_shaft_name_write_failure_reports_the_leftover(
    part_factory: Callable[..., Any],
    shape_factory_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
    com_error_factory: Callable[[], BaseException],
) -> None:
    """`AddNewShaft` already changed the model before the name write failed."""
    part_com = part_factory()
    part_com.ShapeFactory = shape_factory_factory(
        shapes=part_com.MainBody.Shapes,
        revolve_name_write_exception=com_error_factory(),
    )
    selection = selection_factory()
    design = PartDesign(part_com, selection)

    with pytest.raises(PartialCreationError) as caught:
        design.create_shaft(SHAFT_NAME, _sketch(part_com, selection))

    # The default name is what is actually left in the model.
    assert "Shaft" in str(caught.value)
    # Rollback is unsafe here, so the library reports instead of deleting.
    assert selection.deleted == []


def test_revolved_and_mirror_operations_never_update(
    part_factory: Callable[..., Any],
) -> None:
    """The caller decides when to update, so edits can be batched."""
    part_com = part_factory()
    design = PartDesign(part_com)
    sketch = _sketch(part_com)

    shaft = design.create_shaft(SHAFT_NAME, sketch)
    shaft.set_first_angle(90)
    design.ensure_shaft(SHAFT_NAME, sketch)
    design.create_groove(GROOVE_NAME, sketch)
    design.create_mirror(MIRROR_NAME)

    assert part_com.update_calls == 0
