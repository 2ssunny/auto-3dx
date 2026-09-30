"""Level 3: a thin, intent-oriented API composed from the public Level 2 SDK.

Reached through attributes, never needed as an import for ordinary scripts:

    body.features.pad(...)      BodyFeatures    (auto_3dx.highlevel.features)
    sketch.rectangle(...)       profiles        (auto_3dx.highlevel.profiles)
    part.geometry.top_face()    PartGeometry    (auto_3dx.highlevel.finders)
    part.inspect.facts(...)     PartFacts       (auto_3dx.highlevel.facts)

Every call here resolves to Level 2 calls a script could make itself -- `create_pad`,
`sketches.create`, `topology.faces().query()...one()`, `measurement.measure()` -- inside
`part.work_in(body)` where a body is involved. This package imports no COM library and
never reads a wrapper's `com_object`; `tests/unit/test_highlevel_boundary.py` enforces it.
Nothing here rebuilds: `part.update()` stays explicit (`docs/phase5-api-design.md`).
"""

from auto_3dx.highlevel.directions import (
    AGAINST_NORMAL,
    ALONG_NORMAL,
    INTO_MATERIAL,
    OUT_OF_MATERIAL,
    SUPPORTED_EXTRUSION_DIRECTIONS,
    extrusion_direction,
)
from auto_3dx.highlevel.facts import SUPPORTED_FACTS, PartFacts, read_facts
from auto_3dx.highlevel.features import BodyFeatures, hole_origin, pattern_spacing
from auto_3dx.highlevel.finders import PartGeometry, axis_vector
from auto_3dx.highlevel.profiles import (
    CONSTRAINTS_DIMENSIONED,
    CONSTRAINTS_FULLY,
    CONSTRAINTS_NONE,
    CONSTRAINTS_ORIENTATION,
    SUPPORTED_RECTANGLE_CONSTRAINTS,
    RectangleProfile,
    centered_rectangle,
    circle,
    rectangle,
)

__all__ = [
    "AGAINST_NORMAL",
    "ALONG_NORMAL",
    "INTO_MATERIAL",
    "OUT_OF_MATERIAL",
    "SUPPORTED_EXTRUSION_DIRECTIONS",
    "extrusion_direction",
    "SUPPORTED_FACTS",
    "PartFacts",
    "read_facts",
    "BodyFeatures",
    "hole_origin",
    "pattern_spacing",
    "PartGeometry",
    "axis_vector",
    "CONSTRAINTS_DIMENSIONED",
    "CONSTRAINTS_FULLY",
    "CONSTRAINTS_NONE",
    "CONSTRAINTS_ORIENTATION",
    "SUPPORTED_RECTANGLE_CONSTRAINTS",
    "RectangleProfile",
    "centered_rectangle",
    "circle",
    "rectangle",
]
