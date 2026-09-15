"""Read-only inspection of a Part: what the model already contains.

An agent has to find out what is in a model before it changes anything, so reading
a model reliably matters as much as building one (`docs/api-design.md` section 11).
Inspection returns frozen dataclasses. Text rendering is a convenience on top, never
the primary output, so a caller can act on the data without parsing prose.

Every field here comes from a read already backed by live evidence:

* the Part name and `Part.IsUpToDate()`, pinned by the integration suite;
* user parameters through `RootParameterSet.DirectParameters`, verified live and used
  by `ParameterCollection.user_parameters()`;
* sketch names through `MainBody.Sketches`, verified live;
* the main body's features through `MainBody.Shapes` enumeration and each item's
  `Name` and `type(item).__name__`. That mechanism is live-verified for all thirteen
  kinds the SDK creates, and `Name` is documented on the Automation base object every
  shape derives from.

What is not reported yet: other bodies, geometrical sets and their contents, and edge
and face counts. Probe 38 verified the reads they need, and topology searches now
restore the user's CATIA selection, so they are waiting only on implementation.

Inspection never advances the model generation, never rebuilds, and never touches
the selection or the In-Work Object.
"""

import dataclasses
from typing import TYPE_CHECKING, Any

import pywintypes

from auto_3dx._com import automation_error
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
    """One solid feature in the main body, in model-tree order.

    Attributes:
        name: The feature's name as CATIA reports it.
        kind: The CATIA wrapper type name, such as ``"Pad"`` or ``"ConstRadEdgeFillet"``.
            A feature created in the CATIA user interface can be of a kind the SDK
            does not wrap; it is still listed, with its real kind.
        supported: Whether `part.part_design` can create, list and remove this kind.
    """

    name: str
    kind: str
    supported: bool


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
    """

    name: str
    up_to_date: bool
    features: "tuple[FeatureInfo, ...]"
    sketches: "tuple[str, ...]"
    parameters: "tuple[ParameterInfo, ...]"

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
        return "\n".join(lines)


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
        """
        return PartSummary(
            name=self._part.name,
            up_to_date=self._part.is_up_to_date(),
            features=self.features(),
            sketches=self.sketches(),
            parameters=self.parameters(),
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
        shapes = self._main_body_shapes()
        try:
            count = shapes.Count
        except pywintypes.com_error as error:
            raise automation_error(error, "reading MainBody.Shapes.Count") from error
        return tuple(self._feature_info(shapes, index) for index in range(1, count + 1))

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

    def _main_body_shapes(self) -> Any:
        """Returns the raw `MainBody.Shapes` collection.

        Raises:
            AutomationError: If reading it fails.
        """
        try:
            return self._part.com_object.MainBody.Shapes
        except pywintypes.com_error as error:
            raise automation_error(error, "reading MainBody.Shapes") from error

    @staticmethod
    def _feature_info(shapes: Any, index: int) -> FeatureInfo:
        """Reads one shape's name and kind.

        Args:
            shapes: The raw `MainBody.Shapes` collection.
            index: The 1-based position to read.

        Returns:
            The shape's `FeatureInfo`.

        Raises:
            AutomationError: If reading the item or its name fails.
        """
        try:
            item = shapes.Item(index)
            name = item.Name
        except pywintypes.com_error as error:
            raise automation_error(error, f"reading feature {index} of MainBody.Shapes") from error
        kind = type(item).__name__
        return FeatureInfo(name=name, kind=kind, supported=kind in SUPPORTED_FEATURE_KINDS)

    def __repr__(self) -> str:
        """str: Debug representation; does not contact CATIA."""
        return "Inspector()"
