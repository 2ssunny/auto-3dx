from pywintypes import com_error
import sys
from pathlib import Path

COM3DX_DIRECTORY = Path(
    r"C:\Program Files\Dassault Systemes"
    r"\B428_Cloud\win_b64\code\python3dx\lib"
) # Define directory of 3dx configuration file

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