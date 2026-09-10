"""Unit tests for `auto_3dx.transport.windows_com.find_com3dx_path`.

Per docs/conventions.md section 1/5, an explicit path or environment variable
that does not point at an existing file must raise `Com3dxNotFoundError`
rather than silently falling back to a different candidate (e.g. the
registry-discovered release). These tests never touch the real registry or
a real installation, and never import the real `com3dx.py`.
"""

from pathlib import Path

import pytest

from auto_3dx.errors import Com3dxNotFoundError
from auto_3dx.transport.windows_com import COM3DX_PATH_ENV_VAR, find_com3dx_path


@pytest.fixture
def real_temp_file(tmp_path: Path) -> Path:
    """A real file on disk, standing in for a valid `com3dx.py` location."""
    fake_com3dx = tmp_path / "com3dx.py"
    fake_com3dx.write_text("# fake com3dx.py for tests\n", encoding="utf-8")
    return fake_com3dx


def test_find_com3dx_path_explicit_path_exists_returns_that_path(
    real_temp_file: Path,
) -> None:
    """An explicit path to a real file is returned as-is."""
    assert find_com3dx_path(real_temp_file) == real_temp_file


def test_find_com3dx_path_explicit_path_missing_raises_without_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, real_temp_file: Path
) -> None:
    """A bad explicit path raises, even when a valid env var fallback exists.

    This pins the "no silent fallback to a different release" rule: the
    explicit path is authoritative, so it must not be quietly ignored in
    favor of `AUTO_3DX_COM3DX_PATH`.
    """
    monkeypatch.setenv(COM3DX_PATH_ENV_VAR, str(real_temp_file))
    missing_path = tmp_path / "does_not_exist" / "com3dx.py"

    with pytest.raises(Com3dxNotFoundError):
        find_com3dx_path(missing_path)


def test_find_com3dx_path_env_var_set_to_real_file_is_used(
    monkeypatch: pytest.MonkeyPatch, real_temp_file: Path
) -> None:
    """`AUTO_3DX_COM3DX_PATH` is used when no explicit path is given."""
    monkeypatch.setenv(COM3DX_PATH_ENV_VAR, str(real_temp_file))

    assert find_com3dx_path() == real_temp_file


def test_find_com3dx_path_env_var_set_to_missing_file_raises_mentioning_var_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A nonexistent `AUTO_3DX_COM3DX_PATH` raises, mentioning the variable name."""
    missing_path = tmp_path / "does_not_exist" / "com3dx.py"
    monkeypatch.setenv(COM3DX_PATH_ENV_VAR, str(missing_path))

    with pytest.raises(Com3dxNotFoundError) as exc_info:
        find_com3dx_path()

    assert COM3DX_PATH_ENV_VAR in str(exc_info.value)
