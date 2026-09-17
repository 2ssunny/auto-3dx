"""Wrappers around user-defined (offset/angled) hybrid planes.

Sketches used to be creatable only on the three origin planes
(`geometry.sketch.SUPPORT_XY`/`SUPPORT_YZ`/`SUPPORT_ZX`). This module adds the
two other verified plane kinds (`docs/conventions.md` section 1.2.7, probes
29/33/36): a plane offset from a base plane, and a plane at an angle to a
base plane around a 3D axis line. Both are `HybridShapeFactory` products that
must live in a `HybridBody` (a "geometrical set") before they are usable.

Verified facts this module is built on:

    Part.HybridBodies -> HybridBodies ; HybridBodies.Add() -> HybridBody
    HybridBody.AppendHybridShape(iHybridShape) -> void
    HybridShapeFactory.AddNewPlaneOffset(iPlane, iOffset, iOrientation)
        -> HybridShapePlaneOffset
    HybridShapeFactory.AddNewPlaneAngle(iPlane, iRevolAxis, iAngle, iOrientation)
        -> HybridShapePlaneAngle
    HybridShapeFactory.AddNewPointCoord(iX, iY, iZ) -> HybridShapePointCoord
    HybridShapeFactory.AddNewLinePtPt(iPtOrigine, iPtExtremite) -> HybridShapeLinePtPt
    Part.InWorkObject -> AnyObject     (readable AND writable)
    Body.Sketches.Add(iPlane)          takes the RAW hybrid shape; no Reference wrapper

**The in-work-object trap (probe 36).** `HybridBodies.Add()` makes the new
geometrical set the Part's in-work object, and a Part Design feature (a pad,
for instance) cannot be inserted into a geometrical set -- a later
`AddNewPad` is rejected with a bare COM error that says nothing about why.
`AppendHybridShape` moves the in-work object again, every time. The fix,
`Part.InWorkObject = MainBody`, has to run after *every* `HybridBodies.Add()`
and *every* `AppendHybridShape`, or the failure resurfaces somewhere
unrelated to the plane. That discipline lives in exactly two private methods
here (`_geometrical_set`/`_append`, both routed through `_reclaim_main_body`)
so it cannot be forgotten at a call site the way it was the first two times
this was probed.

**The angled plane's axis (probe 36).** `AddNewPlaneAngle` needs an
addressable 3D line for its rotation axis. A `Line2D` from inside a sketch
and an origin plane were each tried as the axis; both created an object
whose `Part.Update()` failed. A line built from two `AddNewPointCoord`
points works, but those two points -- and the line itself -- must also be
appended to the geometrical set to be usable, which is why
`PlaneCollection.create_angle` creates and appends four shapes, not one.

**Orientation.** `iOrientation` is passed as `VT_BOOL`; it reads back as a
plain `VT_I4` integer, and the mapping between the two is not documented
(`docs/conventions.md` 1.2.7). Do not assume `False == 0` when reading
`.Orientation` back -- this module does not expose that read-back at all,
for exactly that reason.

**Model generation (`docs/api-design.md` section 5).** Creating or removing a
plane changes the model exactly as a Part Design feature does -- a sketch
built on a plane drives solid features downstream. `PlaneCollection` shares
one `ModelGeneration` with the rest of the owning `Part`, threaded through
`__init__` the same way `geometry.part_design.PartDesign` does, and hands it
to every `Plane`/`OffsetPlane`/`AnglePlane` it constructs. Each public
operation (`create_offset`, `create_angle`, `remove`,
`remove_geometrical_set`) is one mutation for staleness purposes: the
generation advances exactly once per call, wrapping every internal COM call
that operation makes -- not once per `AddNew*`/`AppendHybridShape` -- and only
once the operation has actually reached CATIA, so a request rejected by
validation first (a bad name, a non-finite offset, an unsupported support)
leaves the generation untouched.

**Rediscovery, not memory.** The geometrical set and the planes in it are found
in the live Part every time they are needed: `Part.HybridBodies` is enumerated
with `Count`/`Item(i)` and matched on `Name`, and the set's `HybridShapes` the
same way. Both enumerations are live-verified (probe 38, 2026-09-15: a set's
`HybridShapes.Count`/`Item(i).Name` and the type name `HybridShapePlaneOffset`
were read back for a plane this module had just created). Nothing is cached
between calls, so a `PlaneCollection` built in a new process -- or a second one
built in this process -- finds the set this SDK already created instead of
adding another beside it, and `remove_geometrical_set` can clean up a set it
never created itself. That is what `list`/`names`/`get` expose to callers.

**Why there is still no `ensure_offset`/`ensure_angle`.** This project's
`ensure_*` rule (`docs/conventions.md` 1.3) is that a name match alone never
justifies reusing geometry; only a value read back and compared does. Both
halves now exist -- the lookup above, and `Offset.Value`/`Plane.DisplayName`
read-back -- so an honest `ensure_offset` could be written. It is deliberately
not part of this module yet: `create_offset`/`create_angle` remain the only
creation paths, and a caller wanting idempotency can now check `get`/`names`
first instead of tracking the returned `Plane` object itself.
"""

import math
from typing import Any

import pywintypes

from auto_3dx._generation import ModelGeneration
from auto_3dx.errors import (
    AmbiguousNameError,
    Auto3dxError,
    ParameterTypeError,
    PartialCreationError,
    PlaneNotFoundError,
    UnsupportedSupportError,
)
from auto_3dx.geometry.deletion import delete_via_selection
from auto_3dx.geometry.sketch import (
    SUPPORTED_SKETCH_SUPPORTS,
    _PLANE_ATTRIBUTE_BY_SUPPORT,
    _wrap_com_error,
)
from auto_3dx.parameters.parameter import (
    validate_angle_value,
    validate_length_value,
    validate_parameter_name,
)

GEOMETRICAL_SET_NAME: str = "auto_3dx_Planes"
"""Name given to the one `HybridBody` this module appends all its planes to.

A single shared geometrical set (rather than one per plane) mirrors probe 36,
where every offset plane, angle plane, and the angle plane's axis points and
line all live in one `HybridBody`. The name is also how the set is found again
in a later process: `Part.HybridBodies` is enumerated and matched on `Name`.
"""

PLANE_OFFSET_KIND: str = "HybridShapePlaneOffset"
"""CATIA type name of a plane made by `AddNewPlaneOffset` (read back live, probe 38)."""

PLANE_ANGLE_KIND: str = "HybridShapePlaneAngle"
"""CATIA type name of a plane made by `AddNewPlaneAngle` (`docs/conventions.md` 1.2.7)."""

_FIRST_COM_INDEX = 1


def _validate_finite_length(value: Any, label: str) -> float:
    """Validates a length-like value: numeric, not a `bool`, and finite.

    Args:
        value: The candidate value.
        label: What this value represents (e.g. `"offset"`), used only in
            the error message.

    Returns:
        `value` coerced to `float`.

    Raises:
        ParameterTypeError: If `value` is a `bool`, is not an `int`/`float`,
            or is not finite (`inf`/`nan`).
    """
    coerced = validate_length_value(value)
    if not math.isfinite(coerced):
        raise ParameterTypeError(f"{label} must be finite, got {value!r}.")
    return coerced


def _validate_finite_angle(value: Any, label: str) -> float:
    """Validates an angle-like value: numeric, not a `bool`, and finite.

    Args:
        value: The candidate value.
        label: What this value represents (e.g. `"angle"`), used only in the
            error message.

    Returns:
        `value` coerced to `float`.

    Raises:
        ParameterTypeError: If `value` is a `bool`, is not an `int`/`float`,
            or is not finite (`inf`/`nan`).
    """
    coerced = validate_angle_value(value)
    if not math.isfinite(coerced):
        raise ParameterTypeError(f"{label} must be finite, got {value!r}.")
    return coerced


def _validate_orientation(value: Any) -> bool:
    """Validates the `iOrientation` argument passed to the hybrid-plane factory.

    Args:
        value: The candidate orientation flag.

    Returns:
        `value` unchanged.

    Raises:
        ParameterTypeError: If `value` is not a `bool`.
    """
    if not isinstance(value, bool):
        raise ParameterTypeError(f"orientation must be a bool, got {type(value).__name__}.")
    return value


def _validate_point(value: Any, label: str) -> "tuple[float, float, float]":
    """Validates a 3D point given as an `(x, y, z)` tuple or list.

    Args:
        value: The candidate point.
        label: What this point represents (e.g. `"axis_start"`), used only
            in the error message.

    Returns:
        `(x, y, z)` as three `float`s.

    Raises:
        ParameterTypeError: If `value` is not a 3-item tuple/list, or any of
            its components is a `bool`, is not an `int`/`float`, or is not
            finite.
    """
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise ParameterTypeError(
            f"{label} must be an (x, y, z) tuple of three numbers, got {value!r}."
        )
    x, y, z = value
    return (
        _validate_finite_length(x, f"{label}.x"),
        _validate_finite_length(y, f"{label}.y"),
        _validate_finite_length(z, f"{label}.z"),
    )


def _resolve_support_plane(part_com_object: Any, support: Any) -> Any:
    """Resolves a `support` argument to a raw plane COM object.

    Mirrors `SketchCollection._plane`/`PartDesign._resolve_plane` for the
    string case, reusing this codebase's existing private helpers
    (`_PLANE_ATTRIBUTE_BY_SUPPORT`/`_wrap_com_error`) exactly the way
    `geometry.part_design` already does, rather than duplicating the
    origin-plane mapping a third time. A non-string `support` is treated as
    a plane wrapper from this module (`Plane`/`OffsetPlane`/`AnglePlane`) and
    used via its `com_object`, so a caller can build a plane on top of
    another already-created plane.

    Args:
        part_com_object: The raw CATIA `Part` COM object.
        support: One of `SUPPORTED_SKETCH_SUPPORTS` (a string), or a plane
            wrapper exposing a `com_object` attribute.

    Returns:
        The raw plane COM object.

    Raises:
        UnsupportedSupportError: If `support` is a string not in
            `SUPPORTED_SKETCH_SUPPORTS`, or is neither a string nor an
            object exposing `com_object`.
        Auto3dxError: If the underlying COM call fails unexpectedly.
    """
    if isinstance(support, str):
        if support not in SUPPORTED_SKETCH_SUPPORTS:
            raise UnsupportedSupportError(
                f"Support {support!r} is not supported; supported supports are "
                f"{sorted(SUPPORTED_SKETCH_SUPPORTS)}."
            )
        attribute = _PLANE_ATTRIBUTE_BY_SUPPORT[support]
        try:
            return getattr(part_com_object.OriginElements, attribute)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
    try:
        return support.com_object
    except AttributeError as error:
        raise UnsupportedSupportError(
            "support must be one of "
            f"{sorted(SUPPORTED_SKETCH_SUPPORTS)} or a plane object exposing "
            f"`com_object` (e.g. one returned by PlaneCollection), got "
            f"{type(support).__name__}."
        ) from error


class Plane:
    """Common wrapper for a hybrid plane shape created by `PlaneCollection`.

    Both `HybridShapePlaneOffset` and `HybridShapePlaneAngle` share `Name`
    and `Plane` (their base plane), which is why this base class exists;
    `OffsetPlane`/`AnglePlane` each add the one extra measurement specific to
    their kind.
    """

    def __init__(self, com_object: Any, generation: ModelGeneration | None = None) -> None:
        """Initializes the wrapper.

        Args:
            com_object: The raw CATIA hybrid plane shape COM object to wrap.
            generation: The owning Part's model generation. A wrapper built
                directly from a raw COM object gets its own, which nothing
                else shares; obtain a `Plane` through `PlaneCollection`
                instead so it shares the Part's generation.
        """
        self._com_object = com_object
        self._generation = generation if generation is not None else ModelGeneration()

    @property
    def com_object(self) -> Any:
        """Returns the raw underlying COM object.

        This is what `SketchCollection.create`/`.ensure` accept as `support`
        and what `Body.Sketches.Add` is given directly -- verified
        (`docs/conventions.md` 1.2.7) to need no `Reference` wrapper.

        Returns:
            The wrapped raw COM object.
        """
        return self._com_object

    @property
    def name(self) -> str:
        """Returns the plane's name.

        Returns:
            The plane's `Name`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Name
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def base_display_name(self) -> str:
        """Returns the display name of this plane's base plane.

        Verified read-back (`docs/conventions.md` 1.2.7): `.Plane.DisplayName`
        works for both `HybridShapePlaneOffset` and `HybridShapePlaneAngle`,
        e.g. `'xy plane'` for an origin plane.

        Returns:
            `self.com_object.Plane.DisplayName`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Plane.DisplayName
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def __repr__(self) -> str:
        """Returns a debugging representation.

        Returns:
            A string such as ``Plane(name='MyPlane')``.
        """
        try:
            name = self.name
        except Auto3dxError:
            name = "<unavailable>"
        return f"{type(self).__name__}(name={name!r})"


class OffsetPlane(Plane):
    """Wraps a raw CATIA `HybridShapePlaneOffset` COM object."""

    @property
    def offset(self) -> float:
        """Returns the plane's offset distance.

        Verified read-back (`docs/conventions.md` 1.2.7): `Offset.Value`
        matches the value given to `AddNewPlaneOffset` at creation.

        Returns:
            `self.com_object.Offset.Value`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Offset.Value
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error


class AnglePlane(Plane):
    """Wraps a raw CATIA `HybridShapePlaneAngle` COM object."""

    @property
    def angle(self) -> float:
        """Returns the plane's angle.

        Verified read-back (`docs/conventions.md` 1.2.7): `Angle.Value`
        matches the value given to `AddNewPlaneAngle` at creation. There is
        no equivalent read-back for the rotation axis line, which is why
        this class exposes no way to recover it.

        Returns:
            `self.com_object.Angle.Value`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Angle.Value
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error


_PLANE_WRAPPER_BY_KIND: "dict[str, type[Plane]]" = {
    PLANE_OFFSET_KIND: OffsetPlane,
    PLANE_ANGLE_KIND: AnglePlane,
}
"""The plane kinds this module creates, and the wrapper each is read back as.

A geometrical set also holds the points and lines `create_angle` builds for an
angle plane's axis. Those are not planes, so `list`/`names`/`get` skip anything
whose type name is not a key here; `remove_geometrical_set` still removes them.
"""


class PlaneCollection:
    """Creates, finds and removes offset and angled hybrid planes on a Part.

    Every plane this collection creates lives in one `HybridBody` named
    `GEOMETRICAL_SET_NAME` -- matching probe 36, where a single geometrical set
    holds every plane, plus the angle plane's axis points and line.

    That set is looked up in the live Part whenever it is needed, never
    remembered between calls, so a collection obtained after a restart finds the
    set an earlier process created: `list`, `names` and `get` report the planes
    in it, and `remove_geometrical_set` removes it whoever created it.
    """

    def __init__(
        self,
        part_com_object: Any,
        selection: Any = None,
        generation: ModelGeneration | None = None,
        body_target: Any = None,
    ) -> None:
        """Initializes the wrapper.

        Args:
            part_com_object: The raw CATIA `Part` COM object. `HybridBodies`
                and `HybridShapeFactory` are read from it to create planes;
                `OriginElements` is read from it to resolve a string
                `support`; `MainBody` and `InWorkObject` are used by the
                in-work-object discipline (see the module docstring).
            selection: The raw CATIA `Selection` COM object from the editor.
                Required only by `remove` and `remove_geometrical_set`, because
                neither `HybridBodies` nor a `HybridBody` exposes a verified
                `Remove` method and deletion has to go through the editor's
                selection, exactly as it does for sketches and solid features.
                Creating and looking up work without it.
            generation: The owning Part's model generation. A standalone
                instance gets its own, which no other wrapper shares; obtain
                `PlaneCollection` from a `Part` instead.
            body_target: A callable returning the raw `Body` of an enclosing
                `part.work_in(body)`, or `None` outside one. Supplied by `Part`; without
                it everything works on the main body exactly as before.
        """
        self._part_com_object = part_com_object
        self._selection = selection
        self._body_target = body_target
        # Shared with the owning Part and everything else reachable from it
        # (`docs/api-design.md` section 5). create_offset/create_angle/remove/
        # remove_geometrical_set each advance it exactly once per call.
        self._generation = generation if generation is not None else ModelGeneration()

    def _main_body(self) -> Any:
        """Returns the raw `Part.MainBody` COM object.

        Returns:
            The raw CATIA `Body` COM object.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._part_com_object.MainBody
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def _reclaim_main_body(self) -> None:
        """Makes `MainBody` the Part's in-work object again.

        THIS IS THE FIX for the bug described in the module docstring:
        `HybridBodies.Add()` and `HybridBody.AppendHybridShape()` both leave
        the geometrical set -- not `MainBody` -- as the Part's in-work
        object, and a later Part Design feature cannot be inserted into a
        geometrical set. This is the ONLY method in this module that writes
        `Part.InWorkObject`, and every method that calls `HybridBodies.Add()`
        or `AppendHybridShape` calls this immediately afterwards, so the fix
        cannot be missed at a call site the way it was the first two times
        this was probed.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            target = self._body_target() if self._body_target is not None else None
            # Inside `part.work_in(body)` the work body is reclaimed instead, so a plane
            # made there does not send later features to the main body.
            self._part_com_object.InWorkObject = (
                target if target is not None else self._main_body()
            )
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def _factory(self) -> Any:
        """Returns the raw `Part.HybridShapeFactory` COM object.

        Returns:
            The raw CATIA `HybridShapeFactory` COM object.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._part_com_object.HybridShapeFactory
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def _geometrical_set(self) -> Any:
        """Returns the shared `HybridBody`, creating it on first use.

        Args: none.

        Returns:
            The raw CATIA `HybridBody` COM object.

        An existing set is found in the Part first, so a collection built after
        a restart -- or a second collection in this process -- appends to the
        set this SDK already created instead of adding another beside it.

        Returns:
            The raw CATIA `HybridBody` COM object.

        Raises:
            AmbiguousNameError: If the Part holds more than one geometrical set
                named `GEOMETRICAL_SET_NAME`.
            PartialCreationError: If the geometrical set was created but the
                follow-up rename failed. It exists and is usable under its
                default CATIA name, but it cannot be found again by name, so it
                has to be removed by hand.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        existing = self._find_geometrical_set()
        if existing is not None:
            return existing
        try:
            hybrid_body = self._part_com_object.HybridBodies.Add()
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        try:
            hybrid_body.Name = GEOMETRICAL_SET_NAME
        except pywintypes.com_error as error:
            self._reclaim_main_body()
            raise PartialCreationError(
                "Created the geometrical set that holds every plane this "
                f"collection creates, but failed to rename it to "
                f"{GEOMETRICAL_SET_NAME!r}. It is usable under its default CATIA "
                "name, but this collection finds its set by name, so it will not "
                "be reused and has to be removed in the CATIA user interface."
            ) from error
        self._reclaim_main_body()
        return hybrid_body

    def _hybrid_bodies(self) -> Any:
        """Returns the raw `Part.HybridBodies` collection.

        Returns:
            The raw CATIA `HybridBodies` COM object.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._part_com_object.HybridBodies
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def _find_geometrical_set(self) -> Any:
        """Finds this module's geometrical set in the live Part, by name.

        Enumerating `HybridBodies` with `Count`/`Item(i)` and reading `Name` is
        live-verified (probe 38). This is what makes the collection stateless:
        nothing is remembered from an earlier call or an earlier process.

        Returns:
            The raw `HybridBody` named `GEOMETRICAL_SET_NAME`, or `None` when the
            Part has no such set.

        Raises:
            AmbiguousNameError: If two or more sets share that name, which a
                name-based lookup cannot safely resolve.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        hybrid_bodies = self._hybrid_bodies()
        matches = []
        try:
            count = int(hybrid_bodies.Count)
            for index in range(_FIRST_COM_INDEX, count + _FIRST_COM_INDEX):
                candidate = hybrid_bodies.Item(index)
                if candidate.Name == GEOMETRICAL_SET_NAME:
                    matches.append(candidate)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        if len(matches) > 1:
            raise AmbiguousNameError(
                f"{len(matches)} geometrical sets are named {GEOMETRICAL_SET_NAME!r}; "
                "a name-based lookup cannot safely pick one. Remove the extra set in "
                "the CATIA user interface."
            )
        return matches[0] if matches else None

    def _shapes_in_set(self, hybrid_body: Any) -> "list[Any]":
        """Enumerates one geometrical set's hybrid shapes, in model-tree order.

        Args:
            hybrid_body: The raw `HybridBody` to read.

        Returns:
            Every raw shape in it.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            shapes = hybrid_body.HybridShapes
            count = int(shapes.Count)
            return [
                shapes.Item(index)
                for index in range(_FIRST_COM_INDEX, count + _FIRST_COM_INDEX)
            ]
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def _append(self, shape: Any, name: str) -> Any:
        """Names a hybrid shape and appends it to the shared geometrical set.

        This is the ONLY place `AppendHybridShape` is called, and
        `_reclaim_main_body` runs immediately afterwards every single time
        (see the module docstring) -- never at the individual call sites in
        `create_offset`/`create_angle`, so the fix cannot be forgotten there.

        Args:
            shape: The raw hybrid shape COM object (from
                `HybridShapeFactory`).
            name: The name to give it before appending.

        Returns:
            `shape`, unchanged, for chaining at the call site.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            PartialCreationError: If the shape was created but the follow-up
                rename or append failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        hybrid_body = self._geometrical_set()
        try:
            shape.Name = name
        except pywintypes.com_error as error:
            raise PartialCreationError(
                f"Created a hybrid shape but failed to rename it to {name!r}; "
                "it was not appended to the geometrical set."
            ) from error
        try:
            hybrid_body.AppendHybridShape(shape)
        except pywintypes.com_error as error:
            raise PartialCreationError(
                f"Created and named a hybrid shape {name!r} but failed to "
                "append it to the geometrical set; it exists but is not part "
                "of the model tree."
            ) from error
        finally:
            # Runs even if AppendHybridShape raised: whether a failed append
            # still moves the in-work object is unverified, and reclaiming
            # MainBody when it was already MainBody is harmless.
            self._reclaim_main_body()
        return shape

    def create_offset(
        self,
        name: str,
        support: Any,
        offset: float,
        orientation: bool = False,
    ) -> OffsetPlane:
        """Creates a plane offset from a base plane.

        Unlike `SketchCollection.create`, this does not check for an
        existing plane with the same name first: there is no verified way to
        enumerate the geometrical set's contents by name (see the module
        docstring), so a duplicate name is possible here and CATIA itself
        does not stop it.

        Args:
            name: The new plane's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            support: The base plane: one of `SUPPORTED_SKETCH_SUPPORTS`
                (`"XY"`/`"YZ"`/`"ZX"`), or a plane wrapper returned by this
                class.
            offset: The offset distance, in millimetres. May be negative or
                zero.
            orientation: Passed through as `AddNewPlaneOffset`'s
                `iOrientation`. Defaults to `False`. There is no verified
                way to read this back meaningfully (see the module
                docstring), so it is write-only here.

        Returns:
            The newly created `OffsetPlane`, already named and appended to
            the shared geometrical set.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            UnsupportedSupportError: If `support` is not a supported value.
            ParameterTypeError: If `offset` is a `bool`, is not an
                `int`/`float`, is not finite, or if `orientation` is not a
                `bool`.
            PartialCreationError: If the plane was created but the follow-up
                rename or append failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        offset_value = _validate_finite_length(offset, "offset")
        orientation_value = _validate_orientation(orientation)
        base_plane = _resolve_support_plane(self._part_com_object, support)
        factory = self._factory()

        # One mutation for the whole operation (`docs/api-design.md` section
        # 5.3): the generation advances exactly once here, covering the
        # geometrical set's possible first-time creation, the plane itself,
        # and its rename/append, even if any of those raises part way through.
        with self._generation.mutation():
            self._geometrical_set()
            try:
                raw = factory.AddNewPlaneOffset(base_plane, offset_value, orientation_value)
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error
            self._append(raw, name)
        return OffsetPlane(raw, self._generation)

    def create_angle(
        self,
        name: str,
        support: Any,
        angle: float,
        axis_start: "tuple[float, float, float]",
        axis_end: "tuple[float, float, float]",
        orientation: bool = False,
    ) -> AnglePlane:
        """Creates a plane at an angle to a base plane, around a 3D axis line.

        The axis is built from two points and a line (`AddNewPointCoord`
        twice, then `AddNewLinePtPt`), all three appended to the shared
        geometrical set before the angle plane itself -- exactly the
        sequence probe 36 verified. Neither a `Line2D` from inside a sketch
        nor an origin plane works as the axis (both create an object whose
        `Part.Update()` fails); only an addressable 3D line does.

        Unlike `SketchCollection.create`, this does not check for an
        existing plane with the same name first (see `create_offset`).

        Args:
            name: The new plane's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`. Also
                used to derive the axis points' and line's names
                (`f"{name}_AxisStart"`, `f"{name}_AxisEnd"`, `f"{name}_Axis"`).
            support: The base plane: one of `SUPPORTED_SKETCH_SUPPORTS`
                (`"XY"`/`"YZ"`/`"ZX"`), or a plane wrapper returned by this
                class.
            angle: The angle, in the unit `AddNewPlaneAngle` itself expects
                (`docs/conventions.md` 1.2.7 gives no unit-conversion
                caveat, unlike the sketch-arc parameters in
                `geometry.sketch`, so this is passed through as given).
            axis_start: The rotation axis's start point, as an `(x, y, z)`
                millimetre tuple.
            axis_end: The rotation axis's end point, as an `(x, y, z)`
                millimetre tuple. Must differ from `axis_start`, though this
                is not checked here (unverified whether CATIA itself rejects
                a degenerate axis).
            orientation: Passed through as `AddNewPlaneAngle`'s
                `iOrientation`. Defaults to `False`. Write-only, same caveat
                as `create_offset`.

        Returns:
            The newly created `AnglePlane`, already named and appended to
            the shared geometrical set.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            UnsupportedSupportError: If `support` is not a supported value.
            ParameterTypeError: If `angle` is a `bool`, is not an
                `int`/`float`, is not finite; if `axis_start`/`axis_end` is
                not a 3-item numeric tuple/list; or if `orientation` is not
                a `bool`.
            PartialCreationError: If any of the four hybrid shapes was
                created but its follow-up rename or append failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        angle_value = _validate_finite_angle(angle, "angle")
        start_coords = _validate_point(axis_start, "axis_start")
        end_coords = _validate_point(axis_end, "axis_end")
        orientation_value = _validate_orientation(orientation)
        base_plane = _resolve_support_plane(self._part_com_object, support)
        factory = self._factory()

        # One mutation for the whole operation, exactly like create_offset:
        # this is four COM creations plus four renames/appends, but they are
        # one logical change to the model, so the generation advances exactly
        # once here, however far through this sequence a failure happens.
        with self._generation.mutation():
            self._geometrical_set()

            try:
                start_point = factory.AddNewPointCoord(*start_coords)
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error
            self._append(start_point, f"{name}_AxisStart")

            try:
                end_point = factory.AddNewPointCoord(*end_coords)
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error
            self._append(end_point, f"{name}_AxisEnd")

            try:
                axis_line = factory.AddNewLinePtPt(start_point, end_point)
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error
            self._append(axis_line, f"{name}_Axis")

            try:
                raw = factory.AddNewPlaneAngle(
                    base_plane, axis_line, angle_value, orientation_value
                )
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error
            self._append(raw, name)
        return AnglePlane(raw, self._generation)

    def list(self) -> "list[Plane]":
        """Lists the planes this SDK created, read fresh from the live Part.

        The planes are found through the geometrical set named
        `GEOMETRICAL_SET_NAME`, so they are still found after the process that
        created them has exited. This is read-only: it does not advance the model
        generation and does not create the set.

        The axis points and line `create_angle` builds are not planes and are not
        listed; `remove_geometrical_set` still removes them.

        Returns:
            One `OffsetPlane`/`AnglePlane` per plane in the set, in model-tree
            order. Empty when the Part has no such set.

        Raises:
            AmbiguousNameError: If two or more geometrical sets share the name.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        hybrid_body = self._find_geometrical_set()
        if hybrid_body is None:
            return []
        planes = []
        for shape in self._shapes_in_set(hybrid_body):
            wrapper = _PLANE_WRAPPER_BY_KIND.get(type(shape).__name__)
            if wrapper is not None:
                planes.append(wrapper(shape, self._generation))
        return planes

    def names(self) -> "list[str]":
        """Lists the names of the planes this SDK created.

        Returns:
            One name per plane, in the same order as `list`. Empty when the Part
            has no geometrical set of this module's name.

        Raises:
            AmbiguousNameError: If two or more geometrical sets share the name.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return [plane.name for plane in self.list()]

    def get(self, name: str) -> Plane:
        """Finds one plane this SDK created, by name.

        Args:
            name: The plane's name, as `names` reports it.

        Returns:
            The matching `OffsetPlane`/`AnglePlane`. It can be passed straight to
            `sketches.create(..., support=plane)` or to `remove`.

        Raises:
            PlaneNotFoundError: If no plane in the set has that name. Raised only
                after enumerating the set, so it means the plane is really absent.
            AmbiguousNameError: If two planes share the name, which CATIA allows
                and this lookup cannot resolve.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        planes = self.list()
        matches = [plane for plane in planes if plane.name == name]
        if not matches:
            raise PlaneNotFoundError(
                f"No plane named {name!r} was found in the geometrical set "
                f"{GEOMETRICAL_SET_NAME!r}. Planes that are there: "
                f"{[plane.name for plane in planes]}."
            )
        if len(matches) > 1:
            raise AmbiguousNameError(
                f"{len(matches)} planes are named {name!r}; a name-based lookup "
                "cannot safely pick one."
            )
        return matches[0]

    def remove(self, plane: Plane) -> None:
        """Deletes one plane from the model.

        Deletion goes through the editor's `Selection`, the same route
        sketches and solid features use, because `HybridBody`'s own shape
        collection has never been driven end to end against a live session --
        only reflected in the type library -- and this project does not call
        unverified COM.

        A plane created by `create_angle` leaves its two axis points and its
        axis line behind: they are separate hybrid shapes, and deleting the
        plane does not cascade to them. Use `remove_geometrical_set` to clear
        everything this collection created at once.

        This deletes model content. It does not call `Part.Update()`, and it
        never saves. Any sketch built on the plane is invalidated by its
        removal, so remove the sketch first.

        Args:
            plane: A plane this collection created.

        Raises:
            ParameterTypeError: If `plane` is not a `Plane`.
            Auto3dxError: If no editor selection is available, or the
                deletion failed.
        """
        if not isinstance(plane, Plane):
            raise ParameterTypeError(
                f"plane must be a Plane, not {type(plane).__name__}."
            )
        # One mutation for the whole operation: the delete and the follow-up
        # in-work-object reclaim are one logical change, so the generation
        # advances exactly once, even if the missing-selection check inside
        # delete_via_selection is what actually raises.
        with self._generation.mutation():
            delete_via_selection(
                self._selection, plane.com_object, f"plane {plane.name!r}", self._part_com_object
            )
            self._reclaim_main_body()

    def remove_geometrical_set(self) -> None:
        """Deletes the geometrical set holding every plane this collection made.

        This is the only way to clear an angled plane's axis points and line,
        which `remove` leaves behind. Deleting the set removes its whole
        contents, so every plane this collection created goes with it, along
        with anything else that happens to live in a set of the same name.

        The set is found in the live Part by name, so this removes one created by
        an earlier process or by another `PlaneCollection` just as well as one
        created through this instance.

        Does nothing if the Part has no such set, so it is safe to call in a
        `finally`. It does not call `Part.Update()`, and it never saves.

        Raises:
            AmbiguousNameError: If two or more geometrical sets share the name.
            Auto3dxError: If no editor selection is available, or the
                deletion failed.
        """
        hybrid_body = self._find_geometrical_set()
        if hybrid_body is None:
            # There is no such set in the model, so there is nothing to touch in
            # CATIA and no reason to advance the generation (`docs/api-design.md`
            # section 5.2: only a change made through the SDK advances it).
            return
        # One mutation for the whole operation, same reasoning as remove().
        with self._generation.mutation():
            delete_via_selection(
                self._selection,
                hybrid_body,
                f"geometrical set {GEOMETRICAL_SET_NAME!r}",
                self._part_com_object,
            )
            self._reclaim_main_body()

