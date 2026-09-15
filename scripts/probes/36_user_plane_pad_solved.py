"""Probe the two things that were blocking sketches on user-defined planes.

Probe 29 built an offset plane, appended it to a geometrical set, and created a
sketch on it -- all updating fine -- and then `AddNewPad` on that sketch failed.
Probe 33 reproduced the failure exactly. Neither found the cause.

The cause is the in-work object. `HybridBodies.Add()` makes the NEW geometrical
set the Part's in-work object, and a pad cannot be inserted into a geometrical
set, so `AddNewPad` is rejected before any question of the plane arises. Setting
`Part.InWorkObject` back to the body makes the same call succeed and update.
Nothing about the plane was ever wrong.

The angled plane had a second, unrelated cause. `AddNewPlaneAngle` needs an
addressable 3D line for its rotation axis. Probe 29 passed a `Line2D` from
inside a sketch and a later attempt passed an origin plane; both created an
object whose update failed. A line through two constructed points works.

Both families are now verified end to end -- plane, then sketch, then pad, with
`Part.Update()` succeeding at each step, which is this project's bar for
verified (`docs/conventions.md` 1.2.2.1).

Signatures, from `87EE735C-DF70-11D1-8556-0060941979CEx0x0x0.py`:

    HybridShapeFactory.AddNewPlaneOffset(iPlane, iOffset, iOrientation)
        -> HybridShapePlaneOffset
    HybridShapeFactory.AddNewPlaneAngle(iPlane, iRevolAxis, iAngle, iOrientation)
        -> HybridShapePlaneAngle
    HybridShapeFactory.AddNewPointCoord(iX, iY, iZ) -> HybridShapePointCoord
    HybridShapeFactory.AddNewLinePtPt(iPtOrigine, iPtExtremite) -> HybridShapeLinePtPt

and from `0D90A5C9-3B08-11D1-A26C-0000F87546FDx0x0x0.py`:

    Part.InWorkObject -> AnyObject        (readable AND writable)
    Part.HybridBodies -> HybridBodies ; HybridBodies.Add() -> HybridBody
    HybridBody.AppendHybridShape(iHybridShape) -> void
    Body.Sketches.Add(iPlane) -> Sketch   (takes the raw hybrid shape directly)

Creates and removes content in the ACTIVE Part, restores the original in-work
object, and never saves.
"""

from typing import Any

from auto_3dx import Catia
from auto_3dx.errors import Auto3dxError

PREFIX = "AUTO3DX_P36_"
PLANE_OFFSET = 30.0
PLANE_ANGLE = 30.0
AXIS_LENGTH = 100.0
RECTANGLE_SIDE = 20.0
PAD_HEIGHT = 10.0


def describe(com_object: Any) -> str:
    """Returns a COM wrapper's type name."""
    return type(com_object).__name__


def attempt(label: str, action: Any) -> Any:
    """Runs one experiment and reports the outcome without stopping the probe."""
    try:
        result = action()
    except Exception as error:  # noqa: BLE001 - probing the real failure mode
        print(f"  {label}: FAILED {type(error).__name__}: {str(error)[:100]}")
        return None
    if result is None:
        print(f"  {label}: OK")
    else:
        print(f"  {label}: OK -> {describe(result)}")
    return result


class Probe:
    """Holds the session objects every step needs, and tracks what to clean up."""

    def __init__(self) -> None:
        """Attaches to the running session and captures the original state."""
        catia = Catia.attach()
        self.part = catia.active_part()
        self.raw = self.part.com_object
        self.body = self.raw.MainBody
        self.hybrid_shape_factory = self.raw.HybridShapeFactory
        self.shape_factory = self.raw.ShapeFactory
        self.selection = catia.active_editor().Selection
        self.original_in_work_object = self.raw.InWorkObject
        self.created: list[Any] = []

    def update(self, label: str) -> bool:
        """Updates the Part and reports whether it succeeded.

        `Part.Update()` returns `None` on success, so success cannot be told
        from failure by return value alone -- hence a boolean of its own.
        """
        try:
            self.part.update()
        except Auto3dxError as error:
            print(f"    update after {label}: FAILED {str(error)[:90]}")
            return False
        print(f"    update after {label}: OK -- VERIFIED")
        return True

    def own(self, com_object: Any) -> Any:
        """Records a created object for cleanup and returns it."""
        if com_object is not None:
            self.created.append(com_object)
        return com_object

    def reclaim_body(self) -> None:
        """Makes the body the in-work object again.

        THIS IS THE FIX. Appending to a geometrical set leaves that set as the
        in-work object, and a pad cannot be inserted into one, so the next
        `AddNewPad` fails with a bare COM error that says nothing about why.
        """
        self.raw.InWorkObject = self.body

    def geometrical_set(self) -> Any:
        """Creates the geometrical set every hybrid shape here is appended to."""
        hybrid_body = self.own(self.raw.HybridBodies.Add())
        hybrid_body.Name = f"{PREFIX}GSET"
        self.reclaim_body()
        return hybrid_body

    def append(self, hybrid_body: Any, shape: Any, name: str) -> Any:
        """Names a hybrid shape, appends it to the set, and reclaims the body."""
        shape.Name = name
        hybrid_body.AppendHybridShape(shape)
        self.reclaim_body()
        return self.own(shape)

    def sketch_and_pad(self, plane: Any, label: str) -> None:
        """Draws a closed rectangle on `plane` and pads it, reporting each update."""
        sketch = attempt(
            f"Sketches.Add({label})", lambda: self.body.Sketches.Add(plane)
        )
        if sketch is None:
            return
        sketch.Name = f"{PREFIX}SKETCH_{label}"
        self.own(sketch)
        editor = sketch.OpenEdition()
        side = RECTANGLE_SIDE
        for x1, y1, x2, y2 in (
            (0.0, 0.0, side, 0.0),
            (side, 0.0, side, side),
            (side, side, 0.0, side),
            (0.0, side, 0.0, 0.0),
        ):
            editor.CreateLine(x1, y1, x2, y2)
        sketch.CloseEdition()
        self.reclaim_body()
        if not self.update(f"rectangle on the {label} plane"):
            return
        pad = attempt(
            f"AddNewPad({label} sketch)",
            lambda: self.shape_factory.AddNewPad(sketch, PAD_HEIGHT),
        )
        if pad is None:
            return
        pad.Name = f"{PREFIX}PAD_{label}"
        self.own(pad)
        self.update(f"pad on the {label} plane")

    def cleanup(self) -> None:
        """Deletes everything created, newest first, and restores the in-work object.

        `Shapes.Remove` does not exist in this release, so deletion goes through
        the Selection. Newest first, because a pad is built on its sketch and a
        sketch on its plane. A pad's deletion cascades to its sketch, so the
        sketch's own deletion can then fail harmlessly.
        """
        print("--- cleanup ---")
        for com_object in reversed(self.created):
            try:
                self.selection.Clear()
                self.selection.Add(com_object)
                self.selection.Delete()
            except Exception as error:  # noqa: BLE001 - cleanup must not stop
                print(f"  {describe(com_object)}: already gone ({str(error)[:50]})")
        self.selection.Clear()
        try:
            self.raw.InWorkObject = self.original_in_work_object
        except Exception as error:  # noqa: BLE001 - cleanup must not stop
            print(f"  could not restore InWorkObject: {str(error)[:70]}")
        self.update("cleanup")
        print(
            f"  shapes: {self.body.Shapes.Count} | "
            f"sketches: {self.body.Sketches.Count} | "
            f"hybrid bodies: {self.raw.HybridBodies.Count}"
        )
        print(
            f"  InWorkObject: {describe(self.raw.InWorkObject)} "
            f"{self.raw.InWorkObject.Name}"
        )
        print("Document save: NOT CALLED")


def main() -> None:
    """Runs the probe against the active Part."""
    probe = Probe()
    print(f"Part: {probe.part.name}")
    print(
        f"InWorkObject at start: {describe(probe.original_in_work_object)} "
        f"{probe.original_in_work_object.Name}"
    )
    try:
        hybrid_body = probe.geometrical_set()
        origin = probe.raw.OriginElements

        print("--- 1. offset plane, then a sketch, then a pad ---")
        offset_plane = attempt(
            "AddNewPlaneOffset(PlaneXY, 30, False)",
            lambda: probe.hybrid_shape_factory.AddNewPlaneOffset(
                origin.PlaneXY, PLANE_OFFSET, False
            ),
        )
        if offset_plane is not None:
            probe.append(hybrid_body, offset_plane, f"{PREFIX}PLANE_OFFSET")
            if probe.update("the offset plane"):
                print(f"    Offset.Value = {offset_plane.Offset.Value}")
                probe.sketch_and_pad(offset_plane, "offset")

        print("--- 2. angled plane needs an addressable 3D line as its axis ---")
        start = probe.hybrid_shape_factory.AddNewPointCoord(0.0, 0.0, 0.0)
        end = probe.hybrid_shape_factory.AddNewPointCoord(0.0, AXIS_LENGTH, 0.0)
        probe.append(hybrid_body, start, f"{PREFIX}AXIS_START")
        probe.append(hybrid_body, end, f"{PREFIX}AXIS_END")
        axis = attempt(
            "AddNewLinePtPt(start, end)",
            lambda: probe.hybrid_shape_factory.AddNewLinePtPt(start, end),
        )
        if axis is None:
            return
        probe.append(hybrid_body, axis, f"{PREFIX}AXIS")
        if not probe.update("the axis line"):
            return
        angle_plane = attempt(
            "AddNewPlaneAngle(PlaneXY, axis line, 30, False)",
            lambda: probe.hybrid_shape_factory.AddNewPlaneAngle(
                origin.PlaneXY, axis, PLANE_ANGLE, False
            ),
        )
        if angle_plane is None:
            return
        probe.append(hybrid_body, angle_plane, f"{PREFIX}PLANE_ANGLE")
        if probe.update("the angled plane"):
            print(f"    Angle.Value = {angle_plane.Angle.Value}")
            probe.sketch_and_pad(angle_plane, "angled")
    finally:
        probe.cleanup()


if __name__ == "__main__":
    main()
