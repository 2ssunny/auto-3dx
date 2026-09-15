"""Probe the argument and observable status semantics of ``Part.IsUpToDate``.

The local generated pywin32 wrapper is the source of the call signature:

    Part.IsUpToDate(self, iObject=defaultNamedNotOptArg) -> VT_BOOL
    iObject -> VT_DISPATCH, the generic CATBaseDispatch interface

The type-library vtable also lists an ``oValue`` VT_BYREF|VT_BOOL output. The
generated wrapper exposes only ``iObject`` and returns the COM result, so this
probe records the actual Python value without assuming whether it is a bool or
an out-parameter tuple. The related ``UpdateObject(iObject)`` signature is
reported but never called because its mutation semantics are not verified.

The probe first tests the Part and MainBody dispatch objects already present in
the active editor. It then changes a temporary user Length parameter and calls
the status method before and after ``Part.Update()``. It also creates a
temporary XY rectangle and Pad, updates them successfully, and repeats the
transition with the Pad height parameter while querying Part, MainBody, Pad,
and Sketch. All temporary objects are removed through ``Editor.Selection``.
The probe never calls ``Save`` or ``PLMPropagate``.
"""

from __future__ import annotations

import argparse
import inspect
import uuid
from typing import Any

from pywintypes import com_error

from auto_3dx import Catia, Part


FIRST_COM_INDEX = 1
SKETCH_WIDTH_MM = 20.0
SKETCH_HEIGHT_MM = 15.0
PAD_HEIGHT_INITIAL_MM = 10.0
PAD_HEIGHT_CHANGED_MM = 17.0
TEMP_PARAMETER_INITIAL = 10.0
TEMP_PARAMETER_CHANGED = 20.0
TEMP_PREFIX = "AUTO3DX_P32_"


def _parse_args() -> argparse.Namespace:
    """Parses the explicit mutation opt-in without connecting to CATIA."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        action="store_true",
        help="opt in to temporary parameter or geometry mutation in the active Part",
    )
    return parser.parse_args()


def _ascii(value: Any) -> str:
    """Returns an ASCII-safe representation for console output."""
    return ascii(str(value))


def _error_text(error: BaseException) -> str:
    """Formats an exception without allowing non-ASCII COM text into output."""
    hresult = getattr(error, "hresult", None)
    if isinstance(hresult, int):
        return f"{type(error).__name__} hresult=0x{hresult & 0xFFFFFFFF:08X}"
    return f"{type(error).__name__}: {_ascii(error)}"


def _method_definition(com_object: Any, method_name: str) -> Any:
    """Finds a generated-wrapper method definition in the object's MRO."""
    for wrapper_type in type(com_object).__mro__:
        method = wrapper_type.__dict__.get(method_name)
        if callable(method):
            return method
    return None


def _report_api_surface(part: Any) -> None:
    """Prints generated-wrapper evidence for update-related methods."""
    print("Type-library evidence:")
    print("  IsUpToDate iObject: VT_DISPATCH / generic CATBaseDispatch")
    print("  IsUpToDate result: VT_BOOL")
    print("  IsUpToDate vtable output: oValue VT_BYREF|VT_BOOL")
    print("  UpdateObject iObject: VT_DISPATCH / generic CATBaseDispatch")
    print("  UpdateObject result: VT_VOID")
    for method_name in ("IsUpToDate", "UpdateObject", "Update"):
        method = _method_definition(part, method_name)
        if method is None:
            print(f"  generated {method_name} signature: unavailable")
            continue
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError) as error:
            print(f"  generated {method_name} signature: unavailable ({_error_text(error)})")
        else:
            print(f"  generated {method_name} signature: {_ascii(signature)}")


def _call_is_up_to_date(part: Any, label: str, target: Any) -> bool:
    """Calls ``IsUpToDate`` once and reports the raw Python result.

    The return value means only that the COM call completed without an
    exception. It deliberately does not assign engineering meaning to the
    returned value.
    """
    try:
        value = part.IsUpToDate(target)
    except com_error as error:
        print(f"  {label}: FAILED {_error_text(error)}")
        print(f"    details: {_ascii(getattr(error, 'excepinfo', None))}")
        return False
    except Exception as error:  # noqa: BLE001 - a probe reports every candidate form
        print(f"  {label}: FAILED {_error_text(error)}")
        return False
    print(f"  {label}: returned type={type(value).__name__}, value={_ascii(value)}")
    return True


def _report_statuses(
    raw_part: Any,
    body: Any,
    stage: str,
    pad: Any = None,
    sketch: Any = None,
) -> dict[str, bool]:
    """Reports conservative dispatch candidates at one named stage."""
    print()
    print(f"--- IsUpToDate candidates: {stage} ---")
    candidates: list[tuple[str, Any]] = [
        ("Part", raw_part),
        ("MainBody", body),
    ]
    if pad is not None:
        candidates.append(("temporary Pad", pad))
    if sketch is not None:
        candidates.append(("temporary Sketch", sketch))
    return {
        label: _call_is_up_to_date(raw_part, label, target)
        for label, target in candidates
    }


def _delete_selected(selection: Any, target: Any, label: str) -> None:
    """Deletes one object through the verified Selection route."""
    try:
        selection.Clear()
        selection.Add(target)
        selection.Delete()
        print(f"  cleanup deleted {label}")
    except Exception as error:  # noqa: BLE001 - cleanup must report and continue
        print(f"  cleanup could not delete {label}: {_error_text(error)}")
    finally:
        try:
            selection.Clear()
        except Exception as error:  # noqa: BLE001 - preserve the cleanup report
            print(f"  cleanup Selection.Clear failed: {_error_text(error)}")


def _capture_selection(selection: Any) -> "tuple[Any, ...]":
    """Captures the user's current selection before this probe changes it."""
    return tuple(
        selection.Item(index).Value
        for index in range(FIRST_COM_INDEX, int(selection.Count) + FIRST_COM_INDEX)
    )


def _restore_selection(selection: Any, values: "tuple[Any, ...]") -> None:
    """Restores the user's selection after all probe cleanup has finished."""
    selection.Clear()
    for value in values:
        selection.Add(value)


def _find_named(collection: Any, name: str) -> Any:
    """Finds an exact name in a one-based COM collection, or returns None."""
    try:
        count = int(collection.Count)
    except Exception:
        return None
    for index in range(FIRST_COM_INDEX, count + FIRST_COM_INDEX):
        try:
            item = collection.Item(index)
            if str(item.Name) == name:
                return item
        except Exception:
            continue
    return None


def _cleanup_geometry(
    selection: Any,
    body: Any,
    sketch_name: str,
    pad_name: str,
) -> None:
    """Removes temporary Pad first, then any remaining temporary Sketch."""
    pad = _find_named(body.Shapes, pad_name)
    if pad is not None:
        _delete_selected(selection, pad, f"Pad {pad_name!r}")
    sketch = _find_named(body.Sketches, sketch_name)
    if sketch is not None:
        _delete_selected(selection, sketch, f"Sketch {sketch_name!r}")


def _run_parameter_transition(part: Any, raw_part: Any, body: Any, name: str) -> None:
    """Tests status around a temporary user-parameter mutation."""
    parameter: Any = None
    try:
        parameter = part.parameters.create_length(name, TEMP_PARAMETER_INITIAL)
        _report_statuses(raw_part, body, "after temporary parameter creation")
        parameter.set(TEMP_PARAMETER_CHANGED)
        _report_statuses(raw_part, body, "after parameter change, before Part.Update")
        try:
            part.update()
            print("Part.Update after parameter change: OK")
        except Exception as error:  # noqa: BLE001 - report the live result
            print(f"Part.Update after parameter change: FAILED {_error_text(error)}")
        _report_statuses(raw_part, body, "after Part.Update")
    finally:
        if parameter is not None:
            try:
                parameter.set(TEMP_PARAMETER_INITIAL)
                print("temporary parameter value restored")
            except Exception as error:  # noqa: BLE001 - cleanup must continue
                print(f"temporary parameter restore failed: {_error_text(error)}")
        try:
            part.parameters.remove(name)
            print("temporary parameter removed")
        except Exception as error:  # noqa: BLE001 - cleanup must report
            print(f"temporary parameter removal failed: {_error_text(error)}")
        try:
            part.update()
            print("Part.Update after parameter cleanup: OK")
        except Exception as error:  # noqa: BLE001 - cleanup must report
            print(f"Part.Update after parameter cleanup: FAILED {_error_text(error)}")


def _run_geometry_transition(
    part: Any,
    raw_part: Any,
    body: Any,
    selection: Any,
    sketch_name: str,
    pad_name: str,
) -> None:
    """Creates verified temporary geometry and tests a Pad parameter mutation."""
    sketch: Any = None
    pad: Any = None
    try:
        print()
        print("Temporary geometry: testing a feature-driven dirty-state transition.")
        sketch = part.sketches.create(sketch_name, support="XY")
        with sketch.edit() as editor:
            editor.rectangle(SKETCH_WIDTH_MM, SKETCH_HEIGHT_MM)
        part.update()
        pad = part.part_design.create_pad(pad_name, sketch, PAD_HEIGHT_INITIAL_MM)
        part.update()
        print("temporary Sketch and Pad: created and Part.Update succeeded")
        _report_statuses(
            raw_part,
            body,
            "verified temporary geometry baseline",
            pad=pad.com_object,
            sketch=sketch.com_object,
        )
        pad.set_height(PAD_HEIGHT_CHANGED_MM)
        _report_statuses(
            raw_part,
            body,
            "after Pad height parameter change, before Part.Update",
            pad=pad.com_object,
            sketch=sketch.com_object,
        )
        part.update()
        print("Part.Update after Pad height change: OK")
        _report_statuses(
            raw_part,
            body,
            "after Part.Update for Pad height",
            pad=pad.com_object,
            sketch=sketch.com_object,
        )
    except Exception as error:  # noqa: BLE001 - a probe reports the live route
        print(f"temporary geometry transition failed: {_error_text(error)}")
    finally:
        if pad is not None:
            try:
                pad.set_height(PAD_HEIGHT_INITIAL_MM)
                part.update()
                print("temporary Pad height restored")
            except Exception as error:  # noqa: BLE001 - cleanup must continue
                print(f"temporary Pad restore failed: {_error_text(error)}")
        _cleanup_geometry(selection, body, sketch_name, pad_name)
        try:
            part.update()
            print("Part.Update after geometry cleanup: OK")
        except Exception as error:  # noqa: BLE001 - cleanup must report
            print(f"Part.Update after geometry cleanup: FAILED {_error_text(error)}")


def main() -> None:
    """Runs the update-status probe against the active Part without saving."""
    args = _parse_args()
    if not args.run:
        print("No mutation performed. Re-run with --run to probe IsUpToDate transitions.")
        print("Document save: NOT CALLED")
        print("PLMPropagate: NOT CALLED")
        return

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
    body = raw_part.MainBody
    original_selection = _capture_selection(selection)

    try:
        print(f"Part: {_ascii(part.name)}")
        _report_api_surface(raw_part)
        _report_statuses(raw_part, body, "baseline")
        token = uuid.uuid4().hex[:8].upper()
        parameter_name = f"{TEMP_PREFIX}LENGTH_{token}"
        sketch_name = f"{TEMP_PREFIX}SKETCH_{token}"
        pad_name = f"{TEMP_PREFIX}PAD_{token}"

        _run_parameter_transition(part, raw_part, body, parameter_name)
        _run_geometry_transition(
            part,
            raw_part,
            body,
            selection,
            sketch_name,
            pad_name,
        )
    finally:
        try:
            _restore_selection(selection, original_selection)
            print("Selection restored.")
        except Exception as error:  # noqa: BLE001 - report UI-state cleanup failure
            print(f"Selection restore failed: {_error_text(error)}")
        print("Document save: NOT CALLED")
        print("PLMPropagate: NOT CALLED")


if __name__ == "__main__":
    main()
