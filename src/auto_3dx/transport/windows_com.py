import importlib.util
import os
import re
import sys
import winreg
from pathlib import Path
from types import ModuleType
from typing import Any

from pywintypes import com_error

from auto_3dx.errors import CatiaConnectionError, Com3dxNotFoundError

COM3DX_PATH_ENV_VAR = "AUTO_3DX_COM3DX_PATH"

_APPLICATION_PROG_ID = "CATIA.Application"
_LOCAL_SERVER_KEY_TEMPLATE = r"CLSID\{clsid}\LocalServer32"
_COM3DX_RELATIVE_PARTS = ("python3dx", "lib", "com3dx.py")
_EXECUTABLE_PATTERN = re.compile(r"(?P<path>.+?\.exe)", re.IGNORECASE)
_COM3DX_MODULE_NAME = "com3dx"


def find_com3dx_path(explicit_path: Path | None = None) -> Path:
    """Resolve the full path to the installed ``com3dx.py``.

    Tries in order and the first one that points at an existing
    file wins:

        1. ``explicit_path`` argument.
        2. The ``AUTO_3DX_COM3DX_PATH`` environment variable (full file path).
        3. The ``CATIA.Application`` COM server registered in the Windows registry

    Args:
        explicit_path: Full path to ``com3dx.py`` supplied by the caller.

    Returns:
        Path to an existing ``com3dx.py`` file.

    Raises:
        Com3dxNotFoundError: None of the candidates resolved to an existing file.
    """
    candidates = (
        explicit_path,
        _path_from_env(),
        _path_from_registry(),
    )
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate

    raise Com3dxNotFoundError(
        "Could not locate com3dx.py. Set the "
        f"{COM3DX_PATH_ENV_VAR} environment variable to its full path, e.g. "
        r"C:\Program Files\Dassault Systemes\<release>\win_b64\code"
        r"\python3dx\lib\com3dx.py."
    )


def _path_from_env() -> Path | None:
    """Return the path configured in ``AUTO_3DX_COM3DX_PATH``, if any."""
    value = os.environ.get(COM3DX_PATH_ENV_VAR)
    if not value:
        return None
    return Path(value)


def _path_from_registry() -> Path | None:
    """Derive ``com3dx.py`` from the registered ``CATIA.Application`` server."""
    clsid = _read_default_value(rf"{_APPLICATION_PROG_ID}\CLSID")
    if clsid is None:
        return None

    local_server_key = _LOCAL_SERVER_KEY_TEMPLATE.format(clsid=clsid)
    local_server = _read_default_value(local_server_key)
    if local_server is None:
        return None

    executable = _extract_executable(local_server)
    if executable is None:
        return None

    code_directory = executable.parent.parent
    return code_directory.joinpath(*_COM3DX_RELATIVE_PARTS)


def _read_default_value(sub_key: str) -> str | None:
    """Read the unnamed default value of ``HKEY_CLASSES_ROOT\\<sub_key>``."""
    try:
        value = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, sub_key)
    except OSError:
        return None
    value = value.strip()
    return value or None


def _extract_executable(local_server_command: str) -> Path | None:
    """Pull the ``.exe`` path out of a ``LocalServer32`` command string."""
    match = _EXECUTABLE_PATTERN.match(local_server_command.strip().strip('"'))
    if match is None:
        return None
    return Path(match.group("path").strip().strip('"'))


def load_com3dx(path: Path) -> ModuleType:
    """Import the installed ``com3dx.py`` helper as a module, once per process.

    ``com3dx`` mutates process-global state when it loads: it replaces
    ``win32com.client.Dispatch`` and ``builtins.hasattr`` with its own versions.
    Only one module instance may own that state, so the loaded module is cached
    under a fixed name in ``sys.modules`` and reused on later calls. Loading it
    from an explicit file location also avoids putting the install directory on
    ``sys.path``.

    Args:
        path: Full path to ``com3dx.py``, as returned by :func:`find_com3dx_path`.

    Returns:
        The loaded ``com3dx`` module.

    Raises:
        CatiaConnectionError: The helper module could not be imported.
    """
    cached = sys.modules.get(_COM3DX_MODULE_NAME)
    if cached is not None:
        return cached

    spec = importlib.util.spec_from_file_location(_COM3DX_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise CatiaConnectionError(f"Could not load the com3dx helper at {path}.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[_COM3DX_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        del sys.modules[_COM3DX_MODULE_NAME]
        raise CatiaConnectionError(
            f"Failed to import the com3dx helper at {path}."
        ) from error

    return module


def attach_running_application(explicit_path: Path | None = None) -> Any:
    """Attach to the already-running 3DEXPERIENCE session and return its Application.

    Locates the installed ``com3dx`` helper, loads it, and asks it for a COM
    connection to the 3DEXPERIENCE application currently registered in the
    Windows Running Object Table. Nothing is launched; a session must already be
    open.

    Args:
        explicit_path: Full path to ``com3dx.py``. When omitted it is resolved by
            :func:`find_com3dx_path`.

    Returns:
        The 3DEXPERIENCE ``Application`` COM object.

    Raises:
        Com3dxNotFoundError: The ``com3dx`` helper could not be located.
        CatiaConnectionError: The helper failed to load, or no running
            3DEXPERIENCE session could be attached.
    """
    com3dx = load_com3dx(find_com3dx_path(explicit_path))

    try:
        client = com3dx.get3dxClient(forceRebuild=False, quiet=True)
    except com_error as error:
        raise CatiaConnectionError(
            "COM error while attaching to the 3DEXPERIENCE session."
        ) from error

    if client is None:
        raise CatiaConnectionError(
            "No running 3DEXPERIENCE session found. Start 3DEXPERIENCE and "
            "open an editor before attaching."
        )

    return client
