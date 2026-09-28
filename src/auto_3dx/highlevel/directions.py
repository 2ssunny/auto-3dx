"""Engineering-intent words for which way a pad or pocket goes, turned into Level 2 values.

Level 2 speaks CATIA's language: `DIRECTION_ALONG_SKETCH_NORMAL` or
`DIRECTION_AGAINST_SKETCH_NORMAL` on `create_pad`/`create_pocket`. This module accepts the
words an engineer uses and translates them, or refuses when the answer cannot be known:

    None                           CATIA's default (a pad along, a pocket against the normal)
    "along_normal"/"against_normal"  the Level 2 values under shorter names
    "+X" ... "-Z"                  along or against, when the sketch normal is parallel to
                                   that world axis (read from the sketch frame)
    "into_material"/"out_of_material"
                                   only for a sketch the SDK itself created on a face, whose
                                   normal points out of that face's material (probes 46i,
                                   46j, 46aa); a pocket's default then cut into the material
                                   (probe 46k)

"forward"/"reverse" are deliberately absent: they would only rename along/against.
"""

from typing import Any

from auto_3dx.errors import ParameterTypeError, UnsupportedOperationError
from auto_3dx.geometry.part_design import (
    DIRECTION_AGAINST_SKETCH_NORMAL,
    DIRECTION_ALONG_SKETCH_NORMAL,
)
from auto_3dx.geometry.sketch import Sketch

ALONG_NORMAL: str = "along_normal"
"""The way the sketch normal points (`DIRECTION_ALONG_SKETCH_NORMAL`)."""

AGAINST_NORMAL: str = "against_normal"
"""Against the sketch normal (`DIRECTION_AGAINST_SKETCH_NORMAL`)."""

INTO_MATERIAL: str = "into_material"
"""Into the solid the sketch's face belongs to. Only for a sketch created on a face."""

OUT_OF_MATERIAL: str = "out_of_material"
"""Away from the solid the sketch's face belongs to. Only for a sketch created on a face."""

AXIS_DIRECTIONS: "dict[str, tuple[float, float, float]]" = {
    "+X": (1.0, 0.0, 0.0),
    "-X": (-1.0, 0.0, 0.0),
    "+Y": (0.0, 1.0, 0.0),
    "-Y": (0.0, -1.0, 0.0),
    "+Z": (0.0, 0.0, 1.0),
    "-Z": (0.0, 0.0, -1.0),
}
"""Signed world axes a pad or pocket direction may name."""

_NORMAL_WORDS: "dict[str, str]" = {
    ALONG_NORMAL: DIRECTION_ALONG_SKETCH_NORMAL,
    AGAINST_NORMAL: DIRECTION_AGAINST_SKETCH_NORMAL,
    DIRECTION_ALONG_SKETCH_NORMAL: DIRECTION_ALONG_SKETCH_NORMAL,
    DIRECTION_AGAINST_SKETCH_NORMAL: DIRECTION_AGAINST_SKETCH_NORMAL,
}

SUPPORTED_EXTRUSION_DIRECTIONS: "frozenset[str]" = frozenset(
    {*_NORMAL_WORDS, *AXIS_DIRECTIONS, INTO_MATERIAL, OUT_OF_MATERIAL}
)
"""Every word `extrusion_direction` understands."""


def extrusion_direction(direction: Any, profile: Any) -> "str | None":
    """Translates an intent direction for a pad or pocket into the Level 2 value.

    Args:
        direction: `None`, or one of `SUPPORTED_EXTRUSION_DIRECTIONS`.
        profile: The `Sketch` the feature is built from.

    Returns:
        `DIRECTION_ALONG_SKETCH_NORMAL`, `DIRECTION_AGAINST_SKETCH_NORMAL`, or `None` to keep
        CATIA's default.

    Raises:
        ParameterTypeError: If `direction` is not a known word, or `profile` is not a
            `Sketch` when the word needs its frame.
        UnsupportedOperationError: If the word cannot be answered for this sketch: an axis
            the sketch normal is not parallel to, or a material side for a sketch the SDK
            did not create on a face.
        Auto3dxError: If the sketch frame cannot be read.
    """
    if direction is None:
        return None
    if not isinstance(direction, str) or direction not in SUPPORTED_EXTRUSION_DIRECTIONS:
        raise ParameterTypeError(
            f"direction must be one of {sorted(SUPPORTED_EXTRUSION_DIRECTIONS)} or None, "
            f"not {direction!r}."
        )
    if direction in _NORMAL_WORDS:
        return _NORMAL_WORDS[direction]
    if not isinstance(profile, Sketch):
        raise ParameterTypeError(
            f"direction {direction!r} needs the profile Sketch, not {type(profile).__name__}."
        )
    if direction in (INTO_MATERIAL, OUT_OF_MATERIAL):
        if not profile.created_on_face:
            raise UnsupportedOperationError(
                f"{direction!r} can only be answered for a sketch created on a face through "
                "the SDK in this session: its normal is then known to point out of the "
                "material. For this sketch use 'along_normal'/'against_normal' or a world "
                "axis such as '+Z'."
            )
        return (
            DIRECTION_AGAINST_SKETCH_NORMAL
            if direction == INTO_MATERIAL
            else DIRECTION_ALONG_SKETCH_NORMAL
        )
    sense = profile.frame().normal_parallel_to(AXIS_DIRECTIONS[direction])
    if sense is None:
        raise UnsupportedOperationError(
            f"The sketch's normal {profile.frame().normal} is not parallel to {direction}; "
            "an extrusion along that axis cannot be expressed on this sketch. Use "
            "'along_normal' or 'against_normal'."
        )
    return DIRECTION_ALONG_SKETCH_NORMAL if sense > 0 else DIRECTION_AGAINST_SKETCH_NORMAL
