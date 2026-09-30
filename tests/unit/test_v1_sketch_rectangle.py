"""v1 sketch ergonomics: shared-corner polygons, axis anchors and the "fully" rectangle.

The fakes follow probe 47i: `CreatePoint` per corner, `CreateLine` per side with its
`StartPoint`/`EndPoint` then set to the corner points, horizontal x2 / vertical x2 / two
lengths through `AddMonoEltCst`, and two `AddBiEltCst(distance, corner, AbsoluteAxis.*)`
anchors. `AbsoluteAxis` is read before `OpenEdition`, the order the probe used.
"""

from typing import Any

import pytest

from auto_3dx.errors import ParameterTypeError, ValidationError
from auto_3dx.geometry.constraint import CONSTRAINT_DISTANCE
from auto_3dx.geometry.sketch import (
    SKETCH_AXIS_HORIZONTAL,
    SKETCH_AXIS_VERTICAL,
    Sketch,
    SketchEditor,
)
from auto_3dx.highlevel import CONSTRAINTS_FULLY
from tests.conftest import Constraints, Factory2D
from tests.conftest import Sketch as FakeSketch


class _Axis:
    def __init__(self, log: "list[str]") -> None:
        self._log = log
        self.VerticalReference = object()
        self.HorizontalReference = object()


class _AxisSketch(FakeSketch):
    """The conftest sketch plus `AbsoluteAxis`, logging when it is read."""

    def __init__(self) -> None:
        super().__init__()
        self.order: "list[str]" = []
        self.axis = _Axis(self.order)

    @property
    def AbsoluteAxis(self) -> Any:  # noqa: N802
        self.order.append("AbsoluteAxis")
        return self.axis

    def OpenEdition(self) -> Any:  # noqa: N802
        self.order.append("OpenEdition")
        return super().OpenEdition()


def test_a_fully_constrained_rectangle_shares_its_corners_and_anchors_one() -> None:
    raw = _AxisSketch()

    profile = Sketch(raw).rectangle(60, 40, origin=(-30, -20), constraints=CONSTRAINTS_FULLY)

    assert raw.order == ["AbsoluteAxis", "OpenEdition"]
    assert raw.factory2d.point_calls == [(-30.0, -20.0), (30.0, -20.0), (30.0, 20.0), (-30.0, 20.0)]
    corners = [corner.com_object for corner in profile.corners]
    for index, line in enumerate(profile.lines):
        assert line.com_object.StartPoint is corners[index]
        assert line.com_object.EndPoint is corners[(index + 1) % 4]
    assert len(profile.constraints) == 8
    distance_calls = raw.Constraints.bi_calls
    assert distance_calls == [
        (CONSTRAINT_DISTANCE, corners[0], raw.axis.VerticalReference),
        (CONSTRAINT_DISTANCE, corners[0], raw.axis.HorizontalReference),
    ]
    assert profile.width_constraint is profile.constraints[4]
    assert profile.height_constraint is profile.constraints[5]
    assert profile.width_constraint.value == 60.0
    assert profile.height_constraint.value == 40.0
    assert raw.close_edition_calls == 1


def test_the_other_levels_share_no_corners() -> None:
    raw = FakeSketch()

    profile = Sketch(raw).rectangle(10, 5, constraints="dimensioned")

    assert profile.corners == ()
    assert profile.width_constraint is not None and profile.width_constraint.value == 10.0
    assert Sketch(FakeSketch()).rectangle(10, 5).width_constraint is None


def test_a_polygon_needs_three_corners_before_anything_is_drawn() -> None:
    factory = Factory2D()
    editor = SketchEditor(factory, Constraints())

    with pytest.raises(ParameterTypeError, match="at least 3"):
        editor.polygon([(0, 0), (1, 0)])
    with pytest.raises(ParameterTypeError, match="corner"):
        editor.polygon([(0, 0), (1, 0), (1,)])  # type: ignore[list-item]
    assert factory.point_calls == [] and factory.line_calls == []

    points, lines = editor.polygon([(0, 0), (4, 0), (0, 3)])
    assert len(points) == len(lines) == 3
    assert lines[2].com_object.EndPoint is points[0].com_object


def test_an_axis_anchor_needs_a_known_axis_and_an_axis_to_constrain_against() -> None:
    editor = SketchEditor(Factory2D(), Constraints())
    point = editor.point(1, 2)

    with pytest.raises(ParameterTypeError, match="vertical"):
        editor.distance_to_axis(point, "x")
    with pytest.raises(ValidationError, match="Sketch.edit"):
        editor.distance_to_axis(point, SKETCH_AXIS_VERTICAL)

    axis = _Axis([])
    anchored = SketchEditor(Factory2D(), Constraints(), absolute_axis=axis)
    corner = anchored.point(0, 0)
    constraint = anchored.distance_to_axis(corner, SKETCH_AXIS_HORIZONTAL, 0.0)
    assert constraint.value == 0.0


def test_a_sketch_without_an_absolute_axis_still_opens() -> None:
    raw = FakeSketch()  # no AbsoluteAxis at all

    with Sketch(raw).edit() as editor:
        editor.line(0, 0, 1, 1)

    assert raw.close_edition_calls == 1
