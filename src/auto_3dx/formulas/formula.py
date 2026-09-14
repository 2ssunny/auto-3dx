"""Wrapper around a single CATIA `Formula` COM object.

A `Formula` is a named relation created by `Relations.CreateFormula` that
drives one target parameter from an expression referencing others.
`Formula.Value` is verified to hold the formula's body text (for example
`'AUTO3DX_THICKNESS * 2'`), not a computed number -- see
`docs/conventions.md` section 1.2.1.
"""

from typing import Any

import pywintypes

from auto_3dx._generation import ModelGeneration
from auto_3dx.errors import Auto3dxError, ParameterTypeError
from auto_3dx.parameters.parameter import validate_parameter_name


def _wrap_com_error(error: pywintypes.com_error) -> Auto3dxError:
    """Converts an unmapped `pywintypes.com_error` into an `Auto3dxError`.

    Args:
        error: The COM error to convert.

    Returns:
        An `Auto3dxError` whose message includes the failure's HRESULT in
        hexadecimal form.
    """
    hresult = error.args[0] if error.args else None
    hresult_hex = f"0x{hresult & 0xFFFFFFFF:08X}" if isinstance(hresult, int) else hresult
    return Auto3dxError(f"Unexpected COM failure (HRESULT={hresult_hex}).")


def _validate_formula_body(body: str) -> str:
    """Checks that a formula body is a usable, non-empty string.

    This does not check the expression is syntactically valid CATIA formula
    syntax -- only CATIA itself can judge that. It rejects the cases that
    would otherwise reach `CreateFormula`/`Modify` and fail there for a
    caller-visible reason (wrong type, empty text) with a clearer error.

    Args:
        body: The candidate formula body text.

    Returns:
        `body` unchanged.

    Raises:
        ParameterTypeError: If `body` is not a `str`, or is empty.
    """
    if not isinstance(body, str):
        raise ParameterTypeError(f"Formula body must be a str, got {type(body).__name__}.")
    if not body:
        raise ParameterTypeError("Formula body must not be empty.")
    return body


class Formula:
    """Wraps a raw CATIA `Formula` COM object.

    `Formula.Value` is the formula's body text, not a computed result --
    verified in `docs/conventions.md` section 1.2.1.
    """

    def __init__(self, com_object: Any, generation: ModelGeneration | None = None) -> None:
        """Initializes the wrapper.

        Args:
            com_object: The raw CATIA `Formula` COM object to wrap.
            generation: The owning Part's model generation, advanced by every
                write this wrapper makes. A wrapper built directly from a raw
                COM object gets its own, which nothing else shares.
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
        """Returns the formula's name.

        Returns:
            The formula's `Name`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Name
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def body(self) -> str:
        """Returns the formula's body text.

        Returns:
            `Formula.Value`, the formula's expression text (for example
            `'AUTO3DX_THICKNESS * 2'`), not a computed number.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Value
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def comment(self) -> str:
        """Returns the formula's comment.

        Returns:
            The formula's `Comment`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Comment
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def activated(self) -> bool:
        """Returns whether the formula is currently active.

        Returns:
            The formula's `Activated` state.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Activated
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def input_count(self) -> int:
        """Returns the number of input parameters the formula body references.

        Returns:
            `Formula.NbInParameters`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.NbInParameters
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def modify(self, body: str) -> None:
        """Replaces the formula's body text.

        Args:
            body: The new formula body. Must be a non-empty `str`.

        Raises:
            ParameterTypeError: If `body` is not a `str`, or is empty.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validated_body = _validate_formula_body(body)
        # The generation advances once this call is attempted, even if it raises
        # (`docs/api-design.md` section 5.3): a formula can drive a feature
        # dimension, so a body change may have rewritten the model's topology.
        with self._generation.mutation():
            try:
                self._com_object.Modify(validated_body)
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error

    def rename(self, name: str) -> None:
        """Renames the formula.

        Args:
            name: The new name. Must be non-empty, without surrounding
                whitespace, and must not contain `"\\"`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        # Advances the generation for the same reason `modify` does: renaming a
        # formula does not change what it drives, but a caller cannot verify
        # that from here, and the rule applies uniformly (section 5.2).
        with self._generation.mutation():
            try:
                self._com_object.Rename(name)
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error

    def activate(self) -> None:
        """Activates the formula.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        # Activating a formula can start it driving a feature dimension again,
        # so it advances the generation for the same reason `modify` does.
        with self._generation.mutation():
            try:
                self._com_object.Activate()
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error

    def deactivate(self) -> None:
        """Deactivates the formula.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        # Mirrors `activate`: deactivating can stop a formula driving a feature
        # dimension, so it changes the model the same way activating does.
        with self._generation.mutation():
            try:
                self._com_object.Deactivate()
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error

    def __repr__(self) -> str:
        """Returns a debugging representation.

        Returns:
            A string such as ``Formula(name='F', body='AUTO3DX_THICKNESS * 2')``.
        """
        try:
            name = self.name
            body = self.body
        except Auto3dxError:
            name = "<unavailable>"
            body = "<unavailable>"
        return f"Formula(name={name!r}, body={body!r})"
