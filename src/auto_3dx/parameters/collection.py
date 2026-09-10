"""Wrapper around the raw CATIA `Parameters` collection."""

from collections.abc import Iterator
from typing import Any

import pywintypes

from auto_3dx.errors import (
    Auto3dxError,
    ParameterAlreadyExistsError,
    ParameterNotFoundError,
    ParameterTypeError,
)
from auto_3dx.parameters.parameter import (
    LENGTH_KIND,
    LENGTH_MAGNITUDE,
    MILLIMETRE,
    Parameter,
    _wrap_com_error,
    validate_length_unit,
    validate_length_value,
    validate_parameter_name,
)


class ParameterCollection:
    """Wraps a raw CATIA `Parameters` collection.

    The underlying COM collection is 1-based: `Item(i)` is valid for `i` in
    `range(1, Count + 1)`. `Count == 0` is a normal, valid state (e.g. the
    currently open Part may legitimately have no parameters) and must not be
    treated as an error.
    """

    def __init__(self, com_object: Any) -> None:
        """Initializes the wrapper.

        Args:
            com_object: The raw CATIA `Parameters` collection to wrap.
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
    def count(self) -> int:
        """Returns the number of parameters in the collection.

        Returns:
            `self.com_object.Count`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Count
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def list(self) -> list[Parameter]:
        """Lists every parameter in the collection.

        Returns:
            A `Parameter` wrapper for each item, in the collection's
            1-based `Item(i)` order. An empty collection returns `[]`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly. A
                failure on a positional `Item(i)` is not a missing-name lookup,
                so it is reported as `Auto3dxError` rather than
                `ParameterNotFoundError`.
        """
        parameters: list[Parameter] = []
        for index in range(1, self.count + 1):
            try:
                com_object = self._com_object.Item(index)
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error
            parameters.append(Parameter(com_object))
        return parameters

    # Return annotation is quoted: by this point `list` is already shadowed
    # in the class namespace by the `list` method above, so the bare
    # subscript `list[str]` would resolve to that method, not the builtin.
    def names(self) -> "list[str]":
        """Lists the names of every parameter in the collection.

        Returns:
            The `name` of each parameter, in the same order as `list()`.
        """
        return [parameter.name for parameter in self.list()]

    def get(self, name: str) -> Parameter:
        """Looks up a parameter by name.

        Args:
            name: The parameter's name.

        Returns:
            The `Parameter` wrapping the matching COM object.

        Raises:
            ParameterNotFoundError: If no parameter named `name` exists.
        """
        try:
            com_object = self._com_object.Item(name)
        except pywintypes.com_error as error:
            raise ParameterNotFoundError(
                f"No parameter named {name!r} was found."
            ) from error
        return Parameter(com_object)

    def set(self, name: str, value: float, unit: str = MILLIMETRE) -> None:
        """Sets a parameter's value by name.

        This does not call `Part.Update()`.

        Args:
            name: The parameter's name.
            value: The new numeric value to assign.
            unit: The unit `value` is expressed in. Defaults to `MILLIMETRE`.

        Raises:
            ParameterNotFoundError: If no parameter named `name` exists.
            ParameterTypeError: If the parameter's kind is not `LENGTH_KIND`,
                or if `value` is not an `int`/`float` (or is a `bool`).
            UnsupportedUnitError: If `unit` is not a supported unit.
        """
        self.get(name).set(value, unit)

    def create_length(
        self,
        name: str,
        value: float,
        unit: str = MILLIMETRE,
    ) -> Parameter:
        """Creates a new Length parameter in this collection.

        The existence check is not a convenience: CATIA silently accepts a
        duplicate name and creates a second parameter reporting the identical
        name, which no lookup can then distinguish. A retried `create_length`
        would quietly litter the model, so an existing name is refused.

        The created parameter's `name` comes back container-qualified
        (``"<container>\\<name>"``), which is not the string that was passed in.
        Use `Parameter.short_name` to get the requested name back.

        This does not call `Part.Update()`.

        Args:
            name: The new parameter's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            value: The initial value.
            unit: The unit `value` is expressed in. Defaults to `MILLIMETRE`.

        Returns:
            The `Parameter` wrapping the newly created COM object.

        Raises:
            ParameterNameError: If `name` is not usable as a parameter name.
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `value` is not an `int`/`float`, or is a `bool`.
            ParameterAlreadyExistsError: If a parameter named `name` already exists.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        validate_length_unit(unit)
        coerced = validate_length_value(value)

        if name in self:
            raise ParameterAlreadyExistsError(
                f"A parameter named {name!r} already exists. CATIA would accept "
                "a duplicate and create a second parameter with the same name, "
                "so creation is refused; use ensure_length() to set the "
                "existing parameter instead."
            )

        try:
            com_object = self._com_object.CreateDimension(
                name, LENGTH_MAGNITUDE, coerced
            )
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        return Parameter(com_object)

    def ensure_length(
        self,
        name: str,
        value: float,
        unit: str = MILLIMETRE,
    ) -> Parameter:
        """Creates a Length parameter, or sets it if it already exists.

        A name that already belongs to a parameter of a different kind is an
        error rather than something to overwrite, so a model is never silently
        repurposed.

        This does not call `Part.Update()`.

        Args:
            name: The parameter's name, subject to the same rules as
                `create_length`.
            value: The value to create with or assign.
            unit: The unit `value` is expressed in. Defaults to `MILLIMETRE`.

        Returns:
            The created or updated `Parameter`.

        Raises:
            ParameterNameError: If `name` is not usable as a parameter name.
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `value` is not an `int`/`float`, is a `bool`,
                or an existing parameter named `name` is not a Length.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        validate_length_unit(unit)
        validate_length_value(value)

        try:
            existing = self.get(name)
        except ParameterNotFoundError:
            return self.create_length(name, value, unit)

        if existing.kind != LENGTH_KIND:
            raise ParameterTypeError(
                f"Parameter {name!r} already exists with kind "
                f"{existing.kind!r}, not {LENGTH_KIND!r}, so it will not be "
                "overwritten."
            )
        existing.set(value, unit)
        return existing

    def remove(self, name: str) -> None:
        """Removes a parameter from the model.

        The parameter is looked up first so a missing name is reported as
        `ParameterNotFoundError`, and so removal targets the authoritative
        qualified name rather than whatever the caller passed.

        This deletes model content. It does not call `Part.Update()`, and it
        never saves.

        Args:
            name: The parameter's name, qualified or short.

        Raises:
            ParameterNotFoundError: If no parameter named `name` exists.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        target = self.get(name)
        try:
            self._com_object.Remove(target.name)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def __len__(self) -> int:
        """Returns the number of parameters in the collection.

        Returns:
            Same as `count`.
        """
        return self.count

    def __iter__(self) -> Iterator[Parameter]:
        """Iterates over the parameters in the collection.

        Returns:
            An iterator over `Parameter` wrappers, in `list()` order.
        """
        return iter(self.list())

    def __contains__(self, name: object) -> bool:
        """Checks whether a parameter with the given name exists.

        A non-`str` argument is accepted and simply reported as absent,
        rather than raising.

        Args:
            name: The candidate parameter name.

        Returns:
            `True` if `get(name)` succeeds, `False` otherwise (including
            when `name` is not a `str`).
        """
        if not isinstance(name, str):
            return False
        try:
            self.get(name)
        except ParameterNotFoundError:
            return False
        return True

    def __repr__(self) -> str:
        """Returns a debugging representation.

        Returns:
            A string such as ``ParameterCollection(count=3)``.
        """
        try:
            count: object = self.count
        except Auto3dxError:
            count = "<unavailable>"
        return f"ParameterCollection(count={count})"
