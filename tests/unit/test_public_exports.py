"""Tests that the package's public surface actually exposes what it documents.

A capability that can only be reached with a deep import
(`from auto_3dx.geometry.edges import Edge`) is not really part of the public
API, and this gap went unnoticed until the documentation was written against
the package and the two disagreed. These tests keep them in step.
"""

import auto_3dx


def test_every_advertised_name_is_importable() -> None:
    """`__all__` must not promise a name the package does not define."""
    missing = [name for name in auto_3dx.__all__ if not hasattr(auto_3dx, name)]

    assert missing == []


def test_no_name_is_advertised_twice() -> None:
    """A duplicate in `__all__` is a merge accident, not a decision."""
    duplicates = sorted({n for n in auto_3dx.__all__ if auto_3dx.__all__.count(n) > 1})

    assert duplicates == []


def test_the_topology_layer_is_reachable_from_the_package() -> None:
    """Edges, faces and their features are public, not implementation detail."""
    for name in (
        "Edge",
        "EdgeSnapshot",
        "Face",
        "FaceSnapshot",
        "ConstRadEdgeFillet",
        "Chamfer",
        "Shell",
        "Thickness",
        "Hole",
        "StaleSnapshotError",
    ):
        assert name in auto_3dx.__all__
        assert hasattr(auto_3dx, name)


def test_the_plane_layer_is_reachable_from_the_package() -> None:
    """A caller passing a plane to `sketches.create` should not need a deep import."""
    for name in ("Plane", "OffsetPlane", "AnglePlane", "PlaneCollection"):
        assert name in auto_3dx.__all__
        assert hasattr(auto_3dx, name)
