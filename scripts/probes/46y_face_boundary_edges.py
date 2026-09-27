"""Probe 46y: with one face selected, does `Search("Topology.Edge,sel")` return its boundary?

One question only. Selecting a body and searching `Topology.Edge,sel` is verified to
return that body's edges (probe 42). Whether the same scoping works with a single FACE
selected has never been run. Fixture: the 60x40x20 block, rebuilt. The top face and a
Part-wide edge snapshot come from the verified SDK paths. Then, each call marked:
`Selection.Clear`, `Selection.Add(top face Reference)`, `Selection.Search(
"Topology.Edge,sel")`, `Selection.Count`, `Item(i).Reference.DisplayName` per hit,
`Selection.Clear`. The top face of a block has exactly four boundary edges, all at z = 20.
The selection was empty before the probe and is left empty.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46y_face_boundary_edges.py
"""

from _micro import (
    block_fixture, delete, marker, planar_face, require_blank_target, step, sweep,
    update_if_needed, verify_blank,
)

PREFIX = "AUTO3DX_P46Y"


def main() -> None:
    catia, part = require_blank_target()
    pad = None
    try:
        pad, _ = block_fixture(part, f"{PREFIX}_BLOCK")
        top = planar_face(part, (0, 0, 1), (0, 0, 1))
        edges = step("[composite, verified] part.topology.edges(body=None)",
                     lambda: part.topology.edges(body=None))
        by_name = {edge.descriptor: edge for edge in edges}
        marker(f"[INFO] Part-wide edges: {len(edges)}")
        selection = step("Editor.Selection", lambda: catia.active_editor().Selection)
        step("Selection.Count (before)", lambda: int(selection.Count))
        step("Selection.Clear", selection.Clear)
        step("Selection.Add(top face Reference)", lambda: selection.Add(top.com_object))
        step("Selection.Search('Topology.Edge,sel')",
             lambda: selection.Search("Topology.Edge,sel"), fatal=False)
        count = step("Selection.Count", lambda: int(selection.Count), fatal=False) or 0
        names = []
        for index in range(1, count + 1):
            reference = step(f"Selection.Item({index}).Reference",
                             lambda index=index: selection.Item(index).Reference)
            names.append(step("Reference.DisplayName", lambda reference=reference:
                              str(reference.DisplayName)))
        step("Selection.Clear", selection.Clear)
        for name in names:
            edge = by_name.get(name)
            where = f"mid {edge.geometry.mid_mm}" if edge is not None else "NOT in the snapshot"
            marker(f"[RESULT] boundary edge {name[:70]} -> {where}")
        marker(f"[RESULT] {len(names)} hits; the top face has 4 boundary edges at z = 20")
    finally:
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        sweep(catia, part, PREFIX)
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
