"""Regression tests pinning the fixes for the code-review findings.

Each test here corresponds to a defect that was found by review rather than by
the original test suite, so the behaviour is locked in explicitly.
"""

import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import pywintypes

from auto_3dx.errors import (
    Auto3dxError,
    CatiaConnectionError,
    ParameterNotFoundError,
    UnsupportedUnitError,
)
from auto_3dx.parameters.collection import ParameterCollection
from auto_3dx.parameters.parameter import Parameter
from auto_3dx.transport import windows_com

from tests.conftest import make_com_error


class _CountFails:
    """Fake `Parameters` collection whose `Count` raises a COM error."""

    @property
    def Count(self) -> int:
        raise make_com_error()

    def Item(self, key: Any) -> Any:
        raise AssertionError("Item must not be reached when Count fails.")


class _ItemByIndexFails:
    """Fake `Parameters` collection that reports items but fails on `Item(i)`."""

    def __init__(self, count: int = 2) -> None:
        self._count = count

    @property
    def Count(self) -> int:
        return self._count

    def Item(self, key: Any) -> Any:
        raise make_com_error()


def test_count_converts_com_error_to_auto3dx_error() -> None:
    """`count` must not leak a raw `com_error` out of the library."""
    collection = ParameterCollection(_CountFails())

    with pytest.raises(Auto3dxError) as caught:
        collection.count

    assert not isinstance(caught.value, pywintypes.com_error)
    assert isinstance(caught.value.__cause__, pywintypes.com_error)


def test_len_and_iter_convert_com_error_to_auto3dx_error() -> None:
    """The dunder methods route through `count`, so they must convert too."""
    collection = ParameterCollection(_CountFails())

    with pytest.raises(Auto3dxError):
        len(collection)

    with pytest.raises(Auto3dxError):
        iter(collection)


def test_repr_survives_a_failing_count() -> None:
    """`repr()` is a debugging aid and must never raise."""
    collection = ParameterCollection(_CountFails())

    assert "unavailable" in repr(collection)


def test_positional_item_failure_is_not_reported_as_not_found() -> None:
    """A failing `Item(i)` is a COM fault, not a missing-name lookup."""
    collection = ParameterCollection(_ItemByIndexFails())

    with pytest.raises(Auto3dxError) as caught:
        collection.list()

    assert not isinstance(caught.value, ParameterNotFoundError)
    assert isinstance(caught.value.__cause__, pywintypes.com_error)


def test_unhashable_unit_raises_unsupported_unit_error(fake_length: Any) -> None:
    """`in` on a frozenset hashes its operand, so an unhashable unit must be
    rejected before the membership test rather than raising `TypeError`."""
    parameter = Parameter(fake_length)

    with pytest.raises(UnsupportedUnitError):
        parameter.set(1.0, unit=[])  # type: ignore[arg-type]

    assert fake_length.Value == 100.0


def test_non_string_unit_raises_unsupported_unit_error(fake_length: Any) -> None:
    """A hashable but non-string unit is also an unsupported unit."""
    parameter = Parameter(fake_length)

    with pytest.raises(UnsupportedUnitError):
        parameter.set(1.0, unit=1)  # type: ignore[arg-type]

    assert fake_length.Value == 100.0


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_env_var_is_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
    blank: str,
) -> None:
    """A cleared shell variable must not hard-fail path discovery.

    A blank value is almost never a deliberate configuration choice, so it falls
    through to registry discovery instead of raising.
    """
    monkeypatch.setenv(windows_com.COM3DX_PATH_ENV_VAR, blank)

    assert windows_com._path_from_env() is None


def test_configured_env_var_is_stripped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Surrounding whitespace around a real path must not break resolution."""
    helper = tmp_path / "com3dx.py"
    helper.write_text("", encoding="utf-8")
    monkeypatch.setenv(windows_com.COM3DX_PATH_ENV_VAR, f"  {helper}  ")

    assert windows_com.find_com3dx_path() == helper


@pytest.fixture
def restore_com3dx_module() -> Iterator[None]:
    """Removes any `com3dx` entry this test session put into `sys.modules`."""
    original = sys.modules.get("com3dx")
    try:
        yield
    finally:
        if original is None:
            sys.modules.pop("com3dx", None)
        else:
            sys.modules["com3dx"] = original


def _write_stub_helper(directory: Path) -> Path:
    """Writes a harmless stand-in for the installed `com3dx.py`."""
    helper = directory / "com3dx.py"
    helper.write_text("def get3dxClient(**kwargs):\n    return None\n", encoding="utf-8")
    return helper


def test_load_com3dx_caches_the_module(
    tmp_path: Path,
    restore_com3dx_module: None,
) -> None:
    """A second load of the same file must reuse the one module instance."""
    helper = _write_stub_helper(tmp_path)

    first = windows_com.load_com3dx(helper)
    second = windows_com.load_com3dx(helper)

    assert first is second
    assert sys.modules["com3dx"] is first


def test_load_com3dx_refuses_a_second_release(
    tmp_path: Path,
    restore_com3dx_module: None,
) -> None:
    """Two releases' generated COM wrappers must never share one process."""
    first_release = tmp_path / "r1"
    second_release = tmp_path / "r2"
    first_release.mkdir()
    second_release.mkdir()
    windows_com.load_com3dx(_write_stub_helper(first_release))

    with pytest.raises(CatiaConnectionError) as caught:
        windows_com.load_com3dx(_write_stub_helper(second_release))

    assert "different 3DEXPERIENCE release" in str(caught.value)


def test_load_com3dx_rolls_back_a_failed_import(
    tmp_path: Path,
    restore_com3dx_module: None,
) -> None:
    """A failed exec must leave no half-built module behind.

    Rolling back is safe because `com3dx.py` only records the original
    `Dispatch`/`hasattr` at module level; it installs its replacements later,
    inside `com3dxInit()`.
    """
    helper = tmp_path / "com3dx.py"
    helper.write_text("raise RuntimeError('boom')\n", encoding="utf-8")

    with pytest.raises(CatiaConnectionError) as caught:
        windows_com.load_com3dx(helper)

    assert isinstance(caught.value.__cause__, RuntimeError)
    assert "com3dx" not in sys.modules


def test_load_com3dx_holds_a_lock(
    tmp_path: Path,
    restore_com3dx_module: None,
) -> None:
    """The check-create-execute sequence must be serialised.

    Two threads that both miss the cache would otherwise execute `com3dx.py`
    twice, or one could observe the module the other published to `sys.modules`
    before its execution finished.
    """
    helper = _write_stub_helper(tmp_path)
    results: list[Any] = []

    original_module_from_spec = windows_com.importlib.util.module_from_spec

    def _record(*args: Any, **kwargs: Any) -> Any:
        assert windows_com._LOAD_LOCK.locked()
        return original_module_from_spec(*args, **kwargs)

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(windows_com.importlib.util, "module_from_spec", _record)
        results.append(windows_com.load_com3dx(helper))
    finally:
        monkeypatch.undo()

    assert results[0] is sys.modules["com3dx"]


def test_set_via_collection_rejects_unhashable_unit(
    parameters_collection_factory: Callable[..., Any],
    fake_length: Any,
) -> None:
    """The collection delegates to `Parameter.set`, so it inherits the guard."""
    collection = ParameterCollection(
        parameters_collection_factory([(fake_length.Name, fake_length)])
    )

    with pytest.raises(UnsupportedUnitError):
        collection.set(fake_length.Name, 1.0, unit=[])  # type: ignore[arg-type]

    assert fake_length.Value == 100.0
