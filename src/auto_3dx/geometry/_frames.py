"""Reading a plane's absolute frame, so a sketch can be matched to the plane it sits on.

A `Sketch` has no support property in this release: the live object exposes only
`GetAbsoluteAxisData` (probe, 2026-09-16, and `docs/conventions.md` 1.2.3). A plane
created by `HybridShapeFactory`, however, reports its own frame:

    plane.IsARefPlane() -> 1
    plane.GetOrigin(seed3)     -> (0.0, 0.0, 35.0)
    plane.GetFirstAxis(seed3)  -> (1.0, 0.0, 0.0)
    plane.GetSecondAxis(seed3) -> (0.0, 1.0, 0.0)

and a sketch built on that plane reports exactly the same nine numbers from
`GetAbsoluteAxisData` -- measured for an offset plane and for an angle plane, whose
frame is not axis aligned at all (`docs/conventions.md` 1.7). Matching the two frames
is therefore an equality test, not a geometric guess.

The three origin planes come back as plain `AnyObject` in this release and expose none
of these methods, which is why they keep their own verified reference frames in
`geometry.sketch`. This module is a leaf: it imports nothing from the SDK, so both
`geometry.sketch` and `geometry.planes` can use it without a cycle.
"""

from typing import Any

import pywintypes

FRAME_SEED: "tuple[float, float, float]" = (0.0, 0.0, 0.0)
"""Seed buffer the plane frame getters need; they return the filled tuple."""

_FRAME_LENGTH = 9


def plane_frame(raw_plane: Any) -> "tuple[float, ...] | None":
    """Reads a plane's absolute frame as origin + first axis + second axis.

    Args:
        raw_plane: A raw CATIA plane COM object.

    Returns:
        The 9-tuple `(origin, first axis, second axis)`, directly comparable with a
        sketch's `GetAbsoluteAxisData`, or `None` when this object cannot report its
        frame. An origin plane is the known case: it arrives as `AnyObject` and has
        none of these methods, so callers fall back to their own reference frames
        rather than treating the absence as a failure.
    """
    try:
        origin = tuple(raw_plane.GetOrigin(list(FRAME_SEED)))
        first = tuple(raw_plane.GetFirstAxis(list(FRAME_SEED)))
        second = tuple(raw_plane.GetSecondAxis(list(FRAME_SEED)))
    except (AttributeError, TypeError, ValueError, pywintypes.com_error):
        return None
    frame = origin + first + second
    if len(frame) != _FRAME_LENGTH:
        return None
    return frame
