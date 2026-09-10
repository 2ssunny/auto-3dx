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

try:
    active_object = editor.ActiveObject
except com_error as exc:
    print("ActiveObject access failed")
    print("HRESULT:", hex(exc.hresult & 0xFFFFFFFF))
    print("Details:", exc.excepinfo)
    raise SystemExit(1)

if active_object is None:
    raise SystemExit("ActiveObject is None.")

print("ActiveObject: OK")
print("Wrapper type:", type(active_object).__name__)
print("Wrapper module:", type(active_object).__module__)

try:
    print("Runtime CLSID:", active_object.CLSID)
except (AttributeError, com_error) as exc:
    print("Runtime CLSID unavailable:", repr(exc))


def collect_mapping_names(
    wrapper_type: type,
    attribute_name: str,
) -> list[str]:
    names: set[str] = set()

    for base_type in wrapper_type.__mro__:
        mapping = base_type.__dict__.get(attribute_name)

        if isinstance(mapping, dict):
            names.update(str(name) for name in mapping)

    return sorted(names)


def collect_method_names(wrapper_type: type) -> list[str]:
    names: set[str] = set()

    for base_type in wrapper_type.__mro__:
        methods = base_type.__dict__.get("_public_methods_")

        if isinstance(methods, (list, tuple)):
            names.update(str(name) for name in methods)

    return sorted(names)


wrapper_type = type(active_object)

readable_properties = collect_mapping_names(
    wrapper_type,
    "_prop_map_get_",
)
writable_properties = collect_mapping_names(
    wrapper_type,
    "_prop_map_put_",
)
methods = collect_method_names(wrapper_type)

print("Object type:", wrapper_type.__name__)
print("Object module:", wrapper_type.__module__)

print()
print(f"Readable properties ({len(readable_properties)}):")
for name in readable_properties:
    print(" ", name)

print()
print(f"Writable properties ({len(writable_properties)}):")
for name in writable_properties:
    print(" ", name)

print()
print(f"Methods ({len(methods)}):")
for name in methods:
    print(" ", name)