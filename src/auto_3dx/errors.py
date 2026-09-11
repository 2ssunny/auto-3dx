class Auto3dxError(Exception):
    """Base class for all errors raised by auto_3dx."""


class Com3dxNotFoundError(Auto3dxError):
    """Raised when the installed com3dx.py helper module cannot be located."""


class CatiaConnectionError(Auto3dxError):
    """Raised when attaching to a running 3DEXPERIENCE session fails."""


class NoActiveEditorError(Auto3dxError):
    """Raised when the application has no ActiveEditor."""


class NoActivePartError(Auto3dxError):
    """Raised when the ActiveEditor's ActiveObject is missing or not a Part."""


class ParameterNotFoundError(Auto3dxError):
    """Raised when a parameter cannot be found by name in a Parameters collection."""


class ParameterTypeError(Auto3dxError):
    """Raised when a parameter's kind or a supplied value's type is unsupported."""


class ParameterNameError(Auto3dxError):
    """Raised when a requested parameter name is not usable.

    CATIA accepts an empty name (auto-naming the parameter ``Length.3``) and a
    name containing the ``\\`` container separator, both of which produce a
    parameter the caller cannot reliably address afterwards.
    """


class ParameterAlreadyExistsError(Auto3dxError):
    """Raised when creating a parameter whose name is already taken.

    CATIA silently accepts a duplicate name and creates a second parameter
    reporting the identical name, which only one lookup can ever reach. The
    library refuses instead of corrupting the model that way.
    """


class UnsupportedUnitError(Auto3dxError):
    """Raised when a unit other than a supported one is requested for a parameter."""


class PartUpdateError(Auto3dxError):
    """Raised when Part.Update() fails."""


class SketchNotFoundError(Auto3dxError):
    """Raised when a sketch cannot be found by name in a Sketches collection."""


class SketchAlreadyExistsError(Auto3dxError):
    """Raised when creating a sketch whose name is already taken.

    CATIA does not guard against duplicate sketch names, so the library
    refuses instead of creating a second, indistinguishable sketch.
    """


class SketchSupportMismatchError(Auto3dxError):
    """Raised when an existing sketch's plane does not match the requested support.

    A name match alone is not enough to reuse a sketch: its axis data (from
    `GetAbsoluteAxisData`) must also match the requested support, or the
    caller would silently draw on the wrong plane.
    """


class FeatureNotFoundError(Auto3dxError):
    """Raised when a Part Design feature (e.g. a Pad) cannot be found by name."""


class FeatureConflictError(Auto3dxError):
    """Raised when an existing feature conflicts with a requested operation.

    For example, a pad whose name matches but whose underlying sketch differs
    from the one requested.
    """


class UnsupportedSupportError(Auto3dxError):
    """Raised when a sketch support string is not one of the supported planes."""


class AmbiguousNameError(Auto3dxError):
    """Raised when a name-based lookup matches two or more items.

    CATIA does not enforce unique names for sketches (`Sketch.Name` is
    writable and a duplicate is accepted silently), so `Sketches.Item(name)`
    can arbitrarily return one of several same-named objects. Any lookup that
    could reuse or mutate geometry must enumerate the collection and count
    matches first; two or more is refused rather than guessing which one the
    caller meant.
    """


class PartialCreationError(Auto3dxError):
    """Raised when a create operation leaves a partially-formed object behind.

    `Sketches.Add` / `AddNewPad` mutate the model before the follow-up `Name`
    write. If that write fails, a default-named sketch or pad is left in the
    model even though the caller sees an error. Retrying naively would then
    add more geometry on top of the leftover object instead of replacing it.
    """


class FormulaNotFoundError(Auto3dxError):
    """Raised when a formula cannot be found by name in a Relations collection."""


class FormulaAlreadyExistsError(Auto3dxError):
    """Raised when creating a formula whose name is already taken."""


class ConstraintNotFoundError(Auto3dxError):
    """Raised when a constraint cannot be found by name in a Constraints collection."""


class UnsupportedMagnitudeError(Auto3dxError):
    """Raised when a `CreateDimension` magnitude is not in the unit catalogue."""
