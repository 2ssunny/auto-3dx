"""Probe 47c: with a face selected by its `Value`, does `Search("Topology.Edge,sel")` return
its boundary edges -- and with an edge selected, `Search("Topology.Face,sel")` its faces?

One question: whether selection-scoped topology search gives true adjacency. Probe 46y
selected the top face by its `Reference` and got 0 hits; 47b checks whether a `Reference`
even lands in the selection. Here the face and the edge are selected by the `Value` their
own search returned. Fixture: the block. Top face: the face hit whose Reference
`DisplayName` belongs to the planar face with the highest centre (measured through the
verified SDK snapshot of the same unchanged model, matched by name within one generation).
Hits are listed by name and matched against the Part-wide snapshots. The top face of a
block has exactly four boundary edges; a top edge has exactly two adjacent faces.

    $env:AUTO3DX_LIVE_PART = "<disposable Part>"
    python -u scripts/probes/47c_face_boundary_by_value.py
"""

from typing import Any

from _micro import (
    block_fixture,
    delete,
    marker,
    require_blank_target,
    step,
    sweep,
    update_if_needed,
    verify_blank,
)

PREFIX = "AUTO3DX_P47C"


def value_named(selection: Any, query: str, name: str) -> Any:
    """Runs one search and returns the Value of the hit whose Reference has `name`."""
    step("Selection.Clear", selection.Clear)
    step(f"Selection.Search({query!r})", lambda: selection.Search(query))
    count = step("Selection.Count", lambda: int(selection.Count))
    for index in range(1, count + 1):
        item = step(f"Item({index})", lambda index=index: selection.Item(index))
        if (
            step("Item.Reference.DisplayName", lambda item=item: str(item.Reference.DisplayName))
            == name
        ):
            return step("Item.Value", lambda item=item: item.Value)
    return None


def scoped(selection: Any, value: Any, query: str) -> "list[str]":
    step("Selection.Clear", selection.Clear)
    step("Selection.Add(Value)", lambda: selection.Add(value))
    step("Selection.Count after Add", lambda: int(selection.Count))
    step(f"Selection.Search({query!r})", lambda: selection.Search(query), fatal=False)
    count = step("Selection.Count", lambda: int(selection.Count), fatal=False) or 0
    names = [
        step(
            f"Item({index}).Reference.DisplayName",
            lambda index=index: str(selection.Item(index).Reference.DisplayName),
        )
        for index in range(1, count + 1)
    ]
    step("Selection.Clear", selection.Clear)
    return names


def main() -> None:
    catia, part = require_blank_target()
    pad = None
    selection = step("Editor.Selection", lambda: catia.active_editor().Selection)
    try:
        pad, _ = block_fixture(part, f"{PREFIX}_BLOCK")
        faces = step(
            "[composite, verified] topology.faces(body=None)",
            lambda: part.topology.faces(body=None),
        )
        edges = step(
            "[composite, verified] topology.edges(body=None)",
            lambda: part.topology.edges(body=None),
        )
        top = faces.query().planar().normal_parallel((0, 0, 1)).extreme((0, 0, 1)).one()
        top_edge = (
            edges.query().lines().parallel((1, 0, 0)).extreme((0, 0, 1)).extreme((0, 1, 0)).one()
        )
        edge_mid = {edge.descriptor: edge.geometry.mid_mm for edge in edges}
        face_centre = {face.descriptor: face.geometry.center_mm for face in faces}

        face_value = value_named(selection, "Topology.Face,all", top.descriptor)
        marker(f"[INFO] top face value found: {face_value is not None}")
        if face_value is not None:
            names = scoped(selection, face_value, "Topology.Edge,sel")
            for name in names:
                marker(
                    f"[RESULT] face->edge {name[:60]} mid {edge_mid.get(name, 'NOT IN SNAPSHOT')}"
                )
            marker(f"[RESULT] face->edges: {len(names)} (a block's top face has 4)")

        edge_value = value_named(selection, "Topology.Edge,all", top_edge.descriptor)
        marker(f"[INFO] top edge value found: {edge_value is not None}")
        if edge_value is not None:
            names = scoped(selection, edge_value, "Topology.Face,sel")
            for name in names:
                marker(
                    f"[RESULT] edge->face {name[:60]} centre {face_centre.get(name, 'NOT IN SNAPSHOT')}"
                )
            marker(f"[RESULT] edge->faces: {len(names)} (a block edge has 2)")
    finally:
        step("Selection.Clear", selection.Clear, fatal=False)
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        sweep(catia, part, PREFIX)
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
