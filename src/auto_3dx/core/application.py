"""Wrapper around the 3DEXPERIENCE ``Application`` COM object.

:class:`Catia` is the entry point of the public API: it attaches to an
already-running 3DEXPERIENCE session and hands out :class:`~auto_3dx.core.part.Part`
wrappers for the session's currently active Part.
"""

import dataclasses
from pathlib import Path
from typing import Any

import pywintypes

from auto_3dx._com import automation_error
from auto_3dx.core.part import Part
from auto_3dx.errors import (
    AmbiguousNameError,
    Auto3dxError,
    NoActiveEditorError,
    NoActivePartError,
)
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


def _selection_of(editor: Any) -> Any:
    """Return the editor's ``Selection``, or ``None`` when it is unavailable.

    Only geometry deletion needs the selection, because neither ``Sketches`` nor
    ``Shapes`` exposes a ``Remove`` method. A session that will not hand one over
    should therefore still yield a usable Part -- read, create and update all
    work without it -- so this degrades to ``None`` instead of failing
    :meth:`Catia.active_part`.

    Args:
        editor: The raw CATIA ``Editor`` COM object.

    Returns:
        The raw ``Selection`` COM object, or ``None``.
    """
    try:
        return editor.Selection
    except (AttributeError, pywintypes.com_error):
        return None


@dataclasses.dataclass(frozen=True)
class EditorInfo:
    """Describes one open editor and what it is currently displaying.

    ``Application.ActiveEditor`` does not reliably follow the UI's active
    tab (observed live: the user switched to a new Part's tab, but
    ``ActiveEditor`` still reported the previous Part). ``EditorInfo`` is
    what :meth:`Catia.editors` reports for every open editor, so a caller can
    pick the right one directly instead of trusting ``ActiveEditor``.

    Attributes:
        name: The editor's ``Name`` (for example, ``"CATIAEditor6"``).
        object_kind: ``type(ActiveObject).__name__`` (for example, ``"Part"``
            or ``"VPMRootOccurrence"``), or ``None`` if ``ActiveObject`` could
            not be read.
        object_name: The active object's ``Name``, or ``None`` if it could
            not be read.
        is_part: ``True`` if ``object_kind == "Part"``.
    """

    name: str
    object_kind: str | None
    object_name: str | None
    is_part: bool


def _editor_info(editor: Any) -> EditorInfo:
    """Builds an :class:`EditorInfo` from a raw ``Editor`` COM object.

    Every read past the editor's own ``Name`` is defensive. A ``com_error``
    while reading ``ActiveObject`` or its ``Name`` is real and observed
    (docs/conventions.md 6.8: one editor in a normal session raised on
    ``ActiveObject``), so it must not abort enumeration -- it just leaves the
    corresponding field(s) as ``None`` for this one entry.

    Args:
        editor: The raw CATIA ``Editor`` COM object.

    Returns:
        The resulting :class:`EditorInfo`.
    """
    try:
        name = editor.Name
    except pywintypes.com_error:
        name = "<unknown>"

    try:
        active_object = editor.ActiveObject
    except pywintypes.com_error:
        active_object = None

    object_kind: str | None = None
    object_name: str | None = None
    if active_object is not None:
        object_kind = type(active_object).__name__
        try:
            object_name = active_object.Name
        except pywintypes.com_error:
            object_name = None

    return EditorInfo(
        name=name,
        object_kind=object_kind,
        object_name=object_name,
        is_part=object_kind == _PART_TYPE_NAME,
    )


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
            raise automation_error(error, "reading Application.Name") from error

    @property
    def active_window_title(self) -> str:
        """str: The title of the active 3DEXPERIENCE window.

        This is the only place the SDK reads a window, and it is read-only. It exists
        because a Part's Automation `Part.Name` is an internal identifier such as
        `"3D Shape00422558"`, while the title a person sees may be the name they gave the
        document. A live script that must confirm it is pointed at the right document
        needs both, and reading this through the SDK keeps raw COM out of scripts
        (`docs/api-design.md` section 15).

        Nothing here manipulates windows: no activation, no resizing, no enumeration.

        Raises:
            SessionError: If the session reports no active window.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            window = self._com_object.ActiveWindow
        except pywintypes.com_error as error:
            raise automation_error(error, "reading Application.ActiveWindow") from error
        if window is None:
            raise NoActiveEditorError(
                "The session reports no active window, so its title cannot be read."
            )
        try:
            return str(window.Caption)
        except pywintypes.com_error as error:
            raise automation_error(error, "reading ActiveWindow.Caption") from error

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
        return Part(active_object, selection=_selection_of(editor), editor=editor)

    def _raw_editors(self) -> Any:
        """Returns the raw ``Application.Editors`` collection.

        Returns:
            The raw CATIA ``Editors`` collection.

        Raises:
            Auto3dxError: Reading ``Application.Editors`` failed.
        """
        try:
            return self._com_object.Editors
        except pywintypes.com_error as error:
            raise automation_error(error, "reading Application.Editors") from error

    def _editor_count(self, editors_com_object: Any) -> int:
        """Returns ``Editors.Count``.

        This is the one enumeration step whose failure is treated as a real
        error rather than something to work around: a bad individual editor
        is expected and handled per-entry, but not being able to tell how
        many editors exist at all is not.

        Args:
            editors_com_object: The raw ``Editors`` collection.

        Returns:
            The number of open editors.

        Raises:
            Auto3dxError: Reading ``Editors.Count`` failed.
        """
        try:
            return editors_com_object.Count
        except pywintypes.com_error as error:
            raise automation_error(error, "reading Editors.Count") from error

    def editors(self) -> "list[EditorInfo]":
        """Lists every editor currently open in the session.

        Enumerates ``Application.Editors`` directly instead of relying on
        ``ActiveEditor``, which does not reliably follow the UI's active tab
        (see :class:`EditorInfo`). An editor whose ``ActiveObject`` cannot be
        read is still included, with ``object_kind``/``object_name`` as
        ``None`` and ``is_part`` `False` -- one bad editor must never break
        the whole listing.

        Returns:
            An :class:`EditorInfo` per open editor, in ``Editors.Item(1..Count)``
            order.

        Raises:
            Auto3dxError: Reading ``Application.Editors`` or its ``Count``
                failed.
        """
        editors_com_object = self._raw_editors()
        count = self._editor_count(editors_com_object)
        result: list[EditorInfo] = []
        for index in range(1, count + 1):
            try:
                editor = editors_com_object.Item(index)
            except pywintypes.com_error:
                result.append(
                    EditorInfo(name="<unknown>", object_kind=None, object_name=None, is_part=False)
                )
                continue
            result.append(_editor_info(editor))
        return result

    def parts(self) -> "list[Part]":
        """Lists every Part currently open in an editor.

        Each returned :class:`~auto_3dx.core.part.Part` is built with its OWN
        editor's ``Selection`` (via :func:`_selection_of`), never another
        editor's. Reusing a different editor's selection would delete
        geometry in the wrong window.

        Returns:
            A `Part` wrapper for each editor whose ``ActiveObject`` is a
            Part (``type(obj).__name__ == "Part"``, the same check
            :meth:`active_part` uses), in ``Editors.Item(1..Count)`` order.

        Raises:
            Auto3dxError: Reading ``Application.Editors`` or its ``Count``
                failed.
        """
        editors_com_object = self._raw_editors()
        count = self._editor_count(editors_com_object)
        result: list[Part] = []
        for index in range(1, count + 1):
            try:
                editor = editors_com_object.Item(index)
            except pywintypes.com_error:
                continue
            try:
                active_object = editor.ActiveObject
            except pywintypes.com_error:
                continue
            if active_object is None:
                continue
            if type(active_object).__name__ != _PART_TYPE_NAME:
                continue
            result.append(
                Part(active_object, selection=_selection_of(editor), editor=editor)
            )
        return result

    def part_named(self, name: str) -> Part:
        """Finds the open Part with the given name.

        Args:
            name: The Part's ``Name`` to match.

        Returns:
            Part: The matching Part, carrying its own editor's ``Selection``.

        Raises:
            NoActivePartError: No open Part has this name. The message lists
                the names of the Parts that ARE open, so the caller knows
                which tab to click.
            AmbiguousNameError: Two or more open Parts share this name.
            Auto3dxError: Reading ``Application.Editors`` or its ``Count``
                failed.
        """
        open_parts = self.parts()
        matches = [part for part in open_parts if part.name == name]
        if not matches:
            open_names = [part.name for part in open_parts]
            raise NoActivePartError(
                f"No open Part named {name!r} was found. Parts that are open: "
                f"{open_names}."
            )
        if len(matches) > 1:
            raise AmbiguousNameError(
                f"{len(matches)} open Parts are named {name!r}; a name-based "
                "lookup cannot safely pick one."
            )
        return matches[0]

    def __repr__(self) -> str:
        """str: Debug representation showing the wrapped Application's name."""
        try:
            name = self.name
        except Auto3dxError:
            name = "<unknown>"
        return f"Catia(name={name!r})"
