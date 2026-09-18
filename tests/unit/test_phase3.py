"""Tests for Phase 3: circular patterns, booleans, constraint removal, feature activity.

The fakes behave as probe 44 measured the live model (`docs/conventions.md` 1.12):

    AddNewCircPattern(seed, 1, n, 1.0, spacing, 1, 1, PlaneXY, PlaneXY, False, 0.0, True)
    CircPattern.AngularRepartition.InstancesCount / .AngularSpacing   -> editable
    AddNewRemove/Add/Intersect/Assemble(tool_body)                    -> consumes the body
    Constraints.Remove(index)                                         -> by index, not name
    Parameters.Item("<Part>\\<Body>\\<Feature>\\Activity")              -> the BoolParam
"""

from typing import Any

import pytest
import pywintypes

from auto_3dx.core.part import Part
from auto_3dx.errors import (
    AmbiguousNameError,
    AutomationError,
    BooleanOperationError,
    ConstraintNotFoundError,
    CrossBodyReferenceError,
    FeatureNotFoundError,
    ParameterNameError,
    ParameterTypeError,
    StaleSnapshotError,
    UnsupportedSupportError,
)
from auto_3dx.geometry.constraint import Constraint, ConstraintCollection
from auto_3dx.geometry.part_design import (
    BOOLEAN_ASSEMBLE_KIND,
    BOOLEAN_INTERSECT_KIND,
    BOOLEAN_REMOVE_KIND,
    CIRCULAR_PATTERN_KIND,
    BooleanOperation,
    CircularPattern,
    Pad,
)
from auto_3dx.geometry.sketch import Sketch

E_FAIL = -2147467259
SEED, PATTERN = "SEED_POCKET", "BOLT_CIRCLE"
TOOL_BODY = "ToolBody"


def _com_error() -> pywintypes.com_error:
    return pywintypes.com_error(
        -2147352567, "Exception occurred.", (0, "CATIA", "failed", None, 0, E_FAIL), None
    )


class _Value:
    """Fake CATIA parameter: a name and a writable `Value`."""

    def __init__(self, name: str, value: Any) -> None:
        self.Name = name
        self.Value = value


class _Repartition:
    def __init__(self, instances: int, spacing: float) -> None:
        self.InstancesCount = _Value("InstancesCount", instances)
        self.AngularSpacing = _Value("AngularSpacing", spacing)


class _Items:
    def __init__(self, parent: Any = None) -> None:
        self.items: "list[Any]" = []
        self.Parent = parent

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self.items)

    def Item(self, key: Any) -> Any:  # noqa: N802 - COM method name
        if isinstance(key, str):
            for item in self.items:
                if str(getattr(item, "Name", "")) == key:
                    return item
            raise _com_error()
        return self.items[key - 1]


class _Constraints(_Items):
    def __init__(self, sketch: "_RawSketch") -> None:
        super().__init__(sketch)
        self._sketch = sketch
        self.removed: "list[int]" = []
        self.removed_while_open: "list[bool]" = []
        self.BrokenConstraintsCount = 0
        self.UnUpdatedConstraintsCount = 0

    def Remove(self, index: int) -> None:  # noqa: N802 - COM method name
        self.removed.append(index)
        self.removed_while_open.append(self._sketch.edition_open)
        del self.items[index - 1]


class _RawSketch:
    def __init__(self, name: str = "SKETCH") -> None:
        self.Name = name
        self.GeometricElements = _Items(self)
        self.Constraints = _Constraints(self)
        self.edition_open = False
        self.open_calls = 0
        self.close_calls = 0

    def OpenEdition(self) -> Any:  # noqa: N802 - COM method name
        self.open_calls += 1
        self.edition_open = True
        return self

    def CloseEdition(self) -> None:  # noqa: N802 - COM method name
        self.close_calls += 1
        self.edition_open = False


class _RawConstraint:
    def __init__(self, name: str) -> None:
        self.Name = name
        self.Type = 1
        self.Status = 0


class Body:  # noqa: N801 - the SDK matches CATIA's own wrapper type names
    def __init__(self, name: str, part: "_Part") -> None:
        self.Name = name
        self.Shapes = _Items(self)
        self.Sketches = _Items(self)
        self.HybridBodies = _Items(self)
        self.InBooleanOperation = False
        self.Parent = part.Bodies


class _RawFeature:
    def __init__(self, name: str, body: Body, **members: Any) -> None:
        self.Name = name
        self.Parent = body.Shapes
        for member, value in members.items():
            setattr(self, member, value)


class CircPattern(_RawFeature):  # noqa: N801 - CATIA's own type name
    pass


class Remove(_RawFeature):  # noqa: N801 - CATIA's own type name
    pass


class Add(_RawFeature):  # noqa: N801 - CATIA's own type name
    pass


class Intersect(_RawFeature):  # noqa: N801 - CATIA's own type name
    pass


class Assemble(_RawFeature):  # noqa: N801 - CATIA's own type name
    pass


_BOOLEAN_CLASSES = {
    "AddNewRemove": Remove,
    "AddNewAdd": Add,
    "AddNewIntersect": Intersect,
    "AddNewAssemble": Assemble,
}


class _ShapeFactory:
    def __init__(self, part: "_Part") -> None:
        self._part = part
        self.calls: "list[tuple[str, tuple[Any, ...]]]" = []

    def AddNewCircPattern(self, *args: Any) -> Any:  # noqa: N802 - COM method name
        self.calls.append(("AddNewCircPattern", args))
        body = self._part.in_work_body()
        pattern = CircPattern(
            f"CircPattern.{len(body.Shapes.items) + 1}",
            body,
            AngularRepartition=_Repartition(args[2], args[4]),
            RadialRepartition=_Repartition(args[1], 0.0),
            ItemToCopy=args[0],
        )
        body.Shapes.items.append(pattern)
        return pattern

    def _boolean(self, method: str, tool: Any) -> Any:
        self.calls.append((method, (tool,)))
        body = self._part.in_work_body()
        feature = _BOOLEAN_CLASSES[method](
            f"{method[6:]}.1", body, Body=tool
        )
        body.Shapes.items.append(feature)
        tool.InBooleanOperation = True
        # CATIA takes the consumed body out of Part.Bodies.
        if tool in self._part.Bodies.items:
            self._part.Bodies.items.remove(tool)
        return feature

    def AddNewRemove(self, tool: Any) -> Any:  # noqa: N802 - COM method name
        return self._boolean("AddNewRemove", tool)

    def AddNewAdd(self, tool: Any) -> Any:  # noqa: N802 - COM method name
        return self._boolean("AddNewAdd", tool)

    def AddNewIntersect(self, tool: Any) -> Any:  # noqa: N802 - COM method name
        return self._boolean("AddNewIntersect", tool)

    def AddNewAssemble(self, tool: Any) -> Any:  # noqa: N802 - COM method name
        return self._boolean("AddNewAssemble", tool)


class _OriginElements:
    def __init__(self) -> None:
        self.PlaneXY = "PlaneXY"
        self.PlaneYZ = "PlaneYZ"
        self.PlaneZX = "PlaneZX"


class _Editor:
    def __init__(self, active_object: Any) -> None:
        self.ActiveObject = active_object


class _Application:
    def __init__(self, editor: Any) -> None:
        self.ActiveEditor = editor


class _Selected:
    def __init__(self, value: Any) -> None:
        self.Value = value
        self.Reference = value


class _Selection:
    def __init__(self, part: "_Part") -> None:
        self._part = part
        self.items: "list[_Selected]" = []
        self.deleted: "list[str]" = []

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self.items)

    def Item(self, index: int) -> Any:  # noqa: N802 - COM method name
        return self.items[index - 1]

    def Clear(self) -> None:  # noqa: N802 - COM method name
        self.items = []

    def Add(self, value: Any) -> None:  # noqa: N802 - COM method name
        self.items.append(_Selected(value))

    def Search(self, query: str) -> None:  # noqa: N802 - COM method name
        self.items = [_Selected(reference) for reference in self._part.edges]

    def Delete(self) -> None:  # noqa: N802 - COM method name
        for item in self.items:
            self.deleted.append(str(getattr(item.Value, "Name", item.Value)))
            for body in [self._part.MainBody, *self._part.Bodies.items]:
                if item.Value in body.Shapes.items:
                    body.Shapes.items.remove(item.Value)
        self.items = []


class _Parameters(_Items):
    pass


class _Part:
    """Fake CATIA `Part` with bodies, features, an Activity parameter per feature."""

    def __init__(self) -> None:
        self.Name = "3D Shape1"
        self.Bodies = _Items(self)
        self.MainBody = Body("PartBody", self)
        self.Bodies.items.append(self.MainBody)
        self.ShapeFactory = _ShapeFactory(self)
        self.OriginElements = _OriginElements()
        self.Parameters = _Parameters(self)
        self._in_work: Any = self.MainBody
        self.Application = _Application(_Editor(self))
        self.edges: "list[Any]" = []
        self.updates = 0

    def add_body(self, name: str) -> Body:
        body = Body(name, self)
        self.Bodies.items.append(body)
        return body

    def add_feature(self, body: Body, name: str, active: bool = True) -> _RawFeature:
        feature = _RawFeature(name, body)
        body.Shapes.items.append(feature)
        self.Parameters.items.append(
            _Value(f"{self.Name}\\{body.Name}\\{name}\\Activity", active)
        )
        return feature

    def in_work_body(self) -> Body:
        node = self._in_work
        while node is not None and not isinstance(node, Body):
            node = getattr(node, "Parent", None)
            node = node.Parent if hasattr(node, "Parent") and not isinstance(node, Body) else node
            if node is None:
                break
        return node if isinstance(node, Body) else self.MainBody

    @property
    def InWorkObject(self) -> Any:  # noqa: N802 - COM property name
        return self._in_work

    @InWorkObject.setter
    def InWorkObject(self, value: Any) -> None:  # noqa: N802 - COM property name
        self._in_work = value

    def IsUpToDate(self, item: Any) -> bool:  # noqa: N802 - COM method name
        return True

    def Update(self) -> None:  # noqa: N802 - COM method name
        self.updates += 1

    def Save(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("Nothing here may save.")


def _part() -> "tuple[Part, _Part, _Selection]":
    raw = _Part()
    selection = _Selection(raw)
    return Part(raw, selection=selection), raw, selection


def _seed(part: Part, raw: _Part, body: Any = None) -> Pad:
    feature = raw.add_feature(body or raw.MainBody, SEED)
    return Pad(feature, part._generation)


# --- circular pattern ---------------------------------------------------------------------------


def test_a_circular_pattern_uses_the_verified_call_shape() -> None:
    part, raw, _ = _part()
    seed = _seed(part, raw)

    pattern = part.part_design.create_circular_pattern(PATTERN, seed, 6, 60.0)

    method, args = raw.ShapeFactory.calls[-1]
    assert method == "AddNewCircPattern"
    assert args == (seed.com_object, 1, 6, 1.0, 60.0, 1, 1, "PlaneXY", "PlaneXY", False, 0.0, True)
    assert pattern.name == PATTERN


def test_a_circular_pattern_does_not_rebuild_on_its_own() -> None:
    part, raw, _ = _part()

    part.part_design.create_circular_pattern(PATTERN, _seed(part, raw), 6, 60.0)

    assert raw.updates == 0


def test_a_circular_pattern_reads_its_angular_row() -> None:
    part, raw, _ = _part()

    pattern = part.part_design.create_circular_pattern(PATTERN, _seed(part, raw), 6, 60.0)

    assert pattern.angular_instances == 6
    assert pattern.angular_spacing_deg == 60.0
    assert pattern.radial_instances == 1


def test_a_circular_pattern_instance_count_and_spacing_are_editable() -> None:
    part, raw, _ = _part()
    pattern = part.part_design.create_circular_pattern(PATTERN, _seed(part, raw), 6, 60.0)

    pattern.set_angular_instances(8)
    pattern.set_angular_spacing_deg(45.0)

    assert (pattern.angular_instances, pattern.angular_spacing_deg) == (8, 45.0)
    assert raw.updates == 0


@pytest.mark.parametrize("instances", [1, 0, -3, 2.5, True, "six"])
def test_an_unusable_instance_count_is_refused_before_catia(instances: Any) -> None:
    part, raw, _ = _part()

    with pytest.raises(ParameterTypeError):
        part.part_design.create_circular_pattern(PATTERN, _seed(part, raw), instances, 60.0)
    assert raw.ShapeFactory.calls == []


def test_an_unusable_spacing_is_refused_before_catia() -> None:
    part, raw, _ = _part()

    with pytest.raises(ParameterTypeError):
        part.part_design.create_circular_pattern(PATTERN, _seed(part, raw), 6, "wide")
    assert raw.ShapeFactory.calls == []


def test_an_unverified_axis_is_refused() -> None:
    part, raw, _ = _part()

    with pytest.raises(UnsupportedSupportError, match="Z"):
        part.part_design.create_circular_pattern(PATTERN, _seed(part, raw), 6, 60.0, axis="X")
    assert raw.ShapeFactory.calls == []


def test_a_seed_feature_from_another_body_is_refused() -> None:
    part, raw, _ = _part()
    other = raw.add_body(TOOL_BODY)
    seed = _seed(part, raw, other)

    with pytest.raises(CrossBodyReferenceError, match=TOOL_BODY):
        part.part_design.create_circular_pattern(PATTERN, seed, 6, 60.0)
    assert raw.ShapeFactory.calls == []


def test_a_seed_that_is_not_a_feature_is_refused() -> None:
    part, raw, _ = _part()

    with pytest.raises(ParameterTypeError):
        part.part_design.create_circular_pattern(PATTERN, "SEED", 6, 60.0)


def test_circular_patterns_are_listed_found_and_removed_by_name() -> None:
    part, raw, selection = _part()
    part.part_design.create_circular_pattern(PATTERN, _seed(part, raw), 6, 60.0)

    assert [item.name for item in part.part_design.circular_patterns] == [PATTERN]
    assert part.part_design.get_circular_pattern(PATTERN).angular_instances == 6

    part.part_design.remove_circular_pattern(PATTERN)

    assert part.part_design.circular_patterns == []
    assert selection.deleted == [PATTERN]
    with pytest.raises(FeatureNotFoundError):
        part.part_design.get_circular_pattern(PATTERN)


def test_a_rediscovered_pattern_reads_the_current_values() -> None:
    part, raw, _ = _part()
    part.part_design.create_circular_pattern(PATTERN, _seed(part, raw), 6, 60.0)

    part.part_design.get_circular_pattern(PATTERN).set_angular_instances(12)

    assert part.part_design.get_circular_pattern(PATTERN).angular_instances == 12


def test_a_pattern_kind_is_what_catia_reports() -> None:
    assert CIRCULAR_PATTERN_KIND == "CircPattern"


# --- boolean operations -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "factory", "kind"),
    [
        ("create_boolean_remove", "AddNewRemove", BOOLEAN_REMOVE_KIND),
        ("create_boolean_add", "AddNewAdd", "Add"),
        ("create_boolean_intersect", "AddNewIntersect", BOOLEAN_INTERSECT_KIND),
        ("create_boolean_assemble", "AddNewAssemble", BOOLEAN_ASSEMBLE_KIND),
    ],
)
def test_each_boolean_calls_its_verified_factory(method: str, factory: str, kind: str) -> None:
    part, raw, _ = _part()
    tool = raw.add_body(TOOL_BODY)

    operation = getattr(part.part_design, method)("OP", TOOL_BODY)

    assert raw.ShapeFactory.calls[-1] == (factory, (tool,))
    assert operation.name == "OP"
    assert operation.tool_body_name == TOOL_BODY
    assert raw.updates == 0


def test_a_boolean_consumes_the_tool_body() -> None:
    """Live, the tool body leaves part.bodies and lives under the feature instead."""
    part, raw, _ = _part()
    tool = raw.add_body(TOOL_BODY)

    part.part_design.create_boolean_remove("CUT", TOOL_BODY)

    assert TOOL_BODY not in part.bodies.names()
    assert tool.InBooleanOperation is True


def test_a_boolean_accepts_a_body_wrapper_as_well_as_a_name() -> None:
    part, raw, _ = _part()
    raw.add_body(TOOL_BODY)

    part.part_design.create_boolean_remove("CUT", part.bodies.get(TOOL_BODY))

    assert raw.ShapeFactory.calls[-1][0] == "AddNewRemove"


def test_the_body_being_modelled_in_cannot_be_its_own_tool() -> None:
    part, raw, _ = _part()

    with pytest.raises(BooleanOperationError, match="own tool"):
        part.part_design.create_boolean_remove("CUT", "PartBody")
    assert raw.ShapeFactory.calls == []


def test_a_body_of_another_part_is_refused() -> None:
    part, raw, _ = _part()
    other_raw = _Part()
    foreign = other_raw.add_body("Foreign")
    other = Part(other_raw)

    with pytest.raises(BooleanOperationError):
        part.part_design.create_boolean_remove("CUT", other.bodies.get("Foreign"))
    assert raw.ShapeFactory.calls == []
    assert foreign.InBooleanOperation is False


def test_a_body_already_consumed_is_refused() -> None:
    part, raw, _ = _part()
    tool = raw.add_body(TOOL_BODY)
    tool.InBooleanOperation = True

    with pytest.raises(BooleanOperationError, match="already been consumed"):
        part.part_design.create_boolean_remove("CUT", TOOL_BODY)
    assert raw.ShapeFactory.calls == []


def test_a_missing_tool_body_name_is_refused_with_the_names_that_exist() -> None:
    part, raw, _ = _part()

    with pytest.raises(BooleanOperationError, match="PartBody"):
        part.part_design.create_boolean_remove("CUT", "NoSuchBody")


def test_a_tool_that_is_neither_a_body_nor_a_name_is_refused() -> None:
    part, raw, _ = _part()

    with pytest.raises(ParameterTypeError):
        part.part_design.create_boolean_remove("CUT", 42)


def test_booleans_are_listed_and_found_by_name_whatever_their_kind() -> None:
    part, raw, _ = _part()
    raw.add_body("ToolA")
    raw.add_body("ToolB")

    part.part_design.create_boolean_remove("CUT", "ToolA")
    part.part_design.create_boolean_add("JOIN", "ToolB")

    assert sorted(item.name for item in part.part_design.boolean_operations) == ["CUT", "JOIN"]
    assert part.part_design.get_boolean("CUT").operation == "Remove"
    with pytest.raises(FeatureNotFoundError):
        part.part_design.get_boolean("NOPE")


def test_removing_a_boolean_requires_acknowledging_the_consumed_body() -> None:
    part, raw, selection = _part()
    raw.add_body(TOOL_BODY)
    part.part_design.create_boolean_remove("CUT", TOOL_BODY)

    with pytest.raises(BooleanOperationError, match=TOOL_BODY):
        part.part_design.remove_boolean("CUT")

    assert selection.deleted == []
    assert [item.name for item in part.part_design.boolean_operations] == ["CUT"]


def test_removing_a_boolean_with_acknowledgement_deletes_it() -> None:
    part, raw, selection = _part()
    raw.add_body(TOOL_BODY)
    part.part_design.create_boolean_remove("CUT", TOOL_BODY)

    part.part_design.remove_boolean("CUT", delete_consumed_body=True)

    assert selection.deleted == ["CUT"]
    assert part.part_design.boolean_operations == []


def test_a_boolean_name_must_be_usable() -> None:
    part, raw, _ = _part()
    raw.add_body(TOOL_BODY)

    with pytest.raises(ParameterNameError):
        part.part_design.create_boolean_remove("  ", TOOL_BODY)


def test_a_boolean_wrapper_repr_names_its_tool_body() -> None:
    part, raw, _ = _part()
    raw.add_body(TOOL_BODY)
    operation = part.part_design.create_boolean_remove("CUT", TOOL_BODY)

    assert TOOL_BODY in repr(operation)
    assert isinstance(operation, BooleanOperation)


# --- constraint removal -------------------------------------------------------------------------


def _sketch_with_constraints() -> "tuple[Sketch, _RawSketch]":
    raw = _RawSketch()
    raw.Constraints.items.extend(
        [_RawConstraint("Parallelism.1"), _RawConstraint("Parallelism.2"), _RawConstraint("Length.5")]
    )
    return Sketch(raw), raw


def test_a_constraint_is_removed_by_name_inside_an_edition() -> None:
    sketch, raw = _sketch_with_constraints()

    sketch.constraints.remove("Parallelism.2")

    assert raw.Constraints.removed == [2]
    assert raw.Constraints.removed_while_open == [True], "the removal must run inside an edition"
    assert raw.open_calls == 1 and raw.close_calls == 1
    assert raw.edition_open is False
    assert sketch.constraints.names() == ["Parallelism.1", "Length.5"]


def test_a_constraint_is_removed_by_object() -> None:
    sketch, raw = _sketch_with_constraints()
    constraint = sketch.constraints.list()[2]

    sketch.constraints.remove(constraint)

    assert raw.Constraints.removed == [3]
    assert sketch.constraints.names() == ["Parallelism.1", "Parallelism.2"]


def test_removing_inside_an_open_edit_block_reuses_that_session() -> None:
    """Nested OpenEdition is unverified, so the open session is reused instead."""
    sketch, raw = _sketch_with_constraints()

    with sketch.edit():
        sketch.constraints.remove("Parallelism.1")
        assert raw.edition_open is True

    assert raw.open_calls == 1, "no second edition was opened"
    assert raw.close_calls == 1
    assert raw.Constraints.removed_while_open == [True]


def test_a_missing_constraint_name_is_reported_with_what_is_there() -> None:
    sketch, raw = _sketch_with_constraints()

    with pytest.raises(ConstraintNotFoundError, match="Parallelism.1"):
        sketch.constraints.remove("Length.99")
    assert raw.Constraints.removed == []
    assert raw.open_calls == 0, "nothing was opened for a request that was refused"


def test_a_duplicate_constraint_name_is_not_guessed() -> None:
    sketch, raw = _sketch_with_constraints()
    raw.Constraints.items.append(_RawConstraint("Parallelism.1"))

    with pytest.raises(AmbiguousNameError):
        sketch.constraints.remove("Parallelism.1")
    assert raw.Constraints.removed == []


def test_a_constraint_already_gone_is_reported() -> None:
    sketch, raw = _sketch_with_constraints()
    constraint = sketch.constraints.list()[0]
    sketch.constraints.remove(constraint)

    with pytest.raises(ConstraintNotFoundError):
        sketch.constraints.remove(constraint)


def test_removing_something_that_is_not_a_constraint_is_refused() -> None:
    sketch, raw = _sketch_with_constraints()

    with pytest.raises(ParameterTypeError):
        sketch.constraints.remove(42)
    assert raw.open_calls == 0


def test_a_failed_removal_still_closes_the_edition() -> None:
    sketch, raw = _sketch_with_constraints()

    def refuse(index: int) -> None:
        raise _com_error()

    raw.Constraints.Remove = refuse

    with pytest.raises(AutomationError):
        sketch.constraints.remove("Parallelism.1")

    assert raw.close_calls == 1
    assert raw.edition_open is False


def test_removing_a_constraint_advances_the_generation() -> None:
    part, raw, _ = _part()
    sketch = Sketch(_RawSketch(), part._generation)
    sketch.com_object.Constraints.items.append(_RawConstraint("Parallelism.1"))
    before = part._generation.value

    sketch.constraints.remove("Parallelism.1")

    assert part._generation.value != before


def test_a_standalone_collection_opens_its_own_edition() -> None:
    raw = _RawSketch()
    raw.Constraints.items.append(_RawConstraint("Parallelism.1"))
    collection = ConstraintCollection(raw)

    collection.remove("Parallelism.1")

    assert raw.open_calls == 1 and raw.close_calls == 1
    assert isinstance(collection.list(), list)


def test_constraint_wrappers_still_read_their_names() -> None:
    sketch, _ = _sketch_with_constraints()

    assert isinstance(sketch.constraints.list()[0], Constraint)
    assert sketch.constraints.count == 3


# --- feature activity ---------------------------------------------------------------------------


def test_a_feature_reports_whether_it_is_active() -> None:
    part, raw, _ = _part()
    pad = Pad(raw.add_feature(raw.MainBody, "PAD"), part._generation)

    assert pad.is_active is True


def test_deactivating_writes_the_activity_parameter_without_rebuilding() -> None:
    part, raw, _ = _part()
    pad = Pad(raw.add_feature(raw.MainBody, "PAD"), part._generation)

    pad.deactivate()

    assert pad.is_active is False
    assert raw.Parameters.items[0].Value is False
    assert raw.updates == 0


def test_activating_puts_a_suppressed_feature_back() -> None:
    part, raw, _ = _part()
    pad = Pad(raw.add_feature(raw.MainBody, "PAD", active=False), part._generation)

    pad.activate()

    assert pad.is_active is True


def test_suppression_makes_older_topology_snapshots_stale() -> None:
    """Suppression can change the whole solid, so held snapshots must not be reused."""
    part, raw, _ = _part()
    raw.edges = ["edge-1", "edge-2"]
    pad = Pad(raw.add_feature(raw.MainBody, "PAD"), part._generation)
    snapshot = part.topology.edges()

    pad.deactivate()

    with pytest.raises(StaleSnapshotError):
        part.part_design.create_edge_fillet("F1", snapshot[0], 1.0)


def test_activity_is_found_for_a_feature_in_another_body() -> None:
    part, raw, _ = _part()
    body = raw.add_body("ToolBody")
    pad = Pad(raw.add_feature(body, "TOOL_PAD"), part._generation)

    pad.deactivate()

    assert pad.is_active is False


def test_activity_is_found_by_scanning_when_the_path_does_not_resolve() -> None:
    """A differently shaped parameter path still resolves through the suffix scan."""
    part, raw, _ = _part()
    feature = raw.add_feature(raw.MainBody, "PAD")
    raw.Parameters.items[0].Name = "Weird\\Container\\PAD\\Activity"
    pad = Pad(feature, part._generation)

    pad.deactivate()

    assert raw.Parameters.items[0].Value is False


def test_a_feature_without_an_activity_parameter_says_so() -> None:
    part, raw, _ = _part()
    feature = _RawFeature("LOOSE", raw.MainBody)
    raw.MainBody.Shapes.items.append(feature)

    with pytest.raises(AutomationError, match="Activity"):
        Pad(feature, part._generation).is_active


def test_every_feature_family_carries_the_activity_controls() -> None:
    """Pad/Pocket, Shaft/Groove and the plain named features share one implementation."""
    part, raw, _ = _part()
    pattern = part.part_design.create_circular_pattern(
        PATTERN, _seed(part, raw), 6, 60.0
    )
    raw.Parameters.items.append(
        _Value(f"{raw.Name}\\PartBody\\{PATTERN}\\Activity", True)
    )

    pattern.deactivate()

    assert pattern.is_active is False
    assert isinstance(pattern, CircularPattern)
