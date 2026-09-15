"""Tests for the Rib and Slot Part Design features.

Verified live against B428_Cloud (probe 24, `docs/conventions.md` section
1.2.5):

    AddNewRib(iSketch, iCenterCurve)  -> Rib    created AND Part.Update() OK
    AddNewSlot(iSketch, iCenterCurve) -> Slot   created AND Part.Update() OK

Both take a PROFILE sketch and a PATH (center curve) sketch. Only the profile
can be read back afterwards (`Rib.Sketch`/`Slot.Sketch`); there is no
verified way to read the path sketch, so `ensure_rib`/`ensure_slot` cannot
compare it -- see the documented limitation pinned below.
"""

from collections.abc import Callable
from typing import Any

import pytest

from auto_3dx.errors import (
    FeatureConflictError,
    FeatureNotFoundError,
    PartialCreationError,
)
from auto_3dx.geometry.part_design import PartDesign, Rib, Slot
from auto_3dx.geometry.sketch import Sketch

RIB_NAME = "AUTO3DX_RIB"
SLOT_NAME = "AUTO3DX_SLOT"
PAD_NAME = "AUTO3DX_PAD"
POCKET_NAME = "AUTO3DX_POCKET"
SHAFT_NAME = "AUTO3DX_SHAFT"
GROOVE_NAME = "AUTO3DX_GROOVE"
MIRROR_NAME = "AUTO3DX_MIRROR"


def _sketch(sketch_factory: Callable[..., Any], name: str = "Sketch.1") -> Sketch:
    """Wraps a fresh fake sketch, as either a rib/slot profile or path."""
    return Sketch(sketch_factory(name=name))


# --- creation ----------------------------------------------------------------


def test_create_rib_passes_profile_then_path_and_sets_name(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
) -> None:
    """`AddNewRib` takes the raw sketch COM objects, profile first."""
    part = part_factory()
    design = PartDesign(part)
    profile = _sketch(sketch_factory, "Profile.1")
    path = _sketch(sketch_factory, "Path.1")

    rib = design.create_rib(RIB_NAME, profile, path)

    assert part.ShapeFactory.add_new_rib_calls == [(profile.com_object, path.com_object)]
    assert rib.name == RIB_NAME
    assert isinstance(rib, Rib)


def test_create_slot_passes_profile_then_path_and_sets_name(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
) -> None:
    """A slot must not be created through `AddNewRib`."""
    part = part_factory()
    design = PartDesign(part)
    profile = _sketch(sketch_factory, "Profile.1")
    path = _sketch(sketch_factory, "Path.1")

    slot = design.create_slot(SLOT_NAME, profile, path)

    assert part.ShapeFactory.add_new_slot_calls == [(profile.com_object, path.com_object)]
    assert part.ShapeFactory.add_new_rib_calls == []
    assert slot.name == SLOT_NAME
    assert isinstance(slot, Slot)


# --- kinds do not leak ---------------------------------------------------------


def test_feature_kinds_stay_separate(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
) -> None:
    """All seven kinds share `MainBody.Shapes`; only the type name separates them."""
    part = part_factory()
    design = PartDesign(part)
    sketch = _sketch(sketch_factory, "Sketch.1")
    path = _sketch(sketch_factory, "Path.1")

    design.create_pad(PAD_NAME, sketch, 12.0)
    design.create_pocket(POCKET_NAME, sketch, 5.0)
    design.create_shaft(SHAFT_NAME, sketch)
    design.create_groove(GROOVE_NAME, sketch)
    design.create_mirror(MIRROR_NAME)
    design.create_rib(RIB_NAME, sketch, path)
    design.create_slot(SLOT_NAME, sketch, path)

    assert [f.name for f in design.ribs] == [RIB_NAME]
    assert [f.name for f in design.slots] == [SLOT_NAME]
    assert [f.name for f in design.pads] == [PAD_NAME]
    assert [f.name for f in design.pockets] == [POCKET_NAME]
    assert [f.name for f in design.shafts] == [SHAFT_NAME]
    assert [f.name for f in design.grooves] == [GROOVE_NAME]
    assert [f.name for f in design.mirrors] == [MIRROR_NAME]


def test_get_rib_does_not_return_a_pad(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
) -> None:
    """A pad holding the requested name must not satisfy a rib lookup."""
    part = part_factory()
    design = PartDesign(part)
    design.create_pad(RIB_NAME, _sketch(sketch_factory), 12.0)

    with pytest.raises(FeatureNotFoundError):
        design.get_rib(RIB_NAME)


def test_get_slot_does_not_return_a_rib(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
) -> None:
    """A rib holding the requested name must not satisfy a slot lookup."""
    part = part_factory()
    design = PartDesign(part)
    design.create_rib(SLOT_NAME, _sketch(sketch_factory), _sketch(sketch_factory, "Path.1"))

    with pytest.raises(FeatureNotFoundError):
        design.get_slot(SLOT_NAME)


# --- profile() -----------------------------------------------------------------


def test_rib_profile_returns_the_passed_profile(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
) -> None:
    """`profile()` wraps `Rib.Sketch` -- the profile, never the path."""
    part = part_factory()
    design = PartDesign(part)
    profile = _sketch(sketch_factory, "Profile.1")
    path = _sketch(sketch_factory, "Path.1")

    rib = design.create_rib(RIB_NAME, profile, path)

    assert rib.profile().com_object is profile.com_object


def test_slot_profile_returns_the_passed_profile(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
) -> None:
    """Same accessor contract as `Rib.profile()`."""
    part = part_factory()
    design = PartDesign(part)
    profile = _sketch(sketch_factory, "Profile.1")
    path = _sketch(sketch_factory, "Path.1")

    slot = design.create_slot(SLOT_NAME, profile, path)

    assert slot.profile().com_object is profile.com_object


# --- ensure_rib ------------------------------------------------------------------


def test_ensure_rib_creates_when_absent(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
) -> None:
    """A missing rib is created."""
    part = part_factory()
    design = PartDesign(part)
    profile = _sketch(sketch_factory, "Profile.1")
    path = _sketch(sketch_factory, "Path.1")

    design.ensure_rib(RIB_NAME, profile, path)

    assert len(part.ShapeFactory.add_new_rib_calls) == 1


def test_ensure_rib_reuses_the_same_profile(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
) -> None:
    """A name match on the same profile must not create a second rib."""
    part = part_factory()
    design = PartDesign(part)
    profile = _sketch(sketch_factory, "Profile.1")
    path = _sketch(sketch_factory, "Path.1")
    design.create_rib(RIB_NAME, profile, path)

    design.ensure_rib(RIB_NAME, profile, path)

    assert len(part.ShapeFactory.add_new_rib_calls) == 1


def test_ensure_rib_accepts_another_wrapper_for_the_same_profile(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
) -> None:
    """COM hands out a fresh wrapper each time, so identity must use `==`, never `is`."""
    part = part_factory()
    design = PartDesign(part)
    fake_profile = sketch_factory(name="Profile.1")
    profile = Sketch(fake_profile)
    path = _sketch(sketch_factory, "Path.1")
    design.create_rib(RIB_NAME, profile, path)
    other = Sketch(fake_profile.another_wrapper())
    assert other.com_object is not profile.com_object
    assert other.com_object == profile.com_object

    design.ensure_rib(RIB_NAME, other, path)

    assert len(part.ShapeFactory.add_new_rib_calls) == 1


def test_ensure_rib_refuses_a_different_profile(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
) -> None:
    """Re-pointing a rib at another profile must be refused."""
    part = part_factory()
    design = PartDesign(part)
    profile = _sketch(sketch_factory, "Profile.1")
    other_profile = _sketch(sketch_factory, "Profile.2")
    path = _sketch(sketch_factory, "Path.1")
    design.create_rib(RIB_NAME, profile, path)

    with pytest.raises(FeatureConflictError):
        design.ensure_rib(RIB_NAME, other_profile, path)

    assert len(part.ShapeFactory.add_new_rib_calls) == 1


def test_ensure_rib_silently_reuses_a_different_path_with_the_same_profile(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
) -> None:
    """A documented limitation, not a bug.

    There is no verified way to read a Rib's path (center curve) sketch back
    from COM, so `ensure_rib` cannot detect that a different path was
    requested for an existing rib built on the same profile -- it reuses the
    existing rib unchanged. `ensure_rib`'s own docstring says so explicitly;
    this test pins the behaviour so the limitation stays visible rather than
    becoming a silent surprise.
    """
    part = part_factory()
    design = PartDesign(part)
    profile = _sketch(sketch_factory, "Profile.1")
    first_path = _sketch(sketch_factory, "Path.1")
    other_path = _sketch(sketch_factory, "Path.2")
    design.create_rib(RIB_NAME, profile, first_path)

    design.ensure_rib(RIB_NAME, profile, other_path)

    assert len(part.ShapeFactory.add_new_rib_calls) == 1


# --- removal and failure modes ---------------------------------------------------


@pytest.mark.parametrize(
    ("create", "remove", "name"),
    [
        ("create_rib", "remove_rib", RIB_NAME),
        ("create_slot", "remove_slot", SLOT_NAME),
    ],
)
def test_remove_uses_the_selection(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
    create: str,
    remove: str,
    name: str,
) -> None:
    """`Shapes` has no `Remove`; deletion goes through `Editor.Selection`."""
    part = part_factory()
    selection = selection_factory()
    design = PartDesign(part, selection)
    profile = _sketch(sketch_factory, "Profile.1")
    path = _sketch(sketch_factory, "Path.1")
    feature = getattr(design, create)(name, profile, path)
    selection.calls.clear()

    getattr(design, remove)(name)

    assert selection.calls[:3] == ["Clear", "Add", "Delete"]
    assert selection.deleted == [feature.com_object]


@pytest.mark.parametrize(
    ("create", "kind_exception_kwarg"),
    [
        ("create_rib", "rib_name_write_exception"),
        ("create_slot", "slot_name_write_exception"),
    ],
)
def test_name_write_failure_reports_the_leftover(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
    shape_factory_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
    com_error_factory: Callable[[], BaseException],
    create: str,
    kind_exception_kwarg: str,
) -> None:
    """`AddNewRib`/`AddNewSlot` already changed the model before the rename failed."""
    part = part_factory()
    part.ShapeFactory = shape_factory_factory(
        shapes=part.MainBody.Shapes,
        **{kind_exception_kwarg: com_error_factory()},
    )
    selection = selection_factory()
    design = PartDesign(part, selection)
    profile = _sketch(sketch_factory, "Profile.1")
    path = _sketch(sketch_factory, "Path.1")

    with pytest.raises(PartialCreationError) as caught:
        getattr(design, create)(RIB_NAME, profile, path)

    # The default name is what is actually left in the model.
    message = str(caught.value)
    assert "Rib" in message or "Slot" in message
    # Rollback is unsafe here, so the library reports instead of deleting.
    assert selection.deleted == []


def test_rib_and_slot_operations_never_update(
    part_factory: Callable[..., Any],
    sketch_factory: Callable[..., Any],
) -> None:
    """The caller decides when to update, so edits can be batched."""
    part = part_factory()
    design = PartDesign(part)
    profile = _sketch(sketch_factory, "Profile.1")
    path = _sketch(sketch_factory, "Path.1")

    design.create_rib(RIB_NAME, profile, path)
    design.ensure_rib(RIB_NAME, profile, path)
    design.create_slot(SLOT_NAME, profile, path)

    assert part.update_calls == 0
