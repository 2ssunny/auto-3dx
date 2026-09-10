"""Unit tests for `auto_3dx.errors` -- the exception hierarchy contract.

See docs/conventions.md section 5 / 6.1: every error subclasses
`Auto3dxError`, which subclasses `Exception`, and exactly these 9 names must
be importable from `auto_3dx.errors`.
"""

import pytest

from auto_3dx import errors

ERROR_CLASS_NAMES = [
    "Auto3dxError",
    "Com3dxNotFoundError",
    "CatiaConnectionError",
    "NoActiveEditorError",
    "NoActivePartError",
    "ParameterNotFoundError",
    "ParameterTypeError",
    "UnsupportedUnitError",
    "PartUpdateError",
]


def test_errors_module_exposes_all_nine_names() -> None:
    """All 9 names from conventions.md 6.1 exist and are importable."""
    for class_name in ERROR_CLASS_NAMES:
        assert hasattr(errors, class_name), f"auto_3dx.errors is missing {class_name!r}."


def test_auto3dx_error_subclasses_exception() -> None:
    """`Auto3dxError` subclasses the builtin `Exception`."""
    assert issubclass(errors.Auto3dxError, Exception)


@pytest.mark.parametrize(
    "class_name",
    [name for name in ERROR_CLASS_NAMES if name != "Auto3dxError"],
)
def test_error_subclass_subclasses_auto3dx_error(class_name: str) -> None:
    """Every non-base error class subclasses `Auto3dxError`."""
    error_class = getattr(errors, class_name)
    assert issubclass(error_class, errors.Auto3dxError)


def test_error_instances_are_raisable_and_catchable_as_auto3dx_error() -> None:
    """Any concrete error can be raised and caught via the common base class."""
    for class_name in ERROR_CLASS_NAMES:
        error_class = getattr(errors, class_name)
        with pytest.raises(errors.Auto3dxError):
            raise error_class("boom.")
