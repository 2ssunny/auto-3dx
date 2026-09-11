"""Probe whether a FACE reference unlocks shell, thickness and hole.

Edge references are solved: `Selection.Search("Topology.Edge,all")` plus
`SelectedElement.Reference` gives a reference that a constant-radius fillet and
a chamfer both accept, created and updated (`docs/conventions.md` 1.2.2.2).
Faces enumerate the same way -- `Search("Topology.Face,all")` returned 9
`PlanarFace` hits on a two-pad body -- but a face reference was rejected by
fillet and chamfer, which is unsurprising: those want an edge.

The features that genuinely want a FACE have never been tried with one, because
until the edge work there was no way to obtain any topology reference at all.
Their signatures, from `D8431606-E4B5-11D1-A5D3-00A0C95752EDx0x0x0.py`:

    AddNewShell(iFaceToRemove, iInternalThickness, iExternalThickness) -> Shell
    AddNewThickness(iFaceToThicken, iOffset) -> Thickness
    AddNewHole(iSupport, iDepth) -> Hole

Each one's first argument is typed `Reference` in the type library, which is
exactly the shape `SelectedElement.Reference` produces. If these work, most of
the remaining blocked feature list opens up with them.

Two rules learned the hard way shape how this probe is written. A feature whose
update fails stays in the tree and makes EVERY later update fail until it is
removed, so each attempt is deleted before the next one begins -- that cascade
is what made an earlier probe look like a list of unrelated failures. And a
reference from a snapshot taken before a modification succeeds or fails
unpredictably, so every attempt takes its own fresh search.

Creates and removes content in the ACTIVE Part. Never saves.
"""

from typing import Any

from auto_3dx import Catia
from auto_3dx.errors import Auto3dxError

PREFIX = "AUTO3DX_P37_"
FACE_QUERY = "Topology.Face,all"
RECTANGLE_SIDE = 40.0
PAD_HEIGHT = 20.0
SHELL_THICKNESS = 2.0
THICKNESS_OFFSET = 3.0
HOLE_DEPTH = 5.0
# How many of the solid's faces to try each feature against. A shell only works
# on a face it can actually open, so one face is not a fair test, but trying all
# of them on every feature would take longer than it is worth.
FACES_TO_TRY = 4


def describe(com_object: Any) -> str:
    """Returns a COM wrapper's type name."""
    return type(com_object).__name__


def search_faces(selection: Any) -> "list[Any]":
    """Returns a fresh `Reference` for each face of the solid.

    `Selection.Search` returns void and mutates the Selection, and
    `Part.CreateReferenceFromObject` fails on a search hit, so the reference
    must come from `SelectedElement.Reference` (`docs/conventions.md` 1.2.2.2).

    Args:
        selection: The editor's raw `Selection` COM object.

    Returns:
        One `Reference` per face, in search order.
    """
    selection.Clear()
    selection.Search(FACE_QUERY)
    references = [selection.Item(index).Reference for index in range(1, selection.Count + 1)]
    selection.Clear()
    return references


def delete_one(selection: Any, com_object: Any) -> None:
    """Deletes one raw COM object through the Selection, tolerating failure.

    `Shapes.Remove` does not exist in this release, so deletion goes through the
    editor's Selection. This runs even for a feature whose update failed: that
    feature is still in the tree, and leaving it there would make every later
    update fail for reasons unrelated to what is being tried.
    """
    try:
        selection.Clear()
        selection.Add(com_object)
        selection.Delete()
        selection.Clear()
    except Exception as error:  # noqa: BLE001 - cleanup must not stop the probe
        print(f"      could not delete {describe(com_object)}: {str(error)[:70]}")


def try_feature(part: Any, selection: Any, label: str, build: Any) -> bool:
    """Builds one face feature on a fresh face reference, then removes it again.

    Args:
        part: The `Part` wrapper.
        selection: The editor's raw `Selection` COM object.
        label: What is being tried, for the printed line.
        build: Takes one face `Reference` and returns the created COM object.

    Returns:
        `True` if the feature was created AND `Part.Update()` succeeded, which
        is this project's bar for verified.
    """
    faces = search_faces(selection)
    if not faces:
        print(f"  {label}: no faces found")
        return False
    verified = False
    for position in range(min(FACES_TO_TRY, len(faces))):
        # A fresh search per attempt: the previous attempt's deletion changed
        # the model, and a stale reference then works or fails unpredictably.
        faces = search_faces(selection)
        try:
            feature = build(faces[position])
        except Exception as error:  # noqa: BLE001 - probing the real failure mode
            print(f"  {label} face {position}: create FAILED {str(error)[:70]}")
            continue
        try:
            part.update()
        except Auto3dxError as error:
            print(f"  {label} face {position}: created, update FAILED {str(error)[:50]}")
        else:
            print(f"  {label} face {position}: created AND update OK -> VERIFIED")
            print(f"      wrapper type: {describe(feature)}")
            verified = True
        delete_one(selection, feature)
        try:
            part.update()
        except Auto3dxError as error:
            print(f"      update after cleanup failed: {str(error)[:60]}")
        if verified:
            return True
    return False


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
        print(f"faces found: {len(search_faces(selection))}")

        print("--- 1. AddNewShell(face, internal, external) ---")
        try_feature(
            part,
            selection,
            "shell",
            lambda face: factory.AddNewShell(face, SHELL_THICKNESS, 0.0),
        )

        print("--- 2. AddNewThickness(face, offset) ---")
        try_feature(
            part,
            selection,
            "thickness",
            lambda face: factory.AddNewThickness(face, THICKNESS_OFFSET),
        )

        print("--- 3. AddNewHole(face, depth) ---")
        try_feature(
            part,
            selection,
            "hole",
            lambda face: factory.AddNewHole(face, HOLE_DEPTH),
        )
    finally:
        print("--- cleanup ---")
        if pad is not None:
            try:
                part.part_design.remove_pad(pad_name)
            except Auto3dxError as error:
                print(f"  pad not removed: {str(error)[:80]}")
        try:
            part.sketches.remove(sketch_name)
        except Auto3dxError:
            pass
        try:
            part.update()
        except Auto3dxError as error:
            print(f"  final update failed: {str(error)[:80]}")
        print(f"  shapes: {body.Shapes.Count} | sketches: {body.Sketches.Count}")
        print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
