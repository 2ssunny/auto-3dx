"""Geometry layer: sketches and Part Design features on top of `core.Part`.

Exposes `Sketch`/`SketchCollection` (2D profiles on origin planes) and
`SketchFeature`/`Pad`/`Pocket`/`RevolvedFeature`/`Shaft`/`Groove`/`Mirror`/
`PartDesign` (extruded, pocketed, revolved, and mirrored solid features),
matching the verified COM surface documented in `docs/conventions.md`
sections 1.2/1.2.1/1.2.3/1.3 and the public API contract in sections
6.9/6.10/6.11/6.13.
"""

from auto_3dx.geometry.part_design import (
    FULL_REVOLUTION,
    GROOVE_KIND,
    LENGTH_TOLERANCE,
    MIRROR_KIND,
    PAD_KIND,
    POCKET_KIND,
    SHAFT_KIND,
    Groove,
    Mirror,
    Pad,
    PartDesign,
    Pocket,
    RevolvedFeature,
    Shaft,
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
    "SHAFT_KIND",
    "GROOVE_KIND",
    "MIRROR_KIND",
    "FULL_REVOLUTION",
    "SketchFeature",
    "Pad",
    "Pocket",
    "RevolvedFeature",
    "Shaft",
    "Groove",
    "Mirror",
    "PartDesign",
]
