"""Public API for automating a running 3DEXPERIENCE CATIA session.

The package root offers only what an ordinary script needs to name directly
(`docs/api-design.md` section 13): the session entry point, the `Part` type, and the
error categories a caller catches. Everything else is reached through attributes,

    catia = Catia.attach()
    part = catia.active_part()
    sketch = part.sketches.create("Profile", support="XY")

and imported for type hints from its own package: `auto_3dx.geometry`,
`auto_3dx.parameters`, `auto_3dx.formulas`, `auto_3dx.measurement`,
`auto_3dx.core` and `auto_3dx.errors`.

A small root keeps every implementation class from looking like a stable entry
point, so an internal rename does not become a breaking change.
"""

from auto_3dx.core.application import Catia
from auto_3dx.core.part import Part
from auto_3dx.errors import (
    Auto3dxError,
    AutomationError,
    ConflictError,
    NotFoundError,
    PartUpdateError,
    SessionError,
    StaleSnapshotError,
    ValidationError,
)

__all__ = [
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
]
