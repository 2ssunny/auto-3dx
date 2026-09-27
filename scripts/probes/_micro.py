"""Shared scaffolding for the Phase 5 micro-probes (`46*_*.py`).

Probe 46 was first written as one large probe; its first stage left 3DEXPERIENCE busy
and unresponsive, and because its output was buffered the call that caused it was never
identified. Every Phase 5 probe is therefore a micro-probe that answers one narrow
question, and every Automation call it makes goes through `step()`, which prints and
flushes a marker immediately before and immediately after the call. If CATIA hangs, the
last `BEFORE` marker without a matching `AFTER` names the call.

Rules each micro-probe follows:

1. verify the exact target Part (`AUTO3DX_LIVE_PART`) and that it is the blank baseline
   before any mutation (`require_blank_target`);
2. create the smallest fixture that can answer its question;
3. test one uncertain capability;
4. remove what it created and prove the Part is blank again (`verify_blank`).

Nothing here saves, propagates or exports. Run with `python -u`.
"""

import os
import sys
import time
from typing import Any

from auto_3dx import Auto3dxError, Catia

_step_number = 0


def marker(text: str) -> None:
    """Prints one progress line and flushes it at once."""
    print(text, flush=True)


def step(label: str, call: Any, *, fatal: bool = True) -> Any:
    """Runs one Automation call between flushed BEFORE and AFTER markers.

    Args:
        label: What is being called, for example `"Line2D.GetEndPoints"`.
        call: A zero-argument callable making exactly one Automation call.
        fatal: Re-raise a failure (the default). With `False` the failure is printed
            and `None` is returned, for calls whose failure is itself the answer.

    Returns:
        Whatever the call returned.
    """
    global _step_number
    _step_number += 1
    number = f"{_step_number:02d}"
    marker(f"[STEP {number} BEFORE] {label}")
    started = time.perf_counter()
    try:
        result = call()
    except BaseException as error:
        elapsed = time.perf_counter() - started
        marker(f"[STEP {number} FAILED] {label} after {elapsed:.3f}s: "
               f"{type(error).__name__}: {str(error)[:200]}")
        if fatal:
            raise
        return None
    elapsed = time.perf_counter() - started
    marker(f"[STEP {number} AFTER] {label} ({elapsed:.3f}s): {_render(result)}")
    return result


def _render(value: Any) -> str:
    """Short, COM-safe text for a result."""
    if value is None or isinstance(value, (bool, int, float, str, tuple, list)):
        return repr(value)[:200]
    return f"<{type(value).__name__}>"


def require_blank_target() -> "tuple[Any, Any]":
    """Attaches, checks the target Part and that it is the blank baseline.

    Returns:
        `(catia, part)` for the active Part, which is the one `AUTO3DX_LIVE_PART` names.
    """
    target = os.environ.get("AUTO3DX_LIVE_PART", "").strip()
    if not target:
        sys.exit("Refusing to run: set AUTO3DX_LIVE_PART to the disposable test Part.")
    catia = step("Catia.attach", Catia.attach)
    part = step("Catia.active_part", catia.active_part)
    name = step("Part.Name", lambda: part.name)
    title = step("active window title", lambda: catia.active_window_title)
    if target not in (name, title):
        sys.exit(f"Refusing to run: the active Part is {name!r} ({title!r}), not {target!r}.")
    problems = blank_problems(part)
    if problems:
        sys.exit(f"Refusing to run: the target is not the blank baseline: {problems}")
    marker(f"[TARGET] {name} is active, blank and up to date")
    return catia, part


def blank_problems(part: Any) -> "list[str]":
    """Lists every way the Part differs from the blank baseline (empty when blank)."""
    raw = part.com_object
    problems = []
    body_count = step("Part.Bodies.Count", lambda: int(raw.Bodies.Count))
    if body_count != 1:
        problems.append(f"{body_count} bodies")
    main = step("Part.MainBody", lambda: raw.MainBody)
    shapes = step("MainBody.Shapes.Count", lambda: int(main.Shapes.Count))
    sketches = step("MainBody.Sketches.Count", lambda: int(main.Sketches.Count))
    sets = step("Part.HybridBodies.Count", lambda: int(raw.HybridBodies.Count))
    relations = step("Part.Relations.Count", lambda: int(raw.Relations.Count))
    up_to_date = step("Part.IsUpToDate", lambda: part.is_up_to_date())
    if shapes:
        problems.append(f"{shapes} features")
    if sketches:
        problems.append(f"{sketches} sketches")
    if sets:
        problems.append(f"{sets} geometrical sets")
    if relations:
        problems.append(f"{relations} relations")
    if not up_to_date:
        problems.append("not up to date")
    return problems


def verify_blank(part: Any) -> bool:
    """Reports whether the Part is back at the blank baseline."""
    problems = blank_problems(part)
    if problems:
        marker(f"[BASELINE] NOT blank: {problems}")
        return False
    marker("[BASELINE] blank: 1 body, 0 features, 0 sketches, 0 sets, 0 relations, up to date")
    return True


def delete(catia: Any, item: Any, label: str) -> None:
    """Deletes one object through the editor selection, one marked call at a time."""
    selection = step("Editor.Selection", lambda: catia.active_editor().Selection)
    step("Selection.Clear", selection.Clear)
    step(f"Selection.Add({label})", lambda: selection.Add(item))
    step("Selection.Delete", selection.Delete)
    step("Selection.Clear", selection.Clear)


__all__ = [
    "Auto3dxError",
    "delete",
    "marker",
    "require_blank_target",
    "step",
    "verify_blank",
]


def block_fixture(part: Any, name: str, length: float = 60.0, width: float = 40.0,
                  height: float = 20.0) -> "tuple[Any, Any]":
    """Builds the smallest solid a face question needs: one centred block, rebuilt.

    Every Automation call is marked. The route (sketch on XY, four lines, pad, update) is
    the one verified since probe 12.

    Returns:
        `(raw_pad, raw_sketch)`. Deleting the pad deletes its sketch with it.
    """
    raw = part.com_object
    plane = step("OriginElements.PlaneXY", lambda: raw.OriginElements.PlaneXY)
    sketches = step("MainBody.Sketches", lambda: raw.MainBody.Sketches)
    sketch = step("Sketches.Add(PlaneXY)", lambda: sketches.Add(plane))
    step("Sketch.Name = ...", lambda: setattr(sketch, "Name", f"{name}_SK"))
    factory = step("Sketch.OpenEdition", sketch.OpenEdition)
    x0, y0, x1, y1 = -length / 2, -width / 2, length / 2, width / 2
    for a, b, c, d in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)):
        step(f"Factory2D.CreateLine({a}, {b}, {c}, {d})",
             lambda a=a, b=b, c=c, d=d: factory.CreateLine(a, b, c, d))
    step("Sketch.CloseEdition", sketch.CloseEdition)
    shape_factory = step("Part.ShapeFactory", lambda: raw.ShapeFactory)
    pad = step(f"ShapeFactory.AddNewPad(sketch, {height})",
               lambda: shape_factory.AddNewPad(sketch, height))
    step("Pad.Name = ...", lambda: setattr(pad, "Name", name))
    step("Part.Update", raw.Update)
    return pad, sketch


def update_if_needed(part: Any) -> None:
    """Rebuilds once after cleanup when CATIA reports the Part out of date."""
    raw = part.com_object
    if not step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw))):
        step("Part.Update", raw.Update)


def planar_face(part: Any, axis: "tuple[float, float, float]",
                direction: "tuple[float, float, float]") -> Any:
    """Finds one planar face with the verified Phase 4 query, marked as one composite step.

    `part.topology.faces()` and `query()` are live-verified SDK paths (probe 45). They make
    many Automation calls, so this marks the composite rather than each call.
    """
    return step(
        f"[composite, verified] topology.faces().query().planar().normal_parallel({axis})"
        f".extreme({direction}).one()",
        lambda: part.topology.faces(body=None).query().planar().normal_parallel(axis)
        .extreme(direction).one(),
    )


def sweep(catia: Any, part: Any, prefix: str) -> None:
    """Deletes any feature or sketch this probe left behind, matched by its name prefix.

    Probe 46u showed that deleting a pad does not always take its sketch with it (after the
    pad's face had served as a pattern axis), so cleanup does not rely on cascades.
    """
    raw = part.com_object
    for collection in ("Shapes", "Sketches"):
        items = step(f"MainBody.{collection}", lambda collection=collection:
                     getattr(raw.MainBody, collection))
        count = step(f"{collection}.Count", lambda items=items: int(items.Count))
        leftovers = []
        for index in range(count, 0, -1):
            item = step(f"{collection}.Item({index})", lambda index=index, items=items:
                        items.Item(index))
            name = step("Item.Name", lambda item=item: str(item.Name))
            if name.startswith(prefix):
                leftovers.append((item, name))
        for item, name in leftovers:
            marker(f"[SWEEP] {collection[:-1].lower()} {name} was left behind")
            delete(catia, item, name)
