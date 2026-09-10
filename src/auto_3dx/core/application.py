"""Wrapper around the 3DEXPERIENCE ``Application`` COM object.

:class:`Catia` is the entry point of the public API: it attaches to an
already-running 3DEXPERIENCE session and hands out :class:`~auto_3dx.core.part.Part`
wrappers for the session's currently active Part.
"""

from pathlib import Path
from typing import Any

import pywintypes

from auto_3dx.core.part import Part
from auto_3dx.errors import Auto3dxError, NoActiveEditorError, NoActivePartError
from auto_3dx.transport.windows_com import attach_running_application

_PART_TYPE_NAME = "Part"


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


class Catia:
    """Wrapper around the 3DEXPERIENCE ``Application`` COM object.

    Attributes:
        com_object: Read-only access to the raw ``Application`` COM object.
    """

    def __init__(self, com_object: Any) -> None:
        """Store the raw Application COM object.

        This does not attach to a session; use :meth:`attach` for that.

        Args:
            com_object: The raw 3DEXPERIENCE ``Application`` COM object.
        """
        self._com_object = com_object

    @classmethod
    def attach(cls, com3dx_path: Path | None = None) -> "Catia":
        """Attach to the running 3DEXPERIENCE session and wrap its Application.

        Args:
            com3dx_path: Full path to ``com3dx.py``. When omitted it is
                resolved by :func:`auto_3dx.transport.windows_com.find_com3dx_path`.

        Returns:
            A :class:`Catia` wrapping the attached ``Application`` COM object.

        Raises:
            Com3dxNotFoundError: The ``com3dx`` helper could not be located.
            CatiaConnectionError: Attaching to the running session failed.
        """
        return cls(attach_running_application(com3dx_path))

    @property
    def com_object(self) -> Any:
        """Any: The raw ``Application`` COM object (escape hatch for testing)."""
        return self._com_object

    @property
    def name(self) -> str:
        """str: The Application's name (``"3DEXPERIENCE"`` for a normal session).

        Raises:
            Auto3dxError: Reading the underlying COM ``Name`` property failed.
        """
        try:
            return self._com_object.Name
        except pywintypes.com_error as error:
            raise Auto3dxError(
                f"Could not read the Application name.{_format_com_error(error)}"
            ) from error

    def active_editor(self) -> Any:
        """Return the raw active ``Editor`` COM object.

        Returns:
            The raw ``Editor`` COM object currently active in the session.

        Raises:
            NoActiveEditorError: There is no active editor, or accessing
                ``ActiveEditor`` failed.
        """
        try:
            editor = self._com_object.ActiveEditor
        except pywintypes.com_error as error:
            raise NoActiveEditorError(
                "Could not access the active editor."
                f"{_format_com_error(error)} Open a document in 3DEXPERIENCE "
                "and try again."
            ) from error
        if editor is None:
            raise NoActiveEditorError(
                "There is no active editor. Open a document in 3DEXPERIENCE "
                "and try again."
            )
        return editor

    def active_part(self) -> Part:
        """Return the currently active Part, wrapped for editing.

        Returns:
            Part: A wrapper around the active editor's ``ActiveObject``.

        Raises:
            NoActiveEditorError: There is no active editor.
            NoActivePartError: The active editor has no active object, or its
                active object is not a Part (for example, a
                ``VPMRootOccurrence`` in an Assembly context).
        """
        editor = self.active_editor()
        try:
            active_object = editor.ActiveObject
        except pywintypes.com_error as error:
            raise NoActivePartError(
                "Could not access the active object."
                f"{_format_com_error(error)} Switch to a Part editor and try "
                "again."
            ) from error
        if active_object is None:
            raise NoActivePartError(
                "The active editor has no active object. Switch to a Part "
                "editor and try again."
            )
        type_name = type(active_object).__name__
        if type_name != _PART_TYPE_NAME:
            raise NoActivePartError(
                f"The active object is a {type_name}, not a Part. Switch to a "
                "Part editor (not an Assembly) and try again."
            )
        return Part(active_object)

    def __repr__(self) -> str:
        """str: Debug representation showing the wrapped Application's name."""
        try:
            name = self.name
        except Auto3dxError:
            name = "<unknown>"
        return f"Catia(name={name!r})"
