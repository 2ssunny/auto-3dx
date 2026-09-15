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
4. There is no way to scope the search to one feature. Every scoped syntax
   tried (`Topology.Edge,in,<name>`, `Topology.Edge,sel`, a name filter
   composed with `&`, ...) either raised a COM error or returned the whole
   solid (probe 35). `MeasurableService` exposed no length for an edge
   either, so an edge cannot be picked by measured geometry. A caller who
   needs "the edges of this pad" has to filter `EdgeSnapshot` results by
   whatever weaker signal is available to them (e.g. count, or manual
   inspection), not by anything this module can offer.

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
from typing import Any

import pywintypes

from auto_3dx.geometry._topology_search import search_references
from auto_3dx.geometry.sketch import _wrap_com_error

EDGE_SEARCH_QUERY: str = "Topology.Edge,all"
"""The only verified `Selection.Search` query that enumerates solid edges.

`Search("Edge,all")` (no `Topology.` prefix) raises a COM error;
`Search("Topology.Face,all")` returns faces, which are rejected by both
`AddNewEdgeFilletWithConstantRadius` and `AddNewChamfer`. This is the one
string this module ever passes to `Search` (`docs/conventions.md` section
1.2.2.2).
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

    def __init__(self, reference: Any, index: int, generation: int = 0) -> None:
        """Initializes the handle.

        Args:
            reference: The raw CATIA `Reference` COM object, as read from
                `SelectedElement.Reference`.
            index: The one-based position this edge held in the
                `Selection.Search` result it came from.
            generation: The model generation the snapshot was taken at, so a
                later change can mark this handle stale. Defaults to 0 for an
                `Edge` built directly in a test, with no owning `PartDesign`.
        """
        self._reference = reference
        self._index = index
        self._generation = generation

    @property
    def generation(self) -> int:
        """int: The model generation this edge's snapshot was taken at."""
        return self._generation

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


def take_edge_snapshot(selection: Any, generation: int = 0) -> EdgeSnapshot:
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
    references = search_references(selection, EDGE_SEARCH_QUERY)
    edges = [
        Edge(reference, position, generation)
        for position, reference in enumerate(references, start=1)
    ]
    return EdgeSnapshot(edges, generation)
