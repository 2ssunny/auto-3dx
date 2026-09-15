"""Probe the 2D geometry `SketchEditor` cannot yet draw: circles, arcs, points,
splines, and the dimensional/positional constraints that go with curves.

Signatures below are copied verbatim from the pywin32 generated type library
cache, file:

    C:\\Users\\ssunn\\AppData\\Local\\Temp\\gen_py\\3.13\\
        0D90A5C9-3B08-11D1-A26C-0000F87546FDx0x0x0.py

`Factory2D` (CLSID {80EC75FA-AE47-0000-0280-030BA6000000}) -- every `Create*`
method it exposes:

    CreateCircle(iCenterX, iCenterY, iRadius, iStartParam, iEndParam) -> Circle2D
    CreateClosedCircle(iCenterX, iCenterY, iRadius)                  -> Circle2D
    CreateClosedEllipse(iCenterX, iCenterY, iMajorX, iMajorY,
                         iMajorRadius, iMinorRadius)                 -> Ellipse2D
    CreateControlPoint(iX, iY)                                       -> ControlPoint2D
    CreateEllipse(iCenterX, iCenterY, iMajorX, iMajorY, iMajorRadius,
                  iMinorRadius, iStartParam, iEndParam)              -> Ellipse2D
    CreateHyperbola(iCenterX, iCenterY, iAxisX, iAxisY,
                    iMajorRadius, iMinorRadius)                      -> Hyperbola2D
    CreateIntersection(iGeometry)                                    -> Geometry2D
    CreateIntersections(iGeometry)                                   -> GeometricElements
    CreateLine(iX1, iY1, iX2, iY2)                                   -> Line2D
    CreateLineFromVector(iX1, iY1, iUX, iUY)                         -> Line2D
    CreateParabola(iCenterX, iCenterY, iAxisX, iAxisY, iFocalDistance)-> Parabola2D
    CreatePoint(iX, iY)                                              -> Point2D
    CreateProjection(iGeometry)                                      -> Geometry2D
    CreateProjections(iGeometry)                                     -> GeometricElements
    CreateSpline(iPoles)                                             -> Spline2D
    GetItem(IDName)                                                  -> CATBaseDispatch

`CreateSpline`'s `iPoles` argument is typed `((8204, 1),)` -- VT_ARRAY|VT_VARIANT,
input only, no BYREF. It is a plain array of poles; this probe feeds it a
Python list of raw `ControlPoint2D` objects returned by `CreateControlPoint`,
since that is the one Factory2D method whose entire purpose is building spline
poles. Whether `CreateSpline` would also accept plain `Point2D` objects is an
open question this probe does not need to answer to draw a spline.

Every `Create*Circle`/`Create*Ellipse` variant expects mandatory
`iStartParam`/`iEndParam` on top of the closed-circle/closed-ellipse ones seen
before; what unit those two params are in is not stated anywhere in the type
library. This probe treats them as radians (0 to `math.pi` for a half circle)
and reports success/failure rather than asserting an interpretation -- if the
call fails, that failure is the answer, not a guess to paper over.

`Constraints` (CLSID {6B70F3B3-6BCF-11D1-A280-0000F87546FD}):

    AddBiEltCst(iCstType, iFirstElem, iSecondElem)   -> Constraint
    AddMonoEltCst(iCstType, iElem)                   -> Constraint
    AddTriEltCst(iCstType, iFirstElem, iSecondElem, iThirdElem) -> Constraint
    Item(iIndex) [1-based] / Remove(iIndex)          -> Constraint / void
    Count, BrokenConstraintsCount, UnUpdatedConstraintsCount

`CatConstraintType` enum, full membership as found in the type library (32
entries; grepped in full, not sampled):

    Reference=0 Distance=1 On=2 Concentricity=3 Tangency=4 Length=5 Angle=6
    PlanarAngle=7 Parallelism=8 AxisParallelism=9 Horizontality=10
    Perpendicularity=11 AxisPerpendicularity=12 Verticality=13 Radius=14
    Symmetry=15 MidPoint=16 Equidistance=17 MajorRadius=18 MinorRadius=19
    SurfContact=20 LinContact=21 PoncContact=22 Chamfer=23 ChamferPerpend=24
    AnnulContact=25 CylinderRadius=26 StContinuity=27 StDistance=28
    SdContinuity=29 SdShape=30 CurvilinearDistance=31

**There is no `Diameter` member anywhere in this enum.** `docs/conventions.md`
1.2.4 only lists `Radius=14` for circle sizing; this probe confirms that is
the complete set for a 2D sketch circle. Per the task's own hard rule ("never
guess a COM signature"), this probe does NOT attempt a diameter constraint --
there is no code to try that would not be a guess, so it is reported as
skipped rather than probed blindly.

Curve object properties (all read via `type(obj).__name__`, same file):

    Circle2D (CLSID {80EC7321-4B09-0000-0280-030BA6000000})
        readable : Application, CenterPoint (Point2D), Construction (bool),
                   Continuity, EndPoint (Point2D), GeometricType, Name,
                   Parent, Period, Radius, ReportName, StartPoint (Point2D)
        writable : CenterPoint, Construction, EndPoint, Name, ReportName,
                   StartPoint
        methods  : GetCenter(oData), GetEndPoints(oEndPoints),
                   GetPointAtParam(iParam, oPoint), SetData(iCenterX,
                   iCenterY, iRadius), IsPeriodic(), GetCurvature/
                   GetDerivatives/GetTangent(iParam, oOut), GetLengthAtParam/
                   GetParamAtLength(iFrom, iTo), GetParamExtents(oParams),
                   GetRangeBox(oBoundPoint)

    Point2D (CLSID {6ED8AC55-6B19-11D1-A280-0000F87546FD})
        readable : Application, Construction, GeometricType, Name, Parent,
                   ReportName
        writable : Construction, Name, ReportName
        methods  : GetCoordinates(oPoint), SetData(iX, iY)
        NOTE: no X/Y properties at all. Coordinates are only readable through
        GetCoordinates, which follows the same seed-array-as-BYREF-output
        convention already verified for `Sketch.GetAbsoluteAxisData`
        (`geometry/sketch.py`): its argument type is `((24588, 3),)`, the
        identical VT_ARRAY|VT_BYREF|VT_VARIANT/in-out flag pair used there.

    ControlPoint2D (CLSID {80EC7432-4CB8-0000-0280-030BA6000000})
        readable : Application, Construction, Curvature, GeometricType, Name,
                   Parent, ReportName
        writable : Construction, Curvature, Name, ReportName
        methods  : GetCoordinates(oPoint), SetData(iX, iY),
                   GetTangent(oTangent), SetTangent(iTangentX, iTangentY),
                   UnsetCurvature(), UnsetTangent()

    Spline2D (CLSID {80EC78F7-EF72-0000-0280-030BA6000000})
        readable : Application, Construction, Continuity, EndPoint (Point2D),
                   GeometricType, Name, Parent, Period, ReportName,
                   StartPoint (Point2D)
        writable : Construction, EndPoint, Name, ReportName, StartPoint
        methods  : GetControlPoints(oCtrlPoints), GetNumberOfControlPoints(),
                   InsertControlPointAfter(iCtrlPoint, iPosition),
                   GetCurvature/GetDerivatives/GetTangent(iParam, oOut),
                   GetEndPoints(oEndPoints), GetLengthAtParam/
                   GetParamAtLength, GetParamExtents(oParams),
                   GetRangeBox(oBoundPoint), IsPeriodic()

`Construction` (bool) turns out to be a property shared by every 2D geometry
type checked here, `Line2D` included -- not unique to curves. This probe uses
it to mark every element except the closed circle as construction geometry
right before the pad attempt, so `AddNewPad` sees exactly one real closed
profile in a sketch that otherwise also holds an open arc, a point, and a
spline (all of which were required by the task in the SAME sketch/edition).

Ambiguous points this probe could not resolve from the type library alone,
and therefore only attempts and reports rather than assumes:

    - `CreateSpline`'s pole array: whether it must be `ControlPoint2D` or
      also accepts `Point2D` is untested; only `ControlPoint2D` is tried.
    - `GetControlPoints`'s output-array seed: no existing probe seeds an
      array of COM object placeholders (only float arrays, e.g.
      GetAbsoluteAxisData's 9 zeros). This probe seeds it with
      `[None] * GetNumberOfControlPoints()` and reports whatever comes back.
    - `CreateCircle`'s `iStartParam`/`iEndParam` units (see above).
    - `Concentricity` (type 3): `docs/conventions.md` 1.2.4 records this as
      unverified because an earlier probe passed the SAME circle to both
      argument slots (a probe bug, not a COM limitation). This probe uses two
      distinct circles instead.

Success, per `docs/conventions.md` 1.2.2.1, means created AND
`Part.Update()` succeeded -- creation alone proves nothing.

Creates and removes geometry in the ACTIVE Part, all named with an
`AUTO3DX_P27_` prefix. Never saves.
"""

import math
from typing import Any

from auto_3dx import Catia
from auto_3dx.errors import PartUpdateError

PREFIX = "AUTO3DX_P27_"
SKETCH_NAME = f"{PREFIX}SKETCH"

# From the CatConstraintType enum quoted above -- not guessed, read directly
# from the type library.
CST_CONCENTRICITY = 3
CST_TANGENCY = 4
CST_RADIUS = 14


def describe(com_object: Any) -> str:
    """Returns a COM wrapper's type name."""
    return type(com_object).__name__


def attempt(label: str, action: Any) -> Any:
    """Runs one experiment and reports the outcome without stopping the probe."""
    try:
        result = action()
    except Exception as error:  # noqa: BLE001 - probing the real failure mode
        print(f"  {label}: FAILED {type(error).__name__}: {str(error)[:110]}")
        return None
    if isinstance(result, tuple):
        print(f"  {label}: OK -> {result}")
    else:
        print(f"  {label}: OK -> {describe(result)}")
    return result


def main() -> None:
    """Runs the probe against the active Part."""
    catia = Catia.attach()
    part = catia.active_part()
    raw = part.com_object
    body = raw.MainBody
    selection = catia.active_editor().Selection

    print("Part:", part.name)
    print("sketches before:", body.Sketches.Count, "| shapes before:", body.Shapes.Count)

    pad: Any = None
    circle_closed: Any = None

    try:
        sketch = part.sketches.create(SKETCH_NAME, support="XY")
        print(f"sketch: {describe(sketch.com_object)} name={sketch.name!r}")

        circle_open: Any = None
        point_obj: Any = None
        spline_obj: Any = None
        control_points: "list[Any]" = []

        with sketch.edit() as editor:
            factory = editor.com_object  # raw Factory2D, escape hatch for methods
            # SketchEditor does not wrap (open arcs, control points, splines).

            print()
            print("--- 1. geometry creation ---")
            circle_closed = attempt(
                "CreateClosedCircle(0, 0, 10)", lambda: editor.circle(0.0, 0.0, 10.0)
            )
            circle_open = attempt(
                "CreateCircle(30, 0, 10, 0, pi) [open arc]",
                lambda: factory.CreateCircle(30.0, 0.0, 10.0, 0.0, math.pi),
            )
            point_obj = attempt("CreatePoint(0, 30)", lambda: editor.point(0.0, 30.0))
            for index, (x, y) in enumerate(((0.0, 50.0), (10.0, 60.0), (20.0, 50.0)), start=1):
                control_point = attempt(
                    f"CreateControlPoint({x}, {y})",
                    lambda x=x, y=y: factory.CreateControlPoint(x, y),
                )
                if control_point is not None:
                    control_points.append(control_point)
            if len(control_points) >= 2:
                spline_obj = attempt(
                    f"CreateSpline([{len(control_points)} ControlPoint2D])",
                    lambda: factory.CreateSpline(control_points),
                )
            else:
                print("  CreateSpline: SKIPPED (fewer than 2 control points were created)")

            print()
            print("--- 2. rename with AUTO3DX_P27_ prefix (Name is writable per type lib) ---")
            for label, obj, name in (
                ("closed circle", circle_closed, f"{PREFIX}CIRCLE_CLOSED"),
                ("open circle", circle_open, f"{PREFIX}CIRCLE_OPEN"),
                ("point", point_obj, f"{PREFIX}POINT"),
                ("spline", spline_obj, f"{PREFIX}SPLINE"),
            ):
                if obj is None:
                    continue
                attempt(f"rename {label} -> {name!r}", lambda o=obj, n=name: setattr(o, "Name", n) or o)
            for index, control_point in enumerate(control_points, start=1):
                name = f"{PREFIX}CTRLPT_{index}"
                attempt(
                    f"rename control point {index} -> {name!r}",
                    lambda o=control_point, n=name: setattr(o, "Name", n) or o,
                )

            print()
            print("--- 3. mark everything but the closed circle as construction ---")
            print("    (isolates one real closed profile for the pad attempt in step 7)")
            for label, obj in (
                ("open circle", circle_open),
                ("point", point_obj),
                ("spline", spline_obj),
            ):
                if obj is None:
                    continue
                attempt(
                    f"{label}.Construction = True",
                    lambda o=obj: setattr(o, "Construction", True) or o,
                )

            print()
            print("--- 4. read back properties ---")
            if circle_closed is not None:
                attempt("closed circle .Radius", lambda: circle_closed.Radius)
                attempt("closed circle .GeometricType", lambda: circle_closed.GeometricType)
                center = attempt("closed circle .CenterPoint", lambda: circle_closed.CenterPoint)
                if center is not None:
                    attempt(
                        "  CenterPoint.GetCoordinates([0.0, 0.0])",
                        lambda: tuple(center.GetCoordinates([0.0, 0.0])),
                    )
                attempt("closed circle .StartPoint", lambda: circle_closed.StartPoint)
                attempt("closed circle .EndPoint", lambda: circle_closed.EndPoint)

            if circle_open is not None:
                attempt("open circle .Radius", lambda: circle_open.Radius)
                start = attempt("open circle .StartPoint", lambda: circle_open.StartPoint)
                if start is not None:
                    attempt(
                        "  StartPoint.GetCoordinates([0.0, 0.0])",
                        lambda: tuple(start.GetCoordinates([0.0, 0.0])),
                    )
                attempt("open circle .EndPoint", lambda: circle_open.EndPoint)

            if point_obj is not None:
                attempt("point .GeometricType", lambda: point_obj.GeometricType)
                attempt(
                    "point.GetCoordinates([0.0, 0.0])",
                    lambda: tuple(point_obj.GetCoordinates([0.0, 0.0])),
                )

            if spline_obj is not None:
                attempt("spline .GeometricType", lambda: spline_obj.GeometricType)
                count = attempt(
                    "spline.GetNumberOfControlPoints()",
                    lambda: spline_obj.GetNumberOfControlPoints(),
                )
                if isinstance(count, int) and count > 0:
                    attempt(
                        f"spline.GetControlPoints([None] * {count})",
                        lambda: tuple(spline_obj.GetControlPoints([None] * count)),
                    )
                attempt("spline .StartPoint", lambda: spline_obj.StartPoint)
                attempt("spline .EndPoint", lambda: spline_obj.EndPoint)

            print()
            print("--- 5. dimensional constraints on the closed circle ---")
            constraints = sketch.com_object.Constraints
            if circle_closed is not None:
                radius_cst = attempt(
                    "AddMonoEltCst(Radius=14, closed circle)",
                    lambda: constraints.AddMonoEltCst(CST_RADIUS, circle_closed),
                )
                if radius_cst is not None:
                    dimension = attempt("  radius constraint .Dimension", lambda: radius_cst.Dimension)
                    if dimension is not None:
                        print(f"    Dimension.Value (captured) = {dimension.Value}")
                        attempt(
                            "  set Dimension.Value = 12.0",
                            lambda: setattr(dimension, "Value", 12.0) or dimension,
                        )
                        print(f"    Dimension.Value (after set) = {radius_cst.Dimension.Value}")
            else:
                print("  SKIPPED: no closed circle to constrain.")

            print(
                "  diameter constraint: SKIPPED -- CatConstraintType has no Diameter "
                "member (full enum quoted in the module docstring); trying one would "
                "require guessing an undocumented code, which is forbidden."
            )

            print()
            print("--- 6. positional constraint between two curves (concentricity) ---")
            print("    (probe 20/22 only tried this with the SAME circle twice -- a probe")
            print("    input bug per docs/conventions.md 1.2.4 -- this uses two distinct ones)")
            if circle_closed is not None and circle_open is not None:
                concentricity_cst = attempt(
                    "AddBiEltCst(Concentricity=3, closed circle, open circle)",
                    lambda: constraints.AddBiEltCst(CST_CONCENTRICITY, circle_closed, circle_open),
                )
                if concentricity_cst is None:
                    attempt(
                        "AddBiEltCst(Tangency=4, closed circle, open circle) [fallback]",
                        lambda: constraints.AddBiEltCst(CST_TANGENCY, circle_closed, circle_open),
                    )
            else:
                print("  SKIPPED: need both circles to relate them.")

            print()
            print("  Constraints.Count           :", constraints.Count)
            attempt("  BrokenConstraintsCount", lambda: constraints.BrokenConstraintsCount)
            attempt("  UnUpdatedConstraintsCount", lambda: constraints.UnUpdatedConstraintsCount)

        # `with sketch.edit()` has exited: CloseEdition() already ran.

        print()
        print("--- 7. Part.Update() after closing the edition ---")
        try:
            part.update()
        except PartUpdateError as error:
            print("  Part.Update(): FAILED ->", str(error)[:120])
            print("  VERDICT: sketch content created but INVALID")
        else:
            print("  Part.Update(): OK")
            print("  VERDICT: sketch content created AND valid -- verified.")

        print()
        print("--- 8. pad the circle profile (curved profiles padable?) ---")
        if circle_closed is not None:
            pad = attempt(
                "ShapeFactory.AddNewPad(sketch, 15.0)",
                lambda: raw.ShapeFactory.AddNewPad(sketch.com_object, 15.0),
            )
            if pad is not None:
                attempt(f"rename pad -> {PREFIX}PAD", lambda: setattr(pad, "Name", f"{PREFIX}PAD") or pad)
                try:
                    part.update()
                except PartUpdateError as error:
                    print("  Part.Update() after pad: FAILED ->", str(error)[:120])
                    print("  VERDICT: pad created but INVALID -- curved profile NOT confirmed padable")
                else:
                    print("  Part.Update() after pad: OK")
                    print("  VERDICT: curved (circular) profile IS padable -- verified.")
        else:
            print("  SKIPPED: no closed circle to pad.")
    finally:
        print()
        print("--- cleanup ---")
        if pad is not None:
            try:
                selection.Clear()
                selection.Add(pad)
                selection.Delete()
                selection.Clear()
                print("  removed pad")
            except Exception as error:  # noqa: BLE001 - report, do not mask
                print(f"  pad removal: {type(error).__name__}")
        try:
            part.sketches.remove(SKETCH_NAME)
            print(f"  removed sketch {SKETCH_NAME}")
        except Exception as error:  # noqa: BLE001 - report, do not mask; may be gone already
            print(f"  sketch removal: {type(error).__name__}")
        try:
            part.update()
            print("  update after cleanup: OK")
        except Exception as error:  # noqa: BLE001 - report, do not mask
            print(f"  update after cleanup FAILED: {type(error).__name__}")
        print("  sketches:", body.Sketches.Count, "| shapes:", body.Shapes.Count)
        print("Document save: NOT CALLED")


if __name__ == "__main__":
    main()
