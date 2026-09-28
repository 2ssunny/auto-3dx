"""Phase 5 Level 2: sketch on a planar face, hole placement and limits, pattern axes, setters.

The fakes follow the micro-probes (`docs/phase5-api-design.md` section 3):

    Sketches.Add(<planar face Reference>)                    -> a sketch on that face (46i)
    AddNewHoleFromPoint(x, y, z, face, depth)                -> starts at (x, y, z) (46m)
    Diameter / BottomType / BottomLimit.LimitMode            -> written before update (46s)
    AddNewCircPattern(..., PlaneYZ|PlaneZX|face|edge, ...)   -> X / Y / cylinder / edge axis

Every refusal is checked to happen before the factory or `Sketches.Add` is called.
"""

from typing import Any

import pytest

from auto_3dx.core.part import Part
from auto_3dx.errors import (
    CrossBodyReferenceError,
    ParameterTypeError,
    StaleSnapshotError,
    UnsupportedOperationError,
    UnsupportedSupportError,
    ValidationError,
)
from auto_3dx._generation import ModelGeneration
from auto_3dx.geometry.edges import Edge
from auto_3dx.geometry.faces import Face
from auto_3dx.geometry.part_design import (
    HOLE_BOTTOM_FLAT,
    HOLE_BOTTOM_V,
    HOLE_LIMIT_BLIND,
    HOLE_LIMIT_THROUGH_ALL,
    ConstRadEdgeFillet,
    CircularPattern,
    Pad,
)
from auto_3dx.geometry.part_design import Hole as HoleWrapper
from auto_3dx.geometry.planes import OffsetPlane
from auto_3dx.geometry.query import EdgeQuery
from tests.unit.test_phase4 import _circle, _cylinder_face, _line, _measurer, _plane_face

X, Y, Z = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)


class _Value:
    def __init__(self, value: Any) -> None:
        self.Value = value


class _Items:
    def __init__(self, parent: Any = None) -> None:
        self.items: "list[Any]" = []
        self.Parent = parent

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self.items)

    def Item(self, key: Any) -> Any:  # noqa: N802 - COM method name
        if isinstance(key, str):
            return next(item for item in self.items if item.Name == key)
        return self.items[key - 1]


class Sketch:  # noqa: N801 - CATIA's type name
    def __init__(self, support: Any) -> None:
        self.Name = "Sketch.1"
        self.support = support

    def GetAbsoluteAxisData(self, seed: Any) -> Any:  # noqa: N802
        return (0.0, 0.0, 20.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)


class _Sketches(_Items):
    def __init__(self, parent: Any) -> None:
        super().__init__(parent)
        self.add_calls: "list[Any]" = []

    def Add(self, support: Any) -> Sketch:  # noqa: N802
        self.add_calls.append(support)
        sketch = Sketch(support)
        self.items.append(sketch)
        return sketch


class Body:  # noqa: N801
    def __init__(self, name: str, part: "_Part") -> None:
        self.Name = name
        self.Shapes = _Items(self)
        self.Sketches = _Sketches(self)
        self.Parent = part.Bodies


class _BottomLimit:
    def __init__(self, depth: float, log: "list[str]") -> None:
        self._mode = 0
        self.Dimension = _Value(depth)
        self._log = log

    @property
    def LimitMode(self) -> int:  # noqa: N802
        return self._mode

    @LimitMode.setter
    def LimitMode(self, value: int) -> None:  # noqa: N802
        self._log.append(f"LimitMode={value}")
        self._mode = value


class _Diameter:
    def __init__(self, log: "list[str]") -> None:
        self._value = 12.0
        self._log = log

    @property
    def Value(self) -> float:  # noqa: N802
        return self._value

    @Value.setter
    def Value(self, value: float) -> None:  # noqa: N802
        self._log.append(f"Diameter={value}")
        self._value = value


class Hole:  # noqa: N801
    def __init__(self, body: Body, depth: float, origin: Any) -> None:
        self.Name = "Hole.1"
        self.Parent = body.Shapes
        self.log: "list[str]" = []
        self.Diameter = _Diameter(self.log)
        self.BottomLimit = _BottomLimit(depth, self.log)
        self._bottom = 1
        self._origin = origin

    @property
    def BottomType(self) -> int:  # noqa: N802
        return self._bottom

    @BottomType.setter
    def BottomType(self, value: int) -> None:  # noqa: N802
        self.log.append(f"BottomType={value}")
        self._bottom = value

    def GetOrigin(self, seed: Any) -> Any:  # noqa: N802
        return self._origin

    def GetDirection(self, seed: Any) -> Any:  # noqa: N802
        return (0.0, 0.0, -1.0)


class CircPattern:  # noqa: N801
    def __init__(self, body: Body, args: "tuple[Any, ...]") -> None:
        self.Name = "CircPattern.1"
        self.Parent = body.Shapes
        self.args = args


class _ShapeFactory:
    def __init__(self, part: "_Part") -> None:
        self._part = part
        self.calls: "list[tuple[str, tuple[Any, ...]]]" = []

    def _add(self, feature: Any) -> Any:
        self._part.MainBody.Shapes.items.append(feature)
        return feature

    def AddNewHole(self, face: Any, depth: float) -> Any:  # noqa: N802
        self.calls.append(("AddNewHole", (face, depth)))
        return self._add(Hole(self._part.MainBody, depth, (0.0, 0.0, 0.0)))

    def AddNewHoleFromPoint(
        self,
        x: float,
        y: float,
        z: float,
        face: Any,  # noqa: N802
        depth: float,
    ) -> Any:
        self.calls.append(("AddNewHoleFromPoint", (x, y, z, face, depth)))
        return self._add(Hole(self._part.MainBody, depth, (x, y, z)))

    def AddNewCircPattern(self, *args: Any) -> Any:  # noqa: N802
        self.calls.append(("AddNewCircPattern", args))
        return self._add(CircPattern(self._part.MainBody, args))


class _Origin:
    PlaneXY, PlaneYZ, PlaneZX = "PlaneXY", "PlaneYZ", "PlaneZX"


class _Part:
    def __init__(self) -> None:
        self.Name = "3D Shape1"
        self.Bodies = _Items(self)
        self.MainBody = Body("PartBody", self)
        self.Bodies.items.append(self.MainBody)
        self.ShapeFactory = _ShapeFactory(self)
        self.OriginElements = _Origin()
        self.InWorkObject: Any = self.MainBody

    def IsUpToDate(self, item: Any) -> bool:  # noqa: N802
        return True


def _setup() -> "tuple[Part, _Part]":
    raw = _Part()
    return Part(raw, selection=object()), raw


def _face(part: Part, raw: _Part, shape: Any, owner: Any = None) -> Face:
    generation = part._generation
    return Face(
        shape,
        1,
        generation.value,
        owner_body=owner or raw.MainBody,
        owner_body_name="PartBody",
        measurer=_measurer(),
        model_generation=generation,
    )


def _edge(part: Part, raw: _Part, shape: Any) -> Edge:
    generation = part._generation
    return Edge(
        shape,
        1,
        generation.value,
        owner_body=raw.MainBody,
        owner_body_name="PartBody",
        measurer=_measurer(),
        model_generation=generation,
    )


TOP = _plane_face(2400.0, (0.0, 0.0, 20.0), X, Y, origin=(0.0, 0.0, 20.0))
SIDE = _plane_face(800.0, (30.0, 0.0, 10.0), Y, Z, origin=(30.0, -20.0, 0.0))
BORE = _cylinder_face(628.3, (50.0, 40.0, 5.0), 5.0)


# --- sketch on a planar face -------------------------------------------------------------------


def test_a_planar_face_is_accepted_as_a_sketch_support() -> None:
    part, raw = _setup()
    face = _face(part, raw, TOP)

    sketch = part.sketches.create("POCKET_PROFILE", support=face)

    assert raw.MainBody.Sketches.add_calls == [TOP]
    assert sketch.name == "POCKET_PROFILE"
    assert sketch.created_on_face is True
    assert part.sketches.create("ON_XY_TOO", support="XY").created_on_face is False


def test_a_curved_face_is_refused_before_sketches_add() -> None:
    part, raw = _setup()

    with pytest.raises(UnsupportedSupportError, match="planar"):
        part.sketches.create("S", support=_face(part, raw, BORE))
    assert raw.MainBody.Sketches.add_calls == []


def test_a_stale_face_is_refused_before_sketches_add() -> None:
    part, raw = _setup()
    face = _face(part, raw, TOP)
    part.sketches.create("FIRST", support="XY")  # advances the generation

    with pytest.raises(StaleSnapshotError):
        part.sketches.create("S", support=face)
    assert raw.MainBody.Sketches.add_calls == [raw.OriginElements.PlaneXY]


def test_a_face_of_another_part_is_refused() -> None:
    part, raw = _setup()
    stranger = ModelGeneration()
    face = Face(TOP, 1, part._generation.value, measurer=_measurer(), model_generation=stranger)

    with pytest.raises(ValidationError, match="another Part"):
        part.sketches.create("S", support=face)
    assert raw.MainBody.Sketches.add_calls == []


def test_a_face_of_another_body_is_refused() -> None:
    part, raw = _setup()
    other = Body("Tool", raw)
    raw.Bodies.items.append(other)

    with pytest.raises(CrossBodyReferenceError):
        part.sketches.create("S", support=_face(part, raw, TOP, owner=other))
    assert raw.MainBody.Sketches.add_calls == []


def test_a_body_sketch_collection_adds_to_that_body() -> None:
    part, raw = _setup()
    other = Body("Tool", raw)
    raw.Bodies.items.append(other)

    part.bodies.get("Tool").sketches.create("S", support="XY")

    assert other.Sketches.add_calls == [raw.OriginElements.PlaneXY]
    assert raw.MainBody.Sketches.add_calls == []


# --- hole placement and limits -----------------------------------------------------------------


def test_the_legacy_hole_call_keeps_its_meaning_a_blind_hole_of_that_depth() -> None:
    # The factory call is unchanged. The blind limit is written explicitly because CATIA
    # carries the previous hole's limit over: live, after a through-all hole, a legacy
    # create_hole(face, 5) came out through-all with depth 30.
    part, raw = _setup()
    face = _face(part, raw, TOP)

    hole = part.part_design.create_hole("H", face, 5.0)

    assert raw.ShapeFactory.calls == [("AddNewHole", (TOP, 5.0))]
    assert hole.com_object.log == ["LimitMode=0"]  # diameter and bottom are not touched


def test_a_positioned_hole_writes_every_attribute_before_any_update() -> None:
    part, raw = _setup()
    face = _face(part, raw, TOP)

    hole = part.part_design.create_hole(
        "H",
        face,
        8.0,
        origin=(10.0, 5.0, 20.0),
        diameter=6.0,
        limit=HOLE_LIMIT_BLIND,
        bottom=HOLE_BOTTOM_FLAT,
    )

    assert raw.ShapeFactory.calls == [("AddNewHoleFromPoint", (10.0, 5.0, 20.0, TOP, 8.0))]
    assert hole.com_object.log == ["Diameter=6.0", "BottomType=0", "LimitMode=0"]
    assert hole.origin == (10.0, 5.0, 20.0)
    assert hole.direction == (0.0, 0.0, -1.0)
    assert (hole.limit, hole.bottom) == (HOLE_LIMIT_BLIND, HOLE_BOTTOM_FLAT)


def test_a_through_all_hole_takes_no_depth_and_sets_the_limit() -> None:
    part, raw = _setup()
    face = _face(part, raw, TOP)

    hole = part.part_design.create_hole(
        "H", face, origin=(0.0, 0.0, 20.0), diameter=6.0, limit=HOLE_LIMIT_THROUGH_ALL
    )

    assert hole.com_object.log == ["Diameter=6.0", "LimitMode=2"]
    assert hole.limit == HOLE_LIMIT_THROUGH_ALL
    fresh = _face(part, raw, TOP)  # the creation above made `face` stale
    with pytest.raises(ParameterTypeError, match="no depth"):
        part.part_design.create_hole("H2", fresh, 5.0, limit=HOLE_LIMIT_THROUGH_ALL)


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({}, ParameterTypeError),  # no depth
        ({"depth": 5.0, "limit": "up_to_next"}, ParameterTypeError),
        ({"depth": 5.0, "bottom": "cone"}, ParameterTypeError),
        ({"depth": 5.0, "diameter": 0.0}, ParameterTypeError),
        ({"depth": 5.0, "origin": (1.0, 2.0)}, ParameterTypeError),
        ({"depth": 5.0, "origin": (10.0, 5.0, 25.0)}, ParameterTypeError),  # off the plane
    ],
)
def test_a_bad_hole_request_is_refused_before_the_factory(kwargs: Any, error: type) -> None:
    part, raw = _setup()

    with pytest.raises(error):
        part.part_design.create_hole("H", _face(part, raw, TOP), **kwargs)
    assert raw.ShapeFactory.calls == []


def test_a_positioned_hole_needs_a_planar_face() -> None:
    part, raw = _setup()

    with pytest.raises(UnsupportedSupportError, match="planar"):
        part.part_design.create_hole("H", _face(part, raw, BORE), 5.0, origin=(50, 40, 10))
    assert raw.ShapeFactory.calls == []


def test_a_hole_limit_and_bottom_can_be_changed_afterwards() -> None:
    part, raw = _setup()
    hole = part.part_design.create_hole("H", _face(part, raw, TOP), 8.0, origin=(0, 0, 20))
    before = part._generation.value

    hole.set_limit(HOLE_LIMIT_THROUGH_ALL)
    with pytest.raises(ParameterTypeError, match="depth"):
        hole.set_limit(HOLE_LIMIT_BLIND)
    hole.set_limit(HOLE_LIMIT_BLIND, depth=12.0)
    hole.set_bottom(HOLE_BOTTOM_V)
    hole.diameter = 9.0
    hole.depth = 11.0

    assert hole.com_object.log == [
        "LimitMode=0",  # written at creation: a depth means a blind hole
        "LimitMode=2",
        "LimitMode=0",
        "BottomType=1",
        "Diameter=9.0",
    ]
    assert (hole.depth, hole.diameter, hole.bottom) == (11.0, 9.0, HOLE_BOTTOM_V)
    assert part._generation.value > before


# --- circular pattern axes ---------------------------------------------------------------------


def _seed(raw: _Part) -> Pad:
    class Pad:  # noqa: N801
        Name = "SEED"
        Parent = raw.MainBody.Shapes

    feature = Pad()
    raw.MainBody.Shapes.items.append(feature)
    from auto_3dx.geometry.part_design import Pad as PadWrapper

    return PadWrapper(feature)


@pytest.mark.parametrize(("axis", "plane"), [("X", "PlaneYZ"), ("Y", "PlaneZX"), ("Z", "PlaneXY")])
def test_named_axes_map_to_the_origin_plane_whose_normal_they_are(axis: str, plane: str) -> None:
    part, raw = _setup()

    part.part_design.create_circular_pattern("P", _seed(raw), 4, 90.0, axis=axis)

    ((name, args),) = raw.ShapeFactory.calls
    assert name == "AddNewCircPattern"
    assert (args[7], args[8], args[9]) == (plane, plane, False)


def test_a_cylindrical_face_and_a_line_edge_are_accepted_as_axes() -> None:
    part, raw = _setup()
    bore = _face(part, raw, BORE)
    edge = _edge(part, raw, _line((30, 5, 0), (30, 5, 10)))

    part.part_design.create_circular_pattern("P1", _seed(raw), 4, 90.0, axis=bore)
    part.part_design.create_circular_pattern(
        "P2",
        _seed(raw),
        4,
        90.0,
        axis=_edge(part, raw, _line((30, 5, 0), (30, 5, 10))),
        reverse=True,
    )

    first, second = raw.ShapeFactory.calls
    assert (first[1][7], first[1][8]) == (BORE, BORE)
    assert second[1][9] is True
    del edge


def test_a_planar_face_or_a_circular_edge_is_refused_as_an_axis() -> None:
    part, raw = _setup()

    with pytest.raises(UnsupportedSupportError, match="cylindrical"):
        part.part_design.create_circular_pattern(
            "P", _seed(raw), 4, 90.0, axis=_face(part, raw, TOP)
        )
    with pytest.raises(UnsupportedSupportError, match="straight"):
        part.part_design.create_circular_pattern(
            "P", _seed(raw), 4, 90.0, axis=_edge(part, raw, _circle((0, 0, 0), 5.0))
        )
    with pytest.raises(ParameterTypeError, match="reverse"):
        part.part_design.create_circular_pattern("P", _seed(raw), 4, 90.0, reverse=1)
    assert raw.ShapeFactory.calls == []


# --- plane-coincidence filter ------------------------------------------------------------------


def test_on_plane_of_keeps_edges_lying_in_the_face_plane_only() -> None:
    part, raw = _setup()
    top = _face(part, raw, TOP)
    rim = _edge(part, raw, _circle((10.0, 5.0, 20.0), 3.0))
    top_edge = _edge(part, raw, _line((-30, 20, 20), (30, 20, 20)))
    vertical = _edge(part, raw, _line((30, 20, 0), (30, 20, 20)))

    kept = EdgeQuery([rim, top_edge, vertical]).on_plane_of(top).all()

    assert kept == [rim, top_edge]
    with pytest.raises(UnsupportedOperationError, match="planar"):
        EdgeQuery([rim]).on_plane_of(_face(part, raw, BORE))


# --- property setters are the set_* methods ----------------------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.calls: "list[tuple[str, Any]]" = []


@pytest.mark.parametrize(
    ("cls", "prop", "method"),
    [
        (Pad, "length", "set_height"),
        (Pad, "height", "set_height"),
        (Pad, "depth", "set_depth"),
        (ConstRadEdgeFillet, "radius", "set_radius"),
        (HoleWrapper, "diameter", "set_diameter"),
        (HoleWrapper, "depth", "set_depth"),
        (CircularPattern, "instances", "set_angular_instances"),
        (CircularPattern, "spacing_deg", "set_angular_spacing_deg"),
        (CircularPattern, "angular_instances", "set_angular_instances"),
        (OffsetPlane, "offset", "set_offset"),
    ],
)
def test_assigning_a_property_calls_its_setter_method(
    cls: type, prop: str, method: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: "list[Any]" = []
    monkeypatch.setattr(cls, method, lambda self, value, *rest: seen.append(value))
    wrapper = cls.__new__(cls)

    setattr(wrapper, prop, 7)

    assert seen == [7]
