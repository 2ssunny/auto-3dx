"""Tests for the package export policy (`docs/api-design.md` section 13).

The package root offers only what an ordinary script needs to name directly. It
used to export 65 names while real usage was `Catia` and `Part`, which made every
implementation class look like a stable entry point. These tests pin the small root
and, just as importantly, prove nothing became unreachable: every public class that
left the root is still importable from its own package.
"""

import importlib

import pytest

import auto_3dx

ROOT_EXPORTS = {
    "Catia",
    "Part",
    "Auto3dxError",
    "SessionError",
    "ValidationError",
    "NotFoundError",
    "ConflictError",
    "AutomationError",
    "PartUpdateError",
    "StaleSnapshotError",
}

# Every public class reachable before the root was trimmed, and the package that
# must now provide it.
HOMES = {
    "auto_3dx.core": ["Catia", "EditorInfo", "Part"],
    "auto_3dx.parameters": [
        "Parameter",
        "ParameterCollection",
        "ParameterInfo",
        "UnitCatalogue",
        "UnitInfo",
    ],
    "auto_3dx.formulas": ["Formula", "FormulaCollection"],
    "auto_3dx.measurement": ["MassProperties", "SolidMeasurement"],
    "auto_3dx.inspect": ["Inspector", "PartSummary", "FeatureInfo"],
    "auto_3dx.geometry": [
        "Sketch",
        "SketchCollection",
        "SketchEditor",
        "SketchElement",
        "Constraint",
        "ConstraintCollection",
        "PartDesign",
        "SketchFeature",
        "RevolvedFeature",
        "Pad",
        "Pocket",
        "Shaft",
        "Groove",
        "Mirror",
        "Rib",
        "Slot",
        "RectangularPattern",
        "ConstRadEdgeFillet",
        "Chamfer",
        "Shell",
        "Thickness",
        "Hole",
        "Topology",
        "Edge",
        "EdgeSnapshot",
        "Face",
        "FaceSnapshot",
        "Plane",
        "OffsetPlane",
        "AnglePlane",
        "PlaneCollection",
    ],
}


def test_the_root_exports_exactly_the_policy_set() -> None:
    """Adding a root name is a deliberate API decision, not a side effect."""
    assert set(auto_3dx.__all__) == ROOT_EXPORTS


def test_every_root_name_is_importable() -> None:
    """`__all__` must not promise a name the package does not define."""
    missing = [name for name in auto_3dx.__all__ if not hasattr(auto_3dx, name)]

    assert missing == []


def test_no_root_name_is_listed_twice() -> None:
    """A duplicate in `__all__` is a merge accident."""
    assert len(auto_3dx.__all__) == len(set(auto_3dx.__all__))


@pytest.mark.parametrize(
    ("package", "name"),
    [(package, name) for package, names in HOMES.items() for name in names],
)
def test_a_class_that_left_the_root_is_importable_from_its_own_package(
    package: str, name: str
) -> None:
    """Trimming the root must not make any public class unreachable."""
    module = importlib.import_module(package)

    assert name in module.__all__
    assert hasattr(module, name)


def test_every_error_is_importable_from_the_errors_module() -> None:
    """Concrete errors left the root, and `auto_3dx.errors` is their home."""
    errors = importlib.import_module("auto_3dx.errors")

    for name in ("SketchNotFoundError", "ParameterTypeError", "FeatureConflictError"):
        assert hasattr(errors, name)
