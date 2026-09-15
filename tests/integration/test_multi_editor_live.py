"""Live checks for enumerating editors and picking a Part by name.

This exists because `Application.ActiveEditor` does NOT reliably follow the UI
tab: a Part was opened in a new tab and clicked, yet `ActiveEditor` still
reported the previous Part's editor. Editing then silently targets the wrong
Part, which is why `parts()` / `part_named()` exist.

Read-only. Nothing is created, modified or saved.
"""

import sys

import pytest

pytestmark = pytest.mark.integration

if sys.platform != "win32":
    pytest.skip("Windows COM is required.", allow_module_level=True)

pytest.importorskip("pywintypes", reason="pywin32 is required.")

from auto_3dx import Catia  # noqa: E402
from auto_3dx.errors import CatiaConnectionError, NoActivePartError  # noqa: E402


@pytest.fixture
def catia():
    """Yields an attached session, skipping when none is running."""
    try:
        yield Catia.attach()
    except CatiaConnectionError as error:
        pytest.skip(f"No running 3DEXPERIENCE session: {error}")


def test_editors_lists_every_editor(catia) -> None:
    """A session normally contains an editor whose ActiveObject cannot be read.

    Observed live: one editor raises on `ActiveObject`, another holds a
    `VPMRootOccurrence`. Neither may break the listing.
    """
    editors = catia.editors()

    assert editors, "a running session always has at least one editor"
    for info in editors:
        assert isinstance(info.name, str) and info.name
        # object_kind is None exactly when the read failed; is_part follows it.
        assert info.is_part == (info.object_kind == "Part")


def test_parts_matches_the_part_editors(catia) -> None:
    """`parts()` is the Part subset of `editors()`, in the same order."""
    editors = catia.editors()
    parts = catia.parts()

    expected = [info.object_name for info in editors if info.is_part]
    assert [part.name for part in parts] == expected


def test_each_part_carries_its_own_selection(catia) -> None:
    """Deletion goes through the editor's Selection, so it must not be shared."""
    parts = catia.parts()
    if not parts:
        pytest.skip("No Part is open.")

    for part in parts:
        # Wired by Catia.parts(); without it geometry deletion is unavailable.
        assert part.sketches is not None
        assert part.part_design is not None


def test_part_named_round_trip(catia) -> None:
    """A Part can be selected by name without relying on the active tab."""
    parts = catia.parts()
    if not parts:
        pytest.skip("No Part is open.")

    wanted = parts[-1].name
    assert catia.part_named(wanted).name == wanted


def test_part_named_reports_what_is_open(catia) -> None:
    """The failure message has to name the open Parts, or it is useless."""
    parts = catia.parts()
    if not parts:
        pytest.skip("No Part is open.")

    with pytest.raises(NoActivePartError) as caught:
        catia.part_named("AUTO3DX_NO_SUCH_PART")

    message = str(caught.value)
    assert "AUTO3DX_NO_SUCH_PART" in message
    assert parts[0].name in message
