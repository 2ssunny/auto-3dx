"""v1 topology: true face/edge adjacency, measured as point-to-face distance.

The fakes follow probe 47l: `GetMeasurable(face, 1)` is a `MeasurableBetween` whose
`DistanceMinToPoint(x, y, z)` returns `(distance, x, y, z)` to the BOUNDED face -- a point
in the face's plane beyond its edge measures the distance to that edge, not 0. Each fake face
is an axis-aligned rectangle, so that distance is the distance to a flat box.

The block is 60 x 40 x 20 (x in [-30, 30], y in [-20, 20], z in [0, 20]); its search also
returns the 4 profile edges of the consumed sketch at z = 0 (probe 46y: 16 edges). A second,
separate block stands next to it with its top face in the same plane.
"""

import math
from typing import Any

import pytest

from auto_3dx._generation import ModelGeneration
from auto_3dx.errors import (
    ParameterTypeError,
    StaleSnapshotError,
    UnsupportedOperationError,
    ValidationError,
)
from auto_3dx.geometry._topology_search import BodyIndex
from auto_3dx.geometry.edges import Edge, EdgeSnapshot
from auto_3dx.geometry.facts import GeometryMeasurer
from auto_3dx.geometry.faces import Face, FaceSnapshot
from auto_3dx.geometry.topology import Topology
from tests.unit.test_phase4 import _Editor, _line, _Shape, _Typed

Box = "tuple[tuple[float, float], tuple[float, float], tuple[float, float]]"


class _Between(_Typed):
    def DistanceMinToPoint(self, x: float, y: float, z: float) -> Any:  # noqa: N802
        low_high = self._fact("box")
        gaps = [max(low - p, 0.0, p - high) for p, (low, high) in zip((x, y, z), low_high)]
        return (math.sqrt(sum(gap * gap for gap in gaps)), x, y, z)


def _measurer(editor: "_Editor | None" = None) -> GeometryMeasurer:
    return GeometryMeasurer(
        editor or _Editor(), cast=lambda item, interface: _Between(item, interface)
    )


def _rect(box: Any, normal_axis: int) -> _Shape:
    """A planar face that is the flat box `box`, normal along one world axis."""
    center = tuple((low + high) / 2 for low, high in box)
    sizes = [high - low for low, high in box]
    area = math.prod(size for index, size in enumerate(sizes) if index != normal_axis)
    u, v = [
        tuple(1.0 if i == axis else 0.0 for i in range(3))
        for axis in range(3)
        if axis != normal_axis
    ]
    return _Shape(area=area / 1e6, cog=center, perimeter=10.0, plane=(*center, *u, *v), box=box)


def _block_faces(x0: float, x1: float) -> "dict[str, _Shape]":
    return {
        "top": _rect(((x0, x1), (-20, 20), (20, 20)), 2),
        "bottom": _rect(((x0, x1), (-20, 20), (0, 0)), 2),
        "front": _rect(((x0, x1), (-20, -20), (0, 20)), 1),
        "back": _rect(((x0, x1), (20, 20), (0, 20)), 1),
        "left": _rect(((x0, x0), (-20, 20), (0, 20)), 0),
        "right": _rect(((x1, x1), (-20, 20), (0, 20)), 0),
    }


def _block_edges(x0: float, x1: float) -> "dict[str, _Shape]":
    edges = {}
    for z in (0.0, 20.0):
        level = "top" if z else "bottom"
        edges[f"{level}-front"] = _line((x0, -20, z), (x1, -20, z))
        edges[f"{level}-back"] = _line((x0, 20, z), (x1, 20, z))
        edges[f"{level}-left"] = _line((x0, -20, z), (x0, 20, z))
        edges[f"{level}-right"] = _line((x1, -20, z), (x1, 20, z))
    for x in (x0, x1):
        for y in (-20.0, 20.0):
            edges[f"vertical {x} {y}"] = _line((x, y, 0), (x, y, 20))
    return edges


def _sketch_edges(x0: float, x1: float) -> "dict[str, _Shape]":
    return {
        f"sketch {name}": shape
        for name, shape in _block_edges(x0, x1).items()
        if name.startswith("bottom")
    }


class _Model:
    """Snapshots of the block (and optionally its coplanar neighbour) for one Part."""

    def __init__(self, neighbour: bool = False) -> None:
        self.generation = ModelGeneration()
        self.editor = _Editor()
        self.measurer = _measurer(self.editor)
        self.face_shapes = _block_faces(-30, 30)
        self.edge_shapes = _block_edges(-30, 30)
        self.sketch_shapes = _sketch_edges(-30, 30)
        if neighbour:
            self.face_shapes.update({f"n-{k}": v for k, v in _block_faces(40, 60).items()})
            self.edge_shapes.update({f"n-{k}": v for k, v in _block_edges(40, 60).items()})

    def faces(self) -> "tuple[FaceSnapshot, dict[str, Face]]":
        named = {
            name: Face(
                shape,
                index,
                self.generation.value,
                owner_body="PartBody",
                measurer=self.measurer,
                model_generation=self.generation,
            )
            for index, (name, shape) in enumerate(self.face_shapes.items(), start=1)
        }
        return FaceSnapshot(list(named.values()), self.generation.value), named

    def edges(self) -> "tuple[EdgeSnapshot, dict[str, Edge]]":
        shapes = [(name, shape, False) for name, shape in self.edge_shapes.items()]
        shapes += [(name, shape, True) for name, shape in self.sketch_shapes.items()]
        named = {
            name: Edge(
                shape,
                index,
                self.generation.value,
                owner_body="PartBody",
                owner_feature_name="Sketch.1" if sketch else "Pad.1",
                measurer=self.measurer,
                model_generation=self.generation,
                from_sketch=sketch,
            )
            for index, (name, shape, sketch) in enumerate(shapes, start=1)
        }
        return EdgeSnapshot(list(named.values()), self.generation.value), named


def _names(elements: "list[Any]", named: "dict[str, Any]") -> "set[str]":
    return {name for name, element in named.items() if any(element is e for e in elements)}


# --- Face.distance_to ----------------------------------------------------------------------------


def test_distance_is_to_the_bounded_face_not_its_plane() -> None:
    model = _Model()
    _, faces = model.faces()
    top = faces["top"]

    assert top.distance_to((0, 0, 20)) == 0.0
    assert top.distance_to((0, 0, 25)) == 5.0
    assert top.distance_to((40, 0, 20)) == 10.0  # probe 47l: in the plane, beyond the edge


def test_a_face_is_measured_for_distance_once() -> None:
    model = _Model()
    _, faces = model.faces()
    before = model.editor.service.calls

    for x in range(5):
        faces["top"].distance_to((x, 0, 20))

    assert model.editor.service.calls == before + 1


@pytest.mark.parametrize("point", [(0, 0), "origin", (0, 0, float("inf")), (True, 0, 0)])
def test_a_bad_point_is_refused(point: Any) -> None:
    _, faces = _Model().faces()

    with pytest.raises(ParameterTypeError):
        faces["top"].distance_to(point)


def test_a_stale_face_measures_nothing() -> None:
    model = _Model()
    _, faces = model.faces()
    model.generation.advance()

    with pytest.raises(StaleSnapshotError):
        faces["top"].distance_to((0, 0, 20))


# --- edges bounding a face -----------------------------------------------------------------------


def test_the_edges_of_a_face_are_its_boundary_not_everything_on_its_plane() -> None:
    model = _Model(neighbour=True)
    _, faces = model.faces()
    snapshot, edges = model.edges()

    bounding = snapshot.query().adjacent_to(faces["top"]).all()
    coplanar = snapshot.query().on_plane_of(faces["top"]).all()

    assert _names(bounding, edges) == {"top-front", "top-back", "top-left", "top-right"}
    assert len(coplanar) == 8  # the neighbour's top edges share the plane, not the face


def test_profile_edges_of_the_consumed_sketch_are_never_adjacent() -> None:
    model = _Model()
    _, faces = model.faces()
    snapshot, edges = model.edges()

    bounding = snapshot.query().adjacent_to(faces["bottom"]).all()

    assert _names(bounding, edges) == {
        "bottom-front",
        "bottom-back",
        "bottom-left",
        "bottom-right",
    }
    assert len(snapshot.query().on_plane_of(faces["bottom"]).all()) == 8
    assert len(snapshot.query().solid().all()) == 12


def test_a_side_face_is_bounded_by_two_horizontal_and_two_vertical_edges() -> None:
    model = _Model()
    _, faces = model.faces()
    snapshot, edges = model.edges()

    bounding = snapshot.query().adjacent_to(faces["front"])

    assert _names(bounding.all(), edges) == {
        "top-front",
        "bottom-front",
        "vertical -30 -20.0",
        "vertical 30 -20.0",
    }
    assert bounding.parallel((1, 0, 0)).extreme((0, 0, 1)).one() is edges["top-front"]


# --- faces an edge bounds -----------------------------------------------------------------------


def test_an_edge_of_the_solid_bounds_exactly_two_faces() -> None:
    model = _Model(neighbour=True)
    snapshot, faces = model.faces()
    _, edges = model.edges()

    adjacent = snapshot.query().adjacent_to(edges["top-front"]).all()

    assert _names(adjacent, faces) == {"top", "front"}


def test_a_profile_edge_is_refused_as_bounding_nothing() -> None:
    model = _Model()
    snapshot, _ = model.faces()
    _, edges = model.edges()

    with pytest.raises(UnsupportedOperationError, match="sketch"):
        snapshot.query().adjacent_to(edges["sketch bottom-front"])


def test_adjacency_refuses_wrong_types_other_parts_and_stale_handles() -> None:
    model, other = _Model(), _Model()
    faces_snapshot, faces = model.faces()
    edges_snapshot, edges = model.edges()
    _, foreign_faces = other.faces()

    with pytest.raises(ParameterTypeError):
        edges_snapshot.query().adjacent_to(edges["top-front"])  # type: ignore[arg-type]
    with pytest.raises(ParameterTypeError):
        faces_snapshot.query().adjacent_to(faces["top"])  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="different Parts"):
        edges_snapshot.query().adjacent_to(foreign_faces["top"])
    model.generation.advance()
    with pytest.raises(StaleSnapshotError):
        edges_snapshot.query().adjacent_to(faces["top"]).all()


def test_an_adjacency_query_reports_what_it_measured_when_ambiguous() -> None:
    from auto_3dx.errors import TopologyQueryAmbiguousError

    model = _Model()
    _, faces = model.faces()
    snapshot, _ = model.edges()

    with pytest.raises(TopologyQueryAmbiguousError, match="adjacent_to"):
        snapshot.query().adjacent_to(faces["top"]).one()


# --- snapshot-level ownership --------------------------------------------------------------------


class _Named:
    def __init__(self, name: str) -> None:
        self.Name = name


class _Collection:
    def __init__(self, names: "list[str]") -> None:
        self.items = [_Named(name) for name in names]

    @property
    def Count(self) -> int:  # noqa: N802
        return len(self.items)

    def Item(self, index: int) -> Any:  # noqa: N802
        return self.items[index - 1]


class _RawBody:
    def __init__(self, name: str, shapes: "list[str]", sketches: "list[str]") -> None:
        self.Name = name
        self.Shapes = _Collection(shapes)
        self.Sketches = _Collection(sketches)


class _RawPart:
    def __init__(self, bodies: "list[_RawBody]") -> None:
        self.Bodies = _Collection([])
        self.Bodies.items = bodies  # type: ignore[assignment]


def test_the_body_index_tells_sketches_from_solid_features() -> None:
    index = BodyIndex(
        _RawPart(
            [
                _RawBody("PartBody", ["Pad.1", "Twin"], ["Sketch.1"]),
                _RawBody("Tool", ["Pad.2"], ["Twin"]),
            ]
        )
    )

    assert index.is_sketch("Sketch.1") is True
    assert index.is_sketch("Pad.1") is False
    assert index.is_sketch("Twin") is None  # a sketch in one body, a feature in another
    assert index.is_sketch("Nope") is None
    assert index.is_sketch(None) is None


def test_a_profile_edge_says_so_in_its_description() -> None:
    model = _Model()
    _, edges = model.edges()

    assert edges["sketch bottom-front"].describe().startswith("line sketch profile edge")
    assert edges["bottom-front"].describe().startswith("line edge")
    assert edges["bottom-front"].from_sketch is False


# --- part.topology.edges_of / faces_of ------------------------------------------------------------


class _Topology(Topology):
    """`Topology` with its two searches replaced by the model's snapshots."""

    def __init__(self, model: _Model) -> None:
        super().__init__(object(), model.generation)
        self.model = model
        self.scopes: "list[Any]" = []

    def edges(self, body: Any = None) -> EdgeSnapshot:  # type: ignore[override]
        self.scopes.append(("edges", body))
        return self.model.edges()[0]

    def faces(self, body: Any = None) -> FaceSnapshot:  # type: ignore[override]
        self.scopes.append(("faces", body))
        return self.model.faces()[0]


def test_topology_answers_edges_of_a_face_and_faces_of_an_edge_in_its_body() -> None:
    model = _Model()
    topology = _Topology(model)
    _, faces = model.faces()
    _, edges = model.edges()

    bounding = topology.edges_of(faces["top"]).lines().all()
    adjacent = topology.faces_of(edges["top-front"]).all()

    assert len(bounding) == 4
    assert {face.geometry.center_mm for face in adjacent} == {(0.0, 0.0, 20.0), (0.0, -20.0, 10.0)}
    assert topology.scopes == [("edges", "PartBody"), ("faces", "PartBody")]


def test_topology_refuses_a_stale_or_wrong_argument_before_searching() -> None:
    model = _Model()
    topology = _Topology(model)
    _, faces = model.faces()
    _, edges = model.edges()

    with pytest.raises(ParameterTypeError):
        topology.edges_of(edges["top-front"])  # type: ignore[arg-type]
    with pytest.raises(ParameterTypeError):
        topology.faces_of(faces["top"])  # type: ignore[arg-type]
    model.generation.advance()
    with pytest.raises(StaleSnapshotError):
        topology.edges_of(faces["top"])
    assert topology.scopes == []


# --- part.geometry -------------------------------------------------------------------------------


class _FakePart:
    def __init__(self, model: _Model) -> None:
        self.topology = _Topology(model)


def test_high_level_edge_finders_skip_profile_edges_and_take_adjacency() -> None:
    from auto_3dx.highlevel import PartGeometry

    model = _Model(neighbour=True)
    geometry = PartGeometry(_FakePart(model))  # type: ignore[arg-type]
    _, faces = model.faces()
    _, edges = model.edges()

    # Without solid(), each bottom edge would tie with the sketch profile edge under it.
    bottom_front = geometry.find_edge(kind="line", parallel="X", extreme="-Z", nearest=(0, -20, 0))
    top_front = geometry.find_edge(parallel="X", adjacent_to=faces["top"], nearest=(0, -30, 20))

    assert bottom_front is not None and bottom_front.from_sketch is False
    assert top_front.index == edges["top-front"].index  # a fresh snapshot, same edge
    assert len(geometry.edges_of(faces["front"]).all()) == 4
    assert len(geometry.faces_of(edges["top-front"]).all()) == 2


def test_query_directions_take_the_same_axis_names_as_the_finders() -> None:
    model = _Model()
    snapshot, _ = model.edges()

    assert len(snapshot.query().solid().parallel("X").all()) == 4
    assert len(snapshot.query().solid().parallel("-z").all()) == 4
    top = snapshot.query().solid().extreme("+Z").all()
    assert len(top) == 4
    with pytest.raises(ParameterTypeError):
        snapshot.query().parallel("W")
    with pytest.raises(ParameterTypeError):
        snapshot.query().parallel("--X")
