"""Wrappers around CATIA `Pad`/`Pocket`/`Shaft`/`Groove`/`Mirror` Part Design features.

A `Pad` extrudes a `Sketch` profile along its normal by a fixed height. A
`Pocket` removes material along the same profile by a fixed depth. Verified
against a live session (`docs/conventions.md` section 1.2.1), `Pocket`'s
readable properties are identical to `Pad`'s, and `FirstLimit.Dimension.Value`
holds the magnitude passed to `AddNewPad`/`AddNewPocket` at creation for both.
That structural symmetry is factored into a shared `SketchFeature` base;
`Pad` and `Pocket` differ only in their `type(com_object).__name__` and, for
`Pad`, the pre-existing `height`/`set_height` public API kept for backward
compatibility.

`Shaft` and `Groove` are the revolved counterparts (`docs/conventions.md`
section 1.2.3): each revolves a `Sketch` profile around the axis set on that
sketch's `CenterLine`, adding material for a `Shaft` and removing it for a
`Groove`, and both expose `FirstAngle`/`SecondAngle` instead of `FirstLimit`.
That symmetry is factored into a shared `RevolvedFeature` base, the same way
`SketchFeature` is shared by `Pad`/`Pocket`. `Mirror` stands apart: it takes a
plane rather than a sketch, so it carries no `sketch()` accessor and no
common base with the other four.

None of these features has a dedicated typed sub-collection in the verified
API surface, so `PartDesign` finds them all by scanning `MainBody.Shapes` and
keeping items whose `type(item).__name__` matches the relevant `*_KIND`
constant.
"""

import math
from typing import Any

import pywintypes

from auto_3dx.errors import (
    AmbiguousNameError,
    Auto3dxError,
    FeatureConflictError,
    FeatureNotFoundError,
    PartialCreationError,
    UnsupportedSupportError,
)
from auto_3dx.geometry.deletion import delete_via_selection
from auto_3dx.geometry.sketch import (
    SUPPORT_YZ,
    SUPPORTED_SKETCH_SUPPORTS,
    Sketch,
    _PLANE_ATTRIBUTE_BY_SUPPORT,
    _wrap_com_error,
)
from auto_3dx.parameters.parameter import (
    DEGREE,
    MILLIMETRE,
    Parameter,
    validate_angle_unit,
    validate_angle_value,
    validate_length_unit,
    validate_length_value,
    validate_parameter_name,
)

LENGTH_TOLERANCE: float = 1e-9
"""Absolute tolerance used to compare feature depths with `math.isclose`."""

PAD_KIND: str = "Pad"
"""The `type(com_object).__name__` value for a CATIA Pad feature."""

POCKET_KIND: str = "Pocket"
"""The `type(com_object).__name__` value for a CATIA Pocket feature."""

SHAFT_KIND: str = "Shaft"
"""The `type(com_object).__name__` value for a CATIA Shaft feature."""

GROOVE_KIND: str = "Groove"
"""The `type(com_object).__name__` value for a CATIA Groove feature."""

MIRROR_KIND: str = "Mirror"
"""The `type(com_object).__name__` value for a CATIA Mirror feature."""

FULL_REVOLUTION: float = 360.0
"""The verified default `FirstAngle.Value` (degrees) a new Shaft/Groove is created with."""


def _scan_shapes(shapes: Any, kind: str) -> "list[Any]":
    """Enumerates a `Shapes` collection and returns the raw items of one kind.

    Shared by every `PartDesign` listing/lookup method so the `Count`/`Item(i)`
    scan and the `type(item).__name__` filter are written once, for both pads
    and pockets.

    Args:
        shapes: The raw CATIA `Shapes` collection (`MainBody.Shapes`).
        kind: The `type(item).__name__` to keep (`PAD_KIND` or `POCKET_KIND`).

    Returns:
        Every raw COM object in `shapes` whose wrapper type matches `kind`,
        in `Item(i)` order.

    Raises:
        Auto3dxError: If the underlying COM call fails unexpectedly.
    """
    try:
        count = shapes.Count
    except pywintypes.com_error as error:
        raise _wrap_com_error(error) from error
    result: list[Any] = []
    for index in range(1, count + 1):
        try:
            item = shapes.Item(index)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        if type(item).__name__ == kind:
            result.append(item)
    return result


class SketchFeature:
    """Common wrapper for a sketch-based Part Design feature (`Pad`/`Pocket`).

    Verified structurally identical for both kinds (`docs/conventions.md`
    section 1.2.1): the feature's magnitude is read from and written to
    `FirstLimit.Dimension.Value`, matching the value passed to
    `AddNewPad`/`AddNewPocket` when the feature was created.
    """

    def __init__(self, com_object: Any) -> None:
        """Initializes the wrapper.

        Args:
            com_object: The raw CATIA `Pad` or `Pocket` COM object to wrap.
        """
        self._com_object = com_object

    @property
    def com_object(self) -> Any:
        """Returns the raw underlying COM object.

        This is an escape hatch for callers that need direct COM access, and
        is useful in tests.

        Returns:
            The wrapped raw COM object.
        """
        return self._com_object

    @property
    def name(self) -> str:
        """Returns the feature's name.

        Returns:
            The feature's `Name`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Name
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def depth(self) -> float:
        """Returns the feature's extrusion/removal magnitude.

        Returns:
            `FirstLimit.Dimension.Value`, verified to equal the magnitude
            passed to `AddNewPad`/`AddNewPocket` when the feature was
            created.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.FirstLimit.Dimension.Value
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def set_depth(self, depth: float, unit: str = MILLIMETRE) -> None:
        """Sets the feature's extrusion/removal magnitude.

        Args:
            depth: The new magnitude.
            unit: The unit `depth` is expressed in. Defaults to `MILLIMETRE`.

        Raises:
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `depth` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_length_unit(unit)
        coerced = validate_length_value(depth)
        try:
            self._com_object.FirstLimit.Dimension.Value = coerced
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def sketch(self) -> Sketch:
        """Returns the sketch this feature was built from.

        Returns:
            A `Sketch` wrapping the feature's `Sketch` property.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return Sketch(self._com_object.Sketch)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def depth_parameter(self) -> Parameter:
        """Returns the `Dimension` parameter backing this feature's depth.

        This is the object a `Formula` targets to drive the feature (verified,
        `docs/conventions.md` section 1.2.1): `Parameters.GetNameToUseInRelation`
        on it resolves to `PartBody\\<feature>\\FirstLimit\\Length`.

        Returns:
            A `Parameter` wrapping `FirstLimit.Dimension`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            dimension = self._com_object.FirstLimit.Dimension
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        return Parameter(dimension)

    def __repr__(self) -> str:
        """Returns a debugging representation.

        Returns:
            A string such as ``Pad(name='Pad.1', depth=20.0)``.
        """
        try:
            name = self.name
            depth: object = self.depth
        except Auto3dxError:
            name = "<unavailable>"
            depth = "<unavailable>"
        return f"{type(self).__name__}(name={name!r}, depth={depth!r})"


class Pad(SketchFeature):
    """Wraps a raw CATIA `Pad` COM object.

    `height`/`set_height` are the pad's pre-existing public API (covered by
    existing tests and by a live integration test) and must keep working
    exactly as before; both are now thin aliases over
    `SketchFeature.depth`/`set_depth`.
    """

    @property
    def height(self) -> float:
        """Returns the pad's extrusion height.

        Returns:
            `FirstLimit.Dimension.Value`, verified to equal the height passed
            to `AddNewPad` when the pad was created. Same as `depth`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self.depth

    def set_height(self, height: float, unit: str = MILLIMETRE) -> None:
        """Sets the pad's extrusion height.

        Args:
            height: The new height.
            unit: The unit `height` is expressed in. Defaults to `MILLIMETRE`.

        Raises:
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `height` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        self.set_depth(height, unit)


class Pocket(SketchFeature):
    """Wraps a raw CATIA `Pocket` COM object.

    Verified structurally identical to `Pad` (`docs/conventions.md` section
    1.2.1): same readable properties, same `FirstLimit.Dimension.Value`
    semantics. No members beyond `SketchFeature` are needed.
    """


class RevolvedFeature:
    """Common wrapper for a sketch-based revolve feature (`Shaft`/`Groove`).

    Verified structurally identical for both kinds (`docs/conventions.md`
    section 1.2.3): unlike `Pad`/`Pocket`, a revolve feature has no
    `FirstLimit`; instead it exposes `FirstAngle`/`SecondAngle` (`Angle`
    objects, in degrees), defaulting to 360.0/0.0 when the feature is
    created. Creating one requires the sketch to already have `CenterLine`
    set (see `Sketch.set_center_line`) and a profile drawn away from that
    axis; this library cannot verify that requirement ahead of time, so a
    missing or degenerate axis surfaces as whatever `Auto3dxError` the failed
    COM call produces.
    """

    def __init__(self, com_object: Any) -> None:
        """Initializes the wrapper.

        Args:
            com_object: The raw CATIA `Shaft` or `Groove` COM object to wrap.
        """
        self._com_object = com_object

    @property
    def com_object(self) -> Any:
        """Returns the raw underlying COM object.

        This is an escape hatch for callers that need direct COM access, and
        is useful in tests.

        Returns:
            The wrapped raw COM object.
        """
        return self._com_object

    @property
    def name(self) -> str:
        """Returns the feature's name.

        Returns:
            The feature's `Name`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Name
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def first_angle(self) -> float:
        """Returns the feature's first revolve angle.

        Returns:
            `FirstAngle.Value`, in degrees. Verified default `FULL_REVOLUTION`
            (360.0) for a freshly created feature.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.FirstAngle.Value
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def second_angle(self) -> float:
        """Returns the feature's second revolve angle.

        Returns:
            `SecondAngle.Value`, in degrees. Verified default 0.0 for a
            freshly created feature.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.SecondAngle.Value
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def set_first_angle(self, angle: float, unit: str = DEGREE) -> None:
        """Sets the feature's first revolve angle.

        Args:
            angle: The new angle.
            unit: The unit `angle` is expressed in. Defaults to `DEGREE`.

        Raises:
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `angle` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_angle_unit(unit)
        coerced = validate_angle_value(angle)
        try:
            self._com_object.FirstAngle.Value = coerced
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def set_second_angle(self, angle: float, unit: str = DEGREE) -> None:
        """Sets the feature's second revolve angle.

        Args:
            angle: The new angle.
            unit: The unit `angle` is expressed in. Defaults to `DEGREE`.

        Raises:
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `angle` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_angle_unit(unit)
        coerced = validate_angle_value(angle)
        try:
            self._com_object.SecondAngle.Value = coerced
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def sketch(self) -> Sketch:
        """Returns the sketch this feature was built from.

        Returns:
            A `Sketch` wrapping the feature's `Sketch` property.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return Sketch(self._com_object.Sketch)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def first_angle_parameter(self) -> Parameter:
        """Returns the `Angle` parameter backing this feature's first angle.

        This is the object a `Formula` targets to drive the feature, the same
        idea as `SketchFeature.depth_parameter()`.

        Returns:
            A `Parameter` wrapping `FirstAngle`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            angle = self._com_object.FirstAngle
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        return Parameter(angle)

    def __repr__(self) -> str:
        """Returns a debugging representation.

        Returns:
            A string such as ``Shaft(name='Shaft.1', first_angle=360.0,
            second_angle=0.0)``.
        """
        try:
            name = self.name
            first_angle: object = self.first_angle
            second_angle: object = self.second_angle
        except Auto3dxError:
            name = "<unavailable>"
            first_angle = "<unavailable>"
            second_angle = "<unavailable>"
        return (
            f"{type(self).__name__}(name={name!r}, first_angle={first_angle!r}, "
            f"second_angle={second_angle!r})"
        )


class Shaft(RevolvedFeature):
    """Wraps a raw CATIA `Shaft` COM object.

    A shaft revolves a sketch profile to add material. No members beyond
    `RevolvedFeature` are needed.
    """


class Groove(RevolvedFeature):
    """Wraps a raw CATIA `Groove` COM object.

    A groove revolves a sketch profile to remove material. No members beyond
    `RevolvedFeature` are needed.
    """


class Mirror:
    """Wraps a raw CATIA `Mirror` COM object.

    Unlike every other feature in this module, a mirror is not built from a
    `Sketch`: `AddNewMirror` takes a plane (verified against
    `OriginElements.PlaneYZ`, `docs/conventions.md` section 1.2.3), so this
    wrapper carries no `sketch()` accessor.
    """

    def __init__(self, com_object: Any) -> None:
        """Initializes the wrapper.

        Args:
            com_object: The raw CATIA `Mirror` COM object to wrap.
        """
        self._com_object = com_object

    @property
    def com_object(self) -> Any:
        """Returns the raw underlying COM object.

        This is an escape hatch for callers that need direct COM access, and
        is useful in tests.

        Returns:
            The wrapped raw COM object.
        """
        return self._com_object

    @property
    def name(self) -> str:
        """Returns the feature's name.

        Returns:
            The feature's `Name`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Name
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def __repr__(self) -> str:
        """Returns a debugging representation.

        Returns:
            A string such as ``Mirror(name='Mirror.1')``.
        """
        try:
            name = self.name
        except Auto3dxError:
            name = "<unavailable>"
        return f"Mirror(name={name!r})"


class PartDesign:
    """Wraps Part Design features on a Part's `MainBody`.

    Pads, pockets, shafts, grooves, and mirrors are all read from
    `part_com_object.MainBody.Shapes`, filtered by `type(item).__name__`
    (`PAD_KIND`/`POCKET_KIND`/`SHAFT_KIND`/`GROOVE_KIND`/`MIRROR_KIND`), and
    created through the matching `part_com_object.ShapeFactory.AddNew*`
    method. All five families share identical policy (existence/ambiguity
    checks by enumeration, partial-creation reporting on a failed rename,
    deletion via selection); that shared behaviour is factored into the
    private `_list`/`_get`/`_create_feature`/`_ensure_by_sketch`/`_remove`
    helpers below, parameterised by kind. Pad/Pocket additionally compare and
    (in `ensure_*`) synchronise a `depth`/`height` magnitude, which
    Shaft/Groove/Mirror do not have; `_create`/`_ensure` layer that
    length-specific validation on top of the shared core for Pad/Pocket only.
    """

    def __init__(self, part_com_object: Any, selection: Any = None) -> None:
        """Initializes the wrapper.

        Args:
            part_com_object: The raw CATIA `Part` COM object. Both
                `MainBody.Shapes` (for existing features) and `ShapeFactory`
                (for creating new ones) are read from it. `OriginElements` is
                also read from it, for `create_mirror`'s plane lookup.
            selection: The raw CATIA `Selection` COM object from the editor.
                Required only by the `remove_*` methods, because `Shapes` has
                no `Remove` method and deletion has to go through the
                editor's selection. Reading and creating work without it.
        """
        self._part_com_object = part_com_object
        self._selection = selection

    def _shapes(self) -> Any:
        """Returns the raw `MainBody.Shapes` collection.

        Returns:
            The raw CATIA `Shapes` collection.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._part_com_object.MainBody.Shapes
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def _list(self, kind: str, wrapper_cls: type) -> "list[Any]":
        """Lists every feature of one kind on the Part's `MainBody`.

        Args:
            kind: `PAD_KIND`, `POCKET_KIND`, `SHAFT_KIND`, `GROOVE_KIND`, or
                `MIRROR_KIND`.
            wrapper_cls: `Pad`, `Pocket`, `Shaft`, `Groove`, or `Mirror`.

        Returns:
            A `wrapper_cls` instance for each matching item in
            `MainBody.Shapes`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return [wrapper_cls(item) for item in _scan_shapes(self._shapes(), kind)]

    def _get(self, kind: str, wrapper_cls: type, noun: str, name: str) -> Any:
        """Looks up a feature of one kind by name.

        Names are not guaranteed unique (CATIA does not enforce it for
        sketches, and features carry no stronger guarantee), so every
        matching feature is enumerated and the match count decides the
        outcome rather than returning on the first hit.

        Args:
            kind: `PAD_KIND`, `POCKET_KIND`, `SHAFT_KIND`, `GROOVE_KIND`, or
                `MIRROR_KIND`.
            wrapper_cls: `Pad`, `Pocket`, `Shaft`, `Groove`, or `Mirror`.
            noun: `"pad"`, `"pocket"`, `"shaft"`, `"groove"`, or `"mirror"`,
                used only in error messages.
            name: The feature's name.

        Returns:
            The matching `wrapper_cls` instance.

        Raises:
            FeatureNotFoundError: If no matching feature named `name` exists.
            AmbiguousNameError: If two or more matching features named `name`
                exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        matches = [feature for feature in self._list(kind, wrapper_cls) if feature.name == name]
        if not matches:
            raise FeatureNotFoundError(f"No {noun} named {name!r} was found.")
        if len(matches) > 1:
            raise AmbiguousNameError(
                f"{len(matches)} {noun}s named {name!r} exist; a name-based "
                "lookup cannot safely pick one."
            )
        return matches[0]

    def _create(
        self,
        name: str,
        sketch: Sketch,
        depth: float,
        unit: str,
        kind: str,
        factory_method: str,
        wrapper_cls: type,
        noun: str,
    ) -> Any:
        """Creates a new sketch-based feature with a length magnitude (Pad/Pocket).

        Validates and coerces the length-specific arguments, then delegates
        the existence check, the factory call, and the rename/`PartialCreationError`
        handling to `_create_feature`.

        Args:
            name: The new feature's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            sketch: The `Sketch` to build the feature from.
            depth: The feature's magnitude (height for a pad, depth for a
                pocket).
            unit: The unit `depth` is expressed in.
            kind: `PAD_KIND` or `POCKET_KIND`, used for the pre-create
                duplicate check.
            factory_method: `"AddNewPad"` or `"AddNewPocket"`.
            wrapper_cls: `Pad` or `Pocket`.
            noun: `"pad"` or `"pocket"`, used only in error messages.

        Returns:
            The newly created `wrapper_cls` instance, already renamed to
            `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `depth` is not an `int`/`float` (or is a `bool`).
            FeatureConflictError: If a feature named `name` already exists.
            AmbiguousNameError: If two or more features named `name` already
                exist.
            PartialCreationError: If the feature was created but the
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        validate_length_unit(unit)
        coerced = validate_length_value(depth)
        return self._create_feature(
            name, kind, factory_method, (sketch.com_object, coerced), wrapper_cls, noun
        )

    def _create_feature(
        self,
        name: str,
        kind: str,
        factory_method: str,
        factory_args: "tuple[Any, ...]",
        wrapper_cls: type,
        noun: str,
    ) -> Any:
        """Creates a new Part Design feature through `ShapeFactory`.

        This is the part of feature creation that every kind shares: the
        pre-create existence check (mirroring the duplicate-name guards used
        elsewhere in this library), the `AddNew*` call, and the follow-up
        rename with `PartialCreationError` reporting on failure. Callers
        validate and assemble their own `factory_args` first -- this method
        does not know or care whether a magnitude is involved.

        Args:
            name: The new feature's name. Must already be validated by the
                caller (via `validate_parameter_name`).
            kind: `PAD_KIND`, `POCKET_KIND`, `SHAFT_KIND`, `GROOVE_KIND`, or
                `MIRROR_KIND`, used for the pre-create duplicate check.
            factory_method: The `ShapeFactory` method name, e.g.
                `"AddNewPad"`.
            factory_args: The positional arguments to pass to that method
                (already validated/coerced raw COM values, never wrapper
                objects).
            wrapper_cls: `Pad`, `Pocket`, `Shaft`, `Groove`, or `Mirror`.
            noun: `"pad"`, `"pocket"`, `"shaft"`, `"groove"`, or `"mirror"`,
                used only in error messages.

        Returns:
            The newly created `wrapper_cls` instance, already renamed to
            `name`.

        Raises:
            FeatureConflictError: If a feature named `name` already exists.
            AmbiguousNameError: If two or more features named `name` already
                exist.
            PartialCreationError: If the feature was created but the
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            self._get(kind, wrapper_cls, noun, name)
        except FeatureNotFoundError:
            pass
        else:
            raise FeatureConflictError(f"A {noun} named {name!r} already exists.")

        try:
            factory = getattr(self._part_com_object.ShapeFactory, factory_method)
            com_object = factory(*factory_args)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        feature = wrapper_cls(com_object)
        # AddNew* already mutated the model; if the rename below fails, a
        # default-named feature is left behind rather than rolled back
        # (deleting a pad/pocket cascade-deletes its sketch, which makes
        # automatic rollback more dangerous than reporting).
        try:
            feature.com_object.Name = name
        except pywintypes.com_error as error:
            try:
                actual_name = feature.name
            except Auto3dxError:
                actual_name = "unknown"
            raise PartialCreationError(
                f"Created a {noun} but failed to rename it to {name!r}; it "
                f"currently exists in the model as {actual_name!r}. Do not "
                f"retry blindly: retrying would create another {noun} instead "
                "of fixing this one."
            ) from error
        return feature

    def _ensure(
        self,
        name: str,
        sketch: Sketch,
        depth: float,
        unit: str,
        get_method: Any,
        create_method: Any,
        noun: str,
    ) -> Any:
        """Creates a feature, or reuses/updates it if one with the same name exists.

        Policy (see `docs/conventions.md` section 1.3):
            - No matching feature named `name` exists: create it.
            - A matching feature named `name` exists on the same sketch and
              the same depth: reuse it unchanged.
            - A matching feature named `name` exists on the same sketch but a
              different depth: update `FirstLimit.Dimension.Value` to `depth`.
            - A matching feature named `name` exists on a different sketch:
              raise `FeatureConflictError`.

        Validates and coerces the length-specific arguments, then delegates
        the existence/sketch-identity check to `_ensure_by_sketch`, passing a
        `sync_existing` callback that performs the depth comparison/update.

        Args:
            name: The feature's name.
            sketch: The `Sketch` the feature must be built from.
            depth: The feature's magnitude.
            unit: The unit `depth` is expressed in.
            get_method: `self.get_pad` or `self.get_pocket`.
            create_method: `self.create_pad` or `self.create_pocket`.
            noun: `"pad"` or `"pocket"`, used only in error messages.

        Returns:
            The existing (possibly updated) or newly created feature.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `depth` is not an `int`/`float` (or is a `bool`).
            AmbiguousNameError: If two or more matching features named `name`
                already exist.
            FeatureConflictError: If a matching feature named `name` already
                exists on a different sketch.
            PartialCreationError: If a new feature had to be created and its
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        validate_length_unit(unit)
        coerced = validate_length_value(depth)

        def sync_existing(existing: Any) -> None:
            if not math.isclose(existing.depth, coerced, rel_tol=0.0, abs_tol=LENGTH_TOLERANCE):
                existing.set_depth(depth, unit)

        return self._ensure_by_sketch(
            name,
            sketch,
            get_method,
            lambda: create_method(name, sketch, depth, unit),
            noun,
            sync_existing,
        )

    def _ensure_by_sketch(
        self,
        name: str,
        sketch: Sketch,
        get_method: Any,
        create: Any,
        noun: str,
        sync_existing: Any = None,
    ) -> Any:
        """Reuses an existing sketch-based feature by name, or creates one.

        This is the part every `ensure_*` shares: look the feature up by
        name, create it if absent, and otherwise verify it was built from the
        same sketch before reusing it. "Same sketch" is judged by COM
        identity (`==` on the raw `Sketch` objects), not by name: names are
        writable and CATIA does not reject a duplicate, so a name match alone
        would be forgeable.

        Args:
            name: The feature's name.
            sketch: The `Sketch` the feature must be built from.
            get_method: `self.get_pad`, `self.get_pocket`, `self.get_shaft`,
                or `self.get_groove`.
            create: A zero-argument callable that creates and returns the new
                feature when none exists yet.
            noun: `"pad"`, `"pocket"`, `"shaft"`, or `"groove"`, used only in
                error messages.
            sync_existing: An optional callable invoked with the existing
                feature when one is found on the same sketch, for kinds that
                need to reconcile a magnitude (Pad/Pocket depth). `None`
                (the default) leaves an existing match untouched, which is
                the required policy for Shaft/Groove: their angles are only
                ever changed by an explicit `set_first_angle`/`set_second_angle`
                call, never implicitly by `ensure_*`.

        Returns:
            The existing (possibly synchronised) or newly created feature.

        Raises:
            FeatureConflictError: If a matching feature named `name` already
                exists on a different sketch.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            existing = get_method(name)
        except FeatureNotFoundError:
            return create()

        try:
            same_sketch = existing.sketch().com_object == sketch.com_object
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        if not same_sketch:
            raise FeatureConflictError(
                f"{noun.capitalize()} {name!r} already exists on a different "
                f"sketch ({existing.sketch().name!r} instead of {sketch.name!r})."
            )

        if sync_existing is not None:
            sync_existing(existing)
        return existing

    def _remove(self, name: str, get_method: Any, noun: str) -> None:
        """Removes a feature from the model.

        `Shapes` exposes no `Remove` method, so deletion goes through the
        editor's `Selection`. That means this method needs the `selection`
        the wrapper was constructed with; obtain the Part via
        `Catia.active_part()` to get one wired in.

        The feature is looked up first so a missing name is reported as
        `FeatureNotFoundError`. Removing a pad/pocket cascade-deletes its
        sketch (verified in `docs/conventions.md` section 1.2), so a
        following `SketchCollection.remove` for that sketch will legitimately
        fail.

        This deletes model content. It does not call `Part.Update()`, and it
        never saves.

        Args:
            name: The feature's name.
            get_method: `self.get_pad`, `self.get_pocket`, `self.get_shaft`,
                `self.get_groove`, or `self.get_mirror`.
            noun: `"pad"`, `"pocket"`, `"shaft"`, `"groove"`, or `"mirror"`,
                used only in the deletion's error message.

        Raises:
            FeatureNotFoundError: If no matching feature named `name` exists.
            Auto3dxError: If no editor selection is available, or the
                deletion failed.
        """
        target = get_method(name)
        delete_via_selection(self._selection, target.com_object, f"{noun} {name!r}")

    @property
    def pads(self) -> "list[Pad]":
        """Lists every pad on the Part's `MainBody`.

        Returns:
            A `Pad` wrapper for each item in `MainBody.Shapes` whose wrapper
            type is `PAD_KIND`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._list(PAD_KIND, Pad)

    def get_pad(self, name: str) -> Pad:
        """Looks up a pad by name.

        Args:
            name: The pad's name.

        Returns:
            The matching `Pad`.

        Raises:
            FeatureNotFoundError: If no pad named `name` exists.
            AmbiguousNameError: If two or more pads named `name` exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._get(PAD_KIND, Pad, "pad", name)

    def create_pad(
        self,
        name: str,
        sketch: Sketch,
        height: float,
        unit: str = MILLIMETRE,
    ) -> Pad:
        """Creates a new pad extruding `sketch` by `height`.

        Args:
            name: The new pad's name. Must be non-empty, without surrounding
                whitespace, and must not contain `"\\"`.
            sketch: The `Sketch` to extrude.
            height: The extrusion height.
            unit: The unit `height` is expressed in. Defaults to `MILLIMETRE`.

        Returns:
            The newly created `Pad`, already renamed to `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `height` is not an `int`/`float` (or is a `bool`).
            FeatureConflictError: If a pad named `name` already exists.
            AmbiguousNameError: If two or more pads named `name` already exist.
            PartialCreationError: If the pad was created but the follow-up
                rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._create(name, sketch, height, unit, PAD_KIND, "AddNewPad", Pad, "pad")

    def ensure_pad(
        self,
        name: str,
        sketch: Sketch,
        height: float,
        unit: str = MILLIMETRE,
    ) -> Pad:
        """Creates a pad, or reuses/updates it if one with the same name exists.

        See `docs/conventions.md` section 1.3 for the full policy.

        Args:
            name: The pad's name.
            sketch: The `Sketch` the pad must extrude.
            height: The extrusion height.
            unit: The unit `height` is expressed in. Defaults to `MILLIMETRE`.

        Returns:
            The existing (possibly updated) or newly created `Pad`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `height` is not an `int`/`float` (or is a `bool`).
            AmbiguousNameError: If two or more pads named `name` already exist.
            FeatureConflictError: If a pad named `name` already exists on a
                different sketch.
            PartialCreationError: If a new pad had to be created and its
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._ensure(name, sketch, height, unit, self.get_pad, self.create_pad, "pad")

    def remove_pad(self, name: str) -> None:
        """Removes a pad from the model.

        Args:
            name: The pad's name.

        Raises:
            FeatureNotFoundError: If no pad named `name` exists.
            Auto3dxError: If no editor selection is available, or the deletion
                failed.
        """
        self._remove(name, self.get_pad, "pad")

    @property
    def pockets(self) -> "list[Pocket]":
        """Lists every pocket on the Part's `MainBody`.

        Returns:
            A `Pocket` wrapper for each item in `MainBody.Shapes` whose
            wrapper type is `POCKET_KIND`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._list(POCKET_KIND, Pocket)

    def get_pocket(self, name: str) -> Pocket:
        """Looks up a pocket by name.

        Args:
            name: The pocket's name.

        Returns:
            The matching `Pocket`.

        Raises:
            FeatureNotFoundError: If no pocket named `name` exists.
            AmbiguousNameError: If two or more pockets named `name` exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._get(POCKET_KIND, Pocket, "pocket", name)

    def create_pocket(
        self,
        name: str,
        sketch: Sketch,
        depth: float,
        unit: str = MILLIMETRE,
    ) -> Pocket:
        """Creates a new pocket removing material along `sketch` by `depth`.

        Args:
            name: The new pocket's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            sketch: The `Sketch` to cut along.
            depth: The removal depth.
            unit: The unit `depth` is expressed in. Defaults to `MILLIMETRE`.

        Returns:
            The newly created `Pocket`, already renamed to `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `depth` is not an `int`/`float` (or is a `bool`).
            FeatureConflictError: If a pocket named `name` already exists.
            AmbiguousNameError: If two or more pockets named `name` already
                exist.
            PartialCreationError: If the pocket was created but the follow-up
                rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._create(
            name, sketch, depth, unit, POCKET_KIND, "AddNewPocket", Pocket, "pocket"
        )

    def ensure_pocket(
        self,
        name: str,
        sketch: Sketch,
        depth: float,
        unit: str = MILLIMETRE,
    ) -> Pocket:
        """Creates a pocket, or reuses/updates it if one with the same name exists.

        Policy identical to `ensure_pad` (`docs/conventions.md` section 1.3),
        applied to pockets.

        Args:
            name: The pocket's name.
            sketch: The `Sketch` the pocket must be built from.
            depth: The removal depth.
            unit: The unit `depth` is expressed in. Defaults to `MILLIMETRE`.

        Returns:
            The existing (possibly updated) or newly created `Pocket`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `depth` is not an `int`/`float` (or is a `bool`).
            AmbiguousNameError: If two or more pockets named `name` already
                exist.
            FeatureConflictError: If a pocket named `name` already exists on a
                different sketch.
            PartialCreationError: If a new pocket had to be created and its
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._ensure(
            name, sketch, depth, unit, self.get_pocket, self.create_pocket, "pocket"
        )

    def remove_pocket(self, name: str) -> None:
        """Removes a pocket from the model.

        Args:
            name: The pocket's name.

        Raises:
            FeatureNotFoundError: If no pocket named `name` exists.
            Auto3dxError: If no editor selection is available, or the deletion
                failed.
        """
        self._remove(name, self.get_pocket, "pocket")

    @property
    def shafts(self) -> "list[Shaft]":
        """Lists every shaft on the Part's `MainBody`.

        Returns:
            A `Shaft` wrapper for each item in `MainBody.Shapes` whose
            wrapper type is `SHAFT_KIND`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._list(SHAFT_KIND, Shaft)

    def get_shaft(self, name: str) -> Shaft:
        """Looks up a shaft by name.

        Args:
            name: The shaft's name.

        Returns:
            The matching `Shaft`.

        Raises:
            FeatureNotFoundError: If no shaft named `name` exists.
            AmbiguousNameError: If two or more shafts named `name` exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._get(SHAFT_KIND, Shaft, "shaft", name)

    def create_shaft(self, name: str, sketch: Sketch) -> Shaft:
        """Creates a new shaft revolving `sketch`.

        `sketch` must already have `CenterLine` set (`Sketch.set_center_line`)
        with a profile drawn away from that axis (`docs/conventions.md`
        section 1.2.3); this library cannot verify that requirement ahead of
        time, so a missing or unusable axis surfaces as whatever error the
        failed `AddNewShaft` call produces. The new shaft is created with the
        verified defaults `FirstAngle.Value == FULL_REVOLUTION` (360.0) and
        `SecondAngle.Value == 0.0`; call `set_first_angle`/`set_second_angle`
        afterward to change them.

        A successful call here does not mean the feature is valid
        (`docs/conventions.md` section 1.2.2.1): this method never calls
        `Part.Update()`. The caller must call it and handle `PartUpdateError`;
        if the update fails, the shaft is left in the model and the caller
        must remove it (`remove_shaft`) rather than retrying blindly.

        Args:
            name: The new shaft's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            sketch: The `Sketch` to revolve. Must have `CenterLine` set.

        Returns:
            The newly created `Shaft`, already renamed to `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            FeatureConflictError: If a shaft named `name` already exists.
            AmbiguousNameError: If two or more shafts named `name` already
                exist.
            PartialCreationError: If the shaft was created but the follow-up
                rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly (for
                example, `sketch` has no `CenterLine`, or its profile is not
                clear of the axis).
        """
        validate_parameter_name(name)
        return self._create_feature(
            name, SHAFT_KIND, "AddNewShaft", (sketch.com_object,), Shaft, "shaft"
        )

    def ensure_shaft(self, name: str, sketch: Sketch) -> Shaft:
        """Creates a shaft, or reuses it if one with the same name and sketch exists.

        Unlike `ensure_pad`, this never touches the shaft's angles: a newly
        created shaft keeps the default 360.0/0.0, and a reused shaft keeps
        whatever `first_angle`/`second_angle` it already has. Change them
        explicitly with `set_first_angle`/`set_second_angle` if needed.

        Args:
            name: The shaft's name.
            sketch: The `Sketch` the shaft must revolve.

        Returns:
            The existing or newly created `Shaft`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            AmbiguousNameError: If two or more shafts named `name` already
                exist.
            FeatureConflictError: If a shaft named `name` already exists on a
                different sketch.
            PartialCreationError: If a new shaft had to be created and its
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        return self._ensure_by_sketch(
            name, sketch, self.get_shaft, lambda: self.create_shaft(name, sketch), "shaft"
        )

    def remove_shaft(self, name: str) -> None:
        """Removes a shaft from the model.

        Args:
            name: The shaft's name.

        Raises:
            FeatureNotFoundError: If no shaft named `name` exists.
            Auto3dxError: If no editor selection is available, or the deletion
                failed.
        """
        self._remove(name, self.get_shaft, "shaft")

    @property
    def grooves(self) -> "list[Groove]":
        """Lists every groove on the Part's `MainBody`.

        Returns:
            A `Groove` wrapper for each item in `MainBody.Shapes` whose
            wrapper type is `GROOVE_KIND`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._list(GROOVE_KIND, Groove)

    def get_groove(self, name: str) -> Groove:
        """Looks up a groove by name.

        Args:
            name: The groove's name.

        Returns:
            The matching `Groove`.

        Raises:
            FeatureNotFoundError: If no groove named `name` exists.
            AmbiguousNameError: If two or more grooves named `name` exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._get(GROOVE_KIND, Groove, "groove", name)

    def create_groove(self, name: str, sketch: Sketch) -> Groove:
        """Creates a new groove revolving `sketch`.

        Same requirements as `create_shaft`: `sketch` must already have
        `CenterLine` set, with a profile drawn away from that axis
        (`docs/conventions.md` section 1.2.3). The new groove is created with
        the verified defaults `FirstAngle.Value == FULL_REVOLUTION` (360.0)
        and `SecondAngle.Value == 0.0`.

        A successful call here does not mean the feature is valid
        (`docs/conventions.md` section 1.2.2.1): this method never calls
        `Part.Update()`. The caller must call it and handle `PartUpdateError`;
        if the update fails, the groove is left in the model and the caller
        must remove it (`remove_groove`) rather than retrying blindly.

        Args:
            name: The new groove's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            sketch: The `Sketch` to revolve. Must have `CenterLine` set.

        Returns:
            The newly created `Groove`, already renamed to `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            FeatureConflictError: If a groove named `name` already exists.
            AmbiguousNameError: If two or more grooves named `name` already
                exist.
            PartialCreationError: If the groove was created but the follow-up
                rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly (for
                example, `sketch` has no `CenterLine`, or its profile is not
                clear of the axis).
        """
        validate_parameter_name(name)
        return self._create_feature(
            name, GROOVE_KIND, "AddNewGroove", (sketch.com_object,), Groove, "groove"
        )

    def ensure_groove(self, name: str, sketch: Sketch) -> Groove:
        """Creates a groove, or reuses it if one with the same name and sketch exists.

        Policy identical to `ensure_shaft`: angles are never touched by this
        method, whether the groove is created (defaults 360.0/0.0) or reused
        (kept as-is).

        Args:
            name: The groove's name.
            sketch: The `Sketch` the groove must revolve.

        Returns:
            The existing or newly created `Groove`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            AmbiguousNameError: If two or more grooves named `name` already
                exist.
            FeatureConflictError: If a groove named `name` already exists on a
                different sketch.
            PartialCreationError: If a new groove had to be created and its
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        return self._ensure_by_sketch(
            name, sketch, self.get_groove, lambda: self.create_groove(name, sketch), "groove"
        )

    def remove_groove(self, name: str) -> None:
        """Removes a groove from the model.

        Args:
            name: The groove's name.

        Raises:
            FeatureNotFoundError: If no groove named `name` exists.
            Auto3dxError: If no editor selection is available, or the deletion
                failed.
        """
        self._remove(name, self.get_groove, "groove")

    def _resolve_plane(self, support: str) -> Any:
        """Resolves a support string to its raw `OriginElements` plane.

        Mirrors `SketchCollection._plane` exactly, reusing the same
        `SUPPORTED_SKETCH_SUPPORTS`/`_PLANE_ATTRIBUTE_BY_SUPPORT` mapping from
        `geometry.sketch` rather than redefining it, so a support string
        means the same thing whether it is used to place a sketch or a
        mirror.

        Args:
            support: One of `SUPPORTED_SKETCH_SUPPORTS`.

        Returns:
            The raw plane COM object (wrapper type `AnyObject`, not `Plane`).

        Raises:
            UnsupportedSupportError: If `support` is not a supported value.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        if support not in SUPPORTED_SKETCH_SUPPORTS:
            raise UnsupportedSupportError(
                f"Support {support!r} is not supported; supported supports are "
                f"{sorted(SUPPORTED_SKETCH_SUPPORTS)}."
            )
        attribute = _PLANE_ATTRIBUTE_BY_SUPPORT[support]
        try:
            return getattr(self._part_com_object.OriginElements, attribute)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def mirrors(self) -> "list[Mirror]":
        """Lists every mirror on the Part's `MainBody`.

        Returns:
            A `Mirror` wrapper for each item in `MainBody.Shapes` whose
            wrapper type is `MIRROR_KIND`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._list(MIRROR_KIND, Mirror)

    def get_mirror(self, name: str) -> Mirror:
        """Looks up a mirror by name.

        Args:
            name: The mirror's name.

        Returns:
            The matching `Mirror`.

        Raises:
            FeatureNotFoundError: If no mirror named `name` exists.
            AmbiguousNameError: If two or more mirrors named `name` exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._get(MIRROR_KIND, Mirror, "mirror", name)

    def create_mirror(self, name: str, support: str = SUPPORT_YZ) -> Mirror:
        """Creates a new mirror across the given support plane.

        Verified (`docs/conventions.md` section 1.2.3): `AddNewMirror` takes
        a plane directly -- `OriginElements.PlaneYZ` is confirmed to work --
        with no BRep name or other reference-layer lookup required, unlike
        every other unimplemented reference-based feature in this library.

        A successful call here does not mean the feature is valid
        (`docs/conventions.md` section 1.2.2.1): this method never calls
        `Part.Update()`. The caller must call it and handle `PartUpdateError`;
        if the update fails, the mirror is left in the model and the caller
        must remove it (`remove_mirror`) rather than retrying blindly.

        Args:
            name: The new mirror's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            support: One of `SUPPORTED_SKETCH_SUPPORTS`. Defaults to
                `SUPPORT_YZ`, the only support verified against a live
                session.

        Returns:
            The newly created `Mirror`, already renamed to `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            UnsupportedSupportError: If `support` is not a supported value.
            FeatureConflictError: If a mirror named `name` already exists.
            AmbiguousNameError: If two or more mirrors named `name` already
                exist.
            PartialCreationError: If the mirror was created but the follow-up
                rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        plane = self._resolve_plane(support)
        return self._create_feature(
            name, MIRROR_KIND, "AddNewMirror", (plane,), Mirror, "mirror"
        )

    def ensure_mirror(self, name: str, support: str = SUPPORT_YZ) -> Mirror:
        """Creates a mirror, or reuses one with the same name.

        There is no verified way to read a `Mirror`'s mirroring plane back
        from COM, so unlike `ensure_pad`/`ensure_shaft`, a name match here is
        reused unconditionally -- `support` is not compared against whatever
        plane the existing mirror actually uses. If a mirror named `name`
        already exists across a different plane than `support`, this method
        cannot detect that and will hand back the existing (wrong-plane)
        mirror. Callers that need that guarantee must track it themselves.

        Args:
            name: The mirror's name.
            support: One of `SUPPORTED_SKETCH_SUPPORTS`. Defaults to
                `SUPPORT_YZ`. Only used when a new mirror has to be created.

        Returns:
            The existing or newly created `Mirror`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            UnsupportedSupportError: If `support` is not a supported value.
            AmbiguousNameError: If two or more mirrors named `name` already
                exist.
            PartialCreationError: If a new mirror had to be created and its
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        if support not in SUPPORTED_SKETCH_SUPPORTS:
            raise UnsupportedSupportError(
                f"Support {support!r} is not supported; supported supports are "
                f"{sorted(SUPPORTED_SKETCH_SUPPORTS)}."
            )
        try:
            return self.get_mirror(name)
        except FeatureNotFoundError:
            return self.create_mirror(name, support)

    def remove_mirror(self, name: str) -> None:
        """Removes a mirror from the model.

        Args:
            name: The mirror's name.

        Raises:
            FeatureNotFoundError: If no mirror named `name` exists.
            Auto3dxError: If no editor selection is available, or the deletion
                failed.
        """
        self._remove(name, self.get_mirror, "mirror")
