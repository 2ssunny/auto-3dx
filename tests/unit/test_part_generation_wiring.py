"""Tests that everything reachable from a `Part` shares one model generation.

Each collection was taught to advance a generation it is given, but a counter only
protects topology if it is the SAME counter the topology snapshots are checked
against. A collection built with its own private counter would advance that one and
leave every snapshot looking current. These tests pin the wiring at the `Part`, the
one place that hands the counter out (`docs/api-design.md` section 5.1).
"""

from typing import Any

from auto_3dx.core.part import Part


class _Reference:
    """Fake CATIA `Reference` from a search hit."""

    def __init__(self, name: str) -> None:
        self.Name = name


class _SelectedElement:
    """Fake `SelectedElement`."""

    def __init__(self, reference: _Reference) -> None:
        self.Reference = reference


class _Selection:
    """Fake editor `Selection` returning one edge for any search."""

    def __init__(self) -> None:
        self._hits: list[Any] = []

    def Clear(self) -> None:  # noqa: N802 - COM method name
        self._hits = []

    def Search(self, query: str) -> None:  # noqa: N802 - COM method name
        self._hits = [_SelectedElement(_Reference("edge-1"))]

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self._hits)

    def Item(self, index: int) -> Any:  # noqa: N802 - COM method name
        return self._hits[index - 1]


class _SketchComObject:
    """Fake CATIA `Sketch` read back from a feature."""

    def __init__(self) -> None:
        self.Name = "Sketch.1"


class Pad:
    """Fake CATIA `Pad`; identified by its class name."""

    def __init__(self) -> None:
        self.Name = "Base"
        self.Sketch = _SketchComObject()


class _Shapes:
    """Fake `Shapes` collection."""

    def __init__(self, items: "list[Any]") -> None:
        self._items = items

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self._items)

    def Item(self, index: int) -> Any:  # noqa: N802 - COM method name
        return self._items[index - 1]


class _MainBody:
    """Fake `MainBody`."""

    def __init__(self) -> None:
        self.Shapes = _Shapes([Pad()])


class _RawPart:
    """Fake CATIA `Part` with parameters and one pad."""

    def __init__(self, parameters: Any) -> None:
        self.Parameters = parameters
        self.MainBody = _MainBody()
        self.Name = "3D Shape1"


def _part(parameters_collection_factory: Any) -> Part:
    """Builds a Part whose parameters collection starts empty."""
    return Part(_RawPart(parameters_collection_factory([])), selection=_Selection())


def test_every_collection_shares_the_part_generation(
    parameters_collection_factory: Any,
) -> None:
    """One counter, handed out by the Part, not one per collection."""
    part = _part(parameters_collection_factory)
    shared = part._generation

    for collection in (
        part.parameters,
        part.sketches,
        part.formulas,
        part.planes,
        part.part_design,
        part.topology,
    ):
        assert collection._generation is shared, type(collection).__name__


def test_a_sketch_read_back_from_a_feature_shares_the_part_generation(
    parameters_collection_factory: Any,
) -> None:
    """Renaming `pad.sketch()` must invalidate topology like any other sketch change."""
    part = _part(parameters_collection_factory)

    sketch = part.part_design.get_pad("Base").sketch()

    assert sketch._generation is part._generation


def test_a_parameter_created_through_the_part_makes_a_snapshot_stale(
    parameters_collection_factory: Any,
) -> None:
    """A parameter can drive a dimension, so creating one invalidates topology."""
    part = _part(parameters_collection_factory)
    edges = part.topology.edges()

    part.parameters.create_real("Ratio", 2.0)

    assert edges.generation != part.part_design.snapshot_generation
