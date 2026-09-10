"""Attach to the running 3DEXPERIENCE session without inspecting a model."""

from __future__ import annotations

import sys
from pathlib import Path


COM3DX_DIRECTORY = Path(
    r"C:\Program Files\Dassault Systemes"
    r"\B428_Cloud\win_b64\code\python3dx\lib"
)

sys.path.insert(0, str(COM3DX_DIRECTORY))

import com3dx  # noqa: E402


client = com3dx.get3dxClient()

if client is None:
    raise SystemExit("Attach failed: no running 3DEXPERIENCE Application was found.")

print("Attach: OK")
print("Wrapper type:", type(client).__name__)
print("Wrapper module:", type(client).__module__)

try:
    print("Runtime CLSID:", client.CLSID)
except Exception as exc:
    print("Runtime CLSID unavailable:", repr(exc))