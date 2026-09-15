"""Read-only probe gathering live evidence for the future ``part.inspect`` API.

``docs/api-design.md`` section 11 sets the rule this probe exists to serve: every
field of the planned read-only inspection API must be backed by a live-verified
read, and a field CATIA cannot report reliably is absent, not guessed. Section 12
(the measurement lesson) is the reason a call succeeding is never treated as proof
by itself here: an inertia bounding box once returned correct values and later
returned all zeros silently on an unchanged model, so every value this probe
prints is reported plainly, without claiming durability beyond this one run.

This probe is READ-ONLY. It never calls ``Update()``, ``Save()``, or
``PLMPropagate()``, never creates, renames, or deletes anything, and never
changes ``Part.InWorkObject``. It prints "Document save: NOT CALLED" at the end
to make that explicit. Every enumeration is bounded by a named constant, and the
omitted count is printed when a collection is larger than that bound. Console
output is ASCII-only (the console is cp1252; non-ASCII text passed to ``print()``
raises), so every name is sanitised before printing.

Per docs/conventions.md section 1: ``Shapes.Remove`` does not exist in this
release, type identification is done with ``type(obj).__name__``, every COM
collection here is 1-based (``Item(1..Count)``), and the only verified topology
queries are ``Selection.Search("Topology.Edge,all")`` and
``"Topology.Face,all"``.

SELECTION RESTORE is the most important check this probe performs. The SDK's
topology search clears the user's CATIA selection and does not put it back
(``docs/api-design.md`` section 7, "Planned"). This probe captures the exact
selection state before touching it (the same way
``scripts/probes/31_edge_selection.py`` does: ``Selection.Item(i).Value`` for
each item), refuses to run any search at all if that capture cannot be trusted,
and restores the selection in a ``finally`` block so a failure part way through
still puts it back. If the selection is EMPTY when the probe starts, restoring a
NON-EMPTY selection is not exercised by this run: the printed instruction tells
the operator to select one or two tree features and run the probe again.

Every generated pywin32 signature this probe calls is quoted below, verbatim,
with the source file it came from. Nothing is called that was not found there.
Both files live under
``C:\\Users\\ssunn\\AppData\\Local\\Temp\\gen_py\\3.13\\``.

From ``0D90A5C9-3B08-11D1-A26C-0000F87546FDx0x0x0.py`` (MechanicalModeler):

    class Bodies(DispatchBaseClass):
        def Add(self): ...                                  # -> Body
        def GetItem(self, IDName=defaultNamedNotOptArg): ... # -> CATBaseDispatch
        def Item(self, iIndex=defaultNamedNotOptArg): ...    # -> Body
        # props: Application, Count, Name, Parent

    class Body(DispatchBaseClass):
        def GetItem(self, IDName=defaultNamedNotOptArg): ... # -> CATBaseDispatch
        def InsertHybridShape(self, iHybridShape=defaultNamedNotOptArg): ...
        # props: Application, HybridBodies -> HybridBodies, HybridShapes -> HybridShapes,
        #        InBooleanOperation, Name (r/w), OrderedGeometricalSets, Parent,
        #        Shapes -> Shapes, Sketches -> Sketches

    class HybridBodies(DispatchBaseClass):
        def Add(self): ...                                  # -> HybridBody
        def GetItem(self, IDName=defaultNamedNotOptArg): ... # -> CATBaseDispatch
        def Item(self, iIndex=defaultNamedNotOptArg): ...    # -> HybridBody
        # props: Application, Count, Name, Parent

    class HybridBody(DispatchBaseClass):
        def AppendHybridShape(self, iHybridShape=defaultNamedNotOptArg): ...
        def GetItem(self, IDName=defaultNamedNotOptArg): ... # -> CATBaseDispatch
        # props: Application, Bodies -> Bodies, GeometricElements -> GeometricElements,
        #        HybridBodies -> HybridBodies (nested sets), HybridShapes -> HybridShapes,
        #        HybridSketches -> Sketches, Name (r/w), Parent

    class HybridShapes(DispatchBaseClass):
        def GetBoundary(self, iLabel=defaultNamedNotOptArg): ...  # -> Boundary
        def GetItem(self, IDName=defaultNamedNotOptArg): ...      # -> CATBaseDispatch
        def Item(self, iIndex=defaultNamedNotOptArg): ...         # -> HybridShape
        # props: Application, Count, Name, Parent

    class Shapes(DispatchBaseClass):
        def GetBoundary(self, iLabel=defaultNamedNotOptArg): ...  # -> Boundary
        def GetItem(self, IDName=defaultNamedNotOptArg): ...      # -> CATBaseDispatch
        def Item(self, iIndex=defaultNamedNotOptArg): ...         # -> Shape
        # props: Application, Count, Name, Parent

    class Sketches(DispatchBaseClass):
        def Add(self, iPlane=defaultNamedNotOptArg): ...          # -> Sketch
        def GetBoundary(self, iLabel=defaultNamedNotOptArg): ...  # -> Boundary
        def GetItem(self, IDName=defaultNamedNotOptArg): ...      # -> CATBaseDispatch
        def Item(self, iIndex=defaultNamedNotOptArg): ...         # -> Sketch
        # props: Application, Count, Name, Parent

    class Part(DispatchBaseClass):
        def IsUpToDate(self, iObject=defaultNamedNotOptArg): ...  # -> VT_BOOL
        def Update(self): ...
        # props (read): AnnotationSets, Application, AxisSystems, Bodies -> Bodies,
        #        Constraints, Density, GeometricElements, HybridBodies -> HybridBodies,
        #        HybridShapeFactory, InWorkObject -> AnyObject (r/w),
        #        MainBody -> Body (r/w), Name (r/w), OrderedGeometricalSets,
        #        OriginElements, Parameters -> Parameters, Parent, Relations,
        #        ShapeFactory, UserSurfaces

From ``0770412C-722E-11D2-8378-0060941974FFx0x0x0.py`` (KnowledgeItf):

    class Parameters(DispatchBaseClass):
        def GetItem(self, IDName=defaultNamedNotOptArg): ...      # -> CATBaseDispatch
        def Item(self, iIndex=defaultNamedNotOptArg): ...         # -> Parameter
        # props: Application, Count, Name, Parent,
        #        RootParameterSet -> ParameterSet, Units

    class ParameterSet(DispatchBaseClass):
        def GetItem(self, IDName=defaultNamedNotOptArg): ...      # -> CATBaseDispatch
        # props: AllParameters -> Parameters, Application,
        #        DirectParameters -> Parameters, Name (r/w),
        #        ParameterSets -> ParameterSets, Parent

From ``14F197B2-0771-11D1-A5B1-00A0C9575177x0x0x0.py`` (InfInterfaces):

    class Selection(DispatchBaseClass):
        def Add(self, iObject=defaultNamedNotOptArg): ...          # -> void
        def Clear(self): ...                                       # -> void
        def Item(self, iIndex=defaultNamedNotOptArg): ...           # -> SelectedElement
        def Search(self, iStringBSTR=defaultNamedNotOptArg): ...    # -> void, mutates Selection
        # props: Application, Count, Count2, Name (r/w), Parent, Selection, VisProperties

Members looked for and NOT found in the type library (so not called here):

* ``Shapes.Remove`` / ``Sketches.Remove`` -- confirmed absent again (conventions.md 1.2).
* Any ``Count``/``Item`` pair on ``Part.InWorkObject`` itself; it is a single
  ``AnyObject``, read once, not enumerated.
* A ``BoundingBox`` or similar member on ``Body`` or ``HybridBody`` -- none exists;
  this probe does not attempt one (see the measurement lesson, section 12).

Run from the repository root, with a live 3DEXPERIENCE session attached:

    python scripts/probes/38_inspection.py

BEFORE RUNNING, to make the selection-restore check meaningful: select one or
two features in the CATIA specification tree (Ctrl-click a couple of entries).
If nothing is selected when the probe starts, it still runs safely, but it can
only prove that restoring an EMPTY selection round-trips -- not a non-empty one.
"""

from typing import Any, Callable, TypeVar

from auto_3dx import Catia


T = TypeVar("T")

FIRST_COM_INDEX = 1

MAX_BODIES = 10
MAX_SHAPES_PER_BODY = 20
MAX_SKETCHES_PER_BODY = 20
MAX_HYBRID_BODIES = 10
MAX_HYBRID_SHAPES_PER_SET = 20
MAX_NESTED_HYBRID_BODIES = 10
MAX_DIRECT_PARAMETERS = 20
MAX_TEXT_PREVIEW = 96

EDGE_SEARCH_QUERY = "Topology.Edge,all"
FACE_SEARCH_QUERY = "Topology.Face,all"

# Sentinel distinguishing "the action legitimately returned None/0/False" from
# "the action raised". Using ``None`` as the failure marker would conflate the two.
_FAILED = object()


def _ascii(value: object) -> str:
    """Returns a console-safe rendering even on a legacy Windows code page."""
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def _short_text(value: object) -> str:
    """Returns a bounded, ASCII-safe representation for a possibly long value."""
    text = _ascii(value)
    if len(text) <= MAX_TEXT_PREVIEW:
        return text
    return f"{text[:MAX_TEXT_PREVIEW]}..."


def attempt(label: str, action: Callable[[], T]) -> Any:
    """Runs one read-only COM action, reporting OK/FAILED, and never raising.

    This is the reporting primitive the whole probe is built from (see the
    module docstring): a field is only as trustworthy as the read that produced
    it, and a call that raised must not stop the rest of the probe from running.

    Args:
        label: Short ASCII description printed with the result line.
        action: A zero-argument callable performing exactly one COM read.

    Returns:
        Whatever ``action`` returned, or the module-level ``_FAILED`` sentinel
        if it raised. Callers must check for ``_FAILED`` with ``is`` before
        using the result, because a legitimate result can be ``None``, ``0``,
        or ``False``.
    """
    try:
        result = action()
    except Exception as error:  # noqa: BLE001 - this is a diagnostic probe
        print(f"FAILED {label}: {type(error).__name__}: {_short_text(error)}")
        return _FAILED
    print(f"OK     {label}")
    return result


def _print_omitted(total: int, shown: int) -> None:
    """Prints how many entries a bounded enumeration left out, if any."""
    remaining = total - shown
    if remaining > 0:
        print(f"    ... {remaining} more omitted")


def _capture_selection(selection: Any) -> list[Any]:
    """Captures the current selection's raw Values, exactly as probe 31 does.

    Raises:
        RuntimeError: An existing selected item could not be read safely. The
            caller must treat this as a hard stop: searching without a trusted
            capture would destroy a selection this probe could not record.
    """
    values: list[Any] = []
    count = int(selection.Count)
    for position in range(FIRST_COM_INDEX, count + FIRST_COM_INDEX):
        try:
            values.append(selection.Item(position).Value)
        except Exception as error:  # noqa: BLE001 - restoration would be unsafe
            raise RuntimeError(
                f"cannot capture existing selection item {position}: "
                f"{type(error).__name__}: {_ascii(error)}"
            ) from error
    return values


def _restore_selection(selection: Any, captured_values: list[Any]) -> None:
    """Restores a selection captured by :func:`_capture_selection`."""
    selection.Clear()
    for value in captured_values:
        selection.Add(value)


def _identity_of(com_object: Any) -> tuple[str | None, str | None]:
    """Returns a bounded ``(name, kind)`` pair for a raw COM object, never raising."""
    try:
        name = _short_text(com_object.Name)
    except Exception:  # noqa: BLE001 - identity is best-effort for reporting
        name = None
    kind = type(com_object).__name__
    return name, kind


def _report_part_identity(raw_part: Any) -> None:
    """Section 1: Part.Name, and the type + name of Part.InWorkObject."""
    print("=== 1. Part identity ===")
    attempt("Part.Name", lambda: print(f"    Name = {_ascii(raw_part.Name)}"))

    in_work = attempt("Part.InWorkObject", lambda: raw_part.InWorkObject)
    if in_work is _FAILED or in_work is None:
        return
    kind = type(in_work).__name__
    print(f"    InWorkObject type = {kind}")
    attempt(
        "Part.InWorkObject.Name",
        lambda: print(f"    InWorkObject.Name = {_ascii(in_work.Name)}"),
    )


def _report_bodies(raw_part: Any) -> "list[Any]":
    """Section 2: Part.Bodies, its Count, and per-body Name / MainBody / identity.

    Returns:
        The list of raw Body COM objects read (up to ``MAX_BODIES``), for reuse
        by the feature-tree section, or an empty list if Bodies was unreadable.
    """
    print("=== 2. Bodies ===")
    bodies = attempt("Part.Bodies", lambda: raw_part.Bodies)
    if bodies is _FAILED:
        return []
    count = attempt("Bodies.Count", lambda: int(bodies.Count))
    if count is _FAILED:
        return []
    print(f"    Bodies.Count = {count}")

    main_body = attempt("Part.MainBody", lambda: raw_part.MainBody)

    result: list[Any] = []
    shown = min(count, MAX_BODIES)
    for index in range(FIRST_COM_INDEX, shown + FIRST_COM_INDEX):
        body = attempt(f"Bodies.Item({index})", lambda index=index: bodies.Item(index))
        if body is _FAILED:
            continue
        result.append(body)
        name, _kind = _identity_of(body)
        print(f"    body[{index}].Name = {name}")

        if main_body is not _FAILED and main_body is not None:
            is_main = attempt(
                f"body[{index}] == Part.MainBody",
                lambda body=body: bool(body == main_body),
            )
            if is_main is not _FAILED:
                print(f"    body[{index}] == Part.MainBody -> {is_main}")

        # COM identity has only been verified for sketches so far (conventions.md
        # 1.2). Read the same index twice and compare with ``==`` to extend that
        # evidence to Body, per the task's explicit ask.
        body_again = attempt(
            f"Bodies.Item({index}) (second read)", lambda index=index: bodies.Item(index)
        )
        if body_again is not _FAILED:
            same_object = attempt(
                f"body[{index}] read twice: == ",
                lambda body=body, body_again=body_again: bool(body == body_again),
            )
            if same_object is not _FAILED:
                print(f"    body[{index}] read twice, == -> {same_object}")

    _print_omitted(count, shown)
    return result


def _report_features_per_body(bodies: "list[Any]") -> None:
    """Section 3: Body.Shapes and Body.Sketches, enumerated as a feature tree."""
    print("=== 3. Features per body (Shapes, Sketches) ===")
    if not bodies:
        print("    skipped: no bodies were available from section 2")
        return

    for body_index, body in enumerate(bodies, start=FIRST_COM_INDEX):
        body_name, _kind = _identity_of(body)
        print(f"  -- body[{body_index}] ({body_name}) --")

        shapes = attempt(f"body[{body_index}].Shapes", lambda body=body: body.Shapes)
        if shapes is not _FAILED:
            shape_count = attempt(
                f"body[{body_index}].Shapes.Count", lambda shapes=shapes: int(shapes.Count)
            )
            if shape_count is not _FAILED:
                print(f"    Shapes.Count = {shape_count}")
                shown = min(shape_count, MAX_SHAPES_PER_BODY)
                for index in range(FIRST_COM_INDEX, shown + FIRST_COM_INDEX):
                    item = attempt(
                        f"Shapes.Item({index})",
                        lambda shapes=shapes, index=index: shapes.Item(index),
                    )
                    if item is _FAILED:
                        continue
                    name, kind = _identity_of(item)
                    print(f"    shape[{index}] Name={name} kind={kind}")
                _print_omitted(shape_count, shown)

        sketches = attempt(f"body[{body_index}].Sketches", lambda body=body: body.Sketches)
        if sketches is not _FAILED:
            sketch_count = attempt(
                f"body[{body_index}].Sketches.Count", lambda sketches=sketches: int(sketches.Count)
            )
            if sketch_count is not _FAILED:
                print(f"    Sketches.Count = {sketch_count}")
                shown = min(sketch_count, MAX_SKETCHES_PER_BODY)
                for index in range(FIRST_COM_INDEX, shown + FIRST_COM_INDEX):
                    item = attempt(
                        f"Sketches.Item({index})",
                        lambda sketches=sketches, index=index: sketches.Item(index),
                    )
                    if item is _FAILED:
                        continue
                    name, kind = _identity_of(item)
                    print(f"    sketch[{index}] Name={name} kind={kind}")
                _print_omitted(sketch_count, shown)


def _report_hybrid_shapes(hybrid_body: Any, label: str) -> None:
    """Reports one geometrical set's HybridShapes: existence, Count, each item."""
    shapes = attempt(f"{label}.HybridShapes", lambda: hybrid_body.HybridShapes)
    if shapes is _FAILED:
        return
    count = attempt(f"{label}.HybridShapes.Count", lambda: int(shapes.Count))
    if count is _FAILED:
        return
    print(f"    {label}.HybridShapes.Count = {count}")
    shown = min(count, MAX_HYBRID_SHAPES_PER_SET)
    for index in range(FIRST_COM_INDEX, shown + FIRST_COM_INDEX):
        item = attempt(
            f"{label}.HybridShapes.Item({index})",
            lambda index=index: shapes.Item(index),
        )
        if item is _FAILED:
            continue
        name, kind = _identity_of(item)
        print(f"    {label} hybrid_shape[{index}] Name={name} kind={kind}")
    _print_omitted(count, shown)


def _report_nested_hybrid_bodies(hybrid_body: Any, label: str) -> None:
    """Reports whether a geometrical set exposes nested HybridBodies, and what is in it."""
    nested = attempt(f"{label}.HybridBodies (nested)", lambda: hybrid_body.HybridBodies)
    if nested is _FAILED:
        return
    nested_count = attempt(f"{label}.HybridBodies.Count", lambda: int(nested.Count))
    if nested_count is _FAILED:
        return
    print(f"    {label}.HybridBodies.Count (nested sets) = {nested_count}")
    shown = min(nested_count, MAX_NESTED_HYBRID_BODIES)
    for index in range(FIRST_COM_INDEX, shown + FIRST_COM_INDEX):
        item = attempt(
            f"{label}.HybridBodies.Item({index})",
            lambda index=index: nested.Item(index),
        )
        if item is _FAILED:
            continue
        name, kind = _identity_of(item)
        print(f"    {label} nested_set[{index}] Name={name} kind={kind}")
    _print_omitted(nested_count, shown)


def _report_geometrical_sets(raw_part: Any) -> None:
    """Section 4: Part.HybridBodies, each set's HybridShapes, and nested sets."""
    print("=== 4. Geometrical sets (HybridBodies) ===")
    hybrid_bodies = attempt("Part.HybridBodies", lambda: raw_part.HybridBodies)
    if hybrid_bodies is _FAILED:
        return
    count = attempt("Part.HybridBodies.Count", lambda: int(hybrid_bodies.Count))
    if count is _FAILED:
        return
    print(f"    Part.HybridBodies.Count = {count}")

    shown = min(count, MAX_HYBRID_BODIES)
    for index in range(FIRST_COM_INDEX, shown + FIRST_COM_INDEX):
        hybrid_body = attempt(
            f"HybridBodies.Item({index})", lambda index=index: hybrid_bodies.Item(index)
        )
        if hybrid_body is _FAILED:
            continue
        name, _kind = _identity_of(hybrid_body)
        label = f"set[{index}] ({name})"
        print(f"  -- {label} --")
        _report_hybrid_shapes(hybrid_body, label)
        _report_nested_hybrid_bodies(hybrid_body, label)
    _print_omitted(count, shown)


def _report_parameters(raw_part: Any) -> None:
    """Section 5: Parameters.Count and RootParameterSet.DirectParameters."""
    print("=== 5. Parameters ===")
    parameters = attempt("Part.Parameters", lambda: raw_part.Parameters)
    if parameters is _FAILED:
        return
    total_count = attempt("Parameters.Count", lambda: int(parameters.Count))
    if total_count is not _FAILED:
        print(f"    Parameters.Count = {total_count}")

    root_set = attempt("Parameters.RootParameterSet", lambda: parameters.RootParameterSet)
    if root_set is _FAILED:
        return
    direct = attempt(
        "RootParameterSet.DirectParameters", lambda: root_set.DirectParameters
    )
    if direct is _FAILED:
        return
    direct_count = attempt(
        "DirectParameters.Count", lambda: int(direct.Count)
    )
    if direct_count is _FAILED:
        return
    print(f"    RootParameterSet.DirectParameters.Count = {direct_count}")

    shown = min(direct_count, MAX_DIRECT_PARAMETERS)
    for index in range(FIRST_COM_INDEX, shown + FIRST_COM_INDEX):
        item = attempt(
            f"DirectParameters.Item({index})", lambda index=index: direct.Item(index)
        )
        if item is _FAILED:
            continue
        name, kind = _identity_of(item)
        value = attempt(
            f"DirectParameters.Item({index}).Value", lambda item=item: item.Value
        )
        value_text = "<unavailable>" if value is _FAILED else _short_text(value)
        print(f"    parameter[{index}] Name={name} kind={kind} Value={value_text}")
    _print_omitted(direct_count, shown)


def _report_update_status(raw_part: Any) -> None:
    """Section 6: Part.IsUpToDate(Part) and its Python type."""
    print("=== 6. Update status ===")
    result = attempt("Part.IsUpToDate(Part)", lambda: raw_part.IsUpToDate(raw_part))
    if result is _FAILED:
        return
    print(f"    IsUpToDate(Part) = {result} (python type = {type(result).__name__})")


def _search_count(selection: Any, query: str, label: str) -> Any:
    """Runs one bounded topology search and returns the hit count, or ``_FAILED``."""
    def _do() -> int:
        selection.Clear()
        selection.Search(query)
        count = int(selection.Count)
        selection.Clear()
        return count

    return attempt(label, _do)


def _report_topology_counts(selection: Any) -> None:
    """Section 7: two edge searches and two face searches, compared for agreement."""
    print("=== 7. Topology counts ===")
    edge_a = _search_count(selection, EDGE_SEARCH_QUERY, "Search(Topology.Edge,all) #1")
    edge_b = _search_count(selection, EDGE_SEARCH_QUERY, "Search(Topology.Edge,all) #2")
    if edge_a is not _FAILED and edge_b is not _FAILED:
        print(f"    edge count: first={edge_a}, second={edge_b}, agree={edge_a == edge_b}")

    face_a = _search_count(selection, FACE_SEARCH_QUERY, "Search(Topology.Face,all) #1")
    face_b = _search_count(selection, FACE_SEARCH_QUERY, "Search(Topology.Face,all) #2")
    if face_a is not _FAILED and face_b is not _FAILED:
        print(f"    face count: first={face_a}, second={face_b}, agree={face_a == face_b}")


def _report_selection_restore(selection: Any, captured_values: "list[Any]") -> bool:
    """Section 8: restores the captured selection and reports PASS/FAIL.

    Args:
        selection: The raw CATIA ``Selection`` COM object.
        captured_values: The raw Values captured before any search ran.

    Returns:
        ``True`` if the restored selection round-trips (same count, and each
        item's ``Value.Name`` and type name match, in order); ``False``
        otherwise, including when any read along the way failed.
    """
    print("=== 8. Selection restore ===")
    print(f"    items selected at probe start: {len(captured_values)}")
    if not captured_values:
        print(
            "    Selection was EMPTY at start: restoring a NON-EMPTY selection was "
            "NOT exercised by this run."
        )
        print(
            "    OPERATOR ACTION: select one or two features in the CATIA "
            "specification tree, then run this probe again."
        )

    restored = attempt(
        "restore captured selection (Clear + Add per item)",
        lambda: _restore_selection(selection, captured_values),
    )
    if restored is _FAILED:
        print("    restore round-trips: FAIL (restore call itself failed)")
        return False

    read_back = attempt("re-read restored Selection.Count", lambda: int(selection.Count))
    if read_back is _FAILED:
        print("    restore round-trips: FAIL (could not re-read selection)")
        return False

    if read_back != len(captured_values):
        print(
            f"    restore round-trips: FAIL (count mismatch: "
            f"expected {len(captured_values)}, got {read_back})"
        )
        return False

    all_match = True
    for position, original_value in enumerate(captured_values, start=FIRST_COM_INDEX):
        restored_value = attempt(
            f"Selection.Item({position}).Value (restored)",
            lambda position=position: selection.Item(position).Value,
        )
        if restored_value is _FAILED:
            all_match = False
            continue
        original_name, original_kind = _identity_of(original_value)
        restored_name, restored_kind = _identity_of(restored_value)
        item_matches = original_name == restored_name and original_kind == restored_kind
        all_match = all_match and item_matches
        print(
            f"    item[{position}] original=({original_name}, {original_kind}) "
            f"restored=({restored_name}, {restored_kind}) match={item_matches}"
        )

    print(f"    restore round-trips: {'PASS' if all_match else 'FAIL'}")
    return all_match


def main() -> None:
    """Runs every inspection-evidence check and restores the selection in finally."""
    catia = Catia.attach()
    editor = catia.active_editor()
    part = catia.active_part()
    raw_part = part.com_object
    selection = editor.Selection

    print(f"Part: {_ascii(part.name)}")
    print("Mode: read-only inspection probe")
    print("Document save: NOT CALLED")

    captured_values: "list[Any]" = []
    capture_ok = False
    try:
        captured_values = _capture_selection(selection)
        capture_ok = True
    except RuntimeError as error:
        print(f"FAILED selection capture: {error}")
        print(
            "Skipping all searches: the existing selection could not be safely "
            "captured, so it must not be touched."
        )

    try:
        _report_part_identity(raw_part)
        bodies = _report_bodies(raw_part)
        _report_features_per_body(bodies)
        _report_geometrical_sets(raw_part)
        _report_parameters(raw_part)
        _report_update_status(raw_part)

        if capture_ok:
            _report_topology_counts(selection)
    finally:
        if capture_ok:
            _report_selection_restore(selection, captured_values)
        else:
            print("=== 8. Selection restore ===")
            print("    skipped: selection capture failed, so nothing was searched or touched")
        print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
