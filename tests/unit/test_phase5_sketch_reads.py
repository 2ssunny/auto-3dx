"""Phase 5: reading a sketch back -- element geometry, construction, constraints, the frame.

The fakes answer exactly as probes 46a-46h, 46ab and 46ac measured, with the edition closed:

    Line2D.GetEndPoints(seed4)   -> (x1, y1, x2, y2)
    Circle2D.GetCenter(seed2)    -> (cx, cy); Radius; GetEndPoints equal for a closed circle
    Point2D.GetCoordinates(seed2)-> (x, y)
    Construction                 -> bool
    Constraint.Mode              -> 0 driving
    GetConstraintElement(i).DisplayName -> the constrained element's name

and every read is refused while the sketch's edition is open (probe 46 hung CATIA there).
"""

import math
from typing import Any

import pytest

from auto_3dx.errors import (
    AutomationError,
    ParameterTypeError,
    UnsupportedOperationError,
    ValidationError,
)
from auto_3dx.geometry.constraint import Constraint
from auto_3dx.geometry.sketch import Sketch, SketchElement
from auto_3dx.geometry.sketch_geometry import (
    CircleGeometry,
    LineGeometry,
    PointGeometry,
    SketchFrame,
)
from tests.conftest import make_com_error


class Line2D:  # noqa: N801 - the SDK identifies elements by CATIA's type name
    def __init__(self, name: str, x1: float, y1: float, x2: float, y2: float) -> None:
        self.Name = name
        self.Construction = False
        self._points = (x1, y1, x2, y2)
        self.reads: "list[str]" = []

    def GetEndPoints(self, seed: Any) -> Any:  # noqa: N802 - COM method name
        assert list(seed) == [0.0] * 4, "GetEndPoints needs its four-number seed"
        self.reads.append("GetEndPoints")
        return self._points


class Circle2D:  # noqa: N801
    def __init__(
        self, name: str, cx: float, cy: float, r: float, arc: "tuple | None" = None
    ) -> None:
        self.Name = name
        self.Construction = False
        self.Radius = r
        self._center = (cx, cy)
        start = (cx + r, cy)
        self._ends = arc if arc is not None else (*start, start[0], start[1] - 2e-15)

    def GetCenter(self, seed: Any) -> Any:  # noqa: N802
        if list(seed) != [0.0, 0.0]:
            raise make_com_error()  # probe 43: no seed -> COM error
        return self._center

    def GetEndPoints(self, seed: Any) -> Any:  # noqa: N802
        return self._ends


class Point2D:  # noqa: N801
    def __init__(self, name: str, x: float, y: float) -> None:
        self.Name = name
        self.Construction = True
        self._xy = (x, y)

    def GetCoordinates(self, seed: Any) -> Any:  # noqa: N802
        return self._xy


class Axis2D:  # noqa: N801
    def __init__(self) -> None:
        self.Name = "AbsoluteAxis"

    def GetEndPoints(self, seed: Any) -> Any:  # noqa: N802
        raise AssertionError("an element without verified reads must never be read")


class _Reference:
    def __init__(self, name: str) -> None:
        self.DisplayName = name


class _Dimension:
    def __init__(self, value: float) -> None:
        self.Value = value


class _RawConstraint:
    def __init__(
        self,
        name: str,
        type_code: int,
        elements: "list[str]",
        value: "float | None" = None,
        mode: int = 0,
    ) -> None:
        self.Name = name
        self.Type = type_code
        self.Status = 0
        self.Mode = mode
        self._elements = elements
        self._value = value

    @property
    def Dimension(self) -> Any:  # noqa: N802
        if self._value is None:
            raise make_com_error()
        return _Dimension(self._value)

    def GetConstraintElement(self, position: int) -> Any:  # noqa: N802
        return _Reference(self._elements[position - 1])


class _Items:
    def __init__(self, items: "list[Any]") -> None:
        self.items = items

    @property
    def Count(self) -> int:  # noqa: N802
        return len(self.items)

    def Item(self, key: Any) -> Any:  # noqa: N802
        if isinstance(key, str):
            for item in self.items:
                if item.Name == key:
                    return item
            raise make_com_error()
        return self.items[key - 1]


class _Factory:
    def __init__(self, owner: "_RawSketch") -> None:
        self._owner = owner

    def CreateLine(self, x1: float, y1: float, x2: float, y2: float) -> Line2D:  # noqa: N802
        line = Line2D(f"Line.{len(self._owner.GeometricElements.items)}", x1, y1, x2, y2)
        self._owner.GeometricElements.items.append(line)
        return line


class _RawSketch:
    def __init__(
        self,
        elements: "list[Any]",
        constraints: "list[Any]",
        axis: "tuple[float, ...]" = (0, 0, 20, 1, 0, 0, 0, 1, 0),
    ) -> None:
        self.Name = "PROFILE"
        self.GeometricElements = _Items([Axis2D(), *elements])
        self.Constraints = _Items(constraints)
        self._axis = axis
        self.edition_open = False

    def GetAbsoluteAxisData(self, seed: Any) -> Any:  # noqa: N802
        return self._axis

    def OpenEdition(self) -> Any:  # noqa: N802
        self.edition_open = True
        return _Factory(self)

    def CloseEdition(self) -> None:  # noqa: N802
        self.edition_open = False


def _sketch() -> "tuple[Sketch, _RawSketch]":
    line = Line2D("Line.1", 10.0, 5.0, 40.0, 25.0)
    circle = Circle2D("Circle.1", 20.0, 15.0, 4.0)
    arc = Circle2D("Circle.2", -20.0, -10.0, 6.0, arc=(-14.0, -10.0, -20.0, -4.0))
    point = Point2D("Point.1", -5.0, 7.5)
    constraints = [
        _RawConstraint("Length.1", 5, ["Line.1"], value=36.06),
        _RawConstraint("Perpendicularity.1", 11, ["Line.1", "Line.2"]),
    ]
    raw = _RawSketch([line, circle, arc, point], constraints)
    return Sketch(raw), raw


# --- element geometry ----------------------------------------------------------------------


def test_a_line_reads_its_end_points_as_plain_values() -> None:
    sketch, _ = _sketch()

    geometry = sketch.get_element("Line.1").geometry()

    assert geometry == LineGeometry(start=(10.0, 5.0), end=(40.0, 25.0))
    assert geometry.length_mm == pytest.approx(math.hypot(30, 20))


def test_a_closed_circle_and_an_arc_are_told_apart_by_their_end_points() -> None:
    sketch, _ = _sketch()

    circle = sketch.get_element("Circle.1").geometry()
    arc = sketch.get_element("Circle.2").geometry()

    assert isinstance(circle, CircleGeometry)
    assert (circle.center, circle.radius_mm, circle.is_closed) == ((20.0, 15.0), 4.0, True)
    assert (arc.center, arc.is_closed, arc.start, arc.end) == (
        (-20.0, -10.0),
        False,
        (-14.0, -10.0),
        (-20.0, -4.0),
    )


def test_a_point_reads_its_position() -> None:
    sketch, _ = _sketch()

    assert sketch.get_element("Point.1").geometry() == PointGeometry(position=(-5.0, 7.5))


def test_an_element_without_verified_reads_is_refused_before_any_read() -> None:
    sketch, _ = _sketch()

    with pytest.raises(UnsupportedOperationError, match="Axis2D"):
        sketch.get_element("AbsoluteAxis").geometry()


def test_construction_is_read_back() -> None:
    sketch, _ = _sketch()

    assert sketch.get_element("Line.1").is_construction is False
    assert sketch.get_element("Point.1").is_construction is True


def test_a_malformed_answer_is_an_automation_error() -> None:
    class Line2D:  # noqa: N801
        Name = "Line.9"

        def GetEndPoints(self, seed: Any) -> Any:  # noqa: N802
            return (1.0, 2.0)

    with pytest.raises(AutomationError, match="unexpected shape"):
        SketchElement(Line2D()).geometry()


def test_a_com_failure_is_an_automation_error() -> None:
    class Point2D:  # noqa: N801
        def GetCoordinates(self, seed: Any) -> Any:  # noqa: N802
            raise make_com_error()

    with pytest.raises(AutomationError):
        SketchElement(Point2D()).geometry()


# --- the open-edition guard ------------------------------------------------------------------


def test_reads_are_refused_while_the_edition_is_open_and_allowed_after() -> None:
    sketch, raw = _sketch()

    with sketch.edit() as editor:
        line = editor.line(0.0, 0.0, 30.0, 0.0)
        with pytest.raises(ValidationError, match="open for editing"):
            line.geometry()
        with pytest.raises(ValidationError, match="open for editing"):
            _ = line.is_construction
        with pytest.raises(ValidationError, match="open for editing"):
            sketch.get_element("Line.1").geometry()
        with pytest.raises(ValidationError, match="edit"):
            sketch.geometry()
        assert line.com_object.reads == []

    assert line.geometry() == LineGeometry(start=(0.0, 0.0), end=(30.0, 0.0))


# --- constraints -------------------------------------------------------------------------------


def test_a_constraint_reports_its_mode_and_the_elements_it_acts_on() -> None:
    constraint = Constraint(_RawConstraint("Perpendicularity.1", 11, ["Line.1", "Line.2"]))

    assert constraint.mode == "driving"
    assert Constraint(_RawConstraint("X", 5, ["Line.1"], mode=1)).mode == "driven"
    assert (constraint.element_name(1), constraint.element_name(2)) == ("Line.1", "Line.2")
    assert constraint.element_name() == "Line.1"


@pytest.mark.parametrize("position", [0, 3, True, "1"])
def test_an_unverified_element_position_is_refused(position: Any) -> None:
    with pytest.raises(ParameterTypeError):
        Constraint(_RawConstraint("X", 5, ["Line.1"])).element_name(position)


def test_an_unknown_mode_is_an_automation_error() -> None:
    with pytest.raises(AutomationError, match="Mode"):
        _ = Constraint(_RawConstraint("X", 5, ["Line.1"], mode=7)).mode


# --- the frame and the whole-sketch read -------------------------------------------------------


def test_the_frame_maps_local_points_into_the_part_and_back() -> None:
    # The side-face frame probe 46j read: origin at a corner, X along +Y, Y along +Z.
    frame = SketchFrame.from_axis_data((30, -20, 0, 0, 1, 0, 0, 0, 1))

    assert frame.normal == pytest.approx((1.0, 0.0, 0.0))
    assert frame.to_global((10.0, 5.0)) == pytest.approx((30.0, -10.0, 5.0))
    assert frame.to_local((30.0, -10.0, 5.0)) == pytest.approx((10.0, 5.0))
    assert frame.distance_from_plane((32.0, 0.0, 0.0)) == pytest.approx(2.0)
    assert frame.normal_parallel_to((1.0, 0.0, 0.0)) == 1
    assert frame.normal_parallel_to((-1.0, 0.0, 0.0)) == -1
    assert frame.normal_parallel_to((0.0, 0.0, 1.0)) is None


def test_a_frame_needs_nine_numbers() -> None:
    with pytest.raises(ValueError):
        SketchFrame.from_axis_data((0, 0, 0))


def test_sketch_frame_reads_the_axis_data() -> None:
    sketch, _ = _sketch()

    assert sketch.frame().origin == (0.0, 0.0, 20.0)
    assert sketch.frame().normal == pytest.approx((0.0, 0.0, 1.0))


def test_sketch_geometry_reports_everything_as_plain_values_without_guessing() -> None:
    sketch, _ = _sketch()

    result = sketch.geometry()

    assert [line.name for line in result.lines] == ["Line.1"]
    assert [circle.name for circle in result.circles] == ["Circle.1", "Circle.2"]
    assert [point.name for point in result.points] == ["Point.1"]
    assert result.other_elements == (("AbsoluteAxis", "Axis2D"),)
    assert result.profile_lines == result.lines
    assert result.profile_circles == result.circles
    first, second = result.constraints
    assert (first.name, first.type_code, first.mode, first.value, first.first_element) == (
        "Length.1",
        5,
        "driving",
        36.06,
        "Line.1",
    )
    assert (second.value, second.first_element) == (None, "Line.1")
    assert result.frame.origin == (0.0, 0.0, 20.0)


def test_sketch_geometry_contains_no_com_objects() -> None:
    sketch, _ = _sketch()

    result = sketch.geometry()

    def walk(value: Any) -> None:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return
        if isinstance(value, tuple):
            for item in value:
                walk(item)
            return
        assert type(value).__module__.startswith("auto_3dx.geometry.sketch_geometry"), value
        for item in vars(value).values():
            walk(item)

    walk(result)
