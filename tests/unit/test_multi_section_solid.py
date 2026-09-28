"""Tests for the Multi-sections Solid (CATIA Loft) Part Design feature.

Verified live in probe 40 (`docs/conventions.md` section 1.8):

    ShapeFactory.AddNewLoft() -> Loft (default name "Multi-sections Solid.N")
    Loft.HybridShape -> HybridShapeLoft
    HybridShapeLoft.AddSectionToLoft(Part.CreateReferenceFromObject(sketch), 1, None)
    HybridShapeLoft.GetSectionFromLoft(rank) -> (Reference, 1, None), rank 1-based;
        Reference.DisplayName is the section sketch name; the rank past the last
        section fails with E_FAIL, and there is no section-count member
    MainBody.Shapes enumeration lists it as type "Loft"
    deleting it through Selection also deleted its section sketches

The fakes model exactly that. `Part.Update`/`Save` raise, so any accidental rebuild or
save from the feature layer fails the test.
"""

from typing import Any

import pytest
import pywintypes

from auto_3dx._generation import ModelGeneration
from auto_3dx.errors import (
    AmbiguousNameError,
    AutomationError,
    FeatureConflictError,
    FeatureNotFoundError,
    ParameterNameError,
    ParameterTypeError,
    PartialCreationError,
)
from auto_3dx.geometry.part_design import (
    MULTI_SECTION_ORIENTATION_VERIFIED,
    MULTI_SECTION_SOLID_KIND,
    MultiSectionSolid,
    PartDesign,
)
from auto_3dx.geometry.sketch import Sketch
from auto_3dx.inspect import SUPPORTED_FEATURE_KINDS

E_FAIL = -2147467259
DISP_E_EXCEPTION = -2147352567
E_UNEXPECTED = -2147418113
SOLID_NAME = "WING_SOLID_LOFT"


def _com_error(scode: int) -> pywintypes.com_error:
    return pywintypes.com_error(
        DISP_E_EXCEPTION,
        "Exception occurred.",
        (0, "CATIAHybridShapeLoft", "The method failed", None, 0, scode),
        None,
    )


class Reference:
    """Fake CATIA `Reference`; its `DisplayName` names the object it points at."""

    def __init__(self, display_name: str) -> None:
        self.DisplayName = display_name


class HybridShapeLoft:
    """Fake `HybridShapeLoft` recording sections and answering read-back by rank."""

    def __init__(self) -> None:
        self.sections: list[tuple[Any, int, Any]] = []
        self.fail_add_at: int | None = None
        self.read_error_at: "tuple[int, int] | None" = None

    def AddSectionToLoft(self, iCrv: Any, iOri: int, iPoint: Any) -> None:  # noqa: N802, N803
        if self.fail_add_at is not None and len(self.sections) + 1 == self.fail_add_at:
            raise _com_error(E_FAIL)
        self.sections.append((iCrv, iOri, iPoint))

    def GetSectionFromLoft(self, iRank: int) -> "tuple[Any, int, Any]":  # noqa: N802, N803
        if self.read_error_at is not None and iRank == self.read_error_at[0]:
            raise _com_error(self.read_error_at[1])
        if 1 <= iRank <= len(self.sections):
            return self.sections[iRank - 1]
        raise _com_error(E_FAIL)


class Loft:
    """Fake CATIA `Loft`; the class name is the kind CATIA reports."""

    def __init__(self, name: str) -> None:
        self._name = name
        self.HybridShape = HybridShapeLoft()
        self.rename_error: BaseException | None = None

    @property
    def Name(self) -> str:  # noqa: N802 - COM property name
        return self._name

    @Name.setter
    def Name(self, value: str) -> None:  # noqa: N802 - COM property name
        if self.rename_error is not None:
            raise self.rename_error
        self._name = value


class Pad:
    """Fake `Pad`, to prove the scan keeps only `Loft` items."""

    def __init__(self, name: str) -> None:
        self.Name = name


class _Shapes:
    def __init__(self) -> None:
        self.items: list[Any] = []

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self.items)

    def Item(self, index: int) -> Any:  # noqa: N802 - COM method name
        return self.items[index - 1]


class _ShapeFactory:
    def __init__(self, shapes: _Shapes) -> None:
        self._shapes = shapes
        self.loft_calls = 0
        self.next_loft: Loft | None = None

    def AddNewLoft(self) -> Loft:  # noqa: N802 - COM method name
        self.loft_calls += 1
        loft = self.next_loft or Loft(f"Multi-sections Solid.{self.loft_calls}")
        self._shapes.items.append(loft)
        return loft


class _MainBody:
    def __init__(self, shapes: _Shapes) -> None:
        self.Shapes = shapes


class _RawSketch:
    def __init__(self, name: str) -> None:
        self.Name = name


class _Part:
    """Fake CATIA `Part` wired for the Multi-sections Solid path."""

    def __init__(self) -> None:
        self.shapes = _Shapes()
        self.MainBody = _MainBody(self.shapes)
        self.ShapeFactory = _ShapeFactory(self.shapes)
        self.reference_calls: list[Any] = []
        self.reference_error: BaseException | None = None

    def CreateReferenceFromObject(self, obj: Any) -> Reference:  # noqa: N802 - COM method
        if self.reference_error is not None:
            raise self.reference_error
        self.reference_calls.append(obj)
        return Reference(obj.Name)

    def Update(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("The feature layer must never rebuild.")

    def Save(self) -> None:  # noqa: N802 - COM method name
        raise AssertionError("Save() must never be called.")


class _Selection:
    """Fake `Selection` whose `Delete` removes the selected items from the model."""

    def __init__(self, part: _Part) -> None:
        self._part = part
        self.added: list[Any] = []

    def Clear(self) -> None:  # noqa: N802 - COM method name
        self.added = []

    def Add(self, item: Any) -> None:  # noqa: N802 - COM method name
        self.added.append(item)

    def Delete(self) -> None:  # noqa: N802 - COM method name
        for item in self.added:
            self._part.shapes.items.remove(item)


def _design() -> "tuple[PartDesign, _Part, ModelGeneration]":
    part = _Part()
    generation = ModelGeneration()
    return PartDesign(part, _Selection(part), generation), part, generation


def _sketches(*names: str) -> "list[Sketch]":
    return [Sketch(_RawSketch(name)) for name in names]


def test_create_adds_every_section_in_order_with_the_verified_arguments() -> None:
    design, part, generation = _design()
    root, tip = _sketches("ROOT", "TIP")

    solid = design.create_multi_section_solid(SOLID_NAME, sections=[root, tip])

    assert isinstance(solid, MultiSectionSolid)
    assert solid.name == SOLID_NAME
    assert part.ShapeFactory.loft_calls == 1
    loft = part.shapes.items[0]
    assert [(ref.DisplayName, ori, point) for ref, ori, point in loft.HybridShape.sections] == [
        ("ROOT", MULTI_SECTION_ORIENTATION_VERIFIED, None),
        ("TIP", MULTI_SECTION_ORIENTATION_VERIFIED, None),
    ]
    assert part.reference_calls == [root.com_object, tip.com_object]
    assert generation.value == 1


def test_more_than_two_sections_are_accepted_in_order() -> None:
    design, part, _ = _design()

    design.create_multi_section_solid(SOLID_NAME, _sketches("A", "B", "C"))

    sections = part.shapes.items[0].HybridShape.sections
    assert [ref.DisplayName for ref, _, _ in sections] == ["A", "B", "C"]


def test_the_kind_is_the_automation_wrapper_name() -> None:
    assert MULTI_SECTION_SOLID_KIND == "Loft"
    assert MULTI_SECTION_SOLID_KIND in SUPPORTED_FEATURE_KINDS


@pytest.mark.parametrize(
    "sections",
    [
        pytest.param([], id="empty"),
        pytest.param(None, id="none"),
        pytest.param("ROOT", id="string"),
    ],
)
def test_sections_that_are_not_a_sequence_of_two_sketches_are_refused(sections: Any) -> None:
    design, part, generation = _design()

    with pytest.raises(ParameterTypeError):
        design.create_multi_section_solid(SOLID_NAME, sections)

    assert part.ShapeFactory.loft_calls == 0
    assert generation.value == 0


def test_a_single_section_is_refused_before_catia_is_called() -> None:
    design, part, generation = _design()

    with pytest.raises(ParameterTypeError, match="at least 2"):
        design.create_multi_section_solid(SOLID_NAME, _sketches("ONLY"))

    assert part.ShapeFactory.loft_calls == 0
    assert part.reference_calls == []
    assert generation.value == 0


def test_a_section_that_is_not_a_sketch_is_refused() -> None:
    design, part, _ = _design()
    root = _sketches("ROOT")[0]

    with pytest.raises(ParameterTypeError, match="Section 2 must be a Sketch"):
        design.create_multi_section_solid(SOLID_NAME, [root, _RawSketch("RAW")])

    assert part.ShapeFactory.loft_calls == 0


def test_the_same_sketch_twice_is_refused() -> None:
    design, part, _ = _design()
    root = _sketches("ROOT")[0]

    with pytest.raises(ParameterTypeError, match="more than once"):
        design.create_multi_section_solid(SOLID_NAME, [root, root])

    assert part.ShapeFactory.loft_calls == 0


def test_an_unusable_name_is_refused_before_catia_is_called() -> None:
    design, part, generation = _design()

    with pytest.raises(ParameterNameError):
        design.create_multi_section_solid("  ", _sketches("ROOT", "TIP"))

    assert part.ShapeFactory.loft_calls == 0
    assert generation.value == 0


def test_an_existing_name_is_a_conflict_and_creates_nothing() -> None:
    design, part, _ = _design()
    design.create_multi_section_solid(SOLID_NAME, _sketches("ROOT", "TIP"))

    with pytest.raises(FeatureConflictError):
        design.create_multi_section_solid(SOLID_NAME, _sketches("ROOT2", "TIP2"))

    assert part.ShapeFactory.loft_calls == 1


def test_a_failed_section_leaves_a_named_feature_and_says_so() -> None:
    """The feature exists by then, so it must be removable by the requested name."""
    design, part, generation = _design()
    loft = Loft("Multi-sections Solid.1")
    loft.HybridShape.fail_add_at = 2
    part.ShapeFactory.next_loft = loft

    with pytest.raises(PartialCreationError, match=SOLID_NAME):
        design.create_multi_section_solid(SOLID_NAME, _sketches("ROOT", "TIP"))

    assert loft.Name == SOLID_NAME
    assert design.get_multi_section_solid(SOLID_NAME).com_object is loft
    assert generation.value == 1


def test_a_failed_rename_is_reported_with_the_name_it_still_has() -> None:
    design, part, _ = _design()
    loft = Loft("Multi-sections Solid.1")
    loft.rename_error = _com_error(E_FAIL)
    part.ShapeFactory.next_loft = loft

    with pytest.raises(PartialCreationError, match="Multi-sections Solid.1"):
        design.create_multi_section_solid(SOLID_NAME, _sketches("ROOT", "TIP"))

    assert loft.HybridShape.sections == []


def test_a_reference_failure_happens_before_any_feature_exists() -> None:
    design, part, generation = _design()
    part.reference_error = _com_error(E_UNEXPECTED)

    with pytest.raises(AutomationError):
        design.create_multi_section_solid(SOLID_NAME, _sketches("ROOT", "TIP"))

    assert part.ShapeFactory.loft_calls == 0
    assert generation.value == 0


def test_listing_keeps_only_multi_section_solids() -> None:
    design, part, _ = _design()
    part.shapes.items.append(Pad("BASE_PAD"))
    design.create_multi_section_solid(SOLID_NAME, _sketches("ROOT", "TIP"))

    assert [solid.name for solid in design.multi_section_solids] == [SOLID_NAME]


def test_get_finds_one_created_elsewhere_and_refuses_to_guess() -> None:
    """A feature another process created is just an item in MainBody.Shapes."""
    design, part, _ = _design()
    part.shapes.items.append(Loft("FROM_ANOTHER_PROCESS"))

    assert design.get_multi_section_solid("FROM_ANOTHER_PROCESS").name == "FROM_ANOTHER_PROCESS"
    with pytest.raises(FeatureNotFoundError):
        design.get_multi_section_solid("MISSING")

    part.shapes.items.append(Loft("FROM_ANOTHER_PROCESS"))
    with pytest.raises(AmbiguousNameError):
        design.get_multi_section_solid("FROM_ANOTHER_PROCESS")


def test_section_names_are_read_from_the_rediscovered_feature() -> None:
    """A fresh wrapper, not the one that created it, reads the sections back."""
    design, _, _ = _design()
    design.create_multi_section_solid(SOLID_NAME, _sketches("ROOT", "MID", "TIP"))

    rediscovered = PartDesign(design._part_com_object).get_multi_section_solid(SOLID_NAME)

    assert rediscovered.section_names() == ["ROOT", "MID", "TIP"]


def test_a_failure_other_than_the_end_of_the_sections_is_raised_not_truncated() -> None:
    design, part, _ = _design()
    design.create_multi_section_solid(SOLID_NAME, _sketches("ROOT", "TIP"))
    part.shapes.items[0].HybridShape.read_error_at = (2, E_UNEXPECTED)

    with pytest.raises(AutomationError):
        design.get_multi_section_solid(SOLID_NAME).section_names()


def test_a_failure_reading_the_first_section_is_raised() -> None:
    design, part, _ = _design()
    design.create_multi_section_solid(SOLID_NAME, _sketches("ROOT", "TIP"))
    part.shapes.items[0].HybridShape.read_error_at = (1, E_FAIL)

    with pytest.raises(AutomationError):
        design.get_multi_section_solid(SOLID_NAME).section_names()


def test_remove_deletes_the_named_feature_through_the_selection() -> None:
    design, part, generation = _design()
    part.shapes.items.append(Pad("BASE_PAD"))
    design.create_multi_section_solid(SOLID_NAME, _sketches("ROOT", "TIP"))
    before = generation.value

    design.remove_multi_section_solid(SOLID_NAME)

    assert [item.Name for item in part.shapes.items] == ["BASE_PAD"]
    assert design.multi_section_solids == []
    assert generation.value == before + 1


def test_removing_a_missing_feature_is_not_found() -> None:
    design, _, generation = _design()

    with pytest.raises(FeatureNotFoundError):
        design.remove_multi_section_solid(SOLID_NAME)

    assert generation.value == 0


def test_reading_does_not_advance_the_generation() -> None:
    design, part, generation = _design()
    loft = Loft(SOLID_NAME)
    loft.HybridShape.sections = [(Reference("ROOT"), 1, None), (Reference("TIP"), 1, None)]
    part.shapes.items.append(loft)

    design.multi_section_solids
    design.get_multi_section_solid(SOLID_NAME).section_names()

    assert generation.value == 0
