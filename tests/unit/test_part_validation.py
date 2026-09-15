"""Unit tests for the verified `Part.is_up_to_date` boundary."""

from typing import Any

import pywintypes
import pytest

from auto_3dx.core.part import Part
from auto_3dx.errors import Auto3dxError


class _RawPart:
    """Fake Part recording status queries and forbidden mutations."""

    def __init__(self, result: Any = True, error: Exception | None = None) -> None:
        """Initializes the configured status result."""
        self.result = result
        self.error = error
        self.targets: list[Any] = []
        self.update_calls = 0
        self.save_calls = 0

    def IsUpToDate(self, target: Any) -> Any:
        """Records and answers one status query."""
        self.targets.append(target)
        if self.error is not None:
            raise self.error
        return self.result

    def Update(self) -> None:
        """Records a forbidden implicit update."""
        self.update_calls += 1

    def Save(self) -> None:
        """Records a forbidden persistence call."""
        self.save_calls += 1


class _Wrapper:
    """Minimal public-wrapper shape exposing a raw COM object."""

    def __init__(self, com_object: Any) -> None:
        """Stores the wrapped object."""
        self.com_object = com_object


@pytest.mark.parametrize("result", [True, False])
def test_is_up_to_date_returns_catias_boolean(result: bool) -> None:
    """Both verified boolean states pass through unchanged."""
    raw_part = _RawPart(result=result)

    assert Part(raw_part).is_up_to_date() is result
    assert raw_part.targets == [raw_part]
    assert raw_part.update_calls == 0
    assert raw_part.save_calls == 0


def test_is_up_to_date_unwraps_an_auto_3dx_wrapper() -> None:
    """A wrapper target contributes its raw com_object."""
    raw_part = _RawPart()
    raw_target = object()

    assert Part(raw_part).is_up_to_date(_Wrapper(raw_target)) is True
    assert raw_part.targets == [raw_target]


def test_is_up_to_date_accepts_a_raw_target() -> None:
    """Raw CATIA dispatch objects are passed through unchanged."""
    raw_part = _RawPart()
    raw_target = object()

    assert Part(raw_part).is_up_to_date(raw_target) is True
    assert raw_part.targets == [raw_target]


def test_is_up_to_date_converts_com_error_with_hresult() -> None:
    """A pywin32 failure never escapes the core boundary."""
    error = pywintypes.com_error(-2147352567, "Exception occurred.", None, None)

    with pytest.raises(Auto3dxError, match="0x80020009"):
        Part(_RawPart(error=error)).is_up_to_date()


@pytest.mark.parametrize(
    "error", [AttributeError("no such member"), TypeError("bad argument")]
)
def test_is_up_to_date_reports_an_unusable_member_as_auto3dx_error(
    error: Exception,
) -> None:
    """A release without the member, or one rejecting the argument, is mapped.

    `Shapes.Remove` turned out not to exist at all in this release, so a
    missing or argument-rejecting member is a real possibility rather than a
    theoretical one, and must not reach the caller as a bare Python error.
    """
    with pytest.raises(Auto3dxError, match="unusable in this release"):
        Part(_RawPart(error=error)).is_up_to_date()


def test_is_up_to_date_does_not_disguise_an_unrelated_bug() -> None:
    """Anything else propagates, so a bug here is not reported as a CATIA failure."""
    with pytest.raises(RuntimeError, match="boom"):
        Part(_RawPart(error=RuntimeError("boom"))).is_up_to_date()


@pytest.mark.parametrize("result", [1, 0, None, "True", (True,)])
def test_is_up_to_date_rejects_non_boolean_results(result: Any) -> None:
    """The live-verified bool contract is enforced at the boundary."""
    with pytest.raises(Auto3dxError, match="non-boolean"):
        Part(_RawPart(result=result)).is_up_to_date()
