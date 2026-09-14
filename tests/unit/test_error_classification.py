"""Tests that errors are classified by when they happen (`docs/api-design.md` 8).

Four modules used to keep their own copy of the COM translator, each returning a bare
`Auto3dxError`, and several guards raised `Auto3dxError` directly. A caller could not
tell "rejected before CATIA was touched" from "CATIA failed and the model may have
changed". These tests pin the rule that separates them: before any COM call is a
`ValidationError`, after one is an `AutomationError` carrying the HRESULT.
"""

from typing import Any

import pytest
import pywintypes

from auto_3dx import _com
from auto_3dx.errors import AutomationError, ValidationError
from auto_3dx.formulas import formula as formula_module
from auto_3dx.geometry import constraint as constraint_module
from auto_3dx.geometry import sketch as sketch_module
from auto_3dx.geometry.deletion import delete_via_selection
from auto_3dx.geometry.sketch import Sketch, _wrap_constraint_com_error
from auto_3dx.parameters import parameter as parameter_module
from auto_3dx.parameters.parameter import Parameter

HRESULT_EXCEPTION_OCCURRED = -2147352567


def _com_error() -> pywintypes.com_error:
    """Builds the COM error CATIA raises for a failed call."""
    return pywintypes.com_error(HRESULT_EXCEPTION_OCCURRED, "Exception occurred.", None, None)


# --- One translator -----------------------------------------------------------------


@pytest.mark.parametrize(
    "module", [sketch_module, constraint_module, parameter_module, formula_module]
)
def test_every_module_translates_through_the_shared_translator(module: Any) -> None:
    """The old private copies are gone; each name now points at the one translator."""
    assert module._wrap_com_error is _com.automation_error


def test_a_parameter_com_failure_is_an_automation_error_with_its_code() -> None:
    """A failed read reaches the caller as CATIA's failure, with the HRESULT as data."""

    class _FailingLength:
        @property
        def Value(self) -> float:  # noqa: N802 - COM property name
            raise _com_error()

    with pytest.raises(AutomationError) as caught:
        _ = Parameter(_FailingLength()).value

    assert caught.value.hresult == HRESULT_EXCEPTION_OCCURRED
    assert isinstance(caught.value.__cause__, pywintypes.com_error)


def test_a_constraint_creation_failure_keeps_its_hint_and_its_code() -> None:
    """The specialised message survives, and the HRESULT is now data too."""
    error = _wrap_constraint_com_error(_com_error())

    assert isinstance(error, AutomationError)
    assert error.hresult == HRESULT_EXCEPTION_OCCURRED
    assert "Sketch.edit()" in str(error)


# --- Before any COM call ---------------------------------------------------------------


class _Factory2D:
    """Fake `Factory2D` that fails the test if geometry reaches COM."""

    def CreateLine(self, *arguments: float) -> Any:  # noqa: N802 - COM method name
        raise AssertionError("a rejected request must not reach CreateLine")


class _SketchComObject:
    """Fake CATIA `Sketch` supporting one edition session."""

    def __init__(self) -> None:
        self.Name = "Profile"
        self.Constraints = object()

    def OpenEdition(self) -> _Factory2D:  # noqa: N802 - COM method name
        return _Factory2D()

    def CloseEdition(self) -> None:  # noqa: N802 - COM method name
        pass


def test_using_an_editor_after_its_block_is_a_validation_error() -> None:
    """The editor is refused before COM, so the model is untouched."""
    sketch = Sketch(_SketchComObject())
    with sketch.edit() as editor:
        pass

    with pytest.raises(ValidationError, match="no longer active"):
        editor.line(0.0, 0.0, 1.0, 1.0)


def test_re_entering_a_sketch_edit_is_a_validation_error() -> None:
    """Nested editions are refused at entry, before a second OpenEdition()."""
    sketch = Sketch(_SketchComObject())

    with sketch.edit(), pytest.raises(ValidationError, match="already being edited"):
        with sketch.edit():
            pass


def test_deleting_without_a_selection_is_a_validation_error() -> None:
    """No selection means nothing was attempted."""
    with pytest.raises(ValidationError):
        delete_via_selection(None, object(), "sketch 'Profile'")


# --- After a COM call ------------------------------------------------------------------


class _FailingDeleteSelection:
    """Fake `Selection` whose delete fails while clearing still works."""

    def Clear(self) -> None:  # noqa: N802 - COM method name
        pass

    def Add(self, item: Any) -> None:  # noqa: N802 - COM method name
        pass

    def Delete(self) -> None:  # noqa: N802 - COM method name
        raise _com_error()


def test_a_failed_delete_is_an_automation_error_with_its_code() -> None:
    """The delete was attempted, so the caller must treat the model as possibly changed."""
    with pytest.raises(AutomationError) as caught:
        delete_via_selection(_FailingDeleteSelection(), object(), "sketch 'Profile'")

    assert caught.value.hresult == HRESULT_EXCEPTION_OCCURRED
    assert isinstance(caught.value.__cause__, pywintypes.com_error)
    assert not isinstance(caught.value, ValidationError)
