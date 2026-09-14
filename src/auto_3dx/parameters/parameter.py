"""Wrapper around a single CATIA `Parameter` COM object.

This module provides :class:`Parameter`, a thin wrapper that isolates callers
from raw COM access, and :class:`ParameterInfo`, a frozen dataclass snapshot
of a parameter's state for callers (including agents) that want structured
data instead of a printed string.
"""

import dataclasses
from typing import Any

import pywintypes

from auto_3dx._generation import ModelGeneration
from auto_3dx.errors import (
    Auto3dxError,
    ParameterNameError,
    ParameterTypeError,
    UnsupportedUnitError,
)

LENGTH_KIND: str = "Length"
"""The `type(com_object).__name__` value for a CATIA Length parameter."""

LENGTH_MAGNITUDE: str = "Length"
"""The `iMagnitude` string `Parameters.CreateDimension` expects for a length.

Verified against this installation's `Parameters.Units` collection, whose
magnitudes are capitalised names (`Length`, `Angle`, `Mass`, ...) rather than
the upper-case forms used by older CATIA documentation.
"""

ANGLE_MAGNITUDE: str = "Angle"
"""The `iMagnitude` string `Parameters.CreateDimension` expects for an angle."""

MILLIMETRE: str = "mm"
"""The only supported unit string for Length parameters."""

SUPPORTED_LENGTH_UNITS: frozenset[str] = frozenset({MILLIMETRE})
"""Units accepted by :meth:`Parameter.set` for Length parameters."""

DEGREE: str = "deg"
"""The only supported unit string for Angle parameters (`FirstAngle`/`SecondAngle`)."""

SUPPORTED_ANGLE_UNITS: frozenset[str] = frozenset({DEGREE})
"""Units accepted for Angle values (verified for `Shaft`/`Groove` `FirstAngle`/`SecondAngle`)."""

NAME_SEPARATOR: str = "\\"
"""Separator CATIA uses between a parameter's container path and its own name."""

REAL_KIND: str = "RealParam"
"""The `type(com_object).__name__` value for a CATIA unitless real parameter."""

INTEGER_KIND: str = "IntParam"
"""The `type(com_object).__name__` value for a CATIA integer parameter."""

STRING_KIND: str = "StrParam"
"""The `type(com_object).__name__` value for a CATIA string parameter."""

BOOLEAN_KIND: str = "BoolParam"
"""The `type(com_object).__name__` value for a CATIA boolean parameter."""

ANGLE_KIND: str = "Angle"
"""The `type(com_object).__name__` value for a CATIA Angle parameter."""

DIMENSION_KIND: str = "Dimension"
"""The `type(com_object).__name__` value for a generic (non-Length/Angle) Dimension.

Only `Length` and `Angle` get a derived wrapper type (verified,
docs/conventions.md 1.1.2); every other magnitude (`Mass`, `Volume`, `Time`,
...) comes back as this generic kind, so `type(obj).__name__` alone cannot
tell them apart -- see `Parameter.magnitude`.
"""

DIMENSIONAL_KINDS: frozenset[str] = frozenset({LENGTH_KIND, ANGLE_KIND, DIMENSION_KIND})
"""Kinds whose value is a physical quantity carrying a `Unit`."""


@dataclasses.dataclass(frozen=True)
class ParameterInfo:
    """Immutable snapshot of a parameter's identity and current state.

    Attributes:
        name: The parameter's name exactly as reported by CATIA. This may be
            container-qualified (``"3D Shape00422533\\Span"``) or bare
            (``"Span"``) depending on how the parameter was created.
        short_name: `name` with any container path stripped.
        kind: The COM wrapper type name (e.g. ``"Length"``).
        value: The parameter's current value.
        unit: The unit the value is expressed in, or `None` if unknown.
    """

    name: str
    short_name: str
    kind: str
    value: Any
    unit: str | None


class Parameter:
    """Wraps a raw CATIA `Parameter` COM object.

    `set()` supports every verified parameter kind: `Length`, `Angle`, generic
    `Dimension`, `RealParam`, `IntParam`, `StrParam`, and `BoolParam`. Any
    other kind can still be read (`name`, `kind`, `value`), but writing it is
    unverified and raises `ParameterTypeError`.
    """

    def __init__(self, com_object: Any, generation: ModelGeneration | None = None) -> None:
        """Initializes the wrapper.

        Args:
            com_object: The raw CATIA parameter COM object to wrap.
            generation: The owning Part's model generation, advanced by every
                write this wrapper makes. A wrapper built directly from a raw
                COM object gets its own, which nothing else shares.
        """
        self._com_object = com_object
        self._generation = generation if generation is not None else ModelGeneration()

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
        """Returns the parameter's name.

        Returns:
            The parameter's name as reported by CATIA.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Name
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def short_name(self) -> str:
        """Returns the parameter's name without its container path.

        CATIA reports `Name` differently depending on how the parameter was
        created: a parameter made by `Parameters.CreateDimension` reports a
        qualified ``"<container>\\<name>"``, while one added through the CATIA
        f(x) dialog reports just ``"<name>"``. This property normalises both to
        the trailing segment.

        Short names are not guaranteed unique once parameter sets are involved,
        so `name` remains the authoritative identifier.

        Returns:
            The segment of `name` after the last `NAME_SEPARATOR`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self.name.rsplit(NAME_SEPARATOR, 1)[-1]

    @property
    def kind(self) -> str:
        """Returns the parameter's kind.

        The kind is derived from the COM wrapper's type name (e.g.
        ``"Length"``), which is the verified way to identify a CATIA
        parameter type. CLSID and `_prop_map_get_` are not used.

        Returns:
            The `type(com_object).__name__` of the wrapped COM object.
        """
        return type(self._com_object).__name__

    @property
    def value(self) -> Any:
        """Returns the parameter's current value.

        Returns:
            The parameter's value, as reported by CATIA.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Value
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def magnitude(self) -> str | None:
        """Returns the physical magnitude this parameter's value is expressed in.

        Only `Length`/`Angle`/generic `Dimension` parameters carry a `Unit`;
        `RealParam`/`IntParam`/`StrParam`/`BoolParam` have none at all, and
        reading it fails (verified, docs/conventions.md 1.1.2). `Unit.Magnitude`
        is the only way to tell a generic `Dimension`'s actual quantity (e.g.
        `"Mass"` vs `"Volume"`) apart, since both share the same `kind`.

        Returns:
            `Unit.Magnitude` (e.g. `"Length"`, `"Mass"`), or `None` if the
            underlying COM object has no readable `Unit`.
        """
        try:
            return self._com_object.Unit.Magnitude
        except (AttributeError, pywintypes.com_error):
            return None

    @property
    def unit(self) -> str | None:
        """Returns the unit the parameter's value is expressed in.

        `Unit.Symbol` is tried first, since it is the verified way to read a
        dimensional parameter's actual unit (docs/conventions.md 1.1.2). Fakes
        used in unit tests, and the genuinely unitless kinds (`RealParam`,
        `IntParam`, `StrParam`, `BoolParam`), have no `Unit` at all, so this
        falls back to the pre-catalogue behaviour when reading it fails: this
        keeps existing fakes (which model a Length parameter as a plain object
        with only `Name`/`Value`) working unchanged.

        Returns:
            `Unit.Symbol` if readable, else `MILLIMETRE` when `kind` is
            `LENGTH_KIND`, else `None`.
        """
        try:
            return self._com_object.Unit.Symbol
        except (AttributeError, pywintypes.com_error):
            if self.kind == LENGTH_KIND:
                return MILLIMETRE
            return None

    def set(self, value: Any, unit: str | None = None) -> None:
        """Sets the parameter's value.

        Dispatches on `kind` (docs/conventions.md 6.15):

        - A dimensional kind (`LENGTH_KIND`, `ANGLE_KIND`, or generic
          `DIMENSION_KIND`) accepts an `int`/`float` (rejecting `bool`). If
          `unit` is given, it must equal this parameter's actual `unit` --
          auto_3dx never converts between units, so a mismatch is an error
          rather than a silent conversion. `unit=None` skips that check
          entirely, which is what makes `set(150)` and `set(150, unit="mm")`
          on a millimetre Length behave exactly as before this method grew
          multi-kind support.
        - `REAL_KIND` accepts an `int`/`float` (rejecting `bool`); `unit` must
          be `None`, since a `RealParam` has no unit at all.
        - `INTEGER_KIND` accepts an `int` (rejecting `bool`); `unit` must be
          `None`.
        - `STRING_KIND` accepts a `str`; `unit` must be `None`.
        - `BOOLEAN_KIND` accepts a `bool`; `unit` must be `None`.
        - Any other kind raises `ParameterTypeError`.

        This method does not call `Part.Update()`. Callers are expected to
        batch several `set()` calls and call `Part.Update()` once afterward.

        Args:
            value: The new value to assign. Its required type depends on
                `kind` (see above).
            unit: The unit `value` is expressed in, or `None` to skip the unit
                check entirely. Defaults to `None`.

        Raises:
            ParameterTypeError: If `kind` is not one of the supported kinds,
                or if `value` is not the type `kind` requires (`bool` is
                explicitly rejected for every numeric kind, since it is a
                subclass of `int`).
            UnsupportedUnitError: If `unit` is given but does not match this
                parameter's actual unit (dimensional kinds), or if `unit` is
                given at all for a kind that has none.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        kind = self.kind
        if kind in DIMENSIONAL_KINDS:
            coerced: Any = _coerce_numeric(value)
            self._check_unit_matches(unit)
        elif kind == REAL_KIND:
            coerced = _coerce_numeric(value)
            self._reject_unit(unit, kind)
        elif kind == INTEGER_KIND:
            coerced = _coerce_integer(value)
            self._reject_unit(unit, kind)
        elif kind == STRING_KIND:
            coerced = _coerce_string(value)
            self._reject_unit(unit, kind)
        elif kind == BOOLEAN_KIND:
            coerced = _coerce_boolean(value)
            self._reject_unit(unit, kind)
        else:
            raise ParameterTypeError(f"Parameter kind {kind!r} is not supported for set().")

        # The generation advances once this write is attempted, even if it raises
        # (`docs/api-design.md` section 5.3). It advances even when this parameter
        # drives nothing: the SDK cannot tell whether it feeds a formula that
        # feeds a feature dimension, so it assumes it might.
        with self._generation.mutation():
            try:
                self._com_object.Value = coerced
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error

    def _check_unit_matches(self, unit: str | None) -> None:
        """Checks `unit` (if given) against this dimensional parameter's actual unit.

        Args:
            unit: The caller-supplied unit, or `None` to skip the check.

        Raises:
            UnsupportedUnitError: If `unit` is given and does not equal
                `self.unit`.
        """
        if unit is None:
            return
        actual = self.unit
        if unit != actual:
            raise UnsupportedUnitError(
                f"Unit {unit!r} does not match this parameter's actual unit "
                f"({actual!r}); auto_3dx does not convert between units."
            )

    def _reject_unit(self, unit: str | None, kind: str) -> None:
        """Checks that no unit was supplied for a unitless parameter kind.

        Args:
            unit: The caller-supplied unit, or `None`.
            kind: This parameter's kind, used only for the error message.

        Raises:
            UnsupportedUnitError: If `unit` is not `None`.
        """
        if unit is not None:
            raise UnsupportedUnitError(f"Parameter kind {kind!r} has no unit; got unit={unit!r}.")

    def info(self) -> ParameterInfo:
        """Builds a structured snapshot of this parameter's current state.

        Returns:
            A `ParameterInfo` populated from `name`, `kind`, `value`, and
            `unit`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        name = self.name
        return ParameterInfo(
            name=name,
            short_name=name.rsplit(NAME_SEPARATOR, 1)[-1],
            kind=self.kind,
            value=self.value,
            unit=self.unit,
        )

    def __repr__(self) -> str:
        """Returns a debugging representation.

        Returns:
            A string such as ``Parameter(name='Span', kind='Length',
            value=1500.0)``.
        """
        try:
            name = self.name
            value = self.value
        except Auto3dxError:
            name = "<unavailable>"
            value = "<unavailable>"
        return f"Parameter(name={name!r}, kind={self.kind!r}, value={value!r})"


def _coerce_numeric(value: Any) -> float:
    """Checks a numeric value and coerces it to `float`.

    Shared by every dimensional kind and `REAL_KIND`.

    Args:
        value: The candidate value.

    Returns:
        `value` as a `float`.

    Raises:
        ParameterTypeError: If `value` is a `bool` or is not an `int`/`float`.
    """
    # bool is a subclass of int, so without this branch True would silently
    # become 1.0.
    if isinstance(value, bool):
        raise ParameterTypeError(f"Value must be an int or float, not bool ({value!r}).")
    if not isinstance(value, (int, float)):
        raise ParameterTypeError(f"Value must be an int or float, got {type(value).__name__}.")
    return float(value)


def _coerce_integer(value: Any) -> int:
    """Checks an `IntParam` value.

    Args:
        value: The candidate value.

    Returns:
        `value` unchanged.

    Raises:
        ParameterTypeError: If `value` is a `bool` or is not an `int`.
    """
    if isinstance(value, bool):
        raise ParameterTypeError(f"Value must be an int, not bool ({value!r}).")
    if not isinstance(value, int):
        raise ParameterTypeError(f"Value must be an int, got {type(value).__name__}.")
    return value


def _coerce_string(value: Any) -> str:
    """Checks a `StrParam` value.

    Args:
        value: The candidate value.

    Returns:
        `value` unchanged.

    Raises:
        ParameterTypeError: If `value` is not a `str`.
    """
    if not isinstance(value, str):
        raise ParameterTypeError(f"Value must be a str, got {type(value).__name__}.")
    return value


def _coerce_boolean(value: Any) -> bool:
    """Checks a `BoolParam` value.

    Args:
        value: The candidate value.

    Returns:
        `value` unchanged.

    Raises:
        ParameterTypeError: If `value` is not a `bool`.
    """
    if not isinstance(value, bool):
        raise ParameterTypeError(f"Value must be a bool, got {type(value).__name__}.")
    return value


def validate_length_unit(unit: str) -> None:
    """Checks that a unit is one this library can write a Length in.

    Args:
        unit: The unit string to check.

    Raises:
        UnsupportedUnitError: If `unit` is not a supported unit string.
    """
    # The isinstance guard comes first because `in` on a frozenset hashes the
    # candidate, so an unhashable unit would raise TypeError instead of
    # UnsupportedUnitError.
    if not isinstance(unit, str) or unit not in SUPPORTED_LENGTH_UNITS:
        raise UnsupportedUnitError(
            f"Unit {unit!r} is not supported; supported units are "
            f"{sorted(SUPPORTED_LENGTH_UNITS)}."
        )


def validate_length_value(value: float) -> float:
    """Checks a Length value and coerces it to `float`.

    Args:
        value: The candidate value.

    Returns:
        `value` as a `float`.

    Raises:
        ParameterTypeError: If `value` is a `bool` or is not an `int`/`float`.
    """
    return _coerce_numeric(value)


def validate_angle_unit(unit: str) -> None:
    """Checks that a unit is one this library can write an Angle in.

    Mirrors `validate_length_unit` exactly: the `isinstance` guard comes first
    for the same reason (an unhashable `unit` must not reach the frozenset
    membership test, which would raise `TypeError` instead of
    `UnsupportedUnitError`).

    Args:
        unit: The unit string to check.

    Raises:
        UnsupportedUnitError: If `unit` is not a supported unit string.
    """
    if not isinstance(unit, str) or unit not in SUPPORTED_ANGLE_UNITS:
        raise UnsupportedUnitError(
            f"Unit {unit!r} is not supported; supported units are "
            f"{sorted(SUPPORTED_ANGLE_UNITS)}."
        )


def validate_angle_value(value: float) -> float:
    """Checks an Angle value and coerces it to `float`.

    Mirrors `validate_length_value` exactly, including the explicit `bool`
    rejection before the `int`/`float` check (`bool` is a subclass of `int`,
    so without it `True` would silently become `1.0`).

    Args:
        value: The candidate value.

    Returns:
        `value` as a `float`.

    Raises:
        ParameterTypeError: If `value` is a `bool` or is not an `int`/`float`.
    """
    return _coerce_numeric(value)


def validate_parameter_name(name: str) -> str:
    """Checks that a requested new-parameter name is addressable afterwards.

    CATIA accepts names the caller cannot then reliably look up: an empty name
    is auto-numbered (``Length.3``), and a name containing the container
    separator produces something indistinguishable from a qualified name. Both
    are rejected here rather than silently creating an unreachable parameter.

    Args:
        name: The requested parameter name.

    Returns:
        `name` unchanged.

    Raises:
        ParameterNameError: If `name` is not a non-empty `str` without
            surrounding whitespace and without `NAME_SEPARATOR`.
    """
    if not isinstance(name, str):
        raise ParameterNameError(f"Parameter name must be a str, got {type(name).__name__}.")
    if not name or name != name.strip():
        raise ParameterNameError(
            f"Parameter name must be non-empty and free of surrounding "
            f"whitespace, got {name!r}."
        )
    if NAME_SEPARATOR in name:
        raise ParameterNameError(
            f"Parameter name must not contain {NAME_SEPARATOR!r}, which CATIA "
            f"uses as the container separator, got {name!r}."
        )
    return name


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
