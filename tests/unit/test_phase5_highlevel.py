"""Phase 5 Level 3: the intent API maps onto public Level 2 calls and nothing else.

The fakes here stand in for the PUBLIC Level 2 API -- `part.work_in`, `part.part_design.
create_*`, `part.topology.faces()/edges()`, `part.measurement.measure()` -- and record how
they were called. Nothing below touches a COM fake directly except through real Level 2
wrappers (`Sketch`, `Face`), so these tests pin the mapping, not COM details.
"""

from contextlib import contextmanager
from collections.abc import Iterator
from typing import Any

import pytest

from auto_3dx.errors import (
    AutomationError,
    FactUnavailableError,
    ParameterTypeError,
    TargetNotUpToDateError,
    TopologyQueryAmbiguousError,
    UnknownFactError,
    UnsupportedOperationError,
    ValidationError,
)
from auto_3dx._generation import ModelGeneration
from auto_3dx.geometry.edges import Edge, EdgeSnapshot
from auto_3dx.geometry.faces import Face, FaceSnapshot
from auto_3dx.geometry.part_design import (
    CHAMFER_ORIENTATION_0,
    CHAMFER_PROPAGATION_0,
    DIRECTION_AGAINST_SKETCH_NORMAL,
    DIRECTION_ALONG_SKETCH_NORMAL,
)
from auto_3dx.geometry.sketch import Sketch
from auto_3dx.highlevel import (
    BodyFeatures,
    PartGeometry,
    extrusion_direction,
    hole_origin,
    pattern_spacing,
    read_facts,
)
from auto_3dx.inspect.summary import FeatureInfo, Inspector
from auto_3dx.measurement.inertia import MassProperties
from tests.conftest import Sketch as FakeSketch
from tests.unit.test_phase4 import (
    X,
    Y,
    Z,
    _block_faces,
    _circle,
    _cylinder_face,
    _line,
    _measurer,
    _plane_face,
)

LISTING = (FeatureInfo(name="Base", kind="Pad", supported=True),)


# --- a recording stand-in for the public Level 2 API -------------------------------------------


class _PartDesign:
    def __init__(self, log: "list[tuple[Any, ...]]") -> None:
        self._log = log

    def __getattr__(self, name: str) -> Any:
        if not name.startswith("create_"):
            raise AttributeError(name)

        def call(*args: Any, **kwargs: Any) -> Any:
            self._log.append((name, args, kwargs))
            return f"<{name}>"

        return call


class _Level2Part:
    def __init__(self) -> None:
        self.log: "list[tuple[Any, ...]]" = []
        self.part_design = _PartDesign(self.log)

    @contextmanager
    def work_in(self, body: Any) -> Iterator[Any]:
        self.log.append(("enter", body))
        yield body
        self.log.append(("exit", body))


BODY = "<the body>"


def _features() -> "tuple[BodyFeatures, _Level2Part]":
    part = _Level2Part()
    return BodyFeatures(LISTING, part, BODY), part


def _sketch(
    axis: "tuple[float, ...]" = (0, 0, 0, 1, 0, 0, 0, 1, 0), on_face: bool = False
) -> Sketch:
    sketch = Sketch(FakeSketch(axis_data=axis))
    sketch._created_on_face = on_face
    return sketch


def _face(shape: Any) -> Face:
    return Face(shape, 1, 0, measurer=_measurer())


# --- body.features is still the listing ---------------------------------------------------------


def test_body_features_is_still_the_feature_info_tuple() -> None:
    features, _ = _features()

    assert isinstance(features, tuple)
    assert features == LISTING
    assert list(features) == list(LISTING)
    assert features[0].name == "Base"
    assert len(features) == 1


def test_a_body_without_a_part_cannot_build() -> None:
    features = BodyFeatures(LISTING, None, BODY)

    with pytest.raises(ValidationError, match="part.bodies"):
        features.pad("P", _sketch(), 10.0)


# --- each intent method is one Level 2 call inside work_in(body) ------------------------------


def test_pad_is_create_pad_inside_work_in() -> None:
    features, part = _features()
    sketch = _sketch()

    assert features.pad("Base", sketch, 20.0, direction="+Z") == "<create_pad>"

    assert part.log == [
        ("enter", BODY),
        ("create_pad", ("Base", sketch, 20.0, "mm", DIRECTION_ALONG_SKETCH_NORMAL), {}),
        ("exit", BODY),
    ]


def test_pocket_into_material_on_a_face_sketch_cuts_against_the_normal() -> None:
    features, part = _features()
    sketch = _sketch(on_face=True)

    features.pocket("Cut", sketch, 5.0, direction="into_material")

    assert part.log[1] == (
        "create_pocket",
        ("Cut", sketch, 5.0, "mm", DIRECTION_AGAINST_SKETCH_NORMAL),
        {},
    )


def test_hole_maps_a_two_number_center_and_writes_every_attribute() -> None:
    features, part = _features()
    top = _face(_plane_face(2400.0, (0, 0, 20), X, Y, origin=(0, 0, 20)))

    features.hole("H", support=top, center=(20.0, 15.0), diameter=6.0, limit="through_all")

    assert part.log[1] == (
        "create_hole",
        ("H", top, None, "mm"),
        {
            "origin": (20.0, 15.0, 20.0),
            "diameter": 6.0,
            "limit": "through_all",
            "bottom": "flat",
            "head": None,
        },
    )


def test_hole_refuses_any_direction_but_into_material() -> None:
    features, part = _features()
    top = _face(_plane_face(2400.0, (0, 0, 20), X, Y))

    with pytest.raises(UnsupportedOperationError, match="into_material"):
        features.hole(
            "H", support=top, center=(0, 0), diameter=6, depth=5, direction="out_of_material"
        )
    with pytest.raises(ParameterTypeError, match="Face"):
        features.hole("H", support="top", center=(0, 0), diameter=6, depth=5)
    assert part.log == []


def test_fillet_takes_exactly_one_edge() -> None:
    features, part = _features()
    edge = Edge(_line((0, 0, 0), (0, 0, 10)), 1, 0, measurer=_measurer())

    features.fillet("F", edges=[edge], radius=2.0)
    features.fillet("F2", edges=edge, radius=2.0)
    with pytest.raises(UnsupportedOperationError, match="several edges"):
        features.fillet("F3", edges=[edge, edge], radius=2.0)

    calls = [entry for entry in part.log if entry[0] == "create_edge_fillet"]
    assert calls == [
        ("create_edge_fillet", ("F", edge, 2.0, "mm"), {}),
        ("create_edge_fillet", ("F2", edge, 2.0, "mm"), {}),
    ]


def test_chamfer_uses_the_verified_length_angle_mode() -> None:
    features, part = _features()
    edge = Edge(_line((0, 0, 0), (0, 0, 10)), 1, 0, measurer=_measurer())

    features.chamfer("C", edge=edge, length=1.5)

    assert part.log[1] == (
        "create_chamfer",
        ("C", edge, 1.5, 45.0, CHAMFER_PROPAGATION_0, CHAMFER_ORIENTATION_0, "mm"),
        {},
    )


def test_circular_pattern_converts_a_total_angle_into_the_verified_spacing() -> None:
    features, part = _features()

    features.circular_pattern("P", feature="<hole>", instances=6, total_angle_deg=360, axis="Z")
    features.circular_pattern(
        "Q", feature="<hole>", instances=4, spacing_deg=30.0, axis="X", reverse=True
    )

    calls = [entry for entry in part.log if entry[0] == "create_circular_pattern"]
    assert calls == [
        ("create_circular_pattern", ("P", "<hole>", 6, 60.0, "Z"), {"reverse": False}),
        ("create_circular_pattern", ("Q", "<hole>", 4, 30.0, "X"), {"reverse": True}),
    ]


# --- direction vocabulary -----------------------------------------------------------------------


def test_axis_directions_come_from_the_sketch_frame() -> None:
    on_xy = _sketch()
    on_bottom = _sketch(axis=(0, 0, 0, 1, 0, 0, 0, -1, 0))  # normal -Z (probe 46j)

    assert extrusion_direction("+Z", on_xy) == DIRECTION_ALONG_SKETCH_NORMAL
    assert extrusion_direction("-Z", on_xy) == DIRECTION_AGAINST_SKETCH_NORMAL
    assert extrusion_direction("+Z", on_bottom) == DIRECTION_AGAINST_SKETCH_NORMAL
    assert extrusion_direction(None, on_xy) is None
    assert extrusion_direction("against_normal", on_xy) == DIRECTION_AGAINST_SKETCH_NORMAL
    with pytest.raises(UnsupportedOperationError, match="not parallel"):
        extrusion_direction("+X", on_xy)


def test_material_side_needs_a_sketch_created_on_a_face() -> None:
    assert extrusion_direction("out_of_material", _sketch(on_face=True)) == (
        DIRECTION_ALONG_SKETCH_NORMAL
    )
    with pytest.raises(UnsupportedOperationError, match="created on a face"):
        extrusion_direction("into_material", _sketch())


@pytest.mark.parametrize("word", ["forward", "reverse", "up", 1])
def test_ambiguous_direction_words_are_refused(word: Any) -> None:
    with pytest.raises(ParameterTypeError):
        extrusion_direction(word, _sketch())


# --- hole centre and pattern spacing ----------------------------------------------------------


def test_a_two_number_center_names_the_other_world_axes() -> None:
    side = _face(_plane_face(800.0, (30, 0, 10), Y, Z))

    assert hole_origin((0.0, 10.0), side) == (30.0, 0.0, 10.0)
    assert hole_origin((1.0, 2.0, 3.0), side) == (1.0, 2.0, 3.0)
    with pytest.raises(UnsupportedOperationError, match="planar"):
        hole_origin((0, 0), _face(_cylinder_face(10.0, (0, 0, 0), 5.0)))
    tilted = _face(_plane_face(10.0, (0, 0, 0), (0.6, 0.8, 0), Z))
    with pytest.raises(UnsupportedOperationError, match="world axis"):
        hole_origin((0, 0), tilted)
    with pytest.raises(ParameterTypeError):
        hole_origin((0,), side)


def test_pattern_spacing_takes_exactly_one_intent() -> None:
    assert pattern_spacing(6, None, 360) == pytest.approx(60.0)
    assert pattern_spacing(5, None, 180) == pytest.approx(45.0)
    assert pattern_spacing(6, 15.0, None) == 15.0
    with pytest.raises(ParameterTypeError):
        pattern_spacing(6, 60.0, 360)
    with pytest.raises(ParameterTypeError):
        pattern_spacing(6, None, None)
    with pytest.raises(ParameterTypeError):
        pattern_spacing(6, None, 400)


# --- semantic finders compose snapshot.query() -----------------------------------------------


class _Topology:
    def __init__(self, faces: "list[Any]", edges: "list[Any]") -> None:
        self.faces_calls: "list[Any]" = []
        self.edges_calls: "list[Any]" = []
        self._faces, self._edges = faces, edges

    def faces(self, body: Any = None) -> FaceSnapshot:
        self.faces_calls.append(body)
        generation = ModelGeneration()
        measurer = _measurer()
        return FaceSnapshot(
            [
                Face(shape, index, 0, measurer=measurer, model_generation=generation)
                for index, shape in enumerate(self._faces, 1)
            ],
            0,
        )

    def edges(self, body: Any = None) -> EdgeSnapshot:
        self.edges_calls.append(body)
        measurer = _measurer()
        return EdgeSnapshot(
            [
                Edge(shape, index, 0, measurer=measurer)
                for index, shape in enumerate(self._edges, 1)
            ],
            0,
        )


class _FinderPart:
    def __init__(self, faces: "list[Any]", edges: "list[Any]" = ()) -> None:
        self.topology = _Topology(list(faces), list(edges))


def test_top_and_bottom_face_use_the_planar_parallel_extreme_rule() -> None:
    part = _FinderPart(_block_faces())
    geometry = PartGeometry(part)

    assert geometry.top_face(body="PartBody").geometry.center_mm == (0.5, 0, 20)
    assert geometry.bottom_face().geometry.center_mm == (0.5, 0, 0)
    assert part.topology.faces_calls[0] == "PartBody"


def test_find_planar_face_and_find_cylindrical_face() -> None:
    geometry = PartGeometry(_FinderPart(_block_faces()))

    side = geometry.find_planar_face(normal_parallel="X", extreme=("X", "max"))
    bore = geometry.find_cylindrical_face(radius=5.0)

    assert side.geometry.center_mm == (30, 0, 10)
    assert bore.geometry.radius_mm == 5.0
    with pytest.raises(TopologyQueryAmbiguousError):
        geometry.find_planar_face(normal_parallel="X")


def test_find_edge_combines_type_radius_plane_and_position() -> None:
    edges = [
        _circle((-15, 0, 20), 5.0),
        _circle((-15, 0, 0), 5.0),
        _line((-30, 20, 20), (30, 20, 20)),
    ]
    part = _FinderPart(_block_faces(), edges)
    geometry = PartGeometry(part)
    top = geometry.top_face()

    rim = geometry.find_edge(kind="circle", radius=5.0, on_plane_of=top)

    assert rim.geometry.center_mm == (-15, 0, 20)
    assert geometry.find_edge(kind="line", parallel="X").geometry.length_mm == pytest.approx(60)
    with pytest.raises(ParameterTypeError, match="kind"):
        geometry.find_edge(kind="spline")


# --- targeted facts never search topology -----------------------------------------------------


class _Bodies:
    def __init__(self) -> None:
        self.main = type("MainBody", (), {"sketch_names": ("S1", "S2")})()

    def names(self) -> "list[str]":
        return ["PartBody", "Tool"]


class _Inspect:
    def __init__(self, features: "tuple[Any, ...]") -> None:
        self._features = features

    def features(self) -> "tuple[Any, ...]":
        return self._features


class _Measurement:
    def __init__(self, outcome: Any) -> None:
        self.calls = 0
        self._outcome = outcome

    def measure(self) -> Any:
        self.calls += 1
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome


class _FactsPart:
    name = "3D Shape1"

    def __init__(self, outcome: Any, features: "tuple[Any, ...]" = LISTING) -> None:
        self.measurement = _Measurement(outcome)
        self.inspect = _Inspect(features)
        self.bodies = _Bodies()
        self.up_to_date_calls = 0

    def is_up_to_date(self) -> bool:
        self.up_to_date_calls += 1
        return True

    @property
    def topology(self) -> Any:
        raise AssertionError("facts() must never take a topology snapshot")


MASS = MassProperties(volume_mm3=48000.0, area_mm2=8800.0, mass_kg=0.1, cog_mm=(0, 0, 10))


def test_facts_read_only_what_was_asked_with_one_measurement() -> None:
    part = _FactsPart(MASS)

    facts = read_facts(part, ("volume", "up_to_date", "surface_area", "volume"))

    assert facts.values == {"volume": 48000.0, "up_to_date": True, "surface_area": 8800.0}
    assert facts["volume"] == 48000.0
    assert part.measurement.calls == 1
    assert part.up_to_date_calls == 1
    assert dict(facts.unavailable) == {}


def test_counting_facts_do_not_measure() -> None:
    part = _FactsPart(MASS)

    facts = read_facts(part, ("feature_count", "sketch_count", "body_count", "name"))

    assert facts.as_dict() == {
        "feature_count": 1,
        "sketch_count": 2,
        "body_count": 2,
        "name": "3D Shape1",
    }
    assert part.measurement.calls == 0


def test_an_unbuilt_or_empty_body_makes_mass_facts_unavailable_not_an_error() -> None:
    stale = read_facts(_FactsPart(TargetNotUpToDateError("not rebuilt")), ("volume", "mass"))
    empty = read_facts(_FactsPart(AutomationError("E_FAIL"), features=()), ("volume",))

    assert set(stale.unavailable) == {"volume", "mass"}
    assert "rebuilt" in stale.unavailable["volume"]
    assert "no feature" in empty.unavailable["volume"]
    with pytest.raises(FactUnavailableError, match="volume"):
        _ = empty["volume"]
    assert "volume" not in empty


def test_a_measurement_failure_on_a_real_solid_propagates() -> None:
    with pytest.raises(AutomationError):
        read_facts(_FactsPart(AutomationError("E_FAIL")), ("volume",))


def test_unknown_facts_are_refused_before_any_read() -> None:
    part = _FactsPart(MASS)

    with pytest.raises(UnknownFactError, match="colour"):
        read_facts(part, ("volume", "colour"))
    with pytest.raises(UnknownFactError):
        read_facts(part, ())
    assert part.measurement.calls == 0


def test_inspector_facts_delegates_to_read_facts() -> None:
    facts = Inspector(_FactsPart(MASS)).facts("volume")

    assert facts.values == {"volume": 48000.0}


# --- sketch primitives compose SketchEditor ---------------------------------------------------


def test_rectangle_draws_four_lines_and_no_constraints_by_default() -> None:
    raw = FakeSketch()
    profile = Sketch(raw).rectangle(width=50, height=30, origin=(0, 0))

    assert raw.factory2d.line_calls == [
        (0.0, 0.0, 50.0, 0.0),
        (50.0, 0.0, 50.0, 30.0),
        (50.0, 30.0, 0.0, 30.0),
        (0.0, 30.0, 0.0, 0.0),
    ]
    assert profile.constraints == ()
    assert raw.open_edition_calls == raw.close_edition_calls == 1


def test_dimensioned_rectangle_adds_exactly_the_verified_constraints() -> None:
    raw = FakeSketch()
    profile = Sketch(raw).centered_rectangle(width=50, height=30, constraints="dimensioned")

    codes = [code for code, _ in raw.Constraints.mono_calls]
    assert codes == [10, 10, 13, 13, 5, 5]  # H, H, V, V, length, length (probe 46ae order)
    assert [element for _, element in raw.Constraints.mono_calls] == [
        profile.bottom.com_object,
        profile.top.com_object,
        profile.right.com_object,
        profile.left.com_object,
        profile.bottom.com_object,
        profile.left.com_object,
    ]
    assert [c.value for c in profile.constraints[4:]] == [50.0, 30.0]
    assert raw.factory2d.line_calls[0] == (-25.0, -15.0, 25.0, -15.0)


@pytest.mark.parametrize("level", ["full", "geometric", ""])
def test_no_constraint_level_claims_more_than_was_verified(level: str) -> None:
    raw = FakeSketch()

    with pytest.raises(ParameterTypeError, match="constraints must be one of"):
        Sketch(raw).rectangle(10, 10, constraints=level)
    assert raw.open_edition_calls == 0


def test_circle_primitive() -> None:
    raw = FakeSketch()

    Sketch(raw).circle(center=(20, 15), radius=3)

    assert raw.factory2d.circle_calls == [(20.0, 15.0, 3.0)]
    with pytest.raises(ParameterTypeError):
        Sketch(raw).circle(center=(0, 0), radius=-1)
