"""Transport adapters for connecting Python to 3DEXPERIENCE Automation."""

from auto_3dx.transport.windows_com import (
    COM3DX_PATH_ENV_VAR,
    attach_running_application,
    find_com3dx_path,
    load_com3dx,
)

__all__ = [
    "COM3DX_PATH_ENV_VAR",
    "attach_running_application",
    "find_com3dx_path",
    "load_com3dx",
]
