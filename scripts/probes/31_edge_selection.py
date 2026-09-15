"""Probe whether CATIA BRep-edge selection survives a model regeneration.

This is deliberately a probe, not a library API. Probe 28 established the
only verified route from a searched edge to a feature-usable reference:

    Editor.Selection.Search("Topology.Edge,all")
      -> SelectedElement.Reference

It also established that a reference captured before a topology-changing
feature may be stale afterward. This script separates three questions that
must not be conflated:

* Are BRep reference names and search order repeatable when the model is
  unchanged?
* Does a controlled regeneration change the searched-edge descriptor set?
* Can CATIA's documented measurement service expose enough geometry to choose
  one edge without depending on search position or a raw BRep name?

The default invocation is read-only with respect to model geometry. It takes
two searches, compares their BRep reference descriptors, and restores the
user's original selection before exiting. It never calls ``Part.Update()``,
``Save()``, or ``PLMPropagate()`` in that mode.

``--measure`` remains read-only. It probes the locally generated
CATOpnsMeasureIDL type library's documented ``MeasurableService`` route and
reports only methods that actually return values. It does not treat a
successful cast or a matching length as a durable selector: equal descriptors
are explicitly reported as ambiguous.

``--regenerate`` is opt-in because it creates temporary geometry. It creates
only ``AUTO3DX_P31_*`` objects, changes that owned pad's height, snapshots
before and after the update, restores the original height, then deletes the
owned pad and sketch in ``finally``. It will refuse to run if either owned
name already exists. This mode still never saves or propagates PLM data.

Run from the repository root, for example:

    python scripts/probes/31_edge_selection.py
    python scripts/probes/31_edge_selection.py --measure
    python scripts/probes/31_edge_selection.py --regenerate --measure

The generated pywin32 wrapper confirms these signatures but does not define a
durability guarantee:

* ``Selection.Search(BSTR) -> void``; it mutates ``Selection``.
* ``SelectedElement.Reference -> Reference``.
* ``Part.CreateReferenceFromBRepName(BSTR, dispatch) -> Reference``.
* ``MeasurableService.GetMeasurable(dispatch, long) -> MeasurableInContext``.

The ``long`` on ``GetMeasurable`` has no attached enum metadata. The probe
tries ``catOpnsEdgeItem == 1`` from the same generated type library and then
tries the concrete measurable wrapper types that expose edge geometry. A
failure is reported as an unverified route, not compensated for with guessed
integers or undocumented BRep-string parsing.
"""

from __future__ import annotations

import argparse
import hashlib
from collections import Counter
from dataclasses import dataclass
from typing import Any, Sequence

from auto_3dx import Catia, Part


EDGE_SEARCH_QUERY = "Topology.Edge,all"
FIRST_COM_INDEX = 1
MAX_DESCRIPTOR_PREVIEW = 8
MAX_TEXT_PREVIEW = 112
MILLIMETRES_PER_METRE = 1000.0

PREFIX = "AUTO3DX_P31_"
SKETCH_NAME = f"{PREFIX}SKETCH"
PAD_NAME = f"{PREFIX}PAD"
PAD_WIDTH_MM = 20.0
PAD_LENGTH_MM = 15.0
PAD_HEIGHT_INITIAL_MM = 10.0
PAD_HEIGHT_REGENERATED_MM = 17.0

# ``CATOpnsMeasureItemType.catOpnsEdgeItem`` in CATOpnsMeasureIDLItf.
# The method parameter is plain VT_I4 in the type library, so this is a
# documented candidate to test, not an asserted parameter contract.
CAT_OPNS_EDGE_ITEM = 1
MEASURABLE_CAST_TARGETS = (
    "MeasurableLine",
    "MeasurableCurve",
    "MeasurableCircle",
)


@dataclass(frozen=True)
class EdgeDescriptor:
    """A searched edge's non-geometric, session-local descriptor.

    Attributes:
        position: One-based position in the current ``Selection.Search`` result.
        wrapper_kind: Python wrapper type returned by ``SelectedElement.Value``.
        reference_name: BRep reference name, or ``None`` when CATIA did not expose it.
        reference_display_name: Display name, or ``None`` when unavailable.
    """

    position: int
    wrapper_kind: str | None
    reference_name: str | None
    reference_display_name: str | None


@dataclass(frozen=True)
class SelectionState:
    """The user's selection values captured before this probe changes Selection."""

    values: tuple[Any, ...]


def _ascii(value: object) -> str:
    """Returns a console-safe rendering even on a legacy Windows code page."""
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def _short_text(value: object) -> str:
    """Returns a bounded, ASCII-safe representation for potentially huge BRep names."""
    text = _ascii(value)
    if len(text) <= MAX_TEXT_PREVIEW:
        return text
    return f"{text[:MAX_TEXT_PREVIEW]}..."


def _fingerprint(name: str | None) -> str:
    """Returns a stable, compact display token for one BRep name within this run."""
    if name is None:
        return "<unavailable>"
    digest = hashlib.sha256(name.encode("utf-8", "backslashreplace")).hexdigest()
    return digest[:16]


def _read_text(com_object: Any, attribute: str) -> str | None:
    """Reads a COM text property without letting one bad hit stop the snapshot."""
    try:
        value = getattr(com_object, attribute)
    except Exception as error:  # noqa: BLE001 - this is a diagnostic probe
        print(f"  read {attribute}: FAILED {type(error).__name__}: {_short_text(error)}")
        return None
    if value is None:
        return None
    return str(value)


def _capture_selection(selection: Any) -> SelectionState:
    """Captures current selection Values so the read-only mode can restore them.

    Raises:
        RuntimeError: If an existing selected element cannot be read safely.
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
    return SelectionState(tuple(values))


def _restore_selection(selection: Any, state: SelectionState) -> None:
    """Restores the selection captured before the probe ran."""
    selection.Clear()
    for value in state.values:
        selection.Add(value)


def _search_edge_elements(selection: Any) -> list[Any]:
    """Runs the one verified topology query and returns its SelectedElement hits."""
    selection.Clear()
    selection.Search(EDGE_SEARCH_QUERY)
    count = int(selection.Count)
    return [
        selection.Item(position)
        for position in range(FIRST_COM_INDEX, count + FIRST_COM_INDEX)
    ]


def _snapshot_edges(selection: Any, label: str) -> list[EdgeDescriptor]:
    """Captures descriptors from a fresh Search without retaining the selection result."""
    print(f"--- {label}: Search({EDGE_SEARCH_QUERY!r}) ---")
    hits = _search_edge_elements(selection)
    descriptors: list[EdgeDescriptor] = []
    for position, selected_element in enumerate(hits, start=FIRST_COM_INDEX):
        try:
            value = selected_element.Value
            wrapper_kind: str | None = type(value).__name__
        except Exception as error:  # noqa: BLE001 - report partial diagnostics
            print(f"  edge[{position}].Value: FAILED {type(error).__name__}: {_short_text(error)}")
            wrapper_kind = None
        try:
            reference = selected_element.Reference
        except Exception as error:  # noqa: BLE001 - report partial diagnostics
            print(
                f"  edge[{position}].Reference: FAILED "
                f"{type(error).__name__}: {_short_text(error)}"
            )
            reference = None
        if reference is None:
            name = None
            display_name = None
        else:
            name = _read_text(reference, "Name")
            display_name = _read_text(reference, "DisplayName")
        descriptors.append(EdgeDescriptor(position, wrapper_kind, name, display_name))

    selection.Clear()
    print(f"  edge count = {len(descriptors)}")
    _print_descriptor_preview(descriptors)
    return descriptors


def _print_descriptor_preview(descriptors: Sequence[EdgeDescriptor]) -> None:
    """Prints a bounded descriptor sample without flooding the terminal with BRep strings."""
    for descriptor in descriptors[:MAX_DESCRIPTOR_PREVIEW]:
        preview = (
            _short_text(descriptor.reference_name)
            if descriptor.reference_name
            else "<unavailable>"
        )
        print(
            f"  edge[{descriptor.position}] kind={descriptor.wrapper_kind!r} "
            f"name_sha256={_fingerprint(descriptor.reference_name)} name={preview!r}"
        )
    remaining = len(descriptors) - MAX_DESCRIPTOR_PREVIEW
    if remaining > 0:
        print(f"  ... {remaining} more descriptors omitted from preview")


def _compare_snapshots(
    before: Sequence[EdgeDescriptor], after: Sequence[EdgeDescriptor], label: str
) -> None:
    """Reports exact-name and position stability without calling either result durable."""
    print(f"--- {label} ---")
    before_names = [descriptor.reference_name for descriptor in before]
    after_names = [descriptor.reference_name for descriptor in after]
    before_available = [name for name in before_names if name is not None]
    after_available = [name for name in after_names if name is not None]
    before_counts = Counter(before_available)
    after_counts = Counter(after_available)
    names_equal = before_counts == after_counts
    positions_equal = before_names == after_names
    duplicates = [name for name, count in before_counts.items() if count > 1]

    print(f"  counts: before={len(before)}, after={len(after)}")
    print(f"  exact BRep-name multiset equal: {names_equal}")
    print(f"  search position sequence equal: {positions_equal}")
    print(
        f"  unavailable names: before={len(before) - len(before_available)}, "
        f"after={len(after) - len(after_available)}"
    )
    if duplicates:
        print(f"  duplicate BRep names in first snapshot: {len(duplicates)} -> AMBIGUOUS")
    if names_equal and positions_equal and not duplicates:
        print("  Result: repeatable while unchanged; durability across regeneration is NOT proven.")
    elif names_equal:
        print(
            "  Result: name multiset survived but search index is unstable; "
            "index is not a selector."
        )
    else:
        print("  Result: BRep names changed; raw BRep names are not a durable selector here.")


def _probe_brep_name_resolution(
    raw_part: Any,
    context: Any,
    context_label: str,
    descriptors: Sequence[EdgeDescriptor],
    label: str,
) -> None:
    """Tests BRep-name re-resolution without using the returned Reference to modify geometry.

    A successful call only proves that CATIA accepts the captured string in the
    supplied context during this session. It does not prove the reference still
    denotes the same physical edge after regeneration, so the output keeps
    those two conclusions separate.
    """
    name = next(
        (descriptor.reference_name for descriptor in descriptors if descriptor.reference_name),
        None,
    )
    print(f"--- {label}: CreateReferenceFromBRepName ({context_label}) ---")
    if name is None:
        print("  skipped: no searchable BRep name was available")
        return
    try:
        resolved = raw_part.CreateReferenceFromBRepName(name, context)
        resolved_name = _read_text(resolved, "Name")
    except Exception as error:  # noqa: BLE001 - this call is the probe result
        print(f"  resolution: FAILED {type(error).__name__}: {_short_text(error)}")
        return
    print(f"  resolution accepted: {resolved_name == name}")
    print("  Result: accepted syntax is not proof of physical-edge identity.")


def _measure_edges(selection: Any, editor: Any, max_edges: int) -> None:
    """Attempts a read-only geometry descriptor for searched edges.

    The generated wrapper gives ``GetMeasurable`` a plain ``long`` argument.
    ``CAT_OPNS_EDGE_ITEM`` is the type library's edge-item constant, but the
    mapping remains a live-probe question. The output deliberately separates
    a working service/cast from a unique, durable geometry selector.
    """
    print("--- measurement candidate: MeasurableService ---")
    try:
        from win32com.client import CastTo
    except Exception as error:  # noqa: BLE001 - do not make pywin32 mandatory for compile
        print(f"  CastTo import: FAILED {type(error).__name__}: {_short_text(error)}")
        return

    try:
        service = editor.GetService("MeasurableService")
    except Exception as error:  # noqa: BLE001 - service availability is a probe result
        print(
            "  Editor.GetService('MeasurableService'): FAILED "
            f"{type(error).__name__}: {_short_text(error)}"
        )
        return

    hits = _search_edge_elements(selection)
    if not hits:
        print("  no searched edges; measurement skipped")
        return
    limit = min(len(hits), max_edges)
    print(f"  testing {limit} of {len(hits)} edges with catOpnsEdgeItem={CAT_OPNS_EDGE_ITEM}")

    measurable_by_target: dict[str, list[tuple[int, float]]] = {}
    for position, selected_element in enumerate(hits[:limit], start=FIRST_COM_INDEX):
        try:
            reference = selected_element.Reference
            base = service.GetMeasurable(reference, CAT_OPNS_EDGE_ITEM)
        except Exception as error:  # noqa: BLE001 - report this edge's route failure
            print(
                f"  edge[{position}] GetMeasurable: FAILED "
                f"{type(error).__name__}: {_short_text(error)}"
            )
            continue

        measured = False
        for target in MEASURABLE_CAST_TARGETS:
            try:
                measurable = CastTo(base, target)
                length_metres = float(measurable.GetLength())
            except Exception:
                continue
            length_mm = length_metres * MILLIMETRES_PER_METRE
            measurable_by_target.setdefault(target, []).append((position, length_mm))
            print(f"  edge[{position}] {target}: length={length_mm:.6f} mm")
            measured = True
            break
        if not measured:
            print("  edge[%d] no concrete Measurable* cast exposed GetLength" % position)

    selection.Clear()
    if not measurable_by_target:
        print("  Result: no measured geometry is available through this wrapper route.")
        return
    for target, samples in measurable_by_target.items():
        duplicate_lengths = _duplicate_lengths(samples)
        if duplicate_lengths:
            print(f"  {target}: duplicate lengths -> length alone is AMBIGUOUS")
        else:
            print(
                f"  {target}: all sampled lengths differ, but endpoints/direction "
                "still need live proof"
            )


def _duplicate_lengths(samples: Sequence[tuple[int, float]]) -> list[float]:
    """Returns repeated rounded lengths without claiming an engineering tolerance."""
    counts = Counter(round(length, 9) for _, length in samples)
    return [length for length, count in counts.items() if count > 1]


def _owned_name_exists(part: Any, body: Any) -> bool:
    """Returns whether a previous P31 object exists, refusing unsafe cleanup if so."""
    sketch_names = part.sketches.names()
    shape_names = [
        str(body.Shapes.Item(position).Name)
        for position in range(FIRST_COM_INDEX, int(body.Shapes.Count) + FIRST_COM_INDEX)
    ]
    existing = [
        name
        for name in (SKETCH_NAME, PAD_NAME)
        if name in sketch_names or name in shape_names
    ]
    if existing:
        print(f"  refusing --regenerate: owned names already exist: {existing!r}")
        return True
    return False


def _run_regeneration_probe(part: Any, selection: Any) -> None:
    """Creates, regenerates, restores, and removes only this probe's owned geometry."""
    raw = part.com_object
    body = raw.MainBody
    if _owned_name_exists(part, body):
        return

    sketch_created = False
    pad_created = False
    pad: Any = None
    print("--- opt-in regeneration check: temporary owned pad ---")
    try:
        sketch = part.sketches.create(SKETCH_NAME, support="XY")
        sketch_created = True
        with sketch.edit() as editor:
            editor.rectangle(PAD_WIDTH_MM, PAD_LENGTH_MM)
        part.update()
        pad = part.part_design.create_pad(PAD_NAME, sketch, PAD_HEIGHT_INITIAL_MM)
        pad_created = True
        part.update()
        print(f"  created {PAD_NAME!r}, height={pad.height:.6f} mm")

        before = _snapshot_edges(selection, "before owned-pad regeneration")
        _probe_brep_name_resolution(
            raw,
            raw,
            "Part",
            before,
            "before regeneration",
        )
        pad.set_height(PAD_HEIGHT_REGENERATED_MM)
        part.update()
        print(f"  changed owned pad height to {PAD_HEIGHT_REGENERATED_MM:.6f} mm")
        after = _snapshot_edges(selection, "after owned-pad regeneration")
        _compare_snapshots(before, after, "regeneration stability")
        _probe_brep_name_resolution(
            raw,
            raw,
            "Part",
            before,
            "after regeneration with pre-regeneration name",
        )
        _probe_brep_name_resolution(
            raw,
            pad.com_object,
            "owned pad",
            before,
            "after regeneration with owned-pad context",
        )

        pad.set_height(PAD_HEIGHT_INITIAL_MM)
        part.update()
        print(f"  restored owned pad height to {PAD_HEIGHT_INITIAL_MM:.6f} mm")
    except Exception as error:  # noqa: BLE001 - cleanup must still run
        print(f"  regeneration experiment: FAILED {type(error).__name__}: {_short_text(error)}")
    finally:
        selection.Clear()
        if pad_created:
            try:
                part.part_design.remove_pad(PAD_NAME)
                print(f"  removed {PAD_NAME!r}")
            except Exception as error:  # noqa: BLE001 - failed update can leave a broken feature
                print(
                    f"  cleanup {PAD_NAME!r}: FAILED {type(error).__name__}: "
                    f"{_short_text(error)}"
                )
        if sketch_created:
            try:
                part.sketches.remove(SKETCH_NAME)
                print(f"  removed {SKETCH_NAME!r}")
            except Exception as error:  # noqa: BLE001 - Pad removal can cascade-delete its sketch
                print(f"  cleanup {SKETCH_NAME!r}: {type(error).__name__}: {_short_text(error)}")
        try:
            part.update()
        except Exception as error:  # noqa: BLE001 - report, never mask cleanup
            print(f"  update after cleanup: FAILED {type(error).__name__}: {_short_text(error)}")
        selection.Clear()


def _parse_args() -> argparse.Namespace:
    """Parses opt-in probe modes without connecting to CATIA."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--measure",
        action="store_true",
        help="probe the read-only MeasurableService geometry route for a bounded edge sample",
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="opt in to temporary owned geometry, regeneration comparison, and finally cleanup",
    )
    parser.add_argument(
        "--max-measured-edges",
        type=int,
        default=MAX_DESCRIPTOR_PREVIEW,
        help="maximum searched edges to send through the experimental measurement route",
    )
    args = parser.parse_args()
    if args.max_measured_edges < FIRST_COM_INDEX:
        parser.error("--max-measured-edges must be positive")
    return args


def main() -> None:
    """Runs the selected durability checks and restores the user's selection."""
    args = _parse_args()
    catia = Catia.attach()
    editor = catia.active_editor()
    raw_part = editor.ActiveObject
    if type(raw_part).__name__ != "Part":
        raise RuntimeError(
            "The active editor is not editing a Part; "
            f"ActiveObject is {type(raw_part).__name__}."
        )
    selection = editor.Selection
    part = Part(raw_part, selection=selection, editor=editor)
    selection_state = _capture_selection(selection)

    print(f"Part: {_ascii(part.name)}")
    print("Mode: read-only" if not args.regenerate else "Mode: opt-in temporary regeneration")
    print("Document save: NOT CALLED")
    try:
        first = _snapshot_edges(selection, "unchanged snapshot A")
        second = _snapshot_edges(selection, "unchanged snapshot B")
        _compare_snapshots(first, second, "unchanged-model stability")
        _probe_brep_name_resolution(raw_part=part.com_object, context=part.com_object,
                                    context_label="Part", descriptors=first,
                                    label="unchanged model")
        if args.measure:
            _measure_edges(selection, editor, args.max_measured_edges)
        if args.regenerate:
            _run_regeneration_probe(part, selection)
    finally:
        try:
            _restore_selection(selection, selection_state)
            print("Selection restored.")
        except Exception as error:  # noqa: BLE001 - selection is UI state, report explicitly
            print(f"Selection restore: FAILED {type(error).__name__}: {_short_text(error)}")
            try:
                selection.Clear()
            except Exception:
                pass
        print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
