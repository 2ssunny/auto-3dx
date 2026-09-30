"""v1: targeted inspection of one feature or sketch, collection protocols, `describe()`,
and full-circle circular patterns.

Everything here is composed of reads and writes that are already live-verified, so the
fakes only reproduce those members: `FirstLimit.Dimension.Value`, `DirectionOrientation`,
`Diameter`/`BottomLimit`/`BottomType`/`GetOrigin`/`GetDirection` of a hole,
`AngularRepartition` of a pattern, `Part.IsUpToDate`, and the sketch reads of Phase 5.
"""

from typing import Any

import pytest

from auto_3dx.core.part import Part
from auto_3dx.errors import (
    AmbiguousNameError,
    FeatureNotFoundError,
    ParameterTypeError,
    SketchNotFoundError,
)
from auto_3dx.geometry.edges import Edge
from auto_3dx.geometry.faces import Face
from auto_3dx.geometry.part_design import CircularPattern
from auto_3dx.highlevel import pattern_spacing
from auto_3dx.inspect import FeatureDetails
from tests.conftest import make_com_error
from tests.unit.test_phase4 import X, Y, _circle, _line, _measurer, _plane_face


class _Value:
    def __init__(self, value: Any) -> None:
        self.Value = value


class _Items:
    def __init__(self, items: "list[Any]") -> None:
        self.items = items

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self.items)

    def Item(self, key: Any) -> Any:  # noqa: N802 - COM method name
        if isinstance(key, str):
            return next(item for item in self.items if item.Name == key)
        return self.items[key - 1]


class Pad:  # noqa: N801 - the SDK identifies features by CATIA's type name
    def __init__(self, name: str, depth: float) -> None:
        self.Name = name
        self.FirstLimit = type("Limit", (), {"Dimension": _Value(depth)})()
        self.DirectionOrientation = 0


class _BottomLimit:
    def __init__(self) -> None:
        self.LimitMode = 2
        self.Dimension = _Value(20.0)


class Hole:  # noqa: N801
    def __init__(self, name: str) -> None:
        self.Name = name
        self.Diameter = _Value(6.0)
        self.BottomLimit = _BottomLimit()
        self.BottomType = 0
        self.Type = 0

    def GetOrigin(self, seed: Any) -> Any:  # noqa: N802
        return (10.0, 5.0, 20.0)

    def GetDirection(self, seed: Any) -> Any:  # noqa: N802
        return (0.0, 0.0, -1.0)


class Mystery:  # noqa: N801 - a kind the SDK does not wrap
    def __init__(self, name: str) -> None:
        self.Name = name


class _RawSketch:
    def __init__(self, name: str) -> None:
        self.Name = name
        self.GeometricElements = _Items([])
        self.Constraints = _Items([])

    def GetAbsoluteAxisData(self, seed: Any) -> Any:  # noqa: N802
        return (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)


class Body:  # noqa: N801
    def __init__(self, name: str, shapes: "list[Any]", sketches: "list[Any]") -> None:
        self.Name = name
        self.Shapes = _Items(shapes)
        self.Sketches = _Items(sketches)


class _RawPart:
    def __init__(self, bodies: "list[Body]") -> None:
        self.Name = "3D Shape1"
        self.Bodies = _Items(bodies)
        self.MainBody = bodies[0]
        self.up_to_date_calls: "list[Any]" = []

    def IsUpToDate(self, item: Any) -> bool:  # noqa: N802
        self.up_to_date_calls.append(item)
        return True


def _part() -> "tuple[Part, _RawPart]":
    raw = _RawPart(
        [
            Body(
                "PartBody",
                [Pad("Base", 20.0), Hole("Bore"), Mystery("UI.1")],
                [_RawSketch("PROFILE")],
            ),
            Body("Tool", [Pad("Twin", 5.0), Pad("Base", 7.0)], [_RawSketch("PROFILE")]),
        ]
    )
    return Part(raw), raw


# --- inspect.feature / inspect.sketch -----------------------------------------------------------


def test_one_feature_is_read_with_its_verified_dimensions() -> None:
    part, raw = _part()

    details = part.inspect.feature("Bore")

    assert isinstance(details, FeatureDetails)
    assert (details.name, details.kind, details.body_name, details.up_to_date) == (
        "Bore",
        "Hole",
        "PartBody",
        True,
    )
    assert dict(details.parameters) == {
        "diameter": 6.0,
        "depth": 20.0,
        "limit": "through_all",
        "bottom": "flat",
        "hole_type": "simple",
        "head": None,
        "origin": (10.0, 5.0, 20.0),
        "direction": (0.0, 0.0, -1.0),
    }
    assert details.active is None  # the fake has no Activity parameter: unknown, not guessed
    assert len(raw.up_to_date_calls) == 1


def test_a_feature_name_in_two_bodies_needs_the_body() -> None:
    part, _ = _part()

    with pytest.raises(AmbiguousNameError, match="body="):
        part.inspect.feature("Base")
    assert part.inspect.feature("Base", body="Tool").parameters["length"] == 7.0
    assert part.inspect.feature("Base", body="PartBody").parameters["length"] == 20.0


def test_an_unwrapped_kind_is_reported_without_parameters_and_a_missing_one_raises() -> None:
    part, _ = _part()

    mystery = part.inspect.feature("UI.1")

    assert (mystery.kind, dict(mystery.parameters)) == ("Mystery", {})
    with pytest.raises(FeatureNotFoundError, match="Nope"):
        part.inspect.feature("Nope")


def test_one_sketch_is_read_as_plain_values_from_any_body() -> None:
    part, _ = _part()

    with pytest.raises(AmbiguousNameError):
        part.inspect.sketch("PROFILE")
    geometry = part.inspect.sketch("PROFILE", body="Tool")
    assert geometry.name == "PROFILE"
    assert geometry.frame.origin == (0.0, 0.0, 0.0)
    with pytest.raises(SketchNotFoundError):
        part.inspect.sketch("GONE")


def test_targeted_inspection_does_not_mutate() -> None:
    part, _ = _part()
    before = part._generation.value

    part.inspect.feature("Bore")
    part.inspect.sketch("PROFILE", body="PartBody")

    assert part._generation.value == before


# --- collection protocols ------------------------------------------------------------------------


def test_bodies_support_len_iteration_and_membership() -> None:
    part, _ = _part()

    assert len(part.bodies) == 2
    assert [body.name for body in part.bodies] == ["PartBody", "Tool"]
    assert "Tool" in part.bodies
    assert "Nope" not in part.bodies
    assert 3 not in part.bodies


# --- describe() ------------------------------------------------------------------------------


def test_a_face_and_an_edge_describe_their_measured_facts() -> None:
    face = Face(
        _plane_face(2400.0, (0, 0, 20), X, Y),
        1,
        0,
        owner_body_name="PartBody",
        owner_feature_name="Base",
        measurer=_measurer(),
    )
    line = Edge(_line((-30, 20, 20), (30, 20, 20)), 1, 0, measurer=_measurer())
    rim = Edge(_circle((10, 5, 20), 3.0), 2, 0, measurer=_measurer())

    assert face.describe() == (
        "planar face, area 2400.000 mm2, centre (0.000, 0.000, 20.000), "
        "normal axis (0.000, 0.000, 1.000), owner 'Base' in body 'PartBody'"
    )
    assert line.describe() == (
        "line edge, length 60.000 mm, from (-30.000, 20.000, 20.000) to (30.000, 20.000, 20.000)"
    )
    assert "radius 3.000 mm, centre (10.000, 5.000, 20.000)" in rim.describe()


# --- full-circle circular patterns ------------------------------------------------------------


class _Repartition:
    def __init__(self, instances: int, spacing: float) -> None:
        self.InstancesCount = _Value(instances)
        self.AngularSpacing = _Value(spacing)


class _RawPattern:
    def __init__(self, instances: int, spacing: float) -> None:
        self.Name = "P"
        self.AngularRepartition = _Repartition(instances, spacing)


def test_a_full_circle_is_read_and_kept_when_the_count_changes() -> None:
    pattern = CircularPattern(_RawPattern(6, 60.0))
    assert pattern.full_circle

    pattern.set_full_circle(8)

    assert (pattern.instances, pattern.spacing_deg, pattern.full_circle) == (8, 45.0, True)
    pattern.instances = 4  # the plain setter keeps the spacing: no longer a full circle
    assert not pattern.full_circle
    pattern.set_full_circle()
    assert pattern.spacing_deg == 90.0
    with pytest.raises(ParameterTypeError):
        pattern.set_full_circle(1)


def test_full_circle_is_one_of_three_mutually_exclusive_spacing_intents() -> None:
    assert pattern_spacing(6, None, None, full_circle=True) == pytest.approx(60.0)
    with pytest.raises(ParameterTypeError, match="full_circle"):
        pattern_spacing(6, 30.0, None, full_circle=True)
    with pytest.raises(ParameterTypeError):
        pattern_spacing(6, None, None, full_circle=1)


def test_a_com_failure_while_reading_a_feature_is_an_automation_error() -> None:
    from auto_3dx.errors import AutomationError

    class Pad:  # noqa: N801
        Name = "Broken"

        @property
        def FirstLimit(self) -> Any:  # noqa: N802
            raise make_com_error()

    raw = _RawPart([Body("PartBody", [Pad()], [])])

    with pytest.raises(AutomationError):
        Part(raw).inspect.feature("Broken")
