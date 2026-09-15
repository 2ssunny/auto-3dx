"""Verify that the installed com3dx helper can load in the current Python environment."""

from __future__ import annotations

import importlib.metadata
import struct
import sys

from auto_3dx.transport import find_com3dx_path


# Found the way the SDK finds it (AUTO_3DX_COM3DX_PATH, else the registered
# CATIA.Application server), not from a machine-specific install path.
COM3DX_DIRECTORY = find_com3dx_path().parent
COM3DX_FILE = COM3DX_DIRECTORY / "com3dx.py"


print("Python executable:", sys.executable)
print("Python version:", sys.version)
print("Python bits:", struct.calcsize("P") * 8)
print("Expected com3dx:", COM3DX_FILE)
print("com3dx exists:", COM3DX_FILE.is_file())

if not COM3DX_FILE.is_file():
    raise SystemExit("The installed com3dx.py file was not found.")

sys.path.insert(0, str(COM3DX_DIRECTORY))

import com3dx  # noqa: E402


print("Imported com3dx:", com3dx.__file__)
print("pywin32 version:", importlib.metadata.version("pywin32"))
print("get3dxClient available:", hasattr(com3dx, "get3dxClient"))
print("Import probe completed.")