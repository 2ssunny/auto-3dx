"""Tests for the face-reference layer and the three face-based Part Design features.

Verified live (`docs/conventions.md` section 1.2.2.2; probe 37):

    selection.Clear()
    selection.Search("Topology.Face,all")       # returns void, mutates Selection
    for i in 1..selection.Count:
        reference = selection.Item(i).Reference  # a real, feature-usable Reference
    selection.Clear()

    AddNewShell(iFaceToRemove, iInternalThickness, iExternalThickness) -> Shell
        verified with (face, 2.0, 0.0)

    AddNewThickness(iFaceToThicken, iOffset) -> Thickness
        verified with (face, 3.0)

    AddNewHole(iSupport, iDepth) -> Hole
        verified with (face, 5.0)

The fakes below are entirely self-contained (no reliance on `tests.conftest`
for the `Selection.Search`/`SelectedElement.Reference` machinery, which the
shared fixtures do not model), mirroring `tests/unit/test_edge_features.py`:
`Selection` records the exact call order so tests can pin
`Clear -> Search -> Item -> Clear`, and `Part.Update`/`Save`/`PLMPropagate`
all raise immediately, so any accidental call from library code fails every
test in this module loudly rather than silently.

The raw fake feature classes are deliberately named `Shell`/`Thickness`/
`Hole` -- CATIA identifies a feature's kind purely by `type(obj).__name__`,
and those are the verified kind strings (`SHELL_KIND`/`THICKNESS_KIND`/
`HOLE_KIND`). The library's *wrapper* classes of the same name are imported
under an alias to avoid shadowing these fakes.
"""

from typing import Any

import pytest
import pywintypes

from auto_3dx.errors import (
    AmbiguousNameError,
    Auto3dxError,
    FeatureConflictError,
    FeatureNotFoundError,
    ParameterNameError,
    ParameterTypeError,
    PartialCreationError,
    StaleSnapshotError,
    UnsupportedUnitError,
)
from auto_3dx.geometry.faces import FACE_SEARCH_QUERY, Face, FaceSnapshot, take_face_snapshot
from auto_3dx.geometry.part_design import (
    HOLE_KIND,
    SHELL_KIND,
    THICKNESS_KIND,
    PartDesign,
)
from auto_3dx.geometry.part_design import Hole as HoleWrapper
from auto_3dx.geometry.part_design import Shell as ShellWrapper
from auto_3dx.geometry.part_design import Thickness as ThicknessWrapper

SHELL_NAME = "AUTO3DX_SHELL"
THICKNESS_NAME = "AUTO3DX_THICKNESS"
HOLE_NAME = "AUTO3DX_HOLE"
SHELL_INTERNAL_THICKNESS = 2.0
SHELL_EXTERNAL_THICKNESS = 0.0
THICKNESS_OFFSET = 3.0
HOLE_DEPTH = 5.0


# --- fakes -------------------------------------------------------------------


class _Reference:
    """Fake CATIA `Reference`. Only `Name`/`DisplayName` are documented to exist."""

    def __init__(self, name: str = "Selection_RFace:(Face:(Brp:(Pad.1;1)))") -> None:
        self.Name = name
        self.DisplayName = name


class _SelectedElement:
    """Fake `SelectedElement`. `.Reference` is the only route probe 37 found working."""

    def __init__(self, reference: _Reference) -> None:
        self.Reference = reference


class _Selection:
    """Fake `Editor.Selection` supporting `Search`, absent from `tests.conftest`.

    Records every call in `calls` (as bare method names, so a test can assert
    the exact `["Clear", "Search", "Item", "Item", "Clear"]`-shaped sequence)
    and every query string passed to `Search` in `queries`.
    """

    def __init__(self, face_references: "list[_Reference] | None" = None) -> None:
        self.calls: list[str] = []
        self.queries: list[str] = []
        self._pool = [_SelectedElement(ref) for ref in (face_references or [])]
        self._current: list[_SelectedElement] = []
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.search_exception: BaseException | None = None

    def Clear(self) -> None:
        self.calls.append("Clear")
        self._current = []
        self.added = []

    def Search(self, query: str) -> None:
        self.calls.append("Search")
        self.queries.append(query)
        if self.search_exception is not None:
            raise self.search_exception
        self._current = list(self._pool)

    @property
    def Count(self) -> int:
        return len(self._current)

    def Item(self, index: int) -> _SelectedElement:
        self.calls.append("Item")
        return self._current[index - 1]

    def Add(self, com_object: Any) -> None:
        self.calls.append("Add")
        self.added.append(com_object)

    def Delete(self) -> None:
        self.calls.append("Delete")
        self.deleted.extend(self.added)


class Shell:
    """Fake CATIA `Shell`. `type(obj).__name__ == "Shell"`."""

    def __init__(self, name: str, name_write_exception: "BaseException | None" = None) -> None:
        self._name = name
        self._name_write_exception = name_write_exception

    @property
    def Name(self) -> str:
        return self._name

    @Name.setter
    def Name(self, value: str) -> None:
        if self._name_write_exception is not None:
            raise self._name_write_exception
        self._name = value


class Thickness:
    """Fake CATIA `Thickness`. `type(obj).__name__ == "Thickness"`."""

    def __init__(self, name: str, name_write_exception: "BaseException | None" = None) -> None:
        self._name = name
        self._name_write_exception = name_write_exception

    @property
    def Name(self) -> str:
        return self._name

    @Name.setter
    def Name(self, value: str) -> None:
        if self._name_write_exception is not None:
            raise self._name_write_exception
        self._name = value


class Hole:
    """Fake CATIA `Hole`. `type(obj).__name__ == "Hole"`."""

    def __init__(self, name: str, name_write_exception: "BaseException | None" = None) -> None:
        self._name = name
        self._name_write_exception = name_write_exception

    @property
    def Name(self) -> str:
        return self._name

    @Name.setter
    def Name(self, value: str) -> None:
        if self._name_write_exception is not None:
            raise self._name_write_exception
        self._name = value


class Pad:
    """Fake CATIA `Pad`, used only to prove a shell/thickness/hole lookup ignores it."""

    def __init__(self, name: str) -> None:
        self.Name = name


class _Shapes:
    """Fake `Shapes` collection: 1-based `Item(int)`, `Count`. No `Remove` (matches CATIA)."""

    def __init__(self) -> None:
        self._items: list[Any] = []

    @property
    def Count(self) -> int:
        return len(self._items)

    def Item(self, index: int) -> Any:
        return self._items[index - 1]

    def _append(self, com_object: Any) -> None:
        self._items.append(com_object)


class _ShapeFactory:
    """Fake `ShapeFactory` recording the exact shell/thickness/hole call arguments."""

    def __init__(
        self,
        shapes: _Shapes,
        shell_name_write_exception: "BaseException | None" = None,
        thickness_name_write_exception: "BaseException | None" = None,
        hole_name_write_exception: "BaseException | None" = None,
    ) -> None:
        self.shapes = shapes
        self.shell_calls: "list[tuple[Any, ...]]" = []
        self.thickness_calls: "list[tuple[Any, ...]]" = []
        self.hole_calls: "list[tuple[Any, ...]]" = []
        self._shell_count = 0
        self._thickness_count = 0
        self._hole_count = 0
        self.shell_name_write_exception = shell_name_write_exception
        self.thickness_name_write_exception = thickness_name_write_exception
        self.hole_name_write_exception = hole_name_write_exception

    def AddNewShell(
        self, iFaceToRemove: Any, iInternalThickness: float, iExternalThickness: float
    ) -> Shell:
        self.shell_calls.append((iFaceToRemove, iInternalThickness, iExternalThickness))
        self._shell_count += 1
        shell = Shell(
            f"Shell.{self._shell_count}",
            name_write_exception=self.shell_name_write_exception,
        )
        self.shapes._append(shell)
        return shell

    def AddNewThickness(self, iFaceToThicken: Any, iOffset: float) -> Thickness:
        self.thickness_calls.append((iFaceToThicken, iOffset))
        self._thickness_count += 1
        thickness = Thickness(
            f"Thickness.{self._thickness_count}",
            name_write_exception=self.thickness_name_write_exception,
        )
        self.shapes._append(thickness)
        return thickness

    def AddNewHole(self, iSupport: Any, iDepth: float) -> Hole:
        self.hole_calls.append((iSupport, iDepth))
        self._hole_count += 1
        hole = Hole(
            f"Hole.{self._hole_count}",
            name_write_exception=self.hole_name_write_exception,
        )
        self.shapes._append(hole)
        return hole


class _MainBody:
    """Fake `Part.MainBody`, exposing only `Shapes`."""

    def __init__(self, shapes: _Shapes) -> None:
        self.Shapes = shapes


class _Part:
    """Fake CATIA `Part`.

    `Update`/`Save`/`PLMPropagate` all raise `AssertionError` unconditionally:
    no code path exercised by this module may call any of them.
    """

    def __init__(
        self,
        shell_name_write_exception: "BaseException | None" = None,
        thickness_name_write_exception: "BaseException | None" = None,
        hole_name_write_exception: "BaseException | None" = None,
    ) -> None:
        self._shapes = _Shapes()
        self.MainBody = _MainBody(self._shapes)
        self.ShapeFactory = _ShapeFactory(
            self._shapes,
            shell_name_write_exception=shell_name_write_exception,
            thickness_name_write_exception=thickness_name_write_exception,
            hole_name_write_exception=hole_name_write_exception,
        )

    def Update(self) -> None:
        raise AssertionError("Part.Update must never be called by this code path.")

    def Save(self) -> None:
        raise AssertionError("Part.Save must never be called.")

    def PLMPropagate(self) -> None:
        raise AssertionError("Part.PLMPropagate must never be called.")


def _face(descriptor: str = "FACE_REF_1") -> Face:
    """Builds a standalone `Face` handle, without going through a snapshot."""
    return Face(_Reference(descriptor), 1)


def _current_face(design: PartDesign, descriptor: str = "FACE_REF_1") -> Face:
    """Builds a `Face` stamped with `design`'s current model generation.

    A real caller gets one from `snapshot_faces()`. A test that only wants a
    usable face, and is not about staleness, would otherwise have to build a
    `_Selection` just to get past the staleness check.
    """
    return Face(_Reference(descriptor), 1, design.snapshot_generation)


# --- Face / FaceSnapshot -------------------------------------------------------


def test_face_exposes_reference_and_index() -> None:
    """`Face.com_object` is the raw reference; `index` is the search position."""
    reference = _Reference("some-brep-name")
    face = Face(reference, 7)

    assert face.com_object is reference
    assert face.index == 7


def test_face_descriptor_reads_reference_name() -> None:
    """`descriptor` is the reference's `Name`, exposed only for logging/comparison."""
    face = Face(_Reference("Selection_RFace:(...)"), 1)

    assert face.descriptor == "Selection_RFace:(...)"


def test_face_descriptor_wraps_com_error() -> None:
    """A COM failure reading `Name` must surface as `Auto3dxError`, not raw."""

    class _RaisingReference:
        @property
        def Name(self) -> str:
            raise pywintypes.com_error(
                -2147352567, "Exception occurred.", (0, "CATIA", "failed", None, 0, -1), None
            )

    face = Face(_RaisingReference(), 1)

    with pytest.raises(Auto3dxError):
        _ = face.descriptor


def test_face_repr_does_not_read_descriptor() -> None:
    """`repr` must not touch the (possibly huge, possibly raising) BRep name."""

    class _RaisingReference:
        @property
        def Name(self) -> str:
            raise AssertionError("repr must not read Name")

    face = Face(_RaisingReference(), 3)

    assert repr(face) == "Face(index=3)"


def test_face_snapshot_supports_len_iter_getitem() -> None:
    """`FaceSnapshot` behaves like a small read-only sequence of `Face`."""
    faces = [_face("a"), _face("b"), _face("c")]

    snapshot = FaceSnapshot(faces)

    assert len(snapshot) == 3
    assert list(snapshot) == faces
    assert snapshot[0] is faces[0]
    assert snapshot[2] is faces[2]


def test_take_face_snapshot_uses_exact_query_and_call_order() -> None:
    """Pins `Clear -> Search("Topology.Face,all") -> Item(i) -> Clear`."""
    selection = _Selection([_Reference("f1"), _Reference("f2")])

    snapshot = take_face_snapshot(selection)

    assert selection.queries == [FACE_SEARCH_QUERY]
    assert selection.calls == ["Clear", "Search", "Item", "Item", "Clear"]
    assert len(snapshot) == 2


def test_take_face_snapshot_reads_selected_element_reference_not_create_reference() -> None:
    """The face's `com_object` must be exactly `SelectedElement.Reference`.

    `Part.CreateReferenceFromObject` fails on a search hit (probe 37), so
    nothing here may go through it -- and nothing in this fake even defines
    it, so a wrongly-implemented `take_face_snapshot` would raise
    `AttributeError` rather than silently succeeding.
    """
    reference = _Reference("only-route-that-works")
    selection = _Selection([reference])

    snapshot = take_face_snapshot(selection)

    assert snapshot[0].com_object is reference


def test_take_face_snapshot_indexes_faces_one_based_in_search_order() -> None:
    """`Face.index` reflects the one-based `Selection.Item` position."""
    selection = _Selection([_Reference("f1"), _Reference("f2"), _Reference("f3")])

    snapshot = take_face_snapshot(selection)

    assert [face.index for face in snapshot] == [1, 2, 3]


def test_take_face_snapshot_requires_a_selection() -> None:
    """No selection means no way to delete/search -- refuse rather than crash."""
    with pytest.raises(Auto3dxError):
        take_face_snapshot(None)


def test_take_face_snapshot_wraps_search_com_error() -> None:
    """A COM failure during `Search` must surface as `Auto3dxError`."""
    selection = _Selection([])
    selection.search_exception = pywintypes.com_error(
        -2147352567, "Exception occurred.", (0, "CATIA", "failed", None, 0, -1), None
    )

    with pytest.raises(Auto3dxError):
        take_face_snapshot(selection)


def test_part_design_snapshot_faces_delegates_to_take_face_snapshot() -> None:
    """`PartDesign.snapshot_faces` is a thin, selection-wired forward."""
    selection = _Selection([_Reference("f1")])
    design = PartDesign(_Part(), selection=selection)

    with pytest.warns(DeprecationWarning, match="part.topology"):
        snapshot = design.snapshot_faces()

    assert selection.queries == [FACE_SEARCH_QUERY]
    assert len(snapshot) == 1


def test_part_design_snapshot_faces_without_selection_raises() -> None:
    """No editor selection wired in means faces cannot be searched at all."""
    design = PartDesign(_Part(), selection=None)

    with pytest.warns(DeprecationWarning), pytest.raises(Auto3dxError):
        design.snapshot_faces()


# --- create_shell: happy path and exact COM call -------------------------------


def test_create_shell_passes_verified_argument_tuple() -> None:
    """Pins `(reference, internal_thickness, external_thickness)`, in that order."""
    part = _Part()
    design = PartDesign(part)
    face = _face()

    shell = design.create_shell(
        SHELL_NAME, face, SHELL_INTERNAL_THICKNESS, SHELL_EXTERNAL_THICKNESS
    )

    assert part.ShapeFactory.shell_calls == [
        (face.com_object, SHELL_INTERNAL_THICKNESS, SHELL_EXTERNAL_THICKNESS)
    ]
    assert isinstance(shell, ShellWrapper)
    assert shell.name == SHELL_NAME


def test_create_shell_coerces_int_thicknesses_to_float() -> None:
    """`int` thicknesses must reach COM as `float`, matching the fillet/chamfer contract."""
    part = _Part()
    design = PartDesign(part)

    design.create_shell(SHELL_NAME, _face(), 2, 0)

    (_, internal, external) = part.ShapeFactory.shell_calls[0]
    assert internal == 2.0 and isinstance(internal, float)
    assert external == 0.0 and isinstance(external, float)


def test_create_shell_never_calls_update_save_or_plm_propagate() -> None:
    """The fake's `Update`/`Save`/`PLMPropagate` raise; reaching them fails the test."""
    design = PartDesign(_Part())

    design.create_shell(SHELL_NAME, _face(), SHELL_INTERNAL_THICKNESS, SHELL_EXTERNAL_THICKNESS)
    # No assertion needed beyond "did not raise" -- the fake's Update/Save/
    # PLMPropagate would have raised AssertionError if called.


# --- create_shell: validation before COM ---------------------------------------


@pytest.mark.parametrize("bad_name", ["", "Has\\Backslash"])
def test_create_shell_rejects_bad_name_before_com(bad_name: str) -> None:
    """An unusable name must be refused before `ShapeFactory` is ever touched."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterNameError):
        design.create_shell(
            bad_name, _face(), SHELL_INTERNAL_THICKNESS, SHELL_EXTERNAL_THICKNESS
        )

    assert part.ShapeFactory.shell_calls == []


def test_create_shell_rejects_non_face_before_com() -> None:
    """A raw reference (not wrapped in `Face`) must never reach COM directly."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterTypeError):
        design.create_shell(
            SHELL_NAME,
            _Reference("not-a-face"),
            SHELL_INTERNAL_THICKNESS,
            SHELL_EXTERNAL_THICKNESS,
        )

    assert part.ShapeFactory.shell_calls == []


@pytest.mark.parametrize("bad_internal", [0.0, -1.0, float("nan"), float("inf")])
def test_create_shell_rejects_non_positive_or_non_finite_internal_thickness(
    bad_internal: float,
) -> None:
    """`internal_thickness` must be finite and strictly positive before COM is touched."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterTypeError):
        design.create_shell(SHELL_NAME, _face(), bad_internal, SHELL_EXTERNAL_THICKNESS)

    assert part.ShapeFactory.shell_calls == []


@pytest.mark.parametrize("bad_external", [-1.0, float("nan"), float("inf")])
def test_create_shell_rejects_negative_or_non_finite_external_thickness(
    bad_external: float,
) -> None:
    """`external_thickness` must be finite and non-negative -- zero is the verified value."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterTypeError):
        design.create_shell(SHELL_NAME, _face(), SHELL_INTERNAL_THICKNESS, bad_external)

    assert part.ShapeFactory.shell_calls == []


def test_create_shell_accepts_zero_external_thickness() -> None:
    """Zero is the verified `external_thickness` value and must not be rejected."""
    part = _Part()
    design = PartDesign(part)
    face = _face()

    design.create_shell(SHELL_NAME, face, SHELL_INTERNAL_THICKNESS, 0.0)

    assert part.ShapeFactory.shell_calls == [(face.com_object, SHELL_INTERNAL_THICKNESS, 0.0)]


def test_create_shell_rejects_bool_thicknesses() -> None:
    """`bool` is a subclass of `int`; it must still be refused for both thicknesses."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterTypeError):
        design.create_shell(SHELL_NAME, _face(), True, SHELL_EXTERNAL_THICKNESS)
    with pytest.raises(ParameterTypeError):
        design.create_shell(SHELL_NAME, _face(), SHELL_INTERNAL_THICKNESS, True)

    assert part.ShapeFactory.shell_calls == []


def test_create_shell_rejects_unsupported_unit() -> None:
    """An unsupported unit must be refused before COM is touched."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(UnsupportedUnitError):
        design.create_shell(
            SHELL_NAME,
            _face(),
            SHELL_INTERNAL_THICKNESS,
            SHELL_EXTERNAL_THICKNESS,
            unit="furlong",
        )

    assert part.ShapeFactory.shell_calls == []


def test_create_shell_conflicts_with_existing_name() -> None:
    """Two shells cannot share a name."""
    design = PartDesign(_Part())
    design.create_shell(
        SHELL_NAME, _face("f1"), SHELL_INTERNAL_THICKNESS, SHELL_EXTERNAL_THICKNESS
    )

    with pytest.raises(FeatureConflictError):
        design.create_shell(
            SHELL_NAME,
            _current_face(design, "f2"),
            SHELL_INTERNAL_THICKNESS,
            SHELL_EXTERNAL_THICKNESS,
        )


def test_create_shell_partial_creation_when_rename_fails(com_error_factory: Any) -> None:
    """A failed rename must be reported, and the feature stays in the model."""
    part = _Part(shell_name_write_exception=com_error_factory())
    design = PartDesign(part)

    with pytest.raises(PartialCreationError):
        design.create_shell(
            SHELL_NAME, _face(), SHELL_INTERNAL_THICKNESS, SHELL_EXTERNAL_THICKNESS
        )

    assert part.MainBody.Shapes.Count == 1


# --- create_thickness: happy path and exact COM call ---------------------------


def test_create_thickness_passes_verified_argument_tuple() -> None:
    """Pins `(reference, offset)`, in that order."""
    part = _Part()
    design = PartDesign(part)
    face = _face()

    thickness = design.create_thickness(THICKNESS_NAME, face, THICKNESS_OFFSET)

    assert part.ShapeFactory.thickness_calls == [(face.com_object, THICKNESS_OFFSET)]
    assert isinstance(thickness, ThicknessWrapper)
    assert thickness.name == THICKNESS_NAME


def test_create_thickness_coerces_int_offset_to_float() -> None:
    """An `int` offset must reach COM as a `float`."""
    part = _Part()
    design = PartDesign(part)

    design.create_thickness(THICKNESS_NAME, _face(), 3)

    (_, offset) = part.ShapeFactory.thickness_calls[0]
    assert offset == 3.0
    assert isinstance(offset, float)


def test_create_thickness_never_calls_update_save_or_plm_propagate() -> None:
    """The fake's `Update`/`Save`/`PLMPropagate` raise; reaching them fails the test."""
    design = PartDesign(_Part())

    design.create_thickness(THICKNESS_NAME, _face(), THICKNESS_OFFSET)


# --- create_thickness: validation before COM ------------------------------------


@pytest.mark.parametrize("bad_name", ["", "Has\\Backslash"])
def test_create_thickness_rejects_bad_name_before_com(bad_name: str) -> None:
    """An unusable name must be refused before `ShapeFactory` is ever touched."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterNameError):
        design.create_thickness(bad_name, _face(), THICKNESS_OFFSET)

    assert part.ShapeFactory.thickness_calls == []


def test_create_thickness_rejects_non_face_before_com() -> None:
    """A raw reference (not wrapped in `Face`) must never reach COM directly."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterTypeError):
        design.create_thickness(THICKNESS_NAME, _Reference("not-a-face"), THICKNESS_OFFSET)

    assert part.ShapeFactory.thickness_calls == []


@pytest.mark.parametrize("bad_offset", [0.0, -1.0, float("nan"), float("inf")])
def test_create_thickness_rejects_non_positive_or_non_finite_offset(bad_offset: float) -> None:
    """`offset` must be finite and strictly positive before COM is touched."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterTypeError):
        design.create_thickness(THICKNESS_NAME, _face(), bad_offset)

    assert part.ShapeFactory.thickness_calls == []


def test_create_thickness_rejects_bool_offset() -> None:
    """`bool` is a subclass of `int`; it must still be refused."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterTypeError):
        design.create_thickness(THICKNESS_NAME, _face(), True)

    assert part.ShapeFactory.thickness_calls == []


def test_create_thickness_rejects_unsupported_unit() -> None:
    """An unsupported unit must be refused before COM is touched."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(UnsupportedUnitError):
        design.create_thickness(THICKNESS_NAME, _face(), THICKNESS_OFFSET, unit="furlong")

    assert part.ShapeFactory.thickness_calls == []


def test_create_thickness_conflicts_with_existing_name() -> None:
    """Two thickness features cannot share a name."""
    design = PartDesign(_Part())
    design.create_thickness(THICKNESS_NAME, _face("f1"), THICKNESS_OFFSET)

    with pytest.raises(FeatureConflictError):
        design.create_thickness(THICKNESS_NAME, _current_face(design, "f2"), THICKNESS_OFFSET)


def test_create_thickness_partial_creation_when_rename_fails(com_error_factory: Any) -> None:
    """A failed rename must be reported, and the feature stays in the model."""
    part = _Part(thickness_name_write_exception=com_error_factory())
    design = PartDesign(part)

    with pytest.raises(PartialCreationError):
        design.create_thickness(THICKNESS_NAME, _face(), THICKNESS_OFFSET)

    assert part.MainBody.Shapes.Count == 1


# --- create_hole: happy path and exact COM call --------------------------------


def test_create_hole_passes_verified_argument_tuple() -> None:
    """Pins `(reference, depth)`, in that order."""
    part = _Part()
    design = PartDesign(part)
    face = _face()

    hole = design.create_hole(HOLE_NAME, face, HOLE_DEPTH)

    assert part.ShapeFactory.hole_calls == [(face.com_object, HOLE_DEPTH)]
    assert isinstance(hole, HoleWrapper)
    assert hole.name == HOLE_NAME


def test_create_hole_coerces_int_depth_to_float() -> None:
    """An `int` depth must reach COM as a `float`."""
    part = _Part()
    design = PartDesign(part)

    design.create_hole(HOLE_NAME, _face(), 5)

    (_, depth) = part.ShapeFactory.hole_calls[0]
    assert depth == 5.0
    assert isinstance(depth, float)


def test_create_hole_never_calls_update_save_or_plm_propagate() -> None:
    """The fake's `Update`/`Save`/`PLMPropagate` raise; reaching them fails the test."""
    design = PartDesign(_Part())

    design.create_hole(HOLE_NAME, _face(), HOLE_DEPTH)


# --- create_hole: validation before COM -----------------------------------------


@pytest.mark.parametrize("bad_name", ["", "Has\\Backslash"])
def test_create_hole_rejects_bad_name_before_com(bad_name: str) -> None:
    """An unusable name must be refused before `ShapeFactory` is ever touched."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterNameError):
        design.create_hole(bad_name, _face(), HOLE_DEPTH)

    assert part.ShapeFactory.hole_calls == []


def test_create_hole_rejects_non_face_before_com() -> None:
    """A raw reference (not wrapped in `Face`) must never reach COM directly."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterTypeError):
        design.create_hole(HOLE_NAME, _Reference("not-a-face"), HOLE_DEPTH)

    assert part.ShapeFactory.hole_calls == []


@pytest.mark.parametrize("bad_depth", [0.0, -1.0, float("nan"), float("inf")])
def test_create_hole_rejects_non_positive_or_non_finite_depth(bad_depth: float) -> None:
    """`depth` must be finite and strictly positive before COM is touched."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterTypeError):
        design.create_hole(HOLE_NAME, _face(), bad_depth)

    assert part.ShapeFactory.hole_calls == []


def test_create_hole_rejects_bool_depth() -> None:
    """`bool` is a subclass of `int`; it must still be refused."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterTypeError):
        design.create_hole(HOLE_NAME, _face(), True)

    assert part.ShapeFactory.hole_calls == []


def test_create_hole_rejects_unsupported_unit() -> None:
    """An unsupported unit must be refused before COM is touched."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(UnsupportedUnitError):
        design.create_hole(HOLE_NAME, _face(), HOLE_DEPTH, unit="furlong")

    assert part.ShapeFactory.hole_calls == []


def test_create_hole_conflicts_with_existing_name() -> None:
    """Two holes cannot share a name."""
    design = PartDesign(_Part())
    design.create_hole(HOLE_NAME, _face("f1"), HOLE_DEPTH)

    with pytest.raises(FeatureConflictError):
        design.create_hole(HOLE_NAME, _current_face(design, "f2"), HOLE_DEPTH)


def test_create_hole_partial_creation_when_rename_fails(com_error_factory: Any) -> None:
    """A failed rename must be reported, and the feature stays in the model."""
    part = _Part(hole_name_write_exception=com_error_factory())
    design = PartDesign(part)

    with pytest.raises(PartialCreationError):
        design.create_hole(HOLE_NAME, _face(), HOLE_DEPTH)

    assert part.MainBody.Shapes.Count == 1


# --- listing / get_* / remove_* : kinds do not leak into each other -----------


def test_shells_thicknesses_holes_and_pads_stay_separate() -> None:
    """A pad, a shell, a thickness, and a hole sharing `Shapes` must not cross-list."""
    part = _Part()
    design = PartDesign(part)
    part.MainBody.Shapes._append(Pad("SharedName"))
    design.create_shell(
        SHELL_NAME,
        _current_face(design, "f1"),
        SHELL_INTERNAL_THICKNESS,
        SHELL_EXTERNAL_THICKNESS,
    )
    design.create_thickness(THICKNESS_NAME, _current_face(design, "f2"), THICKNESS_OFFSET)
    design.create_hole(HOLE_NAME, _current_face(design, "f3"), HOLE_DEPTH)

    assert [f.name for f in design.shells] == [SHELL_NAME]
    assert [f.name for f in design.thicknesses] == [THICKNESS_NAME]
    assert [f.name for f in design.holes] == [HOLE_NAME]


def test_get_shell_does_not_return_a_pad() -> None:
    """A pad holding the requested name must not satisfy a shell lookup."""
    part = _Part()
    design = PartDesign(part)
    part.MainBody.Shapes._append(Pad(SHELL_NAME))

    with pytest.raises(FeatureNotFoundError):
        design.get_shell(SHELL_NAME)


def test_get_thickness_does_not_return_a_pad() -> None:
    """A pad holding the requested name must not satisfy a thickness lookup."""
    part = _Part()
    design = PartDesign(part)
    part.MainBody.Shapes._append(Pad(THICKNESS_NAME))

    with pytest.raises(FeatureNotFoundError):
        design.get_thickness(THICKNESS_NAME)


def test_get_hole_does_not_return_a_pad() -> None:
    """A pad holding the requested name must not satisfy a hole lookup."""
    part = _Part()
    design = PartDesign(part)
    part.MainBody.Shapes._append(Pad(HOLE_NAME))

    with pytest.raises(FeatureNotFoundError):
        design.get_hole(HOLE_NAME)


def test_get_shell_does_not_return_a_thickness_or_hole() -> None:
    """A thickness or hole holding the requested name must not satisfy a shell lookup."""
    design = PartDesign(_Part())
    design.create_thickness(SHELL_NAME, _face("f1"), THICKNESS_OFFSET)
    design.create_hole(SHELL_NAME, _current_face(design, "f2"), HOLE_DEPTH)

    # Neither a Thickness nor a Hole is a Shell -- no match at all, not an
    # ambiguous one.
    with pytest.raises(FeatureNotFoundError):
        design.get_shell(SHELL_NAME)


def test_get_thickness_does_not_return_a_shell_or_hole() -> None:
    """A shell or hole holding the requested name must not satisfy a thickness lookup."""
    design = PartDesign(_Part())
    design.create_shell(
        THICKNESS_NAME, _face("f1"), SHELL_INTERNAL_THICKNESS, SHELL_EXTERNAL_THICKNESS
    )

    with pytest.raises(FeatureNotFoundError):
        design.get_thickness(THICKNESS_NAME)


def test_get_hole_does_not_return_a_shell_or_thickness() -> None:
    """A shell or thickness holding the requested name must not satisfy a hole lookup."""
    design = PartDesign(_Part())
    design.create_shell(
        HOLE_NAME, _face("f1"), SHELL_INTERNAL_THICKNESS, SHELL_EXTERNAL_THICKNESS
    )

    with pytest.raises(FeatureNotFoundError):
        design.get_hole(HOLE_NAME)


def test_get_shell_raises_when_missing() -> None:
    """A name-based lookup with nothing at all must raise, not return `None`."""
    design = PartDesign(_Part())

    with pytest.raises(FeatureNotFoundError):
        design.get_shell("MISSING")


def test_get_shell_raises_when_ambiguous() -> None:
    """Two same-named shells is unsafe to resolve automatically."""
    part = _Part()
    part.MainBody.Shapes._append(Shell(SHELL_NAME))
    part.MainBody.Shapes._append(Shell(SHELL_NAME))
    design = PartDesign(part)

    with pytest.raises(AmbiguousNameError):
        design.get_shell(SHELL_NAME)


def test_get_thickness_raises_when_ambiguous() -> None:
    """Two same-named thickness features is unsafe to resolve automatically."""
    part = _Part()
    part.MainBody.Shapes._append(Thickness(THICKNESS_NAME))
    part.MainBody.Shapes._append(Thickness(THICKNESS_NAME))
    design = PartDesign(part)

    with pytest.raises(AmbiguousNameError):
        design.get_thickness(THICKNESS_NAME)


def test_get_hole_raises_when_ambiguous() -> None:
    """Two same-named holes is unsafe to resolve automatically."""
    part = _Part()
    part.MainBody.Shapes._append(Hole(HOLE_NAME))
    part.MainBody.Shapes._append(Hole(HOLE_NAME))
    design = PartDesign(part)

    with pytest.raises(AmbiguousNameError):
        design.get_hole(HOLE_NAME)


def test_kind_constants_match_the_verified_com_type_names() -> None:
    """`SHELL_KIND`/`THICKNESS_KIND`/`HOLE_KIND` must be the exact `type(obj).__name__` values."""
    assert SHELL_KIND == "Shell"
    assert THICKNESS_KIND == "Thickness"
    assert HOLE_KIND == "Hole"


# --- remove_* ------------------------------------------------------------------


def test_remove_shell_uses_the_selection_delete_sequence() -> None:
    """Deletion goes through `Clear -> Add -> Delete`, the only verified route."""
    part = _Part()
    selection = _Selection()
    design = PartDesign(part, selection=selection)
    shell = design.create_shell(
        SHELL_NAME, _face(), SHELL_INTERNAL_THICKNESS, SHELL_EXTERNAL_THICKNESS
    )

    design.remove_shell(SHELL_NAME)

    assert selection.deleted == [shell.com_object]


def test_remove_thickness_uses_the_selection_delete_sequence() -> None:
    """Deletion goes through `Clear -> Add -> Delete`, the only verified route."""
    part = _Part()
    selection = _Selection()
    design = PartDesign(part, selection=selection)
    thickness = design.create_thickness(THICKNESS_NAME, _face(), THICKNESS_OFFSET)

    design.remove_thickness(THICKNESS_NAME)

    assert selection.deleted == [thickness.com_object]


def test_remove_hole_uses_the_selection_delete_sequence() -> None:
    """Deletion goes through `Clear -> Add -> Delete`, the only verified route."""
    part = _Part()
    selection = _Selection()
    design = PartDesign(part, selection=selection)
    hole = design.create_hole(HOLE_NAME, _face(), HOLE_DEPTH)

    design.remove_hole(HOLE_NAME)

    assert selection.deleted == [hole.com_object]


def test_remove_shell_without_selection_raises() -> None:
    """No editor selection wired in means deletion is unavailable."""
    design = PartDesign(_Part(), selection=None)
    design.create_shell(
        SHELL_NAME, _face(), SHELL_INTERNAL_THICKNESS, SHELL_EXTERNAL_THICKNESS
    )

    with pytest.raises(Auto3dxError):
        design.remove_shell(SHELL_NAME)


def test_remove_shell_raises_when_missing() -> None:
    """Removing a name that does not exist must not silently succeed."""
    design = PartDesign(_Part(), selection=_Selection())

    with pytest.raises(FeatureNotFoundError):
        design.remove_shell("MISSING")


def test_remove_thickness_raises_when_missing() -> None:
    """Removing a name that does not exist must not silently succeed."""
    design = PartDesign(_Part(), selection=_Selection())

    with pytest.raises(FeatureNotFoundError):
        design.remove_thickness("MISSING")


def test_remove_hole_raises_when_missing() -> None:
    """Removing a name that does not exist must not silently succeed."""
    design = PartDesign(_Part(), selection=_Selection())

    with pytest.raises(FeatureNotFoundError):
        design.remove_hole("MISSING")


# --- no ensure_* is offered ------------------------------------------------------


def test_there_is_no_ensure_shell_thickness_or_hole() -> None:
    """A truthful `ensure_*` is not possible here (see `geometry.faces`); none exists."""
    design = PartDesign(_Part())

    assert not hasattr(design, "ensure_shell")
    assert not hasattr(design, "ensure_thickness")
    assert not hasattr(design, "ensure_hole")


# --- staleness guard ----------------------------------------------------------


def test_a_face_from_before_a_model_change_is_refused() -> None:
    """The same staleness guard `geometry.edges` enforces for edges, for faces.

    Applied here as project law even though the specific reuse-failure
    experiment behind `StaleSnapshotError`'s docstring was run on edges,
    not faces (`geometry.faces` module docstring): the same kind of
    `Reference`, obtained the same way, must not be handed to COM after this
    `PartDesign` has changed the model since the snapshot was taken.
    """
    part = _Part()
    design = PartDesign(part)
    face = _face("f1")
    design.create_shell(
        SHELL_NAME, face, SHELL_INTERNAL_THICKNESS, SHELL_EXTERNAL_THICKNESS
    )

    with pytest.raises(StaleSnapshotError):
        design.create_shell(
            "OTHER_SHELL", face, SHELL_INTERNAL_THICKNESS, SHELL_EXTERNAL_THICKNESS
        )
    with pytest.raises(StaleSnapshotError):
        design.create_thickness("OTHER_THICKNESS", face, THICKNESS_OFFSET)
    with pytest.raises(StaleSnapshotError):
        design.create_hole("OTHER_HOLE", face, HOLE_DEPTH)
    # Refused before COM, so only the first feature was ever created.
    assert len(part.ShapeFactory.shell_calls) == 1
    assert part.ShapeFactory.thickness_calls == []
    assert part.ShapeFactory.hole_calls == []


def test_staleness_is_checked_before_any_com_call() -> None:
    """The staleness guard runs before `ShapeFactory` is ever touched.

    Proven by using a face whose underlying reference has no `Name`/etc, so a
    validation ordering bug that read the reference before checking
    generation would raise something other than `StaleSnapshotError`.
    """
    design = PartDesign(_Part())
    stale_face = Face(object(), 1, generation=design.snapshot_generation - 1)

    with pytest.raises(StaleSnapshotError):
        design.create_hole(HOLE_NAME, stale_face, HOLE_DEPTH)


def test_a_removal_also_invalidates_an_outstanding_face_snapshot() -> None:
    """Deleting a feature changes the topology exactly as creating one does."""
    part = _Part()
    design = PartDesign(part, selection=_Selection())
    face = _face("f1")
    design.create_shell(
        SHELL_NAME, face, SHELL_INTERNAL_THICKNESS, SHELL_EXTERNAL_THICKNESS
    )
    fresh = _current_face(design, "f2")
    design.remove_shell(SHELL_NAME)

    with pytest.raises(StaleSnapshotError):
        design.create_shell(
            "ANOTHER", fresh, SHELL_INTERNAL_THICKNESS, SHELL_EXTERNAL_THICKNESS
        )


def test_a_face_snapshot_taken_after_the_change_is_accepted() -> None:
    """The documented fix -- take a new snapshot -- actually works."""
    part = _Part()
    design = PartDesign(part)
    design.create_shell(
        SHELL_NAME, _face("f1"), SHELL_INTERNAL_THICKNESS, SHELL_EXTERNAL_THICKNESS
    )

    design.create_shell(
        "SECOND",
        _current_face(design, "f2"),
        SHELL_INTERNAL_THICKNESS,
        SHELL_EXTERNAL_THICKNESS,
    )

    assert len(part.ShapeFactory.shell_calls) == 2


def test_an_edge_snapshot_and_a_face_snapshot_share_one_generation_counter() -> None:
    """Both reference kinds are invalidated by the same `PartDesign` model change.

    Only face-creating calls are exercised here (this module owns the face
    layer), but the counter that stamps a face is the exact same
    `PartDesign._generation` an edge would be stamped with -- proven by
    checking `snapshot_generation` moves after a face-creating call, exactly
    as `test_edge_features.test_snapshot_generation_tracks_model_changes`
    proves it moves after an edge-creating call.
    """
    design = PartDesign(_Part())
    assert design.snapshot_generation == 0

    design.create_hole(HOLE_NAME, _face("f1"), HOLE_DEPTH)

    assert design.snapshot_generation == 1
