"""Tests for read-only inspection (`docs/api-design.md` section 11).

Inspection exists so a caller, especially an AI agent, can find out what a model
contains before changing it. Its value depends on three promises these tests pin: it
reports what is really there, including features the SDK cannot create; it returns
structured data rather than text; and it changes nothing -- no generation advance, no
rebuild, no save, and a user selection that ends as it started even though edge and
face counts come from a topology search.
"""

from typing import Any

import pytest
import pywintypes

from auto_3dx.core.part import Part
from auto_3dx.errors import AutomationError
from auto_3dx.geometry.edges import EDGE_SEARCH_QUERY
from auto_3dx.geometry.faces import FACE_SEARCH_QUERY
from auto_3dx.inspect import (
    BodyInfo,
    FeatureInfo,
    GeometricalSetInfo,
    GeometryInfo,
    PartSummary,
    TopologyCounts,
)

HRESULT_EXCEPTION_OCCURRED = -2147352567
WIDTH_MM = 60.0
EDGE_COUNT = 3
FACE_COUNT = 2
NESTED_SET_COUNT = 1


class Pad:
    """Fake CATIA `Pad`."""

    def __init__(self, name: str) -> None:
        self.Name = name


class Pocket:
    """Fake CATIA `Pocket`."""

    def __init__(self, name: str) -> None:
        self.Name = name


class Draft:
    """Fake CATIA draft, a kind created in the UI that the SDK does not wrap."""

    def __init__(self, name: str) -> None:
        self.Name = name


class HybridShapePlaneOffset:
    """Fake CATIA offset plane inside a geometrical set."""

    def __init__(self, name: str) -> None:
        self.Name = name


class _SketchComObject:
    """Fake CATIA `Sketch`."""

    def __init__(self, name: str) -> None:
        self.Name = name


class _Collection:
    """Fake 1-based COM collection."""

    def __init__(self, items: "list[Any]") -> None:
        self._items = items

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self._items)

    def Item(self, index: int) -> Any:  # noqa: N802 - COM method name
        return self._items[index - 1]


class _Body:
    """Fake CATIA `Body` with features and sketches."""

    def __init__(self, name: str, shapes: "list[Any]", sketches: "list[Any]") -> None:
        self.Name = name
        self.Shapes = _Collection(shapes)
        self.Sketches = _Collection(sketches)


class _HybridBody:
    """Fake geometrical set with elements and nested sets."""

    def __init__(self, name: str, shapes: "list[Any]", nested: "list[Any]") -> None:
        self.Name = name
        self.HybridShapes = _Collection(shapes)
        self.HybridBodies = _Collection(nested)


class _RawPart:
    """Fake CATIA `Part` that fails the test if anything mutating is called."""

    def __init__(self, parameters: Any, up_to_date: bool = True) -> None:
        self.Name = "Housing"
        self.Parameters = parameters
        self.MainBody = _Body(
            "PartBody",
            [Pad("Base"), Pocket("Bore"), Draft("Draft.1")],
            [_SketchComObject("BaseSketch"), _SketchComObject("BoreSketch")],
        )
        self.tool_body = _Body("Tool", [Pad("ToolPad")], [])
        self.Bodies = _Collection([self.MainBody, self.tool_body])
        self.HybridBodies = _Collection(
            [
                _HybridBody(
                    "Construction",
                    [HybridShapePlaneOffset("Offset.1")],
                    [_HybridBody("Inner", [], [])],
                )
            ]
        )
        self._up_to_date = up_to_date

    def IsUpToDate(self, target: Any) -> bool:  # noqa: N802 - COM method name
        return self._up_to_date

    def Update(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("Inspection must never rebuild the model.")

    def Save(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("Inspection must never save.")


class _Selected:
    """Fake `SelectedElement`."""

    def __init__(self, value: Any) -> None:
        self.Value = value
        self.Reference = value


class _Selection:
    """Fake `Selection` holding one user pick; searches find edges or faces."""

    def __init__(self) -> None:
        self.user_pick = object()
        self.items = [_Selected(self.user_pick)]
        self.deleted = False

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self.items)

    def Item(self, index: int) -> _Selected:  # noqa: N802 - COM method name
        return self.items[index - 1]

    def Clear(self) -> None:  # noqa: N802 - COM method name
        self.items = []

    def Search(self, query: str) -> None:  # noqa: N802 - COM method name
        hits = {EDGE_SEARCH_QUERY: EDGE_COUNT, FACE_SEARCH_QUERY: FACE_COUNT}[query]
        self.items = [_Selected(object()) for _ in range(hits)]

    def Add(self, value: Any) -> None:  # noqa: N802 - COM method name
        self.items.append(_Selected(value))

    def Delete(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("Inspection must never delete.")


def _part(
    parameters_collection_factory: Any,
    length_parameter_factory: Any,
    up_to_date: bool = True,
    selection: Any = "default",
) -> Part:
    """Builds a Part with one user parameter and one feature-internal dimension."""
    width = length_parameter_factory(name="Housing\\Width", value=WIDTH_MM)
    internal = length_parameter_factory(name="Housing\\Base\\FirstLimit\\Length", value=12.0)
    parameters = parameters_collection_factory(
        [("Housing\\Width", width), ("Housing\\Base\\FirstLimit\\Length", internal)],
        direct_items=[("Housing\\Width", width)],
    )
    if selection == "default":
        selection = _Selection()
    return Part(_RawPart(parameters, up_to_date), selection=selection)


def test_summary_reports_what_the_model_contains(
    parameters_collection_factory: Any, length_parameter_factory: Any
) -> None:
    """Name, rebuild status, features, sketches and user parameters, as data."""
    summary = _part(parameters_collection_factory, length_parameter_factory).inspect.summary()

    assert isinstance(summary, PartSummary)
    assert summary.name == "Housing"
    assert summary.up_to_date is True
    assert summary.sketches == ("BaseSketch", "BoreSketch")
    assert [parameter.short_name for parameter in summary.parameters] == ["Width"]
    assert summary.parameters[0].value == WIDTH_MM
    assert [body.name for body in summary.bodies] == ["PartBody", "Tool"]
    assert [geometrical_set.name for geometrical_set in summary.geometrical_sets] == [
        "Construction"
    ]
    assert summary.topology == TopologyCounts(edges=EDGE_COUNT, faces=FACE_COUNT)


def test_features_keep_model_tree_order_and_their_real_kind(
    parameters_collection_factory: Any, length_parameter_factory: Any
) -> None:
    """A feature the SDK cannot create is still listed, with its real kind."""
    features = _part(parameters_collection_factory, length_parameter_factory).inspect.features()

    assert features == (
        FeatureInfo(name="Base", kind="Pad", supported=True),
        FeatureInfo(name="Bore", kind="Pocket", supported=True),
        FeatureInfo(name="Draft.1", kind="Draft", supported=False),
    )


def test_bodies_mark_the_main_body_by_identity(
    parameters_collection_factory: Any, length_parameter_factory: Any
) -> None:
    """Every body is listed; `part_design` handles only the main body's features."""
    part = _part(parameters_collection_factory, length_parameter_factory)

    main, tool = part.inspect.bodies()

    assert main == BodyInfo(
        name="PartBody",
        is_main=True,
        features=part.inspect.features(),
        sketches=("BaseSketch", "BoreSketch"),
    )
    assert tool == BodyInfo(
        name="Tool",
        is_main=False,
        features=(FeatureInfo(name="ToolPad", kind="Pad", supported=False),),
        sketches=(),
    )


def test_a_body_sharing_the_main_body_name_is_not_the_main_body(
    parameters_collection_factory: Any, length_parameter_factory: Any
) -> None:
    """The main body is found by COM identity, never by name."""
    part = _part(parameters_collection_factory, length_parameter_factory)
    part.com_object.tool_body.Name = "PartBody"

    assert [body.is_main for body in part.inspect.bodies()] == [True, False]


def test_geometrical_sets_list_their_elements_and_count_nested_sets(
    parameters_collection_factory: Any, length_parameter_factory: Any
) -> None:
    """Nested sets are counted, not opened: their contents are not live-verified."""
    part = _part(parameters_collection_factory, length_parameter_factory)

    assert part.inspect.geometrical_sets() == (
        GeometricalSetInfo(
            name="Construction",
            elements=(GeometryInfo(name="Offset.1", kind="HybridShapePlaneOffset"),),
            nested_set_count=NESTED_SET_COUNT,
        ),
    )


def test_topology_is_absent_without_an_editor_selection(
    parameters_collection_factory: Any, length_parameter_factory: Any
) -> None:
    """A Part built without a selection cannot search; the field is absent, not guessed."""
    part = _part(parameters_collection_factory, length_parameter_factory, selection=None)

    assert part.inspect.summary().topology is None


def test_feature_dimensions_are_not_reported_as_parameters(
    parameters_collection_factory: Any, length_parameter_factory: Any
) -> None:
    """Every feature exposes its own dimensions; they are not the model's parameters."""
    parameters = _part(parameters_collection_factory, length_parameter_factory).inspect.parameters()

    assert all("FirstLimit" not in parameter.name for parameter in parameters)


def test_an_unrebuilt_model_is_reported_as_needing_an_update(
    parameters_collection_factory: Any, length_parameter_factory: Any
) -> None:
    """Rebuild status is passed through as data, not interpreted."""
    part = _part(parameters_collection_factory, length_parameter_factory, up_to_date=False)

    assert part.inspect.summary().up_to_date is False


def test_inspection_changes_nothing(
    parameters_collection_factory: Any, length_parameter_factory: Any
) -> None:
    """No generation advance, no rebuild or save, and the user's pick is still selected."""
    selection = _Selection()
    part = _part(parameters_collection_factory, length_parameter_factory, selection=selection)

    part.inspect.summary()

    assert part.part_design.snapshot_generation == 0
    assert [item.Value for item in selection.items] == [selection.user_pick]


def test_render_is_readable_text_built_from_the_data(
    parameters_collection_factory: Any, length_parameter_factory: Any
) -> None:
    """Rendering sits on top of the data and says which kinds the SDK cannot handle."""
    text = _part(parameters_collection_factory, length_parameter_factory).inspect.summary().render()

    assert text.splitlines()[0] == "Part: Housing"
    assert "Update status: up to date" in text
    assert "- Base (Pad)" in text
    assert "- Draft.1 (Draft, not supported by auto-3dx)" in text
    assert "- Width = 60.0 mm" in text
    assert "- PartBody (main body, 3 features, 2 sketches)" in text
    assert "- Construction (1 elements, 1 nested sets not listed)" in text
    assert "  - Offset.1 (HybridShapePlaneOffset)" in text
    assert text.splitlines()[-1] == "Topology: 3 edges, 2 faces"


def test_a_com_failure_while_listing_features_is_an_automation_error(
    parameters_collection_factory: Any, length_parameter_factory: Any
) -> None:
    """A failed read surfaces as CATIA's failure, with the cause kept."""
    part = _part(parameters_collection_factory, length_parameter_factory)

    class _FailingBody:
        @property
        def Shapes(self) -> Any:  # noqa: N802 - COM property name
            raise pywintypes.com_error(
                HRESULT_EXCEPTION_OCCURRED, "Exception occurred.", None, None
            )

    part.com_object.MainBody = _FailingBody()

    with pytest.raises(AutomationError) as caught:
        part.inspect.features()

    assert caught.value.hresult == HRESULT_EXCEPTION_OCCURRED


def test_a_com_failure_while_listing_geometrical_sets_is_an_automation_error(
    parameters_collection_factory: Any, length_parameter_factory: Any
) -> None:
    """The new reads translate COM failures exactly like the old ones."""
    part = _part(parameters_collection_factory, length_parameter_factory)

    class _FailingCollection:
        @property
        def Count(self) -> int:  # noqa: N802 - COM property name
            raise pywintypes.com_error(
                HRESULT_EXCEPTION_OCCURRED, "Exception occurred.", None, None
            )

    part.com_object.HybridBodies = _FailingCollection()

    with pytest.raises(AutomationError, match="Part.HybridBodies.Count") as caught:
        part.inspect.geometrical_sets()

    assert caught.value.hresult == HRESULT_EXCEPTION_OCCURRED


def test_the_inspector_is_cached_on_the_part(
    parameters_collection_factory: Any, length_parameter_factory: Any
) -> None:
    """One inspector per Part, like every other namespace on it."""
    part = _part(parameters_collection_factory, length_parameter_factory)

    assert part.inspect is part.inspect
