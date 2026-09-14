"""The auto_3dx exception hierarchy.

Errors are grouped by what the caller can do about them (`docs/api-design.md`
section 8). Catch a category when the reaction is the same for every member, and a
concrete class when it is not:

    Auto3dxError
    |-- SessionError       could not reach or use a running session
    |-- ValidationError    rejected before any COM call; the model is untouched
    |-- NotFoundError      no object with that name exists
    |-- ConflictError      the model's naming or state forbids the request
    `-- AutomationError    CATIA rejected or failed a call

`ValidationError` carries a guarantee the other categories do not: nothing reached
CATIA, so there is nothing to clean up. Anything raised after a COM call was
attempted must not be a `ValidationError`.

This module is a leaf. Every other module may import it, and it imports nothing
from the SDK.
"""


class Auto3dxError(Exception):
    """Base class for all errors raised by auto_3dx."""


# --- Categories ------------------------------------------------------------------


class SessionError(Auto3dxError):
    """Could not reach or use a running 3DEXPERIENCE session.

    The model was never touched. The fix is on the caller's side of the session:
    start 3DEXPERIENCE, install the helper, or open the right editor.
    """


class ValidationError(Auto3dxError):
    """The request was rejected before any COM call was made.

    The model is untouched and the model generation has not advanced, so there is
    nothing to clean up. Correct the arguments and retry.
    """


class NotFoundError(Auto3dxError):
    """No object with the requested name exists.

    Raised only after enumerating the collection, never inferred from a failed
    name lookup, so it means the object is genuinely absent.
    """


class ConflictError(Auto3dxError):
    """The model's current naming or state forbids the request.

    Nothing was created. Typical causes are a name already in use, two objects
    sharing one name, or an existing object that differs from the one requested.
    """


class AutomationError(Auto3dxError):
    """CATIA rejected or failed a call.

    A COM call was attempted, so the model may have changed; the model generation
    has advanced. The original `pywintypes.com_error`, when there is one, is chained
    as `__cause__`.

    Attributes:
        hresult: The HRESULT CATIA reported, as a signed integer, or `None` when the
            failure did not come with one.
    """

    def __init__(self, message: str, hresult: int | None = None) -> None:
        """Initializes the error.

        Args:
            message: The human-readable description.
            hresult: The HRESULT CATIA reported, if any.
        """
        super().__init__(message)
        self.hresult = hresult


# --- Session -----------------------------------------------------------------------


class Com3dxNotFoundError(SessionError):
    """Raised when the installed com3dx.py helper module cannot be located."""


class CatiaConnectionError(SessionError):
    """Raised when attaching to a running 3DEXPERIENCE session fails."""


class NoActiveEditorError(SessionError):
    """Raised when the application has no ActiveEditor."""


class NoActivePartError(SessionError):
    """Raised when the ActiveEditor's ActiveObject is missing or not a Part."""


# --- Validation ------------------------------------------------------------------


class ParameterTypeError(ValidationError):
    """Raised when a parameter's kind or a supplied value's type is unsupported.

    Historically also raised for non-parameter arguments such as an edge, a
    radius or a pattern spacing. The name is narrower than its use; it remains a
    `ValidationError`, so catching the category covers every case.
    """


class ParameterNameError(ValidationError):
    """Raised when a requested parameter name is not usable.

    CATIA accepts an empty name (auto-naming the parameter ``Length.3``) and a
    name containing the ``\\`` container separator, both of which produce a
    parameter the caller cannot reliably address afterwards.
    """


class UnsupportedUnitError(ValidationError):
    """Raised when a unit other than a supported one is requested for a parameter."""


class UnsupportedMagnitudeError(ValidationError):
    """Raised when a `CreateDimension` magnitude is not in the unit catalogue."""


class UnsupportedSupportError(ValidationError):
    """Raised when a sketch support string is not one of the supported planes."""


class StaleSnapshotError(ValidationError):
    """Raised when an `Edge` or `Face` from a snapshot of an older model is used.

    Topology references are the one place in this API where reusing a handle
    after a model change is genuinely unpredictable. Measured with edges: on a
    plain cube with one fillet already applied, a second fillet from the same
    snapshot failed for the next edge, the middle edge and the last edge alike
    -- two of those failed at the creation call and one at `Part.Update()` --
    while a fresh snapshot's first edge succeeded. In another model two
    features from one snapshot both worked. Whether reuse succeeds depends on
    whether that particular edge survived the change untouched, which a caller
    cannot know.

    Faces were not put through the same experiment; each face feature was
    verified once, from its own fresh search. The same rule is applied to them
    because they come through the identical `Reference` mechanism, so this is a
    deliberate conservative default for faces rather than a measured fact.

    Rather than pass that coin flip on, the library refuses the stale handle
    before reaching COM. The fix is always the same: take a new snapshot.
    """


# --- Not found -------------------------------------------------------------------


class ParameterNotFoundError(NotFoundError):
    """Raised when a parameter cannot be found by name in a Parameters collection."""


class SketchNotFoundError(NotFoundError):
    """Raised when a sketch cannot be found by name in a Sketches collection."""


class FeatureNotFoundError(NotFoundError):
    """Raised when a Part Design feature (e.g. a Pad) cannot be found by name."""


class FormulaNotFoundError(NotFoundError):
    """Raised when a formula cannot be found by name in a Relations collection."""


class ConstraintNotFoundError(NotFoundError):
    """Raised when a constraint cannot be found by name in a Constraints collection."""


# --- Conflict --------------------------------------------------------------------


class ParameterAlreadyExistsError(ConflictError):
    """Raised when creating a parameter whose name is already taken.

    CATIA silently accepts a duplicate name and creates a second parameter
    reporting the identical name, which only one lookup can ever reach. The
    library refuses instead of corrupting the model that way.
    """


class SketchAlreadyExistsError(ConflictError):
    """Raised when creating a sketch whose name is already taken.

    CATIA does not guard against duplicate sketch names, so the library
    refuses instead of creating a second, indistinguishable sketch.
    """


class FormulaAlreadyExistsError(ConflictError):
    """Raised when creating a formula whose name is already taken."""


class SketchSupportMismatchError(ConflictError):
    """Raised when an existing sketch's plane does not match the requested support.

    A name match alone is not enough to reuse a sketch: its axis data (from
    `GetAbsoluteAxisData`) must also match the requested support, or the
    caller would silently draw on the wrong plane.
    """


class FeatureConflictError(ConflictError):
    """Raised when an existing feature conflicts with a requested operation.

    For example, a pad whose name matches but whose underlying sketch differs
    from the one requested.
    """


class AmbiguousNameError(ConflictError):
    """Raised when a name-based lookup matches two or more items.

    CATIA does not enforce unique names for sketches (`Sketch.Name` is
    writable and a duplicate is accepted silently), so `Sketches.Item(name)`
    can arbitrarily return one of several same-named objects. Any lookup that
    could reuse or mutate geometry must enumerate the collection and count
    matches first; two or more is refused rather than guessing which one the
    caller meant.
    """


# --- Automation --------------------------------------------------------------------


class PartUpdateError(AutomationError):
    """Raised when Part.Update() fails.

    The feature that caused the failure is still in the model, and every later
    update fails until it is removed. Remove it before doing anything else.
    """


class PartialCreationError(AutomationError):
    """Raised when a create operation leaves a partially-formed object behind.

    `Sketches.Add` / `AddNewPad` mutate the model before the follow-up `Name`
    write. If that write fails, a default-named sketch or pad is left in the
    model even though the caller sees an error. Retrying naively would then
    add more geometry on top of the leftover object instead of replacing it.
    """
