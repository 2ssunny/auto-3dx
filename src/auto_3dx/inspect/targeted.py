"""Targeted, read-only inspection of ONE named feature or sketch.

`part.inspect.summary()` walks the whole model and both B-rep searches; an agent that
wants "what is the depth of Pocket.1?" or "what does sketch PROFILE hold?" should not pay
for that. `inspect.feature(name)` and `inspect.sketch(name)` find exactly one object by
name across every body and read only its own verified properties, through the same
wrappers `part.part_design` returns, so no value is read two different ways.

Everything here is read-only: nothing advances the model generation, rebuilds, touches
the selection or the In-Work Object, or stringifies a raw COM object (formatting a raw
dispatch object is not a safe read in this release).
"""

import dataclasses
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import pywintypes

from auto_3dx._com import automation_error
from auto_3dx.errors import (
    AmbiguousNameError,
    Auto3dxError,
    FeatureNotFoundError,
    SketchNotFoundError,
)
from auto_3dx.geometry.part_design import (
    BOOLEAN_KINDS,
    CHAMFER_KIND,
    CIRCULAR_PATTERN_KIND,
    EDGE_FILLET_KIND,
    GROOVE_KIND,
    HOLE_KIND,
    PAD_KIND,
    POCKET_KIND,
    SHAFT_KIND,
    SHELL_KIND,
    THICKNESS_KIND,
    BooleanOperation,
    Chamfer,
    CircularPattern,
    ConstRadEdgeFillet,
    Groove,
    Hole,
    Pad,
    Pocket,
    Shaft,
    Shell,
    Thickness,
)
from auto_3dx.geometry.sketch import Sketch
from auto_3dx.geometry.sketch_geometry import SketchGeometry

if TYPE_CHECKING:
    from auto_3dx.core.part import Part

_FIRST_COM_INDEX = 1


@dataclasses.dataclass(frozen=True)
class FeatureDetails:
    """One feature, read on its own: identity, state, and its verified dimensions.

    Attributes:
        name: The feature's name.
        kind: CATIA's wrapper type name, such as ``"Pad"`` or ``"Hole"``.
        body_name: The body that holds it.
        up_to_date: `Part.IsUpToDate(feature)`.
        active: Whether it contributes to the geometry (`False` when suppressed); `None`
            when CATIA does not report an Activity parameter for it.
        parameters: The dimensions and settings this SDK can read for its kind, by the
            names the wrapper uses (``{"length": 20.0, "direction": ...}`` for a pad,
            ``{"diameter": 6.0, "depth": 8.0, "limit": "blind", ...}`` for a hole). Empty
            for a kind the SDK does not wrap: the feature is still reported.
    """

    name: str
    kind: str
    body_name: str
    up_to_date: bool
    active: "bool | None"
    parameters: "Mapping[str, Any]"


def _pad(feature: Pad) -> "dict[str, Any]":
    return {"length": feature.length, "direction": feature.direction}


def _pocket(feature: Pocket) -> "dict[str, Any]":
    return {"depth": feature.depth, "direction": feature.direction}


def _revolve(feature: Any) -> "dict[str, Any]":
    return {"first_angle": feature.first_angle, "second_angle": feature.second_angle}


def _hole(feature: Hole) -> "dict[str, Any]":
    return {
        "diameter": feature.diameter,
        "depth": feature.depth,
        "limit": feature.limit,
        "bottom": feature.bottom,
        "origin": feature.origin,
        "direction": feature.direction,
    }


def _fillet(feature: ConstRadEdgeFillet) -> "dict[str, Any]":
    return {"radius": feature.radius}


def _chamfer(feature: Chamfer) -> "dict[str, Any]":
    return {"length1": feature.length1, "angle": feature.angle}


def _shell(feature: Shell) -> "dict[str, Any]":
    return {
        "internal_thickness": feature.internal_thickness,
        "external_thickness": feature.external_thickness,
    }


def _thickness(feature: Thickness) -> "dict[str, Any]":
    return {"offset": feature.offset}


def _pattern(feature: CircularPattern) -> "dict[str, Any]":
    return {"instances": feature.instances, "spacing_deg": feature.spacing_deg}


def _boolean(feature: BooleanOperation) -> "dict[str, Any]":
    return {"tool_body_name": feature.tool_body_name}


_READERS: "dict[str, tuple[type, Callable[[Any], dict[str, Any]]]]" = {
    PAD_KIND: (Pad, _pad),
    POCKET_KIND: (Pocket, _pocket),
    SHAFT_KIND: (Shaft, _revolve),
    GROOVE_KIND: (Groove, _revolve),
    HOLE_KIND: (Hole, _hole),
    EDGE_FILLET_KIND: (ConstRadEdgeFillet, _fillet),
    CHAMFER_KIND: (Chamfer, _chamfer),
    SHELL_KIND: (Shell, _shell),
    THICKNESS_KIND: (Thickness, _thickness),
    CIRCULAR_PATTERN_KIND: (CircularPattern, _pattern),
    **{kind: (BooleanOperation, _boolean) for kind in BOOLEAN_KINDS},
}
"""Kind -> (wrapper, reader of its verified properties)."""


def _read(action: str, read: Callable[[], Any]) -> Any:
    try:
        return read()
    except pywintypes.com_error as error:
        raise automation_error(error, f"reading {action}") from error


def _attr(obj: Any, member: str, label: str) -> Any:
    """Reads one COM member, translating a COM failure."""
    try:
        return getattr(obj, member)
    except pywintypes.com_error as error:
        raise automation_error(error, f"reading {label}") from error


def _item(collection: Any, key: Any, label: str) -> Any:
    """Reads one collection item, translating a COM failure."""
    try:
        return collection.Item(key)
    except pywintypes.com_error as error:
        raise automation_error(error, f"reading {label}") from error


def _items(collection: Any, label: str) -> "list[Any]":
    count = int(_attr(collection, "Count", f"{label}.Count"))
    return [
        _item(collection, index, f"{label}.Item({index})")
        for index in range(_FIRST_COM_INDEX, count + _FIRST_COM_INDEX)
    ]


def _named_in_bodies(
    part: "Part", member: str, name: str, body: "str | None"
) -> "list[tuple[Any, str]]":
    """Every `(raw object, body name)` named `name` in each body's `Shapes` or `Sketches`."""
    found = []
    for raw_body in _items(_attr(part.com_object, "Bodies", "Part.Bodies"), "Part.Bodies"):
        body_name = str(_attr(raw_body, "Name", "Body.Name"))
        if body is not None and body_name != body:
            continue
        collection = _attr(raw_body, member, f"Body.{member}")
        if collection is None:
            continue
        for item in _items(collection, f"{body_name}.{member}"):
            if str(_attr(item, "Name", f"{member} name")) == name:
                found.append((item, body_name))
    return found


def _exactly_one(
    found: "list[tuple[Any, str]]", noun: str, name: str, missing: type
) -> "tuple[Any, str]":
    if not found:
        raise missing(f"No {noun} named {name!r} exists in any body of this Part.")
    if len(found) > 1:
        bodies = sorted({body for _, body in found})
        raise AmbiguousNameError(
            f"{len(found)} {noun}s are named {name!r} (in bodies {bodies}); pass body= to "
            "say which one."
        )
    return found[0]


def feature_details(part: "Part", name: str, body: "str | None" = None) -> FeatureDetails:
    """Reads one named feature without walking the rest of the model.

    Args:
        part: The Part to read.
        name: The feature's name.
        body: The body to look in; `None` looks in every body.

    Returns:
        The `FeatureDetails`.

    Raises:
        FeatureNotFoundError: If no feature has that name.
        AmbiguousNameError: If several do (in one body or across bodies).
        AutomationError: If a read fails.
    """
    raw, body_name = _exactly_one(
        _named_in_bodies(part, "Shapes", name, body), "feature", name, FeatureNotFoundError
    )
    kind = type(raw).__name__
    raw_part = part.com_object
    up_to_date = bool(_read("Part.IsUpToDate", lambda: raw_part.IsUpToDate(raw)))
    parameters: dict[str, Any] = {}
    active: "bool | None" = None
    if kind in _READERS:
        wrapper_cls, reader = _READERS[kind]
        wrapper = wrapper_cls(raw)
        parameters = reader(wrapper)
        try:
            active = wrapper.is_active
        except Auto3dxError:
            # A kind without an Activity parameter in this release: reported as unknown.
            active = None
    return FeatureDetails(
        name=name,
        kind=kind,
        body_name=body_name,
        up_to_date=up_to_date,
        active=active,
        parameters=MappingProxyType(parameters),
    )


def sketch_geometry(part: "Part", name: str, body: "str | None" = None) -> SketchGeometry:
    """Reads one named sketch -- elements, constraints, frame -- as plain values.

    Args:
        part: The Part to read.
        name: The sketch's name.
        body: The body to look in; `None` looks in every body.

    Returns:
        The sketch's `SketchGeometry` (see `Sketch.geometry()`).

    Raises:
        SketchNotFoundError: If no sketch has that name.
        AmbiguousNameError: If several do.
        AutomationError: If a read fails.
    """
    raw, _ = _exactly_one(
        _named_in_bodies(part, "Sketches", name, body), "sketch", name, SketchNotFoundError
    )
    return Sketch(raw, part_com_object=part.com_object).geometry()
