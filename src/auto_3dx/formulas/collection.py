"""Wrapper around the raw CATIA `Relations` collection (a Part's formulas).

Building a formula body requires the name a parameter must be referenced by
inside an expression, which is not `Parameter.name` -- see
`docs/conventions.md` section 1.2.1. That name comes from
`Part.Parameters.GetNameToUseInRelation`, so this collection is constructed
from the raw `Part` COM object rather than from `Part.Relations` alone: it
needs both `Relations` (the formulas) and `Parameters` (to resolve names for
formula bodies).
"""

from collections.abc import Iterator
from typing import Any

import pywintypes

from auto_3dx.errors import (
    AmbiguousNameError,
    Auto3dxError,
    FormulaAlreadyExistsError,
    FormulaNotFoundError,
)
from auto_3dx.formulas.formula import Formula, _validate_formula_body, _wrap_com_error
from auto_3dx.parameters.parameter import Parameter, validate_parameter_name


class FormulaCollection:
    """Wraps a Part's `Relations` collection (its formulas).

    Existence is always decided by enumerating `Relations` (`Count` +
    `Item(i)`) and counting name matches, never by catching a `com_error` from
    a name-based lookup such as `Relations.GetItem`. A COM failure does not
    distinguish "missing" from "transient failure", and reading the latter as
    absence risks creating a duplicate formula.
    """

    def __init__(self, part_com_object: Any) -> None:
        """Initializes the wrapper.

        Args:
            part_com_object: The raw CATIA `Part` COM object. `Part.Relations`
                supplies the formulas themselves, and `Part.Parameters`
                supplies `GetNameToUseInRelation`, needed to build formula
                bodies that reference other parameters.
        """
        self._part_com_object = part_com_object

    def _relations(self) -> Any:
        """Returns the raw `Part.Relations` collection.

        Returns:
            The raw CATIA `Relations` collection.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._part_com_object.Relations
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def count(self) -> int:
        """Returns the number of formulas in the collection.

        Returns:
            `Relations.Count`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._relations().Count
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def list(self) -> list[Formula]:
        """Lists every formula in the collection.

        Returns:
            A `Formula` wrapper for each item, in `Relations`'s 1-based
            `Item(i)` order. An empty collection returns `[]`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        relations = self._relations()
        try:
            count = relations.Count
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

        formulas: list[Formula] = []
        for index in range(1, count + 1):
            try:
                com_object = relations.Item(index)
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error
            formulas.append(Formula(com_object))
        return formulas

    # Return annotation is quoted: by this point `list` is already shadowed
    # in the class namespace by the `list` method above, so the bare
    # subscript `list[str]` would resolve to that method, not the builtin.
    def names(self) -> "list[str]":
        """Lists the names of every formula in the collection.

        Returns:
            The `name` of each formula, in the same order as `list()`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return [formula.name for formula in self.list()]

    def get(self, name: str) -> Formula:
        """Looks up a formula by name.

        Names are not guaranteed unique, so every formula in `list()` is
        checked and the match count decides the outcome rather than returning
        on the first hit (see the class docstring).

        Args:
            name: The formula's name.

        Returns:
            The matching `Formula`.

        Raises:
            FormulaNotFoundError: If no formula named `name` exists.
            AmbiguousNameError: If two or more formulas named `name` exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        matches = [formula for formula in self.list() if formula.name == name]
        if not matches:
            raise FormulaNotFoundError(f"No formula named {name!r} was found.")
        if len(matches) > 1:
            raise AmbiguousNameError(
                f"{len(matches)} formulas named {name!r} exist; a name-based "
                "lookup cannot safely pick one."
            )
        return matches[0]

    def relation_name(self, parameter: Parameter) -> str:
        """Returns the name to reference `parameter` by inside a formula body.

        `Parameter.name` must not be used to build a formula body (verified in
        `docs/conventions.md` section 1.2.1): a user parameter's `name` is
        container-qualified (``'3D Shape00422534\\AUTO3DX_THICKNESS'``) while
        the name a formula body must use has no such prefix
        (``'AUTO3DX_THICKNESS'``), and a feature's internal parameter needs
        its full feature path
        (``'PartBody\\AUTO3DX_BASE_PAD\\FirstLimit\\Length'``). Both are only
        obtainable from `Parameters.GetNameToUseInRelation`.

        Args:
            parameter: The parameter that will appear in a formula body.

        Returns:
            The string to use for `parameter` inside a formula body.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._part_com_object.Parameters.GetNameToUseInRelation(
                parameter.com_object
            )
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def create(
        self,
        name: str,
        target: Parameter,
        body: str,
        comment: str = "",
    ) -> Formula:
        """Creates a new formula driving `target` from `body`.

        The existence check happens before any COM call, mirroring the
        duplicate-name guards used elsewhere in this library.

        Args:
            name: The new formula's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            target: The `Parameter` the formula drives (`iOutputParameter`).
            body: The formula's expression text. Must be a non-empty `str`.
                Build it with `relation_name()`, not `Parameter.name`.
            comment: An optional comment stored on the formula.

        Returns:
            The newly created `Formula`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            ParameterTypeError: If `body` is not a `str`, or is empty.
            FormulaAlreadyExistsError: If a formula named `name` already exists.
            AmbiguousNameError: If two or more formulas named `name` already exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        validated_body = _validate_formula_body(body)

        try:
            self.get(name)
        except FormulaNotFoundError:
            pass
        else:
            raise FormulaAlreadyExistsError(f"A formula named {name!r} already exists.")

        try:
            com_object = self._relations().CreateFormula(
                name, comment, target.com_object, validated_body
            )
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        return Formula(com_object)

    def ensure(
        self,
        name: str,
        target: Parameter,
        body: str,
        comment: str = "",
    ) -> Formula:
        """Creates a formula, or updates it in place if one already exists.

        Policy (see `docs/conventions.md` section 6.12):
            - No formula named `name` exists: create it.
            - A formula named `name` exists with the same body (compared as
              exact strings): reuse it unchanged.
            - A formula named `name` exists with a different body: update it
              with `Modify(body)`.

        Args:
            name: The formula's name.
            target: The `Parameter` the formula drives.
            body: The formula's expression text. Must be a non-empty `str`.
            comment: An optional comment used only if the formula is created.

        Returns:
            The existing (possibly updated) or newly created `Formula`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            ParameterTypeError: If `body` is not a `str`, or is empty.
            AmbiguousNameError: If two or more formulas named `name` already exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        validated_body = _validate_formula_body(body)

        try:
            existing = self.get(name)
        except FormulaNotFoundError:
            return self.create(name, target, validated_body, comment)

        if existing.body != validated_body:
            existing.modify(validated_body)
        return existing

    def remove(self, name: str) -> None:
        """Removes a formula from the model.

        The formula's 1-based index is found by enumeration and passed to
        `Relations.Remove(i)`; `Relations` has no name-based `Remove`.

        This deletes model content. It does not call `Part.Update()`, and it
        never saves.

        Args:
            name: The formula's name.

        Raises:
            FormulaNotFoundError: If no formula named `name` exists.
            AmbiguousNameError: If two or more formulas named `name` exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        relations = self._relations()
        try:
            count = relations.Count
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

        matching_indices: list[int] = []
        for index in range(1, count + 1):
            try:
                item = relations.Item(index)
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error
            if Formula(item).name == name:
                matching_indices.append(index)

        if not matching_indices:
            raise FormulaNotFoundError(f"No formula named {name!r} was found.")
        if len(matching_indices) > 1:
            raise AmbiguousNameError(
                f"{len(matching_indices)} formulas named {name!r} exist; a "
                "name-based lookup cannot safely pick one."
            )

        try:
            relations.Remove(matching_indices[0])
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def __len__(self) -> int:
        """Returns the number of formulas in the collection.

        Returns:
            Same as `count`.
        """
        return self.count

    def __iter__(self) -> Iterator[Formula]:
        """Iterates over the formulas in the collection.

        Returns:
            An iterator over `Formula` wrappers, in `list()` order.
        """
        return iter(self.list())

    def __contains__(self, name: object) -> bool:
        """Checks whether a formula with the given name exists.

        A non-`str` argument is accepted and simply reported as absent,
        rather than raising.

        Args:
            name: The candidate formula name.

        Returns:
            `True` if `get(name)` succeeds, `False` if it is not found.

        Raises:
            AmbiguousNameError: If two or more formulas named `name` exist.
        """
        if not isinstance(name, str):
            return False
        try:
            self.get(name)
        except FormulaNotFoundError:
            return False
        return True

    def __repr__(self) -> str:
        """Returns a debugging representation.

        Returns:
            A string such as ``FormulaCollection(count=2)``.
        """
        try:
            count: object = self.count
        except Auto3dxError:
            count = "<unavailable>"
        return f"FormulaCollection(count={count})"
