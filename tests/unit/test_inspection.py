"""Tests for read-only inspection (`docs/api-design.md` section 11).

Inspection exists so a caller, especially an AI agent, can find out what a model
contains before changing it. Its value depends on three promises these tests pin: it
reports what is really there, including features the SDK cannot create; it returns
structured data rather than text; and it changes nothing -- no generation advance, no
rebuild, no save, and no contact with the user's selection.
"""

from typing import Any

import pytest
import pywintypes

from auto_3dx.core.part import Part
from auto_3dx.errors import AutomationError
from auto_3dx.inspect import FeatureInfo, PartSummary

HRESULT_EXCEPTION_OCCURRED = -2147352567
WIDTH_MM = 60.0


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


class _MainBody:
    """Fake `MainBody` with features and sketches."""

    def __init__(self, shapes: "list[Any]", sketches: "list[Any]") -> None:
        self.Shapes = _Collection(shapes)
        self.Sketches = _Collection(sketches)


class _RawPart:
    """Fake CATIA `Part` that fails the test if anything mutating is called."""

    def __init__(self, parameters: Any, up_to_date: bool = True) -> None:
        self.Name = "Housing"
        self.Parameters = parameters
        self.MainBody = _MainBody(
            [Pad("Base"), Pocket("Bore"), Draft("Draft.1")],
            [_SketchComObject("BaseSketch"), _SketchComObject("BoreSketch")],
        )
        self._up_to_date = up_to_date

    def IsUpToDate(self, target: Any) -> bool:  # noqa: N802 - COM method name
        return self._up_to_date

    def Update(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("Inspection must never rebuild the model.")

    def Save(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("Inspection must never save.")


class _UntouchableSelection:
    """Fake selection that fails the test on any use.

    The topology search behind edge and face counts clears the user's selection, so
    inspection deliberately does not use it.
    """

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"Inspection must not touch the selection (used {name}).")


def _part(
    parameters_collection_factory: Any,
    length_parameter_factory: Any,
    up_to_date: bool = True,
) -> Part:
    """Builds a Part with one user parameter and one feature-internal dimension."""
    width = length_parameter_factory(name="Housing\\Width", value=WIDTH_MM)
    internal = length_parameter_factory(name="Housing\\Base\\FirstLimit\\Length", value=12.0)
    parameters = parameters_collection_factory(
        [("Housing\\Width", width), ("Housing\\Base\\FirstLimit\\Length", internal)],
        direct_items=[("Housing\\Width", width)],
    )
    return Part(_RawPart(parameters, up_to_date), selection=_UntouchableSelection())


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
    """No generation advance; rebuild, save and selection use would fail the test."""
    part = _part(parameters_collection_factory, length_parameter_factory)

    part.inspect.summary()

    assert part.part_design.snapshot_generation == 0


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


def test_the_inspector_is_cached_on_the_part(
    parameters_collection_factory: Any, length_parameter_factory: Any
) -> None:
    """One inspector per Part, like every other namespace on it."""
    part = _part(parameters_collection_factory, length_parameter_factory)

    assert part.inspect is part.inspect
