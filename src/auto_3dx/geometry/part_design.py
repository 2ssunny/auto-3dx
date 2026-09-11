"""Wrappers around CATIA `Pad`/`Pocket` Part Design features.

A `Pad` extrudes a `Sketch` profile along its normal by a fixed height. A
`Pocket` removes material along the same profile by a fixed depth. Verified
against a live session (`docs/conventions.md` section 1.2.1), `Pocket`'s
readable properties are identical to `Pad`'s, and `FirstLimit.Dimension.Value`
holds the magnitude passed to `AddNewPad`/`AddNewPocket` at creation for both.
That structural symmetry is factored into a shared `SketchFeature` base;
`Pad` and `Pocket` differ only in their `type(com_object).__name__` and, for
`Pad`, the pre-existing `height`/`set_height` public API kept for backward
compatibility.

Neither feature has a dedicated typed sub-collection in the verified API
surface, so `PartDesign` finds them by scanning `MainBody.Shapes` and keeping
items whose `type(item).__name__` is `PAD_KIND` or `POCKET_KIND`.
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
)
from auto_3dx.geometry.deletion import delete_via_selection
from auto_3dx.geometry.sketch import Sketch, _wrap_com_error
from auto_3dx.parameters.parameter import (
    MILLIMETRE,
    Parameter,
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


class PartDesign:
    """Wraps Part Design pad and pocket features on a Part's `MainBody`.

    Pads and pockets are both read from `part_com_object.MainBody.Shapes`,
    filtered by `type(item).__name__` (`PAD_KIND`/`POCKET_KIND`), and created
    through `part_com_object.ShapeFactory.AddNewPad`/`AddNewPocket`. The two
    families share identical policy (existence/ambiguity checks, sketch-identity
    comparison, partial-creation reporting, deletion via selection); that
    shared behaviour is factored into the private `_list`/`_get`/`_create`/
    `_ensure`/`_remove` helpers below, parameterised by kind.
    """

    def __init__(self, part_com_object: Any, selection: Any = None) -> None:
        """Initializes the wrapper.

        Args:
            part_com_object: The raw CATIA `Part` COM object. Both
                `MainBody.Shapes` (for existing pads/pockets) and
                `ShapeFactory` (for creating new ones) are read from it.
            selection: The raw CATIA `Selection` COM object from the editor.
                Required only by `remove_pad`/`remove_pocket`, because
                `Shapes` has no `Remove` method and deletion has to go
                through the editor's selection. Reading and creating work
                without it.
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
            kind: `PAD_KIND` or `POCKET_KIND`.
            wrapper_cls: `Pad` or `Pocket`.

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
            kind: `PAD_KIND` or `POCKET_KIND`.
            wrapper_cls: `Pad` or `Pocket`.
            noun: `"pad"` or `"pocket"`, used only in error messages.
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
        """Creates a new sketch-based feature.

        The existence check happens before any COM call, mirroring the
        duplicate-name guards used elsewhere in this library.

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

        try:
            self._get(kind, wrapper_cls, noun, name)
        except FeatureNotFoundError:
            pass
        else:
            raise FeatureConflictError(f"A {noun} named {name!r} already exists.")

        try:
            factory = getattr(self._part_com_object.ShapeFactory, factory_method)
            com_object = factory(sketch.com_object, coerced)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        feature = wrapper_cls(com_object)
        # AddNewPad/AddNewPocket already mutated the model; if the rename below
        # fails, a default-named feature is left behind rather than rolled back
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

        "Same sketch" is judged by COM identity (`==` on the raw `Sketch`
        objects), not by name: names are writable and CATIA does not reject a
        duplicate, so a name match alone would be forgeable.

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

        try:
            existing = get_method(name)
        except FeatureNotFoundError:
            return create_method(name, sketch, depth, unit)

        try:
            same_sketch = existing.sketch().com_object == sketch.com_object
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        if not same_sketch:
            raise FeatureConflictError(
                f"{noun.capitalize()} {name!r} already exists on a different "
                f"sketch ({existing.sketch().name!r} instead of {sketch.name!r})."
            )

        if not math.isclose(existing.depth, coerced, rel_tol=0.0, abs_tol=LENGTH_TOLERANCE):
            existing.set_depth(depth, unit)
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
            get_method: `self.get_pad` or `self.get_pocket`.
            noun: `"pad"` or `"pocket"`, used only in the deletion's error
                message.

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
