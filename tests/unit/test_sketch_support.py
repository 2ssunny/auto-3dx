"""`Sketch.support()` resolves user-defined planes, not just the origin planes.

The handoff acceptance test found the gap: a sketch created on an `auto_3dx` plane was
rediscovered correctly, but `support()` returned `None`, because it only knew the three
origin frames. A sketch cannot be asked what it sits on in this release, so the frames
are compared instead: live, a sketch's `GetAbsoluteAxisData` equals its plane's
`GetOrigin`/`GetFirstAxis`/`GetSecondAxis` exactly, for offset and angle planes alike
(`docs/conventions.md` 1.7).
"""

from typing import Any

import pytest

from auto_3dx._generation import ModelGeneration
from auto_3dx.geometry.planes import GEOMETRICAL_SET_NAME, AnglePlane, OffsetPlane
from auto_3dx.geometry.sketch import SUPPORT_XY, SUPPORT_YZ, Sketch

XY_FRAME = (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
YZ_FRAME = (0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
OFFSET_FRAME = (0.0, 0.0, 35.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
ANGLE_FRAME = (0.0, 0.0, 0.0, 0.0, 1.0, 0.0, -0.8660254037844386, 0.0, 0.5)
UNKNOWN_FRAME = (7.0, 8.0, 9.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)


class _Collection:
    """Fake 1-based COM collection."""

    def __init__(self, items: "list[Any]") -> None:
        self._items = items

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self._items)

    def Item(self, index: int) -> Any:  # noqa: N802 - COM method name
        return self._items[index - 1]


class HybridShapePlaneOffset:
    """Fake offset plane that reports its own frame, as the live object does."""

    def __init__(self, name: str, frame: "tuple[float, ...]") -> None:
        self.Name = name
        self._frame = frame

    def IsARefPlane(self) -> int:  # noqa: N802 - COM method name
        return 1

    def GetOrigin(self, seed: Any) -> "tuple[float, ...]":  # noqa: N802 - COM method name
        return self._frame[0:3]

    def GetFirstAxis(self, seed: Any) -> "tuple[float, ...]":  # noqa: N802 - COM method
        return self._frame[3:6]

    def GetSecondAxis(self, seed: Any) -> "tuple[float, ...]":  # noqa: N802 - COM method
        return self._frame[6:9]


class HybridShapePlaneAngle(HybridShapePlaneOffset):
    """Fake angle plane; same frame getters, different kind name."""


class HybridShapePointCoord:
    """Fake axis point: in the set, not a plane, and with no frame to report."""

    def __init__(self, name: str) -> None:
        self.Name = name


class _HybridBody:
    """Fake geometrical set."""

    def __init__(self, name: str, shapes: "list[Any]") -> None:
        self.Name = name
        self._shapes = shapes

    @property
    def HybridShapes(self) -> _Collection:  # noqa: N802 - COM property name
        return _Collection(self._shapes)


class _Part:
    """Fake `Part` exposing only what plane lookup reads."""

    def __init__(self, shapes: "list[Any]") -> None:
        self.HybridBodies = _Collection([_HybridBody(GEOMETRICAL_SET_NAME, shapes)])


class _RefusingPart(_Part):
    """Fails the test if the planes are enumerated at all."""

    def __init__(self) -> None:  # noqa: D107 - fake
        pass

    @property
    def HybridBodies(self) -> Any:  # noqa: N802 - COM property name
        raise AssertionError("An origin-plane sketch must not enumerate the planes.")


class _RawSketch:
    """Fake `Sketch`: only `GetAbsoluteAxisData`, as the live object has."""

    def __init__(self, frame: "tuple[float, ...]") -> None:
        self.Name = "SKETCH"
        self._frame = frame

    def GetAbsoluteAxisData(self, seed: Any) -> "tuple[float, ...]":  # noqa: N802
        return self._frame


def _sketch(frame: "tuple[float, ...]", part: Any = None) -> Sketch:
    return Sketch(_RawSketch(frame), ModelGeneration(), part)


def test_an_origin_plane_sketch_still_reports_its_support_string() -> None:
    assert _sketch(XY_FRAME).support() == SUPPORT_XY
    assert _sketch(YZ_FRAME).support() == SUPPORT_YZ


def test_an_origin_plane_sketch_does_not_enumerate_the_planes() -> None:
    """The verified constant frames answer first; the Part is never read."""
    assert _sketch(XY_FRAME, _RefusingPart()).support() == SUPPORT_XY


def test_a_sketch_on_an_offset_plane_reports_that_plane() -> None:
    part = _Part([HybridShapePlaneOffset("TOP_OFFSET", OFFSET_FRAME)])

    support = _sketch(OFFSET_FRAME, part).support()

    assert isinstance(support, OffsetPlane)
    assert support.name == "TOP_OFFSET"


def test_a_sketch_on_an_angle_plane_reports_that_plane() -> None:
    """An angle plane's frame is not axis aligned, which is why equality is used."""
    part = _Part([HybridShapePlaneAngle("TILTED", ANGLE_FRAME)])

    support = _sketch(ANGLE_FRAME, part).support()

    assert isinstance(support, AnglePlane)
    assert support.name == "TILTED"


def test_the_right_plane_is_picked_out_of_several() -> None:
    part = _Part(
        [
            HybridShapePlaneOffset("OTHER", (0.0, 0.0, 10.0) + OFFSET_FRAME[3:]),
            HybridShapePlaneOffset("WANTED", OFFSET_FRAME),
            HybridShapePlaneAngle("TILTED", ANGLE_FRAME),
        ]
    )

    support = _sketch(OFFSET_FRAME, part).support()

    assert support is not None
    assert support.name == "WANTED"


def test_a_sketch_matching_no_plane_reports_none() -> None:
    part = _Part([HybridShapePlaneOffset("TOP_OFFSET", OFFSET_FRAME)])

    assert _sketch(UNKNOWN_FRAME, part).support() is None


def test_two_planes_sharing_one_frame_are_not_guessed_between() -> None:
    part = _Part(
        [
            HybridShapePlaneOffset("FIRST", OFFSET_FRAME),
            HybridShapePlaneOffset("SECOND", OFFSET_FRAME),
        ]
    )

    assert _sketch(OFFSET_FRAME, part).support() is None


def test_shapes_that_cannot_report_a_frame_are_skipped() -> None:
    """The axis points and lines of an angle plane have no frame getters."""
    part = _Part(
        [
            HybridShapePointCoord("TILTED_AxisStart"),
            HybridShapePlaneOffset("TOP_OFFSET", OFFSET_FRAME),
        ]
    )

    support = _sketch(OFFSET_FRAME, part).support()

    assert support is not None
    assert support.name == "TOP_OFFSET"


def test_a_sketch_built_without_a_part_reports_none_rather_than_failing() -> None:
    assert _sketch(OFFSET_FRAME).support() is None


def test_resolving_the_support_does_not_advance_the_generation() -> None:
    generation = ModelGeneration()
    part = _Part([HybridShapePlaneOffset("TOP_OFFSET", OFFSET_FRAME)])
    sketch = Sketch(_RawSketch(OFFSET_FRAME), generation, part)

    sketch.support()

    assert generation.value == 0


@pytest.mark.parametrize("frame", [XY_FRAME, OFFSET_FRAME])
def test_the_returned_support_is_what_create_accepts(frame: "tuple[float, ...]") -> None:
    """A rediscovered support can be handed straight back to sketches.create()."""
    part = _Part([HybridShapePlaneOffset("TOP_OFFSET", OFFSET_FRAME)])

    support = _sketch(frame, part).support()

    assert isinstance(support, str) or hasattr(support, "com_object")
