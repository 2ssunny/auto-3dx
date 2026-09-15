"""Probe whether an offset plane can support both a sketch and a Pad.

This is a deliberately narrow follow-up to ``29_user_planes.py``.  The
earlier probe established that an offset plane can be created, appended to a
HybridBody, and passed directly to ``Body.Sketches.Add``.  It also observed
that ``ShapeFactory.AddNewPad`` on the resulting sketch failed.  This probe
repeats only that vertical slice with uniquely named temporary objects and
reports the two separate questions precisely:

* did the creation call return a COM object?
* did the resulting model survive ``Part.Update()``?

The generated pywin32 type-library cache for this B428_Cloud installation
provides the exact signatures used here:

    HybridBodies.Add() -> HybridBody
    HybridShapeFactory.AddNewPlaneOffset(iPlane, iOffset, iOrientation)
        iPlane: VT_DISPATCH, iOffset: VT_R8, iOrientation: VT_BOOL
    HybridBody.AppendHybridShape(iHybridShape) -> void
    Body.Sketches.Add(iPlane) -> Sketch
        iPlane: VT_DISPATCH
    Sketch.OpenEdition() -> Factory2D
    Factory2D.CreateLine(iX1, iY1, iX2, iY2) -> Line2D
    Sketch.CloseEdition() -> void
    ShapeFactory.AddNewPad(iSketch, iHeight) -> Pad
        iSketch: VT_DISPATCH, iHeight: VT_R8

No type-library signature proves that an offset-plane sketch is a valid Pad
profile; only a successful ``Part.Update()`` can establish that.  The probe
therefore does not treat a successful ``AddNewPad`` return as verification.

By default, the script only prints instructions and changes nothing.  Pass
``--run`` to opt in to temporary geometry in the active Part.  Every created
object is named with ``AUTO3DX_P33_`` plus a random token and is deleted in a
``finally`` block through ``Editor.Selection``.  The user's prior Selection
is captured and restored.  This script never calls ``Save`` or
``PLMPropagate``.
"""

from __future__ import annotations

import argparse
import math
import uuid
from dataclasses import dataclass
from typing import Any

from auto_3dx import Catia, Part


FIRST_COM_INDEX = 1
OFFSET_MM_DEFAULT = 30.0
PAD_HEIGHT_MM = 10.0
RECTANGLE_WIDTH_MM = 30.0
RECTANGLE_HEIGHT_MM = 20.0
PREFIX = "AUTO3DX_P33_"


@dataclass(frozen=True)
class SelectionState:
    """Values held in the user's Selection before this probe starts."""

    values: tuple[Any, ...]


def _ascii(value: object) -> str:
    """Returns an ASCII-safe rendering for legacy Windows consoles."""
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def _describe(com_object: Any) -> str:
    """Returns a COM wrapper's runtime type name."""
    return type(com_object).__name__


def _capture_selection(selection: Any) -> SelectionState:
    """Captures selected values before this probe changes editor UI state.

    Raises:
        RuntimeError: If a selected value cannot be read and restored safely.
    """
    values: list[Any] = []
    count = int(selection.Count)
    for index in range(FIRST_COM_INDEX, count + FIRST_COM_INDEX):
        try:
            values.append(selection.Item(index).Value)
        except Exception as error:  # noqa: BLE001 - restoration is a safety boundary
            raise RuntimeError(
                f"cannot capture Selection item {index}: "
                f"{type(error).__name__}: {_ascii(error)}"
            ) from error
    return SelectionState(tuple(values))


def _restore_selection(selection: Any, state: SelectionState) -> None:
    """Restores Selection values captured before the probe ran."""
    selection.Clear()
    for value in state.values:
        selection.Add(value)


def _delete_selected(selection: Any, target: Any, label: str) -> None:
    """Deletes one temporary object through the verified Selection route."""
    try:
        selection.Clear()
        selection.Add(target)
        selection.Delete()
        print(f"  cleanup deleted {label}")
    except Exception as error:  # noqa: BLE001 - cleanup must continue for other objects
        print(f"  cleanup could not delete {label}: {type(error).__name__}: {_ascii(error)}")
    finally:
        try:
            selection.Clear()
        except Exception as error:  # noqa: BLE001 - report UI-state cleanup failure
            print(f"  cleanup Selection.Clear failed: {type(error).__name__}: {_ascii(error)}")


def _update(raw_part: Any, stage: str) -> bool:
    """Calls ``Part.Update`` and reports success separately from creation.

    Returns:
        ``True`` only when the update completed without an exception.
    """
    try:
        raw_part.Update()
    except Exception as error:  # noqa: BLE001 - this exception is the live result
        print(f"  Part.Update after {stage}: FAILED {type(error).__name__}: {_ascii(error)}")
        return False
    print(f"  Part.Update after {stage}: OK -- VERIFIED")
    return True


def _draw_rectangle(sketch: Any) -> bool:
    """Creates a closed four-line rectangle while the Sketch is in edition."""
    factory: Any = None
    opened = False
    try:
        factory = sketch.OpenEdition()
        opened = True
        corners = (
            (0.0, 0.0, RECTANGLE_WIDTH_MM, 0.0),
            (RECTANGLE_WIDTH_MM, 0.0, RECTANGLE_WIDTH_MM, RECTANGLE_HEIGHT_MM),
            (RECTANGLE_WIDTH_MM, RECTANGLE_HEIGHT_MM, 0.0, RECTANGLE_HEIGHT_MM),
            (0.0, RECTANGLE_HEIGHT_MM, 0.0, 0.0),
        )
        for x1, y1, x2, y2 in corners:
            factory.CreateLine(x1, y1, x2, y2)
    except Exception as error:  # noqa: BLE001 - this is a live-probe result
        print(f"  sketch rectangle creation: FAILED {type(error).__name__}: {_ascii(error)}")
        return False
    finally:
        if opened:
            try:
                sketch.CloseEdition()
            except Exception as error:  # noqa: BLE001 - preserve CATIA edit state
                print(f"  Sketch.CloseEdition: FAILED {type(error).__name__}: {_ascii(error)}")
                return False
    print("  sketch rectangle creation: OK")
    return True


def _parse_args() -> argparse.Namespace:
    """Parses the opt-in mutation flag without connecting to CATIA."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        action="store_true",
        help="opt in to temporary plane/sketch/pad creation in the active Part",
    )
    parser.add_argument(
        "--offset-mm",
        type=float,
        default=OFFSET_MM_DEFAULT,
        help=f"PlaneXY offset in mm (default: {OFFSET_MM_DEFAULT:g})",
    )
    args = parser.parse_args()
    if not math.isfinite(args.offset_mm) or args.offset_mm == 0.0:
        parser.error(
            "--offset-mm must be finite and non-zero so this is not an "
            "origin-plane test"
        )
    return args


def main() -> None:
    """Runs the opt-in offset-plane Pad experiment against the active Part."""
    args = _parse_args()
    if not args.run:
        print("No mutation performed. Re-run with --run to probe an offset-plane Pad.")
        print("Document save: NOT CALLED")
        print("PLMPropagate: NOT CALLED")
        return

    catia = Catia.attach()
    editor = catia.active_editor()
    raw_part = editor.ActiveObject
    if type(raw_part).__name__ != "Part":
        raise RuntimeError(
            "The active editor is not editing a Part; "
            f"ActiveObject is {_describe(raw_part)}."
        )
    selection = editor.Selection
    part = Part(raw_part, selection=selection, editor=editor)
    original_selection = _capture_selection(selection)
    token = uuid.uuid4().hex[:8].upper()
    names = {
        "hybrid_body": f"{PREFIX}GSET_{token}",
        "plane": f"{PREFIX}PLANE_{token}",
        "sketch": f"{PREFIX}SKETCH_{token}",
        "pad": f"{PREFIX}PAD_{token}",
    }

    hybrid_body: Any = None
    offset_plane: Any = None
    sketch: Any = None
    pad: Any = None
    try:
        print(f"Part: {_ascii(part.name)}")
        print(f"Offset: {args.offset_mm:g} mm from PlaneXY")
        print("Mode: opt-in temporary geometry")

        factory = raw_part.HybridShapeFactory
        hybrid_body = raw_part.HybridBodies.Add()
        hybrid_body.Name = names["hybrid_body"]
        print(f"HybridBodies.Add: created {_describe(hybrid_body)}")

        base_plane = raw_part.OriginElements.PlaneXY
        offset_plane = factory.AddNewPlaneOffset(base_plane, args.offset_mm, False)
        offset_plane.Name = names["plane"]
        print(f"AddNewPlaneOffset: created {_describe(offset_plane)}")
        hybrid_body.AppendHybridShape(offset_plane)
        print("HybridBody.AppendHybridShape: OK")
        if not _update(raw_part, "offset-plane creation"):
            print("Sketch and Pad creation skipped because the plane did not update.")
            return

        body = raw_part.MainBody
        sketch = body.Sketches.Add(offset_plane)
        sketch.Name = names["sketch"]
        print(f"Sketches.Add(offset plane): created {_describe(sketch)}")
        if not _draw_rectangle(sketch):
            print("AddNewPad skipped because the offset-plane sketch was not created cleanly.")
            return
        if not _update(raw_part, "offset-plane sketch rectangle"):
            print("AddNewPad skipped because the sketch did not update.")
            return

        pad = raw_part.ShapeFactory.AddNewPad(sketch, PAD_HEIGHT_MM)
        pad.Name = names["pad"]
        print(f"AddNewPad(offset-plane sketch): created {_describe(pad)}")
        if not _update(raw_part, "offset-plane Pad"):
            print("  Result: Pad creation returned, but the model is NOT verified.")
    except Exception as error:  # noqa: BLE001 - report the exact first failing call
        print(f"Probe operation FAILED: {type(error).__name__}: {_ascii(error)}")
    finally:
        print("--- cleanup ---")
        # Delete children before their supporting plane and containing set.
        if pad is not None:
            _delete_selected(selection, pad, f"Pad {names['pad']!r}")
        if sketch is not None:
            _delete_selected(selection, sketch, f"Sketch {names['sketch']!r}")
        if offset_plane is not None:
            _delete_selected(selection, offset_plane, f"offset Plane {names['plane']!r}")
        if hybrid_body is not None:
            _delete_selected(selection, hybrid_body, f"HybridBody {names['hybrid_body']!r}")
        _update(raw_part, "temporary-object cleanup")
        try:
            _restore_selection(selection, original_selection)
            print("Selection restored.")
        except Exception as error:  # noqa: BLE001 - report UI-state cleanup failure
            print(f"Selection restore failed: {type(error).__name__}: {_ascii(error)}")
        print("Document save: NOT CALLED")
        print("PLMPropagate: NOT CALLED")


if __name__ == "__main__":
    main()
