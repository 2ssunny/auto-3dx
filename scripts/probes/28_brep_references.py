"""Probe a durable way to name a face/edge, without a hand-written BRep string.

BACKGROUND (`docs/conventions.md` 1.2.2/1.2.2.1, `docs/status.md` 2.2,
`scripts/probes/17_references.py`): about 80 `ShapeFactory.AddNew*` methods
(fillet, chamfer, shell, thickness, draft, hole, ...) take a face or an edge,
and the only known way to name one is a BRep string such as
``FSur:(Face:(Brp:(Pad.1;2);None:();Cf11:()))``, which breaks on rebuild.
Probe 17 already showed:

    - `Part.CreateReferenceFromObject(a_whole_feature)` succeeds and returns a
      `Reference`, but feeding that feature-level `Reference` to
      `AddNewEdgeFilletWithConstantRadius`/`AddNewChamfer` fails for every
      propagation mode tried (0, 1, 2) -- CATIA wants a real edge/face object,
      not a feature.
    - `AddNewMirror` accepts a whole addressable object (an origin plane)
      with no BRep name needed, because a plane -- unlike a face or an edge
      of a solid -- is already independently addressable.
    - `CreateReferenceFromBRepName` was not actually exercised against a real
      face; probe 17 only asserted that a fabricated string exists.

This probe does NOT repeat those experiments. It goes one level further and
asks whether `Editor.Selection.Search` can enumerate the faces/edges of a
body directly, which -- if the returned objects are usable as fillet/chamfer
arguments -- would let library code select "face 3 of Pad.1" without ever
building a BRep string.

TYPE LIBRARY SIGNATURES (verified, not guessed; extracted from the pywin32
`gen_py` cache at `C:\\Users\\ssunn\\AppData\\Local\\Temp\\gen_py\\3.13`,
B428_Cloud install). Every signature below is quoted verbatim from the
generated wrapper source (argument names and order as generated); the COM
VARIANT type codes from the matching `vtableFuncs`/`propMap` entries are
noted in brackets: 9=VT_DISPATCH, 3=VT_I4 (plain long, no enum info in the
type library), 5=VT_R8 (double), 8=VT_BSTR, 11=VT_BOOL, 24=VT_VOID.

File `0D90A5C9-3B08-11D1-A26C-0000F87546FDx0x0x0.py` (the core Part/geometry
interfaces -- this is where `Part`, `Body`, `Face`, `Edge`, ... live):

    class Part:
        def CreateReferenceFromBRepName(self, iLabel, iObjectContext): ...  # -> Reference
        def CreateReferenceFromGeometry(self, iObject): ...                 # -> Reference
        def CreateReferenceFromName(self, iLabel): ...                      # -> Reference
        def CreateReferenceFromObject(self, iObject): ...                   # -> Reference
        def FindObjectByName(self, iObjName): ...                          # -> CATBaseDispatch

    class Body:
        # readable: Application, HybridBodies, HybridShapes, InBooleanOperation,
        #           Name, OrderedGeometricalSets, Parent, Shapes, Sketches
        # NOTE: no `Faces` / `Edges` collection exists on Body. There is no
        # verified way to enumerate topology except through Selection.

    class Face(DispatchBaseClass):          # CLSID {0DD02330-1BE1-11D6-8060-0010B5D44AB2}
        def ComposeWith(self, iReference): ...   # -> Reference   [9,1]
        def GetItem(self, IDName): ...
        # readable: Application, DisplayName [BSTR, read-only], Name [BSTR, r/w], Parent

    class Edge(DispatchBaseClass):          # CLSID {24E09FB0-1BE1-11D6-8060-0010B5D44AB2}
        # identical shape to Face: ComposeWith, GetItem, DisplayName, Name (r/w), Parent

    class PlanarFace(DispatchBaseClass):    # CLSID {1B7551D0-1BE1-11D6-8060-0010B5D44AB2}
        # same as Face, plus GetFirstAxis/GetOrigin/GetSecondAxis(oAxis: SAFEARRAY)

    class CylindricalFace(DispatchBaseClass):  # CLSID {29A45170-31F0-11D6-8066-0010B5D44AB2}
        # same as Face, plus GetDirection/GetOrigin(oVector: SAFEARRAY)

    class Vertex(DispatchBaseClass):        # CLSID {48CB0EE0-1BE1-11D6-8060-0010B5D44AB2}
        # same shape as Face/Edge: ComposeWith, DisplayName, Name (r/w)

    class Shape(DispatchBaseClass):         # generic feature wrapper (e.g. Pad, Pocket)
        # readable: Application, Name, Parent only -- NO DisplayName, NO ComposeWith.

IMPORTANT STRUCTURAL FACT this probe's docstring research turned up, which
probe 17 and docs/status.md 2.2 do not mention: `Face`, `Edge`, `PlanarFace`,
`CylindricalFace`, and `Vertex` are all distinct, named COM wrapper classes,
and every one of them exposes exactly the same three members `Reference`
itself exposes: `DisplayName`, a writable `Name`, and `ComposeWith(iReference)
-> Reference`. A feature wrapper (`Shape`, i.e. what `Pad`/`Pocket`/etc. look
like generically) has none of these -- only `Name`. That is a plausible
explanation for why probe 17's feature-level `Reference` did not satisfy
`AddNewEdgeFilletWithConstantRadius`: a `Reference` wrapping a whole *feature*
is not shaped like a `Reference` wrapping a *face or edge*, even though
`type(obj).__name__` calls both "Reference" after `CreateReferenceFromObject`.
This is exactly what step 2 below checks for real geometry.

File `14F197B2-0771-11D1-A5B1-00A0C9575177x0x0x0.py` (Reference/Selection):

    class Reference(DispatchBaseClass):    # CLSID {81799037-B0F2-0000-0280-030D3B000000}
        def ComposeWith(self, iReference): ...   # -> Reference
        def GetItem(self, IDName): ...
        # readable: Application, DisplayName [BSTR, r/o], Name [BSTR, r/w], Parent
        # This is the FULL Reference API. There is no method to read back the
        # BRep string, and no method to convert a Reference back to geometry
        # other than GetItem(name-of-a-sub-element), which was not explored
        # here (out of scope: this probe never needs to decompose a Reference).

    class Selection(DispatchBaseClass):    # CLSID {816AAD14-C5E5-0000-0280-030D3B000000}
        def Add(self, iObject): ...                                    # [9,1] -> void
        def Clear(self): ...                                           # -> void
        def Delete(self): ...                                          # -> void
        def FindObject(self, iObjectType): ...                         # [BSTR,1] -> AnyObject
        def Item(self, iIndex): ...             # 1-based             # -> SelectedElement
        def Item2(self, iIndex): ...                                   # -> SelectedElement
        def Search(self, iStringBSTR): ...                             # [BSTR,1] -> VOID (24)
        def SelectElement/SelectElement2/SelectElement3/SelectMultipleElements(...): ...
        def IndicateOrSelectElement2D/3D(...): ...
        # readable: Application, Count, Count2, Name, Parent, Selection, VisProperties

      `Search`'s COM return type is VT_VOID (24), not a count and not a list
      of hits. It cannot return anything -- it must instead mutate the
      Selection object itself, the same way SelectElement* does interactively.
      So the verified usage is: `selection.Clear()`, `selection.Search(query)`,
      then read `selection.Count` / `selection.Item(i)` to see what matched.
      This was NOT already established by probe 17, which never called
      `Search` at all.

      `SelectElement*`/`IndicateOrSelectElement*` are interactive (they show a
      CATIA prompt and block for a user pick); they cannot be used headlessly
      and are not attempted here.

    class SelectedElement(DispatchBaseClass):  # CLSID {6EF9EAD4-7378-11D4-85B4-00508B675233}
        def GetCoordinates(self, ioPoint): ...
        def GetItem(self, IDName): ...
        # readable: Application, LeafProduct, Name, Parent,
        #           Reference   [-> Reference, directly!]
        #           Type        [BSTR, e.g. the kind CATIA reports for the hit]
        #           Value       [-> CATBaseDispatch, the actual selected object;
        #                        this is also the default property]

      `SelectedElement.Reference` is the second, more direct route this probe
      tests: if `Search` populates the Selection with real topology, each
      `SelectedElement` already carries a ready-made `Reference` with no call
      to `Part.CreateReferenceFromObject` needed at all. Both routes are
      tried and compared (step 2).

File `D8431606-E4B5-11D1-A5D3-00A0C95752EDx0x0x0.py` (ShapeFactory / feature
classes):

    class ShapeFactory(DispatchBaseClass):
        def AddNewChamfer(self, iObjectToChamfer, iPropagation, iMode,
                           iOrientation, iLength1, iLength2OrAngle): ...
            # arg types: [9,1] Reference, [3,1] long, [3,1] long, [3,1] long,
            #            [5,1] double, [5,1] double  -> Chamfer
        def AddNewDraft(self, iFaceToDraft, iNeutral, iNeutralMode, iParting,
                         iDirX, iDirY, iDirZ, iMode, iAngle,
                         iMultiselectionMode): ...
            # iFaceToDraft [9,1] Reference, iNeutral [9,1] Reference,
            # iNeutralMode [3,1] long, iParting [9,1] Reference,
            # iDirX/iDirY/iDirZ [5,1] double, iMode [3,1] long,
            # iAngle [5,1] double, iMultiselectionMode [3,1] long -> Draft
            # NOTE: no `AddNewSolidDraft` exists in this type library. The
            # closest matches are `AddNewDraft` (above) and
            # `AddNewVolumicDraft` (adds iType/iVolumeSupport). Not exercised
            # here -- out of scope for this probe (fillet/chamfer only).
        def AddNewEdgeFilletWithConstantRadius(self, iEdgeToFillet,
                                                iPropagMode, iRadius): ...
            # iEdgeToFillet [9,1] Reference, iPropagMode [3,1] long,
            # iRadius [5,1] double -> ConstRadEdgeFillet
        def AddNewShell(self, iFaceToRemove, iInternalThickness,
                        iExternalThickness): ...
            # iFaceToRemove [9,1] Reference, both thicknesses [5,1] double
            # -> Shell
        def AddNewThickness(self, iFaceToThicken, iOffset): ...
            # iFaceToThicken [9,1] Reference, iOffset [5,1] double -> Thickness
        def AddNewMirror(self, iMirroringElement): ...
            # iMirroringElement [9,1] Reference -> Mirror
            # (probe 17 passed a raw OriginElements plane object here, not a
            # Reference, and it worked -- COM auto-boxes a plain object into
            # the Reference-typed slot. That is the one precedent for "does a
            # non-Reference object satisfy a Reference-typed parameter" and it
            # is worth re-testing for Face/Edge objects in step 3 below.)

    class Chamfer / ConstRadEdgeFillet (the objects AddNewChamfer/
    AddNewEdgeFilletWithConstantRadius return):
        Chamfer.Mode / .Orientation / .Propagation      -- plain (3,0) long
        ConstRadEdgeFillet.EdgePropagation               -- plain (3,0) long
        ConstRadEdgeFillet.Radius                        -- Length
        ConstRadEdgeFillet.ObjectsToFillet / .EdgesToKeep -- References
        Both also expose AddElementToChamfer/AddObjectToFillet /
        WithdrawElementToChamfer/WithdrawObjectToFillet for incremental
        multi-selection, not used here.

    AMBIGUITY FLAGGED, NOT GUESSED: none of `iPropagMode`, `iPropagation`,
    `iMode`, `iOrientation`, `EdgePropagation`, `Chamfer.Mode`, or
    `Chamfer.Orientation` carries an attached enum type in the type library
    (their COM type is plain VT_I4, IID column is `None`). CATIA's public
    scripting reference names these `CatFilletEdgePropagation` /
    `CatChamferMode` / `CatChamferOrientation` externally, but that mapping
    is NOT present in this generated wrapper, so this probe tries the same
    small integer set probe 17 already tried (0, 1, 2 for propagation; 1, 0,
    1 for chamfer mode/orientation) without asserting what those integers
    mean. If a run reports success for a given resolved reference, that
    tells us whether references are viable at all; it does NOT confirm which
    integer means "propagate to all tangent edges" vs. "this edge only".

APPROACHES TRIED, IN ORDER (each guarded by `attempt()`; nothing here stops
the probe or raises past the `finally` block):

    1. `Selection.Search` with several CATIA query strings, to see whether
       any of them enumerate the pad's own faces/edges and what wrapper type
       (`Face`, `Edge`, `PlanarFace`, `AnyObject`, ...) each hit resolves to.
    2. For every object obtained in step 1: (a) call
       `Part.CreateReferenceFromObject` on it directly, and (b) read
       `SelectedElement.Reference` from the same search hit -- reporting the
       resulting wrapper type and `DisplayName`/`Name` for both, so the two
       routes can be compared.
    3. Feed the references from step 2 to `AddNewEdgeFilletWithConstantRadius`
       and `AddNewChamfer`, then call `Part.Update()` and report SUCCEEDED or
       FAILED for the update specifically -- creation succeeding is not
       treated as proof of anything (`docs/conventions.md` 1.2.2.1,
       `docs/status.md` 2.8: `AddNew*` succeeding does not mean the feature is
       valid).
    4. Only if step 3 produces an updatable fillet: read that reference's
       `Name`/`DisplayName`, remove nothing, re-run the same `Search` that
       found it, and report whether the same name comes back. That is the
       actual question behind the fragility -- can a reference obtained this
       way be stored and looked up again later, or does it only work in the
       instant it was produced.

By default this probe only prints instructions. Pass ``--run`` to opt in.
Everything it creates is prefixed `AUTO3DX_P28_` and is removed in a
`finally` block via the library's own removal methods
(`part.part_design.remove_pad`, `part.sketches.remove`) for the pad/sketch,
and via `Editor.Selection` (`auto_3dx.geometry.deletion` pattern) for the raw
fillet/chamfer COM objects this probe creates directly through
`ShapeFactory`, which the library does not yet wrap. Nothing here calls
`Save()` or `PLMPropagate()`.
"""

import argparse
from typing import Any

from auto_3dx import Catia, Part

SKETCH_NAME = "AUTO3DX_P28_SKETCH"
PAD_NAME = "AUTO3DX_P28_PAD"
PAD_HEIGHT = 20.0
FILLET_RADIUS = 2.0
CHAMFER_LENGTH = 1.5
CHAMFER_ANGLE = 45.0

# Search strings to try against Editor.Selection. None of these is verified
# CATIA syntax -- that is exactly what this probe is finding out. They are
# ordered from "most likely to be real CATIA query grammar" to "long shots".
SEARCH_QUERIES = [
    "Face,all",
    "Edge,all",
    "Topology.Face,all",
    "Topology.Edge,all",
    f"Face,in,{PAD_NAME}",
    f"Edge,in,{PAD_NAME}",
    "Face,sel",
    "Edge,sel",
    "CATPrtSearch.Face,all",
]

# Propagation / mode / orientation integers to try, per the ambiguity noted
# in the module docstring: the type library gives no enum names for these.
FILLET_PROPAGATION_MODES = (1, 0, 2)
CHAMFER_ARGS = (1, 0, 1)  # (iPropagation, iMode, iOrientation)


def _parse_args() -> argparse.Namespace:
    """Parses the explicit mutation opt-in without connecting to CATIA."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        action="store_true",
        help="opt in to temporary Pad, fillet, and chamfer experiments",
    )
    return parser.parse_args()


def _capture_selection(selection: Any) -> "tuple[Any, ...]":
    """Captures the values in the active editor's Selection."""
    values: list[Any] = []
    for index in range(1, int(selection.Count) + 1):
        values.append(selection.Item(index).Value)
    return tuple(values)


def _restore_selection(selection: Any, values: "tuple[Any, ...]") -> None:
    """Restores values captured before the probe changed Selection."""
    selection.Clear()
    for value in values:
        selection.Add(value)


def describe(com_object: Any) -> str:
    """Returns a COM wrapper's type name."""
    return type(com_object).__name__


def attempt(label: str, action: Any) -> Any:
    """Runs one experiment and reports the outcome without stopping the probe."""
    try:
        result = action()
    except Exception as error:  # noqa: BLE001 - probing the real failure mode
        message = str(error)
        print(f"  {label}: FAILED {type(error).__name__}: {message[:160]}")
        return None
    print(f"  {label}: OK -> {describe(result)}")
    return result


def _print_readable(label: str, com_object: Any, attributes: "list[str]") -> None:
    """Prints a handful of readable attributes for one COM object, tolerating gaps."""
    for attribute_name in attributes:
        try:
            value = getattr(com_object, attribute_name)
        except Exception as error:  # noqa: BLE001 - probing availability
            print(f"    {label}.{attribute_name} -> FAILED {type(error).__name__}")
            continue
        print(f"    {label}.{attribute_name} = {value!r}")


def _run_search(selection: Any, query: str) -> "list[Any]":
    """Runs one Selection.Search query and returns the SelectedElement hits.

    `Selection.Search` returns VT_VOID -- it mutates the Selection itself,
    so the hits are read back afterward via `Count`/`Item(i)`.
    """
    selection.Clear()
    selection.Search(query)
    count = selection.Count
    hits = [selection.Item(index) for index in range(1, count + 1)]
    return hits


def _try_update(part: Any, label: str) -> bool:
    """Calls `Part.Update()`, prints OK/FAILED, and returns whether it succeeded.

    `Part.Update()` returns `None` on success just as much as `attempt()`
    reports `None` after catching an exception, so the two cannot be told
    apart by return value alone -- this helper prints and returns a real
    bool instead of layering `attempt()` on top of another success check.
    """
    try:
        part.update()
    except Exception as error:  # noqa: BLE001 - report, do not stop the probe
        print(f"  {label}: FAILED {type(error).__name__}: {str(error)[:160]}")
        return False
    print(f"  {label}: OK")
    return True


def main() -> None:
    """Runs the probe against the active Part."""
    args = _parse_args()
    if not args.run:
        print("No mutation performed. Re-run with --run to probe BRep references.")
        print("Document save: NOT CALLED")
        print("PLMPropagate: NOT CALLED")
        return

    catia = Catia.attach()
    editor = catia.active_editor()
    raw = editor.ActiveObject
    if type(raw).__name__ != "Part":
        raise RuntimeError(
            "The active editor is not editing a Part; "
            f"ActiveObject is {type(raw).__name__}."
        )
    selection = editor.Selection
    original_selection = _capture_selection(selection)
    part = Part(raw, selection=selection, editor=editor)
    body = raw.MainBody
    factory = raw.ShapeFactory

    print("Part:", part.name)
    print("shapes before:", body.Shapes.Count, "| sketches before:", body.Sketches.Count)

    created_feature_com_objects: "list[Any]" = []
    pad_created = False
    sketch_created = False

    try:
        print()
        print("--- setup: a pad this probe owns ---")
        sketch = part.sketches.create(SKETCH_NAME, support="XY")
        sketch_created = True
        with sketch.edit() as editor:
            editor.rectangle(20.0, 15.0, origin_x=0.0, origin_y=0.0)
        part.update()
        pad = part.part_design.create_pad(PAD_NAME, sketch, PAD_HEIGHT)
        pad_created = True
        part.update()
        print(f"  pad: {pad.name}  height={pad.height}")
        print("  shapes now:", body.Shapes.Count)

        print()
        print("--- 1. Selection.Search: can a query enumerate faces/edges? ---")
        search_hits: "dict[str, list[Any]]" = {}
        for query in SEARCH_QUERIES:

            def run(q: str = query) -> "list[Any]":
                hits = _run_search(selection, q)
                if not hits:
                    raise RuntimeError("Search ran but matched nothing")
                return hits

            hits = attempt(f"Search({query!r})", run)
            if hits:
                search_hits[query] = hits
                print(f"    {len(hits)} hit(s); wrapper types:")
                for selected_element in hits[:5]:
                    try:
                        value = selected_element.Value
                        element_type = selected_element.Type
                    except Exception as error:  # noqa: BLE001 - probing availability
                        print(f"      FAILED reading hit: {type(error).__name__}")
                        continue
                    print(f"      Type={element_type!r} Value wrapper={describe(value)}")
        selection.Clear()

        if not search_hits:
            print("  No search query matched anything; steps 2-4 have nothing to work with.")

        print()
        print("--- 2. turning a search hit into a Reference, two ways ---")
        references: "list[tuple[str, Any]]" = []
        for query, hits in search_hits.items():
            for selected_element in hits[:3]:
                try:
                    value = selected_element.Value
                except Exception:  # noqa: BLE001 - already reported in step 1
                    continue
                label_a = f"CreateReferenceFromObject({query!r} hit, {describe(value)})"
                reference_a = attempt(label_a, lambda v=value: raw.CreateReferenceFromObject(v))
                if reference_a is not None:
                    _print_readable("reference_a", reference_a, ["DisplayName", "Name"])
                    references.append((f"{query} via CreateReferenceFromObject", reference_a))

                label_b = f"SelectedElement.Reference ({query!r} hit, {describe(value)})"
                reference_b = attempt(label_b, lambda se=selected_element: se.Reference)
                if reference_b is not None:
                    _print_readable("reference_b", reference_b, ["DisplayName", "Name"])
                    references.append((f"{query} via SelectedElement.Reference", reference_b))

        if not references:
            print("  No reference was obtained from any search hit.")

        print()
        print("--- 3. feeding references to fillet/chamfer, then Part.Update() ---")
        successful_fillet_reference: "tuple[str, Any] | None" = None
        for source_label, reference in references:
            for propagation_mode in FILLET_PROPAGATION_MODES:

                def make_fillet(r: Any = reference, m: int = propagation_mode) -> Any:
                    return factory.AddNewEdgeFilletWithConstantRadius(r, m, FILLET_RADIUS)

                fillet = attempt(
                    f"AddNewEdgeFilletWithConstantRadius({source_label}, mode={propagation_mode})",
                    make_fillet,
                )
                if fillet is None:
                    continue
                created_feature_com_objects.append(fillet)
                update_label = (
                    "Part.Update() after fillet "
                    f"({source_label}, mode={propagation_mode})"
                )
                if _try_update(part, update_label):
                    successful_fillet_reference = (source_label, reference)
                break  # one fillet attempt per reference is enough signal

            propagation, mode, orientation = CHAMFER_ARGS

            def make_chamfer(r: Any = reference) -> Any:
                return factory.AddNewChamfer(
                    r, propagation, mode, orientation, CHAMFER_LENGTH, CHAMFER_ANGLE
                )

            chamfer = attempt(f"AddNewChamfer({source_label})", make_chamfer)
            if chamfer is not None:
                created_feature_com_objects.append(chamfer)
                _try_update(part, f"Part.Update() after chamfer ({source_label})")

        print()
        print("--- 4. does the reference's name survive re-enumeration? ---")
        if successful_fillet_reference is None:
            print("  Skipped: no reference produced a valid, updatable fillet in step 3.")
        else:
            source_label, reference = successful_fillet_reference
            name_before = None
            try:
                name_before = reference.Name
                print(f"  Name before re-enumeration = {name_before!r}")
            except Exception as error:  # noqa: BLE001 - report, do not mask
                print(f"  read Name before re-enumeration: FAILED {type(error).__name__}")
            try:
                print(f"  DisplayName before re-enumeration = {reference.DisplayName!r}")
            except Exception as error:  # noqa: BLE001 - report, do not mask
                print(f"  read DisplayName before re-enumeration: FAILED {type(error).__name__}")
            for query in search_hits:
                rehits = attempt(
                    f"re-run Search({query!r})",
                    lambda q=query: _run_search(selection, q),
                )
                selection.Clear()
                if not rehits:
                    continue
                found_again = False
                for selected_element in rehits:
                    try:
                        candidate_name = selected_element.Reference.Name
                    except Exception:  # noqa: BLE001 - some hits may not resolve
                        continue
                    if candidate_name == name_before:
                        found_again = True
                        break
                print(
                    f"  {query!r}: same reference name reappears -> "
                    f"{found_again} (name_before={name_before!r})"
                )
    finally:
        print()
        print("--- cleanup ---")
        try:
            selection.Clear()
        except Exception as error:  # noqa: BLE001 - report, do not mask
            print(f"  could not clear selection before cleanup: {type(error).__name__}")

        for feature_com_object in reversed(created_feature_com_objects):
            try:
                selection.Clear()
                selection.Add(feature_com_object)
                selection.Delete()
                print(f"  deleted {describe(feature_com_object)}")
            except Exception as error:  # noqa: BLE001 - tolerate already-gone
                print(f"  could NOT delete {describe(feature_com_object)}: {type(error).__name__}")
        try:
            selection.Clear()
        except Exception as error:  # noqa: BLE001 - report, do not mask
            print(f"  could not clear selection after feature cleanup: {type(error).__name__}")

        if pad_created:
            try:
                part.part_design.remove_pad(PAD_NAME)
                print(f"  removed pad {PAD_NAME!r}")
            except Exception as error:  # noqa: BLE001 - tolerate already-gone (cascade)
                print(f"  pad {PAD_NAME!r} cleanup: {type(error).__name__}: {error}")

        if sketch_created:
            try:
                part.sketches.remove(SKETCH_NAME)
                print(f"  removed sketch {SKETCH_NAME!r}")
            except Exception as error:  # noqa: BLE001 - expected once pad cascade-deletes it
                print(f"  sketch {SKETCH_NAME!r} cleanup: {type(error).__name__}: {error}")

        try:
            part.update()
        except Exception as error:  # noqa: BLE001 - report, do not mask
            print(f"  update after cleanup FAILED: {type(error).__name__}: {error}")
        print("  shapes:", body.Shapes.Count, "| sketches:", body.Sketches.Count)
        try:
            _restore_selection(selection, original_selection)
            print("Selection restored.")
        except Exception as error:  # noqa: BLE001 - report UI-state cleanup failure
            print(f"Selection restore failed: {type(error).__name__}: {error}")
        print("Document save: NOT CALLED")
        print("PLMPropagate: NOT CALLED")


if __name__ == "__main__":
    main()
