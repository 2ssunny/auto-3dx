"""Measurement layer: read-only mass properties for a solid.

`Part.Update()` succeeding only means a feature rebuilt, not that it did what
was asked -- a pocket that removes nothing updates fine (`docs/api-design.md`
section 6). This package closes that gap by measuring the resulting solid through
CATIA's `Editor`-hosted Inertia/InertiaBox services (verified in
`scripts/probes/30_measurement.py`), and re-exports the public surface from
`inertia`.
"""

from auto_3dx.measurement.inertia import (
    CUBIC_METRES_TO_CUBIC_MILLIMETRES,
    INERTIA_SERVICE_NAME,
    METRES_TO_MILLIMETRES,
    MassProperties,
    SQUARE_METRES_TO_SQUARE_MILLIMETRES,
    SolidMeasurement,
)

__all__ = [
    "CUBIC_METRES_TO_CUBIC_MILLIMETRES",
    "INERTIA_SERVICE_NAME",
    "METRES_TO_MILLIMETRES",
    "MassProperties",
    "SQUARE_METRES_TO_SQUARE_MILLIMETRES",
    "SolidMeasurement",
]
