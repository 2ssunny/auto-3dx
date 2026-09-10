"""Wrapper around a single CATIA `Parameter` COM object.

This module provides :class:`Parameter`, a thin wrapper that isolates callers
from raw COM access, and :class:`ParameterInfo`, a frozen dataclass snapshot
of a parameter's state for callers (including agents) that want structured
data instead of a printed string.
"""

import dataclasses
from typing import Any

import pywintypes

from auto_3dx.errors import Auto3dxError, ParameterTypeError, UnsupportedUnitError

LENGTH_KIND: str = "Length"
"""The `type(com_object).__name__` value for a CATIA Length parameter."""

MILLIMETRE: str = "mm"
"""The only supported unit string for Length parameters."""

SUPPORTED_LENGTH_UNITS: frozenset[str] = frozenset({MILLIMETRE})
"""Units accepted by :meth:`Parameter.set` for Length parameters."""


@dataclasses.dataclass(frozen=True)
class ParameterInfo:
    """Immutable snapshot of a parameter's identity and current state.

    Attributes:
        name: The parameter's name, as reported by CATIA.
        kind: The COM wrapper type name (e.g. ``"Length"``).
        value: The parameter's current value.
        unit: The unit the value is expressed in, or `None` if unknown.
    """

    name: str
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
        # The isinstance guard comes first because `in` on a frozenset hashes the
        # candidate, so an unhashable unit would raise TypeError instead of
        # UnsupportedUnitError.
        if not isinstance(unit, str) or unit not in SUPPORTED_LENGTH_UNITS:
            raise UnsupportedUnitError(
                f"Unit {unit!r} is not supported; supported units are "
                f"{sorted(SUPPORTED_LENGTH_UNITS)}."
            )
        if isinstance(value, bool):
            raise ParameterTypeError(
                f"Value must be an int or float, not bool ({value!r})."
            )
        if not isinstance(value, (int, float)):
            raise ParameterTypeError(
                f"Value must be an int or float, got {type(value).__name__}."
            )
        try:
            self._com_object.Value = float(value)
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
        return ParameterInfo(
            name=self.name,
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
