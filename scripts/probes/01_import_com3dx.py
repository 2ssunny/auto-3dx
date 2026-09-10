"""Verify that the installed com3dx helper can load in the Conda environment."""

from __future__ import annotations

import importlib.metadata
import struct
import sys
from pathlib import Path


COM3DX_DIRECTORY = Path(
    r"C:\Program Files\Dassault Systemes"
    r"\B428_Cloud\win_b64\code\python3dx\lib"
)
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