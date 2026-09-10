"""Wrapper around the 3DEXPERIENCE ``Part`` COM object.

:class:`Part` exposes only the verified surface of the CATIA ``Part`` object:
its name, its parameters, and ``Update()``. Bodies, Sketches, Relations, and
other unverified members are intentionally not wrapped here.
"""

from typing import Any

import pywintypes

from auto_3dx.errors import Auto3dxError, PartUpdateError
from auto_3dx.parameters.collection import ParameterCollection


def _format_com_error(error: pywintypes.com_error) -> str:
    """Render a COM error's HRESULT as a hex suffix for an error message.

    Args:
        error: The caught ``pywintypes.com_error``.

    Returns:
        A string like ``" (HRESULT: 0x80020009)"``, or an empty string when the
        error carries no HRESULT.
    """
    if not error.args:
        return ""
    hresult = error.args[0]
    if not isinstance(hresult, int):
        return ""
    return f" (HRESULT: {hresult & 0xFFFFFFFF:#010x})"


class Part:
    """Wrapper around a raw 3DEXPERIENCE ``Part`` COM object.

    Attributes:
        com_object: Read-only access to the raw ``Part`` COM object.
    """

    def __init__(self, com_object: Any) -> None:
        """Store the raw Part COM object and reset the cached parameter collection.

        Args:
            com_object: The raw CATIA ``Part`` COM object.
        """
        self._com_object = com_object
        self._parameters: ParameterCollection | None = None

    @property
    def com_object(self) -> Any:
        """Any: The raw ``Part`` COM object (escape hatch for testing)."""
        return self._com_object

    @property
    def name(self) -> str:
        """str: The Part's name (for example, ``"3D Shape00422533"``).

        Raises:
            Auto3dxError: Reading the underlying COM ``Name`` property failed.
        """
        try:
            return self._com_object.Name
        except pywintypes.com_error as error:
            raise Auto3dxError(
                f"Could not read the Part name.{_format_com_error(error)}"
            ) from error

    @property
    def parameters(self) -> ParameterCollection:
        """ParameterCollection: The Part's parameters.

        Built from the raw COM ``Parameters`` object on first access and
        cached afterwards, so repeated access does not re-cross the COM
        boundary.

        Raises:
            Auto3dxError: Reading the underlying COM ``Parameters`` property
                failed.
        """
        if self._parameters is None:
            try:
                parameters_com_object = self._com_object.Parameters
            except pywintypes.com_error as error:
                raise Auto3dxError(
                    "Could not read the Part's Parameters."
                    f"{_format_com_error(error)}"
                ) from error
            self._parameters = ParameterCollection(parameters_com_object)
        return self._parameters

    def update(self) -> None:
        """Recompute the Part by calling ``Part.Update()``.

        Does not call Save, and does not touch ``Part.Relations`` or any other
        unverified API.

        Raises:
            PartUpdateError: ``Part.Update()`` failed.
        """
        try:
            self._com_object.Update()
        except pywintypes.com_error as error:
            raise PartUpdateError(
                f"Part.Update() failed.{_format_com_error(error)}"
            ) from error
        except Exception as error:
            raise PartUpdateError("Part.Update() failed.") from error

    def __repr__(self) -> str:
        """str: Debug representation showing the wrapped Part's name."""
        try:
            name = self.name
        except Auto3dxError:
            name = "<unknown>"
        return f"Part(name={name!r})"
