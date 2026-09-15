"""Probe whether the model can be MEASURED, and use that to settle pattern direction.

Two open problems share one missing capability.

`AddNewRectPattern` survives `Part.Update()` only when its direction arguments
are a `Reference` built from an origin plane (probe 25), and all three origin
planes update successfully (probe 26). But no property reads the direction back,
so which plane produces which axis is unknown -- and a pattern that goes
somewhere other than where the caller asked is worse than no pattern at all.
That is the only reason Pattern is not implemented (docs/conventions.md 1.2.5).

The other problem is that nothing verifies geometry. `Part.Update()` succeeding
says the feature rebuilt, not that it did what was intended: a pocket that
removes nothing still updates fine (docs/status.md 2.6).

Both are answered by measuring the solid. The type library exposes that through
an Editor service:

    Editor.GetService(iService) -> Service
        (14F197B2-0771-11D1-A5B1-00A0C9575177x0x0x0.py, class Editor)

    InertiaService.GetInertiaElement(iSelectedItem) -> Inertia
    Inertia.GetVolume() -> double
    Inertia.GetArea() -> double
    Inertia.GetMass() -> double
    Inertia.GetCOGPosition(oXCOG, oYCOG, oZCOG)
    Inertia.OnlyMainBody()
        (74DE02AE-B214-423E-9332-82ACD452F8A6x0x0x0.py)

    InertiaBoxService.GetInertiaBoxElement(iSelectedItem) -> InertiaBox
    InertiaBox.GetBoundingBox(oBoundingBoxOrigin, oBoundingBoxLenths)
        (same file; both out-parameters are safearrays of double)

    MeasurableService.GetMeasurable(iMeasuredItem, iType) -> MeasurableInContext
        (FEC192B6-AB98-4AA2-B6B1-A5065A5BA7C9x0x0x0.py)

The service NAME string that `GetService` wants is not in the type library, so
this probe tries the plausible candidates and reports which one answers. That is
the first thing it must establish; everything else depends on it.

With a measurement in hand the pattern question becomes arithmetic. Volume and
centre of gravity before and after the pattern give the centroid of the material
the pattern ADDED, by mass balance, and comparing that with the original
feature's centroid yields the displacement -- axis and sign -- as a number
instead of an eyeball. Each origin plane is tried in two configurations, since
one reading cannot separate a rule from a coincidence.

`GetInertiaBoxElement` looks like the obvious tool for this and is not: it is
aligned to the solid's PRINCIPAL INERTIA axes, not the global ones. It agrees
with the global axes for a plain block, which is exactly what makes it
misleading, and reported growth along all three axes at once for a single
pattern. It is still read here, because it is the only volume-extent measurement
available and worth recording, but it is not used to decide anything.

Creates and removes content in the ACTIVE Part. Never saves.
"""

from typing import Any

from auto_3dx import Catia
from auto_3dx.errors import Auto3dxError

PREFIX = "AUTO3DX_P30_"
# The probe pads a 20x20 rectangle drawn from the sketch origin, 10 mm high,
# so its own material sits centred here. Every measured shift is read against it.
PAD_SIDE = 20.0
PAD_HEIGHT = 10.0
PAD_CENTROID_MM = (PAD_SIDE / 2.0, PAD_SIDE / 2.0, PAD_HEIGHT / 2.0)
SERVICE_CANDIDATES = (
    "InertiaService",
    "InertiaBoxService",
    "MeasurableService",
    "CATIAInertiaService",
    "SPAWorkbench",
)
PLANES = ("XY", "YZ", "ZX")


def describe(com_object: Any) -> str:
    """Returns a COM wrapper's type name."""
    return type(com_object).__name__


def readable(com_object: Any) -> "list[str]":
    """Returns the readable COM property names for a wrapper type."""
    names: set[str] = set()
    for base in type(com_object).__mro__:
        mapping = base.__dict__.get("_prop_map_get_")
        if isinstance(mapping, dict):
            names.update(map(str, mapping))
    return sorted(names)


def attempt(label: str, action: Any) -> Any:
    """Runs one experiment and reports the outcome without stopping the probe."""
    try:
        result = action()
    except Exception as error:  # noqa: BLE001 - probing the real failure mode
        print(f"  {label}: FAILED {type(error).__name__}: {str(error)[:130]}")
        return None
    if result is None:
        print(f"  {label}: OK -> None")
    else:
        print(f"  {label}: OK -> {describe(result)} {result!r}"[:160])
    return result


def find_service(editor: Any) -> "tuple[str, Any] | None":
    """Finds the service name `GetService` accepts for inertia measurement."""
    print("--- 1. Which service name does Editor.GetService accept? ---")
    found: tuple[str, Any] | None = None
    for name in SERVICE_CANDIDATES:
        service = attempt(f"GetService({name!r})", lambda n=name: editor.GetService(n))
        if service is not None and found is None:
            found = (name, service)
            print(f"      properties: {readable(service)}")
    return found


def measure(inertia_service: Any, box_service: Any, item: Any) -> "dict[str, Any] | None":
    """Returns volume, centre of gravity and bounding box for one solid.

    Every value CATIA hands back here is SI -- metres and cubic metres, not the
    millimetres the rest of the API uses -- so each one is converted on the way
    out. A 20x20x10 mm pad measures 2e-06 m3, which prints as 0.000 if that is
    missed.

    Three `GetBoundingBox` calling forms were tried against a live session:
    passing two 3-element sequences is the one that works, and it RETURNS
    `(origin, lengths)` rather than mutating the arguments it was given.
    """
    result: dict[str, Any] = {}
    try:
        inertia = inertia_service.GetInertiaElement(item)
        result["volume_mm3"] = float(inertia.GetVolume()) * 1.0e9
        cog = inertia.GetCOGPosition()
        result["cog_mm"] = tuple(float(value) * 1000.0 for value in cog)
    except Exception as error:  # noqa: BLE001 - probing the real failure mode
        print(f"      inertia FAILED {type(error).__name__}: {str(error)[:110]}")
        return None
    try:
        box = box_service.GetInertiaBoxElement(item)
        origin, lengths = box.GetBoundingBox((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        result["box_origin_mm"] = tuple(float(value) * 1000.0 for value in origin)
        result["box_lengths_mm"] = tuple(float(value) * 1000.0 for value in lengths)
    except Exception as error:  # noqa: BLE001 - probing the real failure mode
        print(f"      bounding box FAILED {type(error).__name__}: {str(error)[:110]}")
    return result


def _triple(values: Any) -> str:
    """Formats a 3-tuple of millimetres."""
    return "(" + ", ".join(f"{value:.3f}" for value in values) + ")"


def report_measurement(label: str, measurement: Any) -> None:
    """Prints one measurement in a fixed, comparable format."""
    if measurement is None:
        print(f"      {label}: unavailable")
        return
    print(f"      {label}: volume={measurement['volume_mm3']:.3f} mm3")
    print(f"        cog  {_triple(measurement['cog_mm'])} mm")
    if "box_lengths_mm" in measurement:
        print(f"        box  origin {_triple(measurement['box_origin_mm'])}")
        print(f"             lengths {_triple(measurement['box_lengths_mm'])}")


def added_centroid(before: Any, after: Any) -> "tuple[float, float, float] | None":
    """Returns the centroid of the material one operation added to the body.

    `GetInertiaBoxElement` is NOT an axis-aligned bounding box: it is aligned to
    the solid's principal inertia axes. For the plain block it happens to agree
    with the global axes, which makes it look usable, but after a pattern makes
    the solid asymmetric the box rotates and its extents say nothing about which
    axis anything moved along. Verified live: the same pattern reported growth
    on all three axes at once.

    Volume and centre of gravity are exact, so the added material's centroid
    follows from a mass balance instead:

        C_added = (V_after * C_after - V_before * C_before) / (V_after - V_before)

    Comparing that centroid with the original feature's gives the pattern
    displacement as a number, sign included.
    """
    if before is None or after is None:
        return None
    volume_before = before["volume_mm3"]
    volume_after = after["volume_mm3"]
    added = volume_after - volume_before
    if abs(added) < 1.0e-6:
        return None
    return tuple(
        (volume_after * after["cog_mm"][index] - volume_before * before["cog_mm"][index])
        / added
        for index in range(3)
    )


def describe_shift(origin: Any, centroid: Any) -> str:
    """Describes the displacement from the original centroid to the added one."""
    if centroid is None:
        return "no material was added, so there is nothing to measure"
    deltas = [centroid[index] - origin[index] for index in range(3)]
    labels = ("X", "Y", "Z")
    largest = max(range(3), key=lambda index: abs(deltas[index]))
    detail = ", ".join(f"d{labels[i]}={deltas[i]:+.3f}" for i in range(3))
    if abs(deltas[largest]) < 1.0e-3:
        return f"nothing moved ({detail})"
    sign = "+" if deltas[largest] > 0 else "-"
    return f"{sign}{labels[largest]} ({detail})"


def base_pad(part: Any) -> Any:
    """Builds the pad that every pattern in this probe copies."""
    sketch = part.sketches.create(f"{PREFIX}SKETCH", support="XY")
    with sketch.edit() as editor:
        editor.rectangle(PAD_SIDE, PAD_SIDE)
    part.update()
    pad = part.part_design.create_pad(f"{PREFIX}PAD", sketch, PAD_HEIGHT)
    part.update()
    return pad


def plane_reference(part: Any, plane_name: str) -> Any:
    """Returns a `Reference` to one origin plane, the only direction form that works."""
    raw = part.com_object
    origin = raw.OriginElements
    plane = {
        "XY": origin.PlaneXY,
        "YZ": origin.PlaneYZ,
        "ZX": origin.PlaneZX,
    }[plane_name]
    return raw.CreateReferenceFromObject(plane)


def pattern_once(
    part: Any,
    factory: Any,
    pad: Any,
    plane_name: str,
    copies: int,
    step: float,
    reversed_first: bool = False,
    second: "tuple[str, int, float] | None" = None,
) -> Any:
    """Creates one rectangular pattern and names it.

    The full parameter list, from the type library
    (`D8431606-E4B5-11D1-A5D3-00A0C95752EDx0x0x0.py`), is:

        AddNewRectPattern(iShapeToCopy, iNbOfCopiesInDir1, iNbOfCopiesInDir2,
            iStepInDir1, iStepInDir2, iShapeToCopyPositionAlongDir1,
            iShapeToCopyPositionAlongDir2, iDir1, iDir2, iIsReversedDir1,
            iIsReversedDir2, iRotationAngle) -> RectPattern

    `iIsReversedDir1` is what `reversed_first` drives -- the whole question of
    whether a caller who asks for +X can get it. `second`, when given, drives the
    independent second direction so a two-direction grid can be measured too.
    """
    first_direction = plane_reference(part, plane_name)
    if second is None:
        second_plane, second_copies, second_step = plane_name, 1, step
    else:
        second_plane, second_copies, second_step = second
    second_direction = plane_reference(part, second_plane)
    pattern = factory.AddNewRectPattern(
        pad.com_object,
        copies,
        second_copies,
        step,
        second_step,
        1,
        1,
        first_direction,
        second_direction,
        reversed_first,
        False,
        0,
    )
    pattern.Name = f"{PREFIX}PATTERN"
    return pattern


def remove_pattern(part: Any, selection: Any, pattern: Any) -> None:
    """Deletes one pattern through the Selection, since Shapes.Remove does not exist."""
    if pattern is None:
        return
    selection.Clear()
    selection.Add(pattern)
    selection.Delete()
    selection.Clear()


def main() -> None:
    """Runs the probe against the active Part."""
    catia = Catia.attach()
    part = catia.active_part()
    raw = part.com_object
    body = raw.MainBody
    factory = raw.ShapeFactory
    editor = catia.active_editor()
    selection = editor.Selection

    if find_service(editor) is None:
        print("No candidate service name answered; measurement is unavailable.")
        print("Stopping: the pattern question cannot be settled without it.")
        return
    inertia_service = editor.GetService("InertiaService")
    box_service = editor.GetService("InertiaBoxService")

    print("--- 2. Can the existing solid be measured at all? ---")
    body_reference = attempt(
        "CreateReferenceFromObject(MainBody)",
        lambda: raw.CreateReferenceFromObject(body),
    )
    for label, item in (("MainBody", body), ("Reference(MainBody)", body_reference)):
        if item is None:
            continue
        report_measurement(label, measure(inertia_service, box_service, item))

    print("--- 3. Which axis does each origin plane drive a pattern along? ---")
    print(f"    the pad's own centroid is {_triple(PAD_CENTROID_MM)} mm")
    pad = None
    pattern = None
    try:
        pad = base_pad(part)
        # The whole body is measured, not the pattern feature, so "before" and
        # "after" describe the same thing in the same way.
        before = measure(inertia_service, box_service, body_reference)
        report_measurement("body with the pad", before)

        def run_case(label: str, expectation: str, **kwargs: Any) -> None:
            """Builds one pattern, measures what it added, and removes it again."""
            nonlocal pattern
            print(f"    {label}:")
            pattern = None
            try:
                pattern = pattern_once(part, factory, pad, **kwargs)
            except Exception as error:  # noqa: BLE001 - probing the real failure mode
                print(f"      create FAILED {type(error).__name__}: {str(error)[:110]}")
                return
            try:
                part.update()
            except Auto3dxError as error:
                print(f"      update FAILED: {str(error)[:110]}")
                remove_pattern(part, selection, pattern)
                pattern = None
                return
            after = measure(inertia_service, box_service, body_reference)
            centroid = added_centroid(before, after)
            if after is not None and before is not None:
                added = after["volume_mm3"] - before["volume_mm3"]
                copies_added = added / (PAD_SIDE * PAD_SIDE * PAD_HEIGHT)
                print(f"      material added: {added:.3f} mm3 ({copies_added:.3f} copies)")
            if centroid is not None:
                print(f"      added centroid: {_triple(centroid)} mm")
            print(f"      shift: {describe_shift(PAD_CENTROID_MM, centroid)}")
            print(f"      expected: {expectation}")
            remove_pattern(part, selection, pattern)
            pattern = None
            part.update()

        # Two configurations per plane, because one reading cannot tell a real
        # rule from a coincidence. With N copies at step S the added material is
        # N-1 copies whose combined centroid sits (N/2)*S from the original along
        # the axis, so each case predicts a different, checkable number.
        for copies, step in ((2, 60.0), (3, 100.0)):
            for plane_name in PLANES:
                run_case(
                    f"plane {plane_name}, {copies} copies, step {step:.0f} mm",
                    f"{step * copies / 2.0:.3f} mm along one axis",
                    plane_name=plane_name,
                    copies=copies,
                    step=step,
                )

        print("--- 4. Can the direction be reversed, and is dir2 independent? ---")
        # Without this, an API can only ever offer the direction CATIA happens to
        # pick. iIsReversedDir1 is the only candidate for giving a caller the
        # opposite sense, and dir2 has to be shown to act on its own axis before a
        # two-direction grid can be offered at all.
        run_case(
            "plane XY, 2 copies, step 60 mm, iIsReversedDir1=True",
            "the same 60.000 mm but with the opposite sign to case 3",
            plane_name="XY",
            copies=2,
            step=60.0,
            reversed_first=True,
        )
        run_case(
            "dir1 plane XY 2x60, dir2 plane YZ 2x60",
            "3 copies added, centroid halfway between both axis shifts",
            plane_name="XY",
            copies=2,
            step=60.0,
            second=("YZ", 2, 60.0),
        )

        print("--- 5. Does dir2 use a different axis of the same plane than dir1? ---")
        # Case 4 gave dir1=PlaneXY -> -X and dir2=PlaneYZ -> -Z, not the -Y that
        # dir1 gets from PlaneYZ. That suggests dir1 takes a plane's FIRST axis and
        # dir2 its SECOND (XY -> X then Y, YZ -> Y then Z, ZX -> Z then X). One
        # reading is not a rule, so each plane is isolated in dir2 with dir1 held to
        # a single copy, and the three predictions below either all hold or the
        # hypothesis is wrong.
        for plane_name, expectation in (
            ("XY", "-Y, the second axis of XY"),
            ("YZ", "-Z, the second axis of YZ"),
            ("ZX", "-X, the second axis of ZX"),
        ):
            run_case(
                f"dir1 held at 1 copy, dir2 plane {plane_name} 2x60",
                expectation,
                plane_name="XY",
                copies=1,
                step=60.0,
                second=(plane_name, 2, 60.0),
            )

        # PlaneZX in dir2 predicts -X, which is exactly what PlaneXY gives dir1,
        # so the case above asked for two collinear directions. If that is why it
        # failed, the same plane succeeds once dir1 points elsewhere -- and that
        # would mean a two-direction API has to refuse collinear pairs itself
        # rather than let Part.Update() fail with a broken feature in the tree.
        run_case(
            "dir1 plane YZ held at 1 copy, dir2 plane ZX 2x60",
            "-X, the second axis of ZX, now that dir1 is not also -X",
            plane_name="YZ",
            copies=1,
            step=60.0,
            second=("ZX", 2, 60.0),
        )
    finally:
        remove_pattern(part, selection, pattern)
        if pad is not None:
            try:
                part.part_design.remove_pad(f"{PREFIX}PAD")
            except Auto3dxError as error:
                print(f"cleanup: pad not removed: {str(error)[:110]}")
        try:
            part.sketches.remove(f"{PREFIX}SKETCH")
        except Auto3dxError:
            pass
        try:
            part.update()
        except Auto3dxError as error:
            print(f"cleanup: update failed: {str(error)[:110]}")


if __name__ == "__main__":
    main()
