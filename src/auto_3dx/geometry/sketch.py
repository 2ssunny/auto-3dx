"""Wrappers around CATIA `Sketch` and `Sketches` COM objects.

A `Sketch` is a 2D profile attached to a plane. For the three origin planes
(`OriginElements.PlaneXY` / `PlaneYZ` / `PlaneZX`), those planes are wrapped
as generic `AnyObject` COM objects, not a dedicated `Plane` type, so a plane
is never identified by `type(obj).__name__`; instead callers pass one of the
`SUPPORT_*` strings and this module resolves it to the matching
`OriginElements` attribute.

A sketch can also sit on a user-defined offset or angled plane, created by
`auto_3dx.geometry.planes.PlaneCollection` (`docs/conventions.md` 1.2.7).
`SketchCollection.create`'s `support` parameter therefore accepts either kind
interchangeably: a `SUPPORT_*` string, resolved exactly as before, or a plane
wrapper (`planes.Plane`/`OffsetPlane`/`AnglePlane`) accepted by duck typing
-- anything exposing a `com_object` attribute -- rather than by importing
that type here. `planes.py` already imports this module's private
`_PLANE_ATTRIBUTE_BY_SUPPORT`/`_wrap_com_error` (the same way
`geometry.part_design` does), so importing `planes.Plane` back into this
module would create a circular import; duck typing on `com_object` avoids it
while keeping `create`'s existing string-based behaviour and signature
completely unchanged for existing callers. The plane wrapper's raw
`com_object` is what actually reaches `Sketches.Add`, unwrapped -- verified
(`docs/conventions.md` 1.2.7) to need no `Reference` wrapper, the same as an
origin plane.

`Sketch` itself has no support/plane property. Which plane a sketch is on can
only be recovered by comparing `GetAbsoluteAxisData` against the three
verified reference frames (see `docs/conventions.md` section 1.2). That
comparison has no equivalent for a user-defined plane (there is no verified
reference frame for an arbitrary offset/angle), which is why `ensure` below
still only accepts the three origin-plane strings.
"""

import contextlib
import math
from collections.abc import Iterator
from typing import Any

import pywintypes

from auto_3dx._com import automation_error, format_hresult, hresult_of
from auto_3dx._generation import ModelGeneration
from auto_3dx.errors import (
    AmbiguousNameError,
    Auto3dxError,
    AutomationError,
    ParameterTypeError,
    PartialCreationError,
    SketchAlreadyExistsError,
    SketchNotFoundError,
    SketchSupportMismatchError,
    UnsupportedSupportError,
    ValidationError,
)
from auto_3dx.geometry.constraint import (
    CONSTRAINT_COINCIDENT,
    CONSTRAINT_CONCENTRICITY,
    CONSTRAINT_DISTANCE,
    CONSTRAINT_HORIZONTAL,
    CONSTRAINT_LENGTH,
    CONSTRAINT_PARALLEL,
    CONSTRAINT_PERPENDICULAR,
    CONSTRAINT_RADIUS,
    CONSTRAINT_TANGENT,
    CONSTRAINT_VERTICAL,
    Constraint,
    ConstraintCollection,
)
from auto_3dx.geometry.deletion import delete_via_selection
from auto_3dx.parameters.parameter import (
    MILLIMETRE,
    validate_length_unit,
    validate_length_value,
    validate_parameter_name,
)

SUPPORT_XY: str = "XY"
"""Support string for `OriginElements.PlaneXY`."""

SUPPORT_YZ: str = "YZ"
"""Support string for `OriginElements.PlaneYZ`."""

SUPPORT_ZX: str = "ZX"
"""Support string for `OriginElements.PlaneZX`."""

SUPPORTED_SKETCH_SUPPORTS: frozenset[str] = frozenset({SUPPORT_XY, SUPPORT_YZ, SUPPORT_ZX})
"""The only support strings a sketch can be created on or matched against."""

AXIS_TOLERANCE: float = 1e-9
"""Absolute tolerance used to compare `GetAbsoluteAxisData` results with `math.isclose`."""

_AXIS_DATA_SEED: list[float] = [0.0] * 9
"""Seed buffer passed to `GetAbsoluteAxisData`, which returns the filled 9-tuple."""

_PLANE_ATTRIBUTE_BY_SUPPORT: dict[str, str] = {
    SUPPORT_XY: "PlaneXY",
    SUPPORT_YZ: "PlaneYZ",
    SUPPORT_ZX: "PlaneZX",
}
"""Maps a support string to the `OriginElements` attribute holding that plane."""

_AXIS_DATA_BY_SUPPORT: dict[str, tuple[float, ...]] = {
    SUPPORT_XY: (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
    SUPPORT_YZ: (0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
    SUPPORT_ZX: (0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0),
}
"""Verified `GetAbsoluteAxisData` reference frames (origin + X axis + Y axis) per support."""


# COM failures translate in one place (`auto_3dx._com`, `docs/api-design.md`
# section 8). The private name stays because sibling modules import it from here.
_wrap_com_error = automation_error


def _wrap_constraint_com_error(error: pywintypes.com_error) -> AutomationError:
    """Converts a failed constraint-creation COM call into an `AutomationError`.

    Verified (`docs/conventions.md` sections 1.2.4 and 6.14): `AddMonoEltCst`/
    `AddBiEltCst` only succeed while the owning sketch is open for editing,
    between `OpenEdition()` and `CloseEdition()`; after `CloseEdition()` they
    always raise. That is by far the most likely cause of a failure here, so
    the message names it explicitly instead of only reporting the HRESULT.

    Args:
        error: The COM error to convert.

    Returns:
        An `AutomationError` describing the failure, naming the most likely
        cause, and carrying the HRESULT.
    """
    hresult = hresult_of(error)
    return AutomationError(
        f"Failed to create the constraint (HRESULT={format_hresult(hresult)}). "
        "Constraints only work while the sketch is open for editing, i.e. inside a "
        "`Sketch.edit()` block; this is the most likely cause if that block "
        "has already exited.",
        hresult,
    )


def _axis_data_matches(actual: tuple[float, ...], expected: tuple[float, ...]) -> bool:
    """Compares two 9-tuples of axis data within `AXIS_TOLERANCE`.

    `rel_tol=0.0` is passed explicitly to `math.isclose`: omitting it leaves
    Python's default `rel_tol=1e-09` active, which widens the effective
    tolerance for large coordinate values and can hide a real mismatch.

    Args:
        actual: The axis data read from a sketch.
        expected: The reference axis data for a support.

    Returns:
        `True` if every component is within `AXIS_TOLERANCE` of its
        counterpart. A length mismatch is treated as a plain "no match"
        (`False`) rather than an error, so `support()` can keep returning
        `None` instead of guessing.

    Raises:
        Auto3dxError: If `actual` contains a non-numeric entry that
            `math.isclose` cannot compare.
    """
    if len(actual) != len(expected):
        return False
    try:
        return all(
            math.isclose(a, b, rel_tol=0.0, abs_tol=AXIS_TOLERANCE)
            for a, b in zip(actual, expected)
        )
    except TypeError as error:
        raise AutomationError(
            "Axis data contains a non-numeric entry; expected 9 floats from "
            "GetAbsoluteAxisData."
        ) from error


class SketchEditor:
    """Wraps a `Factory2D` obtained from `Sketch.OpenEdition()`.

    Only valid for the lifetime of the `Sketch.edit()` context manager that
    created it. Geometry creation (`point`/`line`/`circle`/`arc`/`spline`/
    `rectangle`) is a thin, validated pass-through to the verified `Factory2D`
    COM methods (`CreatePoint`, `CreateLine`, `CreateClosedCircle`,
    `CreateCircle`, `CreateControlPoint`, `CreateSpline`; see
    `scripts/probes/27_sketch_geometry.py` for the curved-geometry ones).
    `set_construction()` marks any of the resulting elements as construction
    geometry, which keeps them out of a padded/pocketed profile.

    Constraint creation (`horizontal`, `vertical`, `perpendicular`,
    `parallel`, `coincident`, `tangent`, `length`, `radius`, `distance`,
    `concentric`) lives here too, and only here: verified
    (`docs/conventions.md` 1.2.4/6.14), `Constraints.AddMonoEltCst`/
    `AddBiEltCst` only succeed while the sketch is open for editing, which is
    exactly the lifetime of this object. Their arguments are the raw
    `Line2D`/`Circle2D` COM objects returned by `line()`/`circle()` -- a
    `Reference` built with `CreateReferenceFromObject` is verified to be
    rejected here, unlike Part Design's face/edge references. None of these
    methods calls `Part.Update()`.
    """

    def __init__(
        self,
        com_object: Any,
        constraints: Any,
        generation: ModelGeneration | None = None,
    ) -> None:
        """Initializes the wrapper.

        Args:
            com_object: The raw `Factory2D` COM object to wrap. This is what
                `SketchEditor.com_object` returns, unchanged from before
                constraints were added.
            constraints: The raw `Constraints` COM collection
                (`Sketch.Constraints`) used by the constraint-creation
                methods below.
            generation: The owning sketch's model generation, shared with
                every `Constraint` this editor creates. Geometry creation and
                construction flags made through this editor are covered by
                the single advance `Sketch.edit()` makes when the session
                closes, not by this object directly. A wrapper built
                directly from a raw COM object gets its own generation,
                which nothing else shares.
        """
        self._com_object = com_object
        self._constraints = constraints
        self._generation = generation if generation is not None else ModelGeneration()
        self._active = True

    def _require_active(self) -> None:
        """Rejects use after the owning ``Sketch.edit()`` block has exited."""
        if not self._active:
            raise ValidationError(
                "This SketchEditor is no longer active; create geometry and "
                "constraints only inside the Sketch.edit() block that returned it."
            )

    def _deactivate(self) -> None:
        """Marks this short-lived editor unusable before closing the edition."""
        self._active = False

    @property
    def com_object(self) -> Any:
        """Returns the raw underlying COM object.

        This is an escape hatch for callers that need direct COM access, and
        is useful in tests.

        Returns:
            The wrapped raw COM object.
        """
        return self._com_object

    def point(self, x: float, y: float) -> Any:
        """Creates a 2D point in the sketch.

        Args:
            x: The point's X coordinate, in millimetres.
            y: The point's Y coordinate, in millimetres.

        Returns:
            The raw `Point2D` COM object. It has no `X`/`Y` properties
            (verified, `scripts/probes/27_sketch_geometry.py`): read its
            coordinates back with ``point.GetCoordinates([0.0, 0.0])``, which
            returns an `(x, y)` tuple -- the same seed-array-as-output
            convention already used by `Sketch.GetAbsoluteAxisData` above.

        Raises:
            ParameterTypeError: If `x` or `y` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        self._require_active()
        x_value = validate_length_value(x)
        y_value = validate_length_value(y)
        try:
            return self._com_object.CreatePoint(x_value, y_value)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def line(self, x1: float, y1: float, x2: float, y2: float) -> Any:
        """Creates a 2D line segment in the sketch.

        Args:
            x1: The start point's X coordinate, in millimetres.
            y1: The start point's Y coordinate, in millimetres.
            x2: The end point's X coordinate, in millimetres.
            y2: The end point's Y coordinate, in millimetres.

        Returns:
            The raw `Line2D` COM object.

        Raises:
            ParameterTypeError: If any coordinate is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        self._require_active()
        x1_value = validate_length_value(x1)
        y1_value = validate_length_value(y1)
        x2_value = validate_length_value(x2)
        y2_value = validate_length_value(y2)
        try:
            return self._com_object.CreateLine(x1_value, y1_value, x2_value, y2_value)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def circle(self, center_x: float, center_y: float, radius: float) -> Any:
        """Creates a closed 2D circle in the sketch.

        A closed, unconstrained circle like this one is verified to pad
        successfully (`scripts/probes/27_sketch_geometry.py`), so curved
        profiles are padable, not just polygonal ones.

        Args:
            center_x: The circle centre's X coordinate, in millimetres.
            center_y: The circle centre's Y coordinate, in millimetres.
            radius: The circle radius, in millimetres.

        Returns:
            The raw `Circle2D` COM object. `.Radius`, `.GeometricType`,
            `.StartPoint`, and `.EndPoint` all read back fine; `.CenterPoint`
            is listed as readable in the type library but FAILS with a COM
            error when actually accessed (verified live), so this library
            offers no helper for it -- do not add one without re-verifying
            first. `.Construction` is a writable bool on the returned object
            (see `set_construction()`).

        Raises:
            ParameterTypeError: If `center_x`, `center_y`, or `radius` is not an
                `int`/`float` (or is a `bool`).
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        self._require_active()
        center_x_value = validate_length_value(center_x)
        center_y_value = validate_length_value(center_y)
        radius_value = validate_length_value(radius)
        try:
            return self._com_object.CreateClosedCircle(
                center_x_value, center_y_value, radius_value
            )
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def arc(
        self,
        center_x: float,
        center_y: float,
        radius: float,
        start_param: float,
        end_param: float,
    ) -> Any:
        """Creates an open 2D arc (circle segment) in the sketch.

        Verified (`scripts/probes/27_sketch_geometry.py`): `Factory2D.
        CreateCircle`, given explicit start/end parameters, creates an OPEN
        arc rather than the closed circle `circle()` produces, and the
        result survives `Part.Update()`.

        `start_param`/`end_param` are passed to CATIA exactly as given. The
        probe that verified this call used 0.0 and `math.pi` and treated them
        as radians for that one experiment, but nothing in the type library
        or the observed behaviour actually proves the unit -- do NOT assume
        radians. Treat these two arguments as opaque CATIA parameter values
        until a future probe pins the unit down (e.g. by comparing the arc's
        `StartPoint`/`EndPoint` coordinates against a known angle).

        Args:
            center_x: The arc's centre X coordinate, in millimetres.
            center_y: The arc's centre Y coordinate, in millimetres.
            radius: The arc's radius, in millimetres.
            start_param: The arc's start parameter, in CATIA's own
                (unverified) parameter unit.
            end_param: The arc's end parameter, same caveat as `start_param`.

        Returns:
            The raw `Circle2D` COM object (open, not closed -- unlike
            `circle()`'s result). `.StartPoint`/`.EndPoint` read back as
            `Point2D` objects; see `point()` for how to read their
            coordinates.

        Raises:
            ParameterTypeError: If any argument is not an `int`/`float` (or
                is a `bool`).
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        self._require_active()
        center_x_value = validate_length_value(center_x)
        center_y_value = validate_length_value(center_y)
        radius_value = validate_length_value(radius)
        # validate_length_value is reused here purely as a generic "reject
        # bool/non-numeric, coerce to float" check -- start_param/end_param
        # are not lengths, but no dedicated validator exists for an opaque,
        # unit-unverified CATIA parameter value.
        start_param_value = validate_length_value(start_param)
        end_param_value = validate_length_value(end_param)
        try:
            return self._com_object.CreateCircle(
                center_x_value,
                center_y_value,
                radius_value,
                start_param_value,
                end_param_value,
            )
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def spline(self, points: "list[tuple[float, float]]") -> Any:
        """Creates a 2D spline through a sequence of control points.

        Verified (`scripts/probes/27_sketch_geometry.py`): `Factory2D.
        CreateSpline` accepts a plain array of `ControlPoint2D` objects (this
        method builds them internally, via `CreateControlPoint`, from the
        given coordinates); the probe fed it three such control points and
        the resulting spline survived `Part.Update()`. Whether `CreateSpline`
        would also accept raw `Point2D` objects was NOT tested, so this
        method never tries that path.

        Every coordinate is validated before any COM call is made, so a bad
        point later in the list cannot leave a partial set of control points
        behind in the sketch.

        Args:
            points: The spline's control points, as `(x, y)` millimetre
                pairs, in order. The probe used three; the minimum accepted
                by CATIA itself is not established here.

        Returns:
            The raw `Spline2D` COM object. `.GetNumberOfControlPoints()`
            returns a `float`, not an `int` (verified live); `.StartPoint`
            and `.EndPoint` return `ControlPoint2D` objects.

        Raises:
            ParameterTypeError: If `points` is not a list of two-item tuples,
                or any coordinate is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        self._require_active()
        if not isinstance(points, list):
            raise ParameterTypeError(
                f"points must be a list, got {type(points).__name__}."
            )
        coerced_points: list[tuple[float, float]] = []
        for index, point in enumerate(points):
            if not isinstance(point, tuple) or len(point) != 2:
                raise ParameterTypeError(
                    "Each spline point must be a two-item tuple; "
                    f"points[{index}] is {type(point).__name__}."
                )
            x, y = point
            coerced_points.append(
                (validate_length_value(x), validate_length_value(y))
            )
        poles: list[Any] = []
        for x_value, y_value in coerced_points:
            try:
                poles.append(self._com_object.CreateControlPoint(x_value, y_value))
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error
        try:
            return self._com_object.CreateSpline(poles)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def set_construction(self, element: Any, construction: bool = True) -> None:
        """Marks (or unmarks) a 2D geometry element as construction geometry.

        Verified (`scripts/probes/27_sketch_geometry.py`): `Construction` is
        a writable bool property shared by every 2D geometry type tried
        (`Line2D`, `Circle2D`, `Point2D`, `Spline2D`) -- not something
        specific to curves. Construction geometry is excluded from a padded
        profile: the probe marked every element except one closed circle as
        construction right before padding, isolating a single real closed
        profile in a sketch that also held an open arc, a point, and a
        spline, and the pad succeeded.

        Args:
            element: The raw 2D geometry COM object, as returned by
                `line()`, `circle()`, `arc()`, `point()`, or `spline()`.
            construction: `True` to mark `element` as construction geometry,
                `False` to mark it as real geometry. Defaults to `True`.

        Raises:
            ParameterTypeError: If `construction` is not a `bool`.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        self._require_active()
        # bool is checked explicitly (not just "truthy"), matching the
        # bool-is-an-int-subclass discipline used throughout this library --
        # a stray 1/0 should not silently pass as True/False here either.
        if not isinstance(construction, bool):
            raise ParameterTypeError(
                f"construction must be a bool, got {type(construction).__name__}."
            )
        try:
            element.Construction = construction
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def rectangle(
        self,
        width: float,
        height: float,
        origin_x: float = 0.0,
        origin_y: float = 0.0,
    ) -> "list[Any]":
        """Creates a closed rectangular profile from four lines.

        The rectangle spans from `(origin_x, origin_y)` to
        `(origin_x + width, origin_y + height)`. A closed, unconstrained
        profile like this one is verified to pad successfully, so no
        constraints are added.

        Args:
            width: The rectangle's width along X, in millimetres.
            height: The rectangle's height along Y, in millimetres.
            origin_x: The X coordinate of the rectangle's lower-left corner.
                Defaults to `0.0`.
            origin_y: The Y coordinate of the rectangle's lower-left corner.
                Defaults to `0.0`.

        Returns:
            The four raw `Line2D` COM objects forming the closed loop, in
            counter-clockwise order starting from `(origin_x, origin_y)`.

        Raises:
            ParameterTypeError: If any argument is not an `int`/`float` (or is
                a `bool`).
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        width_value = validate_length_value(width)
        height_value = validate_length_value(height)
        origin_x_value = validate_length_value(origin_x)
        origin_y_value = validate_length_value(origin_y)
        far_x = origin_x_value + width_value
        far_y = origin_y_value + height_value
        return [
            self.line(origin_x_value, origin_y_value, far_x, origin_y_value),
            self.line(far_x, origin_y_value, far_x, far_y),
            self.line(far_x, far_y, origin_x_value, far_y),
            self.line(origin_x_value, far_y, origin_x_value, origin_y_value),
        ]

    def _mono(self, constraint_type: int, element: Any) -> Constraint:
        """Creates a single-element constraint via `Constraints.AddMonoEltCst`.

        Args:
            constraint_type: One of the `CONSTRAINT_*` codes.
            element: The raw 2D element COM object (as returned by `line()`
                or `circle()`).

        Returns:
            A `Constraint` wrapping the newly created constraint.

        Raises:
            Auto3dxError: If the underlying COM call fails -- most likely
                because this sketch's `edit()` block has already exited.
        """
        self._require_active()
        try:
            raw = self._constraints.AddMonoEltCst(constraint_type, element)
        except pywintypes.com_error as error:
            raise _wrap_constraint_com_error(error) from error
        return Constraint(raw, self._generation)

    def _bi(self, constraint_type: int, first: Any, second: Any) -> Constraint:
        """Creates a two-element constraint via `Constraints.AddBiEltCst`.

        Args:
            constraint_type: One of the `CONSTRAINT_*` codes.
            first: The raw first 2D element COM object.
            second: The raw second 2D element COM object.

        Returns:
            A `Constraint` wrapping the newly created constraint.

        Raises:
            Auto3dxError: If the underlying COM call fails -- most likely
                because this sketch's `edit()` block has already exited.
        """
        self._require_active()
        try:
            raw = self._constraints.AddBiEltCst(constraint_type, first, second)
        except pywintypes.com_error as error:
            raise _wrap_constraint_com_error(error) from error
        return Constraint(raw, self._generation)

    def horizontal(self, line: Any) -> Constraint:
        """Constrains a line to be horizontal.

        Verified (`docs/conventions.md` 1.2.4): CATIA normalises the created
        constraint's `Type` to `CONSTRAINT_PARALLEL`, not `CONSTRAINT_HORIZONTAL`
        -- do not look the result back up by the code used to request it.

        Args:
            line: The raw `Line2D` COM object (as returned by `line()`).

        Returns:
            A `Constraint` wrapping the newly created constraint.

        Raises:
            Auto3dxError: If the underlying COM call fails -- most likely
                because this sketch's `edit()` block has already exited.
        """
        return self._mono(CONSTRAINT_HORIZONTAL, line)

    def vertical(self, line: Any) -> Constraint:
        """Constrains a line to be vertical.

        Verified (`docs/conventions.md` 1.2.4): CATIA normalises the created
        constraint's `Type` to `CONSTRAINT_PARALLEL`, not `CONSTRAINT_VERTICAL`
        -- do not look the result back up by the code used to request it.

        Args:
            line: The raw `Line2D` COM object (as returned by `line()`).

        Returns:
            A `Constraint` wrapping the newly created constraint.

        Raises:
            Auto3dxError: If the underlying COM call fails -- most likely
                because this sketch's `edit()` block has already exited.
        """
        return self._mono(CONSTRAINT_VERTICAL, line)

    def perpendicular(self, first: Any, second: Any) -> Constraint:
        """Constrains two lines to be perpendicular.

        Args:
            first: The raw first `Line2D` COM object.
            second: The raw second `Line2D` COM object.

        Returns:
            A `Constraint` wrapping the newly created constraint.

        Raises:
            Auto3dxError: If the underlying COM call fails -- most likely
                because this sketch's `edit()` block has already exited.
        """
        return self._bi(CONSTRAINT_PERPENDICULAR, first, second)

    def parallel(self, first: Any, second: Any) -> Constraint:
        """Constrains two lines to be parallel.

        Args:
            first: The raw first `Line2D` COM object.
            second: The raw second `Line2D` COM object.

        Returns:
            A `Constraint` wrapping the newly created constraint.

        Raises:
            Auto3dxError: If the underlying COM call fails -- most likely
                because this sketch's `edit()` block has already exited.
        """
        return self._bi(CONSTRAINT_PARALLEL, first, second)

    def coincident(self, first: Any, second: Any) -> Constraint:
        """Constrains two elements to be coincident.

        Args:
            first: The raw first 2D element COM object.
            second: The raw second 2D element COM object.

        Returns:
            A `Constraint` wrapping the newly created constraint.

        Raises:
            Auto3dxError: If the underlying COM call fails -- most likely
                because this sketch's `edit()` block has already exited.
        """
        return self._bi(CONSTRAINT_COINCIDENT, first, second)

    def tangent(self, first: Any, second: Any) -> Constraint:
        """Constrains two elements to be tangent.

        Args:
            first: The raw first 2D element COM object.
            second: The raw second 2D element COM object.

        Returns:
            A `Constraint` wrapping the newly created constraint.

        Raises:
            Auto3dxError: If the underlying COM call fails -- most likely
                because this sketch's `edit()` block has already exited.
        """
        return self._bi(CONSTRAINT_TANGENT, first, second)

    def concentric(self, first: Any, second: Any) -> Constraint:
        """Constrains two circles to share the same centre.

        Verified (`scripts/probes/27_sketch_geometry.py`) with two DISTINCT
        `Circle2D` objects; created AND `Part.Update()` succeeded. An earlier
        probe (20/22, `docs/conventions.md` 1.2.4) passed the SAME circle to
        both argument slots -- a probe input bug, not a COM limitation -- so
        that earlier attempt never actually proved or disproved anything
        about this constraint. Passing the same circle object as both `first`
        and `second` here is therefore unverified; always pass two distinct
        circles.

        Args:
            first: The raw first `Circle2D` COM object.
            second: The raw second `Circle2D` COM object, distinct from
                `first`.

        Returns:
            A `Constraint` wrapping the newly created constraint (type
            `CONSTRAINT_CONCENTRICITY`, not dimensional -- it has no
            `Dimension`).

        Raises:
            ParameterTypeError: If `first` and `second` refer to the same
                circle.
            Auto3dxError: If the underlying COM call fails -- most likely
                because this sketch's `edit()` block has already exited.
        """
        if first is second or first == second:
            raise ParameterTypeError(
                "Concentricity requires two distinct circle objects."
            )
        return self._bi(CONSTRAINT_CONCENTRICITY, first, second)

    def length(
        self, line: Any, value: float | None = None, unit: str = MILLIMETRE
    ) -> Constraint:
        """Constrains a line's length, optionally driving it to a value.

        Args:
            line: The raw `Line2D` COM object (as returned by `line()`).
            value: If given, the length to write to the new constraint's
                `Dimension.Value` right after creation. Validated *before*
                any COM call. `None` (the default) leaves the constraint at
                the length already captured from the drawn geometry.
            unit: The unit `value` is expressed in. Only used when `value` is
                given. Defaults to `MILLIMETRE`.

        Returns:
            A `Constraint` wrapping the newly created constraint (type
            `CONSTRAINT_LENGTH`, dimensional).

        Raises:
            UnsupportedUnitError: If `value` is given and `unit` is not a
                supported unit.
            ParameterTypeError: If `value` is given and is not an `int`/
                `float` (or is a `bool`).
            Auto3dxError: If the underlying COM call fails -- most likely
                because this sketch's `edit()` block has already exited.
        """
        if value is not None:
            validate_length_unit(unit)
            value = validate_length_value(value)
        constraint = self._mono(CONSTRAINT_LENGTH, line)
        if value is not None:
            constraint.set_value(value, unit)
        return constraint

    def radius(
        self, circle: Any, value: float | None = None, unit: str = MILLIMETRE
    ) -> Constraint:
        """Constrains a circle's radius, optionally driving it to a value.

        Args:
            circle: The raw `Circle2D` COM object (as returned by `circle()`).
            value: If given, the radius to write to the new constraint's
                `Dimension.Value` right after creation. Validated *before*
                any COM call. `None` (the default) leaves the constraint at
                the radius already captured from the drawn geometry.
            unit: The unit `value` is expressed in. Only used when `value` is
                given. Defaults to `MILLIMETRE`.

        Returns:
            A `Constraint` wrapping the newly created constraint (type
            `CONSTRAINT_RADIUS`, dimensional).

        Raises:
            UnsupportedUnitError: If `value` is given and `unit` is not a
                supported unit.
            ParameterTypeError: If `value` is given and is not an `int`/
                `float` (or is a `bool`).
            Auto3dxError: If the underlying COM call fails -- most likely
                because this sketch's `edit()` block has already exited.
        """
        if value is not None:
            validate_length_unit(unit)
            value = validate_length_value(value)
        constraint = self._mono(CONSTRAINT_RADIUS, circle)
        if value is not None:
            constraint.set_value(value, unit)
        return constraint

    def distance(
        self,
        first: Any,
        second: Any,
        value: float | None = None,
        unit: str = MILLIMETRE,
    ) -> Constraint:
        """Constrains the distance between two elements, optionally driving it.

        Args:
            first: The raw first 2D element COM object.
            second: The raw second 2D element COM object.
            value: If given, the distance to write to the new constraint's
                `Dimension.Value` right after creation. Validated *before*
                any COM call. `None` (the default) leaves the constraint at
                the distance already captured from the drawn geometry.
            unit: The unit `value` is expressed in. Only used when `value` is
                given. Defaults to `MILLIMETRE`.

        Returns:
            A `Constraint` wrapping the newly created constraint (type
            `CONSTRAINT_DISTANCE`, dimensional).

        Raises:
            UnsupportedUnitError: If `value` is given and `unit` is not a
                supported unit.
            ParameterTypeError: If `value` is given and is not an `int`/
                `float` (or is a `bool`).
            Auto3dxError: If the underlying COM call fails -- most likely
                because this sketch's `edit()` block has already exited.
        """
        if value is not None:
            validate_length_unit(unit)
            value = validate_length_value(value)
        constraint = self._bi(CONSTRAINT_DISTANCE, first, second)
        if value is not None:
            constraint.set_value(value, unit)
        return constraint


class Sketch:
    """Wraps a raw CATIA `Sketch` COM object.

    A sketch has no support/plane property of its own; `support()` derives it
    by comparing `GetAbsoluteAxisData` against the verified reference frames
    in `_AXIS_DATA_BY_SUPPORT`.
    """

    def __init__(self, com_object: Any, generation: ModelGeneration | None = None) -> None:
        """Initializes the wrapper.

        Args:
            com_object: The raw CATIA `Sketch` COM object to wrap.
            generation: The owning Part's model generation, advanced by every
                write this wrapper makes (rename, `set_center_line`, and
                closing an `edit()` session) and shared with every
                `ConstraintCollection`/`Constraint`/`SketchEditor` this
                sketch hands out. A wrapper built directly from a raw COM
                object gets its own, which nothing else shares.
        """
        self._com_object = com_object
        self._generation = generation if generation is not None else ModelGeneration()
        self._editing = False
        self._constraints: ConstraintCollection | None = None

    @property
    def com_object(self) -> Any:
        """Returns the raw underlying COM object.

        This is an escape hatch for callers that need direct COM access, and
        is useful in tests.

        Returns:
            The wrapped raw COM object.
        """
        return self._com_object

    @property
    def name(self) -> str:
        """Returns the sketch's name.

        Returns:
            The sketch's `Name`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Name
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def rename(self, name: str) -> None:
        """Renames the sketch.

        `Sketch.Name` is verified writable; this is how `SketchCollection.create()`
        names a sketch right after `Sketches.Add(plane)`.

        Args:
            name: The new name. Must be non-empty, without surrounding
                whitespace, and must not contain `"\\"`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        # The generation advances once this block is attempted, even if the
        # write raises: a caller cannot know whether CATIA applied the name
        # before failing (`docs/api-design.md` section 5.3).
        with self._generation.mutation():
            try:
                self._com_object.Name = name
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error

    def set_center_line(self, line: Any) -> None:
        """Sets the sketch's revolve axis.

        Verified writable (`docs/conventions.md` section 1.2.3): `create_shaft`
        and `create_groove` both require a `CenterLine` on the sketch they
        revolve, and the profile drawn in the sketch has to sit away from that
        axis -- a profile straddling or touching the axis is not the verified
        configuration.

        Args:
            line: The raw 2D line COM object (as returned by
                `SketchEditor.line`) to use as the revolve axis.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        with self._generation.mutation():
            try:
                self._com_object.CenterLine = line
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error

    def axis_data(self) -> "tuple[float, ...]":
        """Reads the sketch's absolute axis data.

        Returns:
            The 9-tuple `(origin_x, origin_y, origin_z, x_axis_x, x_axis_y,
            x_axis_z, y_axis_x, y_axis_y, y_axis_z)` returned by
            `GetAbsoluteAxisData`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly, or if
                `GetAbsoluteAxisData` returns `None` or another non-iterable
                result.
        """
        try:
            raw = self._com_object.GetAbsoluteAxisData(list(_AXIS_DATA_SEED))
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        try:
            return tuple(raw)
        except TypeError as error:
            raise AutomationError(
                "GetAbsoluteAxisData returned a non-iterable result; expected "
                "9 floats."
            ) from error

    def support(self) -> str | None:
        """Derives which origin plane this sketch is attached to.

        Compares `axis_data()` against the verified reference frames for
        `SUPPORT_XY`/`SUPPORT_YZ`/`SUPPORT_ZX` using `math.isclose` and
        `AXIS_TOLERANCE`.

        Returns:
            `SUPPORT_XY`, `SUPPORT_YZ`, or `SUPPORT_ZX` on a match, or `None`
            if the sketch's axis frame does not match any of them (for
            example, a sketch on a user-made plane).

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        actual = self.axis_data()
        for support, reference in _AXIS_DATA_BY_SUPPORT.items():
            if _axis_data_matches(actual, reference):
                return support
        return None

    def element_names(self) -> "list[str]":
        """Lists the names of this sketch's geometric elements.

        Uses the same 1-based `Count`/`Item(i)` collection protocol already
        verified for `Parameters` (`docs/conventions.md` section 1.1), applied
        to the sketch's `GeometricElements` collection.

        Returns:
            The `Name` of each item in `GeometricElements`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            elements = self._com_object.GeometricElements
            count = elements.Count
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        names: list[str] = []
        for index in range(1, count + 1):
            try:
                names.append(elements.Item(index).Name)
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error
        return names

    @property
    def constraints(self) -> ConstraintCollection:
        """Returns a read-only view over this sketch's constraints.

        Built on first access and cached, matching `Part.parameters`/
        `Part.sketches`/`Part.part_design`. Reading this collection works
        whether or not the sketch is currently open for editing; only
        *creating* a new constraint requires `edit()` (see
        `SketchEditor`).

        Returns:
            A `ConstraintCollection` over this sketch's `Constraints`.
        """
        if self._constraints is None:
            self._constraints = ConstraintCollection(self._com_object, self._generation)
        return self._constraints

    @contextlib.contextmanager
    def edit(self) -> Iterator[SketchEditor]:
        """Opens the sketch for editing and yields a `SketchEditor`.

        Wraps `OpenEdition()`/`CloseEdition()`. `CloseEdition()` is always
        called in a `finally` block, so an exception raised while the caller
        is drawing cannot leave the sketch stuck in open-edition state.

        Re-entrant use is refused: nested `OpenEdition()` is unverified, and if
        CATIA keeps a single edition state per sketch, an inner `CloseEdition()`
        would close the outer session and leave the outer `edit()` block's own
        `CloseEdition()` mismatched. The re-entry check happens before any COM
        call, and the instance flag is always reset in the same `finally` that
        calls `CloseEdition()`, so a failed block never leaves the sketch
        permanently locked out of `edit()`.

        Also reads `Constraints` up front and passes it into the
        `SketchEditor`, since constraint creation (`docs/conventions.md`
        1.2.4/6.14) is verified to work only inside this block.

        The whole edition session is one model mutation (`docs/api-design.md`
        section 5.2): geometry, construction flags and constraints are all
        created inside it, so the generation advances exactly once, when
        `CloseEdition()` is attempted -- not once per `SketchEditor` call.
        That single advance happens in the same `finally` that always calls
        `CloseEdition()`, whether the caller's block succeeded or raised, for
        the same reason `PartDesign` advances on attempt rather than on
        success: a call that raised may still have changed the model.

        Yields:
            A `SketchEditor` wrapping the `Factory2D` from `OpenEdition()` and
            this sketch's `Constraints` collection.

        Raises:
            Auto3dxError: If `edit()` is called while already active for this
                `Sketch`, or if reading `Constraints`, `OpenEdition()`, or
                `CloseEdition()` fails unexpectedly.
        """
        if self._editing:
            raise ValidationError(
                "This sketch is already being edited; edit() does not support "
                "re-entrant or concurrent use."
            )
        try:
            constraints = self._com_object.Constraints
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        self._editing = True
        try:
            factory = self._com_object.OpenEdition()
        except pywintypes.com_error as error:
            self._editing = False
            raise _wrap_com_error(error) from error
        editor = SketchEditor(factory, constraints, self._generation)
        try:
            yield editor
        finally:
            editor._deactivate()
            try:
                # One advance for the whole session, attempted here rather
                # than on each geometry/constraint call the caller made
                # above (`docs/api-design.md` section 5.3).
                with self._generation.mutation():
                    self._com_object.CloseEdition()
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error
            finally:
                self._editing = False

    def __repr__(self) -> str:
        """Returns a debugging representation.

        Returns:
            A string such as ``Sketch(name='Sketch.1')``.
        """
        try:
            name = self.name
        except Auto3dxError:
            name = "<unavailable>"
        return f"Sketch(name={name!r})"


class SketchCollection:
    """Wraps the sketches living on a Part's `MainBody`.

    Sketches are read from `part_com_object.MainBody.Sketches`, and planes are
    read from `part_com_object.OriginElements`, so this wrapper is constructed
    from the Part's raw COM object rather than the `Sketches` collection alone.

    Shares one model generation with every `Sketch` it returns
    (`docs/api-design.md` section 5): `create` and `remove` advance it, and
    a stale topology snapshot is refused before it reaches CATIA.
    """

    def __init__(
        self,
        part_com_object: Any,
        selection: Any = None,
        generation: ModelGeneration | None = None,
    ) -> None:
        """Initializes the wrapper.

        Args:
            part_com_object: The raw CATIA `Part` COM object. Both
                `OriginElements` (for planes) and `MainBody.Sketches` (for
                sketches) are read from it.
            selection: The raw CATIA `Selection` COM object from the editor.
                Required only by `remove`, because `Sketches` has no `Remove`
                method and deletion has to go through the editor's selection.
                Reading and creating work without it.
            generation: The owning Part's model generation. A standalone
                instance gets its own, which no other wrapper shares; obtain
                `SketchCollection` from a `Part` instead. Shared with every
                `Sketch` this collection returns.
        """
        self._part_com_object = part_com_object
        self._selection = selection
        # Shared with the owning Part and everything else reachable from it
        # (`docs/api-design.md` section 5). Every mutation here advances it.
        self._generation = generation if generation is not None else ModelGeneration()

    def _sketches(self) -> Any:
        """Returns the raw `MainBody.Sketches` collection.

        Returns:
            The raw CATIA `Sketches` collection.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._part_com_object.MainBody.Sketches
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def _plane(self, support: str) -> Any:
        """Resolves a support string to its raw `OriginElements` plane.

        Args:
            support: One of `SUPPORTED_SKETCH_SUPPORTS`.

        Returns:
            The raw plane COM object (wrapper type `AnyObject`, not `Plane`).

        Raises:
            UnsupportedSupportError: If `support` is not a supported value.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        if support not in SUPPORTED_SKETCH_SUPPORTS:
            raise UnsupportedSupportError(
                f"Support {support!r} is not supported; supported supports are "
                f"{sorted(SUPPORTED_SKETCH_SUPPORTS)}."
            )
        attribute = _PLANE_ATTRIBUTE_BY_SUPPORT[support]
        try:
            return getattr(self._part_com_object.OriginElements, attribute)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def _resolve_support(self, support: Any) -> Any:
        """Resolves a `support` argument to a raw plane COM object.

        Args:
            support: Either one of `SUPPORTED_SKETCH_SUPPORTS` (a string),
                resolved through `OriginElements` exactly like `_plane`; or a
                plane wrapper from `auto_3dx.geometry.planes`
                (`OffsetPlane`/`AnglePlane`) -- anything exposing a
                `com_object` attribute holding the raw hybrid plane shape
                that `Sketches.Add` accepts directly, with no `Reference`
                wrapper needed (verified, `docs/conventions.md` 1.2.7).

        Returns:
            The raw plane COM object.

        Raises:
            UnsupportedSupportError: If `support` is a string not in
                `SUPPORTED_SKETCH_SUPPORTS`, or is neither a string nor an
                object exposing `com_object`.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        if isinstance(support, str):
            return self._plane(support)
        # Duck-typed rather than an `isinstance` check against
        # `auto_3dx.geometry.planes.Plane`: that module already imports this
        # module's private plane-resolution helpers (mirroring
        # `geometry.part_design`'s existing reuse of them), so importing
        # `planes.Plane` back here would create a circular import. Anything
        # exposing `com_object` -- in practice an `OffsetPlane`/`AnglePlane`
        # -- is accepted instead.
        try:
            return support.com_object
        except AttributeError as error:
            raise UnsupportedSupportError(
                "support must be one of "
                f"{sorted(SUPPORTED_SKETCH_SUPPORTS)} or a plane object "
                "exposing `com_object` (e.g. from auto_3dx.geometry.planes), "
                f"got {type(support).__name__}."
            ) from error

    @property
    def count(self) -> int:
        """Returns the number of sketches in the collection.

        Returns:
            `MainBody.Sketches.Count`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._sketches().Count
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def list(self) -> "list[Sketch]":
        """Lists every sketch in the collection.

        Returns:
            A `Sketch` wrapper for each item, in the collection's 1-based
            `Item(i)` order. An empty collection returns `[]`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        sketches = self._sketches()
        try:
            count = sketches.Count
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        result: list[Sketch] = []
        for index in range(1, count + 1):
            try:
                com_object = sketches.Item(index)
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error
            result.append(Sketch(com_object, self._generation))
        return result

    # Return annotation is quoted: by this point `list` is already shadowed in
    # the class namespace by the `list` method above, so the bare subscript
    # `list[str]` would resolve to that method, not the builtin.
    def names(self) -> "list[str]":
        """Lists the names of every sketch in the collection.

        Returns:
            The `name` of each sketch, in the same order as `list()`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return [sketch.name for sketch in self.list()]

    def _matching(self, name: str) -> "list[Sketch]":
        """Enumerates the collection and returns every sketch named `name`.

        Existence must be positive evidence, not a caught exception:
        `Item(name)` raising does not distinguish "no such sketch" from "a
        transient COM failure", and misreading the latter as absence would
        create a duplicate on a retried `create`. Enumerating with `Count`/
        `Item(i)` and comparing `Name` avoids that, and also lets duplicate
        names (which CATIA permits) be counted rather than silently
        collapsed to one.

        Args:
            name: The sketch name to match against.

        Returns:
            Every `Sketch` in the collection whose `name` equals `name`, in
            `list()` order. Empty if none match.

        Raises:
            Auto3dxError: If the underlying enumeration fails unexpectedly.
        """
        return [sketch for sketch in self.list() if sketch.name == name]

    def get(self, name: str) -> Sketch:
        """Looks up a sketch by name.

        Names are not unique in CATIA, so this enumerates the collection
        (see `_matching`) instead of trusting `Item(name)`, and refuses to
        guess when more than one sketch shares the name.

        Args:
            name: The sketch's name.

        Returns:
            The `Sketch` wrapping the matching COM object.

        Raises:
            SketchNotFoundError: If no sketch named `name` exists.
            AmbiguousNameError: If two or more sketches named `name` exist.
            Auto3dxError: If the underlying enumeration fails unexpectedly.
        """
        matches = self._matching(name)
        if not matches:
            raise SketchNotFoundError(f"No sketch named {name!r} was found.")
        if len(matches) > 1:
            raise AmbiguousNameError(
                f"{len(matches)} sketches named {name!r} exist; a name-based "
                "lookup cannot safely pick one."
            )
        return matches[0]

    def create(self, name: str, support: Any = SUPPORT_XY) -> Sketch:
        """Creates a new sketch on the given support plane.

        The existence check enumerates the collection (see `_matching`)
        before any mutating COM call, mirroring the
        `ParameterCollection.create_length` duplicate-name guard: a retried
        `create` must not silently add a second, indistinguishable sketch.

        `Sketches.Add` creates the sketch before its name is set. If the
        follow-up rename fails, the default-named sketch is left in the
        model rather than rolled back (deleting it is a separate, explicit
        operation the caller controls), and `PartialCreationError` reports
        its actual name so a retry does not add another one on top of it.

        Args:
            name: The new sketch's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            support: One of `SUPPORTED_SKETCH_SUPPORTS` (`"XY"`/`"YZ"`/
                `"ZX"`), or a plane wrapper returned by
                `auto_3dx.geometry.planes.PlaneCollection`
                (`OffsetPlane`/`AnglePlane`) -- see `_resolve_support`.
                Defaults to `SUPPORT_XY`.

        Returns:
            The newly created `Sketch`, already renamed to `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            UnsupportedSupportError: If `support` is not a supported value.
            SketchAlreadyExistsError: If a sketch named `name` already exists.
            PartialCreationError: If the sketch was created but the follow-up
                rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        if self._matching(name):
            raise SketchAlreadyExistsError(f"A sketch named {name!r} already exists.")
        plane = self._resolve_support(support)
        # The generation advances once this block is attempted, even if it
        # raises: `Sketches.Add` can create the sketch and then fail the
        # rename, which leaves it in the tree (`docs/api-design.md` 5.3).
        with self._generation.mutation():
            try:
                com_object = self._sketches().Add(plane)
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error
            sketch = Sketch(com_object, self._generation)
            # The rename is applied directly (not via `sketch.rename()`) so
            # this stays a single mutation instead of a nested one.
            try:
                sketch.com_object.Name = name
            except pywintypes.com_error as error:
                try:
                    actual_name = sketch.name
                except Auto3dxError:
                    actual_name = "unknown"
                raise PartialCreationError(
                    f"Created a sketch but failed to rename it to {name!r}; it "
                    f"currently exists in the model as {actual_name!r}. Do not "
                    "retry blindly: retrying would create another sketch instead "
                    "of fixing this one."
                ) from error
        return sketch

    def ensure(self, name: str, support: str = SUPPORT_XY) -> Sketch:
        """Creates a sketch, or reuses it if one with the same name and support exists.

        A name match alone does not authorise reuse: the existing sketch's
        axis data must also match the requested support (see
        `docs/conventions.md` section 1.3). The ambiguous-name check inside
        `get()` runs first, before any axis comparison.

        Unlike `create`, `support` here only accepts the three origin-plane
        strings, not a plane wrapper: reuse is decided by comparing
        `axis_data()` against the verified reference frames in
        `_AXIS_DATA_BY_SUPPORT`, and no such reference frame exists for an
        arbitrary user-defined offset/angle plane, so an honest comparison
        for that case cannot be made yet. Create a sketch on a plane wrapper
        with `create()` directly; managing its reuse across runs is left to
        the caller.

        Args:
            name: The sketch's name.
            support: One of `SUPPORTED_SKETCH_SUPPORTS`. Defaults to `SUPPORT_XY`.

        Returns:
            The existing or newly created `Sketch`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            UnsupportedSupportError: If `support` is not a supported value.
            AmbiguousNameError: If two or more sketches named `name` exist.
            SketchSupportMismatchError: If a sketch named `name` already
                exists but its axis data does not match `support`.
            PartialCreationError: If a new sketch had to be created and its
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        if support not in SUPPORTED_SKETCH_SUPPORTS:
            raise UnsupportedSupportError(
                f"Support {support!r} is not supported; supported supports are "
                f"{sorted(SUPPORTED_SKETCH_SUPPORTS)}."
            )
        try:
            existing = self.get(name)
        except SketchNotFoundError:
            return self.create(name, support)

        if not _axis_data_matches(existing.axis_data(), _AXIS_DATA_BY_SUPPORT[support]):
            raise SketchSupportMismatchError(
                f"Sketch {name!r} already exists but is not on support {support!r}."
            )
        return existing

    def remove(self, name: str) -> None:
        """Removes a sketch from the model.

        `Sketches` exposes no `Remove` method, so deletion goes through the
        editor's `Selection`. That means this method needs the `selection` the
        collection was constructed with; obtain the Part via
        `Catia.active_part()` to get one wired in.

        The sketch is looked up first so a missing name is reported as
        `SketchNotFoundError`. Removing a sketch that still carries a pad is
        expected to fail; remove the pad first (see `PartDesign.remove_pad`),
        which cascade-deletes its sketch anyway.

        This deletes model content. It does not call `Part.Update()`, and it
        never saves.

        Args:
            name: The sketch's name.

        Raises:
            SketchNotFoundError: If no sketch named `name` exists.
            Auto3dxError: If no editor selection is available, or the deletion
                failed.
        """
        target = self.get(name)
        with self._generation.mutation():
            delete_via_selection(
                self._selection, target.com_object, f"sketch {name!r}"
            )

    def __len__(self) -> int:
        """Returns the number of sketches in the collection.

        Returns:
            Same as `count`.
        """
        return self.count

    def __iter__(self) -> Iterator[Sketch]:
        """Iterates over the sketches in the collection.

        Returns:
            An iterator over `Sketch` wrappers, in `list()` order.
        """
        return iter(self.list())

    def __contains__(self, name: object) -> bool:
        """Checks whether a sketch with the given name exists.

        A non-`str` argument is accepted and simply reported as absent,
        rather than raising.

        Args:
            name: The candidate sketch name.

        Returns:
            `True` if `get(name)` succeeds, `False` otherwise (including
            when `name` is not a `str`).
        """
        if not isinstance(name, str):
            return False
        try:
            self.get(name)
        except SketchNotFoundError:
            return False
        return True
