"""Wrappers around CATIA sketch `Constraint`/`Constraints` COM objects.

Verified against a live session (`docs/conventions.md` sections 1.2.4 and
6.14): a sketch constraint is created through `Constraints.AddMonoEltCst`/
`AddBiEltCst`, which only succeed while the owning sketch is open for editing
(between `OpenEdition()` and `CloseEdition()`). That is why the *creation*
methods live on `SketchEditor` in `geometry.sketch`, not here -- this module
only wraps the resulting `Constraint` objects and provides a read-only view
over a sketch's existing `Constraints` collection, both of which stay valid
after the edition closes.

The requested constraint type code and the resulting `Constraint.Type` can
differ: `CONSTRAINT_HORIZONTAL`/`CONSTRAINT_VERTICAL` both normalise to a
Parallelism constraint (`CONSTRAINT_PARALLEL`). A created constraint must
never be looked back up by the code it was requested with.

`Constraints.Remove(i)` is unverified and deliberately not exposed here.

Concentricity (3) IS verified (`scripts/probes/27_sketch_geometry.py`,
created AND `Part.Update()` succeeded), using two DISTINCT circles as
`AddBiEltCst`'s two arguments -- an earlier probe (20/22) had passed the SAME
circle to both argument slots, which `docs/conventions.md` 1.2.4 records as a
probe input bug, not a COM limitation, so that earlier result never proved
anything about concentricity either way.

`CatConstraintType` has no `Diameter` member at all (the full 32-entry enum
was grepped, not sampled, by probe 27) -- only `Radius` (14) exists for
circle sizing. This module deliberately does not offer any diameter-flavoured
convenience; inventing one would mean guessing an undocumented code, which is
forbidden by this project's own rules.
"""

from collections.abc import Iterator
from typing import Any

import pywintypes

from auto_3dx._com import automation_error
from auto_3dx._generation import ModelGeneration
from auto_3dx.errors import (
    AmbiguousNameError,
    Auto3dxError,
    ConstraintNotFoundError,
    ParameterTypeError,
)
from auto_3dx.parameters.parameter import (
    MILLIMETRE,
    Parameter,
    validate_length_unit,
    validate_length_value,
)

CONSTRAINT_HORIZONTAL: int = 10
"""Requested type code for a horizontality constraint.

Verified to be normalised by CATIA into a Parallelism constraint
(`CONSTRAINT_PARALLEL`); the created `Constraint.type_code` will be `8`, not
`10`.
"""

CONSTRAINT_VERTICAL: int = 13
"""Requested type code for a verticality constraint.

Verified to be normalised by CATIA into a Parallelism constraint
(`CONSTRAINT_PARALLEL`); the created `Constraint.type_code` will be `8`, not
`13`.
"""

CONSTRAINT_LENGTH: int = 5
"""Type code for a length constraint on a line. Dimensional (has a `Dimension`)."""

CONSTRAINT_RADIUS: int = 14
"""Type code for a radius constraint on a circle. Dimensional (has a `Dimension`)."""

CONSTRAINT_PERPENDICULAR: int = 11
"""Type code for a perpendicularity constraint between two lines."""

CONSTRAINT_PARALLEL: int = 8
"""Type code for a parallelism constraint between two lines.

Also the normalised `Constraint.type_code` CATIA reports for
`CONSTRAINT_HORIZONTAL`/`CONSTRAINT_VERTICAL` requests.
"""

CONSTRAINT_DISTANCE: int = 1
"""Type code for a distance (offset) constraint between two elements.

Dimensional (has a `Dimension`).
"""

CONSTRAINT_COINCIDENT: int = 2
"""Type code for a coincidence constraint between two elements."""

CONSTRAINT_TANGENT: int = 4
"""Type code for a tangency constraint between two elements."""

CONSTRAINT_CONCENTRICITY: int = 3
"""Type code for a concentricity constraint between two DISTINCT circles.

Verified (`scripts/probes/27_sketch_geometry.py`) with two distinct closed
`Circle2D` objects as `AddBiEltCst`'s two arguments; created AND
`Part.Update()` succeeded. Not dimensional (no `Dimension`)."""


# COM failures translate in one place (`auto_3dx._com`, `docs/api-design.md`
# section 8). The private name stays because sibling modules import it from here.
_wrap_com_error = automation_error


class Constraint:
    """Wraps a raw CATIA sketch `Constraint` COM object.

    Only `CONSTRAINT_LENGTH`/`CONSTRAINT_RADIUS`/`CONSTRAINT_DISTANCE`
    constraints carry a `Dimension` (verified, `docs/conventions.md` 1.2.4);
    every other kind has none. Reading `.Dimension` on a non-dimensional
    constraint is verified to raise inside CATIA rather than return `None`,
    so `_dimension()` treats that failure as "no dimension", not as an error.
    """

    def __init__(self, com_object: Any, generation: ModelGeneration | None = None) -> None:
        """Initializes the wrapper.

        Args:
            com_object: The raw CATIA `Constraint` COM object to wrap.
            generation: The owning Part's model generation, advanced by
                `set_value`. A wrapper built directly from a raw COM object
                gets its own, which nothing else shares.
        """
        self._com_object = com_object
        self._generation = generation if generation is not None else ModelGeneration()

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
        """Returns the constraint's name.

        Returns:
            The constraint's `Name` (e.g. ``"Length.3"``).

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Name
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def type_code(self) -> int:
        """Returns the constraint's actual type code.

        This can differ from the code used to create the constraint: CATIA
        normalises `CONSTRAINT_HORIZONTAL`/`CONSTRAINT_VERTICAL` requests into
        `CONSTRAINT_PARALLEL` (verified, `docs/conventions.md` 1.2.4). Never
        use the originally requested code to look a constraint back up by
        type.

        Returns:
            The constraint's `Type`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Type
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def status(self) -> int:
        """Returns the constraint's health status.

        Returns:
            The constraint's `Status`. `0` means healthy.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Status
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def _dimension(self) -> Any:
        """Returns the constraint's raw `Dimension` COM object, or `None`.

        Verified (`docs/conventions.md` 1.2.4/6.14): reading `.Dimension` on a
        non-dimensional constraint raises inside CATIA. That failure is the
        signal used here to mean "this constraint has no dimension", not a
        transient COM problem to propagate.

        Returns:
            The raw `Dimension` COM object, or `None` if this constraint is
            not dimensional.
        """
        try:
            return self._com_object.Dimension
        except pywintypes.com_error:
            return None

    @property
    def value(self) -> float | None:
        """Returns the constraint's dimension value.

        Returns:
            `Dimension.Value` for a dimensional constraint (length, radius,
            distance), or `None` if this constraint has no dimension.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly while
                reading a `Dimension` known to exist.
        """
        dimension = self._dimension()
        if dimension is None:
            return None
        try:
            return dimension.Value
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def set_value(self, value: float, unit: str = MILLIMETRE) -> None:
        """Sets the constraint's dimension value.

        Verified (`docs/conventions.md` 1.2.4): a dimensional constraint's
        `Dimension.Value` is writable, and `Part.Update()` succeeds afterward
        with `BrokenConstraintsCount` staying `0`. This method does not call
        `Part.Update()`.

        Args:
            value: The new numeric value to assign.
            unit: The unit `value` is expressed in. Defaults to `MILLIMETRE`.

        Raises:
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `value` is not an `int`/`float` (or is a
                `bool`), or if this constraint has no `Dimension`.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_length_unit(unit)
        coerced = validate_length_value(value)
        dimension = self._dimension()
        if dimension is None:
            raise ParameterTypeError(
                "This constraint has no Dimension; set_value() only works on "
                "dimensional constraints (length, radius, distance)."
            )
        # The generation advances once this block is attempted, even if the
        # write raises (`docs/api-design.md` section 5.3): a dimension change
        # rebuilds the solid's topology (probe 31).
        with self._generation.mutation():
            try:
                dimension.Value = coerced
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error

    def dimension_parameter(self) -> Parameter:
        """Returns the `Dimension` parameter backing this constraint's value.

        This is the object a `Formula` targets to drive the constraint, the
        same idea as `SketchFeature.depth_parameter()` in `geometry.part_design`.

        Returns:
            A `Parameter` wrapping this constraint's `Dimension`.

        Raises:
            ParameterTypeError: If this constraint has no `Dimension` (i.e. it
                is not a dimensional constraint).
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        dimension = self._dimension()
        if dimension is None:
            raise ParameterTypeError(
                "This constraint has no Dimension; dimension_parameter() only "
                "works on dimensional constraints (length, radius, distance)."
            )
        return Parameter(dimension)

    def __repr__(self) -> str:
        """Returns a debugging representation.

        Returns:
            A string such as ``Constraint(name='Length.3', type_code=5,
            status=0)``.
        """
        try:
            name = self.name
            type_code: object = self.type_code
            status: object = self.status
        except Auto3dxError:
            name = "<unavailable>"
            type_code = "<unavailable>"
            status = "<unavailable>"
        return f"Constraint(name={name!r}, type_code={type_code!r}, status={status!r})"


class ConstraintCollection:
    """Read-only view over a sketch's `Constraints` collection.

    Constraint *creation* is not exposed here: it only works while the
    sketch is open for editing (`docs/conventions.md` 1.2.4), so those
    methods live on `geometry.sketch.SketchEditor` instead. This collection
    only lists and looks up constraints that already exist, and is safe to
    use outside `Sketch.edit()`.

    `Constraints.Remove(i)` is unverified and deliberately not exposed here
    (`docs/conventions.md` 1.2.4).

    Shares one model generation with every `Constraint` it returns
    (`docs/api-design.md` section 5): `Constraint.set_value` advances it.
    """

    def __init__(
        self, sketch_com_object: Any, generation: ModelGeneration | None = None
    ) -> None:
        """Initializes the wrapper.

        Args:
            sketch_com_object: The raw CATIA `Sketch` COM object.
                `Constraints` is read from it.
            generation: The owning Part's model generation. A standalone
                instance gets its own, which no other wrapper shares; obtain
                this collection through `Sketch.constraints` instead. Shared
                with every `Constraint` this collection returns.
        """
        self._sketch_com_object = sketch_com_object
        self._generation = generation if generation is not None else ModelGeneration()

    def _constraints(self) -> Any:
        """Returns the raw `Sketch.Constraints` collection.

        Returns:
            The raw CATIA `Constraints` collection.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._sketch_com_object.Constraints
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def count(self) -> int:
        """Returns the number of constraints in the collection.

        Returns:
            `Constraints.Count`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._constraints().Count
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def broken_count(self) -> int:
        """Returns the number of broken constraints in the sketch.

        Returns:
            `Constraints.BrokenConstraintsCount`. `0` means every constraint
            is healthy.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._constraints().BrokenConstraintsCount
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def unupdated_count(self) -> int:
        """Returns the number of un-updated constraints in the sketch.

        Returns:
            `Constraints.UnUpdatedConstraintsCount`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._constraints().UnUpdatedConstraintsCount
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def list(self) -> "list[Constraint]":
        """Lists every constraint in the collection.

        Returns:
            A `Constraint` wrapper for each item, in the collection's
            1-based `Item(i)` order. An empty collection returns `[]`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        constraints = self._constraints()
        try:
            count = constraints.Count
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        result: list[Constraint] = []
        for index in range(1, count + 1):
            try:
                com_object = constraints.Item(index)
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error
            result.append(Constraint(com_object, self._generation))
        return result

    # Return annotation is quoted: by this point `list` is already shadowed
    # in the class namespace by the `list` method above (see
    # geometry/sketch.py and parameters/collection.py for the same note).
    def names(self) -> "list[str]":
        """Lists the names of every constraint in the collection.

        Returns:
            The `name` of each constraint, in the same order as `list()`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return [constraint.name for constraint in self.list()]

    def _matching(self, name: str) -> "list[Constraint]":
        """Enumerates the collection and returns every constraint named `name`.

        Existence must be positive evidence, not a caught exception, matching
        the discipline used throughout this library (`docs/conventions.md`
        1.3): enumerating with `Count`/`Item(i)` and comparing `Name` avoids
        misreading a transient COM failure as absence.

        Args:
            name: The constraint name to match against.

        Returns:
            Every `Constraint` in the collection whose `name` equals `name`,
            in `list()` order. Empty if none match.

        Raises:
            Auto3dxError: If the underlying enumeration fails unexpectedly.
        """
        return [constraint for constraint in self.list() if constraint.name == name]

    def get(self, name: str) -> Constraint:
        """Looks up a constraint by name.

        Args:
            name: The constraint's name.

        Returns:
            The `Constraint` wrapping the matching COM object.

        Raises:
            ConstraintNotFoundError: If no constraint named `name` exists.
            AmbiguousNameError: If two or more constraints named `name` exist.
            Auto3dxError: If the underlying enumeration fails unexpectedly.
        """
        matches = self._matching(name)
        if not matches:
            raise ConstraintNotFoundError(f"No constraint named {name!r} was found.")
        if len(matches) > 1:
            raise AmbiguousNameError(
                f"{len(matches)} constraints named {name!r} exist; a "
                "name-based lookup cannot safely pick one."
            )
        return matches[0]

    def __len__(self) -> int:
        """Returns the number of constraints in the collection.

        Returns:
            Same as `count`.
        """
        return self.count

    def __iter__(self) -> Iterator[Constraint]:
        """Iterates over the constraints in the collection.

        Returns:
            An iterator over `Constraint` wrappers, in `list()` order.
        """
        return iter(self.list())

    def __contains__(self, name: object) -> bool:
        """Checks whether a constraint with the given name exists.

        A non-`str` argument is accepted and simply reported as absent,
        rather than raising.

        Args:
            name: The candidate constraint name.

        Returns:
            `True` if `get(name)` succeeds, `False` otherwise (including
            when `name` is not a `str`).
        """
        if not isinstance(name, str):
            return False
        try:
            self.get(name)
        except ConstraintNotFoundError:
            return False
        return True

    def __repr__(self) -> str:
        """Returns a debugging representation.

        Returns:
            A string such as ``ConstraintCollection(count=3)``.
        """
        try:
            count: object = self.count
        except Auto3dxError:
            count = "<unavailable>"
        return f"ConstraintCollection(count={count!r})"
