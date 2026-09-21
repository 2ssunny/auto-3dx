"""Pins `part.inspect` classification to the kinds `part.part_design` really handles.

Discovery Pass 3 found circular patterns and booleans reported as unsupported even though
`part_design` created and found them. The two lists had drifted apart, so this test ties
them together: every kind a `part_design` lookup filters `Body.Shapes` by must be reported
as supported, and a kind the SDK does not handle must still be reported as unsupported.
"""

from typing import Any

import pytest

from auto_3dx.core.part import Part
from auto_3dx.geometry import part_design
from auto_3dx.inspect import SUPPORTED_FEATURE_KINDS

HANDLED_KINDS = {
    part_design.PAD_KIND,
    part_design.POCKET_KIND,
    part_design.SHAFT_KIND,
    part_design.GROOVE_KIND,
    part_design.RIB_KIND,
    part_design.SLOT_KIND,
    part_design.MIRROR_KIND,
    part_design.RECTANGULAR_PATTERN_KIND,
    part_design.CIRCULAR_PATTERN_KIND,
    part_design.EDGE_FILLET_KIND,
    part_design.CHAMFER_KIND,
    part_design.SHELL_KIND,
    part_design.THICKNESS_KIND,
    part_design.HOLE_KIND,
    part_design.MULTI_SECTION_SOLID_KIND,
    *part_design.BOOLEAN_KINDS,
}


class _Items:
    def __init__(self, items: "list[Any]") -> None:
        self.items = items

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self.items)

    def Item(self, index: int) -> Any:  # noqa: N802 - COM method name
        return self.items[index - 1]


def _raw_feature(kind: str, name: str) -> Any:
    """A fake feature whose COM wrapper type name is `kind`, as CATIA reports it."""
    return type(kind, (), {"Name": name})()


class _RawBody:
    def __init__(self, shapes: "list[Any]") -> None:
        self.Name = "PartBody"
        self.Shapes = _Items(shapes)
        self.Sketches = _Items([])
        self.HybridBodies = _Items([])


class _Part:
    def __init__(self, shapes: "list[Any]") -> None:
        self.Name = "3D Shape1"
        self.MainBody = _RawBody(shapes)
        self.Bodies = _Items([self.MainBody])
        self.HybridBodies = _Items([])
        self.InWorkObject = self.MainBody

    def IsUpToDate(self, item: Any) -> bool:  # noqa: N802 - COM method name
        return True


def test_every_kind_part_design_handles_is_reported_as_supported() -> None:
    assert HANDLED_KINDS <= SUPPORTED_FEATURE_KINDS


def test_nothing_is_reported_as_supported_that_part_design_does_not_handle() -> None:
    assert SUPPORTED_FEATURE_KINDS <= HANDLED_KINDS


@pytest.mark.parametrize(
    "kind",
    [
        part_design.CIRCULAR_PATTERN_KIND,
        part_design.BOOLEAN_REMOVE_KIND,
        part_design.BOOLEAN_ADD_KIND,
        part_design.BOOLEAN_INTERSECT_KIND,
        part_design.BOOLEAN_ASSEMBLE_KIND,
    ],
)
def test_phase_3_kinds_are_supported_in_a_summary(kind: str) -> None:
    """The regression Discovery Pass 3 found."""
    part = Part(_Part([_raw_feature(kind, "F1")]))

    features = part.inspect.features()

    assert [(feature.kind, feature.supported) for feature in features] == [(kind, True)]


def test_an_unknown_kind_is_still_reported_as_unsupported() -> None:
    part = Part(_Part([_raw_feature("Draft", "Draft.1"), _raw_feature("Pad", "Pad.1")]))

    features = part.inspect.features()

    assert [(feature.kind, feature.supported) for feature in features] == [
        ("Draft", False),
        ("Pad", True),
    ]
