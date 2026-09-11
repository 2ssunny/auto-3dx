"""Geometry layer: sketches and Part Design pad/pocket features on top of `core.Part`.

Exposes `Sketch`/`SketchCollection` (2D profiles on origin planes) and
`SketchFeature`/`Pad`/`Pocket`/`PartDesign` (extruded and pocketed solid
features), matching the verified COM surface documented in
`docs/conventions.md` sections 1.2/1.2.1/1.3 and the public API contract in
sections 6.9/6.10/6.11.
"""

from auto_3dx.geometry.part_design import (
    LENGTH_TOLERANCE,
    PAD_KIND,
    POCKET_KIND,
    Pad,
    PartDesign,
    Pocket,
    SketchFeature,
)
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
    "POCKET_KIND",
    "SketchFeature",
    "Pad",
    "Pocket",
    "PartDesign",
]
