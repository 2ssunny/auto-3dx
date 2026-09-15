from pywintypes import com_error
import sys

from auto_3dx.transport import find_com3dx_path


# Found the way the SDK finds it (AUTO_3DX_COM3DX_PATH, else the registered
# CATIA.Application server), not from a machine-specific install path.
COM3DX_DIRECTORY = find_com3dx_path().parent

sys.path.insert(0, str(COM3DX_DIRECTORY))

import com3dx  # noqa: E402. Import 3DX embaded COM application


client = com3dx.get3dxClient()

try:
    editor = client.ActiveEditor
except com_error as exc:
    print("ActiveEditor access failed")
    print("HRESULT:", hex(exc.hresult & 0xFFFFFFFF))
    print("Details:", exc.excepinfo)
    raise SystemExit(1)

if editor is None:
    raise SystemExit("ActiveEditor is None.")

print("ActiveEditor: OK")
print("Wrapper type:", type(editor).__name__)
print("Wrapper module:", type(editor).__module__)

try:
    print("Runtime CLSID:", editor.CLSID)
except (AttributeError, com_error) as exc:
    print("Runtime CLSID unavailable:", repr(exc))