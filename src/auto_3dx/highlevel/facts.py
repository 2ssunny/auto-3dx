"""`part.inspect.facts(...)`: read only the facts asked for, never a topology search.

`part.inspect.summary()` stays the comprehensive read, but it always runs both B-rep
searches (1-3.5 s on the benchmark models). An agent asking "is it up to date, and what is
the volume?" should pay for one `IsUpToDate` and one inertia measurement, and nothing else:

    facts = part.inspect.facts("volume", "up_to_date")
    facts["volume"]           # mm3
    facts.values              # {"volume": 48000.0, "up_to_date": True}
    facts.unavailable         # {} -- or {"volume": "..."} with the reason

| Fact                | Read                                          | Unit |
|---------------------|-----------------------------------------------|------|
| `name`              | `part.name`                                   |      |
| `up_to_date`        | `part.is_up_to_date()`                        |      |
| `volume`            | one `part.measurement.measure()` (main body)  | mm3  |
| `surface_area`      |   "                                           | mm2  |
| `mass`              |   "                                           | kg   |
| `center_of_gravity` |   "                                           | mm   |
| `feature_count`     | main body features                            |      |
| `sketch_count`      | main body sketches                            |      |
| `body_count`        | `part.bodies.names()`                         |      |

The four mass facts share one measurement. A measurement is unavailable -- recorded in
`unavailable` with the reason, not raised -- when the main body has not been rebuilt
(`TargetNotUpToDateError`) or holds no feature, whose inertia CATIA cannot compute (live:
an empty body fails `measure()` with a COM error). Any other failure propagates with its
own type. Nothing is cached: every call reads the model as it is now.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from auto_3dx.errors import (
    AutomationError,
    FactUnavailableError,
    TargetNotUpToDateError,
    UnknownFactError,
)

if TYPE_CHECKING:
    from auto_3dx.core.part import Part

FACT_NAME = "name"
FACT_UP_TO_DATE = "up_to_date"
FACT_VOLUME = "volume"
FACT_SURFACE_AREA = "surface_area"
FACT_MASS = "mass"
FACT_CENTER_OF_GRAVITY = "center_of_gravity"
FACT_FEATURE_COUNT = "feature_count"
FACT_SKETCH_COUNT = "sketch_count"
FACT_BODY_COUNT = "body_count"

_MASS_FACTS: "tuple[str, ...]" = (
    FACT_VOLUME,
    FACT_SURFACE_AREA,
    FACT_MASS,
    FACT_CENTER_OF_GRAVITY,
)

SUPPORTED_FACTS: "tuple[str, ...]" = (
    FACT_NAME,
    FACT_UP_TO_DATE,
    *_MASS_FACTS,
    FACT_FEATURE_COUNT,
    FACT_SKETCH_COUNT,
    FACT_BODY_COUNT,
)
"""Every fact name `facts()` knows, in documentation order."""


@dataclass(frozen=True)
class PartFacts:
    """The facts one `part.inspect.facts()` call read.

    Attributes:
        values: Fact name -> value, for every requested fact that could be read.
        unavailable: Fact name -> the reason it could not be read in the model's current
            state. A fact is in exactly one of the two.
    """

    values: "Mapping[str, Any]" = field(default_factory=lambda: MappingProxyType({}))
    unavailable: "Mapping[str, str]" = field(default_factory=lambda: MappingProxyType({}))

    def __getitem__(self, name: str) -> Any:
        """Returns one fact's value.

        Raises:
            FactUnavailableError: If the fact was requested but could not be read.
            KeyError: If it was not requested.
        """
        if name in self.unavailable:
            raise FactUnavailableError(f"{name!r} is unavailable: {self.unavailable[name]}")
        return self.values[name]

    def __contains__(self, name: object) -> bool:
        """bool: Whether the fact was read (requested and available)."""
        return name in self.values

    def as_dict(self) -> "dict[str, Any]":
        """dict: A plain copy of `values`."""
        return dict(self.values)


def read_facts(part: "Part", names: "tuple[str, ...]") -> PartFacts:
    """Reads the requested facts of a Part, and only those.

    Args:
        part: The Part to read.
        names: Fact names from `SUPPORTED_FACTS`; duplicates are read once.

    Returns:
        A `PartFacts`.

    Raises:
        UnknownFactError: If a name is not in `SUPPORTED_FACTS`, or none was given. Nothing
            was read.
        Auto3dxError: If a read fails for a reason other than the two documented
            unavailable states.
    """
    if not names:
        raise UnknownFactError(f"Name at least one fact: {list(SUPPORTED_FACTS)}.")
    unknown = [name for name in names if name not in SUPPORTED_FACTS]
    if unknown:
        raise UnknownFactError(
            f"Unknown fact(s) {unknown}; the supported facts are {list(SUPPORTED_FACTS)}."
        )
    wanted = list(dict.fromkeys(names))
    values: dict[str, Any] = {}
    unavailable: dict[str, str] = {}
    if any(name in _MASS_FACTS for name in wanted):
        _read_mass(part, wanted, values, unavailable)
    for name in wanted:
        if name in values or name in unavailable:
            continue
        if name == FACT_NAME:
            values[name] = part.name
        elif name == FACT_UP_TO_DATE:
            values[name] = part.is_up_to_date()
        elif name == FACT_FEATURE_COUNT:
            values[name] = len(part.inspect.features())
        elif name == FACT_SKETCH_COUNT:
            values[name] = len(part.bodies.main.sketch_names)
        elif name == FACT_BODY_COUNT:
            values[name] = len(part.bodies.names())
    ordered = {name: values[name] for name in wanted if name in values}
    return PartFacts(MappingProxyType(ordered), MappingProxyType(dict(unavailable)))


def _read_mass(
    part: "Part", wanted: "list[str]", values: "dict[str, Any]", unavailable: "dict[str, str]"
) -> None:
    """Measures the main body once and fills every requested mass fact."""
    requested = [name for name in wanted if name in _MASS_FACTS]
    try:
        mass = part.measurement.measure()
    except TargetNotUpToDateError:
        for name in requested:
            unavailable[name] = (
                "the main body has not been rebuilt since it last changed; call part.update() first"
            )
        return
    except AutomationError:
        if part.inspect.features():
            raise
        for name in requested:
            unavailable[name] = "the main body holds no feature, so it has no solid to measure"
        return
    readings = {
        FACT_VOLUME: mass.volume_mm3,
        FACT_SURFACE_AREA: mass.area_mm2,
        FACT_MASS: mass.mass_kg,
        FACT_CENTER_OF_GRAVITY: mass.cog_mm,
    }
    for name in requested:
        values[name] = readings[name]
