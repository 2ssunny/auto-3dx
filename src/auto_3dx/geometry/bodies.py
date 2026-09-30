"""Bodies of a Part: discovery, creation, visibility and guarded removal.

A Part can hold several `Body` objects besides its main `PartBody`, so an enclosure's
walls, trays and bosses stay separate solids that can be shown, hidden and managed
independently. Everything here reads the live model: a body created by an earlier
process is found by name through `Part.Bodies`, and nothing about it is remembered in
Python between calls (`docs/api-design.md` section 4).

Verified live (probe 41, `docs/conventions.md` section 1.9):

    Part.Bodies.Add()             -> Body, default name "Body.N", and the new body
                                     becomes the In-Work Object
    Body.Name                     -> readable and writable
    Part.Bodies.Item(i) == body   -> True for the body Add() returned
    Body.InBooleanOperation       -> False for a new body
    Selection.Add(body); Selection.VisProperties.SetShow(1)
                                  -> hides the body; GetShow() -> (0, 1) after reselecting
    SetShow(0)                    -> shows it again; its volume is unchanged
    Selection.Add(body); Selection.Delete()
                                  -> removes the body with every feature and sketch in it

Visibility and removal go through the editor's `Selection`, which acts on the ACTIVE
editor, so both refuse a Part that is not active (`geometry.deletion.require_active_part`).
Creating a body restores the In-Work Object that was current before, so creating one never
silently redirects later modelling; target a body explicitly with `part.work_in(body)`.
"""

import warnings
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any, cast

import pywintypes

from auto_3dx._com import automation_error, format_hresult, hresult_of
from auto_3dx._generation import ModelGeneration
from auto_3dx.errors import (
    AmbiguousNameError,
    Auto3dxError,
    AutomationError,
    BodyAlreadyExistsError,
    BodyNotFoundError,
    BodyRemovalError,
    PartialCreationError,
    PartUpdateError,
    SelectionNotRestoredWarning,
)
from auto_3dx.geometry._topology_search import _capture_selection, _restore_selection
from auto_3dx.geometry.deletion import (
    delete_via_selection,
    require_active_part,
    require_selection,
)
from auto_3dx.parameters.parameter import validate_parameter_name

if TYPE_CHECKING:
    from auto_3dx.geometry.sketch import SketchCollection
    from auto_3dx.highlevel.features import BodyFeatures

_FIRST_COM_INDEX = 1
_SHOW_ATTR = 0
"""`CatVisPropertyShow.catVisPropertyShowAttr`: the object is shown."""
_NO_SHOW_ATTR = 1
"""`CatVisPropertyShow.catVisPropertyNoShowAttr`: the object is hidden."""


def _same(first: Any, second: Any) -> bool:
    """Compares two COM objects by identity, treating a failed comparison as different."""
    try:
        return bool(first == second)
    except (pywintypes.com_error, TypeError, AttributeError):
        return False


def _items(collection: Any) -> "list[Any]":
    """Enumerates a 1-based COM collection; `None` counts as empty.

    CATIA returns `None` rather than an empty collection for `Body.HybridBodies` of a body
    that has no geometrical sets (live, 2026-09-17).
    """
    if collection is None:
        return []
    count = int(collection.Count)
    return [
        collection.Item(index)
        for index in range(_FIRST_COM_INDEX, count + _FIRST_COM_INDEX)
    ]


class Body:
    """A body of a Part, read from the live model.

    Obtain bodies from `part.bodies`. A `Body` holds only the COM object it was found as;
    its name, contents and visibility are read from CATIA every time.
    """

    def __init__(
        self,
        com_object: Any,
        part_com_object: Any,
        selection: Any = None,
        generation: "ModelGeneration | None" = None,
        owner: Any = None,
    ) -> None:
        """Initializes the wrapper.

        Args:
            com_object: The raw CATIA `Body` COM object.
            part_com_object: The raw CATIA `Part` it belongs to.
            selection: The raw `Selection` of the editor editing that Part. Only
                visibility and sketch removal need it.
            generation: The owning Part's model generation.
            owner: The `Part` wrapper this body was obtained through. The intent methods on
                `features` build through it; without one they refuse.
        """
        self._com_object = com_object
        self._part_com_object = part_com_object
        self._selection = selection
        self._generation = generation if generation is not None else ModelGeneration()
        self._owner = owner

    @property
    def com_object(self) -> Any:
        """Any: The raw `Body` COM object (escape hatch, as on every other wrapper)."""
        return self._com_object

    @property
    def name(self) -> str:
        """str: The body's name.

        Raises:
            AutomationError: If CATIA cannot report it.
        """
        try:
            return str(self._com_object.Name)
        except pywintypes.com_error as error:
            raise automation_error(error, "reading Body.Name") from error

    @property
    def is_main(self) -> bool:
        """bool: Whether this is the Part's main body, by COM identity with `MainBody`."""
        try:
            main_body = self._part_com_object.MainBody
        except pywintypes.com_error as error:
            raise automation_error(error, "reading Part.MainBody") from error
        return _same(self._com_object, main_body)

    @property
    def features(self) -> "BodyFeatures":
        """BodyFeatures: The body's solid features, in model-tree order, plus builders.

        It is the same tuple of `FeatureInfo` values `part.inspect.bodies()` reports -- a
        `tuple` subclass, so equality, length, iteration and indexing are unchanged -- and
        it also offers `pad`, `pocket`, `hole`, `fillet`, `chamfer` and `circular_pattern`,
        each one Level 2 call inside `part.work_in(body)` (`auto_3dx.highlevel.features`).
        The listing is read when this property is; the builders act on the live model.

        Raises:
            AutomationError: If the body's shapes cannot be read.
        """
        # Imported here: `auto_3dx.inspect` and `auto_3dx.highlevel` import this package.
        from auto_3dx.highlevel.features import BodyFeatures
        from auto_3dx.inspect.summary import Inspector

        listing = Inspector._features_of(self._com_object, f"body {self.name!r}")
        return BodyFeatures(listing, self._owner, self)

    @property
    def sketches(self) -> "SketchCollection":
        """SketchCollection: This body's sketches: list, get, create and remove in it.

        The same collection as `part.sketches`, pinned to this body the way
        `part.work_in(body)` pins it (probe 41: `Body.Sketches.Add` lands in that body), so
        `body.sketches.create(name, support=...)` needs no `with` block. It shares the
        Part's model generation.
        """
        from auto_3dx.geometry.sketch import SketchCollection

        body = self._com_object
        return SketchCollection(
            self._part_com_object, self._selection, self._generation, body_target=lambda: body
        )

    @property
    def sketch_names(self) -> "tuple[str, ...]":
        """tuple[str, ...]: The names of the body's sketches, in model-tree order.

        Raises:
            AutomationError: If the body's sketches cannot be read.
        """
        try:
            return tuple(
                str(sketch.Name) for sketch in _items(self._com_object.Sketches)
            )
        except pywintypes.com_error as error:
            raise automation_error(error, "reading Body.Sketches") from error

    @property
    def is_up_to_date(self) -> bool:
        """bool: Whether CATIA has rebuilt this body since its last change.

        A body created or edited inside `part.work_in(body)` is not rebuilt until
        something updates it, and a body that has not been rebuilt has no valid solid:
        measuring one fails inside CATIA's inertia service (probe 42). Read-only.

        Raises:
            AutomationError: If CATIA cannot report the status.
        """
        try:
            result = self._part_com_object.IsUpToDate(self._com_object)
        except pywintypes.com_error as error:
            raise automation_error(
                error, "calling Part.IsUpToDate() for a body"
            ) from error
        except (AttributeError, TypeError) as error:
            raise AutomationError(
                "Part.IsUpToDate() is unusable in this release: "
                f"{type(error).__name__}: {error}"
            ) from error
        return bool(result)

    def update(self) -> None:
        """Rebuilds this body alone, through `Part.UpdateObject`.

        `part.update()` rebuilds the whole Part; this rebuilds one body and leaves the
        rest as it is. Live (probe 42) it made a body whose pad had never been rebuilt
        up to date and measurable, without moving the In-Work Object. It is the update a
        `part.work_in(body)` workflow needs, and like every other rebuild in this SDK it
        is explicit: nothing here updates on its own.

        Raises:
            PartUpdateError: If CATIA could not rebuild the body. The body is left as
                CATIA left it; repair what caused the failure and update again
                (`Part.update`).
        """
        with self._generation.mutation():
            try:
                self._part_com_object.UpdateObject(self._com_object)
            except pywintypes.com_error as error:
                hresult = hresult_of(error)
                raise PartUpdateError(
                    f"Part.UpdateObject() failed for body {self.name!r} "
                    f"(HRESULT={format_hresult(hresult)}).",
                    hresult,
                ) from error
            except (AttributeError, TypeError) as error:
                raise PartUpdateError(
                    "Part.UpdateObject() is unusable in this release: "
                    f"{type(error).__name__}."
                ) from error

    @property
    def is_visible(self) -> bool:
        """bool: Whether the body is shown, read with `VisProperties.GetShow`.

        The read goes through the editor's `Selection`, which is put back as it was.

        Raises:
            InactivePartError: If the Part is not the active one.
            ValidationError: If this body has no editor selection to read through.
            AutomationError: If CATIA cannot report the state, or reports one other than
                shown or hidden.
        """
        state = self._through_selection(
            lambda vis: vis.GetShow(), "reading body visibility"
        )
        value = state[-1] if isinstance(state, tuple) else state
        if value == _SHOW_ATTR:
            return True
        if value == _NO_SHOW_ATTR:
            return False
        raise AutomationError(
            f"VisProperties.GetShow() reported an unknown state {state!r}."
        )

    def hide(self) -> None:
        """Hides the body in the CATIA viewer. The geometry is not changed.

        Raises:
            InactivePartError: If the Part is not the active one.
            ValidationError: If this body has no editor selection to act through.
            AutomationError: If CATIA refuses.
        """
        self._set_show(_NO_SHOW_ATTR, "hiding a body")

    def show(self) -> None:
        """Shows the body in the CATIA viewer. The geometry is not changed.

        Raises:
            InactivePartError: If the Part is not the active one.
            ValidationError: If this body has no editor selection to act through.
            AutomationError: If CATIA refuses.
        """
        self._set_show(_SHOW_ATTR, "showing a body")

    def _set_show(self, state: int, action: str) -> None:
        """Sets the body's show attribute through the selection.

        A visibility change is counted as a model change for staleness: whether a
        topology search still finds a hidden body's edges is not verified, so a
        snapshot taken before it is refused rather than trusted.
        """
        with self._generation.mutation():
            self._through_selection(lambda vis: vis.SetShow(state), action)

    def _through_selection(self, call: Any, action: str) -> Any:
        """Selects only this body, runs `call(VisProperties)`, and restores the selection."""
        require_selection(self._selection)
        require_active_part(self._part_com_object)
        selection = self._selection
        captured = _capture_selection(selection)
        try:
            selection.Clear()
            selection.Add(self._com_object)
            result = call(selection.VisProperties)
        except pywintypes.com_error as error:
            problem = _restore_selection(selection, captured)
            failure = automation_error(error, action)
            if problem is not None:
                failure.add_note(f"In addition, {problem}.")
            raise failure from error
        problem = _restore_selection(selection, captured)
        if problem is not None:
            warnings.warn(
                f"{action.capitalize()} succeeded, but {problem}.",
                SelectionNotRestoredWarning,
                stacklevel=3,
            )
        return result

    def __repr__(self) -> str:
        """str: Debug representation."""
        try:
            name = self.name
        except Auto3dxError:
            name = "<unavailable>"
        return f"Body(name={name!r})"


class BodyCollection:
    """The bodies of a Part, found in the live model every time.

    Obtain it as `part.bodies`. `list`, `names` and `get` read `Part.Bodies`; `create`
    adds a body without leaving it in work; `remove` deletes one only when told what
    it will take with it.
    """

    def __init__(
        self,
        part_com_object: Any,
        selection: Any = None,
        generation: "ModelGeneration | None" = None,
        owner: Any = None,
    ) -> None:
        """Initializes the collection.

        Args:
            part_com_object: The raw CATIA `Part` COM object.
            selection: The raw `Selection` of the editor editing that Part. Needed by
                `remove` and by body visibility.
            generation: The owning Part's model generation.
            owner: The `Part` wrapper, handed to every `Body` so `body.features` can build.
        """
        self._part_com_object = part_com_object
        self._selection = selection
        self._generation = generation if generation is not None else ModelGeneration()
        self._owner = owner

    def _wrap(self, com_object: Any) -> Body:
        return Body(
            com_object, self._part_com_object, self._selection, self._generation, self._owner
        )

    def _raw_bodies(self) -> "list[Any]":
        try:
            return _items(self._part_com_object.Bodies)
        except pywintypes.com_error as error:
            raise automation_error(error, "enumerating Part.Bodies") from error

    def _matching(self, name: str) -> "list[Any]":
        try:
            return [body for body in self._raw_bodies() if str(body.Name) == name]
        except pywintypes.com_error as error:
            raise automation_error(error, "reading a body name") from error

    def list(self) -> "list[Body]":
        """Lists every body, the main body included, in `Part.Bodies` order.

        Returns:
            One `Body` per item in `Part.Bodies`.

        Raises:
            AutomationError: If the bodies cannot be enumerated.
        """
        return [self._wrap(body) for body in self._raw_bodies()]

    def names(self) -> "list[str]":
        """Lists the body names, in `Part.Bodies` order.

        Raises:
            AutomationError: If the bodies cannot be enumerated.
        """
        return [body.name for body in self.list()]

    def get(self, name: str) -> Body:
        """Finds one body by name.

        Args:
            name: The body's name.

        Returns:
            The matching `Body`.

        Raises:
            BodyNotFoundError: If no body has that name. Raised only after enumerating
                `Part.Bodies`.
            AmbiguousNameError: If two or more bodies share the name.
            AutomationError: If the bodies cannot be enumerated.
        """
        matches = self._matching(name)
        if not matches:
            raise BodyNotFoundError(
                f"No body named {name!r} was found. Bodies that are there: {self.names()}."
            )
        if len(matches) > 1:
            raise AmbiguousNameError(
                f"{len(matches)} bodies are named {name!r}; a name-based lookup cannot "
                "safely pick one."
            )
        return self._wrap(matches[0])

    @property
    def main(self) -> Body:
        """Body: The Part's main body.

        Raises:
            AutomationError: If CATIA cannot report it.
        """
        try:
            return self._wrap(self._part_com_object.MainBody)
        except pywintypes.com_error as error:
            raise automation_error(error, "reading Part.MainBody") from error

    def __len__(self) -> int:
        """int: How many bodys there are now, read from the live Part."""
        return len(self.list())

    def __iter__(self) -> "Iterator[Body]":
        """Iterates over the bodys as `list()` returns them, read from the live Part."""
        return iter(self.list())

    def __contains__(self, name: object) -> bool:
        """Whether a body with that name exists now. A non-string is simply absent.

        Existence is decided by enumeration, like `get`, so two bodys sharing the name
        still count as present.
        """
        if not isinstance(name, str):
            return False
        return name in cast(Sequence[str], self.names())

    def create(self, name: str) -> Body:
        """Adds a new body to the Part.

        CATIA makes a new body the In-Work Object (probe 41). This method puts back the
        In-Work Object that was current before, so later modelling is not silently
        redirected; use `part.work_in(body)` to model in the new body.

        Args:
            name: The new body's name. Must be non-empty, without surrounding whitespace,
                and must not contain `"\\\\"`.

        Returns:
            The new `Body`.

        Raises:
            ParameterNameError: If `name` is not usable.
            BodyAlreadyExistsError: If a body with that name exists.
            AmbiguousNameError: If two or more already do.
            PartialCreationError: If the body was added but could not be renamed; it
                exists under CATIA's default name.
            AutomationError: If CATIA refuses, or the previous In-Work Object could not be
                put back.
        """
        validate_parameter_name(name)
        existing = self._matching(name)
        if len(existing) > 1:
            raise AmbiguousNameError(
                f"{len(existing)} bodies are already named {name!r}."
            )
        if existing:
            raise BodyAlreadyExistsError(f"A body named {name!r} already exists.")
        part = self._part_com_object
        try:
            previous = part.InWorkObject
        except pywintypes.com_error as error:
            raise automation_error(error, "reading Part.InWorkObject") from error

        with self._generation.mutation():
            try:
                body = part.Bodies.Add()
            except pywintypes.com_error as error:
                raise automation_error(error, "adding a body") from error
            try:
                try:
                    body.Name = name
                except pywintypes.com_error as error:
                    try:
                        actual = str(body.Name)
                    except pywintypes.com_error:
                        actual = "unknown"
                    raise PartialCreationError(
                        f"Added a body but failed to rename it to {name!r}; it exists as "
                        f"{actual!r}. Remove it before retrying."
                    ) from error
            finally:
                _put_back_in_work(part, previous)
        return self._wrap(body)

    def remove(self, name: str, *, delete_contents: bool = False) -> None:
        """Deletes a body.

        Deleting a body deletes every feature and sketch inside it (probe 41), so a body
        that is not empty is refused unless `delete_contents=True` says that is intended.
        The main body is never removed.

        If the In-Work Object was this body or something inside it, the main body becomes
        the In-Work Object, because the previous one no longer exists; otherwise the
        previous In-Work Object is put back. This does not rebuild and never saves.

        Args:
            name: The body's name.
            delete_contents: Must be `True` to remove a body that still holds features,
                sketches or geometrical sets.

        Raises:
            BodyNotFoundError: If no body has that name.
            BodyRemovalError: If it is the main body, or not empty and `delete_contents`
                is `False`. Nothing is changed.
            InactivePartError: If the Part is not the active one.
            AutomationError: If the deletion fails.
        """
        body = self.get(name)
        raw_body = body.com_object
        if body.is_main:
            raise BodyRemovalError(
                f"{name!r} is the main body of the Part; it is never removed."
            )
        part = self._part_com_object
        try:
            shapes = _items(raw_body.Shapes)
            sketches = _items(raw_body.Sketches)
            sets = _items(raw_body.HybridBodies)
            previous = part.InWorkObject
        except pywintypes.com_error as error:
            raise automation_error(
                error, f"reading the contents of body {name!r}"
            ) from error
        if (shapes or sketches or sets) and not delete_contents:
            raise BodyRemovalError(
                f"Body {name!r} is not empty ({len(shapes)} features, {len(sketches)} "
                f"sketches, {len(sets)} geometrical sets); removing it deletes all of them. "
                "Pass delete_contents=True if that is intended."
            )
        previous_inside = _same(previous, raw_body) or any(
            _same(previous, item) for item in shapes + sketches
        )

        require_selection(self._selection)
        require_active_part(part)
        with self._generation.mutation():
            delete_via_selection(self._selection, raw_body, f"body {name!r}", part)
            if previous_inside:
                try:
                    part.InWorkObject = part.MainBody
                except pywintypes.com_error as error:
                    raise automation_error(
                        error, "making the main body in work"
                    ) from error
            else:
                _put_back_in_work(part, previous)

    def __repr__(self) -> str:
        """str: Debug representation; does not contact CATIA."""
        return "BodyCollection()"


def _put_back_in_work(part_com_object: Any, previous: Any) -> None:
    """Restores a captured In-Work Object and checks that it came back.

    Raises:
        AutomationError: If CATIA refuses the assignment or reports a different object.
    """
    try:
        part_com_object.InWorkObject = previous
        restored = _same(part_com_object.InWorkObject, previous)
    except pywintypes.com_error as error:
        raise automation_error(error, "restoring the In-Work Object") from error
    if not restored:
        raise AutomationError(
            "The In-Work Object did not return to the object it was before."
        )
