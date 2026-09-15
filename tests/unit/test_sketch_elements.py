"""Unit tests for `auto_3dx.geometry.sketch.SketchElement`.

Pins the API change closing the raw-COM leak documented as transitional in
`docs/api-design.md` section 9: `SketchEditor.point`/`line`/`circle`/`arc`/
`spline` now return a `SketchElement` (and `rectangle` a list of four), and
every consumer that used to take a raw 2D COM object -- `set_construction`,
the constraint methods (`_mono`/`_bi`), and `Sketch.set_center_line` -- now
accepts either a `SketchElement` or the raw object itself, unwrapping through
the module-private `_resolve_element` helper.

CATIA is never contacted here. Every COM object is a small, self-contained
fake identified purely by `type(obj).__name__` (`docs/conventions.md` section
4), built specifically for this module rather than reusing `tests/conftest.py`
or other test modules' fakes.
"""

from typing import Any

import pytest

from auto_3dx._generation import ModelGeneration
from auto_3dx.errors import ValidationError
from auto_3dx.geometry.constraint import CONSTRAINT_HORIZONTAL, CONSTRAINT_PARALLEL
from auto_3dx.geometry.sketch import Sketch, SketchEditor, SketchElement

SKETCH_NAME = "AUTO3DX_ELEMENT_SKETCH"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class Point2D:
    """Fake CATIA `Point2D`, as returned by `Factory2D.CreatePoint`."""

    def __init__(self, x: float, y: float) -> None:
        self.X, self.Y = x, y


class Line2D:
    """Fake CATIA `Line2D`, as returned by `Factory2D.CreateLine`."""

    def __init__(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.X1, self.Y1, self.X2, self.Y2 = x1, y1, x2, y2
        self.Construction = False


class Circle2D:
    """Fake CATIA `Circle2D`, as returned by `CreateClosedCircle`/`CreateCircle`."""

    def __init__(self, center_x: float, center_y: float, radius: float) -> None:
        self.CenterX, self.CenterY, self.Radius = center_x, center_y, radius
        self.Construction = False


class ControlPoint2D:
    """Fake CATIA `ControlPoint2D`, as returned by `CreateControlPoint`."""

    def __init__(self, x: float, y: float) -> None:
        self.X, self.Y = x, y


class Spline2D:
    """Fake CATIA `Spline2D`, as returned by `CreateSpline`."""

    def __init__(self, poles: "list[Any]") -> None:
        self.poles: list[Any] = list(poles)
        self.Construction = False


class Factory2D:
    """Fake CATIA `Factory2D`, as returned by `Sketch.OpenEdition()`.

    Records every call so a test can assert exactly what reached COM.
    """

    def __init__(self) -> None:
        self.point_calls: list[tuple[float, float]] = []
        self.line_calls: list[tuple[float, float, float, float]] = []
        self.circle_calls: list[tuple[float, float, float]] = []
        self.arc_calls: list[tuple[float, float, float, float, float]] = []
        self.control_point_calls: list[tuple[float, float]] = []
        self.spline_calls: list[list[Any]] = []

    def CreatePoint(self, iX: float, iY: float) -> Point2D:
        self.point_calls.append((iX, iY))
        return Point2D(iX, iY)

    def CreateLine(self, iX1: float, iY1: float, iX2: float, iY2: float) -> Line2D:
        self.line_calls.append((iX1, iY1, iX2, iY2))
        return Line2D(iX1, iY1, iX2, iY2)

    def CreateClosedCircle(self, iCx: float, iCy: float, iR: float) -> Circle2D:
        self.circle_calls.append((iCx, iCy, iR))
        return Circle2D(iCx, iCy, iR)

    def CreateCircle(
        self, iCx: float, iCy: float, iR: float, iStart: float, iEnd: float
    ) -> Circle2D:
        self.arc_calls.append((iCx, iCy, iR, iStart, iEnd))
        return Circle2D(iCx, iCy, iR)

    def CreateControlPoint(self, iX: float, iY: float) -> ControlPoint2D:
        self.control_point_calls.append((iX, iY))
        return ControlPoint2D(iX, iY)

    def CreateSpline(self, iPoles: "list[Any]") -> Spline2D:
        self.spline_calls.append(list(iPoles))
        return Spline2D(iPoles)


class Constraint:
    """Fake CATIA sketch `Constraint`, as returned by `AddMonoEltCst`/`AddBiEltCst`."""

    def __init__(self, name: str, type_code: int) -> None:
        self.Name = name
        self.Type = type_code
        self.Status = 0


class Constraints:
    """Fake CATIA `Constraints` collection (`Sketch.Constraints`).

    Records every call, by exact argument identity, so a test can pin that
    the RAW element -- never a `SketchElement` wrapper -- reaches COM.
    """

    def __init__(self) -> None:
        self.mono_calls: list[tuple[int, Any]] = []
        self.bi_calls: list[tuple[int, Any, Any]] = []
        self._count = 0

    def AddMonoEltCst(self, iCstType: int, iElem: Any) -> Constraint:
        self.mono_calls.append((iCstType, iElem))
        self._count += 1
        return Constraint(f"Constraint.{self._count}", iCstType)

    def AddBiEltCst(self, iCstType: int, iFirst: Any, iSecond: Any) -> Constraint:
        self.bi_calls.append((iCstType, iFirst, iSecond))
        self._count += 1
        return Constraint(f"Constraint.{self._count}", iCstType)


class FakeSketch:
    """Fake CATIA `Sketch`.

    `__eq__` models COM identity (verified for sketches,
    `docs/conventions.md` 1.2): two distinct Python objects sharing the same
    `_identity` compare equal, exactly as `==` on two wrappers for the same
    real CATIA sketch would. `another_wrapper()` builds such a second,
    distinct object, the way COM hands out a fresh dispatch wrapper on a
    second lookup of the same underlying sketch.
    """

    def __init__(self, name: str = "Sketch.1", identity: Any = None) -> None:
        self._identity = identity if identity is not None else object()
        self._name = name
        self.factory2d = Factory2D()
        self.Constraints = Constraints()
        self.CenterLine: Any = None
        self.open_edition_calls = 0
        self.close_edition_calls = 0

    @property
    def Name(self) -> str:
        return self._name

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FakeSketch):
            return NotImplemented
        return other._identity is self._identity

    def __hash__(self) -> int:
        return id(self._identity)

    def another_wrapper(self) -> "FakeSketch":
        """Returns a DISTINCT object standing in for the same underlying sketch."""
        return FakeSketch(name=self._name, identity=self._identity)

    def OpenEdition(self) -> Factory2D:
        self.open_edition_calls += 1
        return self.factory2d

    def CloseEdition(self) -> None:
        self.close_edition_calls += 1


def _sketch(name: str = SKETCH_NAME, generation: ModelGeneration | None = None) -> Sketch:
    """Builds a `Sketch` wrapper over a fresh `FakeSketch`."""
    shared = generation if generation is not None else ModelGeneration()
    return Sketch(FakeSketch(name=name), shared)


# ---------------------------------------------------------------------------
# 1. Every geometry method returns a SketchElement with the right com_object
#    and kind; rectangle() returns four.
# ---------------------------------------------------------------------------


def test_point_returns_a_sketch_element_with_the_right_com_object_and_kind() -> None:
    sketch = _sketch()

    with sketch.edit() as editor:
        element = editor.point(1.0, 2.0)

    assert isinstance(element, SketchElement)
    assert element.kind == "Point2D"
    assert element.com_object.X == 1.0
    assert element.com_object.Y == 2.0


def test_line_returns_a_sketch_element_with_the_right_com_object_and_kind() -> None:
    sketch = _sketch()

    with sketch.edit() as editor:
        element = editor.line(0.0, 0.0, 10.0, 0.0)

    assert isinstance(element, SketchElement)
    assert element.kind == "Line2D"
    assert (element.com_object.X1, element.com_object.Y1) == (0.0, 0.0)
    assert (element.com_object.X2, element.com_object.Y2) == (10.0, 0.0)


def test_circle_returns_a_sketch_element_with_the_right_com_object_and_kind() -> None:
    sketch = _sketch()

    with sketch.edit() as editor:
        element = editor.circle(0.0, 0.0, 5.0)

    assert isinstance(element, SketchElement)
    assert element.kind == "Circle2D"
    assert element.com_object.Radius == 5.0


def test_arc_returns_a_sketch_element_with_the_right_com_object_and_kind() -> None:
    sketch = _sketch()

    with sketch.edit() as editor:
        element = editor.arc(0.0, 0.0, 5.0, 0.0, 3.14159)

    assert isinstance(element, SketchElement)
    assert element.kind == "Circle2D"
    assert element.com_object.Radius == 5.0


def test_spline_returns_a_sketch_element_with_the_right_com_object_and_kind() -> None:
    sketch = _sketch()

    with sketch.edit() as editor:
        element = editor.spline([(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)])

    assert isinstance(element, SketchElement)
    assert element.kind == "Spline2D"
    assert len(element.com_object.poles) == 3


def test_rectangle_returns_four_sketch_elements() -> None:
    sketch = _sketch()

    with sketch.edit() as editor:
        elements = editor.rectangle(60.0, 40.0)

    assert len(elements) == 4
    assert all(isinstance(element, SketchElement) for element in elements)
    assert all(element.kind == "Line2D" for element in elements)


# ---------------------------------------------------------------------------
# 2. Every consumer accepts a SketchElement and a raw COM object alike, and
#    always passes the RAW object to COM.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("as_wrapper", [True, False])
def test_set_construction_accepts_a_wrapper_and_a_raw_object_alike(as_wrapper: bool) -> None:
    sketch = _sketch()

    with sketch.edit() as editor:
        circle = editor.circle(0.0, 0.0, 5.0)
        target = circle if as_wrapper else circle.com_object
        editor.set_construction(target, True)

    # The write always lands on the raw object, wrapped or not.
    assert circle.com_object.Construction is True


@pytest.mark.parametrize("as_wrapper", [True, False])
def test_horizontal_accepts_a_wrapper_and_a_raw_object_alike_and_passes_the_raw_line(
    as_wrapper: bool,
) -> None:
    sketch = _sketch()

    with sketch.edit() as editor:
        line = editor.line(0.0, 0.0, 10.0, 0.0)
        target = line if as_wrapper else line.com_object
        editor.horizontal(target)

    fake_constraints: Constraints = sketch.com_object.Constraints
    assert fake_constraints.mono_calls == [(CONSTRAINT_HORIZONTAL, line.com_object)]


@pytest.mark.parametrize("as_wrapper", [True, False])
def test_parallel_accepts_a_wrapper_and_a_raw_object_alike_and_passes_both_raw_lines(
    as_wrapper: bool,
) -> None:
    sketch = _sketch()

    with sketch.edit() as editor:
        first = editor.line(0.0, 0.0, 10.0, 0.0)
        second = editor.line(0.0, 5.0, 10.0, 5.0)
        first_arg = first if as_wrapper else first.com_object
        second_arg = second if as_wrapper else second.com_object
        editor.parallel(first_arg, second_arg)

    fake_constraints: Constraints = sketch.com_object.Constraints
    assert fake_constraints.bi_calls == [
        (CONSTRAINT_PARALLEL, first.com_object, second.com_object)
    ]


@pytest.mark.parametrize("as_wrapper", [True, False])
def test_set_center_line_accepts_a_wrapper_and_a_raw_object_alike(as_wrapper: bool) -> None:
    fake_sketch = FakeSketch(name="Sketch.1")
    sketch = Sketch(fake_sketch, ModelGeneration())

    with sketch.edit() as editor:
        axis = editor.line(0.0, 0.0, 0.0, 20.0)

    target = axis if as_wrapper else axis.com_object
    sketch.set_center_line(target)

    assert fake_sketch.CenterLine is axis.com_object


# ---------------------------------------------------------------------------
# 3. An element from a different sketch is refused before any COM call.
# ---------------------------------------------------------------------------


def test_set_construction_refuses_an_element_from_a_different_sketch_before_com() -> None:
    sketch_a = _sketch("A")
    sketch_b = _sketch("B")

    with sketch_a.edit() as editor_a:
        foreign = editor_a.circle(0.0, 0.0, 5.0)

    with sketch_b.edit() as editor_b:
        with pytest.raises(ValidationError, match="different sketch"):
            editor_b.set_construction(foreign)

    # Refused before COM: the flag on the foreign element is untouched.
    assert foreign.com_object.Construction is False


def test_horizontal_refuses_an_element_from_a_different_sketch_before_com() -> None:
    sketch_a = _sketch("A")
    sketch_b = _sketch("B")

    with sketch_a.edit() as editor_a:
        foreign = editor_a.line(0.0, 0.0, 10.0, 0.0)

    with sketch_b.edit() as editor_b:
        with pytest.raises(ValidationError, match="different sketch"):
            editor_b.horizontal(foreign)

    assert sketch_b.com_object.Constraints.mono_calls == []


def test_parallel_refuses_an_element_from_a_different_sketch_before_com() -> None:
    sketch_a = _sketch("A")
    sketch_b = _sketch("B")

    with sketch_a.edit() as editor_a:
        foreign = editor_a.line(0.0, 0.0, 10.0, 0.0)

    with sketch_b.edit() as editor_b:
        local = editor_b.line(0.0, 0.0, 0.0, 10.0)
        with pytest.raises(ValidationError, match="different sketch"):
            editor_b.parallel(foreign, local)
        with pytest.raises(ValidationError, match="different sketch"):
            editor_b.parallel(local, foreign)

    assert sketch_b.com_object.Constraints.bi_calls == []


def test_set_center_line_refuses_an_element_from_a_different_sketch_before_com() -> None:
    sketch_a = _sketch("A")
    fake_sketch_b = FakeSketch(name="B")
    generation_b = ModelGeneration()
    sketch_b = Sketch(fake_sketch_b, generation_b)

    with sketch_a.edit() as editor_a:
        foreign = editor_a.line(0.0, 0.0, 0.0, 20.0)

    with pytest.raises(ValidationError, match="different sketch"):
        sketch_b.set_center_line(foreign)

    assert fake_sketch_b.CenterLine is None
    # --- 4. That refusal must not advance the generation: set_center_line
    #     is a mutation, but a rejection before COM is not one of its
    #     mutations (docs/api-design.md section 5.2).
    assert generation_b.value == 0


# ---------------------------------------------------------------------------
# 5. Two sketch COM objects comparing == count as the same sketch.
# ---------------------------------------------------------------------------


def test_element_is_accepted_by_a_different_wrapper_of_the_same_sketch() -> None:
    """COM hands out a fresh dispatch object per lookup; `==` must still match."""
    fake_sketch = FakeSketch(name="Sketch.1")
    sketch = Sketch(fake_sketch, ModelGeneration())

    with sketch.edit() as editor:
        line = editor.line(0.0, 0.0, 10.0, 0.0)

    other_com = fake_sketch.another_wrapper()
    assert other_com is not fake_sketch
    assert other_com == fake_sketch

    other_sketch = Sketch(other_com, ModelGeneration())
    # Must NOT raise: the element's owner (fake_sketch) compares equal to
    # other_sketch's own COM object (other_com), even though `is` would say
    # they differ.
    other_sketch.set_center_line(line)

    assert other_com.CenterLine is line.com_object


def test_editor_built_without_a_sketch_skips_the_ownership_check() -> None:
    """The compatibility path: no recorded owner means nothing is refused."""
    sketch_a = _sketch("A")
    with sketch_a.edit() as editor_a:
        foreign = editor_a.line(0.0, 0.0, 10.0, 0.0)

    bare_editor = SketchEditor(Factory2D(), Constraints())  # no generation, no sketch

    # Must NOT raise, even though `foreign` was drawn in a different sketch:
    # bare_editor has no recorded owner at all.
    bare_editor.set_construction(foreign)

    assert foreign.com_object.Construction is True
