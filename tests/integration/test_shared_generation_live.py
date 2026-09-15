"""Live check that two wrappers of one Part share its model generation.

`Catia.active_part()` builds a new wrapper on every call. A snapshot taken through one
wrapper must be refused once another wrapper of the same Part has rebuilt the model,
which works only because the generation is keyed by COM identity (`docs/api-design.md`
section 5.1).

The only model call is `Part.Update()` on the current model. The stale fillet request is
refused before CATIA is called, and the test checks that nothing was created. Nothing is
saved.
"""

import sys
from typing import Any

import pytest

pytestmark = pytest.mark.integration

if sys.platform != "win32":
    pytest.skip("Windows COM is required.", allow_module_level=True)

pytest.importorskip("pywintypes", reason="pywin32 is required.")

from auto_3dx import Catia  # noqa: E402
from auto_3dx.errors import (  # noqa: E402
    AmbiguousNameError,
    CatiaConnectionError,
    NoActiveEditorError,
    NoActivePartError,
    StaleSnapshotError,
)

FILLET_RADIUS = 1.0
NEVER_CREATED = "AUTO3DX_IT_SHARED_GENERATION_NEVER_CREATED"


@pytest.fixture
def catia() -> Any:
    """Returns an attached session with an active Part, skipping otherwise."""
    try:
        session = Catia.attach()
        session.active_part()
    except CatiaConnectionError as error:
        pytest.skip(f"No running 3DEXPERIENCE session: {error}")
    except (NoActiveEditorError, NoActivePartError) as error:
        pytest.skip(f"No Part is being edited: {error}")
    return session


def test_a_rebuild_through_one_wrapper_makes_the_others_snapshot_stale(catia: Any) -> None:
    first = catia.active_part()
    try:
        second = Catia.attach().part_named(first.name)
    except AmbiguousNameError:
        pytest.skip("Two open Parts share the active Part's name.")
    assert first is not second
    if len(first.topology.edges()) == 0:
        pytest.skip("The active Part has no solid edges to snapshot.")
    shapes = first.com_object.MainBody.Shapes
    shapes_before = int(shapes.Count)

    snapshot = first.topology.edges()
    second.update()

    with pytest.raises(StaleSnapshotError):
        first.part_design.create_edge_fillet(NEVER_CREATED, snapshot[0], FILLET_RADIUS)
    assert int(shapes.Count) == shapes_before
    assert first.is_up_to_date()
    # A fresh snapshot from either wrapper is current for both.
    first.topology.edges()
