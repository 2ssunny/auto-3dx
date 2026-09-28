"""Probe 46j: does a face-supported sketch's normal point out of the material?

One question only. 46i showed a sketch on the top face of a block gets the frame
(0,0,20 | X | Y), whose normal X x Y is +Z -- outward. Here the same, already verified
call (`Sketches.Add(<planar face Reference>)`) is made on the BOTTOM face (outward is -Z)
and on the +X side face (outward is +X), and only the frames are read. Nothing is drawn.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46j_face_sketch_orientation.py
"""

from _micro import (
    block_fixture,
    delete,
    marker,
    planar_face,
    require_blank_target,
    step,
    update_if_needed,
    verify_blank,
)

PREFIX = "AUTO3DX_P46J"


def cross(u: "tuple[float, ...]", v: "tuple[float, ...]") -> "tuple[float, ...]":
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    pad = None
    created = []
    try:
        pad, _ = block_fixture(part, f"{PREFIX}_BLOCK")
        cases = (
            ("BOTTOM", (0, 0, 1), (0, 0, -1), (0.0, 0.0, -1.0)),
            ("SIDE_PX", (1, 0, 0), (1, 0, 0), (1.0, 0.0, 0.0)),
        )
        faces = {label: planar_face(part, axis, direction) for label, axis, direction, _ in cases}
        sketches = step("MainBody.Sketches", lambda: raw.MainBody.Sketches)
        for label, _, _, outward in cases:
            face = faces[label]
            marker(f"[INFO] {label} centre {face.geometry.center_mm} outward {outward}")
            sketch = step(
                f"Sketches.Add({label} face Reference)",
                lambda face=face: sketches.Add(face.com_object),
                fatal=False,
            )
            if sketch is None:
                continue
            name = f"{PREFIX}_{label}_SK"
            created.append((sketch, name))
            step(
                "Sketch.Name = ...", lambda sketch=sketch, name=name: setattr(sketch, "Name", name)
            )
            frame = step(
                "Sketch.GetAbsoluteAxisData([0.0] * 9)",
                lambda sketch=sketch: sketch.GetAbsoluteAxisData([0.0] * 9),
                fatal=False,
            )
            if frame is not None:
                normal = cross(frame[3:6], frame[6:9])
                dot = sum(a * b for a, b in zip(normal, outward))
                marker(
                    f"[RESULT] {label}: normal {tuple(round(n, 6) for n in normal)}, "
                    f"dot with outward {dot:+.6f}"
                )
        step("Part.Update", raw.Update, fatal=False)
    finally:
        for sketch, name in reversed(created):
            delete(catia, sketch, name)
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
