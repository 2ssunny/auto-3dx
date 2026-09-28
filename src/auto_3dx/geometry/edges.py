"""Edge references for reference-based Part Design features (fillet, chamfer).

About 80 `ShapeFactory.AddNew*` methods take a face or an edge instead of a
sketch, and until now there was no way to name one (`docs/conventions.md`
section 1.2.2). This module implements the one route that has been verified
to work for edges (section 1.2.2.2, probes 28/31/34/35):

    selection.Clear()
    selection.Search("Topology.Edge,all")       # returns void, mutates Selection
    for i in 1..selection.Count:
        reference = selection.Item(i).Reference  # a real, feature-usable Reference
    selection.Clear()

The search replaces the editor's selection, so `geometry._topology_search` captures
the user's selection first and restores it afterwards.

`Part.CreateReferenceFromObject` fails on a search hit -- `Selection.Item(i)
.Reference` is the only way to turn one into something
`AddNewEdgeFilletWithConstantRadius`/`AddNewChamfer` will accept. A face
reference is rejected by both of those factories for every propagation mode
tried, so this module (and the two Part Design features built on it) only
ever deals in edges.

FOUR MEASURED FACTS THAT SHAPE THIS API. Getting these wrong would silently
corrupt a caller's model, so each one is repeated at the point in this module
where it matters, not just here:

1. A `Reference` obtained this way may or may not keep working after the
   model changes, and which one it is cannot be predicted. Three fillets
   built from three FRESH searches all updated (probe 34), and so did two
   fillets from one shared search in that run. But on a plain cube, building
   a second fillet from the same snapshot failed for the next edge, the
   middle edge and the last edge alike -- two of the three failed at the
   creation call and one at `Part.Update()` -- while a fresh snapshot's first
   edge succeeded. Whether reuse works depends on whether that particular
   edge survived the change untouched. A call that works or fails
   unpredictably is not something this library exposes, so a snapshot is
   marked stale as soon as its `PartDesign` changes the model and using it
   afterwards raises instead of reaching COM.
2. Edge COUNT and search ORDER change after every modification: 29 edges,
   then 32 after one fillet, then 38, then 41 (probe 34/35). An index into a
   search result is therefore only meaningful for the exact model state that
   search ran against. `Edge.index` and `EdgeSnapshot` are named and
   documented to make that impossible to miss.
3. A reference's `Name`/`DisplayName` is a long BRep string, and
   `Part.CreateReferenceFromBRepName` fails to resolve it back into a usable
   reference in every context tried (Part context, owning-feature context).
   After a rebuild the whole name set changes too. There is no durable
   selector: a caller cannot store a name or an index and look the same edge
   up again later. `Edge.descriptor` exists only for logging and equality
   comparison within one snapshot, never for storage.
4. The search can be scoped to a BODY, but not to a feature. Selecting one
   body first and searching `Topology.Edge,sel` returns that body's edges
   only, and follows the selection rather than the In-Work Object (probe 42,
   live 2026-09-18); that is what `part.topology.edges(body=...)` does.
   Scoping to one feature is still unsolved: `Topology.Edge,in,<name>`, a
   name filter composed with `&` and the rest raised or returned the whole
   Part (probe 35). What each edge DOES carry is its owner: `owner_body`,
   `owner_body_name` and `owner_feature_name` come from walking
   `Reference.Parent` in the model at snapshot time, so `PartDesign` can
   refuse an edge belonging to another body before CATIA is called. The
   owner feature is the one whose result carries the edge NOW (after a
   fillet every edge of a block named the fillet, probe 45), never history.

   An edge CAN now be picked by measured geometry. Probe 31 concluded it could
   not, but it had passed an item-type code to `MeasurableService.GetMeasurable`
   whose second argument is a `CATMeasurableType`; with the right codes an edge
   reports its length, end points, and radius/centre when circular (probe 45).
   `Edge.geometry` and `EdgeSnapshot.query()` are built on that
   (`geometry.facts`, `geometry.query`).

WHY THERE IS NO `ensure_edge_fillet`/`ensure_chamfer`. `PartDesign.ensure_pad`
(`geometry/part_design.py`) reuses an existing feature by comparing its
source `Sketch` to the requested one by COM identity (`==`). That works
because a `Sketch` is a stable, independently addressable object: the same
`Sketch` COM object can be read back from an existing feature and compared
directly against one the caller holds. An edge has no such handle. The only
way to name one is the `Reference` inside an `Edge`, and fact 3 above rules
out turning its `Name`/`DisplayName` back into anything comparable -- there
is no verified way to read "which edge is this fillet/chamfer actually on"
back from a created feature at all. A truthful `ensure_*` would have to
either skip that comparison (silently reusing a feature that might be on the
wrong edge entirely) or fake identity from an index or a BRep string that
this very module documents as non-durable. Neither is honest, so
`geometry.part_design.PartDesign` ships `create_edge_fillet`/`create_chamfer`
plus `get_*`/`remove_*`/listing, and stops there. A missing method is better
than one that silently reuses the wrong geometry.
"""

from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any

import pywintypes

from auto_3dx.errors import AutomationError
from auto_3dx.geometry._topology_search import (
    BodyIndex,
    owner_of,
    search_references,
)
from auto_3dx.geometry.facts import EdgeGeometry
from auto_3dx.geometry.sketch import _wrap_com_error

if TYPE_CHECKING:
    from auto_3dx.geometry.query import EdgeQuery

EDGE_SEARCH_QUERY: str = "Topology.Edge,all"
"""The only verified `Selection.Search` query that enumerates solid edges.

`Search("Edge,all")` (no `Topology.` prefix) raises a COM error;
`Search("Topology.Face,all")` returns faces, which are rejected by both
`AddNewEdgeFilletWithConstantRadius` and `AddNewChamfer`. This is the one
string this module ever passes to `Search` (`docs/conventions.md` section
1.2.2.2) when the search covers the whole Part.
"""

EDGE_SEARCH_QUERY_IN_SELECTION: str = "Topology.Edge,sel"
"""The same search, restricted to whatever is selected when it runs.

Selecting one body and running this returned that body's edges only, and it followed
the selection rather than the In-Work Object (probe 42, live 2026-09-18). It is how
`part.topology.edges(body=...)` scopes a snapshot to one body. `",in"` was also tried
and returned the whole Part.
"""


class Edge:
    """One edge reference from a single `EdgeSnapshot`.

    Wraps the raw `Reference` COM object read from `SelectedElement.Reference`
    (the only route that works -- `Part.CreateReferenceFromObject` fails on a
    search hit) together with the one-based position it held in that
    search's results.

    Both halves are deliberately non-durable identity, not an oversight:

    * `index` is only meaningful for the model exactly as it stood when the
      snapshot was taken (module docstring, fact 2). Never apply it to a
      different snapshot.
    * The `Reference` itself keeps working across later model changes
      (module docstring, fact 1), so the same `Edge` object may be passed to
      more than one `PartDesign.create_edge_fillet`/`create_chamfer` call.
      What does NOT survive is naming it for later re-lookup (fact 3):
      `descriptor` cannot be stored and resolved back into this same edge
      once the model has moved on, or even across a fresh `Python` process.

    A caller that has modified the model since taking a snapshot must take a
    new one (`part.topology.edges()`) before trusting either `index` or
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
            index: The one-based position this edge held in the
                `Selection.Search` result it came from.
            generation: The model generation the snapshot was taken at, so a
                later change can mark this handle stale. Defaults to 0 for an
                `Edge` built directly in a test, with no owning `PartDesign`.
            owner_body: The raw `Body` COM object this edge was found in, read
                from the reference's owner chain at snapshot time. `None` when
                CATIA did not report one, which leaves the ownership guard in
                `PartDesign` unable to refuse this edge.
            owner_body_name: That body's name, for error messages.
            measurer: The `GeometryMeasurer` that measures this edge on demand, from
                the Part's editor. `None` for a handle built directly, which then cannot
                report `geometry`.
            model_generation: The owning Part's `ModelGeneration`, checked before
                `geometry` is read so a stale handle is refused.
            owner_feature_name: The feature the reference came from (a `Pad`
                for a solid edge, the `Sketch` for an edge of a consumed
                sketch), for error messages.
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

    @property
    def owner_body(self) -> Any:
        """Any: The raw `Body` this edge belongs to, or `None` if CATIA did not say.

        Read from the model when the snapshot was taken (`Reference.Parent` up to the
        owning `Body`, probe 42), never remembered between processes. A feature refuses
        an edge whose owner is a different body from the one it builds in
        (`CrossBodyReferenceError`).
        """
        return self._owner_body

    @property
    def owner_body_name(self) -> "str | None":
        """str | None: The name of the body this edge belongs to, if known."""
        return self._owner_body_name

    @property
    def current_owner_feature_name(self) -> "str | None":
        """str | None: The feature CATIA currently attributes this edge to.

        Same value as `owner_feature_name`, under a name that says what it is. It is read
        from `Reference.Parent`, which names the feature whose RESULT carries the edge
        now -- usually the latest solid feature in the body. It is NOT the feature that
        first created the edge: live, after one fillet every edge of a block reported the
        fillet as its owner (probe 45). Use it to scope a query to "what the current solid
        is made of", never as history.
        """
        return self._owner_feature_name

    @property
    def geometry(self) -> EdgeGeometry:
        """EdgeGeometry: What this edge is, measured through `MeasurableService`.

        Measured on first access and kept for the life of this handle, which is safe only
        because a handle belongs to one model generation: once anything changes the model,
        reading it raises `StaleSnapshotError` instead of returning numbers about geometry
        that may no longer exist.

        Raises:
            StaleSnapshotError: If the model changed since the snapshot was taken.
            AutomationError: If this edge was not taken through `part.topology` (there is
                nothing to measure it with), or CATIA cannot measure it.
        """
        if self._model_generation is not None:
            self._model_generation.require_current(self._generation, "edge", "part.topology.edges()")
        if self._measurer is None:
            raise AutomationError(
                "This edge has no measurer. Take it through part.topology.edges(), which measures "
                "through the Part's own editor."
            )
        if self._geometry is None:
            self._geometry = self._measurer.edge(self._reference)
        return self._geometry

    @property
    def owner_feature_name(self) -> "str | None":
        """str | None: The feature CATIA currently attributes this edge to, if known.

        Read from `Reference.Parent`: the feature whose result carries the edge now,
        usually the latest solid feature in the body. Not historical provenance --
        see `current_owner_feature_name`.
        """
        return self._owner_feature_name

    @property
    def generation(self) -> int:
        """int: The model generation this edge's snapshot was taken at."""
        return self._generation

    def _belongs_to(self, generation: Any) -> bool:
        """Whether this edge came from the Part that owns `generation`.

        Every wrapper of one CATIA Part shares one `ModelGeneration` object
        (`docs/api-design.md` 5.1), so identity of that object is identity of the Part.
        A handle built directly, without one, cannot say and is let through, the same
        policy as an unknown owner body.
        """
        return self._model_generation is None or self._model_generation is generation

    @property
    def com_object(self) -> Any:
        """Returns the raw underlying `Reference` COM object.

        This is the value `PartDesign.create_edge_fillet`/`create_chamfer`
        pass to `ShapeFactory`. It is also an escape hatch for callers that
        need direct COM access, and is useful in tests.

        Returns:
            The wrapped raw `Reference`.
        """
        return self._reference

    @property
    def index(self) -> int:
        """Returns the one-based position this edge held in its search.

        This is NOT a durable identity (module docstring, fact 2): the same
        integer means a different edge, or no edge at all, once the model
        has changed. Never persist this value and use it against a later,
        independently-taken `EdgeSnapshot`.

        Returns:
            The one-based `Selection.Item` position at snapshot time.
        """
        return self._index

    @property
    def descriptor(self) -> str:
        """Returns the underlying reference's `Name`, for logging/comparison only.

        This is a long, opaque BRep string (for example
        ``Selection_REdge:(Edge:(Face:(Brp:...)))``). It exists only so a
        caller can log which edge was used, or compare two `Edge` objects
        taken from the *same* snapshot for equality. It is NOT a durable
        selector (module docstring, fact 3):
        `Part.CreateReferenceFromBRepName` fails to resolve this string back
        into a reference in every context tried, and the whole set of
        descriptors changes after any model rebuild. Do not store this value
        with the intent of looking the edge up again later -- take a new
        `EdgeSnapshot` instead.

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
            A string such as ``Edge(index=3)``.
        """
        return f"Edge(index={self._index!r})"


class EdgeSnapshot:
    """Every edge of the solid, as `Selection.Search` reported it at one instant.

    `part.topology.edges()` is how a caller obtains one. It describes
    the model exactly as it stood the moment the search ran: edge count and
    order both change after every modification, so a snapshot must never be
    used against a model that has since changed.

    **A snapshot is single-generation, and that is enforced rather than merely
    documented.** Measured on a 24 mm cube with one fillet already applied:
    building a second fillet from the same snapshot failed, whether the second
    edge was the next one, the middle one, or the last one -- two of those three
    failed at the creation call and one at `Part.Update()`. Taking a fresh
    snapshot and using its first edge succeeded. An earlier probe saw two
    features built from one snapshot both succeed, so reuse does not always
    fail; it fails depending on whether that particular edge happened to
    survive the change untouched. A call that works or fails unpredictably is
    exactly what this library refuses to expose, so a snapshot is marked stale
    as soon as the `PartDesign` that produced it changes the model, and using
    it then raises instead of reaching COM.

    Attributes:
        generation: The model generation this snapshot was taken at. Compared
            against the owning `PartDesign`'s current generation to decide
            whether the snapshot is still usable.
    """

    def __init__(self, edges: Sequence[Edge], generation: int = 0) -> None:
        """Initializes the snapshot.

        Args:
            edges: The `Edge` objects found by the search, in search order.
            generation: The model generation at snapshot time. Defaults to 0
                for a snapshot built directly in a test, which has no owner to
                compare against.
        """
        self._edges: "tuple[Edge, ...]" = tuple(edges)
        self._generation = generation

    @property
    def generation(self) -> int:
        """int: The model generation this snapshot was taken at."""
        return self._generation

    def query(self) -> "EdgeQuery":
        """Starts a geometry query over this snapshot's edges.

        The query is bound to this snapshot, so it inherits its staleness: once the model
        changes, reading any edge's geometry raises `StaleSnapshotError`.

        Returns:
            A `EdgeQuery` over every edge in this snapshot.
        """
        from auto_3dx.geometry.query import EdgeQuery

        return EdgeQuery(list(self._edges))

    def __len__(self) -> int:
        """Returns how many edges this snapshot found.

        Returns:
            The edge count at snapshot time.
        """
        return len(self._edges)

    def __iter__(self) -> Iterator[Edge]:
        """Iterates the edges in search order.

        Returns:
            An iterator over `Edge` objects.
        """
        return iter(self._edges)

    def __getitem__(self, position: int) -> Edge:
        """Returns one edge by its position within this snapshot.

        `position` indexes into THIS snapshot's own (0-based, Python-style)
        sequence. It is only ever safe to use with a position obtained from
        this same snapshot -- see `Edge.index` for the distinct, one-based
        CATIA search position, which is what `Edge` itself exposes.

        Args:
            position: A 0-based Python index into this snapshot's edges.

        Returns:
            The `Edge` at that position.

        Raises:
            IndexError: If `position` is out of range for this snapshot.
        """
        return self._edges[position]

    def __repr__(self) -> str:
        """Returns a debugging representation.

        Returns:
            A string such as ``EdgeSnapshot(count=29, generation=3)``.
        """
        return f"EdgeSnapshot(count={len(self._edges)}, generation={self._generation})"


def take_edge_snapshot(
    selection: Any,
    generation: int = 0,
    part_com_object: Any = None,
    body: Any = None,
    measurer: Any = None,
    model_generation: Any = None,
) -> EdgeSnapshot:
    """Runs the one verified edge search and returns a fresh `EdgeSnapshot`.

    This is the only verified route from CATIA topology to a feature-usable
    reference (`docs/conventions.md` section 1.2.2.2):
    `Part.CreateReferenceFromObject` fails on a search hit, so each
    `Reference` must come from `SelectedElement.Reference` instead. The
    exact call order matters and is reproduced verbatim by
    `geometry._topology_search.search_references`: `Clear()`,
    `Search(EDGE_SEARCH_QUERY)`, then `Item(i).Reference` for `i` in
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
            Part, which is what `Topology.Edge,all` has always returned: the edges of
            every body in one flat list. Passing a body selects it and searches
            `Topology.Edge,sel` instead, which live returned that body's edges only
            (probe 42). Either way each `Edge` carries the body it was found in.

    Returns:
        A fresh `EdgeSnapshot` describing every edge of the solid as it
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
    query = EDGE_SEARCH_QUERY if body is None else EDGE_SEARCH_QUERY_IN_SELECTION
    references = search_references(selection, query, part_com_object, body)
    index = BodyIndex(part_com_object) if part_com_object is not None else None
    edges = []
    for position, reference in enumerate(references, start=1):
        owner_body, owner_body_name, owner_feature_name = owner_of(reference, index)
        edges.append(
            Edge(
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
    return EdgeSnapshot(edges, generation)
