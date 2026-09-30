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

Warnings are not errors and sit outside the hierarchy. They report a side effect the
SDK could not fully undo after an operation that otherwise succeeded, such as
`SelectionNotRestoredWarning`.

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


# --- Warnings ----------------------------------------------------------------------


class SelectionNotRestoredWarning(UserWarning):
    """A topology snapshot succeeded, but the user's CATIA selection did not fully return.

    The snapshot is valid and the model was not changed; only UI selection state was
    lost. CATIA can silently refuse to re-add an item: live, a feature was dropped when
    its own faces were already selected. Re-select in the CATIA UI if it matters.
    """


# --- Session -----------------------------------------------------------------------


class Com3dxNotFoundError(SessionError):
    """Raised when the installed com3dx.py helper module cannot be located."""


class CatiaConnectionError(SessionError):
    """Raised when attaching to a running 3DEXPERIENCE session fails."""


class NoActiveEditorError(SessionError):
    """Raised when the application has no ActiveEditor."""


class NoActivePartError(SessionError):
    """Raised when the ActiveEditor's ActiveObject is missing or not a Part."""


class InactivePartError(SessionError):
    """Raised when a Selection-based operation targets a Part that is not the active one.

    Deletion, topology search and visibility go through an editor's `Selection`, and
    `Selection.Search` was observed to act on the active editor even through another
    Part's selection (2026-09-17). Until a verified per-editor path exists, these
    operations refuse a Part unless `ActiveEditor.ActiveObject` is that Part. Nothing was
    changed; activate the Part in CATIA and retry.
    """


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


class CrossBodyReferenceError(ValidationError):
    """Raised when a topology reference from one body is used to build in another.

    `Selection.Search("Topology.Edge,all")` returns the edges of every body in the
    Part in one flat list (live, 2026-09-18: a two-body Part reported both bodies'
    edges together), so it is easy to take an edge that belongs to one body and hand
    it to a feature being built in another. CATIA accepts the creation call and fails
    the next `Part.Update()` instead, leaving a broken feature in the tree.

    Every edge and face therefore carries the body it was found in, read from the
    reference's owner chain in the model, and a feature refuses one that belongs to a
    different body before CATIA is called. Nothing was changed: take a snapshot of the
    body you are building in (`part.topology.edges(body=...)`) and use an edge from it.

    The same rule covers a feature used as a pattern seed: patterning a feature of one
    body into another body is refused here rather than left to fail at the next update.
    """


class SupportNotUpdatedError(ValidationError):
    """Raised when a sketch is created on a user plane that has not been rebuilt yet.

    A plane made by `part.planes.create_offset`/`create_angle` is not usable as a
    sketch support until the Part has been rebuilt: `Sketches.Add` fails with an opaque
    `E_FAIL` (live, verified repeatedly). CATIA reports the plane as not up to date
    until then, so the SDK checks that first and refuses with this error instead.
    Nothing was changed; call `part.update()` after creating the plane, then create the
    sketch.
    """


class UnsupportedOperationError(ValidationError):
    """Raised when a request is well formed but the SDK cannot carry it out safely.

    The request names something this release has no live evidence for: a geometry read on
    a sketch element kind whose reads were never verified, a direction that cannot be
    determined for this sketch (`"into_material"` on a sketch not created on a face), a
    fillet over several edges at once, or a circular-pattern axis kind that was never
    driven end to end. Nothing was changed. Use the Level 2 call the message names, or a
    request the evidence covers (`docs/phase5-api-design.md` section 3).
    """


class UnknownFactError(ValidationError):
    """Raised when `part.inspect.facts()` is asked for a fact it does not know.

    The message lists the supported fact names. Nothing was read.
    """


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


class TopologyQueryNoMatchError(NotFoundError):
    """Raised when a geometry query that must find something finds nothing.

    `one()` and `first()` on a face or edge query raise this rather than returning
    `None`, so an agent cannot carry on with a selection that never happened. The message
    lists the filters that were applied. Loosen a tolerance, check the body scope, or
    take a fresh snapshot after the model changed.
    """


class SketchElementNotFoundError(NotFoundError):
    """Raised when a sketch holds no geometric element with the requested name.

    Elements are found by the name CATIA gives them (`"Line.1"`, `"Circle.1"`), read from
    the sketch's `GeometricElements` collection, so an element drawn in an earlier
    session or by another process is found again by name. A missing name is reported
    here rather than as the bare COM failure `GeometricElements.Item` raises.
    """


class BodyNotFoundError(NotFoundError):
    """Raised when a body cannot be found by name in a Part's `Bodies`."""


class PlaneNotFoundError(NotFoundError):
    """Raised when a plane cannot be found by name in this SDK's geometrical set."""


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


class BodyAlreadyExistsError(ConflictError):
    """Raised when creating a body whose name is already taken."""


class BodyRemovalError(ConflictError):
    """Raised when removing a body is refused: the main body, or a non-empty body.

    Deleting a body deletes every feature and sketch in it, so a body that still holds
    content is removed only when the caller says so. Nothing was changed.
    """


class TopologyQueryAmbiguousError(ConflictError):
    """Raised when a geometry query meant to identify one element matches several.

    `one()` never picks among candidates: two faces of equal area, or two edges equally
    near a point, are reported with their measured values so the query can be narrowed.
    Rankings such as `largest()` keep every element tied within their tolerance, which is
    what lets this error see a tie instead of silently choosing whichever came first.
    """


class ReferenceInUseError(ConflictError):
    """Raised when deleting a reference plane that a sketch still sits on.

    CATIA deletes the plane without complaint, leaving the sketch -- and every feature
    built from it -- without a support: live, the next `Part.Update()` failed (probe 45).
    A sketch has no Automation member naming its support, so the dependency is found by
    the one verified signal: the sketch's absolute axis equals the plane's own frame
    exactly (`docs/conventions.md` 1.7). Nothing was changed. Remove or move the sketches
    first, or pass `force=True` to accept breaking them.
    """


class BooleanOperationError(ConflictError):
    """Raised when a multi-body boolean is refused, or removed without acknowledgement.

    A boolean consumes its tool body: after `AddNewRemove`/`AddNewAdd`/`AddNewIntersect`/
    `AddNewAssemble`, that body reports `InBooleanOperation` and is no longer listed in
    `part.bodies` (live, 2026-09-19). Building one is refused when the tool body is the
    target body itself, belongs to another Part, or has already been consumed by an
    earlier boolean.

    Removal is refused for a different reason. Deleting the boolean feature deletes the
    consumed tool body with it -- live, the tool body did not come back and its name
    could no longer be found -- so `remove_boolean` asks for that to be stated with
    `delete_consumed_body=True`. Nothing was changed when this is raised.
    """


class ParameterInUseError(ConflictError):
    """Raised when removing a parameter that a formula still reads.

    CATIA removes such a parameter without complaint and rewrites every formula that
    referenced it, leaving a body like `deleted_L_box * 2` and a Part that is no longer
    up to date (live, 2026-09-18). The relation survives as an orphan that no longer
    computes anything.

    Removal therefore checks `Relations` first: every formula's inputs are read through
    `Formula.GetInParameter`, so the answer comes from the model and is the same in any
    process. Nothing was changed. Remove or rewrite the formulas first --
    `part.parameters.dependents(name)` lists them -- or pass `force=True` to accept the
    orphaned relations deliberately.
    """


class TargetNotUpToDateError(ConflictError):
    """Raised when something is measured that CATIA has not rebuilt yet.

    A body whose features have not been rebuilt has no valid solid: the inertia
    service accepts it and then fails deep inside with `E_FAIL` (live, 2026-09-18,
    a pad created in a body that had not been updated). `Part.IsUpToDate(body)` reports
    that state reliably, so measurement checks it first and says what to do instead of
    surfacing a COM failure. Nothing was changed and nothing was rebuilt: measurement
    is read-only. Call `part.update()`, or `body.update()` for one body, and measure
    again.
    """


class FactUnavailableError(ConflictError):
    """Raised when a requested fact exists but cannot be read in the model's current state.

    `part.inspect.facts()` records such a fact in `PartFacts.unavailable` with the reason,
    for example a main body that has no solid yet or that has not been rebuilt; reading it
    through `facts[name]` raises this error with that reason. Nothing was changed.
    """


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
    """Raised when a rebuild fails.

    The model is left as CATIA left it -- nothing is rolled back and nothing is deleted
    -- and every later update fails while it stays invalid, so repair it before doing
    anything else.

    **Repair usually means undoing the change, not deleting the feature.** When the
    failure followed an edit to something that already worked, put the old value back and
    update again: live, a pad taken from 30 mm to 1 mm broke a fillet that depended on it,
    and restoring 30 mm rebuilt the Part with the fillet intact. Removing the feature is
    for the other case, where a newly created feature never built at all, or where there
    is no previous value to restore.

    Attributes:
        issues: What CATIA reported per feature right after the failure: a tuple of
            `auto_3dx.inspect.UpdateIssue`, each saying whether a feature is up to date and
            whether it is suppressed. Empty when nothing could be read. These are
            observations, not a root cause: the feature reported out of date is where the
            rebuild stopped, not necessarily what broke it (`part.inspect.update_issues()`).
    """

    issues: tuple = ()


class PartialCreationError(AutomationError):
    """Raised when a create operation leaves a partially-formed object behind.

    `Sketches.Add` / `AddNewPad` mutate the model before the follow-up `Name`
    write. If that write fails, a default-named sketch or pad is left in the
    model even though the caller sees an error. Retrying naively would then
    add more geometry on top of the leftover object instead of replacing it.
    """


class HolePlacementMismatchError(PartialCreationError):
    """Raised when CATIA put a positioned hole somewhere other than where it was asked.

    Live (probe 47d), a hole requested at (8, 0, 10) on a disc's top face -- a face bounded
    by one circle -- was created at the circle's centre, (0, 0, 10), with no error: CATIA
    snaps the hole's positioning point to the centre of a circular boundary. The SDK reads
    the origin back after every positioned hole, moves it with `SetOrigin` when it differs
    (probe 47m: that correction holds through the rebuild), and raises this only when the
    origin still differs afterwards. It is never raised silently late: the hole is checked
    before `create_hole` returns.

    The hole exists in the model under the requested name, in the wrong place. Remove it
    (`part.part_design.remove_hole(name)`) before doing anything else.

    Attributes:
        hole_name: The name the hole was created under.
        requested: The origin that was asked for, `(x, y, z)` in Part millimetres.
        actual: The origin CATIA reports, `(x, y, z)` in Part millimetres.
    """

    def __init__(
        self,
        message: str,
        hole_name: str = "",
        requested: "tuple[float, float, float] | None" = None,
        actual: "tuple[float, float, float] | None" = None,
    ) -> None:
        """Initializes the error.

        Args:
            message: The human-readable description.
            hole_name: The name the hole was created under.
            requested: The origin that was asked for.
            actual: The origin CATIA reports.
        """
        super().__init__(message)
        self.hole_name = hole_name
        self.requested = requested
        self.actual = actual
