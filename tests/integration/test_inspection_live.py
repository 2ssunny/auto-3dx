"""Live checks for `part.inspect` (`docs/api-design.md` section 11).

Inspection is only useful if it reports what is really in the model and changes
nothing. The first test compares the summary against direct COM reads and checks that
the user's selection, the In-Work Object, the model generation and the rebuild status
are exactly as they were. The second creates one temporary offset plane so a
geometrical set has known contents, then removes the whole set in a `finally`.

Nothing is saved.
"""

import sys
import uuid
import warnings
from typing import Any

import pytest

pytestmark = pytest.mark.integration

if sys.platform != "win32":
    pytest.skip("Windows COM is required.", allow_module_level=True)

pytest.importorskip("pywintypes", reason="pywin32 is required.")

from auto_3dx import Catia  # noqa: E402
from auto_3dx.errors import (  # noqa: E402
    Auto3dxError,
    CatiaConnectionError,
    NoActiveEditorError,
    NoActivePartError,
    SelectionNotRestoredWarning,
)
from auto_3dx.geometry.planes import GEOMETRICAL_SET_NAME  # noqa: E402
from auto_3dx.inspect import GeometricalSetInfo, GeometryInfo, TopologyCounts  # noqa: E402

PLANE_OFFSET = 30.0


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


def _selected(selection: Any) -> "list[tuple[str, str]]":
    """Reads the selection as (name, type) pairs, in order."""
    return [
        (str(selection.Item(i).Value.Name), type(selection.Item(i).Value).__name__)
        for i in range(1, int(selection.Count) + 1)
    ]


def test_summary_agrees_with_direct_reads_and_changes_nothing(part: Any) -> None:
    selection = Catia.attach().active_editor().Selection
    if int(selection.Count) != 0:
        pytest.skip("The user has something selected; this test only restores to empty.")
    raw = part.com_object
    shapes = raw.MainBody.Shapes
    if int(shapes.Count) == 0:
        pytest.skip("The main body has no feature to select.")
    in_work_before = str(raw.InWorkObject.Name)
    generation_before = part.part_design.snapshot_generation
    up_to_date_before = part.is_up_to_date()

    try:
        selection.Add(shapes.Item(1))
        selected_before = _selected(selection)
        with warnings.catch_warnings():
            warnings.simplefilter("error", SelectionNotRestoredWarning)
            summary = part.inspect.summary()

        assert _selected(selection) == selected_before
        assert part.part_design.snapshot_generation == generation_before
        assert str(raw.InWorkObject.Name) == in_work_before
        assert summary.up_to_date == up_to_date_before

        assert len(summary.bodies) == int(raw.Bodies.Count)
        main_bodies = [body for body in summary.bodies if body.is_main]
        assert len(main_bodies) == 1
        assert main_bodies[0].name == str(raw.MainBody.Name)
        assert main_bodies[0].features == summary.features
        assert main_bodies[0].sketches == summary.sketches

        assert len(summary.geometrical_sets) == int(raw.HybridBodies.Count)
        assert summary.topology == TopologyCounts(
            edges=len(part.topology.edges()), faces=len(part.topology.faces())
        )
    finally:
        selection.Clear()


def test_a_temporary_plane_appears_in_its_geometrical_set(part: Any) -> None:
    if any(item.name == GEOMETRICAL_SET_NAME for item in part.inspect.geometrical_sets()):
        pytest.skip(f"A {GEOMETRICAL_SET_NAME!r} set already exists; it is not ours to remove.")
    raw = part.com_object
    sets_before = int(raw.HybridBodies.Count)
    plane_name = f"AUTO3DX_IT_INSPECT_PLANE_{uuid.uuid4().hex[:8].upper()}"

    try:
        part.planes.create_offset(plane_name, "XY", PLANE_OFFSET)
        created = [
            item for item in part.inspect.geometrical_sets() if item.name == GEOMETRICAL_SET_NAME
        ]
        assert created == [
            GeometricalSetInfo(
                name=GEOMETRICAL_SET_NAME,
                elements=(GeometryInfo(name=plane_name, kind="HybridShapePlaneOffset"),),
                nested_set_count=0,
            )
        ]
    finally:
        try:
            part.planes.remove_geometrical_set()
        except Auto3dxError:
            pass
        part.update()

    # The In-Work Object is not compared here: creating a plane deliberately reclaims
    # the main body (`geometry.planes`). The first test pins that inspection leaves it.
    assert int(raw.HybridBodies.Count) == sets_before
