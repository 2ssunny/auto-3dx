"""Wrapper around a single CATIA `Parameter` COM object.

This module provides :class:`Parameter`, a thin wrapper that isolates callers
from raw COM access, and :class:`ParameterInfo`, a frozen dataclass snapshot
of a parameter's state for callers (including agents) that want structured
data instead of a printed string.
"""

import dataclasses
from typing import Any

import pywintypes

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

MILLIMETRE: str = "mm"
"""The only supported unit string for Length parameters."""

SUPPORTED_LENGTH_UNITS: frozenset[str] = frozenset({MILLIMETRE})
"""Units accepted by :meth:`Parameter.set` for Length parameters."""

NAME_SEPARATOR: str = "\\"
"""Separator CATIA uses between a parameter's container path and its own name."""


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

    Only Length parameters support writing through :meth:`set`. Other kinds
    can still be read (`name`, `kind`, `value`), but their unit is unverified
    and therefore reported as `None`.
    """

    def __init__(self, com_object: Any) -> None:
        """Initializes the wrapper.

        Args:
            com_object: The raw CATIA parameter COM object to wrap.
        """
        self._com_object = com_object

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
    def unit(self) -> str | None:
        """Returns the unit the parameter's value is expressed in.

        Only Length parameters have a verified unit. Any other kind returns
        `None` rather than a guessed unit.

        Returns:
            `MILLIMETRE` when `kind` is `LENGTH_KIND`, otherwise `None`.
        """
        if self.kind == LENGTH_KIND:
            return MILLIMETRE
        return None

    def set(self, value: float, unit: str = MILLIMETRE) -> None:
        """Sets the parameter's value.

        Only Length parameters can be set. Validation happens in this exact
        order: kind, then unit, then value type (rejecting `bool` explicitly
        before the `int`/`float` check, since `bool` is a subclass of `int`
        and would otherwise silently become `0.0`/`1.0`).

        This method does not call `Part.Update()`. Callers are expected to
        batch several `set()` calls and call `Part.Update()` once afterward.

        Args:
            value: The new numeric value to assign.
            unit: The unit `value` is expressed in. Defaults to `MILLIMETRE`.

        Raises:
            ParameterTypeError: If the parameter's kind is not `LENGTH_KIND`,
                or if `value` is not an `int`/`float` (or is a `bool`).
            UnsupportedUnitError: If `unit` is not in `SUPPORTED_LENGTH_UNITS`.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        kind = self.kind
        if kind != LENGTH_KIND:
            raise ParameterTypeError(
                f"Parameter kind {kind!r} is not supported for set(); "
                f"only {LENGTH_KIND!r} parameters can be set."
            )
        validate_length_unit(unit)
        coerced = validate_length_value(value)
        try:
            self._com_object.Value = coerced
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

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
    # bool is a subclass of int, so without this branch True would silently
    # become 1.0.
    if isinstance(value, bool):
        raise ParameterTypeError(f"Value must be an int or float, not bool ({value!r}).")
    if not isinstance(value, (int, float)):
        raise ParameterTypeError(
            f"Value must be an int or float, got {type(value).__name__}."
        )
    return float(value)


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
        raise ParameterNameError(
            f"Parameter name must be a str, got {type(name).__name__}."
        )
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
