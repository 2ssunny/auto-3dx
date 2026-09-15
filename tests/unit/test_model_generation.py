"""Tests for the shared model generation (`docs/api-design.md` section 5).

The generation used to live inside `PartDesign`, and only its own create and remove
paths advanced it. A feature dimension setter, pattern creation, pattern removal and
`Part.update()` all changed the model without invalidating a topology snapshot,
although one pad height change was measured rewriting a live solid from 20 edges to
29 with every name changed (probe 31). These tests pin the paths that were missing
and the rules that close them: one counter per `Part`, advanced by every attempted
mutation and every rebuild, never by a read or by a request rejected before COM.
"""

from typing import Any

import pytest
import pywintypes

from auto_3dx._generation import ModelGeneration
from auto_3dx.core.part import Part
from auto_3dx.errors import Auto3dxError, PartUpdateError, StaleSnapshotError

FILLET_RADIUS = 1.0
NEW_PAD_HEIGHT = 17.0
PATTERN_COUNT = 2
PATTERN_SPACING = 30.0


# --- Fakes ---------------------------------------------------------------------


class _Reference:
    """Fake CATIA `Reference` read from a search hit."""

    def __init__(self, name: str) -> None:
        self.Name = name
        self.DisplayName = name


class _SelectedElement:
    """Fake `SelectedElement`; `.Reference` is the verified route to a reference."""

    def __init__(self, reference: _Reference) -> None:
        self.Reference = reference


class _Selection:
    """Fake editor `Selection` supporting search and selection-based deletion."""

    def __init__(self, references: "list[_Reference]") -> None:
        self._pool = [_SelectedElement(reference) for reference in references]
        self._current: list[Any] = []
        self.deleted: list[Any] = []
        self._added: list[Any] = []

    def Clear(self) -> None:  # noqa: N802 - COM method name
        self._current = []
        self._added = []

    def Search(self, query: str) -> None:  # noqa: N802 - COM method name
        self._current = list(self._pool)

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self._current)

    def Item(self, index: int) -> Any:  # noqa: N802 - COM method name
        return self._current[index - 1]

    def Add(self, com_object: Any) -> None:  # noqa: N802 - COM method name
        self._added.append(com_object)

    def Delete(self) -> None:  # noqa: N802 - COM method name
        self.deleted.extend(self._added)


class _Dimension:
    """Fake `Dimension` holding a writable value."""

    def __init__(self, value: float) -> None:
        self.Value = value


class _Limit:
    """Fake `Limit` exposing its `Dimension`."""

    def __init__(self, value: float) -> None:
        self.Dimension = _Dimension(value)


class Pad:
    """Fake CATIA `Pad`; the class name is what the SDK identifies it by."""

    def __init__(self, name: str, height: float) -> None:
        self.Name = name
        self.FirstLimit = _Limit(height)


class ConstRadEdgeFillet:
    """Fake CATIA edge fillet."""

    def __init__(self, name: str) -> None:
        self.Name = name


class RectPattern:
    """Fake CATIA rectangular pattern."""

    def __init__(self) -> None:
        self.Name = "RectPattern.1"


class _Shapes:
    """Fake `Shapes`: 1-based `Item`, `Count`, and no `Remove`, as in CATIA."""

    def __init__(self) -> None:
        self.items: list[Any] = []

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self.items)

    def Item(self, index: int) -> Any:  # noqa: N802 - COM method name
        return self.items[index - 1]


class _ShapeFactory:
    """Fake `ShapeFactory` recording every creation call."""

    def __init__(self, shapes: _Shapes) -> None:
        self.shapes = shapes
        self.fillet_calls: list[tuple[Any, ...]] = []
        self.pattern_calls: list[tuple[Any, ...]] = []

    def AddNewEdgeFilletWithConstantRadius(  # noqa: N802 - COM method name
        self, reference: Any, propagation: int, radius: float
    ) -> ConstRadEdgeFillet:
        self.fillet_calls.append((reference, propagation, radius))
        fillet = ConstRadEdgeFillet(f"ConstRadEdgeFillet.{len(self.fillet_calls)}")
        self.shapes.items.append(fillet)
        return fillet

    def AddNewRectPattern(self, *arguments: Any) -> RectPattern:  # noqa: N802
        self.pattern_calls.append(arguments)
        return RectPattern()


class _OriginElements:
    """Fake origin planes."""

    def __init__(self) -> None:
        self.PlaneXY = object()
        self.PlaneYZ = object()
        self.PlaneZX = object()


class _MainBody:
    """Fake `MainBody` exposing its shapes."""

    def __init__(self, shapes: _Shapes) -> None:
        self.Shapes = shapes


class _RawPart:
    """Fake CATIA `Part` whose `Update()` can be told how to fail."""

    def __init__(self, update_error: BaseException | None = None) -> None:
        self.shapes = _Shapes()
        self.MainBody = _MainBody(self.shapes)
        self.ShapeFactory = _ShapeFactory(self.shapes)
        self.OriginElements = _OriginElements()
        self.Name = "3D Shape1"
        self.update_calls = 0
        self._update_error = update_error

    def CreateReferenceFromObject(self, plane: Any) -> Any:  # noqa: N802
        return ("reference", plane)

    def Update(self) -> None:  # noqa: N802 - COM method name
        self.update_calls += 1
        if self._update_error is not None:
            raise self._update_error

    def Save(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("Save() must never be called.")

    def PLMPropagate(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("PLMPropagate() must never be called.")


def _part(update_error: BaseException | None = None) -> "tuple[Part, _RawPart]":
    """Builds a Part with a base pad and a two-edge solid to snapshot."""
    raw = _RawPart(update_error)
    raw.shapes.items.append(Pad("Base", 10.0))
    selection = _Selection([_Reference("edge-1"), _Reference("edge-2")])
    return Part(raw, selection=selection), raw


def _generation(part: Part) -> int:
    """Reads the Part's generation through the public accessor."""
    return part.part_design.snapshot_generation


# --- ModelGeneration -----------------------------------------------------------


def test_generation_starts_at_zero_and_advances_by_one() -> None:
    """The counter is a plain monotonic count of model changes."""
    generation = ModelGeneration()
    assert generation.value == 0

    generation.advance()

    assert generation.value == 1


def test_mutation_block_advances_when_it_succeeds() -> None:
    """A completed mutation makes outstanding snapshots stale."""
    generation = ModelGeneration()

    with generation.mutation():
        pass

    assert generation.value == 1


def test_mutation_block_advances_even_when_it_raises() -> None:
    """A mutation that raised may still have changed the model.

    `AddNew*` can create a feature and then fail its rename, so the SDK advances on
    attempt, not on success.
    """
    generation = ModelGeneration()

    with pytest.raises(RuntimeError), generation.mutation():
        raise RuntimeError("the COM call failed half way")

    assert generation.value == 1


def test_require_current_accepts_the_current_generation() -> None:
    """A handle from the current generation passes silently."""
    generation = ModelGeneration()

    generation.require_current(0, "edge", "part.topology.edges()")


def test_require_current_refuses_an_older_generation_and_says_how_to_recover() -> None:
    """The message names the call that produces a fresh snapshot."""
    generation = ModelGeneration()
    generation.advance()

    with pytest.raises(StaleSnapshotError, match=r"part\.topology\.edges\(\)"):
        generation.require_current(0, "edge", "part.topology.edges()")


# --- One generation per Part ---------------------------------------------------


def test_topology_and_part_design_share_the_part_generation() -> None:
    """A snapshot from `part.topology` is current for `part.part_design`."""
    part, raw = _part()

    edges = part.topology.edges()
    part.part_design.create_edge_fillet("F1", edges[0], FILLET_RADIUS)

    assert len(raw.ShapeFactory.fillet_calls) == 1


def test_taking_a_snapshot_does_not_advance_the_generation() -> None:
    """Reads never invalidate anything."""
    part, _ = _part()

    part.topology.edges()
    part.topology.faces()

    assert _generation(part) == 0


def test_a_rejected_request_does_not_advance_the_generation() -> None:
    """Validation that fails before any COM call leaves the model and counter alone."""
    part, raw = _part()
    edges = part.topology.edges()

    with pytest.raises(Auto3dxError):
        part.part_design.create_edge_fillet("", edges[0], FILLET_RADIUS)

    assert _generation(part) == 0
    assert raw.ShapeFactory.fillet_calls == []


# --- The paths that used to be untracked ---------------------------------------


def test_a_pad_height_change_makes_a_snapshot_stale() -> None:
    """The hole probe 31 exposed: a dimension write rewrites the whole edge set."""
    part, raw = _part()
    pad = part.part_design.get_pad("Base")
    edges = part.topology.edges()

    pad.set_height(NEW_PAD_HEIGHT)

    with pytest.raises(StaleSnapshotError):
        part.part_design.create_edge_fillet("F1", edges[0], FILLET_RADIUS)
    assert raw.ShapeFactory.fillet_calls == []


def test_update_makes_a_snapshot_stale_when_it_succeeds() -> None:
    """The rebuild is when CATIA recomputes topology."""
    part, raw = _part()
    edges = part.topology.edges()

    part.update()

    assert raw.update_calls == 1
    with pytest.raises(StaleSnapshotError):
        part.part_design.create_edge_fillet("F1", edges[0], FILLET_RADIUS)


def test_update_advances_the_generation_when_it_fails(com_error_factory: Any) -> None:
    """A failed rebuild leaves the model in a state the caller must repair."""
    part, _ = _part(update_error=com_error_factory())

    with pytest.raises(PartUpdateError):
        part.update()

    assert _generation(part) == 1


def test_creating_a_pattern_advances_the_generation() -> None:
    """Pattern creation bypassed the old counter entirely."""
    part, raw = _part()
    pad = part.part_design.get_pad("Base")

    part.part_design.create_rectangular_pattern(
        pad,
        number_in_direction_1=PATTERN_COUNT,
        number_in_direction_2=PATTERN_COUNT,
        spacing_in_direction_1=PATTERN_SPACING,
        spacing_in_direction_2=PATTERN_SPACING,
        direction_1="X",
        direction_2="Y",
    )

    assert len(raw.ShapeFactory.pattern_calls) == 1
    assert _generation(part) == 1


def test_removing_a_pattern_advances_the_generation() -> None:
    """So did pattern removal, although removing a feature changes topology too."""
    part, _ = _part()
    pad = part.part_design.get_pad("Base")
    pattern = part.part_design.create_rectangular_pattern(
        pad,
        number_in_direction_1=PATTERN_COUNT,
        number_in_direction_2=PATTERN_COUNT,
        spacing_in_direction_1=PATTERN_SPACING,
        spacing_in_direction_2=PATTERN_SPACING,
        direction_1="X",
        direction_2="Y",
    )
    before = _generation(part)

    part.part_design.remove_rectangular_pattern(pattern)

    assert _generation(part) == before + 1


def test_removing_a_feature_by_name_advances_the_generation() -> None:
    """Named removal goes through the same shared counter."""
    part, _ = _part()
    edges = part.topology.edges()
    part.part_design.create_edge_fillet("F1", edges[0], FILLET_RADIUS)
    before = _generation(part)

    part.part_design.remove_edge_fillet("F1")

    assert _generation(part) == before + 1


# --- update() error mapping ------------------------------------------------------


def test_update_maps_a_com_failure_and_keeps_the_cause(com_error_factory: Any) -> None:
    """The original COM error stays reachable for debugging."""
    error = com_error_factory()
    part, _ = _part(update_error=error)

    with pytest.raises(PartUpdateError) as caught:
        part.update()

    assert isinstance(caught.value.__cause__, pywintypes.com_error)


def test_update_maps_a_missing_dispatch_member() -> None:
    """A member missing from a release is a real possibility, not a library bug."""
    part, _ = _part(update_error=AttributeError("Update"))

    with pytest.raises(PartUpdateError, match="unusable in this release"):
        part.update()


def test_update_does_not_disguise_an_unrelated_bug() -> None:
    """Anything broader propagates, so a bug here is not reported as CATIA's fault."""
    part, _ = _part(update_error=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        part.update()
