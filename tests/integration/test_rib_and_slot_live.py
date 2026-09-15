"""Live round-trip for Rib and Slot.

Both take two sketches -- a profile and a center curve -- and probe 24 verified
the argument order as `AddNewRib(profile, path)`. "Verified" means created AND
`Part.Update()` succeeded; `AddNewStiffener` and `AddNewRectPattern` create an
object whose update then fails, which is why neither is implemented
(`docs/conventions.md` 1.2.2.1).

A rib can read its profile back but not its path, so these tests assert the
profile only -- the same limit `ensure_rib` documents.

Everything created is removed in a `finally`, and the document is never saved.
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

RIB_NAME = "AUTO3DX_IT_RIB"
SLOT_NAME = "AUTO3DX_IT_SLOT"
RIB_PROFILE = "AUTO3DX_IT_RIB_PROFILE"
RIB_PATH = "AUTO3DX_IT_RIB_PATH"
SLOT_PROFILE = "AUTO3DX_IT_SLOT_PROFILE"
SLOT_PATH = "AUTO3DX_IT_SLOT_PATH"


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


def _swept_sketches(part, profile_name: str, path_name: str):
    """Builds the profile/path pair that probe 24 verified as sweepable."""
    profile = part.sketches.create(profile_name, support="YZ")
    with profile.edit() as editor:
        editor.rectangle(6.0, 6.0)
    path = part.sketches.create(path_name, support="XY")
    with path.edit() as editor:
        editor.line(0.0, 0.0, 50.0, 0.0)
    part.update()
    return profile, path


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


def test_rib_round_trip(part) -> None:
    """A rib sweeps a profile along a path and reads its profile back."""
    body = part.com_object.MainBody
    shapes_before = body.Shapes.Count
    sketches_before = body.Sketches.Count
    for name in (RIB_PROFILE, RIB_PATH):
        if name in part.sketches:
            pytest.skip(f"{name} already exists; clean it up first.")

    try:
        profile, path = _swept_sketches(part, RIB_PROFILE, RIB_PATH)
        rib = part.part_design.create_rib(RIB_NAME, profile, path)
        part.update()

        assert rib.name == RIB_NAME
        assert rib.profile().name == RIB_PROFILE
        assert RIB_NAME in [f.name for f in part.part_design.ribs]
        # A rib must never be reported as a pad or a slot.
        assert RIB_NAME not in [f.name for f in part.part_design.pads]
        assert RIB_NAME not in [f.name for f in part.part_design.slots]

        # ensure_rib hands back the existing feature rather than a second one.
        again = part.part_design.ensure_rib(RIB_NAME, profile, path)
        assert again.com_object == rib.com_object
        assert len([f for f in part.part_design.ribs if f.name == RIB_NAME]) == 1
    finally:
        _cleanup(part, [("remove_rib", RIB_NAME)], [RIB_PROFILE, RIB_PATH])

    assert body.Shapes.Count == shapes_before
    assert body.Sketches.Count == sketches_before


def test_slot_round_trip(part) -> None:
    """A slot is the cutting version of a rib and behaves the same way."""
    body = part.com_object.MainBody
    shapes_before = body.Shapes.Count
    sketches_before = body.Sketches.Count
    for name in (SLOT_PROFILE, SLOT_PATH):
        if name in part.sketches:
            pytest.skip(f"{name} already exists; clean it up first.")

    try:
        profile, path = _swept_sketches(part, SLOT_PROFILE, SLOT_PATH)
        slot = part.part_design.create_slot(SLOT_NAME, profile, path)
        part.update()

        assert slot.name == SLOT_NAME
        assert slot.profile().name == SLOT_PROFILE
        assert SLOT_NAME in [f.name for f in part.part_design.slots]
        assert SLOT_NAME not in [f.name for f in part.part_design.ribs]
        assert SLOT_NAME not in [f.name for f in part.part_design.pockets]
    finally:
        _cleanup(part, [("remove_slot", SLOT_NAME)], [SLOT_PROFILE, SLOT_PATH])

    assert body.Shapes.Count == shapes_before
    assert body.Sketches.Count == sketches_before


def test_get_rib_refuses_another_feature_kind(part) -> None:
    """Asking for a rib by the name of a slot is a lookup failure, not a cast."""
    for name in (SLOT_PROFILE, SLOT_PATH):
        if name in part.sketches:
            pytest.skip(f"{name} already exists; clean it up first.")

    try:
        profile, path = _swept_sketches(part, SLOT_PROFILE, SLOT_PATH)
        part.part_design.create_slot(SLOT_NAME, profile, path)
        part.update()

        with pytest.raises(FeatureNotFoundError):
            part.part_design.get_rib(SLOT_NAME)
        assert part.part_design.get_slot(SLOT_NAME).name == SLOT_NAME
    finally:
        _cleanup(part, [("remove_slot", SLOT_NAME)], [SLOT_PROFILE, SLOT_PATH])
