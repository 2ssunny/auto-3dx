"""Probe how to scope an edge search, and what integers a chamfer needs.

Probe 34 settled the question probe 28 left open. Three fillets in a row, each
from its own fresh search, all created and updated; and two fillets from ONE
shared search also both updated. So a captured edge reference does NOT go stale
after a modification, and probe 28's cascade of update failures had another
cause: its loop tried a chamfer, that chamfer's update failed, and the broken
feature was left in the tree, after which every later update failed too. A
failed update poisons the model until the bad feature is deleted.

That leaves two things between here and a usable edge-feature API.

FIRST, scoping. `Search("Topology.Edge,all")` returns every edge of the whole
solid -- 29 on a two-pad body, growing to 41 as fillets were added. A caller
wants "the edges of THIS pad", not an index into a list that renumbers itself
after every operation. Probe 28 found `Search("Face,in,<name>")` fails, but
never tried the `Topology.` prefix with a scope, which is the form that worked
for `all`. This probe sweeps the plausible scoped syntaxes and reports the hit
count for each, so a scope is either found or ruled out.

SECOND, chamfer. The type library gives the parameter list but no enum metadata
for three of its arguments -- they are plain VT_I4 with no IID -- so their valid
values are unknown:

    AddNewChamfer(iObjectToChamfer, iPropagation, iMode, iOrientation,
        iLength1, iLength2OrAngle) -> Chamfer
        (D8431606-E4B5-11D1-A5D3-00A0C95752EDx0x0x0.py)

Probe 28 tried one guessed combination, its update failed, and that failure is
what poisoned the rest of the run. This probe sweeps a small set of combinations
instead, and -- the part probe 28 got wrong -- DELETES the chamfer after every
attempt, successful or not, so each combination starts from a clean model and
one failure cannot be mistaken for many.

Creates and removes content in the ACTIVE Part. Never saves.
"""

import itertools
from typing import Any

from auto_3dx import Catia
from auto_3dx.errors import Auto3dxError

PREFIX = "AUTO3DX_P35_"
RECTANGLE_SIDE = 24.0
PAD_HEIGHT = 14.0
CHAMFER_LENGTH = 1.5
CHAMFER_SECOND = 45.0

# The query that is known to work, plus every scoped form worth trying. CATIA's
# search grammar is not in the type library, so these are candidates, not facts.
EDGE_QUERIES = (
    "Topology.Edge,all",
    "Topology.Edge,sel",
    "Topology.Edge,in",
    f"Topology.Edge,in,{PREFIX}PAD",
    f"Topology.Edge,'{PREFIX}PAD',all",
    f"(Topology.Edge),in,{PREFIX}PAD",
    f"Name={PREFIX}PAD & Topology.Edge,all",
    f"Topology.Edge & Name={PREFIX}PAD,all",
    "Topology.Face,all",
)

# Small, bounded sweep: propagation, mode, orientation. Values beyond these
# would be guessing at a wider range than the results could justify.
CHAMFER_PROPAGATIONS = (0, 1)
CHAMFER_MODES = (0, 1, 2)
CHAMFER_ORIENTATIONS = (0, 1)


def describe(com_object: Any) -> str:
    """Returns a COM wrapper's type name."""
    return type(com_object).__name__


def search_edges(selection: Any, query: str) -> "list[Any]":
    """Returns one `Reference` per hit for a search query.

    Args:
        selection: The editor's raw `Selection` COM object.
        query: The CATIA search string.

    Returns:
        One `Reference` per hit, in search order.

    Raises:
        Exception: Whatever COM raises for an invalid query, so the caller can
            report which syntaxes are rejected.
    """
    selection.Clear()
    selection.Search(query)
    references = [selection.Item(index).Reference for index in range(1, selection.Count + 1)]
    selection.Clear()
    return references


def delete_one(selection: Any, com_object: Any) -> None:
    """Deletes one raw COM object through the Selection, tolerating failure."""
    try:
        selection.Clear()
        selection.Add(com_object)
        selection.Delete()
        selection.Clear()
    except Exception as error:  # noqa: BLE001 - cleanup must not stop the probe
        print(f"      could not delete {describe(com_object)}: {str(error)[:70]}")


def sweep_queries(selection: Any) -> None:
    """Reports the hit count, or the failure, for every candidate query."""
    print("--- 1. which search syntaxes scope an edge search? ---")
    for query in EDGE_QUERIES:
        try:
            hits = search_edges(selection, query)
        except Exception as error:  # noqa: BLE001 - probing the real failure mode
            print(f"  {query!r}: FAILED {type(error).__name__}: {str(error)[:70]}")
            continue
        kinds = sorted({describe(hit) for hit in hits})
        print(f"  {query!r}: {len(hits)} hit(s) {kinds}")


def sweep_chamfer(part: Any, factory: Any, selection: Any) -> None:
    """Tries each chamfer integer combination on a clean model."""
    print("--- 2. which chamfer integers produce a valid feature? ---")
    print("    (the chamfer is deleted after every attempt, so a failed update")
    print("     cannot poison the attempts that follow)")
    combinations = itertools.product(
        CHAMFER_PROPAGATIONS, CHAMFER_MODES, CHAMFER_ORIENTATIONS
    )
    for propagation, mode, orientation in combinations:
        label = f"propagation={propagation} mode={mode} orientation={orientation}"
        edges = search_edges(selection, "Topology.Edge,all")
        if not edges:
            print("  no edges to chamfer")
            return
        try:
            chamfer = factory.AddNewChamfer(
                edges[0],
                propagation,
                mode,
                orientation,
                CHAMFER_LENGTH,
                CHAMFER_SECOND,
            )
        except Exception as error:  # noqa: BLE001 - probing the real failure mode
            print(f"  {label}: create FAILED {type(error).__name__}: {str(error)[:60]}")
            continue
        try:
            part.update()
        except Auto3dxError as error:
            print(f"  {label}: created, update FAILED {str(error)[:60]}")
        else:
            print(f"  {label}: created AND update OK -> VERIFIED")
        delete_one(selection, chamfer)
        try:
            part.update()
        except Auto3dxError as error:
            print(f"      update after cleanup failed: {str(error)[:70]}")


def main() -> None:
    """Runs the probe against the active Part."""
    catia = Catia.attach()
    part = catia.active_part()
    raw = part.com_object
    body = raw.MainBody
    factory = raw.ShapeFactory
    selection = catia.active_editor().Selection

    sketch_name = f"{PREFIX}SKETCH"
    pad_name = f"{PREFIX}PAD"
    if sketch_name in part.sketches:
        print(f"refusing to run: {sketch_name} already exists.")
        return

    shapes_before = body.Shapes.Count
    sketches_before = body.Sketches.Count
    print(f"Part: {part.name}")
    print(f"shapes before: {shapes_before} | sketches before: {sketches_before}")

    pad = None
    try:
        sketch = part.sketches.create(sketch_name, support="XY")
        with sketch.edit() as editor:
            editor.rectangle(RECTANGLE_SIDE, RECTANGLE_SIDE)
        part.update()
        pad = part.part_design.create_pad(pad_name, sketch, PAD_HEIGHT)
        part.update()
        print(f"built {pad_name}")

        sweep_queries(selection)
        sweep_chamfer(part, factory, selection)
    finally:
        print("--- cleanup ---")
        if pad is not None:
            try:
                part.part_design.remove_pad(pad_name)
            except Auto3dxError as error:
                print(f"  pad not removed: {str(error)[:90]}")
        try:
            part.sketches.remove(sketch_name)
        except Auto3dxError:
            pass
        try:
            part.update()
        except Auto3dxError as error:
            print(f"  final update failed: {str(error)[:90]}")
        print(f"  shapes: {body.Shapes.Count} | sketches: {body.Sketches.Count}")
        print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
