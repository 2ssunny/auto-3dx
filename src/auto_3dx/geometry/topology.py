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
"""

from typing import Any

from auto_3dx._generation import ModelGeneration
from auto_3dx.geometry.edges import EdgeSnapshot, take_edge_snapshot
from auto_3dx.geometry.faces import FaceSnapshot, take_face_snapshot


class Topology:
    """Takes edge and face snapshots of a Part's solid.

    Obtain it as `part.topology`, so its snapshots share the Part's generation.
    """

    def __init__(self, selection: Any, generation: ModelGeneration | None = None) -> None:
        """Initializes the namespace.

        Args:
            selection: The raw CATIA `Selection` COM object of the editor editing
                the Part. The search runs through it.
            generation: The owning Part's model generation. A standalone instance
                gets its own, which no other wrapper shares, so its snapshots are
                never refused by anything; obtain `Topology` from a `Part` instead.
        """
        self._selection = selection
        self._generation = generation if generation is not None else ModelGeneration()

    def edges(self) -> EdgeSnapshot:
        """Takes a fresh snapshot of every edge of the solid.

        This is read-only: it does not advance the model generation.

        Returns:
            An `EdgeSnapshot` stamped with the current generation.

        Raises:
            Auto3dxError: If no editor selection is available, or the search
                fails unexpectedly.
        """
        return take_edge_snapshot(self._selection, self._generation.value)

    def faces(self) -> FaceSnapshot:
        """Takes a fresh snapshot of every face of the solid.

        This is read-only: it does not advance the model generation.

        Returns:
            A `FaceSnapshot` stamped with the current generation.

        Raises:
            Auto3dxError: If no editor selection is available, or the search
                fails unexpectedly.
        """
        return take_face_snapshot(self._selection, self._generation.value)

    def __repr__(self) -> str:
        """str: Debug representation; does not contact CATIA."""
        return f"Topology(generation={self._generation.value})"
