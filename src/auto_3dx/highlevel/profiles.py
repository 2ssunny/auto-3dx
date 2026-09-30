"""Reusable sketch primitives, each drawn in one `Sketch.edit()` session.

They compose the Level 2 `SketchEditor`: `rectangle()` is `editor.rectangle` plus, on
request, the verified constraint methods; `circle()` is `editor.circle`. Constraint levels
say exactly what they create and never claim more:

    "none"         four lines, no constraints (what `SketchEditor.rectangle` always did)
    "orientation"  + horizontal on the bottom and top, vertical on the right and left
                   (probe 46ad: all four created, statuses OK, update succeeded)
    "dimensioned"  + a length on the bottom (width) and on the left (height)
                   (probe 46ae: six constraints, statuses OK, update succeeded)
    "fully"        a DIFFERENT drawing: the four sides share their corner points
                   (`SketchEditor.polygon`), with horizontal x2, vertical x2, width,
                   height, and the lower-left corner's distances to the sketch's V and H
                   axes -- eight constraints for the four corners' eight degrees of
                   freedom (probe 47i: statuses OK; driving the width 60 -> 70 grew the
                   whole rectangle to the right and kept the corner in place)

The first three draw four independent lines whose corners are not joined, so constraining
one side moves only that side: they are not fully constrained, and nothing here says they
are. "fully" is the only level whose width and height can be edited afterwards as the
rectangle's width and height. It counts degrees of freedom; CATIA's own solver status for
the sketch was not read.

None of these rebuilds. Horizontal and vertical constraints read back as parallelism, as
they always have (`docs/conventions.md` 1.2.4).
"""

from dataclasses import dataclass
from typing import Any

from auto_3dx.errors import ParameterTypeError
from auto_3dx.geometry.constraint import Constraint
from auto_3dx.geometry.sketch import (
    SKETCH_AXIS_HORIZONTAL,
    SKETCH_AXIS_VERTICAL,
    Sketch,
    SketchElement,
)

CONSTRAINTS_NONE: str = "none"
CONSTRAINTS_ORIENTATION: str = "orientation"
CONSTRAINTS_DIMENSIONED: str = "dimensioned"
CONSTRAINTS_FULLY: str = "fully"
SUPPORTED_RECTANGLE_CONSTRAINTS: "frozenset[str]" = frozenset(
    {CONSTRAINTS_NONE, CONSTRAINTS_ORIENTATION, CONSTRAINTS_DIMENSIONED, CONSTRAINTS_FULLY}
)
"""The constraint levels `rectangle()` offers; see the module docstring."""


@dataclass(frozen=True)
class RectangleProfile:
    """The four lines of a rectangle and the constraints drawn with them.

    Attributes:
        bottom: The side from the lower-left corner along +X.
        right: The side from the lower-right corner along +Y.
        top: The side from the upper-right corner along -X.
        left: The side from the upper-left corner along -Y.
        constraints: The constraints created, in creation order; empty for `"none"`.
            For `"fully"`: horizontal bottom, horizontal top, vertical right, vertical
            left, width (bottom length), height (left length), then the lower-left
            corner's distance to the V axis and to the H axis.
        corners: The shared corner points for `"fully"` (lower-left, lower-right,
            upper-right, upper-left); empty for the other levels, whose lines share none.
    """

    bottom: SketchElement
    right: SketchElement
    top: SketchElement
    left: SketchElement
    constraints: "tuple[Constraint, ...]"
    corners: "tuple[SketchElement, ...]" = ()

    @property
    def width_constraint(self) -> "Constraint | None":
        """Constraint | None: The width (bottom length) constraint, if one was made."""
        return self.constraints[_WIDTH_INDEX] if len(self.constraints) > _WIDTH_INDEX else None

    @property
    def height_constraint(self) -> "Constraint | None":
        """Constraint | None: The height (left length) constraint, if one was made."""
        return (
            self.constraints[_HEIGHT_INDEX] if len(self.constraints) > _HEIGHT_INDEX else None
        )

    @property
    def lines(self) -> "tuple[SketchElement, ...]":
        """tuple[SketchElement, ...]: `bottom, right, top, left`, the closed loop in order."""
        return (self.bottom, self.right, self.top, self.left)


_WIDTH_INDEX = 4
_HEIGHT_INDEX = 5


def _pair(value: Any, label: str) -> "tuple[float, float]":
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ParameterTypeError(f"{label} must be two numbers (x, y), not {value!r}.")
    first, second = value
    for item in (first, second):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ParameterTypeError(f"{label} must be two numbers (x, y), not {value!r}.")
    return (float(first), float(second))


def _positive(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
        raise ParameterTypeError(f"{label} must be a positive number, not {value!r}.")
    return float(value)


def _require_sketch(sketch: Any) -> None:
    if not isinstance(sketch, Sketch):
        raise ParameterTypeError(f"Expected a Sketch, not {type(sketch).__name__}.")


def rectangle(
    sketch: Sketch,
    width: float,
    height: float,
    origin: "tuple[float, float]" = (0.0, 0.0),
    constraints: str = CONSTRAINTS_NONE,
) -> RectangleProfile:
    """Draws a closed axis-aligned rectangle from its lower-left corner.

    Args:
        sketch: The sketch to draw in, in its own local coordinates.
        width: The size along local X, in millimetres; positive.
        height: The size along local Y, in millimetres; positive.
        origin: The lower-left corner `(x, y)`.
        constraints: `"none"`, `"orientation"`, `"dimensioned"` or `"fully"` (module
            docstring). Only `"fully"` makes a rectangle whose width and height can be
            driven afterwards (`profile.width_constraint.set_value(...)`).

    Returns:
        The `RectangleProfile`.

    Raises:
        ParameterTypeError: If an argument is invalid. Raised before the sketch is opened.
        ValidationError: If the sketch is already open for editing.
        Auto3dxError: If CATIA refuses a call.
    """
    _require_sketch(sketch)
    width_value = _positive(width, "width")
    height_value = _positive(height, "height")
    corner = _pair(origin, "origin")
    if constraints not in SUPPORTED_RECTANGLE_CONSTRAINTS:
        raise ParameterTypeError(
            f"constraints must be one of {sorted(SUPPORTED_RECTANGLE_CONSTRAINTS)}, not "
            f"{constraints!r}."
        )
    if constraints == CONSTRAINTS_FULLY:
        return _fully_constrained(sketch, width_value, height_value, corner)
    made: list[Constraint] = []
    with sketch.edit() as editor:
        bottom, right, top, left = editor.rectangle(
            width_value, height_value, origin_x=corner[0], origin_y=corner[1]
        )
        if constraints in (CONSTRAINTS_ORIENTATION, CONSTRAINTS_DIMENSIONED):
            made.append(editor.horizontal(bottom))
            made.append(editor.horizontal(top))
            made.append(editor.vertical(right))
            made.append(editor.vertical(left))
        if constraints == CONSTRAINTS_DIMENSIONED:
            made.append(editor.length(bottom, width_value))
            made.append(editor.length(left, height_value))
    return RectangleProfile(bottom, right, top, left, tuple(made))


def _fully_constrained(
    sketch: Sketch, width: float, height: float, corner: "tuple[float, float]"
) -> RectangleProfile:
    """The `"fully"` rectangle: shared corners, eight constraints (probe 47i's sequence)."""
    x0, y0 = corner
    with sketch.edit() as editor:
        points, lines = editor.polygon(
            [(x0, y0), (x0 + width, y0), (x0 + width, y0 + height), (x0, y0 + height)]
        )
        bottom, right, top, left = lines
        made = [
            editor.horizontal(bottom),
            editor.horizontal(top),
            editor.vertical(right),
            editor.vertical(left),
            editor.length(bottom, width),
            editor.length(left, height),
            editor.distance_to_axis(points[0], SKETCH_AXIS_VERTICAL),
            editor.distance_to_axis(points[0], SKETCH_AXIS_HORIZONTAL),
        ]
    return RectangleProfile(bottom, right, top, left, tuple(made), tuple(points))


def centered_rectangle(
    sketch: Sketch,
    width: float,
    height: float,
    center: "tuple[float, float]" = (0.0, 0.0),
    constraints: str = CONSTRAINTS_NONE,
) -> RectangleProfile:
    """Draws a closed axis-aligned rectangle around a centre point.

    The same as `rectangle()` with `origin = center - (width / 2, height / 2)`.

    Args:
        sketch: The sketch to draw in.
        width: The size along local X, in millimetres; positive.
        height: The size along local Y, in millimetres; positive.
        center: The centre `(x, y)`.
        constraints: `"none"`, `"orientation"`, `"dimensioned"` or `"fully"`. With
            `"fully"` the LOWER-LEFT corner is what is anchored, so driving the width
            later grows the rectangle to the right, not about its centre.

    Returns:
        The `RectangleProfile`.

    Raises:
        ParameterTypeError: If an argument is invalid.
        Auto3dxError: If CATIA refuses a call.
    """
    middle = _pair(center, "center")
    width_value = _positive(width, "width")
    height_value = _positive(height, "height")
    return rectangle(
        sketch,
        width_value,
        height_value,
        (middle[0] - width_value / 2.0, middle[1] - height_value / 2.0),
        constraints,
    )


def circle(sketch: Sketch, center: "tuple[float, float]", radius: float) -> SketchElement:
    """Draws one closed circle, unconstrained, in its own edit session.

    Args:
        sketch: The sketch to draw in.
        center: The centre `(x, y)` in the sketch's local millimetres.
        radius: The radius in millimetres; positive.

    Returns:
        The circle's `SketchElement`; `geometry()` reads it back once the call returns.

    Raises:
        ParameterTypeError: If an argument is invalid.
        Auto3dxError: If CATIA refuses a call.
    """
    _require_sketch(sketch)
    middle = _pair(center, "center")
    radius_value = _positive(radius, "radius")
    with sketch.edit() as editor:
        return editor.circle(middle[0], middle[1], radius_value)
