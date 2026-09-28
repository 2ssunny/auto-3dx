"""Probe 45: geometry measurement, pad/pocket direction, plane editing, update diagnostics.

Establishes the live facts Phase 4 needs, on the disposable Part named by
`AUTO3DX_LIVE_PART` and nowhere else:

1. measure  -- what `MeasurableService.GetMeasurable(reference, CATMeasurableType)` and
               `MeasureService.GetMeasureItem([reference])` return for faces and edges:
               area, centre of gravity, plane normal, surface/edge classification, length,
               radius, centre; in which units; whether either one adds anything to the
               model; and roughly how long it takes per topology element.
               Probe 31 passed `catOpnsEdgeItem` (1) to `GetMeasurable`, but its second
               argument is a `CATMeasurableType` (Circle=2, Cylinder=5, Line=6, Plane=7,
               Surface=10), which is why nothing came back then.
2. direction -- whether `DirectionOrientation` (catRegularOrientation=0 /
               catInverseOrientation=1) flips a Pad and a Pocket, on geometry where the
               wrong direction removes nothing.
3. planes   -- whether `Offset.Value` / `Angle.Value` can be written on an existing plane
               and whether a sketch and pad on it follow after `Part.Update()`; whether a
               sketch's frame still equals its plane's frame (the only available dependency
               signal, since `Sketch` has no support member); and what deleting an in-use
               plane actually does to the sketch and pad on it.
4. diagnostics -- what `Part.IsUpToDate(feature)` and `Part.IsInactive(feature)` report per
               feature after a failed update, for two kinds of failure.
5. rectangle -- which constraints `SketchEditor.rectangle` creates today.

Everything this probe creates is named `AUTO3DX_P45_*` and is removed in `finally`.
Raw Automation is used deliberately here; that is what a probe is for. Nothing is saved.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python scripts/probes/45_geometry_intelligence.py [phase ...]
"""

import os
import sys
import time
import traceback
from typing import Any

import win32com.client

from auto_3dx import Auto3dxError, Catia

PREFIX = "AUTO3DX_P45_"
BLOCK_SKETCH, BLOCK_PAD = f"{PREFIX}BLOCK_SKETCH", f"{PREFIX}BLOCK_PAD"
TOP_PLANE = f"{PREFIX}TOP_PLANE"
HOLE_SKETCH, HOLE_POCKET = f"{PREFIX}HOLE_SKETCH", f"{PREFIX}HOLE_POCKET"
DIR_SKETCH, DIR_POCKET = f"{PREFIX}DIR_SKETCH", f"{PREFIX}DIR_POCKET"
DIR_PAD_SKETCH, DIR_PAD = f"{PREFIX}DIR_PAD_SKETCH", f"{PREFIX}DIR_PAD"
LIFT_PLANE, LIFT_SKETCH, LIFT_PAD = f"{PREFIX}LIFT_PLANE", f"{PREFIX}LIFT_SKETCH", f"{PREFIX}LIFT_PAD"
TILT_PLANE, TILT_SKETCH = f"{PREFIX}TILT_PLANE", f"{PREFIX}TILT_SKETCH"
FILLET = f"{PREFIX}FILLET"
RECT_SKETCH = f"{PREFIX}RECT_SKETCH"
LENGTH, WIDTH, HEIGHT = 60.0, 40.0, 20.0
HOLE_RADIUS, HOLE_X = 5.0, -15.0

MEASURABLE_CIRCLE, MEASURABLE_CYLINDER, MEASURABLE_CONE = 2, 5, 3
MEASURABLE_CURVE, MEASURABLE_LINE, MEASURABLE_PLANE = 4, 6, 7
MEASURABLE_SPHERE, MEASURABLE_SURFACE = 9, 10
FACE_TYPES = {
    "MeasurablePlane": MEASURABLE_PLANE,
    "MeasurableCylinder": MEASURABLE_CYLINDER,
    "MeasurableCone": MEASURABLE_CONE,
    "MeasurableSphere": MEASURABLE_SPHERE,
    "MeasurableSurface": MEASURABLE_SURFACE,
}
EDGE_TYPES = {
    "MeasurableLine": MEASURABLE_LINE,
    "MeasurableCircle": MEASURABLE_CIRCLE,
    "MeasurableCurve": MEASURABLE_CURVE,
}


def target_part() -> Any:
    """Attaches and returns the active Part if it is the one named, or exits."""
    target = os.environ.get("AUTO3DX_LIVE_PART", "").strip()
    if not target:
        sys.exit("Refusing to run: set AUTO3DX_LIVE_PART to the disposable test Part.")
    catia = Catia.attach()
    part = catia.active_part()
    title = catia.active_window_title
    if target not in (part.name, title):
        sys.exit(f"Refusing to run: the active Part is {part.name!r} ({title!r}), not {target!r}.")
    return part


def show(label: str, call: Any) -> Any:
    """Prints what one experiment returned, or how it failed."""
    try:
        result = call()
    except BaseException as error:  # a probe records failures instead of stopping
        print(f"  {label}: FAILED {type(error).__name__}: {str(error)[:140]}")
        return None
    print(f"  {label}: {result!r}")
    return result


def members(com_object: Any) -> "list[str]":
    return [n for n in dir(com_object) if n[:1].isupper() and not n.startswith("CLSID")]


def build_block(part: Any) -> None:
    """A 60x40x20 block with a through hole cut down from its top face."""
    sketch = part.sketches.create(BLOCK_SKETCH, support="XY")
    with sketch.edit() as editor:
        editor.rectangle(LENGTH, WIDTH, origin_x=-LENGTH / 2, origin_y=-WIDTH / 2)
    part.part_design.create_pad(BLOCK_PAD, sketch, HEIGHT)
    part.update()
    plane = part.planes.create_offset(TOP_PLANE, "XY", HEIGHT)
    part.update()
    hole = part.sketches.create(HOLE_SKETCH, support=plane)
    with hole.edit() as editor:
        editor.circle(HOLE_X, 0.0, HOLE_RADIUS)
    part.part_design.create_pocket(HOLE_POCKET, hole, HEIGHT + 5.0)
    part.update()
    print(f"  block built, volume {part.measurement.measure().volume_mm3:.3f} "
          f"(expected {LENGTH * WIDTH * HEIGHT - 3.141592653589793 * HOLE_RADIUS**2 * HEIGHT:.3f})")


def measurement(part: Any, raw: Any) -> None:
    """1: what the measurement services report for faces and edges."""
    print("\n== 1. measurement")
    editor = Catia.attach().active_editor()
    measurable = show("  GetService('MeasurableService')",
                      lambda: editor.GetService("MeasurableService"))
    measure = show("  GetService('MeasureService')", lambda: editor.GetService("MeasureService"))
    summary_before = [(f.name, f.kind) for f in part.inspect.features()]

    faces = part.topology.faces(body="PartBody")
    edges = part.topology.edges(body="PartBody")
    print(f"  faces {len(faces)}, edges {len(edges)}")

    def try_measurable(reference: Any, types: "dict[str, int]") -> "dict[str, Any]":
        found: dict[str, Any] = {}
        for interface, code in types.items():
            try:
                item = measurable.GetMeasurable(reference, code)
                cast = win32com.client.CastTo(item, interface)
            except BaseException as error:
                found[interface] = f"<{type(error).__name__}>"
                continue
            values: dict[str, Any] = {}
            for method in ("GetArea", "GetCOfG", "GetLength", "GetRadius", "GetCenter",
                           "GetAxis", "GetDirection", "GetOrigin", "GetAngle", "GetPerimeter"):
                reader = getattr(cast, method, None)
                if reader is None:
                    continue
                try:
                    values[method] = reader()
                except BaseException as error:
                    values[method] = f"<{type(error).__name__}>"
            if hasattr(cast, "GetPlane"):
                try:
                    values["GetPlane"] = cast.GetPlane([0.0] * 9)
                except BaseException as error:
                    values["GetPlane"] = f"<{type(error).__name__}>"
            found[interface] = values
        return found

    def try_measure_item(reference: Any) -> "dict[str, Any]":
        values: dict[str, Any] = {}
        if measure is None:
            return values
        try:
            item = measure.GetMeasureItem([reference])
        except BaseException as error:
            return {"GetMeasureItem": f"<{type(error).__name__}: {str(error)[:80]}>"}
        for method in ("GetMeasureItemType", "GetMeasureSurfaceType", "GetMeasureEdgeType",
                       "GetArea", "GetCOfG", "GetLength", "GetRadius", "GetCenter",
                       "GetAxis", "GetDirection", "GetOrigin"):
            reader = getattr(item, method, None)
            if reader is None:
                continue
            try:
                values[method] = reader()
            except BaseException as error:
                values[method] = f"<{type(error).__name__}>"
        try:
            values["GetPlane"] = item.GetPlane([0.0] * 9)
        except BaseException as error:
            values["GetPlane"] = f"<{type(error).__name__}>"
        return values

    print("\n-- every face through MeasurableService, then MeasureService")
    start = time.perf_counter()
    for face in faces:
        print(f"   face {face.index} owner={face.owner_feature_name}")
        for interface, values in try_measurable(face.com_object, FACE_TYPES).items():
            print(f"     {interface}: {values}")
    face_time = time.perf_counter() - start
    for face in list(faces)[:3]:
        print(f"   face {face.index} MeasureItem: {try_measure_item(face.com_object)}")

    print("\n-- every edge through MeasurableService, then MeasureService")
    start = time.perf_counter()
    for edge in edges:
        print(f"   edge {edge.index} owner={edge.owner_feature_name}")
        for interface, values in try_measurable(edge.com_object, EDGE_TYPES).items():
            print(f"     {interface}: {values}")
    edge_time = time.perf_counter() - start
    for edge in list(edges)[:3]:
        print(f"   edge {edge.index} MeasureItem: {try_measure_item(edge.com_object)}")

    print(f"\n  time: {len(faces)} faces x {len(FACE_TYPES)} types in {face_time:.2f}s, "
          f"{len(edges)} edges x {len(EDGE_TYPES)} types in {edge_time:.2f}s")
    print("  -- did measuring change the model?")
    show("  features unchanged",
         lambda: summary_before == [(f.name, f.kind) for f in part.inspect.features()])
    show("  is_up_to_date", lambda: part.is_up_to_date())
    show("  geometrical sets", lambda: [s.name for s in part.inspect.geometrical_sets()])

    print("\n-- a fresh wrapper and a fresh snapshot measure the same face the same way")
    fresh_faces = Catia.attach().active_part().topology.faces(body="PartBody")
    first = list(fresh_faces)[0]
    for interface, values in try_measurable(first.com_object, {"MeasurableSurface": 10}).items():
        print(f"   fresh face {first.index} {interface}: {values}")


def direction(part: Any, raw: Any) -> None:
    """2: DirectionOrientation on a Pad and a Pocket."""
    print("\n== 2. direction")
    volume = part.measurement.measure().volume_mm3

    sketch = part.sketches.create(DIR_SKETCH, support="XY")
    with sketch.edit() as editor:
        editor.circle(15.0, 0.0, 4.0)
    pocket = part.part_design.create_pocket(DIR_POCKET, sketch, 10.0)
    com = pocket.com_object
    show("  Pocket.DirectionOrientation (as created)", lambda: com.DirectionOrientation)
    show("  Pocket.DirectionType", lambda: com.DirectionType)
    show("  Pocket.IsSymmetric", lambda: com.IsSymmetric)
    show("  update", lambda: part.update())
    default_volume = show("  volume", lambda: part.measurement.measure().volume_mm3)
    print(f"  removed with the default direction: {volume - (default_volume or volume):.3f} "
          f"(a 10 mm deep R4 hole would be {3.141592653589793 * 16 * 10:.3f})")
    show("  set DirectionOrientation = 1", lambda: setattr(com, "DirectionOrientation", 1))
    show("  is_up_to_date before update", lambda: part.is_up_to_date())
    show("  update", lambda: part.update())
    show("  DirectionOrientation", lambda: com.DirectionOrientation)
    reversed_volume = show("  volume", lambda: part.measurement.measure().volume_mm3)
    if reversed_volume is not None:
        print(f"  removed after reversing: {volume - reversed_volume:.3f}")
    show("  fresh wrapper reads it",
         lambda: Catia.attach().active_part().part_design.get_pocket(DIR_POCKET)
         .com_object.DirectionOrientation)
    show("  set back to 0", lambda: setattr(com, "DirectionOrientation", 0))
    show("  update", lambda: part.update())
    show("  volume", lambda: part.measurement.measure().volume_mm3)

    print("  -- a Pad on XY, default and reversed")
    pad_sketch = part.sketches.create(DIR_PAD_SKETCH, support="XY")
    with pad_sketch.edit() as editor:
        editor.circle(80.0, 0.0, 5.0)
    pad = part.part_design.create_pad(DIR_PAD, pad_sketch, 12.0)
    show("  update", lambda: part.update())
    show("  Pad.DirectionOrientation", lambda: pad.com_object.DirectionOrientation)
    show("  COG z", lambda: part.measurement.measure().cog_mm[2])
    show("  set Pad DirectionOrientation = 1",
         lambda: setattr(pad.com_object, "DirectionOrientation", 1))
    show("  update", lambda: part.update())
    show("  COG z after reversing", lambda: part.measurement.measure().cog_mm[2])
    show("  volume", lambda: part.measurement.measure().volume_mm3)


def planes(part: Any, raw: Any) -> None:
    """3: editing planes, the frame signal, and deleting an in-use plane."""
    print("\n== 3. plane editing and dependency")
    lift = part.planes.create_offset(LIFT_PLANE, "XY", 40.0)
    part.update()
    lift_sketch = part.sketches.create(LIFT_SKETCH, support=lift)
    with lift_sketch.edit() as editor:
        editor.circle(0.0, 60.0, 6.0)
    part.part_design.create_pad(LIFT_PAD, lift_sketch, 5.0)
    part.update()
    print(f"  lift pad COG z (whole body): {part.measurement.measure().cog_mm[2]:.3f}")
    show("  Offset.Value", lambda: lift.com_object.Offset.Value)
    show("  Orientation", lambda: lift.com_object.Orientation)
    show("  sketch frame == plane frame", lambda: _frames_equal(lift_sketch, lift))
    show("  write Offset = 55", lambda: setattr(lift.com_object.Offset, "Value", 55.0))
    show("  is_up_to_date before update", lambda: part.is_up_to_date())
    show("  update", lambda: part.update())
    show("  Offset.Value", lambda: lift.com_object.Offset.Value)
    show("  sketch origin z now", lambda: lift_sketch.axis_data()[2])
    show("  whole-body COG z", lambda: part.measurement.measure().cog_mm[2])
    show("  sketch frame still == plane frame", lambda: _frames_equal(lift_sketch, lift))
    show("  fresh wrapper offset",
         lambda: Catia.attach().active_part().planes.get(LIFT_PLANE).offset)

    print("  -- an angle plane")
    tilt = show("  create_angle", lambda: part.planes.create_angle(
        TILT_PLANE, "XY", 30.0, (0.0, -100.0, 0.0), (0.0, 100.0, 0.0)))
    if tilt is not None:
        part.update()
        tilt_sketch = part.sketches.create(TILT_SKETCH, support=tilt)
        part.update()
        show("  Angle.Value", lambda: tilt.com_object.Angle.Value)
        before = show("  sketch axis_data", lambda: tilt_sketch.axis_data())
        show("  write Angle = 45", lambda: setattr(tilt.com_object.Angle, "Value", 45.0))
        show("  update", lambda: part.update())
        show("  Angle.Value", lambda: tilt.com_object.Angle.Value)
        after = show("  sketch axis_data", lambda: tilt_sketch.axis_data())
        print(f"  sketch frame moved: {before != after}")
        show("  sketch frame == plane frame", lambda: _frames_equal(tilt_sketch, tilt))

    print("  -- deleting the in-use offset plane (our own objects only)")
    show("  remove LIFT_PLANE", lambda: part.planes.remove(part.planes.get(LIFT_PLANE)))
    show("  sketch still listed", lambda: LIFT_SKETCH in part.sketches.names())
    show("  pad still listed", lambda: LIFT_PAD in [p.name for p in part.part_design.pads])
    show("  is_up_to_date", lambda: part.is_up_to_date())
    show("  update", lambda: part.update())
    show("  is_up_to_date after update", lambda: part.is_up_to_date())
    show("  sketch axis_data now", lambda: part.sketches.get(LIFT_SKETCH).axis_data())


def _frames_equal(sketch: Any, plane: Any) -> bool:
    """Whether the sketch's absolute axis equals the plane's own frame (probe 1.7 route)."""
    data = sketch.axis_data()
    origin = tuple(plane.com_object.GetOrigin([0.0] * 3))
    first = tuple(plane.com_object.GetFirstAxis([0.0] * 3))
    second = tuple(plane.com_object.GetSecondAxis([0.0] * 3))
    return all(abs(a - b) < 1e-6 for a, b in zip(data, origin + first + second))


def diagnostics(part: Any, raw: Any) -> None:
    """4: per-feature state after two kinds of failed update."""
    print("\n== 4. update diagnostics")
    solid = [
        e for e in part.topology.edges(body="PartBody")
        if e.owner_feature_name and not e.owner_feature_name.endswith("_SKETCH")
    ]
    part.part_design.create_edge_fillet(FILLET, solid[0], 2.0)
    part.update()

    def report(label: str) -> None:
        print(f"  {label}")
        for feature in part.inspect.features():
            wrapper = raw.MainBody.Shapes.Item(feature.name)
            up = show(f"    {feature.name} IsUpToDate", lambda w=wrapper: raw.IsUpToDate(w))
            show(f"    {feature.name} IsInactive", lambda w=wrapper: raw.IsInactive(w))
            del up
        show("    Part IsUpToDate", lambda: raw.IsUpToDate(raw))
        show("    MainBody IsUpToDate", lambda: raw.IsUpToDate(raw.MainBody))

    report("healthy model:")
    pad = part.part_design.get_pad(BLOCK_PAD)
    print("  -- suppress the base pad")
    pad.deactivate()
    show("  update", lambda: part.update())
    report("after the failed update:")
    pad.activate()
    show("  update after reactivating", lambda: part.update())
    report("healed:")

    print("  -- an invalid dimension instead")
    fillet = part.part_design.get_edge_fillet(FILLET)
    previous = fillet.radius
    fillet.set_radius(500.0)
    show("  update with radius 500", lambda: part.update())
    report("after the failed update:")
    fillet.set_radius(previous)
    show("  update after restoring", lambda: part.update())
    report("healed:")


def curves(part: Any, raw: Any) -> None:
    """1b: can a straight edge be told from another curve, and what do fillet faces say?"""
    print("\n== 1b. curve and surface classification on filleted geometry")
    solid = [
        e for e in part.topology.edges(body="PartBody")
        if e.owner_feature_name and not e.owner_feature_name.endswith("_SKETCH")
    ]
    straight = [e for e in solid if _circle_radius(e) is None]
    part.part_design.create_edge_fillet(FILLET, straight[0], 3.0)
    part.update()
    editor = Catia.attach().active_editor()
    service = editor.GetService("MeasurableService")

    for edge in part.topology.edges(body="PartBody"):
        item = service.GetMeasurable(edge.com_object, MEASURABLE_CURVE)
        curve = win32com.client.CastTo(item, "MeasurableCurve")
        circle = win32com.client.CastTo(
            service.GetMeasurable(edge.com_object, MEASURABLE_CIRCLE), "MeasurableCircle"
        )
        line = win32com.client.CastTo(
            service.GetMeasurable(edge.com_object, MEASURABLE_LINE), "MeasurableLine"
        )
        row = {"length": _safe(curve.GetLength)}
        row["points"] = _safe(lambda c=curve: c.GetPoints([0.0] * 3, [0.0] * 3, [0.0] * 3))
        row["circle_radius"] = _safe(circle.GetRadius)
        row["circle_angle"] = _safe(circle.GetAngle)
        row["line_direction"] = _safe(line.GetDirection)
        print(f"   edge {edge.index} {edge.owner_feature_name}: {row}")

    for face in part.topology.faces(body="PartBody"):
        plane = win32com.client.CastTo(
            service.GetMeasurable(face.com_object, MEASURABLE_PLANE), "MeasurablePlane"
        )
        cylinder = win32com.client.CastTo(
            service.GetMeasurable(face.com_object, MEASURABLE_CYLINDER), "MeasurableCylinder"
        )
        cone = win32com.client.CastTo(
            service.GetMeasurable(face.com_object, MEASURABLE_CONE), "MeasurableCone"
        )
        sphere = win32com.client.CastTo(
            service.GetMeasurable(face.com_object, MEASURABLE_SPHERE), "MeasurableSphere"
        )
        row = {
            "plane": _safe(lambda p=plane: p.GetPlane([0.0] * 9)),
            "cyl_radius": _safe(cylinder.GetRadius),
            "cone_angle": _safe(cone.GetAngle),
            "sphere_center": _safe(sphere.GetCenter),
            "sphere_radius": _safe(sphere.GetRadius),
        }
        print(f"   face {face.index}: {row}")


def _safe(call: Any) -> Any:
    try:
        return call()
    except BaseException as error:
        return f"<{type(error).__name__}>"


def _circle_radius(edge: Any) -> Any:
    service = Catia.attach().active_editor().GetService("MeasurableService")
    try:
        circle = win32com.client.CastTo(
            service.GetMeasurable(edge.com_object, MEASURABLE_CIRCLE), "MeasurableCircle"
        )
        return circle.GetRadius()
    except BaseException:
        return None


def rectangle(part: Any, raw: Any) -> None:
    """5: which constraints rectangle() creates today."""
    print("\n== 5. rectangle constraints")
    sketch = part.sketches.create(RECT_SKETCH, support="XY")
    with sketch.edit() as editor:
        editor.rectangle(20.0, 10.0, origin_x=150.0)
    part.update()
    print("  elements:", sketch.element_names())
    print("  constraints:", [(c.name, c.type_code) for c in sketch.constraints.list()])


def cleanup(part: Any, raw: Any) -> None:
    """Removes only what this probe created."""
    print("\n== cleanup")
    try:
        raw.InWorkObject = raw.MainBody
    except BaseException:
        traceback.print_exc()
    for step in (
        lambda: part.part_design.get_pad(BLOCK_PAD).activate(),
        lambda: part.part_design.remove_edge_fillet(FILLET),
        lambda: part.part_design.remove_pocket(DIR_POCKET),
        lambda: part.sketches.remove(DIR_SKETCH),
        lambda: part.part_design.remove_pad(DIR_PAD),
        lambda: part.sketches.remove(DIR_PAD_SKETCH),
        lambda: part.part_design.remove_pad(LIFT_PAD),
        lambda: part.sketches.remove(LIFT_SKETCH),
        lambda: part.sketches.remove(TILT_SKETCH),
        lambda: part.part_design.remove_pocket(HOLE_POCKET),
        lambda: part.sketches.remove(HOLE_SKETCH),
        lambda: part.part_design.remove_pad(BLOCK_PAD),
        lambda: part.sketches.remove(BLOCK_SKETCH),
        lambda: part.sketches.remove(RECT_SKETCH),
        lambda: part.planes.remove_geometrical_set(),
    ):
        try:
            step()
        except Auto3dxError as error:
            print(f"  skipped: {type(error).__name__}: {str(error)[:70]}")
        except BaseException:
            traceback.print_exc()
    try:
        part.update()
    except Auto3dxError as error:
        print(f"  update after cleanup failed: {error}")
    print(part.inspect.summary().render())


PHASES = ("measure", "curves", "direction", "planes", "diagnostics", "rectangle")


def main() -> None:
    wanted = sys.argv[1:] or list(PHASES)
    unknown = [phase for phase in wanted if phase not in PHASES]
    if unknown:
        sys.exit(f"unknown phase(s) {unknown}; choose from {list(PHASES)}")
    part = target_part()
    raw = part.com_object
    previous_in_work = raw.InWorkObject
    print(part.inspect.summary().render())
    try:
        build_block(part)
        for phase in wanted:
            {"measure": measurement, "curves": curves, "direction": direction, "planes": planes,
             "diagnostics": diagnostics, "rectangle": rectangle}[phase](part, raw)
    finally:
        try:
            raw.InWorkObject = previous_in_work
        except BaseException:
            traceback.print_exc()
        cleanup(part, raw)


if __name__ == "__main__":
    main()
