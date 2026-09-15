"""Probe whether re-searching edges lets MORE THAN ONE fillet be built.

Probe 28 got the first ever verified edge feature: an edge reference from
`Selection.Search("Topology.Edge,all")` plus `SelectedElement.Reference`, fed to
`AddNewEdgeFilletWithConstantRadius(reference, 1, radius)`, created a fillet
whose `Part.Update()` succeeded. Every later attempt in that run failed at
update. All references in it were captured BEFORE any modification, so the
suspicion was staleness rather than a real limit.

Probe 31 then closed off both durability routes. `CreateReferenceFromBRepName`
fails in every context tried, so a captured BRep name cannot be re-resolved.
And a rebuild changes the whole descriptor set: after one pad height change the
edge count went 20 -> 29 and neither the name multiset nor the search order
survived. `MeasurableService` exposed no length for an edge either, so an edge
cannot be chosen by measured geometry.

What probe 31 did establish is that for an UNCHANGED model the search is exactly
repeatable: same count, same names, same order, twice in a row.

That leaves exactly one question, and the whole shape of a fillet API depends on
it: after building a fillet, does a FRESH search yield references that work
again? If it does, the library can offer edge features as long as it re-searches
between operations and refuses to reuse a snapshot. If it does not, only a
single edge feature per model state is possible, which is barely an API at all.

This probe answers it by contrast. It builds three fillets in a row, each from
its own fresh search, and separately tries two fillets from one shared search.
The two cases differ only in whether the search was repeated.

Creates and removes content in the ACTIVE Part. Never saves.
"""

from typing import Any

from auto_3dx import Catia
from auto_3dx.errors import Auto3dxError

PREFIX = "AUTO3DX_P34_"
EDGE_QUERY = "Topology.Edge,all"
FILLET_RADIUS = 1.0
PROPAGATION_MODE = 1
SEQUENTIAL_FILLETS = 3
RECTANGLE_SIDE = 24.0
PAD_HEIGHT = 14.0


def describe(com_object: Any) -> str:
    """Returns a COM wrapper's type name."""
    return type(com_object).__name__


def search_edge_references(selection: Any) -> "list[Any]":
    """Returns a fresh `Reference` for every edge of the solid.

    `Selection.Search` returns void and mutates the Selection, so the order is
    Clear, Search, then read Count and Item(i). `SelectedElement.Reference` is
    the only route from a search hit to a usable reference: probe 28 showed
    `Part.CreateReferenceFromObject` fails on one.

    Args:
        selection: The editor's raw `Selection` COM object.

    Returns:
        One `Reference` per edge, in search order.
    """
    selection.Clear()
    selection.Search(EDGE_QUERY)
    references: list[Any] = []
    for index in range(1, selection.Count + 1):
        references.append(selection.Item(index).Reference)
    selection.Clear()
    return references


def build_fillet(factory: Any, reference: Any, name: str) -> Any:
    """Creates one constant-radius edge fillet and names it."""
    fillet = factory.AddNewEdgeFilletWithConstantRadius(
        reference, PROPAGATION_MODE, FILLET_RADIUS
    )
    fillet.Name = name
    return fillet


def try_update(part: Any, label: str) -> bool:
    """Updates the Part and reports whether it succeeded.

    `Part.Update()` returns `None` on success, so a helper that reports `None`
    as failure could not tell the two apart -- hence a boolean of its own.

    Args:
        part: The `Part` wrapper.
        label: What is being updated, for the printed line.

    Returns:
        `True` if the update succeeded.
    """
    try:
        part.update()
    except Auto3dxError as error:
        print(f"    update after {label}: FAILED {str(error)[:100]}")
        return False
    print(f"    update after {label}: OK")
    return True


def delete_all(selection: Any, objects: "list[Any]") -> None:
    """Deletes raw COM objects through the Selection, newest first.

    `Shapes.Remove` does not exist in this release, so deletion goes through the
    editor's Selection. Newest first, because a later feature is built on an
    earlier one.

    Args:
        selection: The editor's raw `Selection` COM object.
        objects: The raw COM objects to delete.
    """
    for com_object in reversed(objects):
        try:
            selection.Clear()
            selection.Add(com_object)
            selection.Delete()
        except Exception as error:  # noqa: BLE001 - cleanup must not stop
            print(f"  cleanup: could not delete {describe(com_object)}: {str(error)[:80]}")
    selection.Clear()


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

    fillets: list[Any] = []
    pad = None
    try:
        sketch = part.sketches.create(sketch_name, support="XY")
        with sketch.edit() as editor:
            editor.rectangle(RECTANGLE_SIDE, RECTANGLE_SIDE)
        part.update()
        pad = part.part_design.create_pad(pad_name, sketch, PAD_HEIGHT)
        part.update()
        print(f"built {pad_name}, {RECTANGLE_SIDE} x {RECTANGLE_SIDE} x {PAD_HEIGHT} mm")

        print("--- 1. one fresh search per fillet ---")
        for attempt in range(1, SEQUENTIAL_FILLETS + 1):
            references = search_edge_references(selection)
            print(f"  attempt {attempt}: search found {len(references)} edges")
            if not references:
                print("    no edges to fillet")
                break
            name = f"{PREFIX}FILLET_{attempt}"
            try:
                fillet = build_fillet(factory, references[0], name)
            except Exception as error:  # noqa: BLE001 - probing the failure mode
                print(f"    create: FAILED {type(error).__name__}: {str(error)[:90]}")
                continue
            fillets.append(fillet)
            print(f"    create: OK -> {describe(fillet)}")
            if not try_update(part, name):
                # A failed update leaves the feature in the tree, so it stays in
                # `fillets` for cleanup, and the run stops rather than stacking
                # more features on a broken one.
                break

        print("--- 2. two fillets from ONE shared search (the stale case) ---")
        shared = search_edge_references(selection)
        print(f"  search found {len(shared)} edges; taking two of them")
        for offset in (0, 1):
            if offset >= len(shared):
                break
            name = f"{PREFIX}SHARED_{offset}"
            try:
                fillet = build_fillet(factory, shared[offset], name)
            except Exception as error:  # noqa: BLE001 - probing the failure mode
                print(f"  edge {offset}: create FAILED {type(error).__name__}: {str(error)[:80]}")
                continue
            fillets.append(fillet)
            print(f"  edge {offset}: create OK")
            if not try_update(part, name):
                break
    finally:
        print("--- cleanup ---")
        delete_all(selection, fillets)
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
