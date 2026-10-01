"""Live checks for Multi-Body support: bodies, `work_in`, visibility, guarded removal.

Everything happens in bodies this test creates, on the disposable Part named by
`AUTO3DX_LIVE_PART` (the session refuses any other). Body B also gets an offset plane made
inside `work_in`, which checks that a plane hands the In-Work Object back to the work body
rather than the main body. Cleanup removes only the two bodies and the one plane this
test made. Nothing is saved.
"""

import math
import sys
from typing import Any

import pytest

pytestmark = pytest.mark.integration

if sys.platform != "win32":
    pytest.skip("Windows COM is required.", allow_module_level=True)

pytest.importorskip("pywintypes", reason="pywin32 is required.")

from auto_3dx import Catia  # noqa: E402
from auto_3dx.errors import (  # noqa: E402
    Auto3dxError,
    BodyRemovalError,
    CatiaConnectionError,
    NoActiveEditorError,
    NoActivePartError,
    ParameterNameError,
)
from auto_3dx.geometry.planes import GEOMETRICAL_SET_NAME  # noqa: E402

BODY_A, BODY_B = "AUTO3DX_IT_BODY_A", "AUTO3DX_IT_BODY_B"
PLANE = "AUTO3DX_IT_BODY_B_TOP_PLANE"
A_SIDE, A_HEIGHT = 20.0, 10.0
B_SIDE, B_HEIGHT, B_X = 30.0, 12.0, 100.0
HOLE_SIDE, HOLE_DEPTH, HOLE_X = 10.0, 5.0, 110.0


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


def _sdk_set_exists(part: Any) -> bool:
    return GEOMETRICAL_SET_NAME in [
        item.name for item in part.inspect.geometrical_sets()
    ]


def _cleanup(part: Any, set_existed: bool) -> None:
    """Removes the two bodies, the plane, and the plane set only if this test created it."""
    for name in (BODY_B, BODY_A):
        try:
            part.bodies.remove(name, delete_contents=True)
        except Auto3dxError:
            pass
    try:
        part.planes.remove(part.planes.get(PLANE))
    except Auto3dxError:
        pass
    sdk_set = [
        item
        for item in part.inspect.geometrical_sets()
        if item.name == GEOMETRICAL_SET_NAME
    ]
    if not set_existed and sdk_set and not sdk_set[0].elements:
        part.planes.remove_geometrical_set()
    part.update()


def test_features_land_in_their_own_bodies_and_survive_rediscovery(part: Any) -> None:
    if {BODY_A, BODY_B} & set(part.bodies.names()):
        pytest.skip("Bodies with this test's names already exist; they are not ours.")
    before = part.inspect.summary()
    set_existed = _sdk_set_exists(part)

    try:
        body_a = part.bodies.create(BODY_A)
        assert part.inspect.in_work_object() == before.in_work_object
        with part.work_in(body_a):
            sketch = part.sketches.create(f"{BODY_A}_SKETCH", support="XY")
            with sketch.edit() as editor:
                editor.rectangle(A_SIDE, A_SIDE)
            part.part_design.create_pad(f"{BODY_A}_PAD", sketch, A_HEIGHT)
        assert part.inspect.in_work_object() == before.in_work_object
        part.update()

        body_b = part.bodies.create(BODY_B)
        with part.work_in(BODY_B):
            sketch = part.sketches.create(f"{BODY_B}_SKETCH", support="XY")
            with sketch.edit() as editor:
                editor.rectangle(B_SIDE, B_SIDE, origin_x=B_X)
            part.part_design.create_pad(f"{BODY_B}_PAD", sketch, B_HEIGHT)
            plane = part.planes.create_offset(PLANE, "XY", B_HEIGHT)
            part.update()
            hole = part.sketches.create(f"{BODY_B}_POCKET_SKETCH", support=plane)
            with hole.edit() as editor:
                editor.rectangle(HOLE_SIDE, HOLE_SIDE, origin_x=HOLE_X)
            part.part_design.create_pocket(f"{BODY_B}_POCKET", hole, HOLE_DEPTH)
            assert part.part_design.get_pocket(f"{BODY_B}_POCKET").name.endswith(
                "POCKET"
            )
        part.update()
        assert part.is_up_to_date()
        assert part.inspect.in_work_object() == before.in_work_object

        # A second wrapper holds nothing from the first: what it finds is in the model.
        fresh = Catia.attach().active_part()
        found_a, found_b = fresh.bodies.get(BODY_A), fresh.bodies.get(BODY_B)
        assert not found_a.is_main and not found_b.is_main
        assert [(f.name, f.kind) for f in found_a.features] == [
            (f"{BODY_A}_PAD", "Pad")
        ]
        assert [(f.name, f.kind) for f in found_b.features] == [
            (f"{BODY_B}_PAD", "Pad"),
            (f"{BODY_B}_POCKET", "Pocket"),
        ]
        assert found_a.sketch_names == (f"{BODY_A}_SKETCH",)
        assert found_b.sketch_names == (f"{BODY_B}_SKETCH", f"{BODY_B}_POCKET_SKETCH")
        main = [body for body in fresh.inspect.bodies() if body.is_main][0]
        assert main.features == before.bodies[0].features

        volume_a = fresh.measurement.measure(found_a).volume_mm3
        volume_b = fresh.measurement.measure(found_b).volume_mm3
        assert volume_a == pytest.approx(A_SIDE * A_SIDE * A_HEIGHT, rel=1e-6)
        assert volume_b == pytest.approx(
            B_SIDE * B_SIDE * B_HEIGHT - HOLE_SIDE * HOLE_SIDE * HOLE_DEPTH, rel=1e-6
        )

        found_a.hide()
        assert found_a.is_visible is False
        assert found_b.is_visible is True
        found_a.show()
        assert found_a.is_visible is True
        assert fresh.measurement.measure(found_a).volume_mm3 == pytest.approx(volume_a)
        assert math.isfinite(volume_b)

        with pytest.raises(BodyRemovalError):
            fresh.bodies.remove(BODY_A)
        assert BODY_A in fresh.bodies.names()
        assert body_b.name == BODY_B
    finally:
        _cleanup(part, set_existed)

    after = part.inspect.summary()
    assert [(b.name, b.features, b.sketches) for b in after.bodies] == [
        (b.name, b.features, b.sketches) for b in before.bodies
    ]
    assert after.in_work_object == before.in_work_object
    assert after.geometrical_sets == before.geometrical_sets


def test_the_in_work_object_is_restored_when_work_in_raises(part: Any) -> None:
    if BODY_A in part.bodies.names():
        pytest.skip("A body with this test's name already exists; it is not ours.")
    before = part.inspect.in_work_object()

    try:
        body = part.bodies.create(BODY_A)
        with pytest.raises(ParameterNameError):
            with part.work_in(body):
                part.sketches.create("  ", support="XY")
        assert part.inspect.in_work_object() == before
    finally:
        try:
            part.bodies.remove(BODY_A, delete_contents=True)
        except Auto3dxError:
            pass
        part.update()

    assert BODY_A not in part.bodies.names()
    assert part.inspect.in_work_object() == before
