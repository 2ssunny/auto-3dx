"""Tests for Phase 2: editing existing features, rediscovering elements, work_at, dependencies.

The fakes behave as probe 43 measured the live model (`docs/conventions.md` 1.11):

    ConstRadEdgeFillet.Radius / Chamfer.Length1 / Chamfer.Angle   -> Length/Angle params
    Hole.Diameter and Hole.BottomLimit.Dimension                  -> the hole's dimensions
    Shell.InternalThickness / ExternalThickness, Thickness.Offset -> Length params
    Sketch.GeometricElements.Item(name)                           -> the element by name
    Part.InWorkObject = feature                                   -> insert after it
    Formula.NbInParameters / GetInParameter(i)                    -> the formula's inputs
    Parameters.Remove(name) on a referenced parameter             -> 'deleted_...' orphan
"""

from typing import Any

import pytest
import pywintypes

from auto_3dx.core.part import Part
from auto_3dx.errors import (
    AutomationError,
    FeatureNotFoundError,
    ParameterInUseError,
    ParameterNameError,
    ParameterNotFoundError,
    ParameterTypeError,
    SketchElementNotFoundError,
    UnsupportedUnitError,
)
from auto_3dx.formulas.collection import FormulaCollection
from auto_3dx.geometry.part_design import (
    Chamfer,
    ConstRadEdgeFillet,
    Hole,
    Pad,
    Shell,
    Thickness,
)
from auto_3dx.geometry.sketch import Sketch, SketchElement
from auto_3dx.parameters.collection import ParameterCollection

E_FAIL = -2147467259


def _com_error() -> pywintypes.com_error:
    return pywintypes.com_error(
        -2147352567,
        "Exception occurred.",
        (0, "CATIA", "failed", None, 0, E_FAIL),
        None,
    )


class _Length:
    """Fake CATIA `Length`/`Angle` parameter: a name and a writable `Value`."""

    def __init__(self, name: str, value: float) -> None:
        self.Name = name
        self.Value = value


class _Limit:
    """Fake `Limit`, which is where a hole keeps its depth."""

    def __init__(self, value: float) -> None:
        self.Dimension = _Length("Depth", value)
        self.LimitMode = 0


class _RawFeature:
    """Fake raw feature with whatever dimension members the real one exposes."""

    def __init__(self, name: str, **members: Any) -> None:
        self.Name = name
        for member, value in members.items():
            setattr(self, member, value)


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
                if getattr(item, "Name", None) == key:
                    return item
            raise _com_error()
        return self.items[key - 1]


class _GeometricElements(_Items):
    """Fake `Sketch.GeometricElements`: `Item` takes a name as well as an index."""


class _RawSketch:
    def __init__(self, name: str = "SKETCH") -> None:
        self.Name = name
        self.GeometricElements = _GeometricElements(self)
        self.Constraints = _Items(self)
        self.edition_open = False

    def OpenEdition(self) -> Any:  # noqa: N802 - COM method name
        self.edition_open = True
        return self

    def CloseEdition(self) -> None:  # noqa: N802 - COM method name
        self.edition_open = False


class _Line2D:
    def __init__(self, name: str) -> None:
        self.Name = name


class _Circle2D:
    def __init__(self, name: str, radius: float) -> None:
        self.Name = name
        self.Radius = radius


class _ShapeFactory:
    """Records the In-Work Object at the moment each feature is created."""

    def __init__(self, part: "_Part") -> None:
        self._part = part
        self.in_work_at_creation: "list[Any]" = []

    def AddNewPad(self, sketch: Any, height: float) -> Any:  # noqa: N802 - COM method name
        self.in_work_at_creation.append(self._part.InWorkObject)
        feature = _RawFeature(f"Pad.{len(self._part.MainBody.Shapes.items) + 1}")
        feature.Sketch = sketch
        feature.FirstLimit = _Limit(height)
        self._part.MainBody.Shapes.items.append(feature)
        self._part._in_work = feature
        return feature


class _RawBody:
    def __init__(self, name: str) -> None:
        self.Name = name
        self.Shapes = _Items(self)
        self.Sketches = _Items(self)
        self.HybridBodies = _Items(self)


class _Editor:
    def __init__(self, active_object: Any) -> None:
        self.ActiveObject = active_object


class _Application:
    def __init__(self, editor: Any) -> None:
        self.ActiveEditor = editor


class _Relations(_Items):
    pass


class _RawFormula:
    """Fake `Formula`: `NbInParameters` + `GetInParameter(i)`, as CATIA exposes them."""

    def __init__(self, name: str, inputs: "list[Any]") -> None:
        self.Name = name
        self._inputs = inputs
        self.Value = "body"

    @property
    def NbInParameters(self) -> int:  # noqa: N802 - COM property name
        return len(self._inputs)

    def GetInParameter(self, index: int) -> Any:  # noqa: N802 - COM method name
        if not 1 <= index <= len(self._inputs):
            raise _com_error()
        return self._inputs[index - 1]


class _Parameters(_Items):
    """Fake `Parameters`: `Item` resolves a short name as well as a qualified one."""

    def __init__(self, part: "_Part") -> None:
        super().__init__(part)
        self.removed: "list[str]" = []

    def Item(self, key: Any) -> Any:  # noqa: N802 - COM method name
        if isinstance(key, str):
            for item in self.items:
                if item.Name == key or item.Name.rsplit("\\", 1)[-1] == key:
                    return item
            raise _com_error()
        return self.items[key - 1]

    def Remove(self, name: str) -> None:  # noqa: N802 - COM method name
        self.removed.append(name)
        for item in list(self.items):
            if item.Name == name:
                self.items.remove(item)
                return
        raise _com_error()


class _Part:
    """Fake CATIA `Part` with features, sketches, parameters and relations."""

    def __init__(self) -> None:
        self.Name = "3D Shape1"
        self.MainBody = _RawBody("PartBody")
        self.Bodies = _Items(self)
        self.Bodies.items.append(self.MainBody)
        self.ShapeFactory = _ShapeFactory(self)
        self.Parameters = _Parameters(self)
        self.Relations = _Relations(self)
        self._in_work: Any = self.MainBody
        self.Application = _Application(_Editor(self))
        self.in_work_writes: "list[Any]" = []
        self.in_work_write_error: BaseException | None = None

    @property
    def InWorkObject(self) -> Any:  # noqa: N802 - COM property name
        return self._in_work

    @InWorkObject.setter
    def InWorkObject(self, value: Any) -> None:  # noqa: N802 - COM property name
        if self.in_work_write_error is not None:
            raise self.in_work_write_error
        self.in_work_writes.append(value)
        self._in_work = value

    def IsUpToDate(self, item: Any) -> bool:  # noqa: N802 - COM method name
        return True

    def Update(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("Nothing here may rebuild.")

    def Save(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("Nothing here may save.")


def _part() -> "tuple[Part, _Part]":
    raw = _Part()
    return Part(raw), raw


# --- feature dimension editing ------------------------------------------------------------------


def test_a_fillet_reads_and_writes_its_radius() -> None:
    raw = _RawFeature("F1", Radius=_Length("Radius", 4.0))
    fillet = ConstRadEdgeFillet(raw)

    assert fillet.radius == 4.0
    fillet.set_radius(8.0)

    assert fillet.radius == 8.0
    assert raw.Radius.Value == 8.0


def test_a_setter_never_rebuilds_on_its_own() -> None:
    """`part.update()` stays the one place a rebuild happens."""
    part, rawpart = _part()
    raw = _RawFeature("F1", Radius=_Length("Radius", 4.0))

    ConstRadEdgeFillet(raw, part._generation).set_radius(6.0)

    assert raw.Radius.Value == 6.0  # the fake Part.Update would have raised


def test_a_write_advances_the_generation_so_snapshots_go_stale() -> None:
    part, _ = _part()
    fillet = ConstRadEdgeFillet(_RawFeature("F1", Radius=_Length("Radius", 4.0)), part._generation)
    before = part._generation.value

    fillet.set_radius(5.0)

    assert part._generation.value != before


def test_a_fillet_radius_parameter_is_the_object_a_formula_drives() -> None:
    raw = _RawFeature("F1", Radius=_Length("Radius", 4.0))

    parameter = ConstRadEdgeFillet(raw).radius_parameter()

    assert parameter.com_object is raw.Radius
    assert parameter.value == 4.0


def test_a_chamfer_reads_and_writes_length1_and_angle() -> None:
    raw = _RawFeature(
        "C1",
        Length1=_Length("Length1", 2.0),
        Length2=_Length("Length2", 1.0),
        Angle=_Length("Angle", 45.0),
    )
    chamfer = Chamfer(raw)

    chamfer.set_length1(5.0)
    chamfer.set_angle(30.0)

    assert (chamfer.length1, chamfer.angle) == (5.0, 30.0)
    assert raw.Length2.Value == 1.0, "Length2 is not written: CATIA refused it live"


def test_a_hole_reads_and_writes_diameter_and_depth() -> None:
    """The depth lives in `BottomLimit.Dimension`; a `Hole` has no `Depth` member."""
    raw = _RawFeature("H1", Diameter=_Length("Diameter", 10.0), BottomLimit=_Limit(5.0))
    hole = Hole(raw)

    hole.set_diameter(12.0)
    hole.set_depth(9.0)

    assert (hole.diameter, hole.depth) == (12.0, 9.0)
    assert raw.BottomLimit.Dimension.Value == 9.0


def test_a_shell_reads_and_writes_both_thicknesses() -> None:
    raw = _RawFeature(
        "S1",
        InternalThickness=_Length("InternalThickness", 2.0),
        ExternalThickness=_Length("ExternalThickness", 0.0),
    )
    shell = Shell(raw)

    shell.set_internal_thickness(4.0)
    shell.set_external_thickness(1.5)

    assert (shell.internal_thickness, shell.external_thickness) == (4.0, 1.5)


def test_a_thickness_reads_and_writes_its_offset() -> None:
    raw = _RawFeature("T1", Offset=_Length("Offset", 3.0))
    thickness = Thickness(raw)

    thickness.set_offset(6.0)

    assert thickness.offset == 6.0


def test_a_dimension_the_release_does_not_expose_is_reported_clearly() -> None:
    hole = Hole(_RawFeature("H1", Diameter=_Length("Diameter", 10.0)))

    with pytest.raises(AutomationError, match="BottomLimit"):
        hole.depth


def test_setters_validate_exactly_as_the_existing_ones_do() -> None:
    fillet = ConstRadEdgeFillet(_RawFeature("F1", Radius=_Length("Radius", 4.0)))

    with pytest.raises(ParameterTypeError):
        fillet.set_radius("wide")
    with pytest.raises(UnsupportedUnitError):
        fillet.set_radius(5.0, unit="furlong")
    assert fillet.radius == 4.0


def test_a_rediscovered_wrapper_reads_the_current_value() -> None:
    """Nothing is cached: a second wrapper over the same feature sees the same value."""
    raw = _RawFeature("F1", Radius=_Length("Radius", 4.0))

    ConstRadEdgeFillet(raw).set_radius(7.0)

    assert ConstRadEdgeFillet(raw).radius == 7.0


def test_a_com_failure_while_writing_is_translated() -> None:
    class _Refusing:
        Name = "Radius"

        @property
        def Value(self) -> float:  # noqa: N802 - COM property name
            return 4.0

        @Value.setter
        def Value(self, value: float) -> None:  # noqa: N802 - COM property name
            raise _com_error()

    fillet = ConstRadEdgeFillet(_RawFeature("F1", Radius=_Refusing()))

    with pytest.raises(AutomationError):
        fillet.set_radius(5.0)


# --- sketch element rediscovery ------------------------------------------------------------------


def _sketch_with_elements() -> "tuple[Sketch, _RawSketch]":
    raw = _RawSketch()
    raw.GeometricElements.items.extend(
        [_Line2D("Line.1"), _Line2D("Line.2"), _Circle2D("Circle.1", 5.0)]
    )
    return Sketch(raw), raw


def test_elements_are_listed_from_the_model() -> None:
    sketch, _ = _sketch_with_elements()

    elements = sketch.elements()

    assert [element.name for element in elements] == ["Line.1", "Line.2", "Circle.1"]
    assert [element.kind for element in elements] == ["_Line2D", "_Line2D", "_Circle2D"]


def test_an_element_is_found_again_by_its_catia_name() -> None:
    """The acceptance case: the Python objects that drew it are long gone."""
    sketch, raw = _sketch_with_elements()

    element = sketch.get_element("Line.2")

    assert element.name == "Line.2"
    assert element.com_object is raw.GeometricElements.items[1]


def test_a_rediscovered_element_knows_which_sketch_it_belongs_to() -> None:
    """That is what lets it be passed straight back into a constraint method."""
    sketch, raw = _sketch_with_elements()

    element = sketch.get_element("Line.1")

    assert element.sketch is raw


def test_a_missing_element_name_is_a_not_found_error_listing_what_is_there() -> None:
    sketch, _ = _sketch_with_elements()

    with pytest.raises(SketchElementNotFoundError) as failure:
        sketch.get_element("Line.99")

    assert "Line.1" in str(failure.value)


def test_an_unusable_element_name_is_refused_before_catia() -> None:
    sketch, _ = _sketch_with_elements()

    with pytest.raises(ParameterNameError):
        sketch.get_element("  ")


def test_a_rediscovered_circle_reports_its_radius() -> None:
    sketch, _ = _sketch_with_elements()

    assert sketch.get_element("Circle.1").radius == 5.0


def test_an_element_without_a_radius_says_so_instead_of_guessing() -> None:
    sketch, _ = _sketch_with_elements()

    with pytest.raises(ParameterTypeError, match="radius"):
        sketch.get_element("Line.1").radius


def test_a_rediscovered_element_is_accepted_by_a_constraint_method() -> None:
    sketch, raw = _sketch_with_elements()
    raw.Constraints.AddBiEltCst = lambda kind, first, second: _RawFeature("Parallelism.1")
    first = sketch.get_element("Line.1")
    second = sketch.get_element("Line.2")

    with sketch.edit() as editor:
        constraint = editor.parallel(first, second)

    assert constraint.name == "Parallelism.1"
    assert raw.edition_open is False


def test_the_editor_closes_even_when_the_block_raises() -> None:
    sketch, raw = _sketch_with_elements()

    with pytest.raises(RuntimeError):
        with sketch.edit():
            raise RuntimeError("boom")

    assert raw.edition_open is False


def test_an_element_from_another_sketch_is_still_refused() -> None:
    """A Phase 1 safety rule that rediscovery must not weaken."""
    sketch, _ = _sketch_with_elements()
    other = SketchElement(_Line2D("Line.1"), _RawSketch("OTHER"))

    with pytest.raises(Exception):
        with sketch.edit() as editor:
            editor.horizontal(other)


# --- work_at ------------------------------------------------------------------------------------


def _pad_in(part: Part, raw: _Part, name: str) -> Pad:
    feature = _RawFeature(name, FirstLimit=_Limit(10.0))
    raw.MainBody.Shapes.items.append(feature)
    return Pad(feature, part._generation)


def test_work_at_makes_the_feature_the_in_work_object_and_restores_it() -> None:
    part, raw = _part()
    pad = _pad_in(part, raw, "PAD")
    before = raw.InWorkObject

    with part.work_at(pad) as target:
        assert raw.InWorkObject is pad.com_object
        assert target is pad

    assert raw.InWorkObject is before


def test_work_at_restores_the_in_work_object_when_the_block_raises() -> None:
    part, raw = _part()
    pad = _pad_in(part, raw, "PAD")
    before = raw.InWorkObject

    with pytest.raises(RuntimeError):
        with part.work_at(pad):
            raise RuntimeError("boom")

    assert raw.InWorkObject is before


def test_work_at_restores_whatever_was_there_not_the_main_body() -> None:
    """No silent fallback: the previous object comes back even if it was a feature."""
    part, raw = _part()
    first = _pad_in(part, raw, "PAD1")
    second = _pad_in(part, raw, "PAD2")
    raw._in_work = second.com_object

    with part.work_at(first):
        pass

    assert raw.InWorkObject is second.com_object


def test_a_feature_created_inside_work_at_is_built_at_that_feature() -> None:
    """Live, CATIA inserts the new feature immediately after the In-Work one."""
    part, raw = _part()
    pad = _pad_in(part, raw, "PAD")
    sketch = Sketch(_RawSketch(), part._generation)

    with part.work_at(pad):
        part.part_design.create_pad("PAD2", sketch, 5.0)

    assert raw.ShapeFactory.in_work_at_creation == [pad.com_object]


def test_outside_work_at_nothing_touches_the_in_work_object() -> None:
    part, raw = _part()
    sketch = Sketch(_RawSketch(), part._generation)

    part.part_design.create_pad("PAD", sketch, 5.0)

    assert raw.in_work_writes == []


@pytest.mark.parametrize("target", [object(), "PAD", 3, None])
def test_work_at_refuses_anything_that_is_not_a_feature_wrapper(target: Any) -> None:
    part, raw = _part()

    with pytest.raises(ParameterTypeError):
        with part.work_at(target):
            pass
    assert raw.in_work_writes == []


def test_work_at_refuses_a_feature_of_another_part() -> None:
    part, raw = _part()
    other_raw = _Part()
    foreign = Pad(_RawFeature("FOREIGN", FirstLimit=_Limit(1.0)))
    other_raw.MainBody.Shapes.items.append(foreign.com_object)

    with pytest.raises(FeatureNotFoundError):
        with part.work_at(foreign):
            pass
    assert raw.in_work_writes == []


def test_a_failed_restore_after_a_clean_block_raises() -> None:
    part, raw = _part()
    pad = _pad_in(part, raw, "PAD")

    with pytest.raises(AutomationError):
        with part.work_at(pad):
            raw.in_work_write_error = _com_error()


def test_work_in_and_work_at_nest_with_the_innermost_winning() -> None:
    part, raw = _part()
    body = _RawBody("ToolBody")
    raw.Bodies.items.append(body)
    pad = _pad_in(part, raw, "PAD")
    sketch = Sketch(_RawSketch(), part._generation)

    with part.work_in("ToolBody"):
        with part.work_at(pad):
            part.part_design.create_pad("PAD2", sketch, 5.0)
        assert raw.InWorkObject is body

    assert raw.ShapeFactory.in_work_at_creation == [pad.com_object]
    assert raw.InWorkObject is raw.MainBody


# --- parameter dependencies ----------------------------------------------------------------------


def _with_formula(raw: _Part) -> "tuple[ParameterCollection, Any]":
    parameter = _Length("3D Shape1\\L_box", 12.0)
    raw.Parameters.items.append(parameter)
    raw.Relations.items.append(_RawFormula("DriveL", [parameter]))
    formulas = FormulaCollection(raw)
    parameters = ParameterCollection(raw.Parameters, dependents_of=formulas.reading)
    return parameters, parameter


def test_a_formula_reports_the_parameters_it_reads() -> None:
    raw = _Part()
    _with_formula(raw)
    formula = FormulaCollection(raw).get("DriveL")

    assert formula.inputs() == ["3D Shape1\\L_box"]


def test_the_formulas_reading_a_parameter_are_found_through_the_model() -> None:
    raw = _Part()
    parameters, parameter = _with_formula(raw)

    readers = FormulaCollection(raw).reading(parameter)

    assert [formula.name for formula in readers] == ["DriveL"]


def test_dependents_lists_the_formulas_blocking_a_removal() -> None:
    raw = _Part()
    parameters, _ = _with_formula(raw)

    assert [formula.name for formula in parameters.dependents("L_box")] == ["DriveL"]


def test_removing_a_parameter_a_formula_reads_is_refused() -> None:
    """CATIA would rewrite the formula to 'deleted_L_box' and leave an orphan."""
    raw = _Part()
    parameters, _ = _with_formula(raw)

    with pytest.raises(ParameterInUseError, match="DriveL"):
        parameters.remove("L_box")

    assert raw.Parameters.removed == []
    assert parameters.names() == ["3D Shape1\\L_box"]


def test_a_parameter_nothing_reads_is_removed_normally() -> None:
    raw = _Part()
    parameters, _ = _with_formula(raw)
    spare = _Length("3D Shape1\\SPARE", 1.0)
    raw.Parameters.items.append(spare)

    parameters.remove("SPARE")

    assert raw.Parameters.removed == ["3D Shape1\\SPARE"]


def test_force_removes_a_referenced_parameter_deliberately() -> None:
    raw = _Part()
    parameters, _ = _with_formula(raw)

    parameters.remove("L_box", force=True)

    assert raw.Parameters.removed == ["3D Shape1\\L_box"]


def test_a_missing_parameter_is_still_reported_as_missing() -> None:
    raw = _Part()
    parameters, _ = _with_formula(raw)

    with pytest.raises(ParameterNotFoundError):
        parameters.remove("NOPE")
    with pytest.raises(ParameterNotFoundError):
        parameters.dependents("NOPE")


def test_a_collection_without_a_dependency_source_behaves_as_before() -> None:
    """A standalone ParameterCollection has no Relations to consult."""
    raw = _Part()
    parameter = _Length("3D Shape1\\L_box", 12.0)
    raw.Parameters.items.append(parameter)
    parameters = ParameterCollection(raw.Parameters)

    assert parameters.dependents("L_box") == []
    parameters.remove("L_box")

    assert raw.Parameters.removed == ["3D Shape1\\L_box"]


def test_a_part_wires_its_parameters_to_its_formulas() -> None:
    raw = _Part()
    _with_formula(raw)
    part = Part(raw)

    with pytest.raises(ParameterInUseError):
        part.parameters.remove("L_box")
