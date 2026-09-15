"""Read-only inspection of a Part: what the model already contains.

An agent has to find out what is in a model before it changes anything, so reading
a model reliably matters as much as building one (`docs/api-design.md` section 11).
Inspection returns frozen dataclasses. Text rendering is a convenience on top, never
the primary output, so a caller can act on the data without parsing prose.

Every field here comes from a read already backed by live evidence:

* the Part name and `Part.IsUpToDate()`, pinned by the integration suite;
* user parameters through `RootParameterSet.DirectParameters`, verified live and used
  by `ParameterCollection.user_parameters()`;
* sketch names through `Body.Sketches`, verified live;
* features through `Body.Shapes` enumeration and each item's `Name` and
  `type(item).__name__`, live-verified for all thirteen kinds the SDK creates;
* bodies through `Part.Bodies` `Count`/`Item`/`Name`, with the main body recognised by
  COM identity (`Bodies.Item(1) == MainBody`, probe 38);
* geometrical sets through `Part.HybridBodies`, each set's `HybridShapes` items with
  their `Name` and type name, and the count of its nested `HybridBodies` (probe 38);
* edge and face counts through `part.topology`, whose searches restore the user's
  CATIA selection;
* the In-Work Object through `Part.InWorkObject`, its `Name` and type name, and COM
  identity with `MainBody`. Live (2026-09-15) it reported a `Pad` and the main `Body`:
  creating a pad made the new pad the In-Work Object, and creating a plane handed it
  back to the main body.

Deliberately absent, because no live read backs them: the contents of nested
geometrical sets, geometrical sets inside a body, and sketches inside a geometrical
set.

Inspection never advances the model generation, never rebuilds, and leaves the
selection and the In-Work Object as it found them.
"""

import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

import pywintypes

from auto_3dx._com import automation_error
from auto_3dx.errors import ValidationError
from auto_3dx.geometry.part_design import (
    CHAMFER_KIND,
    EDGE_FILLET_KIND,
    GROOVE_KIND,
    HOLE_KIND,
    MIRROR_KIND,
    PAD_KIND,
    POCKET_KIND,
    RECTANGULAR_PATTERN_KIND,
    RIB_KIND,
    SHAFT_KIND,
    SHELL_KIND,
    SLOT_KIND,
    THICKNESS_KIND,
)
from auto_3dx.parameters.parameter import ParameterInfo

if TYPE_CHECKING:
    from auto_3dx.core.part import Part

_T = TypeVar("_T")
_FIRST_COM_INDEX = 1

SUPPORTED_FEATURE_KINDS: frozenset[str] = frozenset(
    {
        PAD_KIND,
        POCKET_KIND,
        SHAFT_KIND,
        GROOVE_KIND,
        MIRROR_KIND,
        RIB_KIND,
        SLOT_KIND,
        RECTANGULAR_PATTERN_KIND,
        EDGE_FILLET_KIND,
        CHAMFER_KIND,
        SHELL_KIND,
        THICKNESS_KIND,
        HOLE_KIND,
    }
)
"""The feature kinds `part.part_design` can create, list and remove."""


@dataclasses.dataclass(frozen=True)
class FeatureInfo:
    """One solid feature in a body, in model-tree order.

    Attributes:
        name: The feature's name as CATIA reports it.
        kind: The CATIA wrapper type name, such as ``"Pad"`` or ``"ConstRadEdgeFillet"``.
            A feature created in the CATIA user interface can be of a kind the SDK
            does not wrap; it is still listed, with its real kind.
        supported: Whether `part.part_design` can create, list and remove this feature.
            It works on the main body only, so a feature in any other body is `False`
            whatever its kind.
    """

    name: str
    kind: str
    supported: bool


@dataclasses.dataclass(frozen=True)
class BodyInfo:
    """One body of the Part, in `Part.Bodies` order.

    Attributes:
        name: The body's name.
        is_main: Whether this is the Part's main body, the one `part.part_design` and
            `part.sketches` work on.
        features: The body's solid features, in model-tree order.
        sketches: The body's sketch names, in model-tree order.
    """

    name: str
    is_main: bool
    features: "tuple[FeatureInfo, ...]"
    sketches: "tuple[str, ...]"


@dataclasses.dataclass(frozen=True)
class GeometryInfo:
    """One element of a geometrical set, such as a plane.

    Attributes:
        name: The element's name.
        kind: The CATIA wrapper type name, such as ``"HybridShapePlaneOffset"``.
    """

    name: str
    kind: str


@dataclasses.dataclass(frozen=True)
class GeometricalSetInfo:
    """One geometrical set directly under the Part, in `Part.HybridBodies` order.

    Attributes:
        name: The set's name.
        elements: The set's own elements, in model-tree order.
        nested_set_count: How many geometrical sets are nested in this one. Their
            contents are not reported: no live read has verified them.
    """

    name: str
    elements: "tuple[GeometryInfo, ...]"
    nested_set_count: int


@dataclasses.dataclass(frozen=True)
class TopologyCounts:
    """How many edges and faces `part.topology` currently finds.

    Attributes:
        edges: The length of a fresh `part.topology.edges()` snapshot.
        faces: The length of a fresh `part.topology.faces()` snapshot.
    """

    edges: int
    faces: int


@dataclasses.dataclass(frozen=True)
class InWorkObjectInfo:
    """The Part's In-Work Object: where CATIA puts the next feature it creates.

    A value, not a handle: it never carries the COM object, so it cannot be used to
    change the model.

    Attributes:
        name: The object's name as CATIA reports it.
        kind: The CATIA wrapper type name. Observed live: ``"Body"`` for the main body
            and ``"Pad"`` after creating a pad, which makes the new pad the In-Work
            Object. Other kinds are reported as CATIA names them.
        is_main_body: Whether it is the Part's main body, by COM identity rather than
            by name.
    """

    name: str
    kind: str
    is_main_body: bool


@dataclasses.dataclass(frozen=True)
class PartSummary:
    """A structured snapshot of what a Part contains.

    Attributes:
        name: The Part's name.
        up_to_date: CATIA's rebuild status. `False` means a change has not been
            rebuilt yet; it is not an unsaved-change indicator.
        features: The main body's solid features, in model-tree order.
        sketches: The main body's sketch names, in model-tree order.
        parameters: The user parameters, excluding the dimensions features expose.
        bodies: Every body, including the main body, in `Part.Bodies` order.
        geometrical_sets: The geometrical sets directly under the Part.
        topology: Edge and face counts, or `None` when this Part has no editor
            selection to search with.
        in_work_object: The In-Work Object, or `None` when CATIA reports none.
    """

    name: str
    up_to_date: bool
    features: "tuple[FeatureInfo, ...]"
    sketches: "tuple[str, ...]"
    parameters: "tuple[ParameterInfo, ...]"
    bodies: "tuple[BodyInfo, ...]" = ()
    geometrical_sets: "tuple[GeometricalSetInfo, ...]" = ()
    topology: "TopologyCounts | None" = None
    in_work_object: "InWorkObjectInfo | None" = None

    def render(self) -> str:
        """Formats the summary for a person to read.

        The dataclass fields remain the contract; this text is for display only and
        its layout may change.

        Returns:
            A multi-line, human-readable description.
        """
        lines = [
            f"Part: {self.name}",
            f"Update status: {'up to date' if self.up_to_date else 'needs update'}",
            f"Features ({len(self.features)})",
        ]
        for feature in self.features:
            note = "" if feature.supported else ", not supported by auto-3dx"
            lines.append(f"- {feature.name} ({feature.kind}{note})")
        lines.append(f"Sketches ({len(self.sketches)})")
        lines.extend(f"- {sketch}" for sketch in self.sketches)
        lines.append(f"Parameters ({len(self.parameters)})")
        for parameter in self.parameters:
            unit = f" {parameter.unit}" if parameter.unit else ""
            lines.append(f"- {parameter.short_name} = {parameter.value}{unit}")
        lines.append(f"Bodies ({len(self.bodies)})")
        for body in self.bodies:
            role = "main body, " if body.is_main else ""
            lines.append(
                f"- {body.name} ({role}{len(body.features)} features, "
                f"{len(body.sketches)} sketches)"
            )
        lines.append(f"Geometrical sets ({len(self.geometrical_sets)})")
        for geometrical_set in self.geometrical_sets:
            nested = (
                f", {geometrical_set.nested_set_count} nested sets not listed"
                if geometrical_set.nested_set_count
                else ""
            )
            lines.append(
                f"- {geometrical_set.name} ({len(geometrical_set.elements)} elements{nested})"
            )
            lines.extend(
                f"  - {element.name} ({element.kind})" for element in geometrical_set.elements
            )
        if self.in_work_object is None:
            lines.append("In-Work Object: none")
        else:
            role = ", main body" if self.in_work_object.is_main_body else ""
            lines.append(
                f"In-Work Object: {self.in_work_object.name} "
                f"({self.in_work_object.kind}{role})"
            )
        if self.topology is None:
            lines.append("Topology: not available (no editor selection)")
        else:
            lines.append(f"Topology: {self.topology.edges} edges, {self.topology.faces} faces")
        return "\n".join(lines)


def _read(action: str, read: "Callable[[], _T]") -> _T:
    """Performs one COM read, translating a COM failure.

    Args:
        action: What is being read, for the error message.
        read: The read to perform.

    Returns:
        Whatever `read` returns.

    Raises:
        AutomationError: If the read raises a COM error.
    """
    try:
        return read()
    except pywintypes.com_error as error:
        raise automation_error(error, f"reading {action}") from error


def _items(collection: Any, label: str) -> "list[Any]":
    """Enumerates a 1-based COM collection.

    Args:
        collection: The raw COM collection.
        label: The collection's name, for error messages.

    Returns:
        Every item, in collection order.

    Raises:
        AutomationError: If reading the count or an item fails.
    """
    count = _read(f"{label}.Count", lambda: int(collection.Count))
    return [
        _read(f"{label}.Item({index})", lambda index=index: collection.Item(index))
        for index in range(_FIRST_COM_INDEX, count + _FIRST_COM_INDEX)
    ]


class Inspector:
    """Reads what a Part contains without changing anything.

    Obtain it as `part.inspect`.
    """

    def __init__(self, part: "Part") -> None:
        """Initializes the inspector.

        Args:
            part: The Part to inspect.
        """
        self._part = part

    def summary(self) -> PartSummary:
        """Reads everything this inspector reports, in one structured snapshot.

        Returns:
            A `PartSummary`.

        Raises:
            Auto3dxError: If any underlying read fails.

        Warns:
            SelectionNotRestoredWarning: If CATIA did not fully restore the user's
                selection after counting edges and faces.
        """
        return PartSummary(
            name=self._part.name,
            up_to_date=self._part.is_up_to_date(),
            features=self.features(),
            sketches=self.sketches(),
            parameters=self.parameters(),
            bodies=self.bodies(),
            geometrical_sets=self.geometrical_sets(),
            topology=self.topology(),
            in_work_object=self.in_work_object(),
        )

    def features(self) -> "tuple[FeatureInfo, ...]":
        """Lists every solid feature in the main body, in model-tree order.

        Unlike the per-kind listings on `part.part_design`, this includes features of
        kinds the SDK does not wrap, so nothing in the model is hidden from a caller.

        Returns:
            One `FeatureInfo` per item in `MainBody.Shapes`.

        Raises:
            AutomationError: If enumerating the shapes or reading a name fails.
        """
        main_body = _read("Part.MainBody", lambda: self._part.com_object.MainBody)
        return self._features_of(main_body, "MainBody", is_main=True)

    def sketches(self) -> "tuple[str, ...]":
        """Lists the main body's sketch names, in model-tree order.

        Returns:
            One name per sketch.

        Raises:
            Auto3dxError: If enumerating the sketches fails.
        """
        return tuple(self._part.sketches.names())

    def parameters(self) -> "tuple[ParameterInfo, ...]":
        """Lists the user parameters.

        Only explicitly created parameters are included. The dimensions CATIA exposes
        for every feature (`<Pad>\\FirstLimit\\Length` and similar) are excluded, as
        `part.parameters.user_parameters()` excludes them.

        Returns:
            One `ParameterInfo` per user parameter.

        Raises:
            Auto3dxError: If enumerating or reading the parameters fails.
        """
        return tuple(parameter.info() for parameter in self._part.parameters.user_parameters())

    def bodies(self) -> "tuple[BodyInfo, ...]":
        """Lists every body of the Part with its features and sketches.

        Returns:
            One `BodyInfo` per item in `Part.Bodies`, in that order.

        Raises:
            AutomationError: If enumerating the bodies or reading any of them fails.
        """
        raw_part = self._part.com_object
        main_body = _read("Part.MainBody", lambda: raw_part.MainBody)
        bodies = _items(_read("Part.Bodies", lambda: raw_part.Bodies), "Part.Bodies")
        result = []
        for index, body in enumerate(bodies, start=_FIRST_COM_INDEX):
            label = f"Part.Bodies.Item({index})"
            # COM identity (`==`, verified for bodies) rather than the name, which a
            # second body could share.
            is_main = bool(body == main_body)
            sketches = _items(_read(f"{label}.Sketches", lambda body=body: body.Sketches),
                              f"{label}.Sketches")
            result.append(
                BodyInfo(
                    name=_read(f"{label}.Name", lambda body=body: body.Name),
                    is_main=is_main,
                    features=self._features_of(body, label, is_main=is_main),
                    sketches=tuple(
                        _read(f"{label}.Sketches name", lambda sketch=sketch: sketch.Name)
                        for sketch in sketches
                    ),
                )
            )
        return tuple(result)

    def geometrical_sets(self) -> "tuple[GeometricalSetInfo, ...]":
        """Lists the geometrical sets directly under the Part and their elements.

        Returns:
            One `GeometricalSetInfo` per item in `Part.HybridBodies`, in that order.

        Raises:
            AutomationError: If enumerating the sets or reading any of them fails.
        """
        raw_part = self._part.com_object
        hybrid_bodies = _items(
            _read("Part.HybridBodies", lambda: raw_part.HybridBodies), "Part.HybridBodies"
        )
        result = []
        for index, hybrid_body in enumerate(hybrid_bodies, start=_FIRST_COM_INDEX):
            label = f"Part.HybridBodies.Item({index})"
            shapes = _items(
                _read(f"{label}.HybridShapes", lambda body=hybrid_body: body.HybridShapes),
                f"{label}.HybridShapes",
            )
            nested = _read(
                f"{label}.HybridBodies.Count",
                lambda body=hybrid_body: int(body.HybridBodies.Count),
            )
            result.append(
                GeometricalSetInfo(
                    name=_read(f"{label}.Name", lambda body=hybrid_body: body.Name),
                    elements=tuple(
                        GeometryInfo(
                            name=_read(f"{label} element name", lambda shape=shape: shape.Name),
                            kind=type(shape).__name__,
                        )
                        for shape in shapes
                    ),
                    nested_set_count=nested,
                )
            )
        return tuple(result)

    def topology(self) -> "TopologyCounts | None":
        """Counts the edges and faces `part.topology` finds right now.

        The searches restore the user's CATIA selection and do not advance the model
        generation.

        Returns:
            The counts, or `None` when this Part has no editor selection, as happens
            for a Part built directly from a raw COM object.

        Raises:
            AutomationError: If the selection cannot be read or a search fails.

        Warns:
            SelectionNotRestoredWarning: If CATIA did not fully restore the selection.
        """
        try:
            edges = self._part.topology.edges()
        except ValidationError:
            # The only refusal before COM is a missing selection: nothing to search with.
            return None
        faces = self._part.topology.faces()
        return TopologyCounts(edges=len(edges), faces=len(faces))

    def in_work_object(self) -> "InWorkObjectInfo | None":
        """Reads the Part's In-Work Object without changing it.

        Only `Part.InWorkObject` and its `Name` are read; nothing is assigned.

        Returns:
            The In-Work Object's name, kind and whether it is the main body, or `None`
            when CATIA reports no In-Work Object.

        Raises:
            AutomationError: If reading the In-Work Object, its name or the main body
                fails.
        """
        raw_part = self._part.com_object
        in_work = _read("Part.InWorkObject", lambda: raw_part.InWorkObject)
        if in_work is None:
            return None
        main_body = _read("Part.MainBody", lambda: raw_part.MainBody)
        return InWorkObjectInfo(
            name=_read("Part.InWorkObject.Name", lambda: in_work.Name),
            kind=type(in_work).__name__,
            # COM identity (`==`, verified for bodies): a second body can share the name.
            is_main_body=bool(in_work == main_body),
        )

    @staticmethod
    def _features_of(body: Any, label: str, is_main: bool) -> "tuple[FeatureInfo, ...]":
        """Reads one body's solid features.

        Args:
            body: The raw CATIA `Body`.
            label: How to name the body in error messages.
            is_main: Whether it is the main body, the only one `part_design` handles.

        Returns:
            One `FeatureInfo` per item in the body's `Shapes`.

        Raises:
            AutomationError: If enumerating the shapes or reading a name fails.
        """
        shapes = _items(_read(f"{label}.Shapes", lambda: body.Shapes), f"{label}.Shapes")
        features = []
        for index, shape in enumerate(shapes, start=_FIRST_COM_INDEX):
            kind = type(shape).__name__
            features.append(
                FeatureInfo(
                    name=_read(
                        f"{label}.Shapes.Item({index}).Name", lambda shape=shape: shape.Name
                    ),
                    kind=kind,
                    supported=is_main and kind in SUPPORTED_FEATURE_KINDS,
                )
            )
        return tuple(features)

    def __repr__(self) -> str:
        """str: Debug representation; does not contact CATIA."""
        return "Inspector()"
