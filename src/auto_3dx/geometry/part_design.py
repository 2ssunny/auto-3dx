"""Wrappers around CATIA `Pad`/`Pocket`/`Shaft`/`Groove`/`Mirror`/`Rib`/`Slot` Part
Design features.

A `Pad` extrudes a `Sketch` profile along its normal by a fixed height. A
`Pocket` removes material along the same profile by a fixed depth. Verified
against a live session (`docs/conventions.md` section 1.2.1), `Pocket`'s
readable properties are identical to `Pad`'s, and `FirstLimit.Dimension.Value`
holds the magnitude passed to `AddNewPad`/`AddNewPocket` at creation for both.
That structural symmetry is factored into a shared `SketchFeature` base;
`Pad` and `Pocket` differ only in their `type(com_object).__name__` and, for
`Pad`, the pre-existing `height`/`set_height` public API kept for backward
compatibility.

`Shaft` and `Groove` are the revolved counterparts (`docs/conventions.md`
section 1.2.3): each revolves a `Sketch` profile around the axis set on that
sketch's `CenterLine`, adding material for a `Shaft` and removing it for a
`Groove`, and both expose `FirstAngle`/`SecondAngle` instead of `FirstLimit`.
That symmetry is factored into a shared `RevolvedFeature` base, the same way
`SketchFeature` is shared by `Pad`/`Pocket`.

`Mirror`, `Rib`, and `Slot` (`docs/conventions.md` sections 1.2.3/1.2.5/6.16)
are neither depth- nor angle-driven, so none of them derives from
`SketchFeature` or `RevolvedFeature`. `Mirror` takes a plane rather than a
sketch and carries no `sketch()`/`profile()` accessor at all. `Rib` and
`Slot` each take two sketches (a profile and a path/center-curve) and are
otherwise identical -- a Rib adds material along the path, a Slot removes
it -- but both can only read the profile back (`Sketch`); there is no
verified way to read the path sketch for either. All three still reduce to
nothing more than `com_object`/`Name`/`__repr__`, so rather than writing that
boilerplate a third and fourth time it is factored into a shared
`_NamedFeature` base that all of them inherit.

None of these features has a dedicated typed sub-collection in the verified
API surface, so `PartDesign` finds them all by scanning `MainBody.Shapes` and
keeping items whose `type(item).__name__` matches the relevant `*_KIND`
constant.

`ConstRadEdgeFillet` and `Chamfer` (`docs/conventions.md` section 1.2.2.2) are
the first two Part Design features built on a face/edge reference rather than
a sketch. Getting there required a separate reference layer -- `geometry.edges`
-- because the only verified way to name an edge is a `Reference` read from a
`Selection.Search("Topology.Edge,all")` hit, and that reference's identity is
far less durable than a `Sketch`'s: see `geometry.edges` for the full set of
measured limits (index and BRep name are both non-durable; there is no way to
scope the search to one feature) and for why neither feature ships an
`ensure_*`. Both still reduce to nothing more than `com_object`/`name`, exactly
like `Mirror`/`Rib`/`Slot`, via the same `_NamedFeature` base.

`Shell`, `Thickness`, and `Hole` (probe 37, `docs/conventions.md` section
1.2.2.2) are the face-reference counterparts of `ConstRadEdgeFillet`/
`Chamfer`: built on a `Reference` from `geometry.faces` instead of
`geometry.edges`, for the same reason -- `AddNewShell`/`AddNewThickness`/
`AddNewHole` each take a face, not an edge. They share the exact same
`_list`/`_get`/`_create_feature`/`_remove` plumbing and the exact same
single-generation staleness policy (`geometry.faces`, `_require_current_face`)
as the edge features, and reduce to `com_object`/`name` for the same reason:
there is no verified way to read a shell/thickness/hole's source face back,
so there is no `ensure_shell`/`ensure_thickness`/`ensure_hole` either.

`MultiSectionSolid` (probe 40, `docs/conventions.md` section 1.8) is the Part Design
Multi-sections Solid -- CATIA's `Loft`. It is created differently from every other
feature here: `ShapeFactory.AddNewLoft()` takes no arguments, and the sections are
added to the new feature's `HybridShape` afterwards, one `AddSectionToLoft` call per
section sketch. `_create_feature` gained an optional post-rename `configure` step for
exactly that, so the duplicate-name check, the rename and the `PartialCreationError`
reporting stay shared rather than copied. Its section sketches can be read back from
the live feature by name (`MultiSectionSolid.section_names`), but guides, spine,
coupling, closing points, tangency and relimitation are neither set nor read.
"""

import warnings
import math
from collections.abc import Iterable, Sequence
from typing import Any

import pywintypes

from auto_3dx._generation import ModelGeneration
from auto_3dx.errors import (
    AmbiguousNameError,
    Auto3dxError,
    AutomationError,
    BooleanOperationError,
    CrossBodyReferenceError,
    FeatureConflictError,
    FeatureNotFoundError,
    PartialCreationError,
    ParameterTypeError,
    UnsupportedSupportError,
)
from auto_3dx.geometry.deletion import delete_via_selection
from auto_3dx.geometry.edges import Edge, EdgeSnapshot, take_edge_snapshot
from auto_3dx.geometry.faces import Face, FaceSnapshot, take_face_snapshot
from auto_3dx.geometry.sketch import (
    SUPPORT_YZ,
    SUPPORTED_SKETCH_SUPPORTS,
    Sketch,
    _PLANE_ATTRIBUTE_BY_SUPPORT,
    _wrap_com_error,
)
from auto_3dx.parameters.parameter import (
    DEGREE,
    MILLIMETRE,
    Parameter,
    validate_angle_unit,
    validate_angle_value,
    validate_length_unit,
    validate_length_value,
    validate_parameter_name,
)

LENGTH_TOLERANCE: float = 1e-9
"""Absolute tolerance used to compare feature depths with `math.isclose`."""

CIRCULAR_PATTERN_KIND: str = "CircPattern"
"""`type(item).__name__` of a circular pattern in `Body.Shapes` (probe 44)."""

CIRCULAR_PATTERN_AXIS_Z: str = "Z"
"""The one verified rotation axis for a circular pattern.

Live (probe 44): passing `OriginElements.PlaneXY` as both the rotation centre and the
rotation axis patterned a pocket around the Z axis, and the six instances removed exactly
five extra holes' worth of material. The other two origin planes produced a rotation about
some other axis whose exact mapping the test geometry could not pin down, so only Z is
offered (`docs/conventions.md` section 1.12).
"""

SUPPORTED_CIRCULAR_PATTERN_AXES: "frozenset[str]" = frozenset({CIRCULAR_PATTERN_AXIS_Z})
"""The rotation axes `create_circular_pattern` accepts."""

_CIRCULAR_RADIAL_INSTANCES: int = 1
"""One radial row: the verified call patterns around the axis only."""

_CIRCULAR_RADIAL_STEP: float = 1.0
"""Radial spacing of that single row; unused with one instance, but required."""

_CIRCULAR_ROTATION_ANGLE: float = 0.0
"""`iRotationAngle`, verified at 0.0."""

_CIRCULAR_AXIS_REVERSED: bool = False
"""`iIsReversedRotationAxis`, verified at False."""

_CIRCULAR_RADIUS_ALIGNED: bool = True
"""`iIsRadiusAligned`, verified at True."""

BOOLEAN_REMOVE_KIND: str = "Remove"
"""`type(item).__name__` of a boolean remove feature."""

BOOLEAN_ADD_KIND: str = "Add"
"""`type(item).__name__` of a boolean add feature."""

BOOLEAN_INTERSECT_KIND: str = "Intersect"
"""`type(item).__name__` of a boolean intersect feature."""

BOOLEAN_ASSEMBLE_KIND: str = "Assemble"
"""`type(item).__name__` of a boolean assemble feature."""

BOOLEAN_KINDS: "tuple[str, ...]" = (
    BOOLEAN_REMOVE_KIND,
    BOOLEAN_ADD_KIND,
    BOOLEAN_INTERSECT_KIND,
    BOOLEAN_ASSEMBLE_KIND,
)
"""Every boolean feature kind this SDK creates and finds, all verified live (probe 44)."""

_ACTIVITY_PARAMETER: str = "Activity"
"""The `BoolParam` that suppresses a feature, reached through `Part.Parameters`."""

_MAX_OWNER_WALK: int = 6
"""How far up a feature's `Parent` chain to look for its body and its Part."""


PAD_KIND: str = "Pad"
"""The `type(com_object).__name__` value for a CATIA Pad feature."""

POCKET_KIND: str = "Pocket"
"""The `type(com_object).__name__` value for a CATIA Pocket feature."""

SHAFT_KIND: str = "Shaft"
"""The `type(com_object).__name__` value for a CATIA Shaft feature."""

GROOVE_KIND: str = "Groove"
"""The `type(com_object).__name__` value for a CATIA Groove feature."""

MIRROR_KIND: str = "Mirror"
"""The `type(com_object).__name__` value for a CATIA Mirror feature."""

RIB_KIND: str = "Rib"
"""The `type(com_object).__name__` value for a CATIA Rib feature."""

SLOT_KIND: str = "Slot"
"""The `type(com_object).__name__` value for a CATIA Slot feature."""

MULTI_SECTION_SOLID_KIND: str = "Loft"
"""The `type(com_object).__name__` of a Part Design Multi-sections Solid (probe 40).

CATIA's user interface calls the feature "Multi-sections Solid" and names new ones
`Multi-sections Solid.N`, but the Automation wrapper type is `Loft`.
"""

MULTI_SECTION_ORIENTATION_VERIFIED: int = 1
"""The `iOri` value passed to `AddSectionToLoft` for every section.

The only value tried: it was accepted for both sections in probe 40 and read back as
`1` by `GetSectionFromLoft`, and it is the value the raw NACA wing experiment used. The
type library gives no enum meaning for it, so no other value is offered.
"""

MIN_MULTI_SECTION_SECTIONS: int = 2
"""A Multi-sections Solid needs at least two sections to span between."""

_FIRST_SECTION_RANK: int = 1
"""`GetSectionFromLoft` ranks are 1-based: rank 0 failed and ranks 1 and 2 answered."""

_MAX_SECTION_RANK: int = 1000
"""Upper bound on section read-back, so a release that never fails cannot loop forever."""

_E_FAIL: int = -2147467259
"""`E_FAIL`, which `GetSectionFromLoft` reported for the rank past the last section."""

EDGE_FILLET_KIND: str = "ConstRadEdgeFillet"
"""The `type(com_object).__name__` value for a CATIA constant-radius edge fillet."""

CHAMFER_KIND: str = "Chamfer"
"""The `type(com_object).__name__` value for a CATIA Chamfer feature."""

EDGE_FILLET_PROPAGATION_VERIFIED: int = 1
"""The only `iPropagMode` value verified for `AddNewEdgeFilletWithConstantRadius`.

Verified against a live session (`docs/conventions.md` section 1.2.2.2):
creating a fillet with this propagation mode and then calling
`Part.Update()` succeeded. No other value has been tried against a real
session, so it is the only one `create_edge_fillet` accepts today.
"""

SUPPORTED_EDGE_FILLET_PROPAGATIONS: frozenset[int] = frozenset({EDGE_FILLET_PROPAGATION_VERIFIED})
"""The `iPropagMode` values `create_edge_fillet` accepts. Currently just one."""

CHAMFER_MODE_VERIFIED: int = 1
"""The only working `iMode` value for `AddNewChamfer`.

Verified against a live session (`docs/conventions.md` section 1.2.2.2):
mode 0 creates a feature whose `Part.Update()` fails, and mode 2 fails at
creation. Only mode 1 both creates and updates successfully. `create_chamfer`
always passes this value and does not expose `mode` as a parameter at all --
neither 0 nor 2 is offered under any name.
"""

CHAMFER_PROPAGATION_0: int = 0
CHAMFER_PROPAGATION_1: int = 1
"""The two `iPropagation` values verified for `AddNewChamfer`.

The type library attaches no enum metadata to `iPropagation` (it is a plain
`VT_I4` with no `IID`), so its meaning is not recorded anywhere this library
can read -- only that both 0 and 1 create a feature that then updates
successfully, for both `iOrientation` values (`docs/conventions.md` section
1.2.2.2). Do not infer a meaning (e.g. "minimal" vs. "all tangent") from
these names; they are named by value, not by behavior, because the behavior
is not known.
"""

SUPPORTED_CHAMFER_PROPAGATIONS: frozenset[int] = frozenset(
    {CHAMFER_PROPAGATION_0, CHAMFER_PROPAGATION_1}
)
"""The `iPropagation` values `create_chamfer` accepts."""

CHAMFER_ORIENTATION_0: int = 0
CHAMFER_ORIENTATION_1: int = 1
"""The two `iOrientation` values verified for `AddNewChamfer`.

Same caveat as `CHAMFER_PROPAGATION_0`/`CHAMFER_PROPAGATION_1`: no enum
metadata exists for this integer either, so these are named by value, not by
a guessed meaning. Both values updated successfully for every verified
`iPropagation` value.
"""

SUPPORTED_CHAMFER_ORIENTATIONS: frozenset[int] = frozenset(
    {CHAMFER_ORIENTATION_0, CHAMFER_ORIENTATION_1}
)
"""The `iOrientation` values `create_chamfer` accepts."""

SHELL_KIND: str = "Shell"
"""The `type(com_object).__name__` value for a CATIA Shell feature."""

THICKNESS_KIND: str = "Thickness"
"""The `type(com_object).__name__` value for a CATIA Thickness feature."""

HOLE_KIND: str = "Hole"
"""The `type(com_object).__name__` value for a CATIA Hole feature."""

RECTANGULAR_PATTERN_KIND: str = "RectPattern"
"""The `type(com_object).__name__` value for a CATIA rectangular pattern."""

PATTERN_DIRECTION_X: str = "X"
PATTERN_DIRECTION_Y: str = "Y"
PATTERN_DIRECTION_Z: str = "Z"
PATTERN_DIRECTION_NEGATIVE_X: str = "-X"
PATTERN_DIRECTION_NEGATIVE_Y: str = "-Y"
PATTERN_DIRECTION_NEGATIVE_Z: str = "-Z"
"""The verified signed global axes used by rectangular patterns."""

SUPPORTED_PATTERN_DIRECTIONS: frozenset[str] = frozenset(
    {
        PATTERN_DIRECTION_X,
        PATTERN_DIRECTION_Y,
        PATTERN_DIRECTION_Z,
        PATTERN_DIRECTION_NEGATIVE_X,
        PATTERN_DIRECTION_NEGATIVE_Y,
        PATTERN_DIRECTION_NEGATIVE_Z,
    }
)
"""The signed global axes accepted by rectangular-pattern creation."""

_PATTERN_DIRECTION_MAPPING: dict[int, dict[str, tuple[str, bool]]] = {
    1: {
        PATTERN_DIRECTION_X: ("XY", True),
        PATTERN_DIRECTION_NEGATIVE_X: ("XY", False),
        PATTERN_DIRECTION_Y: ("YZ", True),
        PATTERN_DIRECTION_NEGATIVE_Y: ("YZ", False),
        PATTERN_DIRECTION_Z: ("ZX", True),
        PATTERN_DIRECTION_NEGATIVE_Z: ("ZX", False),
    },
    2: {
        PATTERN_DIRECTION_X: ("ZX", True),
        PATTERN_DIRECTION_NEGATIVE_X: ("ZX", False),
        PATTERN_DIRECTION_Y: ("XY", True),
        PATTERN_DIRECTION_NEGATIVE_Y: ("XY", False),
        PATTERN_DIRECTION_Z: ("YZ", True),
        PATTERN_DIRECTION_NEGATIVE_Z: ("YZ", False),
    },
}
"""Verified `(origin-plane support, reverse)` mappings by direction slot."""

_PATTERN_COPY_POSITION: int = 1
"""The verified `iShapeToCopyPositionAlongDir*` value for a new pattern."""

_PATTERN_ROTATION_ANGLE: float = 0.0
"""The verified `iRotationAngle` value for a new rectangular pattern."""

FULL_REVOLUTION: float = 360.0
"""The verified default `FirstAngle.Value` (degrees) a new Shaft/Groove is created with."""


def _validate_sections(sections: Any) -> "list[Sketch]":
    """Checks the section sketches of a Multi-sections Solid before CATIA is called.

    Args:
        sections: The caller's sections argument.

    Returns:
        The sections as a list, in the order given.

    Raises:
        ParameterTypeError: If `sections` is not a sequence of `Sketch` objects, holds
            fewer than `MIN_MULTI_SECTION_SECTIONS`, or names the same sketch twice.
    """
    if isinstance(sections, (str, bytes)) or not isinstance(sections, Iterable):
        raise ParameterTypeError(
            "sections must be a sequence of Sketch objects, not "
            f"{type(sections).__name__}."
        )
    section_list = list(sections)
    if len(section_list) < MIN_MULTI_SECTION_SECTIONS:
        raise ParameterTypeError(
            f"A multi-section solid needs at least {MIN_MULTI_SECTION_SECTIONS} sections, "
            f"got {len(section_list)}."
        )
    for position, section in enumerate(section_list, start=1):
        if not isinstance(section, Sketch):
            raise ParameterTypeError(
                f"Section {position} must be a Sketch, not {type(section).__name__}."
            )
    for index, first in enumerate(section_list):
        for second in section_list[index + 1:]:
            if bool(first.com_object == second.com_object):
                raise ParameterTypeError(
                    "The same sketch appears more than once in sections; each section "
                    "must be a different sketch."
                )
    return section_list


def _is_past_last_section(error: pywintypes.com_error) -> bool:
    """Tells whether `GetSectionFromLoft` failed because the rank is past the end.

    Args:
        error: The COM error `GetSectionFromLoft` raised.

    Returns:
        `True` only for the `E_FAIL` CATIA reported for the rank after the last section
        in probe 40. Any other failure is a real error, not the end of the list.
    """
    excepinfo = error.args[2] if len(error.args) > 2 else None
    scode = excepinfo[5] if isinstance(excepinfo, tuple) and len(excepinfo) > 5 else None
    return scode == _E_FAIL


def _scan_shapes(shapes: Any, kind: str) -> "list[Any]":
    """Enumerates a `Shapes` collection and returns the raw items of one kind.

    Shared by every `PartDesign` listing/lookup method so the `Count`/`Item(i)`
    scan and the `type(item).__name__` filter are written once, for both pads
    and pockets.

    Args:
        shapes: The raw CATIA `Shapes` collection (`MainBody.Shapes`).
        kind: The `type(item).__name__` to keep (`PAD_KIND` or `POCKET_KIND`).

    Returns:
        Every raw COM object in `shapes` whose wrapper type matches `kind`,
        in `Item(i)` order.

    Raises:
        Auto3dxError: If the underlying COM call fails unexpectedly.
    """
    try:
        count = shapes.Count
    except pywintypes.com_error as error:
        raise _wrap_com_error(error) from error
    result: list[Any] = []
    for index in range(1, count + 1):
        try:
            item = shapes.Item(index)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        if type(item).__name__ == kind:
            result.append(item)
    return result


def _validate_positive_length(value: float, label: str) -> float:
    """Validates a strictly positive length-like value before a COM call.

    Shared by `create_edge_fillet` (radius) and `create_chamfer` (both
    length arguments), which all need "finite, positive, coerced to float"
    on top of what `validate_length_value` alone enforces (numeric, not a
    `bool`).

    Args:
        value: The candidate value.
        label: What this value represents (e.g. `"radius"`), used only in
            the error message.

    Returns:
        `value` coerced to `float`.

    Raises:
        ParameterTypeError: If `value` is a `bool`, is not an `int`/`float`,
            or is not finite and strictly positive.
    """
    coerced = validate_length_value(value)
    if not math.isfinite(coerced) or coerced <= 0.0:
        raise ParameterTypeError(f"{label} must be finite and positive, not {value!r}.")
    return coerced


def _validate_non_negative_length(value: float, label: str) -> float:
    """Validates a finite, non-negative length-like value before a COM call.

    Shared by `create_shell`'s `external_thickness`, the one argument among
    all the face features whose verified value is zero rather than positive
    (probe 37 used `(face, 2.0, 0.0)`): zero is exactly the value proven to
    create and update successfully, so `_validate_positive_length`'s
    strictly-greater-than-zero rule would be wrong here. A negative value has
    never been tried and is refused for the same reason
    `_validate_positive_length` refuses one -- there is no verified
    justification for accepting it.

    Args:
        value: The candidate value.
        label: What this value represents (e.g. `"external_thickness"`), used
            only in the error message.

    Returns:
        `value` coerced to `float`.

    Raises:
        ParameterTypeError: If `value` is a `bool`, is not an `int`/`float`,
            or is not finite and non-negative.
    """
    coerced = validate_length_value(value)
    if not math.isfinite(coerced) or coerced < 0.0:
        raise ParameterTypeError(f"{label} must be finite and non-negative, not {value!r}.")
    return coerced


_MINIMUM_PATTERN_INSTANCES: int = 2
"""One instance is the seed itself; a pattern needs at least two."""


def _validate_instance_count(instances: Any) -> int:
    """Checks a pattern instance count before CATIA is called.

    Args:
        instances: The count the caller passed.

    Returns:
        The count as an `int`.

    Raises:
        ParameterTypeError: If it is not an integer of at least
            `_MINIMUM_PATTERN_INSTANCES`.
    """
    if isinstance(instances, bool) or not isinstance(instances, int):
        raise ParameterTypeError(
            f"instances must be an int, not {type(instances).__name__}."
        )
    if instances < _MINIMUM_PATTERN_INSTANCES:
        raise ParameterTypeError(
            f"instances must be at least {_MINIMUM_PATTERN_INSTANCES}; got {instances}."
        )
    return instances


class _FeatureActivity:
    """Suppression and reactivation, shared by every Part Design feature wrapper.

    CATIA exposes a feature's suppression as a `BoolParam` named `Activity` inside
    `Part.Parameters`, not as a member of the feature itself: live (probe 44),
    `feature.Activity` does not exist and `feature.GetItem("Activity")` fails, while
    `Parameters.Item("<Part>\\<Body>\\<Feature>\\Activity")` returns the parameter. The
    path is built by walking the feature's own `Parent` chain (`Shapes -> Body -> Bodies
    -> Part`), so a wrapper needs nothing but the feature it holds.

    Suppression is non-destructive: live, deactivating a fillet and rebuilding gave back
    the unfilleted volume with the fillet still in the tree, and reactivating it restored
    the filleted volume exactly.
    """

    _com_object: Any
    _generation: ModelGeneration

    def _activity_parameter(self) -> Any:
        """Finds this feature's `Activity` parameter in the Part.

        Returns:
            The raw `BoolParam`.

        Raises:
            AutomationError: If the feature's Part cannot be reached, or the Part has no
                `Activity` parameter for it.
        """
        body_name: str | None = None
        node = self._com_object
        part = None
        for _ in range(_MAX_OWNER_WALK):
            try:
                node = node.Parent
            except (pywintypes.com_error, AttributeError):
                break
            if node is None:
                break
            if type(node).__name__ == "Body" and body_name is None:
                try:
                    body_name = str(node.Name)
                except (pywintypes.com_error, AttributeError):
                    body_name = None
            if hasattr(node, "Parameters"):
                part = node
                break
        if part is None:
            raise AutomationError(
                "This feature's Part could not be reached, so its Activity parameter "
                "cannot be read. Obtain the feature through part.part_design."
            )
        name = self.name
        try:
            parameters = part.Parameters
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        if body_name is not None:
            try:
                return parameters.Item(
                    f"{part.Name}\\{body_name}\\{name}\\{_ACTIVITY_PARAMETER}"
                )
            except pywintypes.com_error:
                # A differently shaped path (a nested body, a renamed Part) still resolves
                # through the scan below rather than failing here.
                pass
        suffix = f"\\{name}\\{_ACTIVITY_PARAMETER}"
        try:
            count = int(parameters.Count)
            for index in range(1, count + 1):
                candidate = parameters.Item(index)
                if str(candidate.Name).endswith(suffix):
                    return candidate
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        raise AutomationError(
            f"CATIA reports no {_ACTIVITY_PARAMETER} parameter for {name!r}, so this "
            "feature cannot be suppressed through this release."
        )

    @property
    def is_active(self) -> bool:
        """bool: Whether the feature currently contributes to the geometry.

        `False` means it is suppressed: still in the tree, but with no effect until it is
        activated again and the Part is rebuilt.

        Raises:
            AutomationError: If the feature's `Activity` cannot be read.
        """
        try:
            return bool(self._activity_parameter().Value)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def deactivate(self) -> None:
        """Suppresses the feature. Does not rebuild; call `part.update()`.

        The feature stays in the model and keeps its dimensions; only its contribution to
        the geometry stops. Suppressing a feature that later features depend on can make
        the next `Part.Update()` fail (live: suppressing a pad under a fillet did), and
        the repair is to activate it again and update -- not to delete anything
        (`docs/api-design.md` section 6).

        Raises:
            AutomationError: If CATIA refuses the write.
        """
        self._set_activity(False)

    def activate(self) -> None:
        """Un-suppresses the feature. Does not rebuild; call `part.update()`.

        Raises:
            AutomationError: If CATIA refuses the write.
        """
        self._set_activity(True)

    def _set_activity(self, active: bool) -> None:
        """Writes the `Activity` parameter under one model mutation.

        Suppression can change the whole solid, so this advances the model generation and
        every outstanding topology snapshot goes stale (`docs/api-design.md` section 7).

        Args:
            active: The new state.

        Raises:
            AutomationError: If CATIA refuses the write.
        """
        parameter = self._activity_parameter()
        with self._generation.mutation():
            try:
                parameter.Value = active
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error


DIRECTION_ALONG_SKETCH_NORMAL: str = "along_sketch_normal"
"""A pad or pocket that goes the way its sketch plane's normal points.

`DirectionOrientation = catRegularOrientation (0)`. For a sketch on XY that is +Z: a pad
went up and a pocket cut into material above XY (probe 45).
"""

DIRECTION_AGAINST_SKETCH_NORMAL: str = "against_sketch_normal"
"""A pad or pocket that goes against its sketch plane's normal.

`DirectionOrientation = catInverseOrientation (1)`. For a sketch on XY that is -Z.
"""

SUPPORTED_DIRECTIONS: "frozenset[str]" = frozenset(
    {DIRECTION_ALONG_SKETCH_NORMAL, DIRECTION_AGAINST_SKETCH_NORMAL}
)
"""The directions `create_pad`/`create_pocket` and `set_direction` accept."""

_ORIENTATION_BY_DIRECTION: "dict[str, int]" = {
    DIRECTION_ALONG_SKETCH_NORMAL: 0,
    DIRECTION_AGAINST_SKETCH_NORMAL: 1,
}
_DIRECTION_BY_ORIENTATION: "dict[int, str]" = {
    orientation: direction for direction, orientation in _ORIENTATION_BY_DIRECTION.items()
}


def _validate_direction(direction: Any) -> int:
    """Turns a public direction into CATIA's `DirectionOrientation`, before any COM call.

    Raises:
        ParameterTypeError: If `direction` is not one of `SUPPORTED_DIRECTIONS`.
    """
    if direction not in _ORIENTATION_BY_DIRECTION:
        raise ParameterTypeError(
            f"direction must be one of {sorted(SUPPORTED_DIRECTIONS)}, not {direction!r}."
        )
    return _ORIENTATION_BY_DIRECTION[direction]


class SketchFeature(_FeatureActivity):
    """Common wrapper for a sketch-based Part Design feature (`Pad`/`Pocket`).

    Verified structurally identical for both kinds (`docs/conventions.md`
    section 1.2.1): the feature's magnitude is read from and written to
    `FirstLimit.Dimension.Value`, matching the value passed to
    `AddNewPad`/`AddNewPocket` when the feature was created.
    """

    def __init__(
        self, com_object: Any, generation: ModelGeneration | None = None
    ) -> None:
        """Initializes the wrapper.

        Args:
            com_object: The raw CATIA `Pad` or `Pocket` COM object to wrap.
            generation: The owning Part's model generation, advanced by every
                write this wrapper makes. A wrapper built directly from a raw
                COM object gets its own, which nothing else shares.
        """
        self._com_object = com_object
        self._generation = generation if generation is not None else ModelGeneration()

    @property
    def com_object(self) -> Any:
        """Returns the raw underlying COM object.

        This is an escape hatch for callers that need direct COM access, and
        is useful in tests.

        Returns:
            The wrapped raw COM object.
        """
        return self._com_object

    @property
    def name(self) -> str:
        """Returns the feature's name.

        Returns:
            The feature's `Name`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Name
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def depth(self) -> float:
        """Returns the feature's extrusion/removal magnitude.

        Returns:
            `FirstLimit.Dimension.Value`, verified to equal the magnitude
            passed to `AddNewPad`/`AddNewPocket` when the feature was
            created.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.FirstLimit.Dimension.Value
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def set_depth(self, depth: float, unit: str = MILLIMETRE) -> None:
        """Sets the feature's extrusion/removal magnitude.

        Args:
            depth: The new magnitude.
            unit: The unit `depth` is expressed in. Defaults to `MILLIMETRE`.

        Raises:
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `depth` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_length_unit(unit)
        coerced = validate_length_value(depth)
        with self._generation.mutation():
            try:
                self._com_object.FirstLimit.Dimension.Value = coerced
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error

    @property
    def direction(self) -> str:
        """str: Which way the feature goes relative to its sketch plane's normal.

        `DIRECTION_ALONG_SKETCH_NORMAL` or `DIRECTION_AGAINST_SKETCH_NORMAL`, read from
        `DirectionOrientation` (0 or 1). The same mapping held live for a Pad and a Pocket
        (probe 45). Note that CATIA creates a Pocket AGAINST the normal by default and a Pad
        ALONG it.

        Raises:
            AutomationError: If CATIA reports an orientation this SDK does not know.
        """
        try:
            orientation = int(self._com_object.DirectionOrientation)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        if orientation not in _DIRECTION_BY_ORIENTATION:
            raise AutomationError(
                f"DirectionOrientation reported {orientation}, which is not a known direction."
            )
        return _DIRECTION_BY_ORIENTATION[orientation]

    def set_direction(self, direction: str) -> None:
        """Sets which way the feature goes. Does not rebuild; call `part.update()`.

        Live (probe 45): a pocket on XY created with CATIA's default removed nothing from a
        block above XY; setting it `DIRECTION_ALONG_SKETCH_NORMAL` and updating removed
        exactly the expected 502.655 mm3.

        Args:
            direction: `DIRECTION_ALONG_SKETCH_NORMAL` or
                `DIRECTION_AGAINST_SKETCH_NORMAL`.

        Raises:
            ParameterTypeError: If `direction` is not one of those.
            Auto3dxError: If CATIA refuses the write.
        """
        orientation = _validate_direction(direction)
        with self._generation.mutation():
            try:
                self._com_object.DirectionOrientation = orientation
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error

    def reverse_direction(self) -> None:
        """Flips the feature to the other side of its sketch plane. Does not rebuild.

        Raises:
            Auto3dxError: If CATIA refuses the read or the write.
        """
        current = self.direction
        self.set_direction(
            DIRECTION_AGAINST_SKETCH_NORMAL
            if current == DIRECTION_ALONG_SKETCH_NORMAL
            else DIRECTION_ALONG_SKETCH_NORMAL
        )

    def sketch(self) -> Sketch:
        """Returns the sketch this feature was built from.

        Returns:
            A `Sketch` wrapping the feature's `Sketch` property.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return Sketch(self._com_object.Sketch, self._generation)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def depth_parameter(self) -> Parameter:
        """Returns the `Dimension` parameter backing this feature's depth.

        This is the object a `Formula` targets to drive the feature (verified,
        `docs/conventions.md` section 1.2.1): `Parameters.GetNameToUseInRelation`
        on it resolves to `PartBody\\<feature>\\FirstLimit\\Length`.

        Returns:
            A `Parameter` wrapping `FirstLimit.Dimension`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            dimension = self._com_object.FirstLimit.Dimension
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        return Parameter(dimension, self._generation)

    def __repr__(self) -> str:
        """Returns a debugging representation.

        Returns:
            A string such as ``Pad(name='Pad.1', depth=20.0)``.
        """
        try:
            name = self.name
            depth: object = self.depth
        except Auto3dxError:
            name = "<unavailable>"
            depth = "<unavailable>"
        return f"{type(self).__name__}(name={name!r}, depth={depth!r})"


class Pad(SketchFeature):
    """Wraps a raw CATIA `Pad` COM object.

    `height`/`set_height` are the pad's pre-existing public API (covered by
    existing tests and by a live integration test) and must keep working
    exactly as before; both are now thin aliases over
    `SketchFeature.depth`/`set_depth`.
    """

    @property
    def height(self) -> float:
        """Returns the pad's extrusion height.

        Returns:
            `FirstLimit.Dimension.Value`, verified to equal the height passed
            to `AddNewPad` when the pad was created. Same as `depth`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self.depth

    def set_height(self, height: float, unit: str = MILLIMETRE) -> None:
        """Sets the pad's extrusion height.

        Args:
            height: The new height.
            unit: The unit `height` is expressed in. Defaults to `MILLIMETRE`.

        Raises:
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `height` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        self.set_depth(height, unit)


class Pocket(SketchFeature):
    """Wraps a raw CATIA `Pocket` COM object.

    Verified structurally identical to `Pad` (`docs/conventions.md` section
    1.2.1): same readable properties, same `FirstLimit.Dimension.Value`
    semantics. No members beyond `SketchFeature` are needed.
    """


class RevolvedFeature(_FeatureActivity):
    """Common wrapper for a sketch-based revolve feature (`Shaft`/`Groove`).

    Verified structurally identical for both kinds (`docs/conventions.md`
    section 1.2.3): unlike `Pad`/`Pocket`, a revolve feature has no
    `FirstLimit`; instead it exposes `FirstAngle`/`SecondAngle` (`Angle`
    objects, in degrees), defaulting to 360.0/0.0 when the feature is
    created. Creating one requires the sketch to already have `CenterLine`
    set (see `Sketch.set_center_line`) and a profile drawn away from that
    axis; this library cannot verify that requirement ahead of time, so a
    missing or degenerate axis surfaces as whatever `Auto3dxError` the failed
    COM call produces.
    """

    def __init__(
        self, com_object: Any, generation: ModelGeneration | None = None
    ) -> None:
        """Initializes the wrapper.

        Args:
            com_object: The raw CATIA `Shaft` or `Groove` COM object to wrap.
            generation: The owning Part's model generation, advanced by every
                write this wrapper makes. A wrapper built directly from a raw
                COM object gets its own, which nothing else shares.
        """
        self._com_object = com_object
        self._generation = generation if generation is not None else ModelGeneration()

    @property
    def com_object(self) -> Any:
        """Returns the raw underlying COM object.

        This is an escape hatch for callers that need direct COM access, and
        is useful in tests.

        Returns:
            The wrapped raw COM object.
        """
        return self._com_object

    @property
    def name(self) -> str:
        """Returns the feature's name.

        Returns:
            The feature's `Name`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Name
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def first_angle(self) -> float:
        """Returns the feature's first revolve angle.

        Returns:
            `FirstAngle.Value`, in degrees. Verified default `FULL_REVOLUTION`
            (360.0) for a freshly created feature.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.FirstAngle.Value
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @property
    def second_angle(self) -> float:
        """Returns the feature's second revolve angle.

        Returns:
            `SecondAngle.Value`, in degrees. Verified default 0.0 for a
            freshly created feature.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.SecondAngle.Value
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def set_first_angle(self, angle: float, unit: str = DEGREE) -> None:
        """Sets the feature's first revolve angle.

        Args:
            angle: The new angle.
            unit: The unit `angle` is expressed in. Defaults to `DEGREE`.

        Raises:
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `angle` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_angle_unit(unit)
        coerced = validate_angle_value(angle)
        with self._generation.mutation():
            try:
                self._com_object.FirstAngle.Value = coerced
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error

    def set_second_angle(self, angle: float, unit: str = DEGREE) -> None:
        """Sets the feature's second revolve angle.

        Args:
            angle: The new angle.
            unit: The unit `angle` is expressed in. Defaults to `DEGREE`.

        Raises:
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `angle` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_angle_unit(unit)
        coerced = validate_angle_value(angle)
        with self._generation.mutation():
            try:
                self._com_object.SecondAngle.Value = coerced
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error

    def sketch(self) -> Sketch:
        """Returns the sketch this feature was built from.

        Returns:
            A `Sketch` wrapping the feature's `Sketch` property.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return Sketch(self._com_object.Sketch, self._generation)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def first_angle_parameter(self) -> Parameter:
        """Returns the `Angle` parameter backing this feature's first angle.

        This is the object a `Formula` targets to drive the feature, the same
        idea as `SketchFeature.depth_parameter()`.

        Returns:
            A `Parameter` wrapping `FirstAngle`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            angle = self._com_object.FirstAngle
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        return Parameter(angle, self._generation)

    def __repr__(self) -> str:
        """Returns a debugging representation.

        Returns:
            A string such as ``Shaft(name='Shaft.1', first_angle=360.0,
            second_angle=0.0)``.
        """
        try:
            name = self.name
            first_angle: object = self.first_angle
            second_angle: object = self.second_angle
        except Auto3dxError:
            name = "<unavailable>"
            first_angle = "<unavailable>"
            second_angle = "<unavailable>"
        return (
            f"{type(self).__name__}(name={name!r}, first_angle={first_angle!r}, "
            f"second_angle={second_angle!r})"
        )


class Shaft(RevolvedFeature):
    """Wraps a raw CATIA `Shaft` COM object.

    A shaft revolves a sketch profile to add material. No members beyond
    `RevolvedFeature` are needed.
    """


class Groove(RevolvedFeature):
    """Wraps a raw CATIA `Groove` COM object.

    A groove revolves a sketch profile to remove material. No members beyond
    `RevolvedFeature` are needed.
    """


class _NamedFeature(_FeatureActivity):
    """Shared `com_object`/`name`/`__repr__` handling for a plain feature wrapper.

    `Mirror`, `Rib`, and `Slot` carry no depth or angle magnitude the way
    `SketchFeature`/`RevolvedFeature` do, so each reduces to nothing more than
    a raw COM object and its `Name`. Rather than copy that same
    `__init__`/`com_object`/`name`/`com_error`-handling a third and fourth
    time, it lives here once and all three inherit it.
    """

    def __init__(
        self, com_object: Any, generation: ModelGeneration | None = None
    ) -> None:
        """Initializes the wrapper.

        Args:
            com_object: The raw CATIA COM object to wrap.
            generation: The owning Part's model generation, advanced by every
                write this wrapper makes. A wrapper built directly from a raw
                COM object gets its own, which nothing else shares.
        """
        self._com_object = com_object
        self._generation = generation if generation is not None else ModelGeneration()

    @property
    def com_object(self) -> Any:
        """Returns the raw underlying COM object.

        This is an escape hatch for callers that need direct COM access, and
        is useful in tests.

        Returns:
            The wrapped raw COM object.
        """
        return self._com_object

    @property
    def name(self) -> str:
        """Returns the feature's name.

        Returns:
            The feature's `Name`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._com_object.Name
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def _dimension(self, path: "tuple[str, ...]") -> Any:
        """Walks to the CATIA parameter object holding one of this feature's dimensions.

        Args:
            path: The member names to follow from the feature, for example
                `("Radius",)` or `("BottomLimit", "Dimension")`.

        Returns:
            The raw `Length`/`Angle` parameter object, which carries `.Value`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        node = self._com_object
        try:
            for member in path:
                node = getattr(node, member)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        except AttributeError as error:
            raise AutomationError(
                f"{type(self).__name__} exposes no {'.'.join(path)} in this release."
            ) from error
        return node

    def _read_dimension(self, path: "tuple[str, ...]") -> float:
        """Reads one of this feature's dimensions.

        Args:
            path: The member names to follow, as for `_dimension`.

        Returns:
            The parameter's current `Value`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return float(self._dimension(path).Value)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def _write_length(
        self, path: "tuple[str, ...]", value: float, unit: str
    ) -> None:
        """Writes a length dimension, validating exactly as the other setters do.

        The write advances the model generation and does NOT rebuild: `part.update()`
        stays the one place a rebuild happens (`docs/api-design.md` section 6), so a
        caller can change several dimensions and rebuild once.

        Args:
            path: The member names to follow, as for `_dimension`.
            value: The new value.
            unit: The unit `value` is expressed in.

        Raises:
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `value` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If CATIA refuses the write.
        """
        validate_length_unit(unit)
        coerced = validate_length_value(value)
        dimension = self._dimension(path)
        with self._generation.mutation():
            try:
                dimension.Value = coerced
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error

    def _write_angle(self, path: "tuple[str, ...]", value: float, unit: str) -> None:
        """Writes an angle dimension, validating exactly as `set_first_angle` does.

        Args:
            path: The member names to follow, as for `_dimension`.
            value: The new angle.
            unit: The unit `value` is expressed in.

        Raises:
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `value` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If CATIA refuses the write.
        """
        validate_angle_unit(unit)
        coerced = validate_angle_value(value)
        dimension = self._dimension(path)
        with self._generation.mutation():
            try:
                dimension.Value = coerced
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error

    def __repr__(self) -> str:
        """Returns a debugging representation.

        Returns:
            A string such as ``Mirror(name='Mirror.1')``.
        """
        try:
            name = self.name
        except Auto3dxError:
            name = "<unavailable>"
        return f"{type(self).__name__}(name={name!r})"


class Mirror(_NamedFeature):
    """Wraps a raw CATIA `Mirror` COM object.

    Unlike every other feature in this module, a mirror is not built from a
    `Sketch`: `AddNewMirror` takes a plane (verified against
    `OriginElements.PlaneYZ`, `docs/conventions.md` section 1.2.3), so this
    wrapper carries no `sketch()`/`profile()` accessor.
    """


class Rib(_NamedFeature):
    """Wraps a raw CATIA `Rib` COM object.

    A rib sweeps a profile `Sketch` along a path (center curve) `Sketch` to
    add material. Verified against a live session (`docs/conventions.md`
    section 1.2.5, probe 24): `AddNewRib(profile, path)` both created the
    feature and survived `Part.Update()`, with a rectangle profile on the YZ
    plane and a line path on the XY plane. Only the profile sketch can be
    read back (`Rib.Sketch`); there is no verified way to read the path
    sketch, so `Rib` carries no accessor for it.
    """

    def profile(self) -> Sketch:
        """Returns the rib's profile sketch.

        Returns:
            A `Sketch` wrapping the feature's `Sketch` property -- the
            profile passed to `AddNewRib`. The path (center curve) sketch is
            not readable back and so has no accessor here.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return Sketch(self._com_object.Sketch, self._generation)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error


class Slot(_NamedFeature):
    """Wraps a raw CATIA `Slot` COM object.

    The cutting twin of `Rib`: a slot sweeps a profile `Sketch` along a path
    (center curve) `Sketch` to remove material instead of adding it.
    Verified against a live session (`docs/conventions.md` section 1.2.5,
    probe 25): `AddNewSlot(profile, path)` both created the feature and
    survived `Part.Update()`, with the same rectangle-profile-on-YZ /
    line-path-on-XY combination verified for `Rib`. Only the profile sketch
    can be read back (`Slot.Sketch`); there is no verified way to read the
    path sketch, so `Slot` carries no accessor for it, exactly like `Rib`.
    """

    def profile(self) -> Sketch:
        """Returns the slot's profile sketch.

        Returns:
            A `Sketch` wrapping the feature's `Sketch` property -- the
            profile passed to `AddNewSlot`. The path (center curve) sketch is
            not readable back and so has no accessor here.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return Sketch(self._com_object.Sketch, self._generation)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error


class MultiSectionSolid(_NamedFeature):
    """Wraps a raw CATIA `Loft` COM object: a Part Design Multi-sections Solid.

    Verified against a live session (probe 40, `docs/conventions.md` section 1.8):
    `ShapeFactory.AddNewLoft()` creates the feature, its `HybridShape` is a
    `HybridShapeLoft`, and `AddSectionToLoft(Reference, 1, None)` accepts a
    `Part.CreateReferenceFromObject(sketch)` reference for each section. The feature is
    found again by enumerating `MainBody.Shapes`, and its sections can be read back from
    that rediscovered object, so nothing here depends on the wrapper that created it.

    Only the sections are covered. Guides, spine, coupling, closing points, tangency and
    relimitation are neither set by `create_multi_section_solid` nor exposed here.
    """

    def section_names(self) -> "list[str]":
        """Reads the names of this feature's section sketches from the live model.

        Each section is read with `HybridShape.GetSectionFromLoft(rank)`, which returns
        `(Reference, orientation, closing point)`; the reference's `DisplayName` is the
        section sketch's name (probe 40). There is no section-count member, so ranks are
        read from 1 until CATIA reports `E_FAIL`, which is what the rank after the last
        section returned live. Any other failure is raised, not taken as the end.

        Names are returned rather than `Sketch` objects: a reference names a sketch, and
        sketch names are not guaranteed unique, so resolving one is left to
        `part.sketches.get(name)`, which refuses to guess.

        Returns:
            The section sketch names, in section order.

        Raises:
            AutomationError: If the sections cannot be read, a reference has no readable
                name, or CATIA reports more than `_MAX_SECTION_RANK` sections.
        """
        try:
            hybrid_loft = self._com_object.HybridShape
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        names: list[str] = []
        for rank in range(_FIRST_SECTION_RANK, _MAX_SECTION_RANK + 1):
            try:
                section = hybrid_loft.GetSectionFromLoft(rank)
            except pywintypes.com_error as error:
                if rank > _FIRST_SECTION_RANK and _is_past_last_section(error):
                    return names
                raise _wrap_com_error(error) from error
            reference = section[0] if isinstance(section, tuple) else section
            try:
                names.append(str(reference.DisplayName))
            except (AttributeError, pywintypes.com_error) as error:
                raise AutomationError(
                    f"Section {rank} of this multi-section solid has no readable name."
                ) from error
        raise AutomationError(
            f"CATIA reported more than {_MAX_SECTION_RANK} sections for one "
            "multi-section solid; stopped reading rather than guess where they end."
        )


class ConstRadEdgeFillet(_NamedFeature):
    """Wraps a raw CATIA `ConstRadEdgeFillet` COM object.

    Created by `AddNewEdgeFilletWithConstantRadius(edge_reference,
    propagation, radius)` from one edge `Reference` (`geometry.edges.Edge`),
    never a face (`docs/conventions.md` section 1.2.2.2: a face reference is
    rejected by this factory for every propagation mode tried). Reduces to
    nothing more than `com_object`/`name`, exactly like `Mirror`/`Rib`/`Slot`:
    there is no verified way to read the source edge back from a fillet, so
    -- unlike `Pad`/`Shaft`, which can compare their source `Sketch` -- this
    wrapper carries no accessor that could tempt a caller into comparing it
    against a stored `Edge`. See `geometry.edges` for why that also means
    there is no `ensure_edge_fillet`.
    """

    @property
    def radius(self) -> float:
        """float: The fillet radius, read from `Radius.Value`.

        Live (probe 43): reading, writing, `Part.Update()`, the resulting volume change
        and a fresh wrapper all agreed on the new value.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._read_dimension(("Radius",))

    def set_radius(self, radius: float, unit: str = MILLIMETRE) -> None:
        """Sets the radius of this existing fillet.

        Editing beats deleting and recreating: the fillet keeps its identity, so the
        edges it consumes are not re-resolved. This does not rebuild; call
        `part.update()`. If that update fails, put the previous radius back and update
        again rather than removing the fillet (`docs/api-design.md` section 6).

        Args:
            radius: The new radius. Must be finite and positive.
            unit: The unit `radius` is expressed in. Defaults to `MILLIMETRE`.

        Raises:
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `radius` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If CATIA refuses the write.
        """
        self._write_length(("Radius",), radius, unit)

    def radius_parameter(self) -> Parameter:
        """Returns the `Length` parameter backing this fillet's radius.

        This is what a `Formula` drives, the same idea as
        `SketchFeature.depth_parameter()`.

        Returns:
            A `Parameter` wrapping `Radius`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return Parameter(self._dimension(("Radius",)), self._generation)


class Chamfer(_NamedFeature):
    """Wraps a raw CATIA `Chamfer` COM object.

    Created by `AddNewChamfer(edge_reference, propagation, mode, orientation,
    length1, length2_or_angle)` with `mode` always `CHAMFER_MODE_VERIFIED`
    (`docs/conventions.md` section 1.2.2.2): mode 0 creates a feature whose
    `Part.Update()` fails and mode 2 fails at creation, so this library never
    passes either. Reduces to `com_object`/`name` only, for the same reason
    as `ConstRadEdgeFillet`: there is no verified way to read the source edge
    back, so there is no `ensure_chamfer` either (`geometry.edges`).

    `Length1` and `Angle` are editable on an existing chamfer (probe 43). `Length2` is
    readable but CATIA refused every write to it on a chamfer created in the
    length/angle mode this SDK uses, so no setter is exposed for it.
    """

    @property
    def length1(self) -> float:
        """float: The chamfer's first length, read from `Length1.Value`.

        Live (probe 43): read, written (2 -> 5), rebuilt and read back.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._read_dimension(("Length1",))

    def set_length1(self, length: float, unit: str = MILLIMETRE) -> None:
        """Sets the chamfer's first length. Does not rebuild; call `part.update()`.

        Args:
            length: The new length. Must be finite and positive.
            unit: The unit `length` is expressed in. Defaults to `MILLIMETRE`.

        Raises:
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `length` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If CATIA refuses the write.
        """
        self._write_length(("Length1",), length, unit)

    @property
    def angle(self) -> float:
        """float: The chamfer angle in degrees, read from `Angle.Value`.

        Live (probe 43): read, written (45 -> 30), rebuilt and read back.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._read_dimension(("Angle",))

    def set_angle(self, angle: float, unit: str = DEGREE) -> None:
        """Sets the chamfer angle. Does not rebuild; call `part.update()`.

        Args:
            angle: The new angle.
            unit: The unit `angle` is expressed in. Defaults to `DEGREE`.

        Raises:
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `angle` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If CATIA refuses the write.
        """
        self._write_angle(("Angle",), angle, unit)


class Shell(_NamedFeature):
    """Wraps a raw CATIA `Shell` COM object.

    Created by `AddNewShell(face_reference, internal_thickness,
    external_thickness)` from one face `Reference` (`geometry.faces.Face`),
    never an edge -- verified on the first face tried with
    `(face, 2.0, 0.0)` (probe 37, `docs/conventions.md` section 1.2.2.2).
    Reduces to `com_object`/`name` only, for the same reason as
    `ConstRadEdgeFillet`/`Chamfer`: there is no verified way to read the
    source face back, so there is no `ensure_shell` either (`geometry.faces`).
    """

    @property
    def internal_thickness(self) -> float:
        """float: The inward wall thickness, read from `InternalThickness.Value`.

        Live (probe 43): read, written (2 -> 4), rebuilt, read back, volume changed.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._read_dimension(("InternalThickness",))

    def set_internal_thickness(self, thickness: float, unit: str = MILLIMETRE) -> None:
        """Sets the inward wall thickness. Does not rebuild; call `part.update()`.

        Args:
            thickness: The new thickness. Must be finite and positive.
            unit: The unit `thickness` is expressed in. Defaults to `MILLIMETRE`.

        Raises:
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `thickness` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If CATIA refuses the write.
        """
        self._write_length(("InternalThickness",), thickness, unit)

    @property
    def external_thickness(self) -> float:
        """float: The outward wall thickness, read from `ExternalThickness.Value`.

        Live (probe 43): read, written (0 -> 1.5), rebuilt, read back, volume changed.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._read_dimension(("ExternalThickness",))

    def set_external_thickness(self, thickness: float, unit: str = MILLIMETRE) -> None:
        """Sets the outward wall thickness. Does not rebuild; call `part.update()`.

        Args:
            thickness: The new thickness. Must be finite and positive.
            unit: The unit `thickness` is expressed in. Defaults to `MILLIMETRE`.

        Raises:
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `thickness` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If CATIA refuses the write.
        """
        self._write_length(("ExternalThickness",), thickness, unit)


class Thickness(_NamedFeature):
    """Wraps a raw CATIA `Thickness` COM object.

    Created by `AddNewThickness(face_reference, offset)` from one face
    `Reference` (`geometry.faces.Face`) -- verified on the first face tried
    with `(face, 3.0)` (probe 37, `docs/conventions.md` section 1.2.2.2).
    Reduces to `com_object`/`name` only, for the same reason as `Shell`:
    there is no verified way to read the source face back, so there is no
    `ensure_thickness` either (`geometry.faces`).
    """

    @property
    def offset(self) -> float:
        """float: The added material thickness, read from `Offset.Value`.

        CATIA calls this member `Offset`, not `Thickness` (probe 43). Live: read,
        written (3 -> 6), rebuilt, read back, volume 52800 -> 57600 mm3, and a fresh
        wrapper agreed.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._read_dimension(("Offset",))

    def set_offset(self, offset: float, unit: str = MILLIMETRE) -> None:
        """Sets the added material thickness. Does not rebuild; call `part.update()`.

        Args:
            offset: The new thickness. Must be finite and positive.
            unit: The unit `offset` is expressed in. Defaults to `MILLIMETRE`.

        Raises:
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `offset` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If CATIA refuses the write.
        """
        self._write_length(("Offset",), offset, unit)


class Hole(_NamedFeature):
    """Wraps a raw CATIA `Hole` COM object.

    Created by `AddNewHole(face_reference, depth)` from one face `Reference`
    (`geometry.faces.Face`) -- verified on the first face tried with
    `(face, 5.0)` (probe 37, `docs/conventions.md` section 1.2.2.2). Reduces
    to `com_object`/`name` only, for the same reason as `Shell`/`Thickness`:
    there is no verified way to read the source face back, so there is no
    `ensure_hole` either (`geometry.faces`).
    """

    @property
    def diameter(self) -> float:
        """float: The hole diameter, read from `Diameter.Value`.

        Live (probe 43): read, written (10 -> 12), rebuilt, read back, volume changed.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._read_dimension(("Diameter",))

    def set_diameter(self, diameter: float, unit: str = MILLIMETRE) -> None:
        """Sets the hole diameter. Does not rebuild; call `part.update()`.

        Args:
            diameter: The new diameter. Must be finite and positive.
            unit: The unit `diameter` is expressed in. Defaults to `MILLIMETRE`.

        Raises:
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `diameter` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If CATIA refuses the write.
        """
        self._write_length(("Diameter",), diameter, unit)

    @property
    def depth(self) -> float:
        """float: The hole depth, read from `BottomLimit.Dimension.Value`.

        A `Hole` has no `Depth` member; the depth passed to `AddNewHole` lands in the
        bottom limit's dimension (probe 43), which is where this reads and writes. Live:
        read (5), written (12), rebuilt, read back, volume changed, fresh wrapper agreed.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._read_dimension(("BottomLimit", "Dimension"))

    def set_depth(self, depth: float, unit: str = MILLIMETRE) -> None:
        """Sets the hole depth. Does not rebuild; call `part.update()`.

        Args:
            depth: The new depth. Must be finite and positive.
            unit: The unit `depth` is expressed in. Defaults to `MILLIMETRE`.

        Raises:
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `depth` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If CATIA refuses the write.
        """
        self._write_length(("BottomLimit", "Dimension"), depth, unit)


class RectangularPattern:
    """Wraps a raw CATIA `RectPattern` COM object.

    The wrapper intentionally exposes only raw-object identity. There is no
    verified safe name lookup, rename, ensure, or mutation contract, but the
    exact returned wrapper can be deleted with
    :meth:`PartDesign.remove_rectangular_pattern`.
    """

    def __init__(
        self, com_object: Any, generation: ModelGeneration | None = None
    ) -> None:
        """Initializes the wrapper.

        Args:
            com_object: The raw CATIA `RectPattern` COM object to wrap.
            generation: The owning Part's model generation, advanced by every
                write this wrapper makes. A wrapper built directly from a raw
                COM object gets its own, which nothing else shares.
        """
        self._com_object = com_object
        self._generation = generation if generation is not None else ModelGeneration()

    @property
    def com_object(self) -> Any:
        """Returns the raw underlying COM object.

        Returns:
            The wrapped raw COM object.
        """
        return self._com_object

    def __repr__(self) -> str:
        """Returns a debugging representation without unverified COM reads."""
        return "RectangularPattern()"


class CircularPattern(_NamedFeature):
    """Wraps a raw CATIA `CircPattern`: copies of a feature around an axis.

    Created by `AddNewCircPattern` (probe 44) with one radial row, so the pattern is the
    angular one a bolt circle needs. The angular row is exposed because both of its
    parameters were verified end to end: read, written, rebuilt, and the resulting volume
    matched the new instance count.

    Unlike `RectangularPattern`, this one is found again by name in `Body.Shapes`, because
    CATIA reports it there under the `CircPattern` kind.
    """

    @property
    def angular_instances(self) -> int:
        """int: How many instances the pattern makes around the axis, the seed included.

        Read from `AngularRepartition.InstancesCount.Value`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return int(self._read_dimension(("AngularRepartition", "InstancesCount")))

    def set_angular_instances(self, instances: int) -> None:
        """Sets the instance count. Does not rebuild; call `part.update()`.

        Live (probe 44): six instances became eight, the update succeeded and the removed
        volume grew by exactly two more holes.

        Args:
            instances: The new count, at least `_MINIMUM_PATTERN_INSTANCES`.

        Raises:
            ParameterTypeError: If `instances` is not a usable instance count.
            Auto3dxError: If CATIA refuses the write.
        """
        count = _validate_instance_count(instances)
        dimension = self._dimension(("AngularRepartition", "InstancesCount"))
        with self._generation.mutation():
            try:
                dimension.Value = count
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error

    @property
    def angular_spacing_deg(self) -> float:
        """float: The angle between two neighbouring instances, in degrees.

        Read from `AngularRepartition.AngularSpacing.Value`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._read_dimension(("AngularRepartition", "AngularSpacing"))

    def set_angular_spacing_deg(self, spacing: float, unit: str = DEGREE) -> None:
        """Sets the angle between instances. Does not rebuild; call `part.update()`.

        Args:
            spacing: The new angle.
            unit: The unit `spacing` is expressed in. Defaults to `DEGREE`.

        Raises:
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `spacing` is not an `int`/`float` (or is a `bool`).
            Auto3dxError: If CATIA refuses the write.
        """
        self._write_angle(("AngularRepartition", "AngularSpacing"), spacing, unit)

    @property
    def radial_instances(self) -> int:
        """int: The instance count of the radial row, which this SDK always creates as 1.

        Read-only: no radial spacing has been verified, so a radial pattern is not offered
        (`docs/conventions.md` section 1.12).

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return int(self._read_dimension(("RadialRepartition", "InstancesCount")))


class BooleanOperation(_NamedFeature):
    """Wraps a raw CATIA boolean feature: `Remove`, `Add`, `Intersect` or `Assemble`.

    A boolean takes one tool body and applies it to the body being modelled in. All four
    were verified live (probe 44) with exact volumes on a disc and a cylinder:

        Remove     111966.36 -> 104897.78   (the 7068.58 overlap taken away)
        Add        111966.36 -> 133172.11   (the 21205.75 outside the disc added)
        Intersect  111966.36 ->   7068.58   (only the overlap left)
        Assemble   111966.36 -> 133172.11   (same as Add for these two solids)

    **The tool body is consumed.** After the operation it reports `InBooleanOperation` and
    no longer appears in `part.bodies`; it lives under the boolean feature instead. That is
    why `tool_body_name` is read from the feature rather than from the body collection, and
    why removal needs `delete_consumed_body=True` (`PartDesign.remove_boolean`).
    """

    @property
    def operation(self) -> str:
        """str: Which boolean this is: `"Remove"`, `"Add"`, `"Intersect"` or `"Assemble"`.

        Taken from the COM wrapper's type name, the same way every other kind in this
        module is identified.
        """
        return type(self._com_object).__name__

    @property
    def tool_body_name(self) -> str:
        """str: The name of the body this operation consumed.

        Read from the feature's own `Body` member (probe 44), so it survives into any
        other process: the body itself is no longer listed in `part.bodies`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return str(self._com_object.Body.Name)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def __repr__(self) -> str:
        """str: Debug representation naming the operation and its tool body."""
        try:
            name = self.name
            tool: object = self.tool_body_name
        except Auto3dxError:
            name = "<unavailable>"
            tool = "<unavailable>"
        return f"{type(self).__name__}(name={name!r}, tool_body_name={tool!r})"


WORK_AT_FEATURES: tuple = (
    SketchFeature,
    RevolvedFeature,
    _NamedFeature,
)
"""The feature wrappers `Part.work_at` accepts as an In-Work Object target.

Every Part Design feature this SDK creates is one of these three families, so this
covers pads, pockets, shafts, grooves, mirrors, ribs, slots, multi-section solids,
fillets, chamfers, shells, thicknesses and holes. A raw COM object is deliberately not
accepted: a wrapper is what `Part` can check for ownership.
"""


class PartDesign:
    """Wraps Part Design features on a Part's `MainBody`.

    Pads, pockets, shafts, grooves, mirrors, ribs, and slots are all read
    from `part_com_object.MainBody.Shapes`, filtered by
    `type(item).__name__` (`PAD_KIND`/`POCKET_KIND`/`SHAFT_KIND`/
    `GROOVE_KIND`/`MIRROR_KIND`/`RIB_KIND`/`SLOT_KIND`), and created through
    the matching `part_com_object.ShapeFactory.AddNew*` method. All seven
    families share identical policy (existence/ambiguity checks by
    enumeration, partial-creation reporting on a failed rename, deletion via
    selection); that shared behaviour is factored into the private
    `_list`/`_get`/`_create_feature`/`_ensure_by_sketch`/`_remove` helpers
    below, parameterised by kind. Pad/Pocket additionally compare and (in
    `ensure_*`) synchronise a `depth`/`height` magnitude, which
    Shaft/Groove/Mirror/Rib/Slot do not have; `_create`/`_ensure` layer that
    length-specific validation on top of the shared core for Pad/Pocket only.
    Rib/Slot reuse `_ensure_by_sketch` like Pad/Pocket/Shaft/Groove, but pass
    a `sketch_of` accessor because their sketch getter is named `profile()`
    rather than `sketch()`.

    Rectangular patterns are different: only creation and exact-wrapper
    cleanup are verified. They are not scanned or looked up by name.

    Edge fillets and chamfers (`ConstRadEdgeFillet`/`Chamfer`) are read and
    created the same way -- `_list`/`_get`/`_create_feature`/`_remove` with
    `EDGE_FILLET_KIND`/`CHAMFER_KIND` -- but they take an edge `Reference`
    (`geometry.edges.Edge`) instead of a `Sketch`, obtained through
    `part.topology.edges()`. There is no `ensure_edge_fillet`/`ensure_chamfer`:
    unlike a `Sketch`, an edge has no verified, stable handle a caller can
    read back and compare, so `_ensure_by_sketch` does not apply and no
    truthful substitute exists (`geometry.edges` explains why in full).

    Shells, thicknesses, and holes (`Shell`/`Thickness`/`Hole`) are the face
    counterpart, read and created the same way -- `_list`/`_get`/
    `_create_feature`/`_remove` with `SHELL_KIND`/`THICKNESS_KIND`/
    `HOLE_KIND` -- but they take a face `Reference` (`geometry.faces.Face`)
    obtained through `part.topology.faces()`. `_require_current_face` mirrors
    `_require_current_edge` exactly, and both share the one `_generation`
    counter and the one `StaleSnapshotError`: a face reference and an
    edge reference go stale for the same reason (a model change may or may
    not have left the underlying topology intact), so this is one condition
    with two producers, not two conditions. There is no
    `ensure_shell`/`ensure_thickness`/`ensure_hole`, for the same reason
    there is no `ensure_edge_fillet`/`ensure_chamfer` (`geometry.faces`
    explains why in full).
    """

    def __init__(
        self,
        part_com_object: Any,
        selection: Any = None,
        generation: ModelGeneration | None = None,
        body_target: Any = None,
        in_work_target: Any = None,
    ) -> None:
        """Initializes the wrapper.

        Args:
            part_com_object: The raw CATIA `Part` COM object. Both
                `MainBody.Shapes` (for existing features) and `ShapeFactory`
                (for creating new ones) are read from it. `OriginElements` is
                also read from it, for `create_mirror`'s plane lookup.
            selection: The raw CATIA `Selection` COM object from the editor.
                Required only by the `remove_*` methods, because `Shapes` has
                no `Remove` method and deletion has to go through the
                editor's selection. Reading and creating work without it.
            generation: The owning Part's model generation. A standalone
                instance gets its own, which no other wrapper shares; obtain
                `PartDesign` from a `Part` instead.
            body_target: A callable returning the raw `Body` of an enclosing
                `part.work_in(body)`, or `None` outside one. Supplied by `Part`; without
                it everything works on the main body exactly as before. It decides which
                body features are listed and looked up in.
            in_work_target: A callable returning the raw object the innermost
                `part.work_in(body)`/`part.work_at(feature)` block targets, or `None`
                outside one. It decides what the In-Work Object is set to before each
                creation: a body appends to that body, a feature inserts right after that
                feature (probe 43). Defaults to following `body_target`.
        """
        self._part_com_object = part_com_object
        self._selection = selection
        self._body_target = body_target
        self._in_work_target = in_work_target
        # Shared with the owning Part and everything else reachable from it
        # (`docs/api-design.md` section 5). Every mutation here advances it, and
        # every edge or face handle is checked against it before reaching CATIA.
        self._generation = generation if generation is not None else ModelGeneration()

    @property
    def snapshot_generation(self) -> int:
        """int: The owning Part's current model generation.

        A topology snapshot is stamped with this value when it is taken, and is
        refused once the two no longer agree. Exposed so a caller can tell
        whether a snapshot it is holding is still current without having to
        catch `StaleSnapshotError`.
        """
        return self._generation.value

    def _require_current_edge(self, edge: Edge, noun: str) -> None:
        """Refuses an `Edge` whose snapshot predates the latest model change.

        Args:
            edge: The edge the caller passed.
            noun: What is being created, for the error message.

        Raises:
            StaleSnapshotError: If the edge came from a snapshot taken
                before this `PartDesign` last changed the model.
        """
        self._generation.require_current(edge.generation, "edge", "part.topology.edges()")
        self._require_same_body(edge, "edge", noun, "part.topology.edges(body=...)")

    def _require_current_face(self, face: Face, noun: str) -> None:
        """Refuses a `Face` whose snapshot predates the latest model change.

        Mirrors `_require_current_edge` exactly and reuses
        `StaleSnapshotError` rather than adding a new one: a face
        reference and an edge reference go stale under a model change for
        the same reason (`geometry.faces`), so this is the same condition,
        not a new one -- even though the error's name and docstring are
        worded for edges specifically (see the module report for whether it
        should be renamed).

        Args:
            face: The face the caller passed.
            noun: What is being created, for the error message.

        Raises:
            StaleSnapshotError: If the face came from a snapshot taken
                before this `PartDesign` last changed the model.
        """
        self._generation.require_current(face.generation, "face", "part.topology.faces()")
        self._require_same_body(face, "face", noun, "part.topology.faces(body=...)")

    def _require_same_body(
        self, reference: Any, kind: str, noun: str, remedy: str
    ) -> None:
        """Refuses topology that belongs to a different body from the target one.

        A Part-wide search returns every body's edges and faces in one list
        (`geometry.edges`), and CATIA accepts a feature built on the wrong body's
        reference, only failing the next `Part.Update()`. The reference carries the body
        it was found in, read from the model at snapshot time, so the mismatch is caught
        before `ShapeFactory` is called and nothing is created.

        An unknown owner is allowed through: CATIA did not say which body the reference
        belongs to, and refusing on a missing answer would break valid calls. That is the
        one gap in this guard, and `docs/api-design.md` section 7 records it.

        Args:
            reference: The `Edge` or `Face` the caller passed.
            kind: `"edge"` or `"face"`, for the message.
            noun: What is being created, for the message.
            remedy: The call that would produce a correctly scoped snapshot.

        Raises:
            CrossBodyReferenceError: If the reference's body is not the body this
                `PartDesign` builds in. Nothing was changed.
        """
        owner = reference.owner_body
        if owner is None:
            return
        target = self._body()
        try:
            same = bool(owner == target)
        except pywintypes.com_error:
            # Identity could not be compared; the guard stays silent rather than
            # refusing a call CATIA might well accept.
            return
        if same:
            return
        try:
            target_name = str(target.Name)
        except (pywintypes.com_error, AttributeError):
            target_name = "the target body"
        owner_name = reference.owner_body_name or "another body"
        feature = reference.owner_feature_name
        origin = f" (from {feature!r})" if feature else ""
        raise CrossBodyReferenceError(
            f"This {kind}{origin} belongs to body {owner_name!r}, but the {noun} would "
            f"be created in {target_name!r}. CATIA would accept that and fail the next "
            f"Part.Update(). Nothing was changed: take {remedy} for the body you are "
            "building in, or open part.work_in(body) for the body that owns this "
            f"{kind}."
        )

    def _body(self) -> Any:
        """Returns the raw body features are listed in: the work body, or `MainBody`.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        target = self._body_target() if self._body_target is not None else None
        if target is not None:
            return target
        try:
            return self._part_com_object.MainBody
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def _target_in_work(self) -> None:
        """Makes the current work target the In-Work Object before a feature is created.

        Only inside `part.work_in(body)` or `part.work_at(feature)`. `ShapeFactory` builds
        in the In-Work Object (probe 41), and creating a feature or a plane moves it, so it
        is set again before every creation rather than once when the context opens. With a
        body in work the feature is appended to that body; with a feature in work CATIA
        inserts the new feature immediately after it (probe 43). Outside a context nothing
        is touched, exactly as before.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        if self._in_work_target is not None:
            target = self._in_work_target()
        else:
            target = self._body_target() if self._body_target is not None else None
        if target is None:
            return
        try:
            self._part_com_object.InWorkObject = target
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def _shapes(self) -> Any:
        """Returns the raw `MainBody.Shapes` collection.

        Returns:
            The raw CATIA `Shapes` collection.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            return self._body().Shapes
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    def _list(self, kind: str, wrapper_cls: type) -> "list[Any]":
        """Lists every feature of one kind on the Part's `MainBody`.

        Args:
            kind: `PAD_KIND`, `POCKET_KIND`, `SHAFT_KIND`, `GROOVE_KIND`, or
                `MIRROR_KIND`.
            wrapper_cls: `Pad`, `Pocket`, `Shaft`, `Groove`, or `Mirror`.

        Returns:
            A `wrapper_cls` instance for each matching item in
            `MainBody.Shapes`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return [
            wrapper_cls(item, self._generation)
            for item in _scan_shapes(self._shapes(), kind)
        ]

    def _get(self, kind: str, wrapper_cls: type, noun: str, name: str) -> Any:
        """Looks up a feature of one kind by name.

        Names are not guaranteed unique (CATIA does not enforce it for
        sketches, and features carry no stronger guarantee), so every
        matching feature is enumerated and the match count decides the
        outcome rather than returning on the first hit.

        Args:
            kind: `PAD_KIND`, `POCKET_KIND`, `SHAFT_KIND`, `GROOVE_KIND`, or
                `MIRROR_KIND`.
            wrapper_cls: `Pad`, `Pocket`, `Shaft`, `Groove`, or `Mirror`.
            noun: `"pad"`, `"pocket"`, `"shaft"`, `"groove"`, or `"mirror"`,
                used only in error messages.
            name: The feature's name.

        Returns:
            The matching `wrapper_cls` instance.

        Raises:
            FeatureNotFoundError: If no matching feature named `name` exists.
            AmbiguousNameError: If two or more matching features named `name`
                exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        matches = [feature for feature in self._list(kind, wrapper_cls) if feature.name == name]
        if not matches:
            raise FeatureNotFoundError(f"No {noun} named {name!r} was found.")
        if len(matches) > 1:
            raise AmbiguousNameError(
                f"{len(matches)} {noun}s named {name!r} exist; a name-based "
                "lookup cannot safely pick one."
            )
        return matches[0]

    def _create(
        self,
        name: str,
        sketch: Sketch,
        depth: float,
        unit: str,
        kind: str,
        factory_method: str,
        wrapper_cls: type,
        noun: str,
        direction: "str | None" = None,
    ) -> Any:
        """Creates a new sketch-based feature with a length magnitude (Pad/Pocket).

        Validates and coerces the length-specific arguments, then delegates
        the existence check, the factory call, and the rename/`PartialCreationError`
        handling to `_create_feature`.

        Args:
            name: The new feature's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            sketch: The `Sketch` to build the feature from.
            depth: The feature's magnitude (height for a pad, depth for a
                pocket).
            unit: The unit `depth` is expressed in.
            kind: `PAD_KIND` or `POCKET_KIND`, used for the pre-create
                duplicate check.
            factory_method: `"AddNewPad"` or `"AddNewPocket"`.
            wrapper_cls: `Pad` or `Pocket`.
            noun: `"pad"` or `"pocket"`, used only in error messages.

        Returns:
            The newly created `wrapper_cls` instance, already renamed to
            `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `depth` is not an `int`/`float` (or is a `bool`).
            FeatureConflictError: If a feature named `name` already exists.
            AmbiguousNameError: If two or more features named `name` already
                exist.
            PartialCreationError: If the feature was created but the
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        validate_length_unit(unit)
        coerced = validate_length_value(depth)
        configure = None
        if direction is not None:
            orientation = _validate_direction(direction)

            def configure(feature: Any) -> None:
                feature.DirectionOrientation = orientation

        return self._create_feature(
            name,
            kind,
            factory_method,
            (sketch.com_object, coerced),
            wrapper_cls,
            noun,
            configure,
        )

    def _create_feature(
        self,
        name: str,
        kind: str,
        factory_method: str,
        factory_args: "tuple[Any, ...]",
        wrapper_cls: type,
        noun: str,
        configure: Any = None,
    ) -> Any:
        """Creates a new Part Design feature through `ShapeFactory`.

        This is the part of feature creation that every kind shares: the
        pre-create existence check (mirroring the duplicate-name guards used
        elsewhere in this library), the `AddNew*` call, and the follow-up
        rename with `PartialCreationError` reporting on failure. Callers
        validate and assemble their own `factory_args` first -- this method
        does not know or care whether a magnitude is involved.

        Args:
            name: The new feature's name. Must already be validated by the
                caller (via `validate_parameter_name`).
            kind: `PAD_KIND`, `POCKET_KIND`, `SHAFT_KIND`, `GROOVE_KIND`, or
                `MIRROR_KIND`, used for the pre-create duplicate check.
            factory_method: The `ShapeFactory` method name, e.g.
                `"AddNewPad"`.
            factory_args: The positional arguments to pass to that method
                (already validated/coerced raw COM values, never wrapper
                objects).
            configure: Optional step that finishes building the feature after it
                is renamed, given its raw COM object. A Multi-sections Solid adds
                its sections here, because `AddNewLoft` takes no arguments. A COM
                failure inside it raises `PartialCreationError`: by then the
                feature exists under `name` and can be removed by name.
            wrapper_cls: `Pad`, `Pocket`, `Shaft`, `Groove`, or `Mirror`.
            noun: `"pad"`, `"pocket"`, `"shaft"`, `"groove"`, or `"mirror"`,
                used only in error messages.

        Returns:
            The newly created `wrapper_cls` instance, already renamed to
            `name`.

        Raises:
            FeatureConflictError: If a feature named `name` already exists.
            AmbiguousNameError: If two or more features named `name` already
                exist.
            PartialCreationError: If the feature was created but the
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        try:
            self._get(kind, wrapper_cls, noun, name)
        except FeatureNotFoundError:
            pass
        else:
            raise FeatureConflictError(f"A {noun} named {name!r} already exists.")

        # The generation advances once this block is attempted, even when it
        # raises: AddNew* can create the feature and then fail the rename, which
        # leaves it in the tree (`docs/api-design.md` section 5.3).
        with self._generation.mutation():
            self._target_in_work()
            try:
                factory = getattr(self._part_com_object.ShapeFactory, factory_method)
                com_object = factory(*factory_args)
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error
            feature = wrapper_cls(com_object, self._generation)
            # A failed rename leaves a default-named feature behind rather than
            # rolling back: deleting a pad or pocket cascade-deletes its sketch,
            # which makes automatic rollback more dangerous than reporting.
            try:
                feature.com_object.Name = name
            except pywintypes.com_error as error:
                try:
                    actual_name = feature.name
                except Auto3dxError:
                    actual_name = "unknown"
                raise PartialCreationError(
                    f"Created a {noun} but failed to rename it to {name!r}; it "
                    f"currently exists in the model as {actual_name!r}. Do not "
                    f"retry blindly: retrying would create another {noun} instead "
                    "of fixing this one."
                ) from error
            if configure is not None:
                try:
                    configure(feature.com_object)
                except pywintypes.com_error as error:
                    raise PartialCreationError(
                        f"Created a {noun} named {name!r} but could not finish "
                        "building it. It is in the model under that name; remove it "
                        "before retrying."
                    ) from error
        return feature

    def _ensure(
        self,
        name: str,
        sketch: Sketch,
        depth: float,
        unit: str,
        get_method: Any,
        create_method: Any,
        noun: str,
    ) -> Any:
        """Creates a feature, or reuses/updates it if one with the same name exists.

        Policy (see `docs/conventions.md` section 1.3):
            - No matching feature named `name` exists: create it.
            - A matching feature named `name` exists on the same sketch and
              the same depth: reuse it unchanged.
            - A matching feature named `name` exists on the same sketch but a
              different depth: update `FirstLimit.Dimension.Value` to `depth`.
            - A matching feature named `name` exists on a different sketch:
              raise `FeatureConflictError`.

        Validates and coerces the length-specific arguments, then delegates
        the existence/sketch-identity check to `_ensure_by_sketch`, passing a
        `sync_existing` callback that performs the depth comparison/update.

        Args:
            name: The feature's name.
            sketch: The `Sketch` the feature must be built from.
            depth: The feature's magnitude.
            unit: The unit `depth` is expressed in.
            get_method: `self.get_pad` or `self.get_pocket`.
            create_method: `self.create_pad` or `self.create_pocket`.
            noun: `"pad"` or `"pocket"`, used only in error messages.

        Returns:
            The existing (possibly updated) or newly created feature.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `depth` is not an `int`/`float` (or is a `bool`).
            AmbiguousNameError: If two or more matching features named `name`
                already exist.
            FeatureConflictError: If a matching feature named `name` already
                exists on a different sketch.
            PartialCreationError: If a new feature had to be created and its
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        validate_length_unit(unit)
        coerced = validate_length_value(depth)

        def sync_existing(existing: Any) -> None:
            if not math.isclose(existing.depth, coerced, rel_tol=0.0, abs_tol=LENGTH_TOLERANCE):
                existing.set_depth(depth, unit)

        return self._ensure_by_sketch(
            name,
            sketch,
            get_method,
            lambda: create_method(name, sketch, depth, unit),
            noun,
            sync_existing,
        )

    def _ensure_by_sketch(
        self,
        name: str,
        sketch: Sketch,
        get_method: Any,
        create: Any,
        noun: str,
        sync_existing: Any = None,
        sketch_of: Any = None,
    ) -> Any:
        """Reuses an existing sketch-based feature by name, or creates one.

        This is the part every `ensure_*` shares: look the feature up by
        name, create it if absent, and otherwise verify it was built from the
        same sketch before reusing it. "Same sketch" is judged by COM
        identity (`==` on the raw `Sketch` objects), not by name: names are
        writable and CATIA does not reject a duplicate, so a name match alone
        would be forgeable.

        Args:
            name: The feature's name.
            sketch: The `Sketch` the feature must be built from.
            get_method: `self.get_pad`, `self.get_pocket`, `self.get_shaft`,
                `self.get_groove`, `self.get_rib`, or `self.get_slot`.
            create: A zero-argument callable that creates and returns the new
                feature when none exists yet.
            noun: `"pad"`, `"pocket"`, `"shaft"`, `"groove"`, `"rib"`, or
                `"slot"`, used only in error messages.
            sync_existing: An optional callable invoked with the existing
                feature when one is found on the same sketch, for kinds that
                need to reconcile a magnitude (Pad/Pocket depth). `None`
                (the default) leaves an existing match untouched, which is
                the required policy for Shaft/Groove/Rib/Slot: their
                angles/paths are only ever changed by an explicit call (or,
                for a Rib/Slot path, not comparable at all), never implicitly
                by `ensure_*`.
            sketch_of: An optional callable taking the existing feature and
                returning the `Sketch` to compare against `sketch`. Defaults
                to `lambda feature: feature.sketch()`, which is right for
                Pad/Pocket/Shaft/Groove; `Rib`/`Slot` pass
                `lambda feature: feature.profile()` instead, since their
                accessor is named `profile()` rather than `sketch()`.

        Returns:
            The existing (possibly synchronised) or newly created feature.

        Raises:
            FeatureConflictError: If a matching feature named `name` already
                exists on a different sketch.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        def _default_sketch_of(feature: Any) -> Sketch:
            return feature.sketch()

        if sketch_of is None:
            sketch_of = _default_sketch_of

        try:
            existing = get_method(name)
        except FeatureNotFoundError:
            return create()

        try:
            existing_sketch = sketch_of(existing)
            same_sketch = existing_sketch.com_object == sketch.com_object
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        if not same_sketch:
            raise FeatureConflictError(
                f"{noun.capitalize()} {name!r} already exists on a different "
                f"sketch ({existing_sketch.name!r} instead of {sketch.name!r})."
            )

        if sync_existing is not None:
            sync_existing(existing)
        return existing

    def _remove(self, name: str, get_method: Any, noun: str) -> None:
        """Removes a feature from the model.

        `Shapes` exposes no `Remove` method, so deletion goes through the
        editor's `Selection`. That means this method needs the `selection`
        the wrapper was constructed with; obtain the Part via
        `Catia.active_part()` to get one wired in.

        The feature is looked up first so a missing name is reported as
        `FeatureNotFoundError`. Removing a pad/pocket cascade-deletes its
        sketch (verified in `docs/conventions.md` section 1.2), so a
        following `SketchCollection.remove` for that sketch will legitimately
        fail.

        This deletes model content. It does not call `Part.Update()`, and it
        never saves.

        Args:
            name: The feature's name.
            get_method: `self.get_pad`, `self.get_pocket`, `self.get_shaft`,
                `self.get_groove`, or `self.get_mirror`.
            noun: `"pad"`, `"pocket"`, `"shaft"`, `"groove"`, or `"mirror"`,
                used only in the deletion's error message.

        Raises:
            FeatureNotFoundError: If no matching feature named `name` exists.
            Auto3dxError: If no editor selection is available, or the
                deletion failed.
        """
        target = get_method(name)
        with self._generation.mutation():
            delete_via_selection(
                self._selection, target.com_object, f"{noun} {name!r}", self._part_com_object
            )

    @property
    def pads(self) -> "list[Pad]":
        """Lists every pad on the Part's `MainBody`.

        Returns:
            A `Pad` wrapper for each item in `MainBody.Shapes` whose wrapper
            type is `PAD_KIND`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._list(PAD_KIND, Pad)

    def get_pad(self, name: str) -> Pad:
        """Looks up a pad by name.

        Args:
            name: The pad's name.

        Returns:
            The matching `Pad`.

        Raises:
            FeatureNotFoundError: If no pad named `name` exists.
            AmbiguousNameError: If two or more pads named `name` exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._get(PAD_KIND, Pad, "pad", name)

    def create_pad(
        self,
        name: str,
        sketch: Sketch,
        height: float,
        unit: str = MILLIMETRE,
        direction: "str | None" = None,
    ) -> Pad:
        """Creates a new pad extruding `sketch` by `height`.

        Args:
            name: The new pad's name. Must be non-empty, without surrounding
                whitespace, and must not contain `"\\"`.
            sketch: The `Sketch` to extrude.
            height: The extrusion height.
            unit: The unit `height` is expressed in. Defaults to `MILLIMETRE`.
            direction: `DIRECTION_ALONG_SKETCH_NORMAL` or
                `DIRECTION_AGAINST_SKETCH_NORMAL`, set right after creation. `None` (the
                default) keeps CATIA's own default, which for a pad is along the normal.

        Returns:
            The newly created `Pad`, already renamed to `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `height` is not an `int`/`float` (or is a `bool`).
            FeatureConflictError: If a pad named `name` already exists.
            AmbiguousNameError: If two or more pads named `name` already exist.
            PartialCreationError: If the pad was created but the follow-up
                rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._create(
            name, sketch, height, unit, PAD_KIND, "AddNewPad", Pad, "pad", direction
        )

    def ensure_pad(
        self,
        name: str,
        sketch: Sketch,
        height: float,
        unit: str = MILLIMETRE,
    ) -> Pad:
        """Creates a pad, or reuses/updates it if one with the same name exists.

        See `docs/conventions.md` section 1.3 for the full policy.

        Args:
            name: The pad's name.
            sketch: The `Sketch` the pad must extrude.
            height: The extrusion height.
            unit: The unit `height` is expressed in. Defaults to `MILLIMETRE`.

        Returns:
            The existing (possibly updated) or newly created `Pad`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `height` is not an `int`/`float` (or is a `bool`).
            AmbiguousNameError: If two or more pads named `name` already exist.
            FeatureConflictError: If a pad named `name` already exists on a
                different sketch.
            PartialCreationError: If a new pad had to be created and its
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._ensure(name, sketch, height, unit, self.get_pad, self.create_pad, "pad")

    def remove_pad(self, name: str) -> None:
        """Removes a pad from the model.

        Args:
            name: The pad's name.

        Raises:
            FeatureNotFoundError: If no pad named `name` exists.
            Auto3dxError: If no editor selection is available, or the deletion
                failed.
        """
        self._remove(name, self.get_pad, "pad")

    @property
    def pockets(self) -> "list[Pocket]":
        """Lists every pocket on the Part's `MainBody`.

        Returns:
            A `Pocket` wrapper for each item in `MainBody.Shapes` whose
            wrapper type is `POCKET_KIND`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._list(POCKET_KIND, Pocket)

    def get_pocket(self, name: str) -> Pocket:
        """Looks up a pocket by name.

        Args:
            name: The pocket's name.

        Returns:
            The matching `Pocket`.

        Raises:
            FeatureNotFoundError: If no pocket named `name` exists.
            AmbiguousNameError: If two or more pockets named `name` exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._get(POCKET_KIND, Pocket, "pocket", name)

    def create_pocket(
        self,
        name: str,
        sketch: Sketch,
        depth: float,
        unit: str = MILLIMETRE,
        direction: "str | None" = None,
    ) -> Pocket:
        """Creates a new pocket removing material along `sketch` by `depth`.

        Args:
            name: The new pocket's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            sketch: The `Sketch` to cut along.
            depth: The removal depth.
            unit: The unit `depth` is expressed in. Defaults to `MILLIMETRE`.
            direction: `DIRECTION_ALONG_SKETCH_NORMAL` or
                `DIRECTION_AGAINST_SKETCH_NORMAL`, set right after creation. `None` (the
                default) keeps CATIA's own default, which for a pocket is AGAINST the
                normal. **A pocket that cuts the wrong way still creates and updates,
                removing nothing** (probe 45): measure the volume before and after to
                confirm a cut.

        Returns:
            The newly created `Pocket`, already renamed to `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `depth` is not an `int`/`float` (or is a `bool`).
            FeatureConflictError: If a pocket named `name` already exists.
            AmbiguousNameError: If two or more pockets named `name` already
                exist.
            PartialCreationError: If the pocket was created but the follow-up
                rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._create(
            name,
            sketch,
            depth,
            unit,
            POCKET_KIND,
            "AddNewPocket",
            Pocket,
            "pocket",
            direction,
        )

    def ensure_pocket(
        self,
        name: str,
        sketch: Sketch,
        depth: float,
        unit: str = MILLIMETRE,
    ) -> Pocket:
        """Creates a pocket, or reuses/updates it if one with the same name exists.

        Policy identical to `ensure_pad` (`docs/conventions.md` section 1.3),
        applied to pockets.

        Args:
            name: The pocket's name.
            sketch: The `Sketch` the pocket must be built from.
            depth: The removal depth.
            unit: The unit `depth` is expressed in. Defaults to `MILLIMETRE`.

        Returns:
            The existing (possibly updated) or newly created `Pocket`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            UnsupportedUnitError: If `unit` is not a supported unit.
            ParameterTypeError: If `depth` is not an `int`/`float` (or is a `bool`).
            AmbiguousNameError: If two or more pockets named `name` already
                exist.
            FeatureConflictError: If a pocket named `name` already exists on a
                different sketch.
            PartialCreationError: If a new pocket had to be created and its
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._ensure(
            name, sketch, depth, unit, self.get_pocket, self.create_pocket, "pocket"
        )

    def remove_pocket(self, name: str) -> None:
        """Removes a pocket from the model.

        Args:
            name: The pocket's name.

        Raises:
            FeatureNotFoundError: If no pocket named `name` exists.
            Auto3dxError: If no editor selection is available, or the deletion
                failed.
        """
        self._remove(name, self.get_pocket, "pocket")

    @property
    def shafts(self) -> "list[Shaft]":
        """Lists every shaft on the Part's `MainBody`.

        Returns:
            A `Shaft` wrapper for each item in `MainBody.Shapes` whose
            wrapper type is `SHAFT_KIND`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._list(SHAFT_KIND, Shaft)

    def get_shaft(self, name: str) -> Shaft:
        """Looks up a shaft by name.

        Args:
            name: The shaft's name.

        Returns:
            The matching `Shaft`.

        Raises:
            FeatureNotFoundError: If no shaft named `name` exists.
            AmbiguousNameError: If two or more shafts named `name` exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._get(SHAFT_KIND, Shaft, "shaft", name)

    def create_shaft(self, name: str, sketch: Sketch) -> Shaft:
        """Creates a new shaft revolving `sketch`.

        `sketch` must already have `CenterLine` set (`Sketch.set_center_line`)
        with a profile drawn away from that axis (`docs/conventions.md`
        section 1.2.3); this library cannot verify that requirement ahead of
        time, so a missing or unusable axis surfaces as whatever error the
        failed `AddNewShaft` call produces. The new shaft is created with the
        verified defaults `FirstAngle.Value == FULL_REVOLUTION` (360.0) and
        `SecondAngle.Value == 0.0`; call `set_first_angle`/`set_second_angle`
        afterward to change them.

        A successful call here does not mean the feature is valid
        (`docs/conventions.md` section 1.2.2.1): this method never calls
        `Part.Update()`. The caller must call it and handle `PartUpdateError`;
        if the update fails, the shaft is left in the model and the caller
        must remove it (`remove_shaft`) rather than retrying blindly.

        Args:
            name: The new shaft's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            sketch: The `Sketch` to revolve. Must have `CenterLine` set.

        Returns:
            The newly created `Shaft`, already renamed to `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            FeatureConflictError: If a shaft named `name` already exists.
            AmbiguousNameError: If two or more shafts named `name` already
                exist.
            PartialCreationError: If the shaft was created but the follow-up
                rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly (for
                example, `sketch` has no `CenterLine`, or its profile is not
                clear of the axis).
        """
        validate_parameter_name(name)
        return self._create_feature(
            name, SHAFT_KIND, "AddNewShaft", (sketch.com_object,), Shaft, "shaft"
        )

    def ensure_shaft(self, name: str, sketch: Sketch) -> Shaft:
        """Creates a shaft, or reuses it if one with the same name and sketch exists.

        Unlike `ensure_pad`, this never touches the shaft's angles: a newly
        created shaft keeps the default 360.0/0.0, and a reused shaft keeps
        whatever `first_angle`/`second_angle` it already has. Change them
        explicitly with `set_first_angle`/`set_second_angle` if needed.

        Args:
            name: The shaft's name.
            sketch: The `Sketch` the shaft must revolve.

        Returns:
            The existing or newly created `Shaft`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            AmbiguousNameError: If two or more shafts named `name` already
                exist.
            FeatureConflictError: If a shaft named `name` already exists on a
                different sketch.
            PartialCreationError: If a new shaft had to be created and its
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        return self._ensure_by_sketch(
            name, sketch, self.get_shaft, lambda: self.create_shaft(name, sketch), "shaft"
        )

    def remove_shaft(self, name: str) -> None:
        """Removes a shaft from the model.

        Args:
            name: The shaft's name.

        Raises:
            FeatureNotFoundError: If no shaft named `name` exists.
            Auto3dxError: If no editor selection is available, or the deletion
                failed.
        """
        self._remove(name, self.get_shaft, "shaft")

    @property
    def grooves(self) -> "list[Groove]":
        """Lists every groove on the Part's `MainBody`.

        Returns:
            A `Groove` wrapper for each item in `MainBody.Shapes` whose
            wrapper type is `GROOVE_KIND`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._list(GROOVE_KIND, Groove)

    def get_groove(self, name: str) -> Groove:
        """Looks up a groove by name.

        Args:
            name: The groove's name.

        Returns:
            The matching `Groove`.

        Raises:
            FeatureNotFoundError: If no groove named `name` exists.
            AmbiguousNameError: If two or more grooves named `name` exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._get(GROOVE_KIND, Groove, "groove", name)

    def create_groove(self, name: str, sketch: Sketch) -> Groove:
        """Creates a new groove revolving `sketch`.

        Same requirements as `create_shaft`: `sketch` must already have
        `CenterLine` set, with a profile drawn away from that axis
        (`docs/conventions.md` section 1.2.3). The new groove is created with
        the verified defaults `FirstAngle.Value == FULL_REVOLUTION` (360.0)
        and `SecondAngle.Value == 0.0`.

        A successful call here does not mean the feature is valid
        (`docs/conventions.md` section 1.2.2.1): this method never calls
        `Part.Update()`. The caller must call it and handle `PartUpdateError`;
        if the update fails, the groove is left in the model and the caller
        must remove it (`remove_groove`) rather than retrying blindly.

        Args:
            name: The new groove's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            sketch: The `Sketch` to revolve. Must have `CenterLine` set.

        Returns:
            The newly created `Groove`, already renamed to `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            FeatureConflictError: If a groove named `name` already exists.
            AmbiguousNameError: If two or more grooves named `name` already
                exist.
            PartialCreationError: If the groove was created but the follow-up
                rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly (for
                example, `sketch` has no `CenterLine`, or its profile is not
                clear of the axis).
        """
        validate_parameter_name(name)
        return self._create_feature(
            name, GROOVE_KIND, "AddNewGroove", (sketch.com_object,), Groove, "groove"
        )

    def ensure_groove(self, name: str, sketch: Sketch) -> Groove:
        """Creates a groove, or reuses it if one with the same name and sketch exists.

        Policy identical to `ensure_shaft`: angles are never touched by this
        method, whether the groove is created (defaults 360.0/0.0) or reused
        (kept as-is).

        Args:
            name: The groove's name.
            sketch: The `Sketch` the groove must revolve.

        Returns:
            The existing or newly created `Groove`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            AmbiguousNameError: If two or more grooves named `name` already
                exist.
            FeatureConflictError: If a groove named `name` already exists on a
                different sketch.
            PartialCreationError: If a new groove had to be created and its
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        return self._ensure_by_sketch(
            name, sketch, self.get_groove, lambda: self.create_groove(name, sketch), "groove"
        )

    def remove_groove(self, name: str) -> None:
        """Removes a groove from the model.

        Args:
            name: The groove's name.

        Raises:
            FeatureNotFoundError: If no groove named `name` exists.
            Auto3dxError: If no editor selection is available, or the deletion
                failed.
        """
        self._remove(name, self.get_groove, "groove")

    def _resolve_plane(self, support: str) -> Any:
        """Resolves a support string to its raw `OriginElements` plane.

        Mirrors `SketchCollection._plane` exactly, reusing the same
        `SUPPORTED_SKETCH_SUPPORTS`/`_PLANE_ATTRIBUTE_BY_SUPPORT` mapping from
        `geometry.sketch` rather than redefining it, so a support string
        means the same thing whether it is used to place a sketch or a
        mirror.

        Args:
            support: One of `SUPPORTED_SKETCH_SUPPORTS`.

        Returns:
            The raw plane COM object (wrapper type `AnyObject`, not `Plane`).

        Raises:
            UnsupportedSupportError: If `support` is not a supported value.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        if support not in SUPPORTED_SKETCH_SUPPORTS:
            raise UnsupportedSupportError(
                f"Support {support!r} is not supported; supported supports are "
                f"{sorted(SUPPORTED_SKETCH_SUPPORTS)}."
            )
        attribute = _PLANE_ATTRIBUTE_BY_SUPPORT[support]
        try:
            return getattr(self._part_com_object.OriginElements, attribute)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error

    @staticmethod
    def _pattern_axis(direction: str) -> str:
        """Returns the unsigned axis portion of a validated pattern direction."""
        return direction.removeprefix("-")

    @staticmethod
    def _validate_pattern_direction(direction: str, slot: int) -> None:
        """Validates one public rectangular-pattern direction.

        Raises:
            ParameterTypeError: If `direction` is not a verified signed axis.
        """
        if not isinstance(direction, str) or direction not in SUPPORTED_PATTERN_DIRECTIONS:
            raise ParameterTypeError(
                f"Direction {slot} must be one of {sorted(SUPPORTED_PATTERN_DIRECTIONS)}, "
                f"not {direction!r}."
            )

    @staticmethod
    def _validate_pattern_count(count: int, slot: int) -> None:
        """Validates a rectangular-pattern instance count before COM mutation.

        Raises:
            ParameterTypeError: If `count` is not a positive integer.
        """
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ParameterTypeError(
                f"Number of instances in direction {slot} must be a positive integer, "
                f"not {count!r}."
            )

    @staticmethod
    def _validate_pattern_spacing(spacing: float, slot: int) -> float:
        """Validates one strictly positive rectangular-pattern step in millimetres.

        Args:
            spacing: The requested instance spacing.
            slot: CATIA's one-based pattern-direction slot, used only in the
                validation error.

        Returns:
            The validated spacing coerced to ``float``.

        Raises:
            ParameterTypeError: If `spacing` is non-numeric, a bool, zero, or
                negative.
        """
        spacing_value = validate_length_value(spacing)
        if not math.isfinite(spacing_value) or spacing_value <= 0.0:
            raise ParameterTypeError(
                f"Spacing in direction {slot} must be finite and positive, "
                f"not {spacing!r}."
            )
        return spacing_value

    def _pattern_direction_reference(self, direction: str, slot: int) -> tuple[Any, bool]:
        """Creates the verified origin-plane reference for one direction slot."""
        support, reverse = _PATTERN_DIRECTION_MAPPING[slot][direction]
        plane = self._resolve_plane(support)
        try:
            reference = self._part_com_object.CreateReferenceFromObject(plane)
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        return reference, reverse

    @property
    def mirrors(self) -> "list[Mirror]":
        """Lists every mirror on the Part's `MainBody`.

        Returns:
            A `Mirror` wrapper for each item in `MainBody.Shapes` whose
            wrapper type is `MIRROR_KIND`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._list(MIRROR_KIND, Mirror)

    def get_mirror(self, name: str) -> Mirror:
        """Looks up a mirror by name.

        Args:
            name: The mirror's name.

        Returns:
            The matching `Mirror`.

        Raises:
            FeatureNotFoundError: If no mirror named `name` exists.
            AmbiguousNameError: If two or more mirrors named `name` exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._get(MIRROR_KIND, Mirror, "mirror", name)

    def create_mirror(self, name: str, support: str = SUPPORT_YZ) -> Mirror:
        """Creates a new mirror across the given support plane.

        Verified (`docs/conventions.md` section 1.2.3): `AddNewMirror` takes
        a plane directly -- `OriginElements.PlaneYZ` is confirmed to work --
        with no BRep name or other reference-layer lookup required, unlike
        every other unimplemented reference-based feature in this library.

        A successful call here does not mean the feature is valid
        (`docs/conventions.md` section 1.2.2.1): this method never calls
        `Part.Update()`. The caller must call it and handle `PartUpdateError`;
        if the update fails, the mirror is left in the model and the caller
        must remove it (`remove_mirror`) rather than retrying blindly.

        Args:
            name: The new mirror's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            support: One of `SUPPORTED_SKETCH_SUPPORTS`. Defaults to
                `SUPPORT_YZ`, the only support verified against a live
                session.

        Returns:
            The newly created `Mirror`, already renamed to `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            UnsupportedSupportError: If `support` is not a supported value.
            FeatureConflictError: If a mirror named `name` already exists.
            AmbiguousNameError: If two or more mirrors named `name` already
                exist.
            PartialCreationError: If the mirror was created but the follow-up
                rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        plane = self._resolve_plane(support)
        return self._create_feature(
            name, MIRROR_KIND, "AddNewMirror", (plane,), Mirror, "mirror"
        )

    def ensure_mirror(self, name: str, support: str = SUPPORT_YZ) -> Mirror:
        """Creates a mirror, or reuses one with the same name.

        There is no verified way to read a `Mirror`'s mirroring plane back
        from COM, so unlike `ensure_pad`/`ensure_shaft`, a name match here is
        reused unconditionally -- `support` is not compared against whatever
        plane the existing mirror actually uses. If a mirror named `name`
        already exists across a different plane than `support`, this method
        cannot detect that and will hand back the existing (wrong-plane)
        mirror. Callers that need that guarantee must track it themselves.

        Args:
            name: The mirror's name.
            support: One of `SUPPORTED_SKETCH_SUPPORTS`. Defaults to
                `SUPPORT_YZ`. Only used when a new mirror has to be created.

        Returns:
            The existing or newly created `Mirror`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            UnsupportedSupportError: If `support` is not a supported value.
            AmbiguousNameError: If two or more mirrors named `name` already
                exist.
            PartialCreationError: If a new mirror had to be created and its
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        if support not in SUPPORTED_SKETCH_SUPPORTS:
            raise UnsupportedSupportError(
                f"Support {support!r} is not supported; supported supports are "
                f"{sorted(SUPPORTED_SKETCH_SUPPORTS)}."
            )
        try:
            return self.get_mirror(name)
        except FeatureNotFoundError:
            return self.create_mirror(name, support)

    def remove_mirror(self, name: str) -> None:
        """Removes a mirror from the model.

        Args:
            name: The mirror's name.

        Raises:
            FeatureNotFoundError: If no mirror named `name` exists.
            Auto3dxError: If no editor selection is available, or the deletion
                failed.
        """
        self._remove(name, self.get_mirror, "mirror")

    @property
    def ribs(self) -> "list[Rib]":
        """Lists every rib on the Part's `MainBody`.

        Returns:
            A `Rib` wrapper for each item in `MainBody.Shapes` whose wrapper
            type is `RIB_KIND`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._list(RIB_KIND, Rib)

    def get_rib(self, name: str) -> Rib:
        """Looks up a rib by name.

        Args:
            name: The rib's name.

        Returns:
            The matching `Rib`.

        Raises:
            FeatureNotFoundError: If no rib named `name` exists.
            AmbiguousNameError: If two or more ribs named `name` exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._get(RIB_KIND, Rib, "rib", name)

    def create_rib(self, name: str, profile: Sketch, path: Sketch) -> Rib:
        """Creates a new rib sweeping `profile` along `path`.

        Verified against a live session (`docs/conventions.md` section
        1.2.5, probe 24): both raw sketch COM objects are passed directly --
        `AddNewRib(profile.com_object, path.com_object)` -- with a rectangle
        profile on the YZ plane and a line path on the XY plane.

        A successful call here does not mean the feature is valid
        (`docs/conventions.md` section 1.2.2.1): this method never calls
        `Part.Update()`. The caller must call it and handle `PartUpdateError`;
        if the update fails, the rib is left in the model and the caller must
        remove it (`remove_rib`) rather than retrying blindly.

        Args:
            name: The new rib's name. Must be non-empty, without surrounding
                whitespace, and must not contain `"\\"`.
            profile: The `Sketch` cross-section to sweep.
            path: The `Sketch` center curve to sweep `profile` along.

        Returns:
            The newly created `Rib`, already renamed to `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            FeatureConflictError: If a rib named `name` already exists.
            AmbiguousNameError: If two or more ribs named `name` already
                exist.
            PartialCreationError: If the rib was created but the follow-up
                rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly (for
                example, an unusable profile/path combination).
        """
        validate_parameter_name(name)
        return self._create_feature(
            name, RIB_KIND, "AddNewRib", (profile.com_object, path.com_object), Rib, "rib"
        )

    def ensure_rib(self, name: str, profile: Sketch, path: Sketch) -> Rib:
        """Creates a rib, or reuses it if one with the same name and profile exists.

        The conflict check compares only the profile sketch, by COM identity
        (`==`), exactly like `ensure_pad`. The path (center curve) sketch is
        **not** compared: there is no verified way to read a rib's path
        sketch back from COM, so this method cannot detect a rib named
        `name` that has the same profile but a different path, and will hand
        back that existing rib unchanged. Callers that need that guarantee
        must track the path themselves.

        Args:
            name: The rib's name.
            profile: The `Sketch` the rib must be built from.
            path: The `Sketch` center curve. Only used when a new rib has to
                be created; never compared against an existing rib's path.

        Returns:
            The existing or newly created `Rib`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            AmbiguousNameError: If two or more ribs named `name` already
                exist.
            FeatureConflictError: If a rib named `name` already exists on a
                different profile sketch.
            PartialCreationError: If a new rib had to be created and its
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        return self._ensure_by_sketch(
            name,
            profile,
            self.get_rib,
            lambda: self.create_rib(name, profile, path),
            "rib",
            sketch_of=lambda feature: feature.profile(),
        )

    def remove_rib(self, name: str) -> None:
        """Removes a rib from the model.

        Args:
            name: The rib's name.

        Raises:
            FeatureNotFoundError: If no rib named `name` exists.
            Auto3dxError: If no editor selection is available, or the deletion
                failed.
        """
        self._remove(name, self.get_rib, "rib")

    @property
    def slots(self) -> "list[Slot]":
        """Lists every slot on the Part's `MainBody`.

        Returns:
            A `Slot` wrapper for each item in `MainBody.Shapes` whose wrapper
            type is `SLOT_KIND`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._list(SLOT_KIND, Slot)

    def get_slot(self, name: str) -> Slot:
        """Looks up a slot by name.

        Args:
            name: The slot's name.

        Returns:
            The matching `Slot`.

        Raises:
            FeatureNotFoundError: If no slot named `name` exists.
            AmbiguousNameError: If two or more slots named `name` exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._get(SLOT_KIND, Slot, "slot", name)

    def create_slot(self, name: str, profile: Sketch, path: Sketch) -> Slot:
        """Creates a new slot cutting along `path` with cross-section `profile`.

        Verified against a live session (`docs/conventions.md` section
        1.2.5, probe 25): both raw sketch COM objects are passed directly --
        `AddNewSlot(profile.com_object, path.com_object)` -- with the same
        rectangle-profile-on-YZ / line-path-on-XY combination verified for
        `create_rib`.

        A successful call here does not mean the feature is valid
        (`docs/conventions.md` section 1.2.2.1): this method never calls
        `Part.Update()`. The caller must call it and handle `PartUpdateError`;
        if the update fails, the slot is left in the model and the caller
        must remove it (`remove_slot`) rather than retrying blindly.

        Args:
            name: The new slot's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            profile: The `Sketch` cross-section to cut.
            path: The `Sketch` center curve to sweep `profile` along.

        Returns:
            The newly created `Slot`, already renamed to `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            FeatureConflictError: If a slot named `name` already exists.
            AmbiguousNameError: If two or more slots named `name` already
                exist.
            PartialCreationError: If the slot was created but the follow-up
                rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly (for
                example, an unusable profile/path combination).
        """
        validate_parameter_name(name)
        return self._create_feature(
            name, SLOT_KIND, "AddNewSlot", (profile.com_object, path.com_object), Slot, "slot"
        )

    def ensure_slot(self, name: str, profile: Sketch, path: Sketch) -> Slot:
        """Creates a slot, or reuses it if one with the same name and profile exists.

        The conflict check compares only the profile sketch, by COM identity
        (`==`), exactly like `ensure_rib`. The path (center curve) sketch is
        **not** compared: there is no verified way to read a slot's path
        sketch back from COM, so this method cannot detect a slot named
        `name` that has the same profile but a different path, and will hand
        back that existing slot unchanged. Callers that need that guarantee
        must track the path themselves.

        Args:
            name: The slot's name.
            profile: The `Sketch` the slot must be built from.
            path: The `Sketch` center curve. Only used when a new slot has to
                be created; never compared against an existing slot's path.

        Returns:
            The existing or newly created `Slot`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            AmbiguousNameError: If two or more slots named `name` already
                exist.
            FeatureConflictError: If a slot named `name` already exists on a
                different profile sketch.
            PartialCreationError: If a new slot had to be created and its
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        return self._ensure_by_sketch(
            name,
            profile,
            self.get_slot,
            lambda: self.create_slot(name, profile, path),
            "slot",
            sketch_of=lambda feature: feature.profile(),
        )

    def remove_slot(self, name: str) -> None:
        """Removes a slot from the model.

        Args:
            name: The slot's name.

        Raises:
            FeatureNotFoundError: If no slot named `name` exists.
            Auto3dxError: If no editor selection is available, or the deletion
                failed.
        """
        self._remove(name, self.get_slot, "slot")

    @property
    def multi_section_solids(self) -> "list[MultiSectionSolid]":
        """Lists every Multi-sections Solid on the Part's `MainBody`.

        Read from the live model each time: a feature created by another process is
        listed just like one created through this wrapper.

        Returns:
            A `MultiSectionSolid` for each item in `MainBody.Shapes` whose wrapper type
            is `MULTI_SECTION_SOLID_KIND`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._list(MULTI_SECTION_SOLID_KIND, MultiSectionSolid)

    def get_multi_section_solid(self, name: str) -> MultiSectionSolid:
        """Looks up a Multi-sections Solid by name.

        Args:
            name: The feature's name.

        Returns:
            The matching `MultiSectionSolid`.

        Raises:
            FeatureNotFoundError: If no Multi-sections Solid named `name` exists.
            AmbiguousNameError: If two or more exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._get(
            MULTI_SECTION_SOLID_KIND, MultiSectionSolid, "multi-section solid", name
        )

    def create_multi_section_solid(
        self, name: str, sections: "Sequence[Sketch]"
    ) -> MultiSectionSolid:
        """Creates a Multi-sections Solid (CATIA Loft) through two or more sketches.

        Each section is passed to `AddSectionToLoft` as a reference created from the
        sketch, with orientation `MULTI_SECTION_ORIENTATION_VERIFIED` and no closing
        point -- the combination verified live (probe 40). The sections are used in the
        order given. No guide, spine, coupling, tangency or relimitation is set.

        This does not rebuild. Call `part.update()` afterwards, and if that raises
        `PartUpdateError`, remove the feature with `remove_multi_section_solid`: a
        feature whose update failed breaks every later update.

        No closing points are set, so what builds depends on the sections' corners
        (`docs/conventions.md` section 1.8). Live, corner-free sections built: two circles,
        and a NACA profile drawn as one closed spline per section. Sections with corners
        failed `Part.Update()`: two rectangles, and a NACA profile whose open trailing
        edge was closed by a separate line. Prefer one smooth closed curve per section.

        Creating the feature makes its loft the In-Work Object in CATIA (probe 40). The
        SDK does not change that; `part.inspect.in_work_object()` reports it.

        Args:
            name: The new feature's name. Must be non-empty, without surrounding
                whitespace, and must not contain `"\\"`.
            sections: Two or more different `Sketch` objects, each a closed profile, in
                the order the solid should pass through them.

        Returns:
            The new `MultiSectionSolid`, renamed to `name`, with every section added.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            ParameterTypeError: If `sections` is not a sequence of at least two
                different `Sketch` objects.
            FeatureConflictError: If a Multi-sections Solid named `name` already exists.
            AmbiguousNameError: If two or more already exist.
            PartialCreationError: If the feature was created but could not be renamed or
                could not receive every section.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        section_list = _validate_sections(sections)
        references = []
        for section in section_list:
            try:
                references.append(
                    self._part_com_object.CreateReferenceFromObject(section.com_object)
                )
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error

        def add_sections(com_object: Any) -> None:
            hybrid_loft = com_object.HybridShape
            for reference in references:
                hybrid_loft.AddSectionToLoft(
                    reference, MULTI_SECTION_ORIENTATION_VERIFIED, None
                )

        return self._create_feature(
            name,
            MULTI_SECTION_SOLID_KIND,
            "AddNewLoft",
            (),
            MultiSectionSolid,
            "multi-section solid",
            configure=add_sections,
        )

    def remove_multi_section_solid(self, name: str) -> None:
        """Removes a Multi-sections Solid from the model.

        The feature is found in the live model by name, so one created by another
        process can be removed. Deleting it also deleted its section sketches in probe
        40, the way deleting a pad deletes its sketch; a later `sketches.remove` for
        them will legitimately raise `SketchNotFoundError`. Planes the sketches sat on
        are not removed. This does not rebuild and never saves.

        Args:
            name: The feature's name.

        Raises:
            FeatureNotFoundError: If no Multi-sections Solid named `name` exists.
            Auto3dxError: If no editor selection is available, or the deletion failed.
        """
        self._remove(name, self.get_multi_section_solid, "multi-section solid")

    def snapshot_edges(self) -> EdgeSnapshot:
        """Takes a fresh snapshot of every edge of the Part's solid.

        This is the only verified way to obtain an edge reference
        (`docs/conventions.md` section 1.2.2.2, `geometry.edges`):
        `Selection.Clear()`, `Selection.Search("Topology.Edge,all")`, then
        `SelectedElement.Reference` for each hit. The result describes the
        model exactly as it stands right now -- edge count and search order
        both change after any modification (measured: 29, then 32 after one
        fillet, then 38, then 41) -- so take a new snapshot after a
        `create_edge_fillet`/`create_chamfer` call rather than reusing an old
        one across a model change; an older snapshot is refused. The user's
        CATIA selection is restored afterwards, exactly as for
        `part.topology.edges()`. See `geometry.edges` for the full rationale.

        Returns:
            A fresh `EdgeSnapshot`.

        Raises:
            ValidationError: If no editor selection is available.
            AutomationError: If the selection cannot be read, or the search
                fails.
        """
        warnings.warn(
            "PartDesign.snapshot_edges() is deprecated; use part.topology.edges(), "
            "which shares the same model generation.",
            DeprecationWarning,
            stacklevel=2,
        )
        return take_edge_snapshot(
            self._selection, self._generation.value, self._part_com_object
        )

    @property
    def edge_fillets(self) -> "list[ConstRadEdgeFillet]":
        """Lists every constant-radius edge fillet on the Part's `MainBody`.

        Returns:
            A `ConstRadEdgeFillet` wrapper for each item in `MainBody.Shapes`
            whose wrapper type is `EDGE_FILLET_KIND`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._list(EDGE_FILLET_KIND, ConstRadEdgeFillet)

    def get_edge_fillet(self, name: str) -> ConstRadEdgeFillet:
        """Looks up an edge fillet by name.

        Args:
            name: The fillet's name.

        Returns:
            The matching `ConstRadEdgeFillet`.

        Raises:
            FeatureNotFoundError: If no edge fillet named `name` exists.
            AmbiguousNameError: If two or more edge fillets named `name`
                exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._get(EDGE_FILLET_KIND, ConstRadEdgeFillet, "edge fillet", name)

    def create_edge_fillet(
        self,
        name: str,
        edge: Edge,
        radius: float,
        unit: str = MILLIMETRE,
        propagation: int = EDGE_FILLET_PROPAGATION_VERIFIED,
    ) -> ConstRadEdgeFillet:
        """Creates a new constant-radius fillet on one edge.

        Verified (`docs/conventions.md` section 1.2.2.2):
        `AddNewEdgeFilletWithConstantRadius(edge_reference, propagation,
        radius)` both created the feature and survived `Part.Update()`, with
        `propagation = EDGE_FILLET_PROPAGATION_VERIFIED` (1). No other
        propagation value has been tried against a live session, so it is
        the only one this method accepts.

        A successful call here does not mean the feature is valid
        (`docs/conventions.md` section 1.2.2.1): this method never calls
        `Part.Update()`. The caller must call it and handle
        `PartUpdateError`. **A failed update leaves the fillet in the tree,
        and every later `Part.Update()` fails too until the model is valid
        again** -- this is exactly what made an earlier probe look like a
        cascade of unrelated failures. Repair before retrying, and prefer
        rollback to deletion: if the failure followed an edit to something
        that worked, undo that edit and update again (live, a 1 mm pad under
        this fillet failed the update, and restoring the pad healed the Part
        with the fillet intact). Remove the fillet with `remove_edge_fillet`
        when it never built in the first place. Do not retry blindly.

        Args:
            name: The new fillet's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            edge: The `Edge` to fillet, from `part.topology.edges()`.
            radius: The fillet radius. Must be finite and positive.
            unit: The unit `radius` is expressed in. Defaults to
                `MILLIMETRE`.
            propagation: One of `SUPPORTED_EDGE_FILLET_PROPAGATIONS`.
                Defaults to `EDGE_FILLET_PROPAGATION_VERIFIED`, the only
                value verified against a live session.

        Returns:
            The newly created `ConstRadEdgeFillet`, already renamed to
            `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            ParameterTypeError: If `edge` is not an `Edge`, `radius` is not
                finite and positive, or `propagation` is not supported.
            UnsupportedUnitError: If `unit` is not a supported unit.
            FeatureConflictError: If an edge fillet named `name` already
                exists.
            AmbiguousNameError: If two or more edge fillets named `name`
                already exist.
            PartialCreationError: If the fillet was created but the
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly (for
                example, `edge` no longer resolves to a real edge).
        """
        validate_parameter_name(name)
        if not isinstance(edge, Edge):
            raise ParameterTypeError(
                "edge must be an Edge from part.topology.edges(), not "
                f"{type(edge).__name__}."
            )
        self._require_current_edge(edge, "fillet")
        if propagation not in SUPPORTED_EDGE_FILLET_PROPAGATIONS:
            raise ParameterTypeError(
                f"propagation must be one of {sorted(SUPPORTED_EDGE_FILLET_PROPAGATIONS)}, "
                f"not {propagation!r}."
            )
        validate_length_unit(unit)
        coerced_radius = _validate_positive_length(radius, "radius")
        return self._create_feature(
            name,
            EDGE_FILLET_KIND,
            "AddNewEdgeFilletWithConstantRadius",
            (edge.com_object, propagation, coerced_radius),
            ConstRadEdgeFillet,
            "edge fillet",
        )

    def remove_edge_fillet(self, name: str) -> None:
        """Removes an edge fillet from the model.

        Args:
            name: The fillet's name.

        Raises:
            FeatureNotFoundError: If no edge fillet named `name` exists.
            Auto3dxError: If no editor selection is available, or the
                deletion failed.
        """
        self._remove(name, self.get_edge_fillet, "edge fillet")

    @property
    def chamfers(self) -> "list[Chamfer]":
        """Lists every chamfer on the Part's `MainBody`.

        Returns:
            A `Chamfer` wrapper for each item in `MainBody.Shapes` whose
            wrapper type is `CHAMFER_KIND`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._list(CHAMFER_KIND, Chamfer)

    def get_chamfer(self, name: str) -> Chamfer:
        """Looks up a chamfer by name.

        Args:
            name: The chamfer's name.

        Returns:
            The matching `Chamfer`.

        Raises:
            FeatureNotFoundError: If no chamfer named `name` exists.
            AmbiguousNameError: If two or more chamfers named `name` exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._get(CHAMFER_KIND, Chamfer, "chamfer", name)

    def create_chamfer(
        self,
        name: str,
        edge: Edge,
        length1: float,
        length2_or_angle: float,
        propagation: int,
        orientation: int,
        unit: str = MILLIMETRE,
    ) -> Chamfer:
        """Creates a new chamfer on one edge.

        Verified (`docs/conventions.md` section 1.2.2.2):
        `AddNewChamfer(edge_reference, propagation, mode, orientation,
        length1, length2_or_angle)` created the feature AND survived
        `Part.Update()` for every combination of `propagation` in
        `SUPPORTED_CHAMFER_PROPAGATIONS` (0, 1) and `orientation` in
        `SUPPORTED_CHAMFER_ORIENTATIONS` (0, 1), with `length1 = 1.5` and
        `length2_or_angle = 45.0`. `mode` is always `CHAMFER_MODE_VERIFIED`
        (1): mode 0 creates a feature whose update fails, and mode 2 fails at
        creation, so this method does not expose `mode` as a parameter at
        all -- neither 0 nor 2 is offered under any name.

        Neither `propagation` nor `orientation` carries attached enum
        metadata in the type library (both are plain `VT_I4`), so their
        meaning is unknown; only their verified-safe integer values are
        recorded as constants here (`CHAMFER_PROPAGATION_0`/`_1`,
        `CHAMFER_ORIENTATION_0`/`_1`).

        A successful call here does not mean the feature is valid
        (`docs/conventions.md` section 1.2.2.1): this method never calls
        `Part.Update()`. The caller must call it and handle
        `PartUpdateError`. **A failed update leaves the chamfer in the tree,
        and every later `Part.Update()` fails too until the model is valid
        again** -- this is exactly what made an earlier probe look like a
        cascade of unrelated failures. Undo the edit that broke it and update
        again, or remove the chamfer with `remove_chamfer` when it never
        built; do not retry blindly.

        Args:
            name: The new chamfer's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            edge: The `Edge` to chamfer, from `part.topology.edges()`.
            length1: The first chamfer length. Must be finite and positive.
            length2_or_angle: The second chamfer length or angle. Must be
                finite and positive.
            propagation: One of `SUPPORTED_CHAMFER_PROPAGATIONS`.
            orientation: One of `SUPPORTED_CHAMFER_ORIENTATIONS`.
            unit: The unit `length1`/`length2_or_angle` are expressed in.
                Defaults to `MILLIMETRE`.

        Returns:
            The newly created `Chamfer`, already renamed to `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            ParameterTypeError: If `edge` is not an `Edge`, `length1`/
                `length2_or_angle` is not finite and positive, or
                `propagation`/`orientation` is not supported.
            UnsupportedUnitError: If `unit` is not a supported unit.
            FeatureConflictError: If a chamfer named `name` already exists.
            AmbiguousNameError: If two or more chamfers named `name` already
                exist.
            PartialCreationError: If the chamfer was created but the
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly (for
                example, `edge` no longer resolves to a real edge).
        """
        validate_parameter_name(name)
        if not isinstance(edge, Edge):
            raise ParameterTypeError(
                "edge must be an Edge from part.topology.edges(), not "
                f"{type(edge).__name__}."
            )
        self._require_current_edge(edge, "chamfer")
        if propagation not in SUPPORTED_CHAMFER_PROPAGATIONS:
            raise ParameterTypeError(
                f"propagation must be one of {sorted(SUPPORTED_CHAMFER_PROPAGATIONS)}, "
                f"not {propagation!r}."
            )
        if orientation not in SUPPORTED_CHAMFER_ORIENTATIONS:
            raise ParameterTypeError(
                f"orientation must be one of {sorted(SUPPORTED_CHAMFER_ORIENTATIONS)}, "
                f"not {orientation!r}."
            )
        validate_length_unit(unit)
        coerced_length1 = _validate_positive_length(length1, "length1")
        coerced_length2 = _validate_positive_length(length2_or_angle, "length2_or_angle")
        return self._create_feature(
            name,
            CHAMFER_KIND,
            "AddNewChamfer",
            (
                edge.com_object,
                propagation,
                CHAMFER_MODE_VERIFIED,
                orientation,
                coerced_length1,
                coerced_length2,
            ),
            Chamfer,
            "chamfer",
        )

    def remove_chamfer(self, name: str) -> None:
        """Removes a chamfer from the model.

        Args:
            name: The chamfer's name.

        Raises:
            FeatureNotFoundError: If no chamfer named `name` exists.
            Auto3dxError: If no editor selection is available, or the
                deletion failed.
        """
        self._remove(name, self.get_chamfer, "chamfer")

    def snapshot_faces(self) -> FaceSnapshot:
        """Takes a fresh snapshot of every face of the Part's solid.

        This is the face counterpart of `snapshot_edges` and is the only
        verified way to obtain a face reference (`docs/conventions.md`
        section 1.2.2.2, probe 37, `geometry.faces`): `Selection.Clear()`,
        `Selection.Search("Topology.Face,all")`, then
        `SelectedElement.Reference` for each hit. The result describes the
        model exactly as it stands right now; take a new snapshot after a
        `create_shell`/`create_thickness`/`create_hole` call rather than
        reusing an old one across a model change. See `geometry.faces` for
        the full rationale, including which parts of it are independently
        measured for faces and which are carried over from the edge layer as
        a conservative policy. The user's CATIA selection is restored
        afterwards, exactly as for `part.topology.faces()`.

        Returns:
            A fresh `FaceSnapshot`.

        Raises:
            ValidationError: If no editor selection is available.
            AutomationError: If the selection cannot be read, or the search
                fails.
        """
        warnings.warn(
            "PartDesign.snapshot_faces() is deprecated; use part.topology.faces(), "
            "which shares the same model generation.",
            DeprecationWarning,
            stacklevel=2,
        )
        return take_face_snapshot(
            self._selection, self._generation.value, self._part_com_object
        )

    @property
    def shells(self) -> "list[Shell]":
        """Lists every shell on the Part's `MainBody`.

        Returns:
            A `Shell` wrapper for each item in `MainBody.Shapes` whose
            wrapper type is `SHELL_KIND`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._list(SHELL_KIND, Shell)

    def get_shell(self, name: str) -> Shell:
        """Looks up a shell by name.

        Args:
            name: The shell's name.

        Returns:
            The matching `Shell`.

        Raises:
            FeatureNotFoundError: If no shell named `name` exists.
            AmbiguousNameError: If two or more shells named `name` exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._get(SHELL_KIND, Shell, "shell", name)

    def create_shell(
        self,
        name: str,
        face: Face,
        internal_thickness: float,
        external_thickness: float,
        unit: str = MILLIMETRE,
    ) -> Shell:
        """Creates a new shell that hollows the solid, opening it at one face.

        Verified (`docs/conventions.md` section 1.2.2.2, probe 37):
        `AddNewShell(face_reference, internal_thickness, external_thickness)`
        both created the feature and survived `Part.Update()`, on the first
        face tried, with `internal_thickness = 2.0` and
        `external_thickness = 0.0`. No other combination has been tried
        against a live session.

        A successful call here does not mean the feature is valid
        (`docs/conventions.md` section 1.2.2.1): this method never calls
        `Part.Update()`. The caller must call it and handle
        `PartUpdateError`. **A failed update leaves the shell in the tree,
        and every later `Part.Update()` fails too until the model is valid
        again** -- exactly the edge-feature failure mode documented on
        `create_edge_fillet`. Undo the edit that broke it and update again, or
        remove the shell with `remove_shell` when it never built; do not retry
        blindly.

        Args:
            name: The new shell's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            face: The `Face` to open, from `part.topology.faces()`.
            internal_thickness: The shell's wall thickness. Must be finite
                and strictly positive -- only `2.0` is verified, and a zero
                or negative wall thickness has no justified meaning here.
            external_thickness: The shell's outward offset. Must be finite
                and non-negative -- only `0.0` is verified, and that is
                itself the boundary value, so zero is accepted but a
                negative value is not (never tried, no justification).
            unit: The unit `internal_thickness`/`external_thickness` are
                expressed in. Defaults to `MILLIMETRE`.

        Returns:
            The newly created `Shell`, already renamed to `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            ParameterTypeError: If `face` is not a `Face`,
                `internal_thickness` is not finite and positive, or
                `external_thickness` is not finite and non-negative.
            UnsupportedUnitError: If `unit` is not a supported unit.
            FeatureConflictError: If a shell named `name` already exists.
            AmbiguousNameError: If two or more shells named `name` already
                exist.
            PartialCreationError: If the shell was created but the follow-up
                rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly (for
                example, `face` no longer resolves to a real face).
        """
        validate_parameter_name(name)
        if not isinstance(face, Face):
            raise ParameterTypeError(
                "face must be a Face from part.topology.faces(), not "
                f"{type(face).__name__}."
            )
        self._require_current_face(face, "shell")
        validate_length_unit(unit)
        coerced_internal = _validate_positive_length(internal_thickness, "internal_thickness")
        coerced_external = _validate_non_negative_length(external_thickness, "external_thickness")
        return self._create_feature(
            name,
            SHELL_KIND,
            "AddNewShell",
            (face.com_object, coerced_internal, coerced_external),
            Shell,
            "shell",
        )

    def remove_shell(self, name: str) -> None:
        """Removes a shell from the model.

        Args:
            name: The shell's name.

        Raises:
            FeatureNotFoundError: If no shell named `name` exists.
            Auto3dxError: If no editor selection is available, or the
                deletion failed.
        """
        self._remove(name, self.get_shell, "shell")

    @property
    def thicknesses(self) -> "list[Thickness]":
        """Lists every thickness feature on the Part's `MainBody`.

        Returns:
            A `Thickness` wrapper for each item in `MainBody.Shapes` whose
            wrapper type is `THICKNESS_KIND`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._list(THICKNESS_KIND, Thickness)

    def get_thickness(self, name: str) -> Thickness:
        """Looks up a thickness feature by name.

        Args:
            name: The thickness feature's name.

        Returns:
            The matching `Thickness`.

        Raises:
            FeatureNotFoundError: If no thickness feature named `name`
                exists.
            AmbiguousNameError: If two or more thickness features named
                `name` exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._get(THICKNESS_KIND, Thickness, "thickness", name)

    def create_thickness(
        self,
        name: str,
        face: Face,
        offset: float,
        unit: str = MILLIMETRE,
    ) -> Thickness:
        """Creates a new feature that thickens the solid at one face.

        Verified (`docs/conventions.md` section 1.2.2.2, probe 37):
        `AddNewThickness(face_reference, offset)` both created the feature
        and survived `Part.Update()`, on the first face tried, with
        `offset = 3.0`. No other value has been tried against a live
        session.

        A successful call here does not mean the feature is valid
        (`docs/conventions.md` section 1.2.2.1): this method never calls
        `Part.Update()`. The caller must call it and handle
        `PartUpdateError`. **A failed update leaves the thickness feature in
        the tree, and every later `Part.Update()` fails too until it is
        removed** -- exactly the edge-feature failure mode documented on
        `create_edge_fillet`. Remove it with `remove_thickness` before
        retrying; do not retry blindly.

        Args:
            name: The new feature's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            face: The `Face` to thicken, from `part.topology.faces()`.
            offset: The thickening offset. Must be finite and strictly
                positive -- only `3.0` is verified, and a zero offset would
                do nothing while a negative one has never been tried, so
                neither is justified.
            unit: The unit `offset` is expressed in. Defaults to
                `MILLIMETRE`.

        Returns:
            The newly created `Thickness`, already renamed to `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            ParameterTypeError: If `face` is not a `Face`, or `offset` is not
                finite and positive.
            UnsupportedUnitError: If `unit` is not a supported unit.
            FeatureConflictError: If a thickness feature named `name` already
                exists.
            AmbiguousNameError: If two or more thickness features named
                `name` already exist.
            PartialCreationError: If the feature was created but the
                follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly (for
                example, `face` no longer resolves to a real face).
        """
        validate_parameter_name(name)
        if not isinstance(face, Face):
            raise ParameterTypeError(
                "face must be a Face from part.topology.faces(), not "
                f"{type(face).__name__}."
            )
        self._require_current_face(face, "thickness")
        validate_length_unit(unit)
        coerced_offset = _validate_positive_length(offset, "offset")
        return self._create_feature(
            name,
            THICKNESS_KIND,
            "AddNewThickness",
            (face.com_object, coerced_offset),
            Thickness,
            "thickness",
        )

    def remove_thickness(self, name: str) -> None:
        """Removes a thickness feature from the model.

        Args:
            name: The thickness feature's name.

        Raises:
            FeatureNotFoundError: If no thickness feature named `name`
                exists.
            Auto3dxError: If no editor selection is available, or the
                deletion failed.
        """
        self._remove(name, self.get_thickness, "thickness")

    @property
    def holes(self) -> "list[Hole]":
        """Lists every hole on the Part's `MainBody`.

        Returns:
            A `Hole` wrapper for each item in `MainBody.Shapes` whose wrapper
            type is `HOLE_KIND`, in `Item(i)` order.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._list(HOLE_KIND, Hole)

    def get_hole(self, name: str) -> Hole:
        """Looks up a hole by name.

        Args:
            name: The hole's name.

        Returns:
            The matching `Hole`.

        Raises:
            FeatureNotFoundError: If no hole named `name` exists.
            AmbiguousNameError: If two or more holes named `name` exist.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._get(HOLE_KIND, Hole, "hole", name)

    def create_hole(
        self,
        name: str,
        face: Face,
        depth: float,
        unit: str = MILLIMETRE,
    ) -> Hole:
        """Creates a new simple hole into the solid from one face.

        Verified (`docs/conventions.md` section 1.2.2.2, probe 37):
        `AddNewHole(face_reference, depth)` both created the feature and
        survived `Part.Update()`, on the first face tried, with
        `depth = 5.0`. No other value has been tried against a live session.

        A successful call here does not mean the feature is valid
        (`docs/conventions.md` section 1.2.2.1): this method never calls
        `Part.Update()`. The caller must call it and handle
        `PartUpdateError`. **A failed update leaves the hole in the tree, and
        every later `Part.Update()` fails too until the model is valid again**
        -- exactly the edge-feature failure mode documented on
        `create_edge_fillet`. Undo the edit that broke it and update again, or
        remove the hole with `remove_hole` when it never built; do not retry
        blindly.

        Args:
            name: The new hole's name. Must be non-empty, without
                surrounding whitespace, and must not contain `"\\"`.
            face: The `Face` to drill from, from `part.topology.faces()`.
            depth: The hole's depth. Must be finite and strictly positive --
                only `5.0` is verified, and a zero or negative depth has no
                justified meaning for a hole.
            unit: The unit `depth` is expressed in. Defaults to
                `MILLIMETRE`.

        Returns:
            The newly created `Hole`, already renamed to `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            ParameterTypeError: If `face` is not a `Face`, or `depth` is not
                finite and positive.
            UnsupportedUnitError: If `unit` is not a supported unit.
            FeatureConflictError: If a hole named `name` already exists.
            AmbiguousNameError: If two or more holes named `name` already
                exist.
            PartialCreationError: If the hole was created but the follow-up
                rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly (for
                example, `face` no longer resolves to a real face).
        """
        validate_parameter_name(name)
        if not isinstance(face, Face):
            raise ParameterTypeError(
                "face must be a Face from part.topology.faces(), not "
                f"{type(face).__name__}."
            )
        self._require_current_face(face, "hole")
        validate_length_unit(unit)
        coerced_depth = _validate_positive_length(depth, "depth")
        return self._create_feature(
            name,
            HOLE_KIND,
            "AddNewHole",
            (face.com_object, coerced_depth),
            Hole,
            "hole",
        )

    def remove_hole(self, name: str) -> None:
        """Removes a hole from the model.

        Args:
            name: The hole's name.

        Raises:
            FeatureNotFoundError: If no hole named `name` exists.
            Auto3dxError: If no editor selection is available, or the
                deletion failed.
        """
        self._remove(name, self.get_hole, "hole")

    def create_rectangular_pattern(
        self,
        pad: Pad,
        number_in_direction_1: int,
        number_in_direction_2: int,
        spacing_in_direction_1: float,
        spacing_in_direction_2: float,
        direction_1: str,
        direction_2: str,
    ) -> RectangularPattern:
        """Creates a verified rectangular pattern of a `Pad`.

        CATIA requires origin-plane references for pattern directions, not raw
        planes or 2D lines. Its two direction slots interpret a plane
        differently, so this API accepts signed global axes and chooses both
        the verified plane reference and its required reverse flag.

        This only uses the measured call form: ``AddNewRectPattern(pad, n1,
        n2, step1, step2, 1, 1, ref1, ref2, reverse1, reverse2, 0.0)``. It
        never calls `Part.Update()`, `Save`, or PLM propagation. The caller
        must update the Part and handle failures, because CATIA leaves a
        failed pattern in the model; use
        :meth:`remove_rectangular_pattern` to clean it up.

        Args:
            pad: The `Pad` to copy; this is the source type verified by probes.
            number_in_direction_1: Number of instances along direction 1.
            number_in_direction_2: Number of instances along direction 2.
            spacing_in_direction_1: Direction-1 instance spacing in mm.
            spacing_in_direction_2: Direction-2 instance spacing in mm.
            direction_1: A signed axis from `SUPPORTED_PATTERN_DIRECTIONS`.
                Its sign is the complete direction choice.
            direction_2: A signed axis from `SUPPORTED_PATTERN_DIRECTIONS`.
                Its sign is the complete direction choice.

        Returns:
            A wrapper around the new `RectPattern` COM object.

        Raises:
            ParameterTypeError: If the source Pad, a direction, count, or
                spacing is invalid.
            FeatureConflictError: If directions are collinear. This is
                rejected before CATIA can create a broken feature.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        if not isinstance(pad, Pad):
            raise ParameterTypeError(
                "A rectangular pattern source must be a Pad created or wrapped "
                f"by auto_3dx, not {type(pad).__name__}."
            )
        self._validate_pattern_direction(direction_1, 1)
        self._validate_pattern_direction(direction_2, 2)
        self._validate_pattern_count(number_in_direction_1, 1)
        self._validate_pattern_count(number_in_direction_2, 2)
        if self._pattern_axis(direction_1) == self._pattern_axis(direction_2):
            raise FeatureConflictError(
                "Rectangular-pattern directions must use distinct axes; "
                f"{direction_1!r} and {direction_2!r} are collinear."
            )

        spacing_1 = self._validate_pattern_spacing(spacing_in_direction_1, 1)
        spacing_2 = self._validate_pattern_spacing(spacing_in_direction_2, 2)
        reference_1, mapped_reverse_1 = self._pattern_direction_reference(
            direction_1, 1
        )
        reference_2, mapped_reverse_2 = self._pattern_direction_reference(
            direction_2, 2
        )
        with self._generation.mutation():
            self._target_in_work()
            try:
                com_object = self._part_com_object.ShapeFactory.AddNewRectPattern(
                    pad.com_object,
                    number_in_direction_1,
                    number_in_direction_2,
                    spacing_1,
                    spacing_2,
                    _PATTERN_COPY_POSITION,
                    _PATTERN_COPY_POSITION,
                    reference_1,
                    reference_2,
                    mapped_reverse_1,
                    mapped_reverse_2,
                    _PATTERN_ROTATION_ANGLE,
                )
            except pywintypes.com_error as error:
                raise _wrap_com_error(error) from error
        return RectangularPattern(com_object, self._generation)

    def _owning_body(self, feature: Any) -> "tuple[Any, str | None]":
        """Walks a feature's `Parent` chain to the body that holds it.

        Args:
            feature: A raw feature COM object.

        Returns:
            `(body, body_name)`, both `None` when CATIA does not report a body.
        """
        node = feature
        for _ in range(_MAX_OWNER_WALK):
            try:
                node = node.Parent
            except (pywintypes.com_error, AttributeError):
                return None, None
            if node is None:
                return None, None
            if type(node).__name__ == "Body":
                try:
                    return node, str(node.Name)
                except (pywintypes.com_error, AttributeError):
                    return node, None
        return None, None

    def _require_feature_in_target_body(self, feature: Any, noun: str) -> None:
        """Refuses a seed feature that lives in a different body from the target one.

        Patterning a feature of one body into another is accepted by CATIA and fails at
        the next update, the same trap Phase 1 closed for edges and faces.

        Args:
            feature: The seed feature wrapper.
            noun: What is being created, for the message.

        Raises:
            CrossBodyReferenceError: If the seed belongs to another body. Nothing was
                changed. An owner CATIA does not report is allowed through, exactly as it
                is for topology references.
        """
        owner, owner_name = self._owning_body(feature.com_object)
        if owner is None:
            return
        target = self._body()
        try:
            if bool(owner == target):
                return
        except pywintypes.com_error:
            return
        try:
            target_name = str(target.Name)
        except (pywintypes.com_error, AttributeError):
            target_name = "the target body"
        raise CrossBodyReferenceError(
            f"{feature.name!r} belongs to body {owner_name or 'another body'!r}, but the "
            f"{noun} would be created in {target_name!r}. CATIA would accept that and fail "
            "the next Part.Update(). Nothing was changed: open part.work_in(body) for the "
            "body that owns the feature."
        )

    def create_circular_pattern(
        self,
        name: str,
        feature: Any,
        angular_instances: int,
        angular_spacing_deg: float,
        axis: str = CIRCULAR_PATTERN_AXIS_Z,
    ) -> CircularPattern:
        """Creates a circular pattern of an existing feature around an origin axis.

        This is the bolt-circle operation: one hole becomes six around the centre. Live
        (probe 44), six instances of a pocket spaced 60 degrees apart removed exactly five
        extra holes' worth of material, and the pattern rebuilt and was found again by
        name in a fresh process.

        The verified call is `AddNewCircPattern(feature, 1, instances, 1.0, spacing, 1, 1,
        PlaneXY, PlaneXY, False, 0.0, True)`: one radial row, the angular row the caller
        asked for, and the XY plane as both rotation centre and rotation axis. Radial rows
        and a non-zero rotation angle are not exposed, because neither was verified.

        It never calls `Part.Update()`. A pattern that CATIA cannot build leaves a broken
        feature behind, which `remove_circular_pattern` takes out again.

        Args:
            name: The new pattern's name. Must be non-empty, without surrounding
                whitespace, and must not contain `"\\"`.
            feature: The feature to copy -- a `Pad`, `Pocket`, fillet, and so on, from
                `part.part_design`. It must belong to the body being modelled in.
            angular_instances: How many instances in total, the original included.
            angular_spacing_deg: The angle between neighbouring instances, in degrees.
            axis: The rotation axis. Only `CIRCULAR_PATTERN_AXIS_Z` is verified.

        Returns:
            The newly created `CircularPattern`, already renamed to `name`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            ParameterTypeError: If `feature` is not a feature wrapper, the instance count
                is not usable, or the spacing is not a number.
            UnsupportedSupportError: If `axis` is not a verified axis.
            CrossBodyReferenceError: If the feature belongs to a different body.
            FeatureConflictError: If a circular pattern named `name` already exists.
            AmbiguousNameError: If two or more already exist with that name.
            PartialCreationError: If it was created but the follow-up rename failed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        if not isinstance(feature, WORK_AT_FEATURES):
            raise ParameterTypeError(
                "A circular pattern copies a Part Design feature from part.part_design, "
                f"not {type(feature).__name__}."
            )
        if axis not in SUPPORTED_CIRCULAR_PATTERN_AXES:
            raise UnsupportedSupportError(
                f"axis must be one of {sorted(SUPPORTED_CIRCULAR_PATTERN_AXES)}; got "
                f"{axis!r}. Only the Z axis has been verified live."
            )
        instances = _validate_instance_count(angular_instances)
        spacing = validate_angle_value(angular_spacing_deg)
        self._require_feature_in_target_body(feature, "circular pattern")
        try:
            reference = self._part_com_object.OriginElements.PlaneXY
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        return self._create_feature(
            name,
            CIRCULAR_PATTERN_KIND,
            "AddNewCircPattern",
            (
                feature.com_object,
                _CIRCULAR_RADIAL_INSTANCES,
                instances,
                _CIRCULAR_RADIAL_STEP,
                spacing,
                _PATTERN_COPY_POSITION,
                _PATTERN_COPY_POSITION,
                reference,
                reference,
                _CIRCULAR_AXIS_REVERSED,
                _CIRCULAR_ROTATION_ANGLE,
                _CIRCULAR_RADIUS_ALIGNED,
            ),
            CircularPattern,
            "circular pattern",
        )

    @property
    def circular_patterns(self) -> "list[CircularPattern]":
        """list[CircularPattern]: Every circular pattern in the body being modelled in.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._list(CIRCULAR_PATTERN_KIND, CircularPattern)

    def get_circular_pattern(self, name: str) -> CircularPattern:
        """Finds a circular pattern by name in the body being modelled in.

        Args:
            name: The pattern's name.

        Returns:
            The matching `CircularPattern`.

        Raises:
            FeatureNotFoundError: If no circular pattern has that name.
            AmbiguousNameError: If two or more do.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._get(CIRCULAR_PATTERN_KIND, CircularPattern, "circular pattern", name)

    def remove_circular_pattern(self, name: str) -> None:
        """Removes a circular pattern by name, leaving the feature it copied in place.

        This does not rebuild and never saves.

        Args:
            name: The pattern's name.

        Raises:
            FeatureNotFoundError: If no circular pattern has that name.
            AmbiguousNameError: If two or more do.
            Auto3dxError: If no editor selection is available, or deletion failed.
        """
        self._remove(name, self.get_circular_pattern, "circular pattern")

    def _resolve_tool_body(self, tool_body: Any, noun: str) -> Any:
        """Resolves and vets the tool body of a boolean operation.

        Args:
            tool_body: A `Body` wrapper, or the name of a body of this Part.
            noun: The operation, for the messages.

        Returns:
            The raw tool `Body` COM object.

        Raises:
            ParameterTypeError: If `tool_body` is neither a body wrapper nor a name.
            BooleanOperationError: If it is not a body of this Part, is the body being
                modelled in, or has already been consumed by another boolean. Nothing
                was changed.
            Auto3dxError: If the bodies cannot be read.
        """
        if not isinstance(tool_body, str) and not hasattr(tool_body, "com_object"):
            raise ParameterTypeError(
                f"The tool body of a boolean {noun} must be a Body from part.bodies or "
                f"its name, not {type(tool_body).__name__}."
            )
        wanted = tool_body if isinstance(tool_body, str) else None
        raw_wanted = None if wanted is not None else tool_body.com_object
        try:
            bodies = self._part_com_object.Bodies
            count = int(bodies.Count)
            candidates = [bodies.Item(index) for index in range(1, count + 1)]
        except pywintypes.com_error as error:
            raise _wrap_com_error(error) from error
        found = None
        names = []
        for candidate in candidates:
            try:
                candidate_name = str(candidate.Name)
            except pywintypes.com_error:
                continue
            names.append(candidate_name)
            if wanted is not None:
                if candidate_name == wanted:
                    found = candidate
            else:
                try:
                    if bool(candidate == raw_wanted):
                        found = candidate
                except pywintypes.com_error:
                    continue
        if found is None:
            label = wanted if wanted is not None else "that body"
            raise BooleanOperationError(
                f"{label!r} is not a body of this Part, so it cannot be the tool of a "
                f"boolean {noun}. Bodies that are there: {names}. A body already consumed "
                "by an earlier boolean is no longer listed."
            )
        target = self._body()
        try:
            if bool(found == target):
                raise BooleanOperationError(
                    f"A boolean {noun} cannot use the body it is applied to as its own "
                    "tool. Open part.work_in(other_body) for the target, or pass a "
                    "different tool body."
                )
        except pywintypes.com_error:
            pass
        try:
            if bool(found.InBooleanOperation):
                raise BooleanOperationError(
                    f"Body {str(found.Name)!r} has already been consumed by a boolean "
                    "operation, so it cannot be used again. Nothing was changed."
                )
        except pywintypes.com_error:
            pass
        return found

    def _create_boolean(
        self, name: str, kind: str, factory_method: str, tool_body: Any, noun: str
    ) -> BooleanOperation:
        """Creates one boolean feature after vetting its tool body.

        Args:
            name: The new feature's name.
            kind: The `type(item).__name__` CATIA gives it.
            factory_method: The `ShapeFactory` method.
            tool_body: The tool body wrapper or name.
            noun: The operation, for messages.

        Returns:
            The newly created `BooleanOperation`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            ParameterTypeError: If `tool_body` is not a body wrapper or a name.
            BooleanOperationError: If the tool body is refused.
            FeatureConflictError: If a feature of this kind already has that name.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        validate_parameter_name(name)
        raw_tool = self._resolve_tool_body(tool_body, noun)
        return self._create_feature(
            name, kind, factory_method, (raw_tool,), BooleanOperation, f"boolean {noun}"
        )

    def create_boolean_remove(self, name: str, tool_body: Any) -> BooleanOperation:
        """Subtracts a tool body from the body being modelled in.

        Live (probe 44): a cylinder removed exactly its overlap from a disc, the update
        succeeded, and the tool body reported `InBooleanOperation` afterwards.

        **The tool body is consumed**: it disappears from `part.bodies` and lives under
        this feature instead. Removing the feature later deletes that body with it
        (`remove_boolean`).

        The target is whichever body is being modelled in, so wrap the call in
        `part.work_in(target_body)` when it is not the main body. This never calls
        `Part.Update()`.

        Args:
            name: The new feature's name.
            tool_body: The `Body` to subtract, or its name.

        Returns:
            The new `BooleanOperation`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            ParameterTypeError: If `tool_body` is not a body wrapper or a name.
            BooleanOperationError: If the tool body is the target body, is not a body of
                this Part, or has already been consumed.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._create_boolean(
            name, BOOLEAN_REMOVE_KIND, "AddNewRemove", tool_body, "remove"
        )

    def create_boolean_add(self, name: str, tool_body: Any) -> BooleanOperation:
        """Adds a tool body into the body being modelled in.

        Live (probe 44): the disc gained exactly the part of the cylinder that lay outside
        it. The tool body is consumed, exactly as for `create_boolean_remove`.

        Args:
            name: The new feature's name.
            tool_body: The `Body` to add, or its name.

        Returns:
            The new `BooleanOperation`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            ParameterTypeError: If `tool_body` is not a body wrapper or a name.
            BooleanOperationError: If the tool body is refused.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._create_boolean(name, BOOLEAN_ADD_KIND, "AddNewAdd", tool_body, "add")

    def create_boolean_intersect(self, name: str, tool_body: Any) -> BooleanOperation:
        """Keeps only what the tool body and the body being modelled in share.

        Live (probe 44): the result was exactly the overlap volume. The tool body is
        consumed, exactly as for `create_boolean_remove`.

        Args:
            name: The new feature's name.
            tool_body: The `Body` to intersect with, or its name.

        Returns:
            The new `BooleanOperation`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            ParameterTypeError: If `tool_body` is not a body wrapper or a name.
            BooleanOperationError: If the tool body is refused.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._create_boolean(
            name, BOOLEAN_INTERSECT_KIND, "AddNewIntersect", tool_body, "intersect"
        )

    def create_boolean_assemble(self, name: str, tool_body: Any) -> BooleanOperation:
        """Assembles a tool body into the body being modelled in.

        Live (probe 44) this gave the same volume as `create_boolean_add` for two solids
        that only overlapped; assemble differs from add by honouring the tool body's own
        add/remove history, which this SDK has not exercised. The tool body is consumed,
        exactly as for `create_boolean_remove`.

        Args:
            name: The new feature's name.
            tool_body: The `Body` to assemble, or its name.

        Returns:
            The new `BooleanOperation`.

        Raises:
            ParameterNameError: If `name` is not usable as a name.
            ParameterTypeError: If `tool_body` is not a body wrapper or a name.
            BooleanOperationError: If the tool body is refused.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        return self._create_boolean(
            name, BOOLEAN_ASSEMBLE_KIND, "AddNewAssemble", tool_body, "assemble"
        )

    @property
    def boolean_operations(self) -> "list[BooleanOperation]":
        """list[BooleanOperation]: Every boolean in the body being modelled in.

        Raises:
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        found: list[BooleanOperation] = []
        for kind in BOOLEAN_KINDS:
            found.extend(self._list(kind, BooleanOperation))
        return found

    def get_boolean(self, name: str) -> BooleanOperation:
        """Finds a boolean operation by name, whichever of the four kinds it is.

        Args:
            name: The feature's name.

        Returns:
            The matching `BooleanOperation`.

        Raises:
            FeatureNotFoundError: If no boolean has that name.
            AmbiguousNameError: If two or more do.
            Auto3dxError: If the underlying COM call fails unexpectedly.
        """
        matches = [item for item in self.boolean_operations if item.name == name]
        if not matches:
            raise FeatureNotFoundError(f"No boolean operation named {name!r} was found.")
        if len(matches) > 1:
            raise AmbiguousNameError(
                f"{len(matches)} boolean operations are named {name!r}; refusing to guess."
            )
        return matches[0]

    def remove_boolean(self, name: str, *, delete_consumed_body: bool = False) -> None:
        """Removes a boolean operation -- and the body it consumed.

        **This is destructive beyond the feature itself.** Live (probe 44), deleting a
        boolean took the consumed tool body with it: the body did not come back, its name
        could no longer be found, and only the target body's original geometry returned.
        There is no verified way to release a tool body back out of a boolean, so this asks
        the caller to say that losing it is intended.

        This does not rebuild and never saves.

        Args:
            name: The boolean feature's name.
            delete_consumed_body: Must be `True`. Deleting the feature deletes the tool
                body and everything in it.

        Raises:
            FeatureNotFoundError: If no boolean has that name.
            AmbiguousNameError: If two or more do.
            BooleanOperationError: If `delete_consumed_body` is not `True`. Nothing was
                changed.
            Auto3dxError: If no editor selection is available, or deletion failed.
        """
        operation = self.get_boolean(name)
        if not delete_consumed_body:
            try:
                tool = operation.tool_body_name
            except Auto3dxError:
                tool = "the consumed body"
            raise BooleanOperationError(
                f"Removing boolean {name!r} would also delete {tool!r}, the body it "
                "consumed, with everything in it; CATIA gives no way to release that body "
                "again. Nothing was changed. Pass delete_consumed_body=True to confirm."
            )
        with self._generation.mutation():
            delete_via_selection(
                self._selection,
                operation.com_object,
                f"boolean operation {name!r}",
                self._part_com_object,
            )

    def remove_rectangular_pattern(self, pattern: RectangularPattern) -> None:
        """Removes a rectangular pattern through the owning editor's Selection.

        Rectangular patterns currently have no verified safe name lookup. This
        method therefore accepts the wrapper returned by
        :meth:`create_rectangular_pattern`, which also gives callers a public
        cleanup route when a later :meth:`Part.update` fails.

        Args:
            pattern: The rectangular pattern wrapper to delete.

        Raises:
            ParameterTypeError: If `pattern` is not a `RectangularPattern`.
            Auto3dxError: If no editor selection is available, or deletion
                failed.
        """
        if not isinstance(pattern, RectangularPattern):
            raise ParameterTypeError(
                "pattern must be a RectangularPattern returned by "
                f"create_rectangular_pattern(), not {type(pattern).__name__}."
            )
        with self._generation.mutation():
            delete_via_selection(
                self._selection,
                pattern.com_object,
                "rectangular pattern",
                self._part_com_object,
            )
