"""Live checks for the Multi-sections Solid (CATIA Loft) Part Design feature.

Sections are built through public APIs only: a closed profile on XY, an offset plane (with
the update CATIA needs before a sketch can go on it), and a closed profile on that plane.

What builds depends on the sections' corners (`docs/conventions.md` section 1.8). With
`AddSectionToLoft(reference, 1, None)` -- no closing points -- corner-free sections built
(two circles; a single closed NACA spline per section), while sections with corners
failed `Part.Update()` (two rectangles; an open NACA spline closed by a line). The first
test uses circles for the whole lifecycle; the second pins the rectangle failure and
the recovery the API documents for it.

Everything created is removed in a `finally`: the feature (which takes its section
sketches with it), any sketch left over, and the one plane each test created, never the
whole geometrical set. Nothing is saved.
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

from auto_3dx import Catia, PartUpdateError  # noqa: E402
from auto_3dx.errors import (  # noqa: E402
    Auto3dxError,
    CatiaConnectionError,
    NoActiveEditorError,
    NoActivePartError,
)
from auto_3dx.geometry.part_design import MULTI_SECTION_SOLID_KIND  # noqa: E402
from auto_3dx.geometry.planes import GEOMETRICAL_SET_NAME  # noqa: E402

ROOT_RADIUS, TIP_RADIUS = 20.0, 12.0
ROOT_WIDTH, ROOT_HEIGHT = 40.0, 20.0
TIP_WIDTH, TIP_HEIGHT = 30.0, 15.0
TIP_OFFSET = 30.0
# Clear of anything near the origin, so the solid adds material rather than merging.
SECTION_CENTRE_X = -500.0


@pytest.fixture
def part() -> Any:
    """Returns the active Part, skipping when no suitable session is available."""
    try:
        catia = Catia.attach()
    except CatiaConnectionError as error:
        pytest.skip(f"No running 3DEXPERIENCE session: {error}")
    try:
        return catia.active_part()
    except (NoActiveEditorError, NoActivePartError) as error:
        pytest.skip(f"No Part is being edited: {error}")


def _names(label: str) -> "dict[str, str]":
    token = uuid.uuid4().hex[:8].upper()
    return {
        "root": f"AUTO3DX_IT_MSS_{label}_ROOT_{token}",
        "tip": f"AUTO3DX_IT_MSS_{label}_TIP_{token}",
        "plane": f"AUTO3DX_IT_MSS_{label}_PLANE_{token}",
        "solid": f"AUTO3DX_IT_MSS_{label}_SOLID_{token}",
    }


def _sections(part: Any, names: "dict[str, str]", shape: str) -> "list[Any]":
    """Builds the root and tip section sketches of the given shape."""
    root = part.sketches.create(names["root"], support="XY")
    with root.edit() as editor:
        if shape == "circle":
            editor.circle(SECTION_CENTRE_X, 0.0, ROOT_RADIUS)
        else:
            editor.rectangle(ROOT_WIDTH, ROOT_HEIGHT, origin_x=SECTION_CENTRE_X)
    part.update()
    plane = part.planes.create_offset(names["plane"], "XY", TIP_OFFSET)
    part.update()
    tip = part.sketches.create(names["tip"], support=plane)
    with tip.edit() as editor:
        if shape == "circle":
            editor.circle(SECTION_CENTRE_X, 0.0, TIP_RADIUS)
        else:
            editor.rectangle(TIP_WIDTH, TIP_HEIGHT, origin_x=SECTION_CENTRE_X)
    part.update()
    return [root, tip]


def _plane_set_exists(part: Any) -> bool:
    return GEOMETRICAL_SET_NAME in [item.name for item in part.inspect.geometrical_sets()]


def _volume_of_main_body(part: Any) -> float:
    """CATIA cannot measure an empty body, whose volume is zero anyway."""
    if int(part.com_object.MainBody.Shapes.Count) == 0:
        return 0.0
    return part.measurement.measure().volume_mm3


def _remove_own(part: Any, names: "dict[str, str]", plane_set_existed: bool) -> None:
    """Removes exactly what one test created, then rebuilds.

    The plane's geometrical set goes too, but only if this test created it and it is
    empty again.
    """
    try:
        part.part_design.remove_multi_section_solid(names["solid"])
    except Auto3dxError:
        pass
    for key in ("tip", "root"):
        try:
            part.sketches.remove(names[key])
        except Auto3dxError:
            pass
    try:
        part.planes.remove(part.planes.get(names["plane"]))
    except Auto3dxError:
        pass
    plane_set = [s for s in part.inspect.geometrical_sets() if s.name == GEOMETRICAL_SET_NAME]
    if not plane_set_existed and plane_set and not plane_set[0].elements:
        part.planes.remove_geometrical_set()
    part.update()


def test_a_multi_section_solid_is_created_rediscovered_and_removed(part: Any) -> None:
    names = _names("CIRCLE")
    before = part.inspect.summary()
    plane_set_existed = _plane_set_exists(part)
    volume_before = _volume_of_main_body(part)

    try:
        sections = _sections(part, names, "circle")
        solid = part.part_design.create_multi_section_solid(names["solid"], sections=sections)
        part.update()

        assert solid.name == names["solid"]
        assert part.is_up_to_date()
        after = part.inspect.summary()
        assert (names["solid"], MULTI_SECTION_SOLID_KIND, True) in [
            (feature.name, feature.kind, feature.supported) for feature in after.features
        ]
        assert after.topology != before.topology
        volume = part.measurement.measure().volume_mm3
        assert math.isfinite(volume)
        # A frustum of radii 20 and 12 over 30 mm, where nothing else is.
        frustum = math.pi * TIP_OFFSET / 3 * (
            ROOT_RADIUS**2 + ROOT_RADIUS * TIP_RADIUS + TIP_RADIUS**2
        )
        assert volume - volume_before == pytest.approx(frustum, rel=0.01)

        # A second wrapper holds nothing from the first: what it finds is in the model.
        fresh = Catia.attach().active_part()
        found = fresh.part_design.get_multi_section_solid(names["solid"])
        assert found.section_names() == [names["root"], names["tip"]]

        fresh.part_design.remove_multi_section_solid(names["solid"])
        fresh.update()
        assert names["solid"] not in [s.name for s in fresh.part_design.multi_section_solids]
        # Deleting the feature took its section sketches with it (probe 40).
        assert names["root"] not in fresh.inspect.sketches()
    finally:
        _remove_own(part, names, plane_set_existed)

    restored = part.inspect.summary()
    assert [(f.name, f.kind) for f in restored.features] == [
        (f.name, f.kind) for f in before.features
    ]
    assert restored.sketches == before.sketches
    assert restored.topology == before.topology
    assert part.is_up_to_date()


def test_sections_with_corners_fail_the_update_and_removal_recovers(part: Any) -> None:
    """Two rectangles do not build without closing points; removing the feature recovers."""
    names = _names("RECT")
    before = part.inspect.summary()
    plane_set_existed = _plane_set_exists(part)

    try:
        sections = _sections(part, names, "rectangle")
        part.part_design.create_multi_section_solid(names["solid"], sections=sections)

        with pytest.raises(PartUpdateError):
            part.update()
        assert not part.is_up_to_date()

        part.part_design.remove_multi_section_solid(names["solid"])
        part.update()
        assert part.is_up_to_date()
    finally:
        _remove_own(part, names, plane_set_existed)

    restored = part.inspect.summary()
    assert [(f.name, f.kind) for f in restored.features] == [
        (f.name, f.kind) for f in before.features
    ]
    assert restored.sketches == before.sketches
    assert restored.topology == before.topology
