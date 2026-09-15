"""Unit tests for verified rectangular-pattern creation without CATIA.

These fakes are intentionally self-contained: they pin the exact COM call and
the plane-reference/sign mapping without relying on ``tests.conftest``.
"""

from typing import Any

import pytest

from auto_3dx.errors import FeatureConflictError, ParameterTypeError
from auto_3dx.geometry.part_design import (
    PATTERN_DIRECTION_NEGATIVE_X,
    PATTERN_DIRECTION_NEGATIVE_Y,
    PATTERN_DIRECTION_NEGATIVE_Z,
    PATTERN_DIRECTION_X,
    PATTERN_DIRECTION_Y,
    PATTERN_DIRECTION_Z,
    Pad,
    PartDesign,
    RectangularPattern,
)


class _Plane:
    """Minimal origin-plane fake, identified by object identity."""


class _OriginElements:
    """Fake origin elements with the three verified plane properties."""

    def __init__(self) -> None:
        """Initializes distinct fake origin planes."""
        self.PlaneXY = _Plane()
        self.PlaneYZ = _Plane()
        self.PlaneZX = _Plane()


class _Reference:
    """Fake reference recording its source origin plane."""

    def __init__(self, plane: _Plane) -> None:
        """Stores the plane used to create this reference."""
        self.plane = plane


class _Pad:
    """Fake CATIA Pad source object."""


class RectPattern:
    """Fake CATIA pattern; its class name is the documented COM kind."""


class _Selection:
    """Fake editor selection recording the verified deletion sequence."""

    def __init__(self) -> None:
        """Initializes an empty action log."""
        self.actions: list[Any] = []

    def Clear(self) -> None:
        """Records a clear."""
        self.actions.append("Clear")

    def Add(self, item: Any) -> None:
        """Records the selected item."""
        self.actions.append(("Add", item))

    def Delete(self) -> None:
        """Records a delete."""
        self.actions.append("Delete")


class _ShapeFactory:
    """Fake factory recording the exact `AddNewRectPattern` call."""

    def __init__(self) -> None:
        """Initializes an empty call log."""
        self.calls: list[tuple[Any, ...]] = []

    def AddNewRectPattern(self, *args: Any) -> RectPattern:
        """Records the exact verified 12-argument invocation."""
        self.calls.append(args)
        return RectPattern()


class _Part:
    """Fake Part exposing only the members rectangular patterns require."""

    def __init__(self) -> None:
        """Initializes plane, reference, factory, and forbidden-action logs."""
        self.OriginElements = _OriginElements()
        self.ShapeFactory = _ShapeFactory()
        self.reference_calls: list[_Plane] = []
        self.update_calls = 0
        self.save_calls = 0

    def CreateReferenceFromObject(self, plane: _Plane) -> _Reference:
        """Creates a fake reference and records the supplied origin plane."""
        self.reference_calls.append(plane)
        return _Reference(plane)

    def Update(self) -> None:
        """Records an update so tests can prove the wrapper did not call it."""
        self.update_calls += 1

    def Save(self) -> None:
        """Records a save so tests can prove the wrapper did not call it."""
        self.save_calls += 1


def _pad() -> Pad:
    """Returns the public wrapper around a fake source pad."""
    return Pad(_Pad())


@pytest.mark.parametrize(
    ("direction_1", "direction_2", "plane_1", "reverse_1", "plane_2", "reverse_2"),
    [
        (PATTERN_DIRECTION_NEGATIVE_X, PATTERN_DIRECTION_NEGATIVE_Y, "XY", False, "XY", False),
        (PATTERN_DIRECTION_NEGATIVE_Y, PATTERN_DIRECTION_NEGATIVE_Z, "YZ", False, "YZ", False),
        (PATTERN_DIRECTION_NEGATIVE_Z, PATTERN_DIRECTION_NEGATIVE_X, "ZX", False, "ZX", False),
        (PATTERN_DIRECTION_X, PATTERN_DIRECTION_Y, "XY", True, "XY", True),
        (PATTERN_DIRECTION_Y, PATTERN_DIRECTION_Z, "YZ", True, "YZ", True),
        (PATTERN_DIRECTION_Z, PATTERN_DIRECTION_X, "ZX", True, "ZX", True),
    ],
)
def test_create_rectangular_pattern_maps_signed_axes_to_verified_references(
    direction_1: str,
    direction_2: str,
    plane_1: str,
    reverse_1: bool,
    plane_2: str,
    reverse_2: bool,
) -> None:
    """Each direction slot uses its independently verified plane mapping."""
    part = _Part()

    pattern = PartDesign(part).create_rectangular_pattern(
        _pad(), 2, 3, 60.0, 100.0, direction_1, direction_2
    )

    assert isinstance(pattern, RectangularPattern)
    assert part.reference_calls == [
        getattr(part.OriginElements, f"Plane{plane_1}"),
        getattr(part.OriginElements, f"Plane{plane_2}"),
    ]
    call = part.ShapeFactory.calls[0]
    assert isinstance(call[7], _Reference)
    assert isinstance(call[8], _Reference)
    assert call[9:11] == (reverse_1, reverse_2)


def test_create_rectangular_pattern_passes_the_recorded_com_signature() -> None:
    """The call includes fixed verified position and rotation arguments."""
    part = _Part()
    source = _pad()

    PartDesign(part).create_rectangular_pattern(
        source,
        2,
        1,
        60,
        60.0,
        PATTERN_DIRECTION_NEGATIVE_X,
        PATTERN_DIRECTION_NEGATIVE_Y,
    )

    call = part.ShapeFactory.calls[0]
    assert call[:7] == (source.com_object, 2, 1, 60.0, 60.0, 1, 1)
    assert isinstance(call[7], _Reference)
    assert isinstance(call[8], _Reference)
    assert call[9:] == (False, False, 0.0)


@pytest.mark.parametrize(
    ("direction_1", "direction_2"),
    [
        (PATTERN_DIRECTION_X, PATTERN_DIRECTION_X),
        (PATTERN_DIRECTION_X, PATTERN_DIRECTION_NEGATIVE_X),
        (PATTERN_DIRECTION_Y, PATTERN_DIRECTION_NEGATIVE_Y),
        (PATTERN_DIRECTION_NEGATIVE_Z, PATTERN_DIRECTION_Z),
    ],
)
def test_create_rectangular_pattern_rejects_collinear_axes_before_com(
    direction_1: str, direction_2: str
) -> None:
    """CATIA must not be allowed to create a broken same-axis pattern."""
    part = _Part()

    with pytest.raises(FeatureConflictError):
        PartDesign(part).create_rectangular_pattern(
            _pad(), 2, 2, 60.0, 60.0, direction_1, direction_2
        )

    assert part.reference_calls == []
    assert part.ShapeFactory.calls == []


def test_create_rectangular_pattern_rejects_unknown_direction_before_com() -> None:
    """Only the six verified signed global axes are accepted."""
    part = _Part()

    with pytest.raises(ParameterTypeError):
        PartDesign(part).create_rectangular_pattern(
            _pad(), 2, 2, 60.0, 60.0, "NORTH", PATTERN_DIRECTION_Y
        )

    assert part.reference_calls == []
    assert part.ShapeFactory.calls == []


@pytest.mark.parametrize("direction", [[], {}, set()])
def test_create_rectangular_pattern_rejects_unhashable_direction_before_com(
    direction: Any,
) -> None:
    """Container inputs are mapped to the public validation error."""
    part = _Part()

    with pytest.raises(ParameterTypeError):
        PartDesign(part).create_rectangular_pattern(
            _pad(), 2, 2, 60.0, 60.0, direction, PATTERN_DIRECTION_Y
        )

    assert part.reference_calls == []
    assert part.ShapeFactory.calls == []


@pytest.mark.parametrize(
    "spacing",
    [0, 0.0, -1, -0.5, True, "60", float("nan"), float("inf"), float("-inf")],
)
def test_create_rectangular_pattern_rejects_non_positive_spacing_before_com(
    spacing: Any,
) -> None:
    """A step that cannot produce a valid pattern must not create references."""
    part = _Part()

    with pytest.raises(ParameterTypeError):
        PartDesign(part).create_rectangular_pattern(
            _pad(),
            2,
            1,
            spacing,
            60.0,
            PATTERN_DIRECTION_NEGATIVE_X,
            PATTERN_DIRECTION_NEGATIVE_Y,
        )

    assert part.reference_calls == []
    assert part.ShapeFactory.calls == []


def test_create_rectangular_pattern_rejects_non_pad_source_before_com() -> None:
    """Only the live-verified Pad source family is accepted."""
    part = _Part()

    class PocketLike:
        """Object that must not pass merely because it exposes com_object."""

        com_object = object()

    with pytest.raises(ParameterTypeError):
        PartDesign(part).create_rectangular_pattern(
            PocketLike(),
            2,
            2,
            60.0,
            60.0,
            PATTERN_DIRECTION_X,
            PATTERN_DIRECTION_Y,
        )

    assert part.reference_calls == []
    assert part.ShapeFactory.calls == []


def test_create_rectangular_pattern_uses_signed_direction_without_a_second_flip() -> None:
    """The sign in each public axis is the only source of the CATIA reverse flag."""
    part = _Part()

    PartDesign(part).create_rectangular_pattern(
        _pad(),
        2,
        1,
        60.0,
        60.0,
        PATTERN_DIRECTION_X,
        PATTERN_DIRECTION_NEGATIVE_Y,
    )

    assert part.ShapeFactory.calls[0][9:11] == (True, False)


def test_create_rectangular_pattern_never_updates_or_saves() -> None:
    """Pattern creation is deliberately non-updating and non-persistent."""
    part = _Part()

    PartDesign(part).create_rectangular_pattern(
        _pad(), 2, 2, 60.0, 60.0, PATTERN_DIRECTION_X, PATTERN_DIRECTION_Y
    )

    assert part.update_calls == 0
    assert part.save_calls == 0


def test_remove_rectangular_pattern_uses_the_verified_selection_sequence() -> None:
    """A failed pattern update can be cleaned up without raw COM access."""
    part = _Part()
    selection = _Selection()
    design = PartDesign(part, selection=selection)
    pattern = design.create_rectangular_pattern(
        _pad(), 2, 2, 60.0, 60.0, PATTERN_DIRECTION_X, PATTERN_DIRECTION_Y
    )

    design.remove_rectangular_pattern(pattern)

    assert selection.actions == [
        "Clear",
        ("Add", pattern.com_object),
        "Delete",
        "Clear",
    ]
    assert part.update_calls == 0
    assert part.save_calls == 0


def test_remove_rectangular_pattern_rejects_another_wrapper_before_selection() -> None:
    """Deletion accepts only the object-returning pattern wrapper."""
    selection = _Selection()

    with pytest.raises(ParameterTypeError):
        PartDesign(_Part(), selection=selection).remove_rectangular_pattern(_pad())

    assert selection.actions == []
