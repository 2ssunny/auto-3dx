"""`body.features`: the body's feature listing, plus intent methods that build in that body.

`Body.features` has always been a tuple of `FeatureInfo`. `BodyFeatures` IS that tuple --
same equality, length, iteration and indexing -- and also carries `pad`, `pocket`, `hole`,
`fillet`, `chamfer` and `circular_pattern`. The tuple is the listing as it was when
`body.features` was read; the methods always act on the live model, so read
`body.features` again to see what they added.

Every method is one Level 2 call inside `part.work_in(body)`:

    pad              -> part.part_design.create_pad
    pocket           -> part.part_design.create_pocket
    hole             -> part.part_design.create_hole(..., origin=, diameter=, limit=, bottom=)
    fillet           -> part.part_design.create_edge_fillet
    chamfer          -> part.part_design.create_chamfer (length/angle mode)
    circular_pattern -> part.part_design.create_circular_pattern

so validation, staleness, cross-body checks, naming and errors are exactly Level 2's. None
of them rebuilds: call `part.update()` (or `body.update()`) when the batch is done.
"""

import math
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from auto_3dx.errors import ParameterTypeError, UnsupportedOperationError, ValidationError
from auto_3dx.geometry.edges import Edge
from auto_3dx.geometry.faces import Face
from auto_3dx.geometry.facts import SURFACE_PLANAR
from auto_3dx.geometry.part_design import (
    CHAMFER_ORIENTATION_0,
    CHAMFER_PROPAGATION_0,
    CIRCULAR_PATTERN_AXIS_Z,
    HOLE_BOTTOM_FLAT,
    HOLE_LIMIT_BLIND,
    Chamfer,
    CircularPattern,
    ConstRadEdgeFillet,
    Hole,
    Pad,
    Pocket,
)
from auto_3dx.highlevel.directions import INTO_MATERIAL, extrusion_direction
from auto_3dx.parameters.parameter import MILLIMETRE

if TYPE_CHECKING:
    from auto_3dx.core.part import Part
    from auto_3dx.geometry.bodies import Body

FULL_CIRCLE_DEG: float = 360.0
"""A `total_angle_deg` of a full turn spreads the copies evenly: spacing = 360 / n."""

DEFAULT_CHAMFER_ANGLE_DEG: float = 45.0
"""The angle every live chamfer used (probe 35)."""

_AXIS_TOLERANCE: float = 1e-6
_HOLE_DIRECTIONS: "frozenset[str]" = frozenset({INTO_MATERIAL})
"""The only hole direction with evidence: CATIA's default, into the material (46m, 46p)."""


def hole_origin(center: Any, face: Face) -> "tuple[float, float, float]":
    """Turns a hole `center` into the Part point Level 2 `create_hole(origin=...)` takes.

    A 3-tuple is used as is. A 2-tuple is allowed on a planar face whose normal is parallel
    to a world axis and names the two OTHER world coordinates in X, Y, Z order -- normal Z:
    `(x, y)`; normal X: `(y, z)`; normal Y: `(x, z)` -- and the third comes from the face's
    plane. Anything else is refused rather than projected.

    Args:
        center: `(a, b)` or `(x, y, z)` in millimetres.
        face: The planar `Face` the hole starts on.

    Returns:
        `(x, y, z)` in Part millimetres.

    Raises:
        ParameterTypeError: If `center` is not two or three numbers.
        UnsupportedOperationError: If a 2-tuple is used on a face that is not planar or not
            perpendicular to a world axis.
        Auto3dxError: If the face cannot be measured.
    """
    if not isinstance(center, (tuple, list)) or len(center) not in (2, 3):
        raise ParameterTypeError(
            f"center must be (a, b) or (x, y, z) in millimetres, not {center!r}."
        )
    for value in center:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ParameterTypeError(f"center must hold numbers, not {center!r}.")
    if len(center) == 3:
        return (float(center[0]), float(center[1]), float(center[2]))
    facts = face.geometry
    normal = facts.normal
    if facts.surface_type != SURFACE_PLANAR or normal is None:
        raise UnsupportedOperationError(
            f"A two-number center needs a planar face; this one measures as "
            f"{facts.surface_type!r}. Give (x, y, z)."
        )
    axis = next(
        (index for index in range(3) if abs(abs(normal[index]) - 1.0) <= _AXIS_TOLERANCE),
        None,
    )
    if axis is None:
        raise UnsupportedOperationError(
            f"The face's normal {normal} is not parallel to a world axis, so a two-number "
            "center is ambiguous. Give (x, y, z)."
        )
    others = [index for index in range(3) if index != axis]
    point = [0.0, 0.0, 0.0]
    point[others[0]] = float(center[0])
    point[others[1]] = float(center[1])
    point[axis] = float(facts.center_mm[axis])
    return (point[0], point[1], point[2])


def pattern_spacing(
    instances: Any,
    spacing_deg: "float | None",
    total_angle_deg: "float | None",
    full_circle: bool = False,
) -> float:
    """Resolves the angle between neighbouring copies from exactly one of two intents.

    CATIA's complete-crown mode was accepted and ignored live (probe 46w), so a total angle
    is converted here into the verified angular spacing instead: a full turn gives
    `360 / instances` (the last copy does not land on the first); any other total spreads
    the copies from the first to the last, `total / (instances - 1)`.

    Raises:
        ParameterTypeError: If neither or both are given, or a value is not usable.
    """
    if not isinstance(full_circle, bool):
        raise ParameterTypeError(f"full_circle must be a bool, not {type(full_circle).__name__}.")
    if full_circle:
        if spacing_deg is not None or total_angle_deg is not None:
            raise ParameterTypeError(
                "full_circle=True already fixes the spacing (360 / instances); do not also "
                "give spacing_deg or total_angle_deg."
            )
        total_angle_deg = FULL_CIRCLE_DEG
    if (spacing_deg is None) == (total_angle_deg is None):
        raise ParameterTypeError(
            "Give exactly one of spacing_deg, total_angle_deg or full_circle=True."
        )
    if spacing_deg is not None:
        return float(spacing_deg)
    if isinstance(instances, bool) or not isinstance(instances, int) or instances < 2:
        raise ParameterTypeError(f"instances must be an int of at least 2, not {instances!r}.")
    if (
        isinstance(total_angle_deg, bool)
        or not isinstance(total_angle_deg, (int, float))
        or not 0.0 < float(total_angle_deg) <= FULL_CIRCLE_DEG
    ):
        raise ParameterTypeError(f"total_angle_deg must be in (0, 360], not {total_angle_deg!r}.")
    total = float(total_angle_deg)
    if math.isclose(total, FULL_CIRCLE_DEG, rel_tol=0.0, abs_tol=1e-9):
        return FULL_CIRCLE_DEG / instances
    return total / (instances - 1)


def _single_edge(edges: Any) -> Edge:
    """Accepts one `Edge`, or a sequence holding exactly one."""
    if isinstance(edges, Edge):
        return edges
    if isinstance(edges, Sequence) and not isinstance(edges, str):
        items = list(edges)
        if len(items) == 1 and isinstance(items[0], Edge):
            return items[0]
        if len(items) > 1:
            raise UnsupportedOperationError(
                "A fillet over several edges at once has no live evidence (only single-edge "
                f"fillets were verified); got {len(items)} edges. Make one fillet per edge."
            )
    raise ParameterTypeError(
        f"edges must be an Edge or a list of one Edge, not {type(edges).__name__}."
    )


class BodyFeatures(tuple):
    """A body's features as `FeatureInfo` values, plus methods that add features to it.

    Obtain it as `body.features`. See the module docstring for how each method maps onto
    Level 2.
    """

    _part: "Part | None"
    _body: "Body"

    def __new__(
        cls, features: "Iterable[Any]", part: "Part | None", body: "Body"
    ) -> "BodyFeatures":
        """Builds the listing.

        Args:
            features: The body's `FeatureInfo` values, in tree order.
            part: The `Part` the body belongs to, which the methods build through. `None`
                for a body built without one; its methods then refuse.
            body: The `Body` itself.
        """
        instance = super().__new__(cls, features)
        instance._part = part
        instance._body = body
        return instance

    def _require_part(self) -> "Part":
        if self._part is None:
            raise ValidationError(
                "This body was not obtained through part.bodies, so it cannot build "
                "features. Use part.bodies.get(name) or part.bodies.main."
            )
        return self._part

    def pad(
        self,
        name: str,
        profile: Any,
        length: float,
        *,
        direction: "str | None" = None,
        unit: str = MILLIMETRE,
    ) -> Pad:
        """Extrudes a profile sketch into a new pad in this body.

        Args:
            name: The pad's name.
            profile: The `Sketch` to extrude.
            length: How far to extrude.
            direction: `None` (CATIA's default: along the sketch normal),
                `"along_normal"`, `"against_normal"`, `"+X"` ... `"-Z"`, or
                `"into_material"`/`"out_of_material"` for a sketch created on a face
                (`auto_3dx.highlevel.directions`).
            unit: The unit of `length`. Defaults to millimetres.

        Returns:
            The new `Pad`. Not rebuilt: call `part.update()`.

        Raises:
            ParameterTypeError: If `direction` is unknown.
            UnsupportedOperationError: If `direction` cannot be answered for `profile`.
            Auto3dxError: Whatever `part.part_design.create_pad` raises.
        """
        part = self._require_part()
        level2 = extrusion_direction(direction, profile)
        with part.work_in(self._body):
            return part.part_design.create_pad(name, profile, length, unit, level2)

    def pocket(
        self,
        name: str,
        profile: Any,
        depth: float,
        *,
        direction: "str | None" = None,
        unit: str = MILLIMETRE,
    ) -> Pocket:
        """Cuts a profile sketch into the solid of this body.

        CATIA's default pocket direction is AGAINST the sketch normal, which on a sketch
        created on a face is into the material (probe 46k) and on an origin plane under a
        solid is away from it (a zero-effect cut, probe 45). Say which you mean.

        Args:
            name: The pocket's name.
            profile: The `Sketch` to cut along.
            depth: How deep to cut.
            direction: As for `pad`.
            unit: The unit of `depth`. Defaults to millimetres.

        Returns:
            The new `Pocket`. Not rebuilt: call `part.update()`.

        Raises:
            ParameterTypeError: If `direction` is unknown.
            UnsupportedOperationError: If `direction` cannot be answered for `profile`.
            Auto3dxError: Whatever `part.part_design.create_pocket` raises.
        """
        part = self._require_part()
        level2 = extrusion_direction(direction, profile)
        with part.work_in(self._body):
            return part.part_design.create_pocket(name, profile, depth, unit, level2)

    def hole(
        self,
        name: str,
        *,
        support: Face,
        center: Any,
        diameter: float,
        depth: "float | None" = None,
        limit: str = HOLE_LIMIT_BLIND,
        direction: str = INTO_MATERIAL,
        bottom: str = HOLE_BOTTOM_FLAT,
        unit: str = MILLIMETRE,
    ) -> Hole:
        """Drills a hole at a point of a planar face of this body.

        Every attribute is written explicitly -- diameter, bottom and limit -- because
        CATIA carries a hole's settings over to the next hole (probe 46q).

        Args:
            name: The hole's name.
            support: The planar `Face` to drill from, from a current snapshot.
            center: `(x, y, z)`, or two numbers on a face perpendicular to a world axis
                (`hole_origin`).
            diameter: The hole diameter.
            depth: The depth of a blind hole; must be omitted for `"through_all"`.
            limit: `"blind"` (the default) or `"through_all"`.
            direction: Only `"into_material"`, CATIA's verified default.
            bottom: `"flat"` (the default; the volume is exactly a cylinder) or `"v"`
                (a 120-degree drill point).
            unit: The unit of `depth` and `diameter`. Defaults to millimetres.

        Returns:
            The new `Hole`. Not rebuilt: call `part.update()`.

        Raises:
            ParameterTypeError: If an argument is invalid (see `create_hole`).
            UnsupportedOperationError: If `direction` is not `"into_material"`, or `center`
                cannot be placed on this face.
            Auto3dxError: Whatever `part.part_design.create_hole` raises.
        """
        part = self._require_part()
        if direction not in _HOLE_DIRECTIONS:
            raise UnsupportedOperationError(
                f"A hole can only drill {INTO_MATERIAL!r} (CATIA's default, verified on a top "
                f"and a side face); got {direction!r}. Reversing a hole has no live evidence."
            )
        if not isinstance(support, Face):
            raise ParameterTypeError(
                f"support must be a Face from part.topology.faces(), not {type(support).__name__}."
            )
        origin = hole_origin(center, support)
        with part.work_in(self._body):
            return part.part_design.create_hole(
                name,
                support,
                depth,
                unit,
                origin=origin,
                diameter=diameter,
                limit=limit,
                bottom=bottom,
            )

    def fillet(
        self, name: str, *, edges: Any, radius: float, unit: str = MILLIMETRE
    ) -> ConstRadEdgeFillet:
        """Rounds one edge of this body with a constant radius.

        Args:
            name: The fillet's name.
            edges: One `Edge`, or a list of exactly one, from a current snapshot.
            radius: The fillet radius.
            unit: The unit of `radius`. Defaults to millimetres.

        Returns:
            The new fillet. Not rebuilt: call `part.update()`.

        Raises:
            UnsupportedOperationError: If more than one edge is given.
            ParameterTypeError: If `edges` holds no `Edge`.
            Auto3dxError: Whatever `part.part_design.create_edge_fillet` raises.
        """
        part = self._require_part()
        edge = _single_edge(edges)
        with part.work_in(self._body):
            return part.part_design.create_edge_fillet(name, edge, radius, unit)

    def chamfer(
        self,
        name: str,
        *,
        edge: Edge,
        length: float,
        angle: float = DEFAULT_CHAMFER_ANGLE_DEG,
        unit: str = MILLIMETRE,
    ) -> Chamfer:
        """Bevels one edge of this body by a length and an angle.

        Uses the verified length/angle mode with CATIA's first propagation and orientation
        values (probe 35), which gave equal set-backs at 45 degrees.

        Args:
            name: The chamfer's name.
            edge: The `Edge` to bevel, from a current snapshot.
            length: The chamfer length.
            angle: The chamfer angle in degrees. Defaults to 45.
            unit: The unit of `length`. Defaults to millimetres.

        Returns:
            The new `Chamfer`. Not rebuilt: call `part.update()`.

        Raises:
            Auto3dxError: Whatever `part.part_design.create_chamfer` raises.
        """
        part = self._require_part()
        with part.work_in(self._body):
            return part.part_design.create_chamfer(
                name, edge, length, angle, CHAMFER_PROPAGATION_0, CHAMFER_ORIENTATION_0, unit
            )

    def circular_pattern(
        self,
        name: str,
        *,
        feature: Any,
        instances: int,
        spacing_deg: "float | None" = None,
        total_angle_deg: "float | None" = None,
        axis: Any = CIRCULAR_PATTERN_AXIS_Z,
        reverse: bool = False,
        full_circle: bool = False,
    ) -> CircularPattern:
        """Copies a feature of this body around an axis.

        Args:
            name: The pattern's name.
            feature: The feature to copy, a wrapper from `part.part_design` or from another
                `body.features` call.
            instances: How many copies in total, the original included.
            spacing_deg: The angle between neighbouring copies; or
            total_angle_deg: the angle the copies spread over (360 for a full circle); or
            full_circle: `True` to spread `instances` copies evenly over 360 degrees.
            axis: `"X"`, `"Y"`, `"Z"`, a cylindrical `Face` or a linear `Edge`.
            reverse: Turn the other way (documented for Z only).

        Returns:
            The new `CircularPattern`. Not rebuilt: call `part.update()`.

        Raises:
            ParameterTypeError: If the spacing is not given exactly once.
            Auto3dxError: Whatever `part.part_design.create_circular_pattern` raises.
        """
        part = self._require_part()
        spacing = pattern_spacing(instances, spacing_deg, total_angle_deg, full_circle)
        with part.work_in(self._body):
            return part.part_design.create_circular_pattern(
                name, feature, instances, spacing, axis, reverse=reverse
            )
