import importlib.util
import os
import re
import sys
import threading
import winreg
from pathlib import Path
from types import ModuleType
from typing import Any

from auto_3dx.errors import CatiaConnectionError, Com3dxNotFoundError

COM3DX_PATH_ENV_VAR = "AUTO_3DX_COM3DX_PATH"

_APPLICATION_PROG_ID = "CATIA.Application"
_LOCAL_SERVER_KEY_TEMPLATE = r"CLSID\{clsid}\LocalServer32"
_COM3DX_RELATIVE_PARTS = ("python3dx", "lib", "com3dx.py")
_EXECUTABLE_PATTERN = re.compile(r"(?P<path>.+?\.exe)", re.IGNORECASE)
_COM3DX_MODULE_NAME = "com3dx"

# Serialises the whole check-create-execute sequence in load_com3dx(). Without it
# two threads can both miss the cache and execute com3dx.py twice, or one can
# observe the half-executed module that the other published to sys.modules.
_LOAD_LOCK = threading.Lock()


def find_com3dx_path(explicit_path: Path | None = None) -> Path:
    """Resolve the full path to the installed ``com3dx.py``.

    Tries, in order:

        1. ``explicit_path`` argument.
        2. The ``AUTO_3DX_COM3DX_PATH`` environment variable (full file path).
        3. The ``CATIA.Application`` COM server registered in the Windows registry.

    An explicit path or an environment variable value that does not point at an
    existing file is treated as an error, not a missed candidate: silently
    falling back could attach to a different 3DEXPERIENCE release than the one
    the caller asked for. Only the registry lookup is allowed to fail softly.

    Args:
        explicit_path: Full path to ``com3dx.py`` supplied by the caller.

    Returns:
        Path to an existing ``com3dx.py`` file.

    Raises:
        Com3dxNotFoundError: ``explicit_path`` was given but does not exist, the
            ``AUTO_3DX_COM3DX_PATH`` environment variable is set but does not
            point at an existing file, or no candidate resolved to an existing
            file at all.
    """
    if explicit_path is not None:
        if explicit_path.is_file():
            return explicit_path
        raise Com3dxNotFoundError(
            f"The com3dx_path argument {explicit_path} does not exist. Pass the "
            "full path to the com3dx.py belonging to the 3DEXPERIENCE release "
            "you want to attach to."
        )

    env_path = _path_from_env()
    if env_path is not None:
        if env_path.is_file():
            return env_path
        raise Com3dxNotFoundError(
            f"The {COM3DX_PATH_ENV_VAR} environment variable is set to "
            f"{env_path}, which does not exist. Fix or unset the environment "
            "variable rather than relying on a fallback."
        )

    registry_path = _path_from_registry()
    if registry_path is not None and registry_path.is_file():
        return registry_path

    raise Com3dxNotFoundError(
        "Could not locate com3dx.py. Set the "
        f"{COM3DX_PATH_ENV_VAR} environment variable to its full path, e.g. "
        r"C:\Program Files\Dassault Systemes\<release>\win_b64\code"
        r"\python3dx\lib\com3dx.py."
    )


def _path_from_env() -> Path | None:
    """Return the path configured in ``AUTO_3DX_COM3DX_PATH``, if any.

    A variable that is unset, empty, or whitespace-only is treated as "not
    configured" and falls through to registry discovery. An empty value is
    almost always a cleared shell variable rather than a deliberate choice, so
    failing on it would break attach for no benefit. A non-blank value that does
    not point at an existing file is a different matter and is rejected by
    :func:`find_com3dx_path` instead of falling back.

    Returns:
        The configured path, or ``None`` when the variable is unset or blank.
    """
    value = os.environ.get(COM3DX_PATH_ENV_VAR)
    if value is None or not value.strip():
        return None
    return Path(value.strip())


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

    ``com3dx`` owns process-global COM state: its ``com3dxInit()`` replaces
    ``win32com.client.Dispatch``, ``win32com.client.DispatchBaseClass.__str__``
    and ``builtins.hasattr``. That replacement happens when ``get3dxClient()``
    is first called rather than at import time, but the module still holds the
    saved originals, so only one instance may exist per process. The loaded
    module is therefore cached under a fixed name in ``sys.modules`` and reused
    on later calls. Loading from an explicit file location also avoids putting
    the install directory on ``sys.path``.

    If a ``com3dx`` module is already cached from a different file than
    ``path``, it is refused rather than reused or replaced: mixing the
    generated COM wrappers of two different 3DEXPERIENCE releases in one
    process is not safe, and a new process is required to switch releases.

    Args:
        path: Full path to ``com3dx.py``, as returned by :func:`find_com3dx_path`.

    Returns:
        The loaded ``com3dx`` module.

    Raises:
        CatiaConnectionError: The helper module could not be imported, or a
            ``com3dx`` module loaded from a different file is already cached in
            this process.
    """
    requested = path.resolve()

    with _LOAD_LOCK:
        cached = sys.modules.get(_COM3DX_MODULE_NAME)
        if cached is not None:
            cached_file = getattr(cached, "__file__", None)
            if cached_file is None or Path(cached_file).resolve() != requested:
                raise CatiaConnectionError(
                    "A com3dx helper from a different 3DEXPERIENCE release is "
                    "already loaded in this process "
                    f"({cached_file or 'unknown location'}), so {requested} cannot "
                    "also be loaded. Use a new process to attach to a different "
                    "release."
                )
            return cached

        spec = importlib.util.spec_from_file_location(_COM3DX_MODULE_NAME, path)
        if spec is None or spec.loader is None:
            raise CatiaConnectionError(f"Could not load the com3dx helper at {path}.")

        module = importlib.util.module_from_spec(spec)
        # Published before exec_module so that a self-referential import inside
        # com3dx.py resolves. The lock keeps this half-built module invisible to
        # other threads until execution has finished.
        sys.modules[_COM3DX_MODULE_NAME] = module
        try:
            spec.loader.exec_module(module)
        except Exception as error:
            # Safe to retry: com3dx.py only records the original Dispatch and
            # hasattr at module level, it does not install its replacements
            # until com3dxInit() runs, so a failed exec leaves no global change.
            del sys.modules[_COM3DX_MODULE_NAME]
            raise CatiaConnectionError(
                f"Failed to import the com3dx helper at {path}."
            ) from error

        return module


def attach_running_application(com3dx_path: Path | None = None) -> Any:
    """Attach to the already-running 3DEXPERIENCE session and return its Application.

    Locates the installed ``com3dx`` helper, loads it, and asks it for a COM
    connection to the 3DEXPERIENCE application currently registered in the
    Windows Running Object Table. Nothing is launched; a session must already be
    open.

    Args:
        com3dx_path: Full path to ``com3dx.py``. When omitted it is resolved by
            :func:`find_com3dx_path`.

    Returns:
        The 3DEXPERIENCE ``Application`` COM object.

    Raises:
        Com3dxNotFoundError: The ``com3dx`` helper could not be located.
        CatiaConnectionError: The helper failed to load, ``get3dxClient`` raised
            any exception, or no running 3DEXPERIENCE session could be attached.
    """
    com3dx = load_com3dx(find_com3dx_path(com3dx_path))

    try:
        client = com3dx.get3dxClient(forceRebuild=False, quiet=True)
    except Exception as error:
        raise CatiaConnectionError(
            "Failed to attach to the 3DEXPERIENCE session."
        ) from error

    if client is None:
        raise CatiaConnectionError(
            "No running 3DEXPERIENCE session was found. Start 3DEXPERIENCE and "
            "try again."
        )

    return client
