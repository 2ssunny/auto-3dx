"""Unit tests for `auto_3dx.parameters.parameter.Parameter`.

See docs/conventions.md sections 6.5 (contract) and the `set()` validation
order table: kind check, then unit check, then `bool` rejection, then
`int`/`float` check.
"""

from collections.abc import Callable
from typing import Any

import pytest

from auto_3dx.errors import ParameterTypeError, UnsupportedUnitError
from auto_3dx.parameters.parameter import MILLIMETRE, Parameter, ParameterInfo


def test_parameter_kind_length_fake_reports_length(fake_length: Any) -> None:
    """`kind` is derived from the fake COM class name, here `"Length"`."""
    parameter = Parameter(fake_length)
    assert parameter.kind == "Length"


def test_parameter_kind_non_length_fake_reports_its_class_name(fake_real: Any) -> None:
    """`kind` reflects whatever class name the fake COM object has."""
    parameter = Parameter(fake_real)
    assert parameter.kind == "Real"


def test_parameter_unit_length_is_millimetre(fake_length: Any) -> None:
    """A Length parameter's `unit` is `"mm"`."""
    parameter = Parameter(fake_length)
    assert parameter.unit == MILLIMETRE


def test_parameter_unit_non_length_is_none(fake_real: Any) -> None:
    """A non-Length parameter's `unit` is `None` (unverified)."""
    parameter = Parameter(fake_real)
    assert parameter.unit is None


def test_parameter_set_length_writes_float_value(fake_length: Any) -> None:
    """`set(150)` writes `150.0` (a `float`) to the underlying `Value`."""
    parameter = Parameter(fake_length)

    parameter.set(150)

    assert fake_length.Value == 150.0
    assert isinstance(fake_length.Value, float)


def test_parameter_set_non_length_raises_parameter_type_error(fake_real: Any) -> None:
    """`set()` on a non-Length parameter raises `ParameterTypeError`."""
    parameter = Parameter(fake_real)

    with pytest.raises(ParameterTypeError):
        parameter.set(150)


def test_parameter_set_unsupported_unit_raises_unsupported_unit_error(
    fake_length: Any,
) -> None:
    """`set(150, unit="inch")` raises `UnsupportedUnitError`."""
    parameter = Parameter(fake_length)

    with pytest.raises(UnsupportedUnitError):
        parameter.set(150, unit="inch")


def test_parameter_set_bool_value_raises_parameter_type_error(fake_length: Any) -> None:
    """`set(True)` raises `ParameterTypeError`.

    `bool` is a subclass of `int` in Python, so a naive
    `isinstance(value, (int, float))` check would silently accept it and
    coerce it to `0.0`/`1.0`. This is a real trap the implementation must
    guard against explicitly.
    """
    parameter = Parameter(fake_length)
    original_value = fake_length.Value

    with pytest.raises(ParameterTypeError):
        parameter.set(True)

    assert fake_length.Value == original_value


def test_parameter_set_string_value_raises_parameter_type_error(fake_length: Any) -> None:
    """`set("150")` raises `ParameterTypeError` -- numeric strings are not accepted."""
    parameter = Parameter(fake_length)

    with pytest.raises(ParameterTypeError):
        parameter.set("150")


def test_parameter_set_valid_length_does_not_call_part_update(
    fake_length: Any, part_factory: Callable[..., Any]
) -> None:
    """`set()` never touches `Part.Update()`.

    The fake `Part` here is otherwise unrelated to the parameter being set:
    it exists purely as a witness. If `Parameter.set()` ever grew a hidden
    dependency on updating the part, this test would catch it.
    """
    part = part_factory()
    parameter = Parameter(fake_length)

    parameter.set(150)

    assert part.update_calls == 0


def test_parameter_info_returns_matching_parameter_info(fake_length: Any) -> None:
    """`info()` returns a `ParameterInfo` with matching name/kind/value/unit."""
    parameter = Parameter(fake_length)

    info = parameter.info()

    assert info == ParameterInfo(
        name=fake_length.Name,
        kind="Length",
        value=fake_length.Value,
        unit=MILLIMETRE,
    )
