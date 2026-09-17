"""Probe the Multi-Body path: bodies, In-Work Body targeting, visibility and deletion.

Type-library facts this starts from (0D90A5C9-3B08-11D1-A26C-0000F87546FD, 14F197B2-...):

    Part.Bodies: Add(), Item(i), Count, GetItem(name)
    Body: Name (r/w), Shapes, Sketches, HybridBodies, HybridShapes, InBooleanOperation
    Part.InWorkObject (r/w)
    Selection.VisProperties -> VisPropertySet: SetShow(iShow), GetShow(oShow)
        CatVisPropertyShow: catVisPropertyShowAttr = 0, catVisPropertyNoShowAttr = 1

What the SDK needs to know before any of it becomes public: what `Bodies.Add()` returns
and how the In-Work Object moves; whether an assigned In-Work Body sticks; which body a
sketch lands in through `Body.Sketches.Add` and through `MainBody.Sketches.Add` while
another body is in work; whether `ShapeFactory.AddNewPad`/`AddNewPocket` build inside the
In-Work Body; whether `VisProperties.SetShow` hides a body, reads back, and leaves its
geometry alone; and what deleting a body takes with it.

Safety: this probe mutates, so it runs only when the active window's title is exactly
`AUTO3DX_LIVE_PART`, and it works only on the active Part (Selection-based deletion and
visibility act on the active editor). Everything it creates is prefixed `AUTO3DX_P41_`
and removed in `finally`; the In-Work Object and selection are restored. Never saves.
"""

import os
import sys
from typing import Any

from auto_3dx import Catia
from auto_3dx.geometry.sketch import Sketch

PART_ENV_VAR = "AUTO3DX_LIVE_PART"
PREFIX = "AUTO3DX_P41_"
BODY_A, BODY_B = f"{PREFIX}BODY_A", f"{PREFIX}BODY_B"
SHOW, NO_SHOW = 0, 1
_FAILED = object()


def attempt(label: str, call: Any) -> Any:
    try:
        value = call()
    except Exception as error:  # noqa: BLE001 - probing
        print(f"  {label}: FAILED {type(error).__name__}: {str(error)[:150]}")
        return _FAILED
    print(f"  {label}: {value!r}"[:230])
    return value


def names(collection: Any) -> "list[tuple[str, str]]":
    return [
        (str(collection.Item(i).Name), type(collection.Item(i)).__name__)
        for i in range(1, int(collection.Count) + 1)
    ]


def body_named(raw_part: Any, name: str) -> Any:
    bodies = raw_part.Bodies
    for index in range(1, int(bodies.Count) + 1):
        if bodies.Item(index).Name == name:
            return bodies.Item(index)
    return None


def in_work(raw_part: Any) -> str:
    obj = raw_part.InWorkObject
    return f"{type(obj).__name__} {obj.Name!r}"


def tree(raw_part: Any) -> None:
    bodies = raw_part.Bodies
    for index in range(1, int(bodies.Count) + 1):
        body = bodies.Item(index)
        print(
            f"    body {body.Name!r} main={bool(body == raw_part.MainBody)} "
            f"shapes={names(body.Shapes)} sketches={names(body.Sketches)}"
        )


def rectangle_sketch(
    body: Any, raw_part: Any, name: str, origin_x: float, side: float
) -> Any:
    raw_sketch = body.Sketches.Add(raw_part.OriginElements.PlaneXY)
    raw_sketch.Name = name
    with Sketch(raw_sketch).edit() as editor:
        editor.rectangle(side, side, origin_x=origin_x)
    return raw_sketch


def show_state(selection: Any, body: Any) -> Any:
    selection.Clear()
    selection.Add(body)
    state = attempt(f"GetShow({body.Name})", lambda: selection.VisProperties.GetShow())
    selection.Clear()
    return state


def delete(selection: Any, obj: Any) -> None:
    selection.Clear()
    selection.Add(obj)
    selection.Delete()
    selection.Clear()


def main() -> None:
    target = os.environ.get(PART_ENV_VAR, "").strip()
    if not target:
        sys.exit(
            f"Refusing to run: set {PART_ENV_VAR} to the disposable test Part's title."
        )
    catia = Catia.attach()
    caption = str(catia.com_object.ActiveWindow.Caption)
    part = catia.active_part()
    if caption != target and part.name != target:
        sys.exit(
            f"Refusing to run: active window {caption!r} / Part {part.name!r} is not {target!r}."
        )
    raw = part.com_object
    selection = catia.active_editor().Selection
    main_body = raw.MainBody
    original_in_work = raw.InWorkObject
    print("target:", caption, "/", part.name)
    print("baseline tree:")
    tree(raw)
    print("baseline in-work:", in_work(raw), "| selection count:", selection.Count)

    try:
        print("\n=== 1. Bodies.Add ===")
        body_a = attempt("Bodies.Add()", lambda: raw.Bodies.Add())
        print("  type:", type(body_a).__name__, "| default name:", body_a.Name)
        print("  in-work after Add:", in_work(raw))
        body_a.Name = BODY_A
        print("  renamed:", body_a.Name, "| Bodies.Count:", raw.Bodies.Count)
        attempt("InBooleanOperation", lambda: body_a.InBooleanOperation)
        found = body_named(raw, BODY_A)
        print("  Bodies.Item(i) by name == Add() result:", bool(found == body_a))
        print("  MainBody still PartBody:", main_body.Name)

        print("\n=== 2. Assign the In-Work Object ===")
        raw.InWorkObject = main_body
        print("  set MainBody ->", in_work(raw))
        raw.InWorkObject = body_a
        print(
            "  set BODY_A   ->",
            in_work(raw),
            "| == body_a:",
            bool(raw.InWorkObject == body_a),
        )

        print("\n=== 3. Where sketches land ===")
        sketch_a = rectangle_sketch(body_a, raw, f"{PREFIX}BODY_A_SKETCH", 0.0, 20.0)
        print("  body_a.Sketches.Add while BODY_A in work:")
        tree(raw)
        print("  in-work after sketch:", in_work(raw))
        raw.InWorkObject = body_a
        stray = attempt(
            "MainBody.Sketches.Add while BODY_A in work",
            lambda: main_body.Sketches.Add(raw.OriginElements.PlaneYZ),
        )
        if stray is not _FAILED:
            stray.Name = f"{PREFIX}STRAY_SKETCH"
            tree(raw)
            delete(selection, stray)
            print("  stray sketch deleted")

        print("\n=== 4. Pad A with BODY_A in work ===")
        raw.InWorkObject = body_a
        pad_a = attempt(
            "AddNewPad(sketch_a, 10)",
            lambda: raw.ShapeFactory.AddNewPad(sketch_a, 10.0),
        )
        pad_a.Name = f"{PREFIX}BODY_A_PAD"
        print("  in-work after pad:", in_work(raw))
        attempt("part.update()", part.update)
        print("  up_to_date:", part.is_up_to_date())
        tree(raw)
        attempt(
            "measure BODY_A volume", lambda: part.measurement.measure(body_a).volume_mm3
        )

        print("\n=== 5. Body B with a pad and a pocket ===")
        body_b = raw.Bodies.Add()
        body_b.Name = BODY_B
        raw.InWorkObject = body_b
        sketch_b = rectangle_sketch(body_b, raw, f"{PREFIX}BODY_B_SKETCH", 100.0, 30.0)
        pad_b = raw.ShapeFactory.AddNewPad(sketch_b, 12.0)
        pad_b.Name = f"{PREFIX}BODY_B_PAD"
        attempt("update after pad B", part.update)
        raw.InWorkObject = body_b
        hole_b = rectangle_sketch(
            body_b, raw, f"{PREFIX}BODY_B_POCKET_SKETCH", 110.0, 10.0
        )
        pocket_b = attempt(
            "AddNewPocket(hole_b, 5)",
            lambda: raw.ShapeFactory.AddNewPocket(hole_b, 5.0),
        )
        if pocket_b is not _FAILED:
            pocket_b.Name = f"{PREFIX}BODY_B_POCKET"
        attempt("update after pocket B", part.update)
        print("  up_to_date:", part.is_up_to_date())
        tree(raw)
        volume_a = attempt(
            "volume A", lambda: part.measurement.measure(body_a).volume_mm3
        )
        attempt("volume B", lambda: part.measurement.measure(body_b).volume_mm3)
        attempt(
            "volume MainBody (empty)",
            lambda: part.measurement.measure(main_body).volume_mm3,
        )

        print("\n=== 6. Visibility through Selection.VisProperties ===")
        show_state(selection, body_a)
        show_state(selection, body_b)
        selection.Clear()
        selection.Add(body_a)
        attempt(
            "SetShow(NO_SHOW) on BODY_A",
            lambda: selection.VisProperties.SetShow(NO_SHOW),
        )
        attempt(
            "GetShow while still selected", lambda: selection.VisProperties.GetShow()
        )
        selection.Clear()
        print("  after hide, reselected:")
        show_state(selection, body_a)
        show_state(selection, body_b)
        attempt(
            "volume A while hidden", lambda: part.measurement.measure(body_a).volume_mm3
        )
        print("  up_to_date while hidden:", part.is_up_to_date())
        selection.Clear()
        selection.Add(body_a)
        attempt(
            "SetShow(SHOW) on BODY_A", lambda: selection.VisProperties.SetShow(SHOW)
        )
        selection.Clear()
        print("  after show:")
        show_state(selection, body_a)
        attempt(
            "volume A after show", lambda: part.measurement.measure(body_a).volume_mm3
        )
        print("  volume A unchanged:", volume_a)

        print("\n=== 7. Delete BODY_B, see what goes with it ===")
        delete(selection, body_b)
        tree(raw)
        attempt("update after deleting BODY_B", part.update)
    finally:
        print("\n=== cleanup: only AUTO3DX_P41_ bodies ===")
        for name in (BODY_B, BODY_A):
            body = body_named(raw, name)
            if body is not None:
                try:
                    delete(selection, body)
                    print("  deleted", name)
                except Exception as error:  # noqa: BLE001 - probing
                    print("  delete FAILED", name, type(error).__name__, error)
        try:
            raw.InWorkObject = original_in_work
        except Exception as error:  # noqa: BLE001 - probing
            print("  in-work restore FAILED", type(error).__name__, error)
        selection.Clear()
        try:
            part.update()
        except Exception as error:  # noqa: BLE001 - probing
            print("  final update FAILED", type(error).__name__, error)

    print("\nfinal tree:")
    tree(raw)
    print("final in-work:", in_work(raw), "| selection count:", selection.Count)
    print("final up_to_date:", part.is_up_to_date())
    print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
