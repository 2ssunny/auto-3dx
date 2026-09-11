"""Catalogue of CATIA's unit system (`Parameters.Units`).

`Parameters.Units` exposes every unit this installation knows about (1887
entries, verified against B428_Cloud), grouped into distinct physical
magnitudes (339 of them: `Length`, `Angle`, `Mass`, `Volume`, ...). This module
enumerates that collection once and caches the result, since re-enumerating
1887 COM objects on every lookup would be needlessly slow.

See docs/conventions.md sections 1.1.2 (ground truth) and 6.15 (contract).
"""

import dataclasses
from typing import Any

import pywintypes

from auto_3dx.parameters.parameter import _wrap_com_error


@dataclasses.dataclass(frozen=True)
class UnitInfo:
    """Immutable snapshot of one entry in `Parameters.Units`.

    Attributes:
        name: The unit's full name (e.g. `"Millimeter"`).
        magnitude: The physical magnitude this unit measures (e.g. `"Length"`).
        symbol: The unit's short symbol (e.g. `"mm"`), as written into
            `Dimension.Unit.Symbol`.
    """

    name: str
    magnitude: str
    symbol: str


class UnitCatalogue:
    """Wraps and caches `Parameters.Units`.

    The underlying COM collection is enumerated exactly once, on first use of
    any query method, and the result is cached for the lifetime of this
    object -- `Parameters.Units` does not change while a Part is open, and
    re-enumerating 1887 items per query would be wasteful.
    """

    def __init__(self, parameters_com_object: Any) -> None:
        """Initializes the catalogue without enumerating anything yet.

        Args:
            parameters_com_object: The raw CATIA `Parameters` collection (the
                object exposing `.Units`), NOT `Parameters.Units` itself.
        """
        self._parameters_com_object = parameters_com_object
        self._by_magnitude: dict[str, list[UnitInfo]] | None = None

    def _load(self) -> dict[str, list[UnitInfo]]:
        """Enumerates `Parameters.Units` once and caches the result by magnitude.

        Returns:
            A mapping of magnitude to the `UnitInfo` entries for it.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        if self._by_magnitude is not None:
            return self._by_magnitude

        try:
            units_com_object = self._parameters_com_object.Units
            count = units_com_object.Count
            loaded: list[UnitInfo] = []
            for index in range(1, count + 1):
                item = units_com_object.Item(index)
                loaded.append(
                    UnitInfo(name=item.Name, magnitude=item.Magnitude, symbol=item.Symbol)
                )
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

        by_magnitude: dict[str, list[UnitInfo]] = {}
        for unit in loaded:
            by_magnitude.setdefault(unit.magnitude, []).append(unit)
        self._by_magnitude = by_magnitude
        return by_magnitude

    def magnitudes(self) -> list[str]:
        """Lists every distinct physical magnitude in the catalogue.

        Returns:
            The sorted, distinct `magnitude` values across all units (339 in
            the verified installation).
        """
        return sorted(self._load().keys())

    def units(self, magnitude: str) -> list[UnitInfo]:
        """Lists every unit belonging to one magnitude.

        Args:
            magnitude: The magnitude to look up (e.g. `"Length"`).

        Returns:
            The `UnitInfo` entries for `magnitude`, in catalogue order. An
            unknown magnitude returns `[]` rather than raising.
        """
        return list(self._load().get(magnitude, []))

    def symbols(self, magnitude: str) -> list[str]:
        """Lists the unit symbols belonging to one magnitude.

        Args:
            magnitude: The magnitude to look up (e.g. `"Length"`).

        Returns:
            The `symbol` of each `UnitInfo` from `units(magnitude)`.
        """
        return [unit.symbol for unit in self.units(magnitude)]

    def supports(self, magnitude: str, symbol: str) -> bool:
        """Checks whether a magnitude/symbol combination exists in the catalogue.

        Args:
            magnitude: The magnitude to check (e.g. `"Length"`).
            symbol: The unit symbol to check (e.g. `"mm"`).

        Returns:
            `True` if `symbol` is one of `symbols(magnitude)`.
        """
        return symbol in self.symbols(magnitude)
