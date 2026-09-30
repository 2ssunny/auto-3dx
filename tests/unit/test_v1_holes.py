"""v1 holes: placement read back and corrected, up-to-next, counterbored and countersunk heads.

The fakes follow the micro-probes:

    AddNewHoleFromPoint on a face bounded by one circle -> origin snapped to its centre (47d)
    Hole.SetOrigin(x, y, z)                              -> origin moved, kept on rebuild (47m)
    BottomLimit.LimitMode = 1                            -> up to the next face (47f)
    Type = 2, HeadDiameter, HeadDepth                    -> counterbore (47h)
    Type = 3, CounterSunkMode = 0, HeadDepth, HeadAngle  -> countersink (47h)
    Type carried over from the previous hole             -> always written (47h)
"""

from typing import Any

import pytest

from auto_3dx.errors import (
    AutomationError,
    HolePlacementMismatchError,
    ParameterTypeError,
    PartialCreationError,
)
from auto_3dx.geometry import (
    HOLE_LIMIT_UP_TO_NEXT,
    HOLE_TYPE_COUNTERBORED,
    HOLE_TYPE_COUNTERSUNK,
    HOLE_TYPE_SIMPLE,
    Counterbore,
    Countersink,
)
from tests.conftest import make_com_error
from tests.unit import test_phase5_low_level as phase5
from tests.unit.test_phase5_low_level import TOP, _face, _setup


class _Logged:
    def __init__(self, name: str, value: float, log: "list[str]") -> None:
        self._name = name
        self._value = value
        self._log = log

    @property
    def Value(self) -> float:  # noqa: N802
        return self._value

    @Value.setter
    def Value(self, value: float) -> None:  # noqa: N802
        self._log.append(f"{self._name}={value}")
        self._value = value


class Hole(phase5.Hole):  # noqa: N801 - CATIA's type name
    """The Phase 5 fake plus `Type`, heads and `SetOrigin`; can snap like probe 47d."""

    snap_to: "tuple[float, float, float] | None" = None
    set_origin_moves: bool = True
    set_origin_fails: bool = False

    def __init__(self, body: Any, depth: float, origin: Any) -> None:
        super().__init__(body, depth, origin)
        if Hole.snap_to is not None:
            self._origin = Hole.snap_to
        self._type = 2  # carried over from an earlier counterbored hole
        self.HeadDiameter = _Logged("HeadDiameter", 12.0, self.log)
        self.HeadDepth = _Logged("HeadDepth", 4.0, self.log)
        self.HeadAngle = _Logged("HeadAngle", 90.0, self.log)
        self._cs_mode = 1

    @property
    def Type(self) -> int:  # noqa: N802
        return self._type

    @Type.setter
    def Type(self, value: int) -> None:  # noqa: N802
        self.log.append(f"Type={value}")
        self._type = value

    @property
    def CounterSunkMode(self) -> int:  # noqa: N802
        return self._cs_mode

    @CounterSunkMode.setter
    def CounterSunkMode(self, value: int) -> None:  # noqa: N802
        self.log.append(f"CounterSunkMode={value}")
        self._cs_mode = value

    def SetOrigin(self, x: float, y: float, z: float) -> None:  # noqa: N802
        self.log.append(f"SetOrigin=({x}, {y}, {z})")
        if Hole.set_origin_fails:
            raise make_com_error()
        if Hole.set_origin_moves:
            self._origin = (x, y, z)


@pytest.fixture(autouse=True)
def _v1_hole(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(phase5, "Hole", Hole)
    monkeypatch.setattr(Hole, "snap_to", None)
    monkeypatch.setattr(Hole, "set_origin_moves", True)
    monkeypatch.setattr(Hole, "set_origin_fails", False)


# --- placement ---------------------------------------------------------------------------------


def test_a_hole_placed_where_asked_is_not_moved() -> None:
    part, raw = _setup()

    hole = part.part_design.create_hole("H", _face(part, raw, TOP), 5.0, origin=(10, 5, 20))

    assert hole.origin == (10.0, 5.0, 20.0)
    assert not any(entry.startswith("SetOrigin") for entry in hole.com_object.log)


def test_a_hole_catia_snapped_to_a_circle_centre_is_moved_back() -> None:
    Hole.snap_to = (0.0, 0.0, 20.0)
    part, raw = _setup()

    hole = part.part_design.create_hole("H", _face(part, raw, TOP), 5.0, origin=(8, 0, 20))

    assert hole.origin == (8.0, 0.0, 20.0)
    assert hole.com_object.log[-1] == "SetOrigin=(8.0, 0.0, 20.0)"


def test_a_hole_that_stays_in_the_wrong_place_raises_with_both_points() -> None:
    Hole.snap_to = (0.0, 0.0, 20.0)
    Hole.set_origin_moves = False
    part, raw = _setup()

    with pytest.raises(HolePlacementMismatchError) as caught:
        part.part_design.create_hole("H", _face(part, raw, TOP), 5.0, origin=(8, 0, 20))

    error = caught.value
    assert (error.hole_name, error.requested, error.actual) == (
        "H",
        (8.0, 0.0, 20.0),
        (0.0, 0.0, 20.0),
    )
    assert isinstance(error, PartialCreationError)  # the hole exists: remove it
    assert isinstance(error, AutomationError)
    assert "remove it" in str(error)
    assert len(raw.MainBody.Shapes.items) == 1  # never deleted behind the caller's back


def test_a_failed_move_is_reported_as_a_placement_mismatch() -> None:
    Hole.snap_to = (0.0, 0.0, 20.0)
    Hole.set_origin_fails = True
    part, raw = _setup()

    with pytest.raises(HolePlacementMismatchError, match="moving it failed"):
        part.part_design.create_hole("H", _face(part, raw, TOP), 5.0, origin=(8, 0, 20))


def test_a_hole_without_an_origin_is_left_where_catia_puts_it() -> None:
    Hole.snap_to = (1.0, 2.0, 20.0)
    part, raw = _setup()

    hole = part.part_design.create_hole("H", _face(part, raw, TOP), 5.0)

    assert hole.origin == (1.0, 2.0, 20.0)


def test_the_high_level_hole_is_checked_the_same_way() -> None:
    Hole.snap_to = (0.0, 0.0, 20.0)
    Hole.set_origin_moves = False
    part, raw = _setup()
    top = _face(part, raw, TOP)

    with pytest.raises(HolePlacementMismatchError):
        part.bodies.get("PartBody").features.hole(
            "H", support=top, center=(8.0, 0.0), diameter=4.0, depth=5.0
        )


# --- limits and type ---------------------------------------------------------------------------


def test_an_up_to_next_hole_takes_no_depth() -> None:
    part, raw = _setup()

    hole = part.part_design.create_hole(
        "H", _face(part, raw, TOP), origin=(0, 0, 20), limit=HOLE_LIMIT_UP_TO_NEXT
    )

    assert "LimitMode=1" in hole.com_object.log
    assert hole.limit == HOLE_LIMIT_UP_TO_NEXT
    with pytest.raises(ParameterTypeError, match="no depth"):
        hole.set_limit(HOLE_LIMIT_UP_TO_NEXT, depth=4.0)


def test_the_type_is_always_written_because_catia_carries_it_over() -> None:
    part, raw = _setup()

    hole = part.part_design.create_hole("H", _face(part, raw, TOP), 5.0)

    assert hole.com_object.log == ["LimitMode=0", "Type=0"]
    assert (hole.hole_type, hole.head) == (HOLE_TYPE_SIMPLE, None)


def test_a_counterbored_hole_writes_type_then_head() -> None:
    part, raw = _setup()

    hole = part.part_design.create_hole(
        "H", _face(part, raw, TOP), 10.0, diameter=6.0, head=Counterbore(12.0, 4.0)
    )

    assert hole.com_object.log[-3:] == ["Type=2", "HeadDiameter=12.0", "HeadDepth=4.0"]
    assert hole.hole_type == HOLE_TYPE_COUNTERBORED
    assert hole.head == Counterbore(diameter=12.0, depth=4.0)


def test_a_countersunk_hole_uses_depth_and_angle_mode() -> None:
    part, raw = _setup()

    hole = part.part_design.create_hole(
        "H", _face(part, raw, TOP), 10.0, head=Countersink(depth=2.0, angle_deg=90.0)
    )

    assert hole.com_object.log[-4:] == [
        "Type=3",
        "CounterSunkMode=0",
        "HeadDepth=2.0",
        "HeadAngle=90.0",
    ]
    assert hole.hole_type == HOLE_TYPE_COUNTERSUNK
    assert hole.head == Countersink(depth=2.0, angle_deg=90.0)


def test_a_head_can_be_changed_and_removed_afterwards() -> None:
    part, raw = _setup()
    hole = part.part_design.create_hole("H", _face(part, raw, TOP), 10.0)
    before = part._generation.value

    hole.set_head(Counterbore(10.0, 3.0))
    assert hole.head == Counterbore(10.0, 3.0)
    hole.set_head(None)

    assert hole.hole_type == HOLE_TYPE_SIMPLE
    assert part._generation.value > before


@pytest.mark.parametrize(
    "head",
    [
        Counterbore(0.0, 4.0),
        Counterbore(12.0, -1.0),
        Countersink(2.0, 180.0),
        Countersink(2.0, 0.0),
        Countersink(float("nan"), 90.0),
        (12.0, 4.0),
        "counterbore",
    ],
)
def test_a_bad_head_is_refused_before_the_factory(head: Any) -> None:
    part, raw = _setup()

    with pytest.raises(ParameterTypeError):
        part.part_design.create_hole("H", _face(part, raw, TOP), 10.0, head=head)
    assert raw.ShapeFactory.calls == []
