"""Attach to the running 3DEXPERIENCE session without inspecting a model."""

from __future__ import annotations

import sys

from auto_3dx.transport import find_com3dx_path


# Found the way the SDK finds it (AUTO_3DX_COM3DX_PATH, else the registered
# CATIA.Application server), not from a machine-specific install path.
COM3DX_DIRECTORY = find_com3dx_path().parent

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