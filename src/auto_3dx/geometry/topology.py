"""Topology snapshots of a Part's solid: its edges and faces.

Edges and faces are not a Part Design detail. Fillets and chamfers consume edges;
shells, thicknesses and holes consume faces; measurement, inspection and any future
selection system will consume both. So they live on `part.topology`, next to the
features that use them rather than inside them.

Both come from the one verified route (`docs/conventions.md` section 1.2.2.2):
`Selection.Search("Topology.Edge,all")` or `"Topology.Face,all"`, then
`SelectedElement.Reference` for each hit. A snapshot covers the whole solid; no
verified search scopes it to one feature.

A snapshot is single-generation. It is stamped with the Part's model generation, and
every consumer refuses it once the model has changed through the SDK
(`docs/api-design.md` sections 5 and 7).

The search replaces the editor's selection, so the user's selection is captured
before it and restored afterwards. When CATIA silently refuses part of the restore,
the snapshot is still returned and `SelectionNotRestoredWarning` is emitted.
"""

from typing import Any

from auto_3dx._generation import ModelGeneration
from auto_3dx.geometry.edges import EdgeSnapshot, take_edge_snapshot
from auto_3dx.geometry.faces import FaceSnapshot, take_face_snapshot


class _WorkBody:
    """The default `body` argument: follow the open work context, if there is one."""

    def __repr__(self) -> str:
        """str: Debug representation; does not contact CATIA."""
        return "WORK_BODY"


WORK_BODY = _WorkBody()
"""Default scope for `edges`/`faces`: the `part.work_in(body)` body, else the Part.

It exists so that `body=None` can keep its own meaning -- search the whole Part -- even
inside a work context, which a plain `None` default could not express.
"""


class Topology:
    """Takes edge and face snapshots of a Part's solid.

    Obtain it as `part.topology`, so its snapshots share the Part's generation.

    A search covers the whole Part unless it is scoped to a body, either explicitly
    (`part.topology.edges(body="ToolBody")`) or implicitly, by taking the snapshot
    inside `part.work_in(body)`.
    """

    def __init__(
        self,
        selection: Any,
        generation: ModelGeneration | None = None,
        part_com_object: Any = None,
        body_target: Any = None,
        resolve_body: Any = None,
        measurer: Any = None,
    ) -> None:
        """Initializes the namespace.

        Args:
            selection: The raw CATIA `Selection` COM object of the editor editing
                the Part. The search runs through it.
            generation: The owning Part's model generation. A standalone instance
                gets its own, which no other wrapper shares, so its snapshots are
                never refused by anything; obtain `Topology` from a `Part` instead.
            part_com_object: The raw Part being searched. Searches are refused unless it
                is the active Part, because `Selection.Search` acts on the active editor.
            body_target: Returns the raw body of the `part.work_in(body)` context that is
                open, or `None` outside one. A snapshot taken inside a work context covers
                that body, matching where sketches and features go.
            resolve_body: Turns whatever a caller passes as `body` into a raw `Body` COM
                object. `part.topology` supplies `part.bodies.get` for names; without it,
                a wrapper is unwrapped through `com_object` and anything else is used
                as-is.
            measurer: The `GeometryMeasurer` every edge and face measures itself with,
                on demand. `part.topology` supplies one built from the Part's editor;
                without it, `geometry` on a snapshot element raises.
        """
        self._selection = selection
        self._part_com_object = part_com_object
        self._generation = generation if generation is not None else ModelGeneration()
        self._body_target = body_target
        self._resolve_body = resolve_body
        self._measurer = measurer

    def _scope(self, body: Any) -> Any:
        """Returns the raw body a snapshot should be restricted to, or `None`.

        Args:
            body: `WORK_BODY` (the default) to follow the open work context, `None`
                for the whole Part, or a `Body`, a body name, or a raw body.

        Returns:
            The raw `Body` COM object to search inside, or `None` for the whole Part.

        Raises:
            BodyNotFoundError: If a name does not match a body of this Part.
            Auto3dxError: If resolving the body failed.
        """
        if body is WORK_BODY:
            return self._body_target() if self._body_target is not None else None
        if body is None:
            return None
        if self._resolve_body is not None:
            body = self._resolve_body(body)
        return getattr(body, "com_object", body)

    def edges(self, body: Any = WORK_BODY) -> EdgeSnapshot:
        """Takes a fresh snapshot of edges, by default of the whole Part's solid.

        A Part-wide search returns the edges of every body in one flat list, so an edge
        of one body can easily be handed to a feature being built in another. Pass
        `body` to search inside one body instead, and note that every `Edge` carries
        `owner_body_name` either way; `PartDesign` refuses an edge from the wrong body
        (`CrossBodyReferenceError`).

        This is read-only: it does not advance the model generation, and the user's
        CATIA selection is restored afterwards.

        Args:
            body: A `Body`, a body name, or a raw body to search inside. Defaults to the
                body of the open `part.work_in(body)` context, or the whole Part when
                there is none. Pass `None` for the whole Part inside a work context.

        Returns:
            An `EdgeSnapshot` stamped with the current generation.

        Raises:
            ValidationError: If no editor selection is available.
            BodyNotFoundError: If `body` names a body this Part does not have.
            AutomationError: If the current selection cannot be read (nothing is
                changed), or the search fails.

        Warns:
            SelectionNotRestoredWarning: If the selection did not fully come back.
                The snapshot is still valid.
        """
        return take_edge_snapshot(
            self._selection,
            self._generation.value,
            self._part_com_object,
            self._scope(body),
            self._measurer,
            self._generation,
        )

    def faces(self, body: Any = WORK_BODY) -> FaceSnapshot:
        """Takes a fresh snapshot of faces, by default of the whole Part's solid.

        Scoping works exactly as for `edges`, and every `Face` carries the body it was
        found in.

        This is read-only: it does not advance the model generation, and the user's
        CATIA selection is restored afterwards.

        Args:
            body: A `Body`, a body name, or a raw body to search inside. Defaults to the
                body of the open `part.work_in(body)` context, or the whole Part when
                there is none. Pass `None` for the whole Part inside a work context.

        Returns:
            A `FaceSnapshot` stamped with the current generation.

        Raises:
            ValidationError: If no editor selection is available.
            BodyNotFoundError: If `body` names a body this Part does not have.
            AutomationError: If the current selection cannot be read (nothing is
                changed), or the search fails.

        Warns:
            SelectionNotRestoredWarning: If the selection did not fully come back.
                The snapshot is still valid.
        """
        return take_face_snapshot(
            self._selection,
            self._generation.value,
            self._part_com_object,
            self._scope(body),
            self._measurer,
            self._generation,
        )

    def __repr__(self) -> str:
        """str: Debug representation; does not contact CATIA."""
        return f"Topology(generation={self._generation.value})"
