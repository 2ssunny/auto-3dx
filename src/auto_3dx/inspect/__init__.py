"""Read-only inspection of what a Part already contains.

Reached as `part.inspect`. Results are frozen dataclasses; text rendering sits on top
(`docs/api-design.md` section 11).
"""

from auto_3dx.inspect.summary import (
    SUPPORTED_FEATURE_KINDS,
    UpdateIssue,
    BodyInfo,
    FeatureInfo,
    GeometricalSetInfo,
    GeometryInfo,
    InWorkObjectInfo,
    Inspector,
    PartSummary,
    TopologyCounts,
)

__all__ = [
    "SUPPORTED_FEATURE_KINDS",
    "UpdateIssue",
    "BodyInfo",
    "FeatureInfo",
    "GeometricalSetInfo",
    "GeometryInfo",
    "InWorkObjectInfo",
    "Inspector",
    "PartSummary",
    "TopologyCounts",
]
