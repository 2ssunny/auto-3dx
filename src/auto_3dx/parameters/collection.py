"""Wrapper around the raw CATIA `Parameters` collection."""

from collections.abc import Callable, Iterator
from typing import Any

import pywintypes

from auto_3dx.errors import (
    AmbiguousNameError,
    Auto3dxError,
    ParameterAlreadyExistsError,
    ParameterNotFoundError,
    ParameterTypeError,
    UnsupportedMagnitudeError,
)
from auto_3dx.parameters.parameter import (
    ANGLE_KIND,
    ANGLE_MAGNITUDE,
    BOOLEAN_KIND,
    DIMENSION_KIND,
    INTEGER_KIND,
    LENGTH_KIND,
    LENGTH_MAGNITUDE,
    MILLIMETRE,
    REAL_KIND,
    STRING_KIND,
    Parameter,
    _coerce_boolean,
    _coerce_integer,
    _coerce_numeric,
    _coerce_string,
    _wrap_com_error,
    validate_length_unit,
    validate_length_value,
    validate_parameter_name,
)
from auto_3dx.parameters.units import UnitCatalogue


def _require_kind(parameter: Parameter, expected_kind: str) -> None:
    """Checks that an existing parameter has the kind an `ensure_*` call expects.

    Args:
        parameter: The existing parameter found by name.
        expected_kind: The kind the caller's `ensure_*` method requires.

    Raises:
        ParameterTypeError: If `parameter.kind != expected_kind`.
    """
    if parameter.kind != expected_kind:
        raise ParameterTypeError(
            f"Parameter {parameter.name!r} already exists with kind "
            f"{parameter.kind!r}, not {expected_kind!r}, so it will not be overwritten."
        )


def _dimension_kind_for_magnitude(magnitude: str) -> str:
    """Maps a `CreateDimension` magnitude to the COM wrapper kind it produces.

    Only `Length` and `Angle` get a derived wrapper type (verified,
    docs/conventions.md 1.1.2); every other magnitude comes back as a generic
    `Dimension`, so `ensure_dimension` needs this to know which kind an
    existing parameter must have.

    Args:
        magnitude: The magnitude passed to `CreateDimension`.

    Returns:
        `LENGTH_KIND` for `"Length"`, `ANGLE_KIND` for `"Angle"`, else
        `DIMENSION_KIND`.
    """
    if magnitude == LENGTH_MAGNITUDE:
        return LENGTH_KIND
    if magnitude == ANGLE_MAGNITUDE:
        return ANGLE_KIND
    return DIMENSION_KIND


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
        self._units: UnitCatalogue | None = None

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
    def units(self) -> UnitCatalogue:
        """Returns this collection's unit catalogue, built and cached on first access.

        Returns:
            A `UnitCatalogue` wrapping `Parameters.Units`.
        """
        if self._units is None:
            self._units = UnitCatalogue(self._com_object)
        return self._units

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

    def user_parameters(self) -> "list[Parameter]":
        """Lists only the parameters a person or script explicitly created.

        Creating geometry makes CATIA auto-expose that feature's own dimensions
        as parameters, so `list()` grows by roughly 15 entries per pad
        (`<Pad>\\FirstLimit\\Length`, `<Sketch>\\Coincidence.3\\Activity`, and
        so on). Those are real and useful -- a formula driving a pad's thickness
        targets `...\\FirstLimit\\Length` -- but they are named after the
        feature path, so they move when a feature is renamed and they are not
        what "which parameters does this Part have?" means.

        `RootParameterSet.DirectParameters` holds exactly the explicitly
        created ones (verified: 3 of 18 after one pad).

        Returns:
            A `Parameter` wrapper for each explicitly created parameter. An
            empty collection returns `[]`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            direct = self._com_object.RootParameterSet.DirectParameters
            count = direct.Count
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

        parameters: list[Parameter] = []
        for index in range(1, count + 1):
            try:
                com_object = direct.Item(index)
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error
            parameters.append(Parameter(com_object))
        return parameters

    def user_names(self) -> "list[str]":
        """Lists the short names of the explicitly created parameters.

        Returns:
            `Parameter.short_name` for each entry of `user_parameters()`, so
            the caller sees `"Span"` rather than `"3D Shape00422534\\Span"`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return [parameter.short_name for parameter in self.user_parameters()]

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
            raise ParameterNotFoundError(f"No parameter named {name!r} was found.") from error
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

    def _matching_parameters(self, name: str) -> "list[Parameter]":
        """Enumerates the user parameters and returns the ones named `name`.

        Existence must be judged by enumeration, not by catching a COM failure
        from a name-based lookup (docs/conventions.md 1.3): `Item(name)`
        failing does not distinguish "does not exist" from "some other
        transient COM failure," so treating a failure as "absent" would let a
        retried create() silently pile up duplicate parameters (fail-open).

        Two details decide what is compared, and both were learned the hard
        way against a live session:

        * `CreateDimension` stores a container-qualified name, so a parameter
          created as `"Span"` reports `"3D Shape1\\Span"`. Comparing `name`
          alone therefore never matches the string the caller passed, which
          made every duplicate check silently pass. `short_name` is compared
          as well, and a caller who passes the qualified form still matches.
        * Only `user_parameters()` is enumerated, not `list()`. A feature's
          own dimensions are exposed as parameters named after the feature
          path (`...\\FirstLimit\\Length`), whose short names collide with
          perfectly reasonable user names such as `"Length"`; matching those
          would refuse a legitimate creation.

        Args:
            name: The parameter name to match, qualified or short.

        Returns:
            Every `Parameter` from `user_parameters()` whose `name` or
            `short_name` equals `name`. Empty if none match.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return [
            parameter
            for parameter in self.user_parameters()
            if name in (parameter.name, parameter.short_name)
        ]

    def _create(self, name: str, factory: Callable[[], Any]) -> Parameter:
        """Shared create-parameter safety discipline.

        Args:
            name: The already name-validated candidate parameter name.
            factory: A zero-argument callable performing the actual
                `Parameters.CreateXxx` COM call and returning the raw created
                object.

        Returns:
            The newly created `Parameter`.

        Raises:
            ParameterAlreadyExistsError: If exactly one parameter is already
                named `name`.
            AmbiguousNameError: If two or more parameters are already named
                `name`.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        matches = self._matching_parameters(name)
        if len(matches) > 1:
            raise AmbiguousNameError(
                f"{len(matches)} parameters are already named {name!r}; refusing "
                "to create another one on top of an already-ambiguous name."
            )
        if matches:
            raise ParameterAlreadyExistsError(
                f"A parameter named {name!r} already exists. CATIA would accept "
                "a duplicate and create a second parameter with the same name, "
                "so creation is refused; use the matching ensure_*() method "
                "instead."
            )
        try:
            com_object = factory()
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        return Parameter(com_object)

    def _ensure(
        self,
        name: str,
        check_existing: Callable[[Parameter], None],
        create: Callable[[], Parameter],
        apply_existing: Callable[[Parameter], None],
    ) -> Parameter:
        """Shared ensure-parameter safety discipline.

        Args:
            name: The already name-validated candidate parameter name.
            check_existing: Raises `ParameterTypeError` if an existing match's
                kind (and, where relevant, magnitude) is wrong to overwrite.
            create: Creates the parameter if no match exists.
            apply_existing: Writes the new value onto an existing,
                kind-checked match.

        Returns:
            The created or updated `Parameter`.

        Raises:
            AmbiguousNameError: If two or more parameters are already named
                `name`.
            ParameterTypeError: If `check_existing` rejects the existing match.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        matches = self._matching_parameters(name)
        if len(matches) > 1:
            raise AmbiguousNameError(
                f"{len(matches)} parameters are already named {name!r}; refusing "
                "to guess which one to update."
            )
        if not matches:
            return create()
        existing = matches[0]
        check_existing(existing)
        apply_existing(existing)
        return existing

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
            AmbiguousNameError: If two or more parameters are already named `name`.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        validate_length_unit(unit)
        coerced = validate_length_value(value)
        return self._create(
            name, lambda: self._com_object.CreateDimension(name, LENGTH_MAGNITUDE, coerced)
        )

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
            AmbiguousNameError: If two or more parameters are already named `name`.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        validate_length_unit(unit)
        coerced = validate_length_value(value)
        return self._ensure(
            name,
            lambda existing: _require_kind(existing, LENGTH_KIND),
            lambda: self.create_length(name, coerced, unit),
            lambda existing: existing.set(coerced, unit),
        )

    def create_real(self, name: str, value: float) -> Parameter:
        """Creates a new unitless real-number (`RealParam`) parameter.

        This does not call `Part.Update()`.

        Args:
            name: The new parameter's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            value: The initial value.

        Returns:
            The `Parameter` wrapping the newly created COM object.

        Raises:
            ParameterNameError: If `name` is not usable as a parameter name.
            ParameterTypeError: If `value` is not an `int`/`float`, or is a `bool`.
            ParameterAlreadyExistsError: If a parameter named `name` already exists.
            AmbiguousNameError: If two or more parameters are already named `name`.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        coerced = _coerce_numeric(value)
        return self._create(name, lambda: self._com_object.CreateReal(name, coerced))

    def ensure_real(self, name: str, value: float) -> Parameter:
        """Creates a `RealParam`, or sets it if it already exists.

        This does not call `Part.Update()`.

        Args:
            name: The parameter's name, subject to the same rules as
                `create_real`.
            value: The value to create with or assign.

        Returns:
            The created or updated `Parameter`.

        Raises:
            ParameterNameError: If `name` is not usable as a parameter name.
            ParameterTypeError: If `value` is not an `int`/`float`, is a `bool`,
                or an existing parameter named `name` is not a `RealParam`.
            AmbiguousNameError: If two or more parameters are already named `name`.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        coerced = _coerce_numeric(value)
        return self._ensure(
            name,
            lambda existing: _require_kind(existing, REAL_KIND),
            lambda: self.create_real(name, coerced),
            lambda existing: existing.set(coerced),
        )

    def create_integer(self, name: str, value: int) -> Parameter:
        """Creates a new integer (`IntParam`) parameter.

        This does not call `Part.Update()`.

        Args:
            name: The new parameter's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            value: The initial value.

        Returns:
            The `Parameter` wrapping the newly created COM object.

        Raises:
            ParameterNameError: If `name` is not usable as a parameter name.
            ParameterTypeError: If `value` is not an `int`, or is a `bool`.
            ParameterAlreadyExistsError: If a parameter named `name` already exists.
            AmbiguousNameError: If two or more parameters are already named `name`.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        coerced = _coerce_integer(value)
        return self._create(name, lambda: self._com_object.CreateInteger(name, coerced))

    def ensure_integer(self, name: str, value: int) -> Parameter:
        """Creates an `IntParam`, or sets it if it already exists.

        This does not call `Part.Update()`.

        Args:
            name: The parameter's name, subject to the same rules as
                `create_integer`.
            value: The value to create with or assign.

        Returns:
            The created or updated `Parameter`.

        Raises:
            ParameterNameError: If `name` is not usable as a parameter name.
            ParameterTypeError: If `value` is not an `int`, is a `bool`, or an
                existing parameter named `name` is not an `IntParam`.
            AmbiguousNameError: If two or more parameters are already named `name`.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        coerced = _coerce_integer(value)
        return self._ensure(
            name,
            lambda existing: _require_kind(existing, INTEGER_KIND),
            lambda: self.create_integer(name, coerced),
            lambda existing: existing.set(coerced),
        )

    def create_string(self, name: str, value: str) -> Parameter:
        """Creates a new string (`StrParam`) parameter.

        This does not call `Part.Update()`.

        Args:
            name: The new parameter's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            value: The initial value.

        Returns:
            The `Parameter` wrapping the newly created COM object.

        Raises:
            ParameterNameError: If `name` is not usable as a parameter name.
            ParameterTypeError: If `value` is not a `str`.
            ParameterAlreadyExistsError: If a parameter named `name` already exists.
            AmbiguousNameError: If two or more parameters are already named `name`.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        coerced = _coerce_string(value)
        return self._create(name, lambda: self._com_object.CreateString(name, coerced))

    def ensure_string(self, name: str, value: str) -> Parameter:
        """Creates a `StrParam`, or sets it if it already exists.

        This does not call `Part.Update()`.

        Args:
            name: The parameter's name, subject to the same rules as
                `create_string`.
            value: The value to create with or assign.

        Returns:
            The created or updated `Parameter`.

        Raises:
            ParameterNameError: If `name` is not usable as a parameter name.
            ParameterTypeError: If `value` is not a `str`, or an existing
                parameter named `name` is not a `StrParam`.
            AmbiguousNameError: If two or more parameters are already named `name`.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        coerced = _coerce_string(value)
        return self._ensure(
            name,
            lambda existing: _require_kind(existing, STRING_KIND),
            lambda: self.create_string(name, coerced),
            lambda existing: existing.set(coerced),
        )

    def create_boolean(self, name: str, value: bool) -> Parameter:
        """Creates a new boolean (`BoolParam`) parameter.

        This does not call `Part.Update()`.

        Args:
            name: The new parameter's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            value: The initial value.

        Returns:
            The `Parameter` wrapping the newly created COM object.

        Raises:
            ParameterNameError: If `name` is not usable as a parameter name.
            ParameterTypeError: If `value` is not a `bool`.
            ParameterAlreadyExistsError: If a parameter named `name` already exists.
            AmbiguousNameError: If two or more parameters are already named `name`.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        coerced = _coerce_boolean(value)
        return self._create(name, lambda: self._com_object.CreateBoolean(name, coerced))

    def ensure_boolean(self, name: str, value: bool) -> Parameter:
        """Creates a `BoolParam`, or sets it if it already exists.

        This does not call `Part.Update()`.

        Args:
            name: The parameter's name, subject to the same rules as
                `create_boolean`.
            value: The value to create with or assign.

        Returns:
            The created or updated `Parameter`.

        Raises:
            ParameterNameError: If `name` is not usable as a parameter name.
            ParameterTypeError: If `value` is not a `bool`, or an existing
                parameter named `name` is not a `BoolParam`.
            AmbiguousNameError: If two or more parameters are already named `name`.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        coerced = _coerce_boolean(value)
        return self._ensure(
            name,
            lambda existing: _require_kind(existing, BOOLEAN_KIND),
            lambda: self.create_boolean(name, coerced),
            lambda existing: existing.set(coerced),
        )

    def create_dimension(self, name: str, magnitude: str, value: float) -> Parameter:
        """Creates a new Dimension-family parameter for an arbitrary magnitude.

        Only `"Length"` and `"Angle"` get a derived wrapper type (`Length`/
        `Angle`); every other magnitude comes back as a generic `Dimension`
        (verified, docs/conventions.md 1.1.2). `create_length` is the
        `"Length"`-specialised sibling of this method with an extra unit
        check; it does not call this method, so it keeps working against a
        `Parameters` fake that has no `Units` collection.

        Args:
            name: The new parameter's name, subject to the same rules as
                `create_real`.
            magnitude: The physical magnitude, as it appears in
                `UnitCatalogue.magnitudes()` (e.g. `"Length"`, `"Mass"`).
            value: The initial value, in that magnitude's internal unit.

        Returns:
            The `Parameter` wrapping the newly created COM object.

        Raises:
            ParameterNameError: If `name` is not usable as a parameter name.
            ParameterTypeError: If `value` is not an `int`/`float`, or is a `bool`.
            UnsupportedMagnitudeError: If `magnitude` is not one this
                installation's unit catalogue recognises.
            ParameterAlreadyExistsError: If a parameter named `name` already exists.
            AmbiguousNameError: If two or more parameters are already named `name`.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        coerced = _coerce_numeric(value)
        if magnitude not in self.units.magnitudes():
            raise UnsupportedMagnitudeError(
                f"Magnitude {magnitude!r} is not recognised by this installation's "
                "unit catalogue."
            )
        return self._create(
            name, lambda: self._com_object.CreateDimension(name, magnitude, coerced)
        )

    def ensure_dimension(self, name: str, magnitude: str, value: float) -> Parameter:
        """Creates a Dimension-family parameter, or sets it if it already exists.

        Args:
            name: The parameter's name, subject to the same rules as
                `create_dimension`.
            magnitude: The physical magnitude, as it appears in
                `UnitCatalogue.magnitudes()`.
            value: The value to create with or assign, in that magnitude's
                internal unit.

        Returns:
            The created or updated `Parameter`.

        Raises:
            ParameterNameError: If `name` is not usable as a parameter name.
            ParameterTypeError: If `value` is not an `int`/`float`, is a `bool`,
                or an existing parameter named `name` has the wrong kind (or,
                for a generic `Dimension`, a different magnitude).
            UnsupportedMagnitudeError: If `magnitude` is not one this
                installation's unit catalogue recognises.
            AmbiguousNameError: If two or more parameters are already named `name`.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        coerced = _coerce_numeric(value)
        if magnitude not in self.units.magnitudes():
            raise UnsupportedMagnitudeError(
                f"Magnitude {magnitude!r} is not recognised by this installation's "
                "unit catalogue."
            )
        expected_kind = _dimension_kind_for_magnitude(magnitude)

        def _check(existing: Parameter) -> None:
            _require_kind(existing, expected_kind)
            # A generic "Dimension" kind alone does not distinguish Mass from
            # Volume (docs/conventions.md 1.1.2), so it also needs its
            # magnitude checked before being silently repurposed.
            if expected_kind == DIMENSION_KIND and existing.magnitude != magnitude:
                raise ParameterTypeError(
                    f"Parameter {name!r} already exists with magnitude "
                    f"{existing.magnitude!r}, not {magnitude!r}, so it will not "
                    "be overwritten."
                )

        return self._ensure(
            name,
            _check,
            lambda: self.create_dimension(name, magnitude, coerced),
            lambda existing: existing.set(coerced),
        )

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
