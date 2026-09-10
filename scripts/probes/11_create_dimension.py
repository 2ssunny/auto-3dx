"""Probe `Parameters.CreateDimension` against the running 3DEXPERIENCE session.

The type library pins the signature as:

    CreateDimension(iName: BSTR, iMagnitude: BSTR, iValue: double) -> Dimension

`Parameters.Units` reports magnitudes as capitalised names (`Length`, `Angle`,
`Mass`, ...), so `"Length"` is the candidate magnitude string. This probe checks
that, and answers the questions the library needs before it can expose creation:

    - Does `"Length"` work as the magnitude, and what fails for a bad one?
    - What wrapper type comes back -- `Dimension` or the derived `Length`?
    - Is the initial value interpreted as millimetres?
    - Does `Count` increase and does name lookup find the new parameter?
    - Does `Part.Update()` succeed afterwards?
    - Does `Parameters.Remove` undo it cleanly?

The probe removes what it creates and NEVER saves the document.
"""

from typing import Any

from auto_3dx import Catia
from auto_3dx.errors import ParameterNotFoundError

PROBE_NAME = "AUTO3DX_PROBE_LENGTH"
PROBE_MAGNITUDE = "Length"
PROBE_VALUE = 25.0
BAD_MAGNITUDE = "NOT_A_MAGNITUDE"


def describe(com_object: Any) -> str:
    """Returns the COM wrapper type name and module for an object."""
    wrapper_type = type(com_object)
    return f"{wrapper_type.__name__} (module {wrapper_type.__module__})"


def main() -> None:
    """Runs the probe against the active Part."""
    catia = Catia.attach()
    part = catia.active_part()
    parameters = part.parameters
    raw = parameters.com_object

    print("Part:", part.name)
    print("Count before:", parameters.count)
    print("Existing names:", parameters.names())

    print()
    print("--- bad magnitude behaviour ---")
    try:
        raw.CreateDimension(f"{PROBE_NAME}_BAD", BAD_MAGNITUDE, PROBE_VALUE)
    except Exception as error:  # noqa: BLE001 - probing the real failure mode
        print(f"rejected as expected: {type(error).__name__}: {error}")
    else:
        print("WARNING: a bogus magnitude was accepted; it must be cleaned up manually.")

    print()
    print("--- create ---")
    created = raw.CreateDimension(PROBE_NAME, PROBE_MAGNITUDE, PROBE_VALUE)
    print("returned:", describe(created))
    print("Name:", created.Name)
    print("Value:", created.Value, type(created.Value).__name__)
    print("Count after create:", parameters.count)

    try:
        looked_up = parameters.get(PROBE_NAME)
        print("name lookup:", looked_up.name, looked_up.kind, looked_up.value, looked_up.unit)
    except ParameterNotFoundError as error:
        print("name lookup FAILED:", error)

    print()
    print("--- update ---")
    part.update()
    print("Part.Update(): OK")
    print("Value after update:", parameters.get(PROBE_NAME).value)

    print()
    print("--- remove ---")
    try:
        raw.Remove(PROBE_NAME)
        removed_by = "name"
    except Exception as error:  # noqa: BLE001 - Remove(name) may not be supported
        print(f"Remove(name) failed: {type(error).__name__}: {error}")
        raw.Remove(parameters.count)
        removed_by = "index"
    print("removed by:", removed_by)
    print("Count after remove:", parameters.count)
    print("Names after remove:", parameters.names())

    part.update()
    print("Part.Update() after remove: OK")
    print()
    print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
