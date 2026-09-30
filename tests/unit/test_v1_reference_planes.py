"""v1 reference geometry: an offset plane from a planar face, on a chosen material side.

Live evidence (probes 47e, 47n, 47o): `AddNewPlaneOffset(face reference, d, orientation)`
builds a plane parallel to a block face; orientation False went INTO the material on the
top, bottom and +X faces and True out of it; the plane reports `GetOrigin` only after
`Part.Update()`.
"""

from typing import Any

import pytest

from auto_3dx._generation import ModelGeneration
from auto_3dx.errors import (
    AutomationError,
    ParameterTypeError,
    StaleSnapshotError,
    UnsupportedSupportError,
    ValidationError,
)
from auto_3dx.geometry.faces import Face
from auto_3dx.geometry.planes import OffsetPlane, PlaneCollection
from auto_3dx.highlevel import INTO_MATERIAL, PartGeometry
from tests.unit.test_phase4 import X, Y, _cylinder_face, _measurer, _plane_face
from tests.unit.test_user_planes import FakePart, FakePlaneOffsetShape

TOP = _plane_face(2400.0, (0, 0, 20), X, Y, origin=(0, 0, 20))
BORE = _cylinder_face(628.3, (0, 0, 10), 5.0)


def _setup() -> "tuple[PlaneCollection, FakePart, ModelGeneration]":
    raw = FakePart()
    generation = ModelGeneration()
    return PlaneCollection(raw, generation=generation), raw, generation


def _face(shape: Any, generation: ModelGeneration) -> Face:
    return Face(shape, 1, generation.value, measurer=_measurer(), model_generation=generation)


def _offset_calls(raw: FakePart) -> "list[Any]":
    return [call for call in raw.calls if call[0] == "AddNewPlaneOffset"]


def test_a_planar_face_is_an_offset_plane_support() -> None:
    planes, raw, generation = _setup()
    face = _face(TOP, generation)

    plane = planes.create_offset("ABOVE", face, 5.0, True)

    assert _offset_calls(raw) == [("AddNewPlaneOffset", TOP, 5.0, True)]
    assert isinstance(plane, OffsetPlane)


def test_a_bad_face_support_is_refused_before_the_factory() -> None:
    planes, raw, generation = _setup()
    stale = _face(TOP, generation)
    generation.advance()

    with pytest.raises(StaleSnapshotError):
        planes.create_offset("P", stale, 5.0)
    with pytest.raises(UnsupportedSupportError, match="planar"):
        planes.create_offset("P", _face(BORE, generation), 5.0)
    with pytest.raises(ValidationError, match="another Part"):
        planes.create_offset("P", _face(TOP, ModelGeneration()), 5.0)
    assert _offset_calls(raw) == []


def test_a_plane_reports_its_origin_only_once_built() -> None:
    shape = FakePlaneOffsetShape([], None, 5.0, False)
    shape.Name = "P"
    plane = OffsetPlane(shape)

    with pytest.raises(AutomationError, match="part.update"):
        plane.origin  # probe 47n: GetOrigin fails before the update

    shape.GetOrigin = lambda seed: (0.0, 0.0, 25.0)  # type: ignore[attr-defined]
    shape.GetFirstAxis = lambda seed: (-1.0, 0.0, 0.0)  # type: ignore[attr-defined]
    shape.GetSecondAxis = lambda seed: (0.0, 1.0, 0.0)  # type: ignore[attr-defined]
    assert plane.origin == (0.0, 0.0, 25.0)
    assert plane.normal == pytest.approx((0.0, 0.0, -1.0))


class _Part:
    def __init__(self, planes: PlaneCollection) -> None:
        self.planes = planes


def test_the_high_level_side_is_a_material_side() -> None:
    planes, raw, generation = _setup()
    geometry = PartGeometry(_Part(planes))  # type: ignore[arg-type]

    geometry.offset_plane("ABOVE", face=_face(TOP, generation), distance=5)
    geometry.offset_plane("BELOW", face=_face(TOP, generation), distance=5, side=INTO_MATERIAL)

    assert [call[3] for call in _offset_calls(raw)] == [True, False]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"distance": 0},
        {"distance": -5},
        {"distance": True},
        {"distance": 5, "side": "up"},
        {"distance": 5, "face": "top"},
    ],
)
def test_a_bad_high_level_plane_request_is_refused(kwargs: Any) -> None:
    planes, raw, generation = _setup()
    geometry = PartGeometry(_Part(planes))  # type: ignore[arg-type]
    arguments = {"face": _face(TOP, generation), **kwargs}

    with pytest.raises(ParameterTypeError):
        geometry.offset_plane("P", **arguments)
    assert _offset_calls(raw) == []
