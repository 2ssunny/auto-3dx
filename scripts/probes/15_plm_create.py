"""Probe `PLMNewService.PLMCreate` -- creating a new PLM object.

Type library signature (B428_Cloud):

    PLMCreate(iUserType: BSTR [in], oEditor: IDispatch [out])
    SetAttributeValue(iAttributeID: BSTR [in], iAttributeValue: VARIANT [in])
    getLastError(oErrorMessage [in/out], oErrorCode [out])

`oEditor` is an OUT parameter, so pywin32 returns it.

The user type strings come from `GetCustomType()` on the objects already open in
the session (probe: `VPMRepReference` -> `'3DShape'`, `VPMReference` ->
`'VPMReference'`), and `V_Name` is the readable/writable name attribute.

Questions:
    - Does `PLMCreate('VPMReference')` succeed, and what Editor comes back?
    - What is the new editor's `ActiveObject`, and can a `Part` be reached?
    - Does `SetAttributeValue('V_Name', ...)` before `PLMCreate` name the result?
    - What does `getLastError` report on failure?

THIS CREATES A REAL PLM OBJECT in the active collaborative space. It does NOT
save: `PLMPropagateService.PLMPropagate()`/`Save()` are never called here.
"""

from typing import Any

from auto_3dx.transport.windows_com import attach_running_application

USER_TYPE_PRODUCT = "VPMReference"
USER_TYPE_SHAPE = "3DShape"
NAME_ATTRIBUTE = "V_Name"
NEW_NAME = "AUTO3DX_NEW_PRODUCT"


def describe(com_object: Any) -> str:
    """Returns a COM object's wrapper type name."""
    return type(com_object).__name__


def last_error(service: Any) -> str:
    """Reads `getLastError` defensively."""
    try:
        return repr(service.getLastError(""))
    except Exception as error:  # noqa: BLE001 - probing availability
        return f"<getLastError failed: {type(error).__name__}: {error}>"


def report_object(label: str, com_object: Any) -> None:
    """Prints the identity of a PLM object."""
    print(f"{label}: {describe(com_object)}")
    for method in ("GetCustomType",):
        try:
            print(f"    {method}() -> {getattr(com_object, method)()!r}")
        except Exception as error:  # noqa: BLE001 - probing availability
            print(f"    {method}() -> FAILED {type(error).__name__}")
    for attribute in ("V_Name", "PLM_ExternalID", "originated"):
        try:
            print(f"    {attribute} = {com_object.GetAttributeValue(attribute)!r}")
        except Exception:  # noqa: BLE001 - attribute may not exist
            pass


def main() -> None:
    """Runs the probe against the running session."""
    app = attach_running_application()
    editor_before = app.ActiveEditor
    print("Editors before:", app.Editors.Count)
    print("Active editor before:", editor_before.Name)

    service = editor_before.GetService("PLMNewService")
    print("PLMNewService:", describe(service))

    print()
    print("--- SetAttributeValue before create ---")
    try:
        service.SetAttributeValue(NAME_ATTRIBUTE, NEW_NAME)
        print(f"  SetAttributeValue({NAME_ATTRIBUTE!r}, {NEW_NAME!r}): accepted")
    except Exception as error:  # noqa: BLE001 - probing the real failure mode
        print(f"  SetAttributeValue FAILED: {type(error).__name__}: {str(error)[:120]}")
        print("  last error:", last_error(service))

    print()
    print(f"--- PLMCreate({USER_TYPE_PRODUCT!r}) ---")
    try:
        new_editor = service.PLMCreate(USER_TYPE_PRODUCT)
    except Exception as error:  # noqa: BLE001 - probing the real failure mode
        print(f"  FAILED: {type(error).__name__}: {str(error)[:160]}")
        print("  last error:", last_error(service))
        print()
        print("Nothing was created. Document save: NOT CALLED")
        return

    print(f"  returned: {describe(new_editor)}")
    print("Editors after:", app.Editors.Count)

    try:
        print("  editor.Name:", new_editor.Name)
    except Exception as error:  # noqa: BLE001 - probing availability
        print(f"  editor.Name FAILED: {type(error).__name__}")

    print()
    print("--- what is in the new editor? ---")
    try:
        active_object = new_editor.ActiveObject
    except Exception as error:  # noqa: BLE001 - probing availability
        print(f"  ActiveObject FAILED: {type(error).__name__}: {str(error)[:120]}")
        active_object = None

    if active_object is not None:
        report_object("  ActiveObject", active_object)
        for step in ("Parent", "Father"):
            try:
                report_object(f"  ActiveObject.{step}", getattr(active_object, step))
            except Exception as error:  # noqa: BLE001 - probing availability
                print(f"  ActiveObject.{step} -> FAILED {type(error).__name__}")

    print()
    print("--- application active editor now ---")
    try:
        print("  ActiveEditor.Name:", app.ActiveEditor.Name)
        report_object("  ActiveEditor.ActiveObject", app.ActiveEditor.ActiveObject)
    except Exception as error:  # noqa: BLE001 - probing availability
        print(f"  FAILED: {type(error).__name__}: {str(error)[:120]}")

    print()
    print("Document save: NOT CALLED (PLMPropagate deliberately not invoked here)")


if __name__ == "__main__":
    main()
