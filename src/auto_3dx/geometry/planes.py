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

**Why there is no `ensure_offset`/`ensure_angle`.** This project's `ensure_*`
rule (`docs/conventions.md` 1.3) is that a name match alone never justifies
reusing geometry; only a value read back and compared does. For an offset
plane, `Offset.Value` and the base plane's `Plane.DisplayName` are both
verified readable, so that comparison could be made honestly. But making it
requires *finding* the candidate plane by name first, and unlike
`Sketches`/`Shapes`/`Parameters` -- whose `Count`/`Item(i)` enumeration was
exercised end to end in this project's probes (created, then successfully
read back) -- a geometrical set's own shape collection has never been
enumerated that way here; `HybridShapes` appears only as a declared, readable
member name in a type-library reflection dump (probe 29), never driven with
`Count`/`Item(i)` and matched against a shape whose name we just set. Without
that other half, a by-name lookup could easily return nothing (or the wrong
thing) while looking like it works. Exactly like `ConstRadEdgeFillet`/
`Chamfer` in `geometry.part_design`, a missing `ensure_*` is safer than one
resting on an unverified enumeration, so `create_offset`/`create_angle` are
the only creation paths this module offers; a caller wanting idempotency
across runs must track the returned `Plane` itself.
"""

import math
from typing import Any

import pywintypes

from auto_3dx.errors import (
    Auto3dxError,
    ParameterTypeError,
    PartialCreationError,
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
line all live in one `HybridBody`.
"""


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

    def __init__(self, com_object: Any) -> None:
        """Initializes the wrapper.

        Args:
            com_object: The raw CATIA hybrid plane shape COM object to wrap.
        """
        self._com_object = com_object

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


class PlaneCollection:
    """Creates offset and angled hybrid planes on a Part.

    Every plane this collection creates lives in one lazily-created
    `HybridBody` named `GEOMETRICAL_SET_NAME`, cached on this instance for
    its lifetime -- matching probe 36, where a single geometrical set holds
    every plane, plus the angle plane's axis points and line.
    """

    def __init__(self, part_com_object: Any, selection: Any = None) -> None:
        """Initializes the wrapper.

        Args:
            part_com_object: The raw CATIA `Part` COM object. `HybridBodies`
                and `HybridShapeFactory` are read from it to create planes;
                `OriginElements` is read from it to resolve a string
                `support`; `MainBody` and `InWorkObject` are used by the
                in-work-object discipline (see the module docstring).
            selection: The raw CATIA `Selection` COM object from the editor.
                Required only by `remove`, because neither `HybridBodies` nor
                a `HybridBody` exposes a verified `Remove` method and deletion
                has to go through the editor's selection, exactly as it does
                for sketches and solid features. Creating works without it.
        """
        self._part_com_object = part_com_object
        self._selection = selection
        self._hybrid_body: Any = None

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
            self._part_com_object.InWorkObject = self._main_body()
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

        Raises:
            PartialCreationError: If the geometrical set was created but the
                follow-up rename failed. It is still cached and usable under
                its default CATIA name; a retry will not create a second one
                on top of it.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        if self._hybrid_body is not None:
            return self._hybrid_body
        try:
            hybrid_body = self._part_com_object.HybridBodies.Add()
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        # Cached before the rename is even attempted: the geometrical set
        # already exists in the model at this point, and a later retry must
        # not call HybridBodies.Add() again on top of it.
        self._hybrid_body = hybrid_body
        try:
            hybrid_body.Name = GEOMETRICAL_SET_NAME
        except pywintypes.com_error as error:
            self._reclaim_main_body()
            raise PartialCreationError(
                "Created the geometrical set that holds every plane this "
                f"collection creates, but failed to rename it to "
                f"{GEOMETRICAL_SET_NAME!r}; it is still usable, under its "
                "default CATIA name, and is already cached so a retry will "
                "not create a second one."
            ) from error
        self._reclaim_main_body()
        return self._hybrid_body

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
        self._geometrical_set()
        try:
            raw = factory.AddNewPlaneOffset(base_plane, offset_value, orientation_value)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        self._append(raw, name)
        return OffsetPlane(raw)

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
            raw = factory.AddNewPlaneAngle(base_plane, axis_line, angle_value, orientation_value)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        self._append(raw, name)
        return AnglePlane(raw)

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
        delete_via_selection(self._selection, plane.com_object, f"plane {plane.name!r}")
        self._reclaim_main_body()

    def remove_geometrical_set(self) -> None:
        """Deletes the geometrical set holding every plane this collection made.

        This is the only way to clear an angled plane's axis points and line,
        which `remove` leaves behind. Deleting the set removes its whole
        contents, so every plane this collection created goes with it, along
        with anything else that happens to live in a set of the same name.

        Does nothing if no set has been created yet, so it is safe to call in
        a `finally`. It does not call `Part.Update()`, and it never saves.

        Raises:
            Auto3dxError: If no editor selection is available, or the
                deletion failed.
        """
        if self._hybrid_body is None:
            return
        delete_via_selection(
            self._selection, self._hybrid_body, f"geometrical set {GEOMETRICAL_SET_NAME!r}"
        )
        # The cache must go too, or the next create would append to a set that
        # no longer exists in the model.
        self._hybrid_body = None
        self._reclaim_main_body()

