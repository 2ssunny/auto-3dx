"""Tests for the exception hierarchy contract (`docs/api-design.md` section 8).

Errors are grouped by what a caller can do about them. These tests pin every
concrete class to its category, so a new error cannot be added without deciding
which category it belongs to, and so a class cannot silently move between
categories -- which would change what `except ValidationError` means for callers.
"""

import inspect

import pytest
import pywintypes

from auto_3dx import _com, errors

CATEGORIES = {
    "SessionError": {
        "Com3dxNotFoundError",
        "CatiaConnectionError",
        "NoActiveEditorError",
        "NoActivePartError",
    },
    "ValidationError": {
        "ParameterNameError",
        "ParameterTypeError",
        "UnsupportedUnitError",
        "UnsupportedMagnitudeError",
        "UnsupportedSupportError",
        "StaleSnapshotError",
    },
    "NotFoundError": {
        "ParameterNotFoundError",
        "SketchNotFoundError",
        "FeatureNotFoundError",
        "FormulaNotFoundError",
        "ConstraintNotFoundError",
    },
    "ConflictError": {
        "ParameterAlreadyExistsError",
        "SketchAlreadyExistsError",
        "FormulaAlreadyExistsError",
        "FeatureConflictError",
        "SketchSupportMismatchError",
        "AmbiguousNameError",
    },
    "AutomationError": {
        "PartUpdateError",
        "PartialCreationError",
    },
}
HRESULT_EXCEPTION_OCCURRED = -2147352567


def _error_classes() -> "dict[str, type]":
    """Every exception class defined in `auto_3dx.errors`."""
    return {
        name: value
        for name, value in vars(errors).items()
        if inspect.isclass(value)
        and issubclass(value, BaseException)
        and value.__module__ == errors.__name__
    }


def test_every_category_derives_directly_from_the_base() -> None:
    """The categories are the second level of the hierarchy, nothing in between."""
    for category in CATEGORIES:
        assert getattr(errors, category).__bases__ == (errors.Auto3dxError,)


def test_the_base_derives_from_exception() -> None:
    """Callers catching `Exception` still catch everything the SDK raises."""
    assert errors.Auto3dxError.__bases__ == (Exception,)


@pytest.mark.parametrize(
    ("category", "member"),
    [(category, member) for category, members in CATEGORIES.items() for member in members],
)
def test_each_error_belongs_to_its_documented_category(category: str, member: str) -> None:
    """A class moving between categories changes what callers catch."""
    assert getattr(errors, member).__bases__ == (getattr(errors, category),)


def test_every_error_class_is_accounted_for() -> None:
    """A new error must be placed in a category deliberately, not by accident."""
    documented = {"Auto3dxError", *CATEGORIES, *(m for ms in CATEGORIES.values() for m in ms)}

    assert set(_error_classes()) == documented


def test_automation_error_carries_the_hresult() -> None:
    """The code survives as data, not only inside the message."""
    error = errors.AutomationError("failed.", HRESULT_EXCEPTION_OCCURRED)

    assert error.hresult == HRESULT_EXCEPTION_OCCURRED
    assert str(error) == "failed."


def test_automation_subclasses_still_take_a_bare_message() -> None:
    """Existing raise sites pass only a message, and must keep working."""
    error = errors.PartUpdateError("Part.Update() failed.")

    assert error.hresult is None


def test_translation_builds_an_automation_error_with_the_code() -> None:
    """One translation, one message shape, and the HRESULT as an attribute."""
    com_error = pywintypes.com_error(HRESULT_EXCEPTION_OCCURRED, "Exception occurred.", None, None)

    error = _com.automation_error(com_error, "reading Part.Name")

    assert isinstance(error, errors.AutomationError)
    assert error.hresult == HRESULT_EXCEPTION_OCCURRED
    assert str(error) == (
        "Unexpected COM failure while reading Part.Name (HRESULT=0x80020009)."
    )


def test_translation_without_an_action_still_names_the_code() -> None:
    """A call site with nothing more specific to say still reports the HRESULT."""
    com_error = pywintypes.com_error(HRESULT_EXCEPTION_OCCURRED, "Exception occurred.", None, None)

    assert str(_com.automation_error(com_error)) == (
        "Unexpected COM failure (HRESULT=0x80020009)."
    )


def test_translation_tolerates_an_error_without_a_code() -> None:
    """Not every COM error carries an integer first argument."""
    com_error = pywintypes.com_error("no code")

    error = _com.automation_error(com_error)

    assert error.hresult is None
    assert "HRESULT=unknown" in str(error)
