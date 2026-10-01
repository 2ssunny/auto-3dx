"""Tests for the first safety batch: body-scoped topology, per-body update, preconditions.

The fakes behave as probe 42 measured the live model (`docs/conventions.md` 1.10):

    Search("Topology.Edge,all")     -> every body's edges in one flat list
    Selection.Add(body) + ",sel"    -> that body's edges only, following the selection
    Reference.Parent                -> the owning feature; Parent again -> Shapes -> Body
    Part.IsUpToDate(body)           -> False for a body nothing has rebuilt
    Part.UpdateObject(body)         -> rebuilds that body alone
    EnumParam.Value                 -> AttributeError; ValueAsString() -> a string
    Part.IsUpToDate(new plane)      -> False until the Part is rebuilt

The raw body fake is deliberately called `Body`, because the owner walk recognises the
owning body by its COM wrapper type name, exactly as CATIA reports it.
"""

from typing import Any

import pytest
import pywintypes

from auto_3dx.core.part import Part
from auto_3dx.errors import (
    CrossBodyReferenceError,
    ParameterTypeError,
    PartUpdateError,
    SupportNotUpdatedError,
    TargetNotUpToDateError,
)
from auto_3dx.geometry.edges import (
    EDGE_SEARCH_QUERY,
    EDGE_SEARCH_QUERY_IN_SELECTION,
    Edge,
)
from auto_3dx.geometry.faces import FACE_SEARCH_QUERY_IN_SELECTION, Face
from auto_3dx.measurement.inertia import INERTIA_SERVICE_NAME, SolidMeasurement
from auto_3dx.parameters.parameter import Parameter

MAIN_PAD, TOOL_PAD = "MAIN_PAD", "TOOL_PAD"
TOOL_BODY = "ToolBody"
E_FAIL = -2147467259


def _com_error() -> pywintypes.com_error:
    return pywintypes.com_error(
        -2147352567,
        "Exception occurred.",
        (0, "CATIA", "failed", None, 0, E_FAIL),
        None,
    )


class _Items:
    """Fake 1-based COM collection."""

    def __init__(self, parent: Any = None) -> None:
        self.items: "list[Any]" = []
        self.Parent = parent

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self.items)

    def Item(self, index: int) -> Any:  # noqa: N802 - COM method name
        return self.items[index - 1]


class _Sketches(_Items):
    def Add(self, plane: Any) -> Any:  # noqa: N802 - COM method name
        sketch = _Feature(f"Sketch.{len(self.items) + 1}", self)
        self.items.append(sketch)
        return sketch


class Body:  # noqa: N801 - the owner walk matches CATIA's wrapper type name
    """Fake raw `Body`."""

    def __init__(self, name: str) -> None:
        self.Name = name
        self.Shapes = _Items(self)
        self.Sketches = _Sketches(self)
        self.HybridBodies = _Items(self)


class _Feature:
    """Fake raw feature (a Pad, a fillet, a sketch): its `Parent` is its collection."""

    def __init__(self, name: str, owner: Any) -> None:
        self.Name = name
        self.Parent = owner


class _Reference:
    """Fake topology `Reference`: `Parent` is the feature it came from."""

    def __init__(self, feature: Any, descriptor: str) -> None:
        self.Parent = feature
        self.Name = descriptor


class _Selected:
    def __init__(self, value: Any) -> None:
        self.Value = value
        self.Reference = value


class _ShapeFactory:
    def __init__(self, part: "_Part") -> None:
        self._part = part
        self.calls: "list[tuple[str, Any]]" = []

    def _add(self, method: str, body: Any) -> Any:
        self.calls.append((method, body.Name))
        feature = _Feature(f"{method}.{len(body.Shapes.items) + 1}", body.Shapes)
        body.Shapes.items.append(feature)
        self._part.up_to_date[id(body)] = False
        return feature

    def AddNewEdgeFilletWithConstantRadius(  # noqa: N802 - COM method name
        self, edge: Any, propagation: int, radius: float
    ) -> Any:
        return self._add("EdgeFillet", self._part.in_work_body())

    def AddNewShell(  # noqa: N802 - COM method name
        self, faces: Any, internal: float, external: float
    ) -> Any:
        return self._add("Shell", self._part.in_work_body())


class _OriginElements:
    def __init__(self) -> None:
        self.PlaneXY = object()
        self.PlaneYZ = object()
        self.PlaneZX = object()


class _Editor:
    def __init__(self, active_object: Any) -> None:
        self.ActiveObject = active_object


class _Application:
    def __init__(self, editor: Any) -> None:
        self.ActiveEditor = editor


class _Parameters(_Items):
    pass


class _Part:
    """Fake CATIA `Part` with two bodies, per-object update status and topology."""

    def __init__(self) -> None:
        self.Name = "3D Shape1"
        self.MainBody = Body("PartBody")
        self.tool_body = Body(TOOL_BODY)
        self.Bodies = _Items(self)
        self.Bodies.items.extend([self.MainBody, self.tool_body])
        self.ShapeFactory = _ShapeFactory(self)
        self.OriginElements = _OriginElements()
        self.Parameters = _Parameters(self)
        self._in_work: Any = self.MainBody
        self.Application = _Application(_Editor(self))
        self.up_to_date: "dict[int, bool]" = {}
        self.update_calls: "list[str]" = []
        self.update_object_calls: "list[str]" = []
        self.update_failure: BaseException | None = None
        self.edges: "dict[int, list[_Reference]]" = {}
        self.faces: "dict[int, list[_Reference]]" = {}

    # --- model contents ---------------------------------------------------------
    def add_pad(
        self, body: Body, name: str, edges: int = 2, faces: int = 1
    ) -> _Feature:
        pad = _Feature(name, body.Shapes)
        body.Shapes.items.append(pad)
        self.edges.setdefault(id(body), []).extend(
            _Reference(pad, f"{name}_EDGE_{index}") for index in range(edges)
        )
        self.faces.setdefault(id(body), []).extend(
            _Reference(pad, f"{name}_FACE_{index}") for index in range(faces)
        )
        self.up_to_date[id(body)] = True
        return pad

    def in_work_body(self) -> Body:
        node = self._in_work
        while node is not None and not isinstance(node, Body):
            node = getattr(node, "Parent", None)
        return node if node is not None else self.MainBody

    def topology(self, kind: str, scope: Any) -> "list[_Reference]":
        source = self.edges if kind == "edge" else self.faces
        if scope is None:
            return [
                reference
                for body in self.Bodies.items
                for reference in source.get(id(body), [])
            ]
        return list(source.get(id(scope), []))

    # --- COM surface ------------------------------------------------------------
    @property
    def InWorkObject(self) -> Any:  # noqa: N802 - COM property name
        return self._in_work

    @InWorkObject.setter
    def InWorkObject(self, value: Any) -> None:  # noqa: N802 - COM property name
        self._in_work = value

    def IsUpToDate(self, item: Any) -> bool:  # noqa: N802 - COM method name
        return self.up_to_date.get(id(item), True)

    def Update(self) -> None:  # noqa: N802 - COM method name
        self.update_calls.append("Update")
        if self.update_failure is not None:
            raise self.update_failure
        self.up_to_date = dict.fromkeys(self.up_to_date, True)

    def UpdateObject(self, item: Any) -> None:  # noqa: N802 - COM method name
        self.update_object_calls.append(str(item.Name))
        if self.update_failure is not None:
            raise self.update_failure
        self.up_to_date[id(item)] = True

    def Save(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("Nothing here may save.")


class _Selection:
    """Fake `Selection` whose `Search` honours a `,sel` query, as probe 42 measured."""

    def __init__(self, part: _Part) -> None:
        self._part = part
        self.items: "list[_Selected]" = []
        self.queries: "list[str]" = []
        self.scopes: "list[str | None]" = []

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self.items)

    def Item(self, index: int) -> _Selected:  # noqa: N802 - COM method name
        return self.items[index - 1]

    def Clear(self) -> None:  # noqa: N802 - COM method name
        self.items = []

    def Add(self, value: Any) -> None:  # noqa: N802 - COM method name
        self.items.append(_Selected(value))

    def Search(self, query: str) -> None:  # noqa: N802 - COM method name
        self.queries.append(query)
        kind = "edge" if "Edge" in query else "face"
        scope = self.items[0].Value if (query.endswith(",sel") and self.items) else None
        self.scopes.append(None if scope is None else str(scope.Name))
        self.items = [
            _Selected(reference) for reference in self._part.topology(kind, scope)
        ]


def _part() -> "tuple[Part, _Part, _Selection]":
    raw = _Part()
    raw.add_pad(raw.MainBody, MAIN_PAD, edges=3, faces=2)
    raw.add_pad(raw.tool_body, TOOL_PAD, edges=2, faces=1)
    selection = _Selection(raw)
    return Part(raw, selection=selection), raw, selection


# --- body-scoped topology ---------------------------------------------------------------------


def test_a_part_wide_snapshot_still_returns_every_body_and_says_who_owns_what() -> None:
    """The old behaviour is unchanged; ownership is what is new."""
    part, _, selection = _part()

    edges = part.topology.edges()

    assert len(edges) == 5
    assert selection.queries == [EDGE_SEARCH_QUERY]
    assert [edge.owner_body_name for edge in edges] == ["PartBody"] * 3 + [
        TOOL_BODY
    ] * 2
    assert {edge.owner_feature_name for edge in edges} == {MAIN_PAD, TOOL_PAD}


def test_a_snapshot_scoped_to_a_body_selects_it_and_searches_in_the_selection() -> None:
    part, _, selection = _part()

    edges = part.topology.edges(body=TOOL_BODY)

    assert selection.queries == [EDGE_SEARCH_QUERY_IN_SELECTION]
    assert selection.scopes == [TOOL_BODY]
    assert [edge.owner_body_name for edge in edges] == [TOOL_BODY] * 2


def test_faces_scope_to_a_body_the_same_way() -> None:
    part, raw, selection = _part()

    faces = part.topology.faces(body=part.bodies.get(TOOL_BODY))

    assert selection.queries == [FACE_SEARCH_QUERY_IN_SELECTION]
    assert [face.owner_body_name for face in faces] == [TOOL_BODY]


def test_inside_work_in_a_snapshot_follows_the_work_body() -> None:
    """Sketches and features go into the work body; so does topology."""
    part, _, _ = _part()

    with part.work_in(TOOL_BODY):
        scoped = part.topology.edges()
        part_wide = part.topology.edges(body=None)

    assert [edge.owner_body_name for edge in scoped] == [TOOL_BODY] * 2
    assert len(part_wide) == 5


def test_an_unknown_body_name_is_refused_before_any_search() -> None:
    part, _, selection = _part()

    with pytest.raises(Exception, match="NOPE"):
        part.topology.edges(body="NOPE")
    assert selection.queries == []


# --- ownership validation ---------------------------------------------------------------------


def test_an_edge_from_another_body_is_refused_before_catia_is_called() -> None:
    """The live failure mode: CATIA accepts this and fails the next update instead."""
    part, raw, _ = _part()
    tool_edge = part.topology.edges(body=TOOL_BODY)[0]

    with pytest.raises(CrossBodyReferenceError) as failure:
        part.part_design.create_edge_fillet("F1", tool_edge, 1.0)

    assert TOOL_BODY in str(failure.value) and "PartBody" in str(failure.value)
    assert raw.ShapeFactory.calls == []
    assert raw.MainBody.Shapes.items[-1].Name == MAIN_PAD


def test_an_edge_of_the_target_body_is_accepted() -> None:
    part, raw, _ = _part()
    edge = part.topology.edges(body="PartBody")[0]

    fillet = part.part_design.create_edge_fillet("F1", edge, 1.0)

    assert fillet.name == "F1"
    assert raw.ShapeFactory.calls == [("EdgeFillet", "PartBody")]


def test_inside_work_in_the_work_body_is_what_a_reference_is_checked_against() -> None:
    part, raw, _ = _part()

    with part.work_in(TOOL_BODY):
        tool_edge = part.topology.edges()[0]
        part.part_design.create_edge_fillet("F1", tool_edge, 1.0)

    assert raw.ShapeFactory.calls == [("EdgeFillet", TOOL_BODY)]


def test_a_face_from_another_body_is_refused_too() -> None:
    part, raw, _ = _part()
    tool_face = part.topology.faces(body=TOOL_BODY)[0]

    with pytest.raises(CrossBodyReferenceError):
        part.part_design.create_shell("S1", tool_face, 1.0, 0.0)
    assert raw.ShapeFactory.calls == []


def test_a_reference_whose_owner_catia_did_not_report_is_still_accepted() -> None:
    """Refusing on a missing answer would break calls CATIA would have accepted."""
    part, raw, _ = _part()
    reference = raw.edges[id(raw.MainBody)][0]
    edge = Edge(reference, 1, part.topology.edges().generation)

    part.part_design.create_edge_fillet("F1", edge, 1.0)

    assert raw.ShapeFactory.calls == [("EdgeFillet", "PartBody")]
    assert edge.owner_body is None


def test_a_face_built_by_hand_without_an_owner_is_accepted() -> None:
    part, raw, _ = _part()
    reference = raw.faces[id(raw.MainBody)][0]
    face = Face(reference, 1, part.topology.faces().generation)

    part.part_design.create_shell("S1", face, 1.0, 0.0)

    assert raw.ShapeFactory.calls == [("Shell", "PartBody")]


# --- per-body update --------------------------------------------------------------------------


def test_a_body_reports_whether_catia_has_rebuilt_it() -> None:
    part, raw, _ = _part()
    tool = part.bodies.get(TOOL_BODY)
    raw.up_to_date[id(raw.tool_body)] = False

    assert tool.is_up_to_date is False
    assert part.bodies.main.is_up_to_date is True


def test_body_update_rebuilds_only_that_body() -> None:
    part, raw, _ = _part()
    raw.up_to_date[id(raw.tool_body)] = False
    raw.up_to_date[id(raw.MainBody)] = False

    part.bodies.get(TOOL_BODY).update()

    assert raw.update_object_calls == [TOOL_BODY]
    assert raw.update_calls == []
    assert raw.IsUpToDate(raw.tool_body) is True
    assert raw.IsUpToDate(raw.MainBody) is False


def test_body_update_does_not_move_the_in_work_object() -> None:
    part, raw, _ = _part()
    raw.up_to_date[id(raw.tool_body)] = False

    part.bodies.get(TOOL_BODY).update()

    assert raw.InWorkObject is raw.MainBody


def test_part_update_takes_a_body_and_uses_update_object() -> None:
    part, raw, _ = _part()
    raw.up_to_date[id(raw.tool_body)] = False

    part.update(part.bodies.get(TOOL_BODY))

    assert raw.update_object_calls == [TOOL_BODY]
    assert raw.update_calls == []


def test_part_update_without_a_target_still_rebuilds_everything() -> None:
    part, raw, _ = _part()

    part.update()

    assert raw.update_calls == ["Update"]
    assert raw.update_object_calls == []


def test_an_update_advances_the_generation_so_snapshots_go_stale() -> None:
    part, raw, _ = _part()
    edges = part.topology.edges()
    before = edges.generation

    part.bodies.get(TOOL_BODY).update()

    assert part.topology.edges().generation != before


def test_a_failed_body_update_raises_part_update_error_naming_the_body() -> None:
    part, raw, _ = _part()
    raw.update_failure = _com_error()

    with pytest.raises(PartUpdateError, match=TOOL_BODY):
        part.bodies.get(TOOL_BODY).update()


def test_a_failed_targeted_part_update_raises_part_update_error() -> None:
    part, raw, _ = _part()
    raw.update_failure = _com_error()

    with pytest.raises(PartUpdateError, match="UpdateObject"):
        part.update(part.bodies.get(TOOL_BODY))


# --- measurement preconditions -----------------------------------------------------------------


class _Inertia:
    def GetVolume(self) -> float:  # noqa: N802 - COM method name
        return 1.0

    def GetArea(self) -> float:  # noqa: N802 - COM method name
        return 2.0

    def GetMass(self) -> float:  # noqa: N802 - COM method name
        return 3.0

    def GetCOGPosition(self) -> "tuple[float, float, float]":  # noqa: N802
        return (0.0, 0.0, 0.0)


class _InertiaService:
    def __init__(self) -> None:
        self.calls: "list[Any]" = []

    def GetInertiaElement(self, item: Any) -> Any:  # noqa: N802 - COM method name
        self.calls.append(item)
        return _Inertia()


class _MeasuringEditor:
    def __init__(self, service: Any) -> None:
        self._service = service

    def GetService(self, name: str) -> Any:  # noqa: N802 - COM method name
        assert name == INERTIA_SERVICE_NAME
        return self._service


def test_measuring_a_body_that_was_never_rebuilt_is_refused_clearly() -> None:
    """Live, the inertia service accepted it and then failed with a bare E_FAIL."""
    raw = _Part()
    raw.up_to_date[id(raw.tool_body)] = False
    service = _InertiaService()
    measurement = SolidMeasurement(_MeasuringEditor(service), None, raw.IsUpToDate)

    with pytest.raises(TargetNotUpToDateError, match=TOOL_BODY):
        measurement.measure(raw.tool_body)
    assert service.calls == []
    assert raw.update_calls == [] and raw.update_object_calls == []


def test_measuring_an_up_to_date_body_still_works() -> None:
    raw = _Part()
    service = _InertiaService()
    measurement = SolidMeasurement(_MeasuringEditor(service), None, raw.IsUpToDate)

    properties = measurement.measure(raw.tool_body)

    assert properties.volume_mm3 == pytest.approx(1e9)
    assert service.calls == [raw.tool_body]


def test_a_body_wrapper_is_checked_through_its_com_object() -> None:
    part, raw, _ = _part()
    raw.up_to_date[id(raw.tool_body)] = False
    service = _InertiaService()
    measurement = SolidMeasurement(_MeasuringEditor(service), None, raw.IsUpToDate)

    with pytest.raises(TargetNotUpToDateError):
        measurement.measure(part.bodies.get(TOOL_BODY))


def test_measurement_without_a_status_check_behaves_as_before() -> None:
    raw = _Part()
    raw.up_to_date[id(raw.tool_body)] = False
    service = _InertiaService()
    measurement = SolidMeasurement(_MeasuringEditor(service), None)

    measurement.measure(raw.tool_body)

    assert service.calls == [raw.tool_body]


def test_an_unreadable_status_does_not_block_a_measurement() -> None:
    raw = _Part()
    service = _InertiaService()

    def unreadable(item: Any) -> bool:
        raise ParameterTypeError("cannot tell")

    measurement = SolidMeasurement(_MeasuringEditor(service), None, unreadable)

    measurement.measure(raw.tool_body)

    assert service.calls == [raw.tool_body]


# --- EnumParam ---------------------------------------------------------------------------------


class _EnumParam:
    """Fake `EnumParam`: no `Value`, a `ValueAsString()` method (probe 42)."""

    def __init__(self, name: str, value: str) -> None:
        self.Name = name
        self._value = value

    def ValueAsString(self) -> str:  # noqa: N802 - COM method name
        return self._value


class _LengthParam:
    def __init__(self, name: str, value: float) -> None:
        self.Name = name
        self.Value = value


class _ValuelessParam:
    def __init__(self, name: str) -> None:
        self.Name = name


def test_an_enum_parameter_reports_its_value_as_a_string() -> None:
    parameter = Parameter(_EnumParam("Coincidence.1\\Mode", "CstAttr_Mode_Constrained"))

    assert parameter.value == "CstAttr_Mode_Constrained"
    assert parameter.kind == "_EnumParam"


def test_an_ordinary_parameter_is_unaffected() -> None:
    parameter = Parameter(_LengthParam("Pad\\Length", 30.0))

    assert parameter.value == 30.0


def test_reading_every_parameter_survives_an_enum_among_them() -> None:
    """A Part with one sketch constraint holds these, and listing used to crash."""
    parameters = [
        Parameter(_LengthParam("Pad\\Length", 30.0)),
        Parameter(_EnumParam("Parallelism.1\\Mode", "CstAttr_Mode_Constrained")),
    ]

    assert [parameter.value for parameter in parameters] == [
        30.0,
        "CstAttr_Mode_Constrained",
    ]


def test_a_parameter_with_no_readable_value_says_so() -> None:
    parameter = Parameter(_ValuelessParam("Mystery"))

    with pytest.raises(ParameterTypeError, match="ValueAsString"):
        parameter.value


# --- sketch support prerequisites ---------------------------------------------------------------


class _Plane:
    """Fake user plane wrapper, as `part.planes.create_offset` returns one."""

    def __init__(self, com_object: Any) -> None:
        self.com_object = com_object


def test_a_sketch_on_a_plane_that_was_never_rebuilt_is_refused() -> None:
    part, raw, _ = _part()
    plane_com_object = _Feature("MY_PLANE", None)
    raw.up_to_date[id(plane_com_object)] = False

    with pytest.raises(SupportNotUpdatedError, match="MY_PLANE"):
        part.sketches.create("S", support=_Plane(plane_com_object))
    assert raw.MainBody.Sketches.items == []


def test_the_same_plane_works_once_the_part_has_been_updated() -> None:
    part, raw, _ = _part()
    plane_com_object = _Feature("MY_PLANE", None)
    raw.up_to_date[id(plane_com_object)] = False

    part.update()
    sketch = part.sketches.create("S", support=_Plane(plane_com_object))

    assert sketch.name == "S"
    assert len(raw.MainBody.Sketches.items) == 1


def test_an_origin_plane_support_is_not_second_guessed() -> None:
    part, raw, _ = _part()

    sketch = part.sketches.create("S", support="XY")

    assert sketch.name == "S"
