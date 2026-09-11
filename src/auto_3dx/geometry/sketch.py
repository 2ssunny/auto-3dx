"""Wrappers around CATIA `Sketch` and `Sketches` COM objects.

A `Sketch` is a 2D profile attached to one of the three origin planes
(`OriginElements.PlaneXY` / `PlaneYZ` / `PlaneZX`). Those planes are wrapped
as generic `AnyObject` COM objects, not a dedicated `Plane` type, so a plane
is never identified by `type(obj).__name__`; instead callers pass one of the
`SUPPORT_*` strings and this module resolves it to the matching
`OriginElements` attribute.

`Sketch` itself has no support/plane property. Which plane a sketch is on can
only be recovered by comparing `GetAbsoluteAxisData` against the three
verified reference frames (see `docs/conventions.md` section 1.2).
"""

import contextlib
import math
from collections.abc import Iterator
from typing import Any

import pywintypes

from auto_3dx.errors import (
    AmbiguousNameError,
    Auto3dxError,
    PartialCreationError,
    SketchAlreadyExistsError,
    SketchNotFoundError,
    SketchSupportMismatchError,
    UnsupportedSupportError,
)
from auto_3dx.geometry.constraint import (
    CONSTRAINT_COINCIDENT,
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


def _wrap_com_error(error: pywintypes.com_error) -> Auto3dxError:
    """Converts an unmapped `pywintypes.com_error` into an `Auto3dxError`.

    Args:
        error: The COM error to convert.

    Returns:
        An `Auto3dxError` whose message includes the failure's HRESULT in
        hexadecimal form.
    """
    hresult = error.args[0] if error.args else None
    hresult_hex = f"0x{hresult & 0xFFFFFFFF:08X}" if isinstance(hresult, int) else hresult
    return Auto3dxError(f"Unexpected COM failure (HRESULT={hresult_hex}).")


def _wrap_constraint_com_error(error: pywintypes.com_error) -> Auto3dxError:
    """Converts a failed constraint-creation COM call into an `Auto3dxError`.

    Verified (`docs/conventions.md` sections 1.2.4 and 6.14): `AddMonoEltCst`/
    `AddBiEltCst` only succeed while the owning sketch is open for editing,
    between `OpenEdition()` and `CloseEdition()`; after `CloseEdition()` they
    always raise. That is by far the most likely cause of a failure here, so
    the message names it explicitly instead of only reporting the HRESULT.

    Args:
        error: The COM error to convert.

    Returns:
        An `Auto3dxError` describing the failure and naming the most likely
        cause.
    """
    hresult = error.args[0] if error.args else None
    hresult_hex = f"0x{hresult & 0xFFFFFFFF:08X}" if isinstance(hresult, int) else hresult
    return Auto3dxError(
        f"Failed to create the constraint (HRESULT={hresult_hex}). Constraints "
        "only work while the sketch is open for editing, i.e. inside a "
        "`Sketch.edit()` block; this is the most likely cause if that block "
        "has already exited."
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
        raise Auto3dxError(
            "Axis data contains a non-numeric entry; expected 9 floats from "
            "GetAbsoluteAxisData."
        ) from error


class SketchEditor:
    """Wraps a `Factory2D` obtained from `Sketch.OpenEdition()`.

    Only valid for the lifetime of the `Sketch.edit()` context manager that
    created it. Geometry creation (`point`/`line`/`circle`/`rectangle`) is a
    thin, validated pass-through to the verified `Factory2D` COM methods
    (`CreatePoint`, `CreateLine`, `CreateClosedCircle`).

    Constraint creation (`horizontal`, `vertical`, `perpendicular`,
    `parallel`, `coincident`, `tangent`, `length`, `radius`, `distance`) lives
    here too, and only here: verified (`docs/conventions.md` 1.2.4/6.14),
    `Constraints.AddMonoEltCst`/`AddBiEltCst` only succeed while the sketch is
    open for editing, which is exactly the lifetime of this object. Their
    arguments are the raw `Line2D`/`Circle2D` COM objects returned by
    `line()`/`circle()` -- a `Reference` built with
    `CreateReferenceFromObject` is verified to be rejected here, unlike Part
    Design's face/edge references. None of these methods calls
    `Part.Update()`.
    """

    def __init__(self, com_object: Any, constraints: Any) -> None:
        """Initializes the wrapper.

        Args:
            com_object: The raw `Factory2D` COM object to wrap. This is what
                `SketchEditor.com_object` returns, unchanged from before
                constraints were added.
            constraints: The raw `Constraints` COM collection
                (`Sketch.Constraints`) used by the constraint-creation
                methods below.
        """
        self._com_object = com_object
        self._constraints = constraints

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
            The raw `Point2D` COM object.

        Raises:
            ParameterTypeError: If `x` or `y` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
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

        Args:
            center_x: The circle centre's X coordinate, in millimetres.
            center_y: The circle centre's Y coordinate, in millimetres.
            radius: The circle radius, in millimetres.

        Returns:
            The raw `Circle2D` COM object.

        Raises:
            ParameterTypeError: If `center_x`, `center_y`, or `radius` is not an
                `int`/`float` (or is a `bool`).
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        center_x_value = validate_length_value(center_x)
        center_y_value = validate_length_value(center_y)
        radius_value = validate_length_value(radius)
        try:
            return self._com_object.CreateClosedCircle(
                center_x_value, center_y_value, radius_value
            )
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
        try:
            raw = self._constraints.AddMonoEltCst(constraint_type, element)
        except pywintypes.com_error as error:
            raise _wrap_constraint_com_error(error) from error
        return Constraint(raw)

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
        try:
            raw = self._constraints.AddBiEltCst(constraint_type, first, second)
        except pywintypes.com_error as error:
            raise _wrap_constraint_com_error(error) from error
        return Constraint(raw)

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

    def __init__(self, com_object: Any) -> None:
        """Initializes the wrapper.

        Args:
            com_object: The raw CATIA `Sketch` COM object to wrap.
        """
        self._com_object = com_object
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
            raise Auto3dxError(
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
            self._constraints = ConstraintCollection(self._com_object)
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

        Yields:
            A `SketchEditor` wrapping the `Factory2D` from `OpenEdition()` and
            this sketch's `Constraints` collection.

        Raises:
            Auto3dxError: If `edit()` is called while already active for this
                `Sketch`, or if reading `Constraints`, `OpenEdition()`, or
                `CloseEdition()` fails unexpectedly.
        """
        if self._editing:
            raise Auto3dxError(
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
        try:
            yield SketchEditor(factory, constraints)
        finally:
            try:
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
    """

    def __init__(self, part_com_object: Any, selection: Any = None) -> None:
        """Initializes the wrapper.

        Args:
            part_com_object: The raw CATIA `Part` COM object. Both
                `OriginElements` (for planes) and `MainBody.Sketches` (for
                sketches) are read from it.
            selection: The raw CATIA `Selection` COM object from the editor.
                Required only by `remove`, because `Sketches` has no `Remove`
                method and deletion has to go through the editor's selection.
                Reading and creating work without it.
        """
        self._part_com_object = part_com_object
        self._selection = selection

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
            result.append(Sketch(com_object))
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

    def create(self, name: str, support: str = SUPPORT_XY) -> Sketch:
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
            support: One of `SUPPORTED_SKETCH_SUPPORTS`. Defaults to `SUPPORT_XY`.

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
        plane = self._plane(support)
        try:
            com_object = self._sketches().Add(plane)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        sketch = Sketch(com_object)
        try:
            sketch.rename(name)
        except Auto3dxError as error:
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
