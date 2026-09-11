"""Probe the non-Length parameter types and the unit system.

Type library signatures (B428_Cloud):

    Parameters.CreateReal(iName, iValue: double)      -> RealParam
    Parameters.CreateInteger(iName, iValue: long)     -> IntParam
    Parameters.CreateString(iName, iValue: BSTR)      -> StrParam
    Parameters.CreateBoolean(iName, iValue: bool)     -> BoolParam
    Parameters.CreateDimension(iName, iMagnitude, iValue: double) -> Dimension
    Parameters.Units                                  -> Units (Count 1887)
    Unit: Name, Magnitude, Symbol

Questions:
    - What wrapper type does each Create* return, and is `.Value` writable?
    - Does `CreateDimension` accept magnitudes other than "Length"? Angle, Mass?
    - What unit does a non-Length dimension report, and can it be read back?
    - Is `Parameter.Unit` (seen on `Angle`) readable for every kind?

Verified means created AND the value round-trips AND `Part.Update()` succeeds.

Creates and removes parameters in the ACTIVE Part. Never saves.
"""

from typing import Any

from auto_3dx import Catia

PREFIX = "AUTO3DX_PT_"


def describe(com_object: Any) -> str:
    """Returns a COM wrapper's type name."""
    return type(com_object).__name__


def probe_value(label: str, made: Any, new_value: Any) -> None:
    """Reports a created parameter and tries a round-trip write."""
    print(f"  {label}: {describe(made)}")
    for attribute in ("Name", "Value", "Unit", "ValuateFromString"):
        try:
            value = getattr(made, attribute)
            if callable(value):
                print(f"      {attribute}: callable")
            else:
                print(f"      {attribute} = {value!r}")
        except Exception:  # noqa: BLE001 - probing availability
            print(f"      {attribute}: unavailable")
    try:
        made.Value = new_value
        print(f"      write {new_value!r} -> {made.Value!r}  (writable)")
    except Exception as error:  # noqa: BLE001 - probing the real failure mode
        print(f"      write FAILED: {type(error).__name__}: {str(error)[:70]}")


def main() -> None:
    """Runs the probe against the active Part."""
    catia = Catia.attach()
    part = catia.active_part()
    raw = part.parameters.com_object
    created: list[str] = []

    print("Part:", part.name)
    print("parameters before:", part.parameters.count)

    try:
        print()
        print("--- 1. non-Length Create* methods ---")
        attempts = (
            ("CreateReal", lambda n: raw.CreateReal(n, 1.5), 2.5),
            ("CreateInteger", lambda n: raw.CreateInteger(n, 7), 9),
            ("CreateString", lambda n: raw.CreateString(n, "abc"), "xyz"),
            ("CreateBoolean", lambda n: raw.CreateBoolean(n, True), False),
        )
        for label, factory, new_value in attempts:
            name = f"{PREFIX}{label[6:].upper()}"
            try:
                made = factory(name)
            except Exception as error:  # noqa: BLE001 - probing failure mode
                print(f"  {label}: FAILED {type(error).__name__}: {str(error)[:70]}")
                continue
            created.append(made.Name)
            probe_value(label, made, new_value)

        print()
        print("--- 2. CreateDimension with other magnitudes ---")
        for magnitude, value, new_value in (
            ("Angle", 45.0, 90.0),
            ("Mass", 2.0, 3.0),
            ("Time", 10.0, 20.0),
            ("Volume", 5.0, 6.0),
            ("NotAMagnitude", 1.0, 2.0),
        ):
            name = f"{PREFIX}DIM_{magnitude.upper()}"
            try:
                made = raw.CreateDimension(name, magnitude, value)
            except Exception as error:  # noqa: BLE001 - probing failure mode
                print(f"  {magnitude}: FAILED {type(error).__name__}")
                continue
            created.append(made.Name)
            probe_value(magnitude, made, new_value)

        print()
        print("--- 3. Part.Update() after all creations ---")
        part.update()
        print("  OK")

        print()
        print("--- 4. unit system: magnitudes and their units ---")
        units = raw.Units
        by_magnitude: dict[str, list[str]] = {}
        for index in range(1, units.Count + 1):
            unit = units.Item(index)
            by_magnitude.setdefault(unit.Magnitude, []).append(unit.Symbol)
        print(f"  Units.Count = {units.Count}, distinct magnitudes = {len(by_magnitude)}")
        for magnitude in ("Length", "Angle", "Mass", "Time", "Volume"):
            symbols = [s for s in by_magnitude.get(magnitude, []) if s]
            print(f"    {magnitude:10s} {len(symbols):3d} units: {symbols[:8]}")
        print("  Unit item shape:", [
            (units.Item(1).Name, units.Item(1).Magnitude, units.Item(1).Symbol)
        ])
    finally:
        print()
        print("--- cleanup ---")
        for name in created:
            try:
                raw.Remove(name)
            except Exception as error:  # noqa: BLE001 - report, do not mask
                print(f"  could NOT remove {name!r}: {type(error).__name__}")
        try:
            part.update()
        except Exception as error:  # noqa: BLE001 - report, do not mask
            print(f"  update after cleanup FAILED: {type(error).__name__}")
        print("  parameters:", part.parameters.count, part.parameters.user_names())
        print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
