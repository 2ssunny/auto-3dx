"""Geometry layer: sketches and Part Design pad features on top of `core.Part`.

Exposes `Sketch`/`SketchCollection` (2D profiles on origin planes) and
`Pad`/`PartDesign` (extruded solid features), matching the verified COM
surface documented in `docs/conventions.md` sections 1.2/1.3 and the public
API contract in sections 6.9/6.10.
"""

from auto_3dx.geometry.part_design import LENGTH_TOLERANCE, PAD_KIND, Pad, PartDesign
from auto_3dx.geometry.sketch import (
    AXIS_TOLERANCE,
    SUPPORT_XY,
    SUPPORT_YZ,
    SUPPORT_ZX,
    SUPPORTED_SKETCH_SUPPORTS,
    Sketch,
    SketchCollection,
    SketchEditor,
)

__all__ = [
    "AXIS_TOLERANCE",
    "SUPPORT_XY",
    "SUPPORT_YZ",
    "SUPPORT_ZX",
    "SUPPORTED_SKETCH_SUPPORTS",
    "Sketch",
    "SketchCollection",
    "SketchEditor",
    "LENGTH_TOLERANCE",
    "PAD_KIND",
    "Pad",
    "PartDesign",
]
