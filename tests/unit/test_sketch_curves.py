"""Unit tests for curved 2D sketch geometry and its constraints.

Covers the additions to `auto_3dx.geometry.sketch.SketchEditor` (`arc`,
`spline`, `set_construction`) and `auto_3dx.geometry.constraint`
(`CONSTRAINT_CONCENTRICITY`, `SketchEditor.concentric`), all verified live
against B428_Cloud by `scripts/probes/27_sketch_geometry.py`
(`docs/conventions.md` 1.2.2.1: created AND `Part.Update()` succeeded).

CATIA is never contacted here: every COM object is a fake identified purely
by `type(obj).__name__` (docs/conventions.md section 4), matching
`tests/conftest.py`'s convention. `tests.conftest.Factory2D` does not yet
implement `CreateCircle` (open arc)/`CreateControlPoint`/`CreateSpline` --
this module is the one that needs them, and conftest.py is off limits for
this task, so `CurvedFactory2D` below subclasses it and adds exactly those
three methods, recording every call the way the base class already does for
`CreateLine`/`CreateClosedCircle`/`CreatePoint`.
"""

from collections.abc import Callable
from typing import Any

import pytest
import pywintypes

from auto_3dx.errors import Auto3dxError, ParameterTypeError
from auto_3dx.geometry.constraint import CONSTRAINT_CONCENTRICITY, CONSTRAINT_RADIUS
from auto_3dx.geometry.sketch import Sketch, SketchCollection

from tests.conftest import Circle2D as FakeCircle2D
from tests.conftest import Factory2D as FakeFactory2D
from tests.conftest import make_com_error

SKETCH_NAME = "AUTO3DX_CURVE_SKETCH"


class ControlPoint2D:
    """Fake CATIA `ControlPoint2D`, as returned by `CreateControlPoint`.

    Deliberately has no `Construction`/other properties beyond what a test
    needs -- `SketchEditor.spline()` never exposes these to a caller
    directly, only the resulting `Spline2D`.
    """

    def __init__(self, x: float, y: float) -> None:
        self.X, self.Y = x, y


class Spline2D:
    """Fake CATIA `Spline2D`, as returned by `Factory2D.CreateSpline`.

    Stores the exact pole objects it was built from (by identity), so a test
    can confirm `CreateSpline` received the very `ControlPoint2D` objects
    `CreateControlPoint` returned, in order -- not new objects, not
    coordinates.
    """

    def __init__(self, poles: "list[Any]") -> None:
        self.poles: list[Any] = list(poles)
        self.Construction = False


class CurvedFactory2D(FakeFactory2D):
    """Extends `tests.conftest.Factory2D` with probe-27's curved methods.

    `closed`, once set `True`, makes every one of these three methods raise
    `pywintypes.com_error` -- modelling a `Factory2D` whose owning sketch is
    no longer open for editing, the same technique
    `tests.conftest.Constraints.outside_edition` uses for constraint
    creation.
    """

    def __init__(self) -> None:
        super().__init__()
        self.arc_calls: list[tuple[float, float, float, float, float]] = []
        self.control_point_calls: list[tuple[float, float]] = []
        self.spline_calls: list[list[Any]] = []
        self.closed = False
        # Separate from `closed` so a test can isolate spline()'s SECOND
        # try/except block (the CreateSpline call itself) from its first
        # (the per-pole CreateControlPoint calls).
        self.fail_create_spline = False

    def CreateCircle(
        self,
        iCenterX: float,
        iCenterY: float,
        iRadius: float,
        iStartParam: float,
        iEndParam: float,
    ) -> Any:
        self.arc_calls.append((iCenterX, iCenterY, iRadius, iStartParam, iEndParam))
        if self.closed:
            raise make_com_error()
        # Real CATIA reports both the closed circle (CreateClosedCircle) and
        # this open arc as type(obj).__name__ == "Circle2D" (probe 27); this
        # fake preserves that by reusing the same fake class, not a subclass.
        circle = FakeCircle2D(iCenterX, iCenterY, iRadius)
        circle.StartParam = iStartParam
        circle.EndParam = iEndParam
        circle.Construction = False
        return circle

    def CreateControlPoint(self, iX: float, iY: float) -> ControlPoint2D:
        self.control_point_calls.append((iX, iY))
        if self.closed:
            raise make_com_error()
        return ControlPoint2D(iX, iY)

    def CreateSpline(self, iPoles: "list[Any]") -> Spline2D:
        self.spline_calls.append(list(iPoles))
        if self.closed:
            raise make_com_error()
        return Spline2D(iPoles)


def _curved_sketch(part_com: Any, selection: Any = None, name: str = SKETCH_NAME) -> Sketch:
    """Creates one sketch on the fake Part, wired with a `CurvedFactory2D`.

    `Sketch.OpenEdition()` returns whatever `factory2d` currently holds, so
    swapping it in before `edit()` is enough -- no change to `Sketch`/
    `SketchCollection` is needed to exercise the new curved methods.
    """
    sketch = SketchCollection(part_com, selection).create(name)
    sketch.com_object.factory2d = CurvedFactory2D()
    return sketch


# ---------------------------------------------------------------------------
# 1. arc(): exact CreateCircle arguments, in order; returns the raw object.
# ---------------------------------------------------------------------------


def test_arc_calls_create_circle_with_the_exact_arguments_in_order(
    part_factory: Callable[..., Any],
) -> None:
    """`arc()` must be a thin, order-preserving pass-through to `CreateCircle`."""
    part_com = part_factory()
    sketch = _curved_sketch(part_com)

    with sketch.edit() as editor:
        result = editor.arc(1.0, 2.0, 10.0, 0.0, 3.14159)

    factory: CurvedFactory2D = sketch.com_object.factory2d
    assert factory.arc_calls == [(1.0, 2.0, 10.0, 0.0, 3.14159)]
    assert result.kind == "Circle2D"
    assert result.com_object.Radius == 10.0


def test_arc_coerces_int_arguments_to_float(part_factory: Callable[..., Any]) -> None:
    """Integers are accepted and coerced, matching `line()`/`circle()`."""
    part_com = part_factory()
    sketch = _curved_sketch(part_com)

    with sketch.edit() as editor:
        editor.arc(0, 0, 10, 0, 1)

    factory: CurvedFactory2D = sketch.com_object.factory2d
    call = factory.arc_calls[0]
    assert call == (0.0, 0.0, 10.0, 0.0, 1.0)
    assert all(isinstance(value, float) for value in call)


@pytest.mark.parametrize(
    "bad_args",
    [
        (True, 0.0, 10.0, 0.0, 1.0),
        (0.0, 0.0, 10.0, True, 1.0),
        (0.0, 0.0, 10.0, 0.0, "1.0"),
        ("0", 0.0, 10.0, 0.0, 1.0),
    ],
)
def test_arc_rejects_non_numeric_arguments_before_any_com_call(
    part_factory: Callable[..., Any], bad_args: "tuple[Any, Any, Any, Any, Any]"
) -> None:
    """A `bool` or `str` anywhere in the five arguments must be refused first."""
    part_com = part_factory()
    sketch = _curved_sketch(part_com)

    with sketch.edit() as editor:
        with pytest.raises(ParameterTypeError):
            editor.arc(*bad_args)

    factory: CurvedFactory2D = sketch.com_object.factory2d
    assert factory.arc_calls == []


# ---------------------------------------------------------------------------
# 2. spline(): builds one ControlPoint2D per pole (exact coordinates, in
#    order), then calls CreateSpline with exactly those objects, by identity.
# ---------------------------------------------------------------------------


def test_spline_builds_one_control_point_per_pole_in_order(
    part_factory: Callable[..., Any],
) -> None:
    """Each `(x, y)` pair must produce its own `CreateControlPoint` call."""
    part_com = part_factory()
    sketch = _curved_sketch(part_com)
    poles = [(0.0, 50.0), (10.0, 60.0), (20.0, 50.0)]

    with sketch.edit() as editor:
        editor.spline(poles)

    factory: CurvedFactory2D = sketch.com_object.factory2d
    assert factory.control_point_calls == poles


def test_spline_calls_create_spline_with_the_exact_control_point_objects(
    part_factory: Callable[..., Any],
) -> None:
    """`CreateSpline` must receive the SAME `ControlPoint2D` objects, by identity."""
    part_com = part_factory()
    sketch = _curved_sketch(part_com)

    with sketch.edit() as editor:
        result = editor.spline([(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)])

    factory: CurvedFactory2D = sketch.com_object.factory2d
    assert len(factory.spline_calls) == 1
    passed_poles = factory.spline_calls[0]
    assert len(passed_poles) == 3
    assert all(type(pole).__name__ == "ControlPoint2D" for pole in passed_poles)
    assert result.kind == "Spline2D"
    assert result.com_object.poles == passed_poles
    # Identity, not just equality/count: no new objects were built in between.
    for pole in passed_poles:
        assert pole in result.com_object.poles


def test_spline_rejects_a_non_numeric_coordinate_before_any_com_call(
    part_factory: Callable[..., Any],
) -> None:
    """A bad coordinate anywhere in the list must stop before ANY control point is built.

    Otherwise a bad third point would leave two orphaned `ControlPoint2D`
    objects already created in the sketch.
    """
    part_com = part_factory()
    sketch = _curved_sketch(part_com)

    with sketch.edit() as editor:
        with pytest.raises(ParameterTypeError):
            editor.spline([(0.0, 0.0), (5.0, 5.0), (True, 0.0)])

    factory: CurvedFactory2D = sketch.com_object.factory2d
    assert factory.control_point_calls == []
    assert factory.spline_calls == []


@pytest.mark.parametrize(
    "bad_points",
    [
        ((0.0, 0.0), (5.0, 5.0)),
        [(0.0, 0.0), (5.0,)],
        [(0.0, 0.0), [5.0, 5.0]],
    ],
)
def test_spline_rejects_a_malformed_point_list_before_any_com_call(
    part_factory: Callable[..., Any], bad_points: Any
) -> None:
    """Malformed containers are mapped to a stable public validation error."""
    part_com = part_factory()
    sketch = _curved_sketch(part_com)

    with sketch.edit() as editor:
        with pytest.raises(ParameterTypeError):
            editor.spline(bad_points)

    factory: CurvedFactory2D = sketch.com_object.factory2d
    assert factory.control_point_calls == []
    assert factory.spline_calls == []


# ---------------------------------------------------------------------------
# 3. set_construction(): writes the bool, both directions, and validates it.
# ---------------------------------------------------------------------------


def test_set_construction_marks_an_element_construction_by_default(
    part_factory: Callable[..., Any],
) -> None:
    """`set_construction(element)` with no second argument sets `True`."""
    part_com = part_factory()
    sketch = _curved_sketch(part_com)

    with sketch.edit() as editor:
        circle = editor.circle(0.0, 0.0, 10.0)
        assert circle.com_object.Construction is False
        editor.set_construction(circle)

    assert circle.com_object.Construction is True


def test_set_construction_can_unset_an_element(part_factory: Callable[..., Any]) -> None:
    """`set_construction(element, False)` clears the flag again."""
    part_com = part_factory()
    sketch = _curved_sketch(part_com)

    with sketch.edit() as editor:
        circle = editor.circle(0.0, 0.0, 10.0)
        editor.set_construction(circle, True)
        editor.set_construction(circle, False)

    assert circle.com_object.Construction is False


def test_set_construction_works_on_every_new_curved_geometry_kind(
    part_factory: Callable[..., Any],
) -> None:
    """`Construction` is verified shared by every 2D geometry kind, curves included."""
    part_com = part_factory()
    sketch = _curved_sketch(part_com)

    with sketch.edit() as editor:
        arc = editor.arc(30.0, 0.0, 10.0, 0.0, 3.14159)
        point = editor.point(0.0, 30.0)
        spline = editor.spline([(0.0, 50.0), (10.0, 60.0), (20.0, 50.0)])
        for element in (arc, point, spline):
            editor.set_construction(element)

    assert arc.com_object.Construction is True
    assert point.com_object.Construction is True
    assert spline.com_object.Construction is True


@pytest.mark.parametrize("bad_value", [1, 0, "true", None, 1.0])
def test_set_construction_rejects_a_non_bool(
    part_factory: Callable[..., Any], bad_value: Any
) -> None:
    """`1`/`0` (ints) and other non-bool values must be refused explicitly."""
    part_com = part_factory()
    sketch = _curved_sketch(part_com)

    with sketch.edit() as editor:
        circle = editor.circle(0.0, 0.0, 10.0)
        with pytest.raises(ParameterTypeError):
            editor.set_construction(circle, bad_value)

    # Refused before the write: the flag must be untouched.
    assert circle.com_object.Construction is False


# ---------------------------------------------------------------------------
# 4. concentric(): exact constraint type code (3) and both raw circles.
# ---------------------------------------------------------------------------


def test_concentric_uses_type_code_3(part_factory: Callable[..., Any]) -> None:
    """Pins the literal verified in probe 27: Concentricity == 3."""
    assert CONSTRAINT_CONCENTRICITY == 3


def test_concentric_calls_add_bi_elt_cst_with_both_raw_circles(
    part_factory: Callable[..., Any],
) -> None:
    """`concentric(a, b)` must pass code 3 and the exact raw `Circle2D` objects."""
    part_com = part_factory()
    sketch = _curved_sketch(part_com)

    with sketch.edit() as editor:
        first = editor.circle(0.0, 0.0, 10.0)
        second = editor.circle(30.0, 0.0, 10.0)
        editor.concentric(first, second)

    fake_constraints = sketch.com_object.Constraints
    assert fake_constraints.bi_calls == [
        (CONSTRAINT_CONCENTRICITY, first.com_object, second.com_object)
    ]
    _, recorded_first, recorded_second = fake_constraints.bi_calls[0]
    assert recorded_first is first.com_object
    assert recorded_second is second.com_object
    assert type(recorded_first).__name__ != "Reference"


def test_concentric_constraint_has_no_dimension(part_factory: Callable[..., Any]) -> None:
    """Concentricity is not dimensional -- `.Dimension` must not be assumed present."""
    part_com = part_factory()
    sketch = _curved_sketch(part_com)

    with sketch.edit() as editor:
        first = editor.circle(0.0, 0.0, 10.0)
        second = editor.circle(30.0, 0.0, 10.0)
        constraint = editor.concentric(first, second)

    assert constraint.value is None


def test_concentric_rejects_the_same_circle_before_com(
    part_factory: Callable[..., Any],
) -> None:
    """The probe only verified two distinct circles, so self-pairs are blocked."""
    part_com = part_factory()
    sketch = _curved_sketch(part_com)

    with sketch.edit() as editor:
        circle = editor.circle(0.0, 0.0, 10.0)
        with pytest.raises(ParameterTypeError, match="distinct"):
            editor.concentric(circle, circle)

    assert sketch.com_object.Constraints.bi_calls == []


def test_radius_constraint_still_uses_type_code_14(part_factory: Callable[..., Any]) -> None:
    """Sanity check pinning the other constraint this task covers: Radius == 14."""
    assert CONSTRAINT_RADIUS == 14

    part_com = part_factory()
    sketch = _curved_sketch(part_com)

    with sketch.edit() as editor:
        circle = editor.circle(0.0, 0.0, 10.0)
        editor.radius(circle, 12.0)

    fake_constraints = sketch.com_object.Constraints
    assert fake_constraints.mono_calls == [(CONSTRAINT_RADIUS, circle.com_object)]


# ---------------------------------------------------------------------------
# 5. Geometry creation is refused (as an Auto3dxError, never a raw com_error)
#    once the sketch is no longer open for editing.
# ---------------------------------------------------------------------------


def test_arc_outside_edition_surfaces_as_auto3dx_error(
    part_factory: Callable[..., Any],
) -> None:
    """A stale `Factory2D` (sketch no longer open) must not leak `com_error`."""
    part_com = part_factory()
    sketch = _curved_sketch(part_com)

    with sketch.edit() as editor:
        editor.com_object.closed = True
        with pytest.raises(Auto3dxError) as caught:
            editor.arc(0.0, 0.0, 10.0, 0.0, 3.14159)

    assert not isinstance(caught.value, pywintypes.com_error)


def test_spline_outside_edition_surfaces_as_auto3dx_error(
    part_factory: Callable[..., Any],
) -> None:
    """Same trap as `arc()`, for `spline()`'s `CreateControlPoint` call."""
    part_com = part_factory()
    sketch = _curved_sketch(part_com)

    with sketch.edit() as editor:
        editor.com_object.closed = True
        with pytest.raises(Auto3dxError) as caught:
            editor.spline([(0.0, 0.0), (5.0, 5.0)])

    assert not isinstance(caught.value, pywintypes.com_error)


def test_spline_outside_edition_fails_on_create_spline_itself(
    part_factory: Callable[..., Any],
) -> None:
    """Also covers the case where every pole is built but `CreateSpline` itself fails."""
    part_com = part_factory()
    sketch = _curved_sketch(part_com)
    factory: CurvedFactory2D

    with sketch.edit() as editor:
        factory = editor.com_object
        # Build the poles first (still "open"), then go stale right before
        # CreateSpline -- isolates the second try/except block in spline().
        poles = [(0.0, 0.0), (5.0, 5.0)]
        control_points = [factory.CreateControlPoint(x, y) for x, y in poles]
        factory.control_point_calls.clear()
        factory.closed = True
        with pytest.raises(Auto3dxError) as caught:
            factory.closed = False  # allow CreateControlPoint again, only CreateSpline fails
            original_create_spline = factory.CreateSpline

            def _failing_create_spline(iPoles: "list[Any]") -> Any:
                factory.spline_calls.append(list(iPoles))
                raise make_com_error()

            factory.CreateSpline = _failing_create_spline  # type: ignore[method-assign]
            try:
                editor.spline(poles)
            finally:
                factory.CreateSpline = original_create_spline

    assert not isinstance(caught.value, pywintypes.com_error)
    del control_points  # only built to document intent; unused otherwise


def test_concentric_outside_edition_surfaces_as_auto3dx_error(
    part_factory: Callable[..., Any],
) -> None:
    """Same trap, for the new bi-element constraint method."""
    part_com = part_factory()
    sketch = _curved_sketch(part_com)

    with sketch.edit() as editor:
        first = editor.circle(0.0, 0.0, 10.0)
        second = editor.circle(30.0, 0.0, 10.0)
        sketch.com_object.Constraints.outside_edition = True
        with pytest.raises(Auto3dxError) as caught:
            editor.concentric(first, second)

    assert not isinstance(caught.value, pywintypes.com_error)
    assert "edit()" in str(caught.value)


def test_retained_editor_refuses_use_after_close_edition(
    part_factory: Callable[..., Any],
) -> None:
    """A retained short-lived wrapper cannot issue COM calls after its context."""
    part_com = part_factory()
    sketch = _curved_sketch(part_com)

    with sketch.edit() as editor:
        factory: CurvedFactory2D = editor.com_object

    with pytest.raises(Auto3dxError, match="no longer active"):
        editor.arc(0.0, 0.0, 10.0, 0.0, 1.0)

    assert sketch.com_object.close_edition_calls == 1
    assert factory.arc_calls == []


# ---------------------------------------------------------------------------
# 6. Nothing new here ever calls Part.Update() or Part.Save().
# ---------------------------------------------------------------------------


def test_new_curved_geometry_and_constraints_never_call_part_update(
    part_factory: Callable[..., Any],
) -> None:
    """`arc`/`spline`/`set_construction`/`concentric` must leave `Part.Update()` uncalled.

    `part_factory`'s fake `Part.Save` raises `AssertionError` unconditionally
    (see conftest.py), so this test would already fail loudly if any of these
    new code paths ever called `Save`.
    """
    part_com = part_factory()
    sketch = _curved_sketch(part_com)

    with sketch.edit() as editor:
        arc = editor.arc(30.0, 0.0, 10.0, 0.0, 3.14159)
        point = editor.point(0.0, 30.0)
        spline = editor.spline([(0.0, 50.0), (10.0, 60.0), (20.0, 50.0)])
        circle_a = editor.circle(0.0, 0.0, 10.0)
        circle_b = editor.circle(30.0, 0.0, 10.0)
        for element in (arc, point, spline):
            editor.set_construction(element)
        editor.radius(circle_a, 12.0)
        editor.concentric(circle_a, circle_b)

    assert part_com.update_calls == 0
