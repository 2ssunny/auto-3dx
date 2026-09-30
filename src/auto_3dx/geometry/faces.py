"""Face references for reference-based Part Design features (shell, thickness, hole).

`geometry.edges` solved the general problem of naming one piece of solid
topology and used it for two edge-hungry features (fillet, chamfer). This
module is that layer's sibling for FACES: about eighty `ShapeFactory.AddNew*`
methods take a face or an edge instead of a sketch (`docs/conventions.md`
section 1.2.2), and three of the face-hungry ones are verified here (probe
37, `scripts/probes/37_face_features.py`):

    AddNewShell(iFaceToRemove, iInternalThickness, iExternalThickness) -> Shell
    AddNewThickness(iFaceToThicken, iOffset) -> Thickness
    AddNewHole(iSupport, iDepth) -> Hole

The route to a feature-usable face reference is identical to the edge route
except for the query string (`docs/conventions.md` section 1.2.2.2):

    selection.Clear()
    selection.Search("Topology.Face,all")    # returns void, mutates Selection
    for i in 1..selection.Count:
        reference = selection.Item(i).Reference  # a real, feature-usable Reference
    selection.Clear()

`Search("Face,all")` (no `Topology.` prefix) fails; the prefix is required,
exactly as for edges. `Part.CreateReferenceFromObject` fails on a search hit
for faces just as it does for edges, so `SelectedElement.Reference` is again
the only route in. A 40x40x20 mm pad reported 8 faces (probe 37); a face
reference is rejected by `AddNewEdgeFilletWithConstantRadius`/`AddNewChamfer`
for every propagation mode tried (`geometry.edges`), which is why those two
features only ever take an edge and these three only ever take a face.

WHAT IS ACTUALLY MEASURED VERSUS CARRIED OVER AS POLICY. `geometry.edges`
documents four facts it measured directly for edges, including an extensive
before/after comparison of edge count and fillet-reuse behaviour across
several model changes. Nothing that thorough has been repeated for faces
specifically -- probe 37 tried each of the three features once, on a fresh
search, and moved on. Two things follow from that:

1. This module still enforces "a snapshot is single-generation" exactly as
   `geometry.edges` does: `Face`/`FaceSnapshot` carry a `generation`, and
   `PartDesign` refuses a stale one before it reaches COM. That is project
   law (not optional -- a failed update leaves a broken feature in the tree,
   docs/conventions.md 1.2.2.1), applied here as a conservative default
   because a face `Reference` is read from the exact same kind of COM object
   as an edge `Reference`, obtained the exact same way. It is not, itself, a
   claim that face-reference reuse was reproduced to fail the way edge reuse
   was -- that specific experiment has not been run on faces.
2. `Face.descriptor` (the reference's `Name`/`DisplayName`) is documented as
   non-durable by the same reasoning, not by a separate measurement:
   `geometry.edges` fact 3 showed `Part.CreateReferenceFromBRepName` cannot
   resolve an edge's BRep name back into a reference in any context tried,
   and a face reference's `Name` is the same kind of opaque BRep string on
   the same kind of `Reference` object. No one has separately tried to
   resolve a face's BRep name back, so treat this as inherited caution, not
   an independent result.

WHY THERE IS NO `ensure_shell`/`ensure_thickness`/`ensure_hole`, for the same
reason `geometry.edges` gives for `ensure_edge_fillet`/`ensure_chamfer`: a
`Face` has no stable, independently re-readable handle the way a `Sketch`
does. There is no verified way to read "which face is this shell/thickness/
hole actually on" back from a created feature, so a truthful `ensure_*` would
have to either skip that comparison (silently reusing a feature that might be
on the wrong face) or fake identity from an index or a BRep string this very
module documents as non-durable. Neither is honest, so
`geometry.part_design.PartDesign` ships `create_shell`/`create_thickness`/
`create_hole` plus `get_*`/`remove_*`/listing, and stops there, exactly like
the edge features.

ON SHARING CODE WITH `geometry.edges`. `Face`/`FaceSnapshot` below are
structurally identical to `Edge`/`EdgeSnapshot` (same `index`/`generation`/
`com_object`/`descriptor`/`__repr__`, same `len`/`iter`/`getitem` sequence
behaviour), and `take_face_snapshot` differs from `take_edge_snapshot` only
in the query string. Collapsing the two *classes* into one shared base was
deliberately not done: an `isinstance(x, Edge)`/`isinstance(x, Face)` check
is exactly how `create_edge_fillet`/`create_shell` (etc.) refuse a reference
of the wrong kind, and the docstring narrative each one carries is specific
to its own measured facts (see the section above). What genuinely is the same
mechanical routine -- capture the user's selection, `Clear()`,
`Search(query)`, `Item(i).Reference` for `i` in `1..Count`, restore the
selection -- lives once in `geometry._topology_search.search_references`,
which both snapshot functions call.
"""

import math
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any

import pywintypes

from auto_3dx.errors import AutomationError, ParameterTypeError
from auto_3dx.geometry._topology_search import (
    BodyIndex,
    owner_of,
    search_references,
)
from auto_3dx.geometry.facts import FaceGeometry
from auto_3dx.geometry.sketch import _wrap_com_error

if TYPE_CHECKING:
    from auto_3dx.geometry.query import FaceQuery

FACE_SEARCH_QUERY: str = "Topology.Face,all"
"""The only verified `Selection.Search` query that enumerates solid faces.

`Search("Face,all")` (no `Topology.` prefix) raises a COM error, exactly as
it does for edges; `Search("Topology.Edge,all")` returns edges, which are the
wrong kind of reference for `AddNewShell`/`AddNewThickness`/`AddNewHole`.
This is the one string this module ever passes to `Search`
(`docs/conventions.md` section 1.2.2.2, probe 37) when the search covers the whole
Part.
"""

FACE_SEARCH_QUERY_IN_SELECTION: str = "Topology.Face,sel"
"""The same search, restricted to whatever is selected when it runs.

Selecting one body and running this returned that body's faces only (probe 42, live
2026-09-18), which is how `part.topology.faces(body=...)` scopes a snapshot. A body
whose features have not been rebuilt reports no faces at all rather than failing.
"""


class Face:
    """One face reference from a single `FaceSnapshot`.

    Wraps the raw `Reference` COM object read from `SelectedElement.Reference`
    (the only route that works -- `Part.CreateReferenceFromObject` fails on a
    search hit, for faces exactly as for edges) together with the one-based
    position it held in that search's results.

    Both halves are deliberately non-durable identity, mirroring `Edge`:

    * `index` is only meaningful for the model exactly as it stood when the
      snapshot was taken. Never apply it to a different snapshot.
    * `descriptor` exists only for logging and equality comparison within one
      snapshot, never for storage -- see the module docstring for why that is
      inherited caution rather than a separately measured fact for faces.

    A caller that has modified the model since taking a snapshot must take a
    new one (`part.topology.faces()`) before trusting either `index` or
    `descriptor` again.
    """

    def __init__(
        self,
        reference: Any,
        index: int,
        generation: int = 0,
        owner_body: Any = None,
        owner_body_name: "str | None" = None,
        owner_feature_name: "str | None" = None,
        measurer: Any = None,
        model_generation: Any = None,
    ) -> None:
        """Initializes the handle.

        Args:
            reference: The raw CATIA `Reference` COM object, as read from
                `SelectedElement.Reference`.
            index: The one-based position this face held in the
                `Selection.Search` result it came from.
            generation: The model generation the snapshot was taken at, so a
                later change can mark this handle stale. Defaults to 0 for a
                `Face` built directly in a test, with no owning `PartDesign`.
            owner_body: The raw `Body` COM object this face was found in, read
                from the reference's owner chain at snapshot time. `None` when
                CATIA did not report one, which leaves the ownership guard in
                `PartDesign` unable to refuse this face.
            owner_body_name: That body's name, for error messages.
            measurer: The `GeometryMeasurer` that measures this face on demand, from
                the Part's editor. `None` for a handle built directly, which then cannot
                report `geometry`.
            model_generation: The owning Part's `ModelGeneration`, checked before
                `geometry` is read so a stale handle is refused.
            owner_feature_name: The feature the reference came from, for error
                messages.
        """
        self._reference = reference
        self._index = index
        self._generation = generation
        self._owner_body = owner_body
        self._owner_body_name = owner_body_name
        self._owner_feature_name = owner_feature_name
        self._measurer = measurer
        self._model_generation = model_generation
        self._geometry: Any = None
        self._point_distance: Any = None

    @property
    def owner_body(self) -> Any:
        """Any: The raw `Body` this face belongs to, or `None` if CATIA did not say.

        Read from the model when the snapshot was taken (`Reference.Parent` up to the
        owning `Body`, probe 42), never remembered between processes. A feature refuses
        a face whose owner is a different body from the one it builds in
        (`CrossBodyReferenceError`).
        """
        return self._owner_body

    @property
    def owner_body_name(self) -> "str | None":
        """str | None: The name of the body this face belongs to, if known."""
        return self._owner_body_name

    @property
    def current_owner_feature_name(self) -> "str | None":
        """str | None: The feature CATIA currently attributes this face to.

        Same value as `owner_feature_name`, under a name that says what it is. It is read
        from `Reference.Parent`, which names the feature whose RESULT carries the face
        now -- usually the latest solid feature in the body. It is NOT the feature that
        first created the face: live, after one fillet every edge of a block reported the
        fillet as its owner (probe 45). Use it to scope a query to "what the current solid
        is made of", never as history.
        """
        return self._owner_feature_name

    @property
    def geometry(self) -> FaceGeometry:
        """FaceGeometry: What this face is, measured through `MeasurableService`.

        Measured on first access and kept for the life of this handle, which is safe only
        because a handle belongs to one model generation: once anything changes the model,
        reading it raises `StaleSnapshotError` instead of returning numbers about geometry
        that may no longer exist.

        Raises:
            StaleSnapshotError: If the model changed since the snapshot was taken.
            AutomationError: If this face was not taken through `part.topology` (there is
                nothing to measure it with), or CATIA cannot measure it.
        """
        if self._model_generation is not None:
            self._model_generation.require_current(self._generation, "face", "part.topology.faces()")
        if self._measurer is None:
            raise AutomationError(
                "This face has no measurer. Take it through part.topology.faces(), which measures "
                "through the Part's own editor."
            )
        if self._geometry is None:
            self._geometry = self._measurer.face(self._reference)
        return self._geometry

    @property
    def owner_feature_name(self) -> "str | None":
        """str | None: The feature CATIA currently attributes this face to, if known.

        Read from `Reference.Parent`: the feature whose result carries the face now,
        usually the latest solid feature in the body. Not historical provenance --
        see `current_owner_feature_name`.
        """
        return self._owner_feature_name

    @property
    def generation(self) -> int:
        """int: The model generation this face's snapshot was taken at."""
        return self._generation

    def describe(self) -> str:
        """One line of measured facts about this face, for messages, logs and agents.

        Built from `geometry` (measured once, lazily) and the owner read at snapshot time,
        for example ``"planar face, area 2400.000 mm2, centre (0.000, 0.000, 20.000),
        normal axis (0.000, 0.000, 1.000), owner 'Pad.1' in body 'PartBody'"``. The owner
        is CATIA's current owner, not the feature that created the face. It contains no
        index and no BRep name: neither identifies the face beyond this snapshot.

        Returns:
            The description.

        Raises:
            StaleSnapshotError: If the model changed since the snapshot was taken.
            AutomationError: If the face cannot be measured.
        """
        facts = self.geometry
        parts = [
            f"{facts.surface_type} face",
            f"area {facts.area_mm2:.3f} mm2",
            f"centre {_point_text(facts.center_mm)}",
        ]
        if facts.normal is not None:
            parts.append(f"normal axis {_point_text(facts.normal)}")
        if facts.radius_mm is not None:
            parts.append(f"radius {facts.radius_mm:.3f} mm")
        parts.append(_owner_text(self._owner_feature_name, self._owner_body_name))
        return ", ".join(part for part in parts if part)

    def distance_to(self, point: Any) -> float:
        """The shortest distance from a point to this face, in millimetres.

        Measured by CATIA (`MeasurableBetween.DistanceMinToPoint`) to the face as it is
        bounded, not to its plane or cylinder: live (probe 47l) a point in a block's top
        plane 10 mm beyond its edge measured 10, not 0. It is what `adjacent_to` in
        `geometry.query` is built on.

        Args:
            point: `(x, y, z)` in Part millimetres.

        Returns:
            The distance; 0 for a point on the face.

        Raises:
            ParameterTypeError: If `point` is not three finite numbers.
            StaleSnapshotError: If the model changed since the snapshot was taken.
            AutomationError: If the face cannot be measured.
        """
        target = _point3(point, "point")
        if self._model_generation is not None:
            self._model_generation.require_current(
                self._generation, "face", "part.topology.faces()"
            )
        if self._measurer is None:
            raise AutomationError(
                "This face has no measurer. Take it through part.topology.faces(), which "
                "measures through the Part's own editor."
            )
        if self._point_distance is None:
            self._point_distance = self._measurer.point_distance(self._reference)
        return float(self._point_distance(target))

    def _belongs_to(self, generation: Any) -> bool:
        """Whether this face came from the Part that owns `generation`.

        Every wrapper of one CATIA Part shares one `ModelGeneration` object
        (`docs/api-design.md` 5.1), so identity of that object is identity of the Part.
        A handle built directly, without one, cannot say and is let through, the same
        policy as an unknown owner body.
        """
        return self._model_generation is None or self._model_generation is generation

    @property
    def com_object(self) -> Any:
        """Returns the raw underlying `Reference` COM object.

        This is the value `PartDesign.create_shell`/`create_thickness`/
        `create_hole` pass to `ShapeFactory`. It is also an escape hatch for
        callers that need direct COM access, and is useful in tests.

        Returns:
            The wrapped raw `Reference`.
        """
        return self._reference

    @property
    def index(self) -> int:
        """Returns the one-based position this face held in its search.

        This is NOT a durable identity: the same integer means a different
        face, or no face at all, once the model has changed. Never persist
        this value and use it against a later, independently-taken
        `FaceSnapshot`.

        Returns:
            The one-based `Selection.Item` position at snapshot time.
        """
        return self._index

    @property
    def descriptor(self) -> str:
        """Returns the underlying reference's `Name`, for logging/comparison only.

        Same shape as `Edge.descriptor`: a long, opaque BRep string. It
        exists only so a caller can log which face was used, or compare two
        `Face` objects taken from the *same* snapshot for equality. Do not
        store this value with the intent of looking the face up again later
        -- take a new `FaceSnapshot` instead (module docstring).

        Returns:
            The raw `Reference.Name` string.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._reference.Name
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def __repr__(self) -> str:
        """Returns a debugging representation.

        The opaque BRep descriptor is deliberately not read here: it can be
        very long, and reading it can itself raise. Use `descriptor`
        explicitly when it is actually needed.

        Returns:
            A string such as ``Face(index=3)``.
        """
        return f"Face(index={self._index!r})"


class FaceSnapshot:
    """Every face of the solid, as `Selection.Search` reported it at one instant.

    `part.topology.faces()` is how a caller obtains one. It describes
    the model exactly as it stood the moment the search ran: as with edges,
    face count and order should be assumed to change after every
    modification, so a snapshot must never be used against a model that has
    since changed.

    **A snapshot is single-generation, and that is enforced rather than
    merely documented** -- the same policy `geometry.edges.EdgeSnapshot`
    enforces, applied here as project law rather than as an independently
    reproduced failure (see the module docstring). A snapshot is marked stale
    as soon as the `PartDesign` that produced it changes the model, and using
    it then raises instead of reaching COM.

    Attributes:
        generation: The model generation this snapshot was taken at. Compared
            against the owning `PartDesign`'s current generation to decide
            whether the snapshot is still usable.
    """

    def __init__(self, faces: Sequence[Face], generation: int = 0) -> None:
        """Initializes the snapshot.

        Args:
            faces: The `Face` objects found by the search, in search order.
            generation: The model generation at snapshot time. Defaults to 0
                for a snapshot built directly in a test, which has no owner to
                compare against.
        """
        self._faces: "tuple[Face, ...]" = tuple(faces)
        self._generation = generation

    @property
    def generation(self) -> int:
        """int: The model generation this snapshot was taken at."""
        return self._generation

    def query(self) -> "FaceQuery":
        """Starts a geometry query over this snapshot's faces.

        The query is bound to this snapshot, so it inherits its staleness: once the model
        changes, reading any face's geometry raises `StaleSnapshotError`.

        Returns:
            A `FaceQuery` over every face in this snapshot.
        """
        from auto_3dx.geometry.query import FaceQuery

        return FaceQuery(list(self._faces))

    def __len__(self) -> int:
        """Returns how many faces this snapshot found.

        Returns:
            The face count at snapshot time.
        """
        return len(self._faces)

    def __iter__(self) -> Iterator[Face]:
        """Iterates the faces in search order.

        Returns:
            An iterator over `Face` objects.
        """
        return iter(self._faces)

    def __getitem__(self, position: int) -> Face:
        """Returns one face by its position within this snapshot.

        `position` indexes into THIS snapshot's own (0-based, Python-style)
        sequence. It is only ever safe to use with a position obtained from
        this same snapshot -- see `Face.index` for the distinct, one-based
        CATIA search position, which is what `Face` itself exposes.

        Args:
            position: A 0-based Python index into this snapshot's faces.

        Returns:
            The `Face` at that position.

        Raises:
            IndexError: If `position` is out of range for this snapshot.
        """
        return self._faces[position]

    def __repr__(self) -> str:
        """Returns a debugging representation.

        Returns:
            A string such as ``FaceSnapshot(count=8, generation=0)``.
        """
        return f"FaceSnapshot(count={len(self._faces)}, generation={self._generation})"


def take_face_snapshot(
    selection: Any,
    generation: int = 0,
    part_com_object: Any = None,
    body: Any = None,
    measurer: Any = None,
    model_generation: Any = None,
) -> FaceSnapshot:
    """Runs the one verified face search and returns a fresh `FaceSnapshot`.

    This is the face counterpart of `geometry.edges.take_edge_snapshot`,
    verified against a live session (`docs/conventions.md` section 1.2.2.2,
    probe 37): `Part.CreateReferenceFromObject` fails on a search hit here
    too, so each `Reference` must come from `SelectedElement.Reference`
    instead. The exact call order matters and is reproduced verbatim by
    `geometry._topology_search.search_references`: `Clear()`,
    `Search(FACE_SEARCH_QUERY)`, then `Item(i).Reference` for `i` in
    `1..Count`. The user's selection is captured before the search and
    restored afterwards, so taking a snapshot does not change it.

    Args:
        selection: The raw CATIA `Selection` COM object from the editor.
        generation: The model generation to stamp the snapshot with, so a
            later change can mark it stale. Defaults to 0 for a snapshot with
            no owning `PartDesign`.
        part_com_object: The raw Part being searched; the search is refused unless it
            is the active Part.
        body: The raw `Body` COM object to search inside. `None` searches the whole
            Part, as `Topology.Face,all` has always done. Passing a body selects it and
            searches `Topology.Face,sel`, which live returned that body's faces only
            (probe 42). Either way each `Face` carries the body it was found in.

    Returns:
        A fresh `FaceSnapshot` describing every face of the solid as it
        stands right now. Take a new one after any model change; an old
        snapshot is refused once its owner has changed the model.

    Raises:
        ValidationError: If `selection` is `None`.
        AutomationError: If the selection cannot be captured (nothing is
            changed), or the search fails.

    Warns:
        SelectionNotRestoredWarning: If the selection did not fully come back.
            The snapshot is still valid.
    """
    query = FACE_SEARCH_QUERY if body is None else FACE_SEARCH_QUERY_IN_SELECTION
    references = search_references(selection, query, part_com_object, body)
    index = BodyIndex(part_com_object) if part_com_object is not None else None
    faces = []
    for position, reference in enumerate(references, start=1):
        owner_body, owner_body_name, owner_feature_name = owner_of(reference, index)
        faces.append(
            Face(
                reference,
                position,
                generation,
                owner_body,
                owner_body_name,
                owner_feature_name,
                measurer,
                model_generation,
            )
        )
    return FaceSnapshot(faces, generation)


def _point3(value: Any, label: str) -> "tuple[float, float, float]":
    """Validates an `(x, y, z)` point of finite numbers, before any COM call."""
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise ParameterTypeError(f"{label} must be three numbers (x, y, z), not {value!r}.")
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
        raise ParameterTypeError(f"{label} must hold numbers, not {value!r}.")
    if not all(math.isfinite(item) for item in value):
        raise ParameterTypeError(f"{label} must be finite, not {value!r}.")
    return (float(value[0]), float(value[1]), float(value[2]))


def _point_text(point: "tuple[float, float, float]") -> str:
    """Renders a point or direction with three decimals, for descriptions."""
    return "(" + ", ".join(f"{value:.3f}" for value in point) + ")"


def _owner_text(feature: "str | None", body: "str | None") -> str:
    """Renders what CATIA reported as the owner, or nothing when it reported nothing."""
    if feature and body:
        return f"owner {feature!r} in body {body!r}"
    if feature:
        return f"owner {feature!r}"
    if body:
        return f"in body {body!r}"
    return ""
