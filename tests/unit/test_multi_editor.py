"""Unit tests for multi-editor support on `Catia` (docs/conventions.md 6.8).

`Application.ActiveEditor` does not reliably follow the UI's active tab
(observed live: the user clicked a new Part's tab, but `ActiveEditor` still
reported the previous Part's editor). These tests pin `Catia.editors()`,
`Catia.parts()`, and `Catia.part_named()`, which let a caller pick the right
editor directly instead of trusting `ActiveEditor`.
"""

from collections.abc import Callable
from typing import Any

import pytest

from auto_3dx.core.application import Catia, EditorInfo
from auto_3dx.core.part import Part as PartWrapper
from auto_3dx.errors import AmbiguousNameError, Auto3dxError, NoActivePartError
from auto_3dx.geometry.sketch import SketchCollection

RAISING_EDITOR_NAME = "CATIAEditor4"
FIRST_PART_EDITOR_NAME = "CATIAEditor0"
ASSEMBLY_EDITOR_NAME = "CATIAEditor5"
SECOND_PART_EDITOR_NAME = "CATIAEditor6"

FIRST_PART_NAME = "3D Shape00422533"
SECOND_PART_NAME = "3D Shape00422534"

SKETCH_NAME = "AUTO3DX_SKETCH"


def _build_four_editor_session(
    application_factory: Callable[..., Any],
    editors_factory: Callable[..., Any],
    editor_factory: Callable[..., Any],
    part_factory: Callable[..., Any],
    vpm_root_occurrence_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
    raising_fake_factory: Callable[..., Any],
    com_error_factory: Callable[[], Any],
    first_part_name: str = FIRST_PART_NAME,
    second_part_name: str = SECOND_PART_NAME,
) -> dict[str, Any]:
    """Builds the verified 4-editor scenario from docs/conventions.md 6.8.

    Layout (1-based, matching the live observation):
        [1] CATIAEditor4 -- ActiveObject raises pywintypes.com_error
        [2] CATIAEditor0 -- ActiveObject is a Part
        [3] CATIAEditor5 -- ActiveObject is a VPMRootOccurrence
        [4] CATIAEditor6 -- ActiveObject is a second, distinct Part

    Returns:
        A dict with every raw fake needed by the tests: `application`,
        `raising_editor`, `first_part`, `first_selection`, `assembly_editor`,
        `second_part`, `second_selection`.
    """
    raising_editor = raising_fake_factory("Editor", ActiveObject=com_error_factory())
    raising_editor.Name = RAISING_EDITOR_NAME

    first_part = part_factory(name=first_part_name)
    first_selection = selection_factory()
    first_part_editor = editor_factory(
        active_object=first_part, name=FIRST_PART_EDITOR_NAME, selection=first_selection
    )

    assembly_editor = editor_factory(
        active_object=vpm_root_occurrence_factory(name="Product1"),
        name=ASSEMBLY_EDITOR_NAME,
    )

    second_part = part_factory(name=second_part_name)
    second_selection = selection_factory()
    second_part_editor = editor_factory(
        active_object=second_part, name=SECOND_PART_EDITOR_NAME, selection=second_selection
    )

    editors = editors_factory(
        items=[raising_editor, first_part_editor, assembly_editor, second_part_editor]
    )
    application = application_factory(editors=editors)

    return {
        "application": application,
        "raising_editor": raising_editor,
        "first_part": first_part,
        "first_selection": first_selection,
        "assembly_editor": assembly_editor,
        "second_part": second_part,
        "second_selection": second_selection,
    }


def test_editors_lists_every_editor_including_one_whose_active_object_raises(
    application_factory: Callable[..., Any],
    editors_factory: Callable[..., Any],
    editor_factory: Callable[..., Any],
    part_factory: Callable[..., Any],
    vpm_root_occurrence_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
    raising_fake_factory: Callable[..., Any],
    com_error_factory: Callable[[], Any],
) -> None:
    """A bad editor stays in the listing instead of aborting enumeration.

    This is the central "one bad editor must never break the whole listing"
    case: `Editors.Item(1).ActiveObject` raises `pywintypes.com_error`, but
    `editors()` still returns 4 entries, with that one carrying `None` fields.
    """
    scenario = _build_four_editor_session(
        application_factory,
        editors_factory,
        editor_factory,
        part_factory,
        vpm_root_occurrence_factory,
        selection_factory,
        raising_fake_factory,
        com_error_factory,
    )

    result = Catia(scenario["application"]).editors()

    assert len(result) == 4
    assert result[0] == EditorInfo(
        name=RAISING_EDITOR_NAME, object_kind=None, object_name=None, is_part=False
    )


def test_editors_reports_is_part_correctly_for_part_and_assembly(
    application_factory: Callable[..., Any],
    editors_factory: Callable[..., Any],
    editor_factory: Callable[..., Any],
    part_factory: Callable[..., Any],
    vpm_root_occurrence_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
    raising_fake_factory: Callable[..., Any],
    com_error_factory: Callable[[], Any],
) -> None:
    """`is_part` distinguishes a Part editor from a VPMRootOccurrence editor."""
    scenario = _build_four_editor_session(
        application_factory,
        editors_factory,
        editor_factory,
        part_factory,
        vpm_root_occurrence_factory,
        selection_factory,
        raising_fake_factory,
        com_error_factory,
    )

    result = Catia(scenario["application"]).editors()

    part_entry = result[1]
    assembly_entry = result[2]
    assert part_entry.object_kind == "Part"
    assert part_entry.object_name == FIRST_PART_NAME
    assert part_entry.is_part is True
    assert assembly_entry.object_kind == "VPMRootOccurrence"
    assert assembly_entry.is_part is False


def test_parts_returns_only_the_part_editors_in_order(
    application_factory: Callable[..., Any],
    editors_factory: Callable[..., Any],
    editor_factory: Callable[..., Any],
    part_factory: Callable[..., Any],
    vpm_root_occurrence_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
    raising_fake_factory: Callable[..., Any],
    com_error_factory: Callable[[], Any],
) -> None:
    """`parts()` skips the raising editor and the assembly editor entirely."""
    scenario = _build_four_editor_session(
        application_factory,
        editors_factory,
        editor_factory,
        part_factory,
        vpm_root_occurrence_factory,
        selection_factory,
        raising_fake_factory,
        com_error_factory,
    )

    result = Catia(scenario["application"]).parts()

    assert len(result) == 2
    assert all(isinstance(part, PartWrapper) for part in result)
    assert [part.com_object for part in result] == [scenario["first_part"], scenario["second_part"]]


def test_parts_each_part_carries_its_own_editors_selection(
    application_factory: Callable[..., Any],
    editors_factory: Callable[..., Any],
    editor_factory: Callable[..., Any],
    part_factory: Callable[..., Any],
    vpm_root_occurrence_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
    raising_fake_factory: Callable[..., Any],
    com_error_factory: Callable[[], Any],
) -> None:
    """Deleting through the second Part must only touch the SECOND selection.

    This is the safety property the whole feature exists for: mixing up
    editors' selections would delete geometry in the wrong window.
    """
    scenario = _build_four_editor_session(
        application_factory,
        editors_factory,
        editor_factory,
        part_factory,
        vpm_root_occurrence_factory,
        selection_factory,
        raising_fake_factory,
        com_error_factory,
    )
    # Create a sketch directly on the second Part's raw COM object, ahead of
    # collecting the wrappers, so there is something to delete afterwards.
    SketchCollection(scenario["second_part"]).create(SKETCH_NAME)

    parts = Catia(scenario["application"]).parts()
    first_part, second_part = parts

    second_part.sketches.remove(SKETCH_NAME)

    assert scenario["second_selection"].deleted, "the second editor's selection recorded the delete"
    assert not scenario["first_selection"].calls, "the first editor's selection must be untouched"


def test_part_named_returns_the_right_part_when_names_differ(
    application_factory: Callable[..., Any],
    editors_factory: Callable[..., Any],
    editor_factory: Callable[..., Any],
    part_factory: Callable[..., Any],
    vpm_root_occurrence_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
    raising_fake_factory: Callable[..., Any],
    com_error_factory: Callable[[], Any],
) -> None:
    """`part_named()` picks the Part whose `Name` matches, not just any Part."""
    scenario = _build_four_editor_session(
        application_factory,
        editors_factory,
        editor_factory,
        part_factory,
        vpm_root_occurrence_factory,
        selection_factory,
        raising_fake_factory,
        com_error_factory,
    )

    found = Catia(scenario["application"]).part_named(SECOND_PART_NAME)

    assert found.com_object is scenario["second_part"]


def test_part_named_missing_name_lists_the_parts_that_are_open(
    application_factory: Callable[..., Any],
    editors_factory: Callable[..., Any],
    editor_factory: Callable[..., Any],
    part_factory: Callable[..., Any],
    vpm_root_occurrence_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
    raising_fake_factory: Callable[..., Any],
    com_error_factory: Callable[[], Any],
) -> None:
    """A missing name's error message names the open Parts -- the whole point.

    It tells the user which tab to click instead of them.
    """
    scenario = _build_four_editor_session(
        application_factory,
        editors_factory,
        editor_factory,
        part_factory,
        vpm_root_occurrence_factory,
        selection_factory,
        raising_fake_factory,
        com_error_factory,
    )

    with pytest.raises(NoActivePartError) as exc_info:
        Catia(scenario["application"]).part_named("NoSuchPart")

    message = str(exc_info.value)
    assert FIRST_PART_NAME in message
    assert SECOND_PART_NAME in message


def test_part_named_two_same_named_parts_raises_ambiguous_name_error(
    application_factory: Callable[..., Any],
    editors_factory: Callable[..., Any],
    editor_factory: Callable[..., Any],
    part_factory: Callable[..., Any],
    vpm_root_occurrence_factory: Callable[..., Any],
    selection_factory: Callable[..., Any],
    raising_fake_factory: Callable[..., Any],
    com_error_factory: Callable[[], Any],
) -> None:
    """Two Parts sharing a name must never be silently resolved to one."""
    duplicate_name = "AUTO3DX_DUP_PART"
    scenario = _build_four_editor_session(
        application_factory,
        editors_factory,
        editor_factory,
        part_factory,
        vpm_root_occurrence_factory,
        selection_factory,
        raising_fake_factory,
        com_error_factory,
        first_part_name=duplicate_name,
        second_part_name=duplicate_name,
    )

    with pytest.raises(AmbiguousNameError):
        Catia(scenario["application"]).part_named(duplicate_name)


def test_editors_count_com_error_surfaces_as_auto3dx_error(
    application_factory: Callable[..., Any],
    editors_factory: Callable[..., Any],
    com_error_factory: Callable[[], Any],
) -> None:
    """A `com_error` reading `Editors.Count` itself is a real failure, not a per-entry one."""
    editors = editors_factory(count_exception=com_error_factory())
    application = application_factory(editors=editors)

    with pytest.raises(Auto3dxError):
        Catia(application).editors()

    with pytest.raises(Auto3dxError):
        Catia(application).parts()
