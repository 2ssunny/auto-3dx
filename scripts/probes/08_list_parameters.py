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



def collect_callable_names(wrapper_type: type) -> list[str]:
    names: set[str] = set()

    for base_type in wrapper_type.__mro__:
        for name, member in base_type.__dict__.items():
            if name.startswith("_"):
                continue

            if callable(member):
                names.add(name)

    return sorted(names)


if type(active_object).__name__ != "Part":
    raise SystemExit(
        "The active object is not a Part. "
        f"Actual type: {type(active_object).__name__}"
    )

part = active_object

try:
    parameters = part.Parameters
except com_error as exc:
    print("Part.Parameters access failed")
    print("HRESULT:", hex(exc.hresult & 0xFFFFFFFF))
    print("Details:", exc.excepinfo)
    raise SystemExit(1)

if parameters is None:
    raise SystemExit("Part.Parameters returned None.")

print("Parameters collection: OK")
print("Wrapper type:", type(parameters).__name__)
print("Wrapper module:", type(parameters).__module__)

try:
    print("Runtime CLSID:", parameters.CLSID)
except (AttributeError, com_error) as exc:
    print("Runtime CLSID unavailable:", repr(exc))

try:
    print("Parameter count:", parameters.Count)
except com_error as exc:
    print("Parameters.Count failed")
    print("HRESULT:", hex(exc.hresult & 0xFFFFFFFF))
    print("Details:", exc.excepinfo)
    raise SystemExit(1)

readable_properties = collect_mapping_names(
    type(parameters),
    "_prop_map_get_",
)
writable_properties = collect_mapping_names(
    type(parameters),
    "_prop_map_put_",
)
methods = collect_callable_names(type(parameters))

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



PARAMETER_NAME = "AUTO3DX_TEST_LENGTH"


try:
    parameter = parameters.Item(PARAMETER_NAME)
except com_error as exc:
    print(f"Parameter lookup failed: {PARAMETER_NAME}")
    print("HRESULT:", hex(exc.hresult & 0xFFFFFFFF))
    print("Details:", exc.excepinfo)
    raise SystemExit(1)

if parameter is None:
    raise SystemExit(f"Parameter returned None: {PARAMETER_NAME}")

print("Parameter lookup: OK")
print("Requested name:", PARAMETER_NAME)
print("Wrapper type:", type(parameter).__name__)
print("Wrapper module:", type(parameter).__module__)

try:
    print("Runtime CLSID:", parameter.CLSID)
except (AttributeError, com_error) as exc:
    print("Runtime CLSID unavailable:", repr(exc))

readable_properties = collect_mapping_names(
    type(parameter),
    "_prop_map_get_",
)
writable_properties = collect_mapping_names(
    type(parameter),
    "_prop_map_put_",
)
methods = collect_callable_names(type(parameter))

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


REQUIRED_PROPERTIES = {
    "Name",
    "Value",
}

missing_properties = REQUIRED_PROPERTIES.difference(readable_properties)

if missing_properties:
    missing = ", ".join(sorted(missing_properties))
    raise SystemExit(f"Required readable properties are missing: {missing}")

try:
    parameter_name = parameter.Name
    parameter_value = parameter.Value
except com_error as exc:
    print("Parameter value read failed")
    print("HRESULT:", hex(exc.hresult & 0xFFFFFFFF))
    print("Details:", exc.excepinfo)
    raise SystemExit(1)

print("Parameter read: OK")
print("Name:", parameter_name)
print("Value:", parameter_value)


parameter_count = parameters.Count

print("Parameter list")
print("Count:", parameter_count)

for index in range(1, parameter_count + 1):
    try:
        current_parameter = parameters.Item(index)
    except com_error as exc:
        print(f"Parameter lookup failed at index {index}")
        print("HRESULT:", hex(exc.hresult & 0xFFFFFFFF))
        print("Details:", exc.excepinfo)
        raise SystemExit(1)

    readable_properties = collect_mapping_names(
        type(current_parameter),
        "_prop_map_get_",
    )

    if "Name" in readable_properties:
        parameter_name = current_parameter.Name
    else:
        parameter_name = "<Name unavailable>"

    if "Value" in readable_properties:
        parameter_value = current_parameter.Value
        value_type = type(parameter_value).__name__
    else:
        parameter_value = "<Value unavailable>"
        value_type = "<unknown>"

    print(
        f"[{index}] "
        f"name={parameter_name!r}, "
        f"wrapper={type(current_parameter).__name__}, "
        f"value={parameter_value!r}, "
        f"python_type={value_type}"
    )