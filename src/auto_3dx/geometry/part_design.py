"""Wrappers around CATIA `Pad` Part Design features.

A `Pad` extrudes a `Sketch` profile along its normal by a fixed height.
Pads have no dedicated typed sub-collection in the verified API surface, so
`PartDesign` finds them by scanning `MainBody.Shapes` and keeping items whose
`type(item).__name__ == "Pad"`.
"""

import math
from typing import Any

import pywintypes

from auto_3dx.errors import Auto3dxError, FeatureConflictError, FeatureNotFoundError
from auto_3dx.geometry.deletion import delete_via_selection
from auto_3dx.geometry.sketch import Sketch, _wrap_com_error
from auto_3dx.parameters.parameter import (
    MILLIMETRE,
    validate_length_unit,
    validate_length_value,
    validate_parameter_name,
)

LENGTH_TOLERANCE: float = 1e-9
"""Absolute tolerance used to compare pad heights with `math.isclose`."""

PAD_KIND: str = "Pad"
"""The `type(com_object).__name__` value for a CATIA Pad feature."""


class Pad:
    """Wraps a raw CATIA `Pad` COM object.

    A pad's extrusion height is read from and written to
    `FirstLimit.Dimension.Value`, verified to equal the height passed to
    `ShapeFactory.AddNewPad` when the pad was created.
    """

    def __init__(self, com_object: Any) -> None:
        """Initializes the wrapper.

        Args:
            com_object: The raw CATIA `Pad` COM object to wrap.
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
        """Returns the pad's name.

        Returns:
            The pad's `Name`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Name
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def height(self) -> float:
        """Returns the pad's extrusion height.

        Returns:
            `FirstLimit.Dimension.Value`, verified to equal the height passed
            to `AddNewPad` when the pad was created.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.FirstLimit.Dimension.Value
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

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
        validate_length_unit(unit)
        coerced = validate_length_value(height)
        try:
            self._com_object.FirstLimit.Dimension.Value = coerced
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def sketch(self) -> Sketch:
        """Returns the sketch this pad was extruded from.

        Returns:
            A `Sketch` wrapping `Pad.Sketch`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return Sketch(self._com_object.Sketch)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def __repr__(self) -> str:
        """Returns a debugging representation.

        Returns:
            A string such as ``Pad(name='Pad.1', height=20.0)``.
        """
        try:
            name = self.name
            height: object = self.height
        except Auto3dxError:
            name = "<unavailable>"
            height = "<unavailable>"
        return f"Pad(name={name!r}, height={height!r})"


class PartDesign:
    """Wraps Part Design pad features on a Part's `MainBody`.

    Pads are read from `part_com_object.MainBody.Shapes`, filtered to items
    whose wrapper type is `"Pad"`, and created through
    `part_com_object.ShapeFactory.AddNewPad`.
    """

    def __init__(self, part_com_object: Any, selection: Any = None) -> None:
        """Initializes the wrapper.

        Args:
            part_com_object: The raw CATIA `Part` COM object. Both
                `MainBody.Shapes` (for existing pads) and `ShapeFactory` (for
                creating new pads) are read from it.
            selection: The raw CATIA `Selection` COM object from the editor.
                Required only by `remove_pad`, because `Shapes` has no `Remove`
                method and deletion has to go through the editor's selection.
                Reading and creating work without it.
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

    @property
    def pads(self) -> "list[Pad]":
        """Lists every pad on the Part's `MainBody`.

        Returns:
            A `Pad` wrapper for each item in `MainBody.Shapes` whose wrapper
            type is `PAD_KIND`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        shapes = self._shapes()
        try:
            count = shapes.Count
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        result: list[Pad] = []
        for index in range(1, count + 1):
            try:
                item = shapes.Item(index)
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error
            if type(item).__name__ == PAD_KIND:
                result.append(Pad(item))
        return result

    def get_pad(self, name: str) -> Pad:
        """Looks up a pad by name.

        Args:
            name: The pad's name.

        Returns:
            The matching `Pad`.

        Raises:
            FeatureNotFoundError: If no pad named `name` exists.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        for pad in self.pads:
            if pad.name == name:
                return pad
        raise FeatureNotFoundError(f"No pad named {name!r} was found.")

    def create_pad(
        self,
        name: str,
        sketch: Sketch,
        height: float,
        unit: str = MILLIMETRE,
    ) -> Pad:
        """Creates a new pad extruding `sketch` by `height`.

        The existence check happens before any COM call, mirroring the
        duplicate-name guards used elsewhere in this library.

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
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        validate_length_unit(unit)
        coerced = validate_length_value(height)

        try:
            self.get_pad(name)
        except FeatureNotFoundError:
            pass
        else:
            raise FeatureConflictError(f"A pad named {name!r} already exists.")

        try:
            com_object = self._part_com_object.ShapeFactory.AddNewPad(
                sketch.com_object, coerced
            )
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        pad = Pad(com_object)
        try:
            pad.com_object.Name = name
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        return pad

    def ensure_pad(
        self,
        name: str,
        sketch: Sketch,
        height: float,
        unit: str = MILLIMETRE,
    ) -> Pad:
        """Creates a pad, or reuses/updates it if one with the same name exists.

        Policy (see `docs/conventions.md` section 1.3):
            - No pad named `name` exists: create it.
            - A pad named `name` exists on the same sketch and the same
              height: reuse it unchanged.
            - A pad named `name` exists on the same sketch but a different
              height: update `FirstLimit.Dimension.Value` to `height`.
            - A pad named `name` exists on a different sketch: raise
              `FeatureConflictError`.

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
            FeatureConflictError: If a pad named `name` already exists on a
                different sketch.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        validate_length_unit(unit)
        coerced = validate_length_value(height)

        try:
            existing = self.get_pad(name)
        except FeatureNotFoundError:
            return self.create_pad(name, sketch, height, unit)

        if existing.sketch().name != sketch.name:
            raise FeatureConflictError(
                f"Pad {name!r} already exists on a different sketch "
                f"({existing.sketch().name!r} instead of {sketch.name!r})."
            )

        if not math.isclose(existing.height, coerced, abs_tol=LENGTH_TOLERANCE):
            existing.set_height(height, unit)
        return existing

    def remove_pad(self, name: str) -> None:
        """Removes a pad from the model.

        `Shapes` exposes no `Remove` method, so deletion goes through the
        editor's `Selection`. That means this method needs the `selection` the
        wrapper was constructed with; obtain the Part via `Catia.active_part()`
        to get one wired in.

        The pad is looked up first so a missing name is reported as
        `FeatureNotFoundError`. Removing a pad cascade-deletes its sketch
        (verified in `docs/conventions.md` section 1.2), so a following
        `SketchCollection.remove` for that sketch will legitimately fail.

        This deletes model content. It does not call `Part.Update()`, and it
        never saves.

        Args:
            name: The pad's name.

        Raises:
            FeatureNotFoundError: If no pad named `name` exists.
            Auto3dxError: If no editor selection is available, or the deletion
                failed.
        """
        target = self.get_pad(name)
        delete_via_selection(self._selection, target.com_object, f"pad {name!r}")
