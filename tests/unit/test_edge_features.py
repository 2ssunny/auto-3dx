"""Tests for the edge-reference layer and the two edge-based Part Design features.

Verified live (`docs/conventions.md` section 1.2.2.2; probes 28/31/34/35):

    selection.Clear()
    selection.Search("Topology.Edge,all")       # returns void, mutates Selection
    for i in 1..selection.Count:
        reference = selection.Item(i).Reference  # a real, feature-usable Reference
    selection.Clear()

    AddNewEdgeFilletWithConstantRadius(iEdgeToFillet, iPropagMode, iRadius)
        -> ConstRadEdgeFillet, verified with iPropagMode = 1

    AddNewChamfer(iObjectToChamfer, iPropagation, iMode, iOrientation,
                  iLength1, iLength2OrAngle) -> Chamfer
        iMode = 1 is the ONLY working value (0 fails update, 2 fails
        creation). Verified with propagation 0/1 and orientation 0/1, all
        four combinations updating fine.

The fakes below are entirely self-contained (no reliance on `tests.conftest`
for the `Selection.Search`/`SelectedElement.Reference` machinery, which the
shared fixtures do not model): `Selection` records the exact call order so
tests can pin `Clear -> Search -> Item -> Clear`, and `Part.Update`/`Save`/
`PLMPropagate` all raise immediately, so any accidental call from library
code fails every test in this module loudly rather than silently.

The raw fake feature classes are deliberately named `ConstRadEdgeFillet`/
`Chamfer` -- CATIA identifies a feature's kind purely by
`type(obj).__name__`, and those are the verified kind strings
(`EDGE_FILLET_KIND`/`CHAMFER_KIND`). The library's *wrapper* classes of the
same name are imported under an alias to avoid shadowing these fakes.
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
from auto_3dx.geometry.edges import EDGE_SEARCH_QUERY, Edge, EdgeSnapshot, take_edge_snapshot
from auto_3dx.geometry.part_design import (
    CHAMFER_KIND,
    CHAMFER_MODE_VERIFIED,
    CHAMFER_ORIENTATION_0,
    CHAMFER_ORIENTATION_1,
    CHAMFER_PROPAGATION_0,
    CHAMFER_PROPAGATION_1,
    EDGE_FILLET_KIND,
    EDGE_FILLET_PROPAGATION_VERIFIED,
    PartDesign,
)
from auto_3dx.geometry.part_design import Chamfer as ChamferWrapper
from auto_3dx.geometry.part_design import ConstRadEdgeFillet as ConstRadEdgeFilletWrapper

FILLET_NAME = "AUTO3DX_FILLET"
CHAMFER_NAME = "AUTO3DX_CHAMFER"
FILLET_RADIUS = 2.0
CHAMFER_LENGTH_1 = 1.5
CHAMFER_LENGTH_2 = 45.0


# --- fakes -------------------------------------------------------------------


class _Reference:
    """Fake CATIA `Reference`. Only `Name`/`DisplayName` are documented to exist."""

    def __init__(self, name: str = "Selection_REdge:(Edge:(Face:(Brp:(Pad.1;1))))") -> None:
        self.Name = name
        self.DisplayName = name


class _SelectedElement:
    """Fake `SelectedElement`. `.Reference` is the only route probe 28 found working."""

    def __init__(self, reference: _Reference) -> None:
        self.Reference = reference


class _Selection:
    """Fake `Editor.Selection` supporting `Search`, absent from `tests.conftest`.

    Records every call in `calls` (as bare method names, so a test can assert
    the exact `["Clear", "Search", "Item", "Item", "Clear"]`-shaped sequence)
    and every query string passed to `Search` in `queries`.
    """

    def __init__(self, edge_references: "list[_Reference] | None" = None) -> None:
        self.calls: list[str] = []
        self.queries: list[str] = []
        self._pool = [_SelectedElement(ref) for ref in (edge_references or [])]
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


class ConstRadEdgeFillet:
    """Fake CATIA `ConstRadEdgeFillet`. `type(obj).__name__ == "ConstRadEdgeFillet"`."""

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


class Chamfer:
    """Fake CATIA `Chamfer`. `type(obj).__name__ == "Chamfer"`."""

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
    """Fake CATIA `Pad`, used only to prove a fillet/chamfer lookup ignores it."""

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
    """Fake `ShapeFactory` recording the exact fillet/chamfer call arguments."""

    def __init__(
        self,
        shapes: _Shapes,
        fillet_name_write_exception: "BaseException | None" = None,
        chamfer_name_write_exception: "BaseException | None" = None,
    ) -> None:
        self.shapes = shapes
        self.edge_fillet_calls: "list[tuple[Any, ...]]" = []
        self.chamfer_calls: "list[tuple[Any, ...]]" = []
        self._fillet_count = 0
        self._chamfer_count = 0
        self.fillet_name_write_exception = fillet_name_write_exception
        self.chamfer_name_write_exception = chamfer_name_write_exception

    def AddNewEdgeFilletWithConstantRadius(
        self, iEdgeToFillet: Any, iPropagMode: int, iRadius: float
    ) -> ConstRadEdgeFillet:
        self.edge_fillet_calls.append((iEdgeToFillet, iPropagMode, iRadius))
        self._fillet_count += 1
        fillet = ConstRadEdgeFillet(
            f"ConstRadEdgeFillet.{self._fillet_count}",
            name_write_exception=self.fillet_name_write_exception,
        )
        self.shapes._append(fillet)
        return fillet

    def AddNewChamfer(
        self,
        iObjectToChamfer: Any,
        iPropagation: int,
        iMode: int,
        iOrientation: int,
        iLength1: float,
        iLength2OrAngle: float,
    ) -> Chamfer:
        self.chamfer_calls.append(
            (iObjectToChamfer, iPropagation, iMode, iOrientation, iLength1, iLength2OrAngle)
        )
        self._chamfer_count += 1
        chamfer = Chamfer(
            f"Chamfer.{self._chamfer_count}",
            name_write_exception=self.chamfer_name_write_exception,
        )
        self.shapes._append(chamfer)
        return chamfer


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
        fillet_name_write_exception: "BaseException | None" = None,
        chamfer_name_write_exception: "BaseException | None" = None,
    ) -> None:
        self._shapes = _Shapes()
        self.MainBody = _MainBody(self._shapes)
        self.ShapeFactory = _ShapeFactory(
            self._shapes,
            fillet_name_write_exception=fillet_name_write_exception,
            chamfer_name_write_exception=chamfer_name_write_exception,
        )

    def Update(self) -> None:
        raise AssertionError("Part.Update must never be called by this code path.")

    def Save(self) -> None:
        raise AssertionError("Part.Save must never be called.")

    def PLMPropagate(self) -> None:
        raise AssertionError("Part.PLMPropagate must never be called.")


def _edge(descriptor: str = "EDGE_REF_1") -> Edge:
    """Builds a standalone `Edge` handle, without going through a snapshot."""
    return Edge(_Reference(descriptor), 1)


def _current_edge(design: PartDesign, descriptor: str = "EDGE_REF_1") -> Edge:
    """Builds an `Edge` stamped with `design`'s current model generation.

    A real caller gets one from `snapshot_edges()`. A test that only wants a
    usable edge, and is not about staleness, would otherwise have to build a
    `_Selection` just to get past the staleness check.
    """
    return Edge(_Reference(descriptor), 1, design.snapshot_generation)


# --- Edge / EdgeSnapshot -------------------------------------------------------


def test_edge_exposes_reference_and_index() -> None:
    """`Edge.com_object` is the raw reference; `index` is the search position."""
    reference = _Reference("some-brep-name")
    edge = Edge(reference, 7)

    assert edge.com_object is reference
    assert edge.index == 7


def test_edge_descriptor_reads_reference_name() -> None:
    """`descriptor` is the reference's `Name`, exposed only for logging/comparison."""
    edge = Edge(_Reference("Selection_REdge:(...)"), 1)

    assert edge.descriptor == "Selection_REdge:(...)"


def test_edge_descriptor_wraps_com_error() -> None:
    """A COM failure reading `Name` must surface as `Auto3dxError`, not raw."""

    class _RaisingReference:
        @property
        def Name(self) -> str:
            raise pywintypes.com_error(
                -2147352567, "Exception occurred.", (0, "CATIA", "failed", None, 0, -1), None
            )

    edge = Edge(_RaisingReference(), 1)

    with pytest.raises(Auto3dxError):
        _ = edge.descriptor


def test_edge_repr_does_not_read_descriptor() -> None:
    """`repr` must not touch the (possibly huge, possibly raising) BRep name."""

    class _RaisingReference:
        @property
        def Name(self) -> str:
            raise AssertionError("repr must not read Name")

    edge = Edge(_RaisingReference(), 3)

    assert repr(edge) == "Edge(index=3)"


def test_edge_snapshot_supports_len_iter_getitem() -> None:
    """`EdgeSnapshot` behaves like a small read-only sequence of `Edge`."""
    edges = [_edge("a"), _edge("b"), _edge("c")]

    snapshot = EdgeSnapshot(edges)

    assert len(snapshot) == 3
    assert list(snapshot) == edges
    assert snapshot[0] is edges[0]
    assert snapshot[2] is edges[2]


def test_take_edge_snapshot_uses_exact_query_and_call_order() -> None:
    """Pins `Clear -> Search("Topology.Edge,all") -> Item(i) -> Clear`."""
    selection = _Selection([_Reference("e1"), _Reference("e2")])

    snapshot = take_edge_snapshot(selection)

    assert selection.queries == [EDGE_SEARCH_QUERY]
    assert selection.calls == ["Clear", "Search", "Item", "Item", "Clear"]
    assert len(snapshot) == 2


def test_take_edge_snapshot_reads_selected_element_reference_not_create_reference() -> None:
    """The edge's `com_object` must be exactly `SelectedElement.Reference`.

    `Part.CreateReferenceFromObject` fails on a search hit (probe 28), so
    nothing here may go through it -- and nothing in this fake even defines
    it, so a wrongly-implemented `take_edge_snapshot` would raise
    `AttributeError` rather than silently succeeding.
    """
    reference = _Reference("only-route-that-works")
    selection = _Selection([reference])

    snapshot = take_edge_snapshot(selection)

    assert snapshot[0].com_object is reference


def test_take_edge_snapshot_indexes_edges_one_based_in_search_order() -> None:
    """`Edge.index` reflects the one-based `Selection.Item` position."""
    selection = _Selection([_Reference("e1"), _Reference("e2"), _Reference("e3")])

    snapshot = take_edge_snapshot(selection)

    assert [edge.index for edge in snapshot] == [1, 2, 3]


def test_take_edge_snapshot_requires_a_selection() -> None:
    """No selection means no way to delete/search -- refuse rather than crash."""
    with pytest.raises(Auto3dxError):
        take_edge_snapshot(None)


def test_take_edge_snapshot_wraps_search_com_error() -> None:
    """A COM failure during `Search` must surface as `Auto3dxError`."""
    selection = _Selection([])
    selection.search_exception = pywintypes.com_error(
        -2147352567, "Exception occurred.", (0, "CATIA", "failed", None, 0, -1), None
    )

    with pytest.raises(Auto3dxError):
        take_edge_snapshot(selection)


def test_part_design_snapshot_edges_delegates_to_take_edge_snapshot() -> None:
    """`PartDesign.snapshot_edges` is a thin, selection-wired forward."""
    selection = _Selection([_Reference("e1")])
    design = PartDesign(_Part(), selection=selection)

    with pytest.warns(DeprecationWarning, match="part.topology"):
        snapshot = design.snapshot_edges()

    assert selection.queries == [EDGE_SEARCH_QUERY]
    assert len(snapshot) == 1


def test_part_design_snapshot_edges_without_selection_raises() -> None:
    """No editor selection wired in means edges cannot be searched at all."""
    design = PartDesign(_Part(), selection=None)

    with pytest.warns(DeprecationWarning), pytest.raises(Auto3dxError):
        design.snapshot_edges()


# --- create_edge_fillet: happy path and exact COM call ------------------------


def test_create_edge_fillet_passes_verified_argument_tuple() -> None:
    """Pins `(reference, EDGE_FILLET_PROPAGATION_VERIFIED, radius)`, in that order."""
    part = _Part()
    design = PartDesign(part)
    edge = _edge()

    fillet = design.create_edge_fillet(FILLET_NAME, edge, FILLET_RADIUS)

    assert part.ShapeFactory.edge_fillet_calls == [
        (edge.com_object, EDGE_FILLET_PROPAGATION_VERIFIED, FILLET_RADIUS)
    ]
    assert isinstance(fillet, ConstRadEdgeFilletWrapper)
    assert fillet.name == FILLET_NAME


def test_create_edge_fillet_coerces_int_radius_to_float() -> None:
    """An `int` radius must reach COM as a `float`, matching Pad/Pocket's contract."""
    part = _Part()
    design = PartDesign(part)

    design.create_edge_fillet(FILLET_NAME, _edge(), 2)

    (_, _, radius) = part.ShapeFactory.edge_fillet_calls[0]
    assert radius == 2.0
    assert isinstance(radius, float)


def test_create_edge_fillet_never_calls_update_save_or_plm_propagate() -> None:
    """The fake's `Update`/`Save`/`PLMPropagate` raise; reaching them fails the test."""
    design = PartDesign(_Part())

    design.create_edge_fillet(FILLET_NAME, _edge(), FILLET_RADIUS)
    # No assertion needed beyond "did not raise" -- the fake's Update/Save/
    # PLMPropagate would have raised AssertionError if called.


# --- create_edge_fillet: validation before COM ---------------------------------


@pytest.mark.parametrize(
    "bad_name",
    ["", "Has\\Backslash"],
)
def test_create_edge_fillet_rejects_bad_name_before_com(bad_name: str) -> None:
    """An unusable name must be refused before `ShapeFactory` is ever touched."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterNameError):
        design.create_edge_fillet(bad_name, _edge(), FILLET_RADIUS)

    assert part.ShapeFactory.edge_fillet_calls == []


def test_create_edge_fillet_rejects_non_edge_before_com() -> None:
    """A raw reference (not wrapped in `Edge`) must never reach COM directly."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterTypeError):
        design.create_edge_fillet(FILLET_NAME, _Reference("not-an-edge"), FILLET_RADIUS)

    assert part.ShapeFactory.edge_fillet_calls == []


@pytest.mark.parametrize("bad_radius", [0.0, -1.0, float("nan"), float("inf")])
def test_create_edge_fillet_rejects_non_positive_or_non_finite_radius(
    bad_radius: float,
) -> None:
    """Radius must be finite and strictly positive before COM is touched."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterTypeError):
        design.create_edge_fillet(FILLET_NAME, _edge(), bad_radius)

    assert part.ShapeFactory.edge_fillet_calls == []


def test_create_edge_fillet_rejects_bool_radius() -> None:
    """`bool` is a subclass of `int`; it must still be refused."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterTypeError):
        design.create_edge_fillet(FILLET_NAME, _edge(), True)

    assert part.ShapeFactory.edge_fillet_calls == []


def test_create_edge_fillet_rejects_unsupported_unit() -> None:
    """An unsupported unit must be refused before COM is touched."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(UnsupportedUnitError):
        design.create_edge_fillet(FILLET_NAME, _edge(), FILLET_RADIUS, unit="furlong")

    assert part.ShapeFactory.edge_fillet_calls == []


def test_create_edge_fillet_rejects_unsupported_propagation() -> None:
    """Only `EDGE_FILLET_PROPAGATION_VERIFIED` (1) is offered; no other integer."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterTypeError):
        design.create_edge_fillet(FILLET_NAME, _edge(), FILLET_RADIUS, propagation=0)

    assert part.ShapeFactory.edge_fillet_calls == []


def test_create_edge_fillet_conflicts_with_existing_name() -> None:
    """Two fillets cannot share a name."""
    design = PartDesign(_Part())
    design.create_edge_fillet(FILLET_NAME, _edge("e1"), FILLET_RADIUS)

    with pytest.raises(FeatureConflictError):
        design.create_edge_fillet(FILLET_NAME, _current_edge(design, "e2"), FILLET_RADIUS)


def test_create_edge_fillet_partial_creation_when_rename_fails(
    com_error_factory: Any,
) -> None:
    """A failed rename must be reported, and the feature stays in the model."""
    part = _Part(fillet_name_write_exception=com_error_factory())
    design = PartDesign(part)

    with pytest.raises(PartialCreationError):
        design.create_edge_fillet(FILLET_NAME, _edge(), FILLET_RADIUS)

    # The feature is left behind under its default name, not rolled back.
    assert part.MainBody.Shapes.Count == 1


# --- create_chamfer: happy path and exact COM call -----------------------------


def test_create_chamfer_passes_verified_argument_tuple_and_hardcoded_mode() -> None:
    """Pins the full 6-argument call, with `iMode` always `CHAMFER_MODE_VERIFIED`."""
    part = _Part()
    design = PartDesign(part)
    edge = _edge()

    chamfer = design.create_chamfer(
        CHAMFER_NAME,
        edge,
        CHAMFER_LENGTH_1,
        CHAMFER_LENGTH_2,
        propagation=CHAMFER_PROPAGATION_1,
        orientation=CHAMFER_ORIENTATION_0,
    )

    assert part.ShapeFactory.chamfer_calls == [
        (
            edge.com_object,
            CHAMFER_PROPAGATION_1,
            CHAMFER_MODE_VERIFIED,
            CHAMFER_ORIENTATION_0,
            CHAMFER_LENGTH_1,
            CHAMFER_LENGTH_2,
        )
    ]
    assert isinstance(chamfer, ChamferWrapper)
    assert chamfer.name == CHAMFER_NAME


@pytest.mark.parametrize(
    ("propagation", "orientation"),
    [
        (CHAMFER_PROPAGATION_0, CHAMFER_ORIENTATION_0),
        (CHAMFER_PROPAGATION_0, CHAMFER_ORIENTATION_1),
        (CHAMFER_PROPAGATION_1, CHAMFER_ORIENTATION_0),
        (CHAMFER_PROPAGATION_1, CHAMFER_ORIENTATION_1),
    ],
)
def test_create_chamfer_mode_is_always_verified_across_all_combinations(
    propagation: int, orientation: int
) -> None:
    """Every verified propagation/orientation combination still hardcodes mode."""
    part = _Part()
    design = PartDesign(part)

    design.create_chamfer(
        CHAMFER_NAME,
        _edge(),
        CHAMFER_LENGTH_1,
        CHAMFER_LENGTH_2,
        propagation=propagation,
        orientation=orientation,
    )

    (_, call_propagation, call_mode, call_orientation, _, _) = part.ShapeFactory.chamfer_calls[0]
    assert call_mode == CHAMFER_MODE_VERIFIED == 1
    assert call_propagation == propagation
    assert call_orientation == orientation


def test_create_chamfer_does_not_accept_a_mode_argument() -> None:
    """Mode 0/2 are not offered under any name -- there is no `mode` parameter at all."""
    design = PartDesign(_Part())

    with pytest.raises(TypeError):
        design.create_chamfer(  # type: ignore[call-arg]
            CHAMFER_NAME,
            _edge(),
            CHAMFER_LENGTH_1,
            CHAMFER_LENGTH_2,
            propagation=CHAMFER_PROPAGATION_1,
            orientation=CHAMFER_ORIENTATION_1,
            mode=0,
        )


def test_create_chamfer_never_calls_update_save_or_plm_propagate() -> None:
    """The fake's `Update`/`Save`/`PLMPropagate` raise; reaching them fails the test."""
    design = PartDesign(_Part())

    design.create_chamfer(
        CHAMFER_NAME,
        _edge(),
        CHAMFER_LENGTH_1,
        CHAMFER_LENGTH_2,
        propagation=CHAMFER_PROPAGATION_0,
        orientation=CHAMFER_ORIENTATION_0,
    )


# --- create_chamfer: validation before COM -------------------------------------


@pytest.mark.parametrize(
    "bad_name",
    ["", "Has\\Backslash"],
)
def test_create_chamfer_rejects_bad_name_before_com(bad_name: str) -> None:
    """An unusable name must be refused before `ShapeFactory` is ever touched."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterNameError):
        design.create_chamfer(
            bad_name,
            _edge(),
            CHAMFER_LENGTH_1,
            CHAMFER_LENGTH_2,
            propagation=CHAMFER_PROPAGATION_0,
            orientation=CHAMFER_ORIENTATION_0,
        )

    assert part.ShapeFactory.chamfer_calls == []


def test_create_chamfer_rejects_non_edge_before_com() -> None:
    """A raw reference (not wrapped in `Edge`) must never reach COM directly."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterTypeError):
        design.create_chamfer(
            CHAMFER_NAME,
            _Reference("not-an-edge"),
            CHAMFER_LENGTH_1,
            CHAMFER_LENGTH_2,
            propagation=CHAMFER_PROPAGATION_0,
            orientation=CHAMFER_ORIENTATION_0,
        )

    assert part.ShapeFactory.chamfer_calls == []


@pytest.mark.parametrize("bad_length", [0.0, -1.0, float("nan"), float("inf")])
def test_create_chamfer_rejects_non_positive_or_non_finite_length1(bad_length: float) -> None:
    """`length1` must be finite and strictly positive before COM is touched."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterTypeError):
        design.create_chamfer(
            CHAMFER_NAME,
            _edge(),
            bad_length,
            CHAMFER_LENGTH_2,
            propagation=CHAMFER_PROPAGATION_0,
            orientation=CHAMFER_ORIENTATION_0,
        )

    assert part.ShapeFactory.chamfer_calls == []


@pytest.mark.parametrize("bad_length", [0.0, -1.0, float("nan"), float("inf")])
def test_create_chamfer_rejects_non_positive_or_non_finite_length2(bad_length: float) -> None:
    """`length2_or_angle` must be finite and strictly positive before COM is touched."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterTypeError):
        design.create_chamfer(
            CHAMFER_NAME,
            _edge(),
            CHAMFER_LENGTH_1,
            bad_length,
            propagation=CHAMFER_PROPAGATION_0,
            orientation=CHAMFER_ORIENTATION_0,
        )

    assert part.ShapeFactory.chamfer_calls == []


def test_create_chamfer_rejects_unsupported_propagation() -> None:
    """Only 0/1 are offered for `iPropagation` -- no other integer."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterTypeError):
        design.create_chamfer(
            CHAMFER_NAME,
            _edge(),
            CHAMFER_LENGTH_1,
            CHAMFER_LENGTH_2,
            propagation=2,
            orientation=CHAMFER_ORIENTATION_0,
        )

    assert part.ShapeFactory.chamfer_calls == []


def test_create_chamfer_rejects_unsupported_orientation() -> None:
    """Only 0/1 are offered for `iOrientation` -- no other integer."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(ParameterTypeError):
        design.create_chamfer(
            CHAMFER_NAME,
            _edge(),
            CHAMFER_LENGTH_1,
            CHAMFER_LENGTH_2,
            propagation=CHAMFER_PROPAGATION_0,
            orientation=7,
        )

    assert part.ShapeFactory.chamfer_calls == []


def test_create_chamfer_rejects_unsupported_unit() -> None:
    """An unsupported unit must be refused before COM is touched."""
    part = _Part()
    design = PartDesign(part)

    with pytest.raises(UnsupportedUnitError):
        design.create_chamfer(
            CHAMFER_NAME,
            _edge(),
            CHAMFER_LENGTH_1,
            CHAMFER_LENGTH_2,
            propagation=CHAMFER_PROPAGATION_0,
            orientation=CHAMFER_ORIENTATION_0,
            unit="furlong",
        )

    assert part.ShapeFactory.chamfer_calls == []


def test_create_chamfer_conflicts_with_existing_name() -> None:
    """Two chamfers cannot share a name."""
    design = PartDesign(_Part())
    design.create_chamfer(
        CHAMFER_NAME,
        _edge("e1"),
        CHAMFER_LENGTH_1,
        CHAMFER_LENGTH_2,
        propagation=CHAMFER_PROPAGATION_0,
        orientation=CHAMFER_ORIENTATION_0,
    )

    with pytest.raises(FeatureConflictError):
        design.create_chamfer(
            CHAMFER_NAME,
            _current_edge(design, "e2"),
            CHAMFER_LENGTH_1,
            CHAMFER_LENGTH_2,
            propagation=CHAMFER_PROPAGATION_0,
            orientation=CHAMFER_ORIENTATION_0,
        )


def test_create_chamfer_partial_creation_when_rename_fails(com_error_factory: Any) -> None:
    """A failed rename must be reported, and the feature stays in the model."""
    part = _Part(chamfer_name_write_exception=com_error_factory())
    design = PartDesign(part)

    with pytest.raises(PartialCreationError):
        design.create_chamfer(
            CHAMFER_NAME,
            _edge(),
            CHAMFER_LENGTH_1,
            CHAMFER_LENGTH_2,
            propagation=CHAMFER_PROPAGATION_0,
            orientation=CHAMFER_ORIENTATION_0,
        )

    assert part.MainBody.Shapes.Count == 1


# --- listing / get_* / remove_* : kinds do not leak into each other -----------


def test_edge_fillets_and_chamfers_and_pads_stay_separate() -> None:
    """A pad, a fillet, and a chamfer sharing `MainBody.Shapes` must not cross-list."""
    part = _Part()
    design = PartDesign(part)
    part.MainBody.Shapes._append(Pad("SharedName"))
    design.create_edge_fillet(FILLET_NAME, _current_edge(design, "e1"), FILLET_RADIUS)
    design.create_chamfer(
        CHAMFER_NAME,
        _current_edge(design, "e2"),
        CHAMFER_LENGTH_1,
        CHAMFER_LENGTH_2,
        propagation=CHAMFER_PROPAGATION_0,
        orientation=CHAMFER_ORIENTATION_0,
    )

    assert [f.name for f in design.edge_fillets] == [FILLET_NAME]
    assert [f.name for f in design.chamfers] == [CHAMFER_NAME]


def test_get_edge_fillet_does_not_return_a_pad() -> None:
    """A pad holding the requested name must not satisfy a fillet lookup."""
    part = _Part()
    design = PartDesign(part)
    part.MainBody.Shapes._append(Pad(FILLET_NAME))

    with pytest.raises(FeatureNotFoundError):
        design.get_edge_fillet(FILLET_NAME)


def test_get_chamfer_does_not_return_a_pad() -> None:
    """A pad holding the requested name must not satisfy a chamfer lookup."""
    part = _Part()
    design = PartDesign(part)
    part.MainBody.Shapes._append(Pad(CHAMFER_NAME))

    with pytest.raises(FeatureNotFoundError):
        design.get_chamfer(CHAMFER_NAME)


def test_get_edge_fillet_does_not_return_a_chamfer() -> None:
    """A chamfer holding the requested name must not satisfy a fillet lookup."""
    design = PartDesign(_Part())
    design.create_chamfer(
        FILLET_NAME,
        _edge(),
        CHAMFER_LENGTH_1,
        CHAMFER_LENGTH_2,
        propagation=CHAMFER_PROPAGATION_0,
        orientation=CHAMFER_ORIENTATION_0,
    )

    with pytest.raises(FeatureNotFoundError):
        design.get_edge_fillet(FILLET_NAME)


def test_get_chamfer_does_not_return_an_edge_fillet() -> None:
    """A fillet holding the requested name must not satisfy a chamfer lookup."""
    design = PartDesign(_Part())
    design.create_edge_fillet(CHAMFER_NAME, _edge(), FILLET_RADIUS)

    with pytest.raises(FeatureNotFoundError):
        design.get_chamfer(CHAMFER_NAME)


def test_get_edge_fillet_raises_when_missing() -> None:
    """A name-based lookup with nothing at all must raise, not return `None`."""
    design = PartDesign(_Part())

    with pytest.raises(FeatureNotFoundError):
        design.get_edge_fillet("MISSING")


def test_get_edge_fillet_raises_when_ambiguous() -> None:
    """Two same-named fillets is unsafe to resolve automatically."""
    part = _Part()
    part.MainBody.Shapes._append(ConstRadEdgeFillet(FILLET_NAME))
    part.MainBody.Shapes._append(ConstRadEdgeFillet(FILLET_NAME))
    design = PartDesign(part)

    with pytest.raises(AmbiguousNameError):
        design.get_edge_fillet(FILLET_NAME)


def test_get_chamfer_raises_when_ambiguous() -> None:
    """Two same-named chamfers is unsafe to resolve automatically."""
    part = _Part()
    part.MainBody.Shapes._append(Chamfer(CHAMFER_NAME))
    part.MainBody.Shapes._append(Chamfer(CHAMFER_NAME))
    design = PartDesign(part)

    with pytest.raises(AmbiguousNameError):
        design.get_chamfer(CHAMFER_NAME)


def test_kind_constants_match_the_verified_com_type_names() -> None:
    """`EDGE_FILLET_KIND`/`CHAMFER_KIND` must be the exact `type(obj).__name__` values."""
    assert EDGE_FILLET_KIND == "ConstRadEdgeFillet"
    assert CHAMFER_KIND == "Chamfer"


# --- remove_* ------------------------------------------------------------------


def test_remove_edge_fillet_uses_the_selection_delete_sequence() -> None:
    """Deletion goes through `Clear -> Add -> Delete`, the only verified route."""
    part = _Part()
    selection = _Selection()
    design = PartDesign(part, selection=selection)
    fillet = design.create_edge_fillet(FILLET_NAME, _edge(), FILLET_RADIUS)

    design.remove_edge_fillet(FILLET_NAME)

    assert selection.deleted == [fillet.com_object]


def test_remove_chamfer_uses_the_selection_delete_sequence() -> None:
    """Deletion goes through `Clear -> Add -> Delete`, the only verified route."""
    part = _Part()
    selection = _Selection()
    design = PartDesign(part, selection=selection)
    chamfer = design.create_chamfer(
        CHAMFER_NAME,
        _edge(),
        CHAMFER_LENGTH_1,
        CHAMFER_LENGTH_2,
        propagation=CHAMFER_PROPAGATION_0,
        orientation=CHAMFER_ORIENTATION_0,
    )

    design.remove_chamfer(CHAMFER_NAME)

    assert selection.deleted == [chamfer.com_object]


def test_remove_edge_fillet_without_selection_raises() -> None:
    """No editor selection wired in means deletion is unavailable."""
    design = PartDesign(_Part(), selection=None)
    design.create_edge_fillet(FILLET_NAME, _edge(), FILLET_RADIUS)

    with pytest.raises(Auto3dxError):
        design.remove_edge_fillet(FILLET_NAME)


def test_remove_edge_fillet_raises_when_missing() -> None:
    """Removing a name that does not exist must not silently succeed."""
    design = PartDesign(_Part(), selection=_Selection())

    with pytest.raises(FeatureNotFoundError):
        design.remove_edge_fillet("MISSING")


def test_remove_chamfer_raises_when_missing() -> None:
    """Removing a name that does not exist must not silently succeed."""
    design = PartDesign(_Part(), selection=_Selection())

    with pytest.raises(FeatureNotFoundError):
        design.remove_chamfer("MISSING")


# --- no ensure_* is offered ------------------------------------------------------


def test_there_is_no_ensure_edge_fillet_or_ensure_chamfer() -> None:
    """A truthful `ensure_*` is not possible here (see `geometry.edges`); none exists."""
    design = PartDesign(_Part())

    assert not hasattr(design, "ensure_edge_fillet")
    assert not hasattr(design, "ensure_chamfer")


# --- staleness guard ----------------------------------------------------------


def test_an_edge_from_before_a_model_change_is_refused() -> None:
    """The single sharpest edge in this API: reuse must not reach COM.

    Measured on a plain cube with one fillet already applied, a second fillet
    from the same snapshot failed for the next edge, the middle edge and the
    last edge alike, two of them at the creation call and one at the update,
    while a fresh snapshot's first edge succeeded. Elsewhere the same reuse
    worked. Passing that coin flip to a caller is what this guard prevents.
    """
    part = _Part()
    design = PartDesign(part)
    edge = _edge("e1")
    design.create_edge_fillet(FILLET_NAME, edge, FILLET_RADIUS)

    with pytest.raises(StaleSnapshotError):
        design.create_edge_fillet("OTHER_FILLET", edge, FILLET_RADIUS)
    with pytest.raises(StaleSnapshotError):
        design.create_chamfer(
            "OTHER_CHAMFER",
            edge,
            CHAMFER_LENGTH_1,
            CHAMFER_LENGTH_2,
            propagation=CHAMFER_PROPAGATION_0,
            orientation=CHAMFER_ORIENTATION_0,
        )
    # Refused before COM, so only the first feature was ever created.
    assert len(part.ShapeFactory.edge_fillet_calls) == 1
    assert part.ShapeFactory.chamfer_calls == []


def test_a_removal_also_invalidates_an_outstanding_snapshot() -> None:
    """Deleting a feature changes the topology exactly as creating one does."""
    part = _Part()
    design = PartDesign(part, selection=_Selection())
    edge = _edge("e1")
    design.create_edge_fillet(FILLET_NAME, edge, FILLET_RADIUS)
    fresh = _current_edge(design, "e2")
    design.remove_edge_fillet(FILLET_NAME)

    with pytest.raises(StaleSnapshotError):
        design.create_edge_fillet("ANOTHER", fresh, FILLET_RADIUS)


def test_a_snapshot_taken_after_the_change_is_accepted() -> None:
    """The documented fix -- take a new snapshot -- actually works."""
    part = _Part()
    design = PartDesign(part)
    design.create_edge_fillet(FILLET_NAME, _edge("e1"), FILLET_RADIUS)

    design.create_edge_fillet("SECOND", _current_edge(design, "e2"), FILLET_RADIUS)

    assert len(part.ShapeFactory.edge_fillet_calls) == 2


def test_snapshot_generation_tracks_model_changes() -> None:
    """A caller can ask whether the snapshot it holds is still current."""
    design = PartDesign(_Part())
    assert design.snapshot_generation == 0

    design.create_edge_fillet(FILLET_NAME, _edge("e1"), FILLET_RADIUS)

    assert design.snapshot_generation == 1

