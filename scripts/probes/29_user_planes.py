r"""Probe user-defined (non-origin) sketch planes.

THE GAP this probe investigates: `auto_3dx/geometry/sketch.py` can create a
sketch only on one of the three origin planes (`Part.OriginElements.PlaneXY`
/ `PlaneYZ` / `PlaneZX`). Real parts need sketches on an offset plane, an
angled plane, or a plane through geometry. This probe finds out how to make
such a plane with `Part.HybridShapeFactory`, whether the result must be
appended to a `HybridBody` (geometrical set) before it is usable, and
whether `Sketches.Add` accepts it directly or only through
`Part.CreateReferenceFromObject`.

Every signature quoted below is copied verbatim from this installation's
pywin32 type-library cache under
`C:\Users\ssunn\AppData\Local\Temp\gen_py\3.13`. Argument tuples use
pywin32's own `(vt, flag)` encoding: vt 9 = VT_DISPATCH, 5 = VT_R8 (double),
11 = VT_BOOL; flag 1 = required (`defaultNamedNotOptArg`).

`87EE735C-DF70-11D1-8556-0060941979CEx0x0x0.py`, class `HybridShapeFactory`
(CLSID `{8964041B-BB8A-0000-0280-020E60000000}`) -- the methods this probe
uses or considered:

    AddNewPlaneOffset(iPlane, iOffset, iOrientation) -> HybridShapePlaneOffset
        args ((9,1), (5,1), (11,1))   iOffset = double, mm; iOrientation = bool
    AddNewPlaneOffsetPt(iPlane, iPt)                 -> HybridShapePlaneOffsetPt
        args ((9,1), (9,1))
    AddNewPlaneAngle(iPlane, iRevolAxis, iAngle, iOrientation)
                                                      -> HybridShapePlaneAngle
        args ((9,1), (9,1), (5,1), (11,1))   iAngle = double, degrees
    AddNewPlane1Line1Pt(iLn, iPt)                    -> HybridShapePlane1Line1Pt
        args ((9,1), (9,1))
    AddNewPlane3Points(iPt1, iPt2, iPt3)             -> HybridShapePlane3Points
        args ((9,1), (9,1), (9,1))
    AddNewPlaneNormal(iCurve, iPt)                   -> HybridShapePlaneNormal
        args ((9,1), (9,1))
    AddNewPlaneTangent(iSurface, iPt)                -> HybridShapePlaneTangent
        args ((9,1), (9,1))
    AddNewPlaneEquation(iA_Coeff, iB_Coeff, iC_Coeff, iD_Coeff)
                                                      -> HybridShapePlaneEquation
        args ((5,1), (5,1), (5,1), (5,1))

    Also present in this release but not exercised here: AddNewPlane1Curve,
    AddNewPlane2Lines, AddNewPlaneBetween, AddNewPlaneDatum, AddNewPlaneMean.

Every `iPlane`/`iPt`/`iLn`/`iRevolAxis` argument is typed as a plain `(9,1)`
-- a generic `IDispatch`, not narrowed to `Reference` or `Plane`. The type
library therefore cannot say, by itself, whether `AddNewPlaneOffset` accepts
a raw `OriginElements.PlaneXY` or demands a `Reference` built with
`Part.CreateReferenceFromObject`; this is a real ambiguity, not something to
guess past, so both forms are tried below and the result is reported.
Precedent cuts both ways: `docs/conventions.md` 1.2.3 shows `AddNewMirror`
accepting a raw origin plane directly, but 1.2.2.1 shows `AddNewRectPattern`'s
direction argument only producing a successful `Part.Update()` when wrapped
as a `Reference`.

`0D90A5C9-3B08-11D1-A26C-0000F87546FDx0x0x0.py`:

    class Part (properties/methods used here):
        HybridShapeFactory                 property, declared return type
                                            "Factory" (generic base interface,
                                            CLSID {8EF79FFE-E43C-11D1-98CA-00805F852731})
        HybridBodies                       property -> HybridBodies
        CreateReferenceFromObject(iObject) -> Reference   args ((9,1),)
        Update()                           -> void

    class HybridBodies:
        Add()                    -> HybridBody   (no arguments)
        Item(iIndex) / Count     1-based collection protocol (same shape as
                                 every other CATIA collection in this project)

    class HybridBody:
        AppendHybridShape(iHybridShape) -> void   args ((9,1),)
        readable: Application, Bodies, GeometricElements, HybridBodies,
                  HybridShapes, HybridSketches, Name, Parent
        writable: Name

    class Sketches:
        Add(iPlane) -> Sketch   args ((9,1),)
        Same generic-IDispatch signature already relied on in
        `geometry/sketch.py` for the three origin planes -- nothing in the
        type library requires the argument to be an origin plane specifically.

    IMPORTANT CAVEAT on `HybridShapeFactory`'s declared return type: the type
    library says `Part.HybridShapeFactory` returns the generic base interface
    "Factory" -- the EXACT SAME declared CLSID as `Part.ShapeFactory`.
    `ShapeFactory` already works in this codebase via
    `raw.ShapeFactory.AddNewPad(...)` (`geometry/part_design.py`), which is
    only possible because `com3dx`'s `Dispatch3dx` casts the *runtime* object
    up to its real derived type (`ShapeFactory`), not the declared "Factory"
    base (`docs/conventions.md` 1.1's `Length`/`Dimension` cast is the same
    mechanism). The same cast is assumed for `HybridShapeFactory`; step 1
    below confirms it by reading `type(raw.HybridShapeFactory).__name__`
    instead of assuming it.

`14F197B2-0771-11D1-A5B1-00A0C9575177x0x0x0.py`, class `Reference` (CLSID
`{81799037-B0F2-0000-0280-030D3B000000}`):

    readable: Application, DisplayName, Name, Parent
    writable: Name

`87EE735C-...py`, class `HybridShapePlaneOffset`
(CLSID `{89D7662D-F4A3-0000-0280-020E60000000}`):

    readable: Application, Name, Offset (-> Length, same wrapper type as a
              Length parameter -- `.Value` reads the offset back in mm),
              Orientation (int, VT_I4), Parent, Plane (-> Reference), Thickness
    writable: Name, Orientation, Plane

`87EE735C-...py`, class `HybridShapePlaneAngle`
(CLSID `{89D7661A-9109-0000-0280-020E60000000}`):

    readable: Angle (-> Angle, `.Value` in degrees), Application, Name,
              Orientation (int), Parent, Plane (-> Reference),
              ProjectionMode (bool), RevolAxis (-> Reference), Thickness
    writable: Name, Orientation, Plane, ProjectionMode, RevolAxis

AMBIGUITY FLAGGED, NOT GUESSED: `AddNewPlaneOffset`/`AddNewPlaneAngle` take
`iOrientation` as `VT_BOOL` at creation time, but the created object's own
`Orientation` property reads back as a plain integer (`VT_I4`), not a bool.
The type library does not document how the boolean argument maps to the
integer read back, so this probe reports the raw value instead of assuming
`False == 0`.

No `HybridShapes.Remove`, `Sketches.Remove`, or `HybridBodies.Remove` exists
in this release (same shape as the `Shapes`/`Sketches` finding in
`docs/conventions.md` 1.2) -- deleting the hybrid shapes and the hybrid body
created here goes through `Editor.Selection`
(`auto_3dx.geometry.deletion.delete_via_selection`'s
`Selection.Clear()` -> `Selection.Add()` -> `Selection.Delete()` sequence),
exactly like sketches and pads already do.

"Verified" means CREATED and `Part.Update()` succeeded
(`docs/conventions.md` 1.2.2.1) -- a successful `AddNewPlane*` or
`AppendHybridShape` call alone proves nothing.

Creates and removes content in the ACTIVE Part only. Never calls `Save()` or
`PLMPropagate()`. Prints ASCII only (the console is cp1252).
"""

from typing import Any

from auto_3dx import Catia
from auto_3dx.errors import Auto3dxError, PartUpdateError
from auto_3dx.geometry.sketch import Sketch

PREFIX = "AUTO3DX_P29_"
OFFSET_MM = 30.0
ANGLE_DEG = 30.0
RECT_WIDTH = 30.0
RECT_HEIGHT = 20.0
PAD_HEIGHT = 10.0
AXIS_LENGTH = 50.0


def describe(com_object: Any) -> str:
    """Returns a COM object's wrapper type name."""
    return type(com_object).__name__


def attempt(label: str, action: Any) -> Any:
    """Runs one experiment and reports OK/FAILED without stopping the probe.

    Args:
        label: What is being tried, printed verbatim.
        action: A zero-argument callable performing the COM call.

    Returns:
        The action's result on success, or `None` on failure.
    """
    try:
        result = action()
    except Exception as error:  # noqa: BLE001 - probing the real failure mode
        print(f"  {label}: FAILED {type(error).__name__}: {str(error)[:120]}")
        return None
    if result is None:
        print(f"  {label}: OK")
    else:
        print(f"  {label}: OK ({describe(result)})")
    return result


def rename_quietly(com_object: Any, name: str, label: str) -> None:
    """Best-effort rename for identification; a failure is reported, not raised.

    Args:
        com_object: The raw COM object whose `Name` is being set.
        name: The name to write.
        label: What is being renamed, for the failure message.
    """
    try:
        com_object.Name = name
    except Exception as error:  # noqa: BLE001 - naming is not the property under test
        print(f"  rename {label} to {name!r}: FAILED {type(error).__name__}")


def main() -> None:
    """Runs the probe against the active Part."""
    catia = Catia.attach()
    part = catia.active_part()
    raw = part.com_object
    selection = catia.active_editor().Selection

    print("Part:", part.name)

    hybrid_bodies_raw: list[Any] = []
    hybrid_shapes_raw: list[Any] = []
    sketch_names: list[str] = []
    pad_names: list[str] = []

    try:
        print()
        print("--- 1. HybridShapeFactory and existing hybrid bodies ---")
        factory = attempt("Part.HybridShapeFactory", lambda: raw.HybridShapeFactory)
        if factory is None:
            print("No HybridShapeFactory available; aborting probe.")
            return

        hybrid_bodies = raw.HybridBodies
        print(f"  Part.HybridBodies: {describe(hybrid_bodies)} Count={hybrid_bodies.Count}")
        for index in range(1, hybrid_bodies.Count + 1):
            existing = hybrid_bodies.Item(index)
            print(f"    [{index}] {existing.Name!r} ({describe(existing)})")

        body = attempt("HybridBodies.Add() (new geometrical set)", lambda: hybrid_bodies.Add())
        if body is None:
            print("Could not create a HybridBody; aborting probe.")
            return
        hybrid_bodies_raw.append(body)
        rename_quietly(body, f"{PREFIX}GSET", "hybrid body")
        print(f"  created HybridBody named {body.Name!r}")

        print()
        print("--- 2. offset plane from PlaneXY ---")
        base_plane = raw.OriginElements.PlaneXY
        plane_offset = attempt(
            "AddNewPlaneOffset(raw PlaneXY, offset, orientation=False)",
            lambda: factory.AddNewPlaneOffset(base_plane, OFFSET_MM, False),
        )
        offset_plane_input_form = "raw plane"
        if plane_offset is None:
            base_plane_ref = raw.CreateReferenceFromObject(base_plane)
            plane_offset = attempt(
                "AddNewPlaneOffset(Reference(PlaneXY), offset, orientation=False)",
                lambda: factory.AddNewPlaneOffset(base_plane_ref, OFFSET_MM, False),
            )
            offset_plane_input_form = "Reference-wrapped plane"
        if plane_offset is None:
            print("Could not create the offset plane in either form; aborting probe.")
            return
        print(f"  AddNewPlaneOffset base-plane argument accepted as: {offset_plane_input_form}")
        hybrid_shapes_raw.append(plane_offset)
        rename_quietly(plane_offset, f"{PREFIX}PLANE_OFFSET", "offset plane")

        attempt(
            "HybridBody.AppendHybridShape(plane_offset)",
            lambda: body.AppendHybridShape(plane_offset),
        )
        try:
            part.update()
            print("  Part.Update() after offset plane: OK -- VERIFIED")
        except PartUpdateError as error:
            print(f"  Part.Update() after offset plane: FAILED {str(error)[:120]} -- NOT verified")

        print("  read-back on the offset plane:")
        print(f"    Name = {plane_offset.Name!r}")
        try:
            offset_length = plane_offset.Offset
            print(f"    Offset -> {describe(offset_length)} Value = {offset_length.Value}")
        except Exception as error:  # noqa: BLE001 - probing availability
            print(f"    Offset: FAILED {type(error).__name__}")
        try:
            print(f"    Orientation (int) = {plane_offset.Orientation!r}")
        except Exception as error:  # noqa: BLE001 - probing availability
            print(f"    Orientation: FAILED {type(error).__name__}")
        try:
            plane_reference = plane_offset.Plane
            print(
                f"    Plane -> {describe(plane_reference)} "
                f"DisplayName = {plane_reference.DisplayName!r}"
            )
        except Exception as error:  # noqa: BLE001 - probing availability
            print(f"    Plane: FAILED {type(error).__name__}")

        print()
        print("--- 3. sketch on the offset plane: raw hybrid shape vs Reference ---")
        main_body = raw.MainBody
        raw_sketch = attempt(
            "Sketches.Add(plane_offset) [raw hybrid shape]",
            lambda: main_body.Sketches.Add(plane_offset),
        )
        sketch_input_form = "raw hybrid shape"
        if raw_sketch is None:
            plane_offset_ref = raw.CreateReferenceFromObject(plane_offset)
            raw_sketch = attempt(
                "Sketches.Add(CreateReferenceFromObject(plane_offset))",
                lambda: main_body.Sketches.Add(plane_offset_ref),
            )
            sketch_input_form = "Reference-wrapped hybrid shape"
        if raw_sketch is None:
            print("Could not create a sketch on the offset plane in either form; aborting probe.")
            return
        print(f"  Sketches.Add accepted the plane as: {sketch_input_form}")

        offset_sketch = Sketch(raw_sketch)
        try:
            offset_sketch.rename(f"{PREFIX}SKETCH_OFFSET")
        except Auto3dxError as error:
            print(f"  rename offset sketch: FAILED {error}; leaving it as {offset_sketch.name!r}")
        sketch_names.append(offset_sketch.name)

        print()
        print("--- 4. draw + pad on the offset-plane sketch ---")
        drew_rectangle = False
        try:
            with offset_sketch.edit() as editor:
                editor.rectangle(RECT_WIDTH, RECT_HEIGHT)
            print("  sketch.edit() rectangle: OK")
            drew_rectangle = True
        except Exception as error:  # noqa: BLE001 - probing the real failure mode
            print(f"  sketch.edit() rectangle: FAILED {type(error).__name__}: {error}")

        if drew_rectangle:
            try:
                part.update()
                print("  Part.Update() after rectangle: OK")
            except PartUpdateError as error:
                print(f"  Part.Update() after rectangle: FAILED {str(error)[:120]}")

            pad = attempt(
                "part.part_design.create_pad(name, offset_sketch, height)",
                lambda: part.part_design.create_pad(
                    f"{PREFIX}PAD_OFFSET", offset_sketch, PAD_HEIGHT
                ),
            )
            if pad is not None:
                pad_names.append(pad.name)
                try:
                    part.update()
                    print("  Part.Update() after pad: OK -- VERIFIED end to end")
                except PartUpdateError as error:
                    print(
                        f"  Part.Update() after pad: FAILED {str(error)[:120]} -- NOT verified"
                    )

        print()
        print("--- 5. angled plane: does the whole AddNewPlane* family work? ---")
        axis_line = None
        try:
            axis_sketch = part.sketches.create(f"{PREFIX}AXIS_SKETCH", support="XY")
            sketch_names.append(axis_sketch.name)
            with axis_sketch.edit() as editor:
                axis_line = editor.line(0.0, 0.0, AXIS_LENGTH, 0.0)
            part.update()
            print("  axis sketch + line for iRevolAxis: OK")
        except Exception as error:  # noqa: BLE001 - probing the real failure mode
            print(f"  axis sketch + line for iRevolAxis: FAILED {type(error).__name__}: {error}")

        if axis_line is not None:
            axis_reference = raw.CreateReferenceFromObject(axis_line)
            angle_plane = attempt(
                "AddNewPlaneAngle(raw PlaneXY, Reference(axis line), angle, orientation=False)",
                lambda: factory.AddNewPlaneAngle(base_plane, axis_reference, ANGLE_DEG, False),
            )
            angle_plane_input_form = "raw plane"
            if angle_plane is None:
                base_plane_ref = raw.CreateReferenceFromObject(base_plane)
                angle_plane = attempt(
                    "AddNewPlaneAngle(Reference(PlaneXY), Reference(axis line), "
                    "angle, orientation=False)",
                    lambda: factory.AddNewPlaneAngle(
                        base_plane_ref, axis_reference, ANGLE_DEG, False
                    ),
                )
                angle_plane_input_form = "Reference-wrapped plane"

            if angle_plane is not None:
                print(f"  AddNewPlaneAngle base-plane argument accepted as: {angle_plane_input_form}")
                hybrid_shapes_raw.append(angle_plane)
                rename_quietly(angle_plane, f"{PREFIX}PLANE_ANGLE", "angled plane")

                attempt(
                    "HybridBody.AppendHybridShape(angle_plane)",
                    lambda: body.AppendHybridShape(angle_plane),
                )
                try:
                    part.update()
                    print("  Part.Update() after angled plane: OK -- VERIFIED")
                except PartUpdateError as error:
                    print(
                        f"  Part.Update() after angled plane: FAILED {str(error)[:120]} "
                        "-- NOT verified"
                    )

                print("  read-back on the angled plane:")
                print(f"    Name = {angle_plane.Name!r}")
                try:
                    angle_value = angle_plane.Angle
                    print(f"    Angle -> {describe(angle_value)} Value = {angle_value.Value}")
                except Exception as error:  # noqa: BLE001 - probing availability
                    print(f"    Angle: FAILED {type(error).__name__}")
                try:
                    print(f"    Orientation (int) = {angle_plane.Orientation!r}")
                except Exception as error:  # noqa: BLE001 - probing availability
                    print(f"    Orientation: FAILED {type(error).__name__}")
                try:
                    print(f"    ProjectionMode = {angle_plane.ProjectionMode!r}")
                except Exception as error:  # noqa: BLE001 - probing availability
                    print(f"    ProjectionMode: FAILED {type(error).__name__}")
            else:
                print("  Could not create the angled plane in either form.")
    finally:
        print()
        print("--- 6. cleanup (tolerates anything already gone) ---")
        for name in list(pad_names):
            try:
                part.part_design.remove_pad(name)
                print(f"  removed pad {name!r}")
            except Exception as error:  # noqa: BLE001 - report, do not mask
                print(f"  remove pad {name!r}: {type(error).__name__} (tolerated)")

        for name in list(sketch_names):
            try:
                part.sketches.remove(name)
                print(f"  removed sketch {name!r}")
            except Exception as error:  # noqa: BLE001 - may have cascaded away with its pad
                print(f"  remove sketch {name!r}: {type(error).__name__} (tolerated)")

        for shape in reversed(hybrid_shapes_raw):
            try:
                selection.Clear()
                selection.Add(shape)
                selection.Delete()
                print(f"  deleted hybrid shape ({describe(shape)})")
            except Exception as error:  # noqa: BLE001 - report, do not mask
                print(f"  delete hybrid shape ({describe(shape)}): {type(error).__name__} (tolerated)")
        try:
            selection.Clear()
        except Exception as error:  # noqa: BLE001 - report, do not mask
            print(f"  Selection.Clear() after shapes: {type(error).__name__} (tolerated)")

        for hybrid_body in reversed(hybrid_bodies_raw):
            try:
                selection.Clear()
                selection.Add(hybrid_body)
                selection.Delete()
                print("  deleted hybrid body")
            except Exception as error:  # noqa: BLE001 - report, do not mask
                print(f"  delete hybrid body: {type(error).__name__} (tolerated)")
        try:
            selection.Clear()
        except Exception as error:  # noqa: BLE001 - report, do not mask
            print(f"  Selection.Clear() after hybrid bodies: {type(error).__name__} (tolerated)")

        try:
            part.update()
            print("  final Part.Update(): OK")
        except Exception as error:  # noqa: BLE001 - report, do not mask
            print(f"  final Part.Update(): FAILED {type(error).__name__} (tolerated)")

        print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
