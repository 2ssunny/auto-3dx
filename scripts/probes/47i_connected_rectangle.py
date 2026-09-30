"""Probe 47i: does a rectangle with shared corner points stay a rectangle when its width is driven?

One question only. Phase 5's "dimensioned" rectangle is four independent lines: editing
its width moves only the constrained bottom line. Here the four corners are `Point2D`s
shared by the lines (`Line2D.StartPoint`/`EndPoint` written, typelib members never used
live), with horizontal x2, vertical x2, a width and a height length, and two distance
constraints anchoring the lower-left corner to the sketch's absolute axes
(`AbsoluteAxis.VerticalReference` / `HorizontalReference`). Fixture: one sketch on XY,
corner (-30, -20), 60 x 40. After closing and one update, every line's end points and every
constraint's status are read; then the width constraint is driven 60 -> 70, updated, and
the end points are read again. A connected, anchored rectangle keeps (-30, -20) and grows
to x = 40 on BOTH the bottom and the top line.

    $env:AUTO3DX_LIVE_PART = "<disposable Part>"
    python -u scripts/probes/47i_connected_rectangle.py [x0 y0]

With `0 0` the corner sits on both sketch axes, so both anchors are distance-0 constraints.
"""

import sys
from typing import Any

from _micro import delete, marker, require_blank_target, step, sweep, update_if_needed, verify_blank

PREFIX = "AUTO3DX_P47I"
HORIZONTAL, VERTICAL, LENGTH, DISTANCE = 10, 13, 5, 1


def read_lines(lines: "dict[str, Any]") -> None:
    for label, line in lines.items():
        step(f"{label}.GetEndPoints", lambda line=line: line.GetEndPoints([0.0] * 4), fatal=False)


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    sketch = None
    try:
        plane = step("OriginElements.PlaneXY", lambda: raw.OriginElements.PlaneXY)
        sketches = step("MainBody.Sketches", lambda: raw.MainBody.Sketches)
        sketch = step("Sketches.Add(PlaneXY)", lambda: sketches.Add(plane))
        step("Sketch.Name = ...", lambda: setattr(sketch, "Name", f"{PREFIX}_SK"))
        constraints = step("Sketch.Constraints", lambda: sketch.Constraints)
        axis = step("Sketch.AbsoluteAxis", lambda: sketch.AbsoluteAxis)
        factory = step("Sketch.OpenEdition", sketch.OpenEdition)
        x0, y0 = (float(value) for value in sys.argv[1:3]) if len(sys.argv) == 3 else (-30.0, -20.0)
        marker(f"[INFO] lower-left corner ({x0}, {y0})")
        corners = [(x0, y0), (x0 + 60.0, y0), (x0 + 60.0, y0 + 40.0), (x0, y0 + 40.0)]
        points = [
            step(f"CreatePoint{corner}", lambda corner=corner: factory.CreatePoint(*corner))
            for corner in corners
        ]
        lines = {}
        for label, (a, b) in zip(
            ("bottom", "right", "top", "left"), ((0, 1), (1, 2), (2, 3), (3, 0))
        ):
            (x1, y1), (x2, y2) = corners[a], corners[b]
            line = step(
                f"CreateLine {label}",
                lambda x1=x1, y1=y1, x2=x2, y2=y2: factory.CreateLine(x1, y1, x2, y2),
            )
            step(
                f"{label}.StartPoint = p{a}",
                lambda line=line, a=a: setattr(line, "StartPoint", points[a]),
            )
            step(
                f"{label}.EndPoint = p{b}",
                lambda line=line, b=b: setattr(line, "EndPoint", points[b]),
            )
            lines[label] = line
        made = []
        for label, kind, line in (
            ("H bottom", HORIZONTAL, lines["bottom"]),
            ("H top", HORIZONTAL, lines["top"]),
            ("V right", VERTICAL, lines["right"]),
            ("V left", VERTICAL, lines["left"]),
        ):
            made.append(
                step(
                    f"AddMonoEltCst({label})",
                    lambda kind=kind, line=line: constraints.AddMonoEltCst(kind, line),
                )
            )
        width = step(
            "AddMonoEltCst(length bottom)",
            lambda: constraints.AddMonoEltCst(LENGTH, lines["bottom"]),
        )
        height = step(
            "AddMonoEltCst(length left)", lambda: constraints.AddMonoEltCst(LENGTH, lines["left"])
        )
        vertical_axis = step("AbsoluteAxis.VerticalReference", lambda: axis.VerticalReference)
        horizontal_axis = step("AbsoluteAxis.HorizontalReference", lambda: axis.HorizontalReference)
        x_anchor = step(
            "AddBiEltCst(distance p0, V axis)",
            lambda: constraints.AddBiEltCst(DISTANCE, points[0], vertical_axis),
            fatal=False,
        )
        y_anchor = step(
            "AddBiEltCst(distance p0, H axis)",
            lambda: constraints.AddBiEltCst(DISTANCE, points[0], horizontal_axis),
            fatal=False,
        )
        made += [width, height] + [c for c in (x_anchor, y_anchor) if c is not None]
        step("Sketch.CloseEdition", sketch.CloseEdition)
        marker("[EDITION] closed")
        step("Part.Update", raw.Update, fatal=False)
        step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw)), fatal=False)
        read_lines(lines)
        for constraint in made:
            step("Constraint.Name", lambda c=constraint: str(c.Name), fatal=False)
            step("Constraint.Status", lambda c=constraint: int(c.Status), fatal=False)
            step("Constraint.Dimension.Value", lambda c=constraint: c.Dimension.Value, fatal=False)
        step("width Dimension.Value = 70", lambda: setattr(width.Dimension, "Value", 70.0))
        step("Part.Update (width 70)", raw.Update, fatal=False)
        step("Part.IsUpToDate", lambda: bool(raw.IsUpToDate(raw)), fatal=False)
        read_lines(lines)
        marker(
            "[RESULT] connected and anchored if bottom AND top now end at x = 40, corner stays (-30, -20)"
        )
    finally:
        if sketch is not None:
            delete(catia, sketch, f"{PREFIX}_SK")
        sweep(catia, part, PREFIX)
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
