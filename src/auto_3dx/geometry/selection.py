"""`part.selection`: what the user selected in CATIA, and highlighting for the user to see.

An agent working next to a person needs "the edge I clicked" as an ordinary `Edge`, not as
a raw `SelectedElement`. This module reads the editor's current selection into the same
public wrappers the rest of the SDK returns, and goes the other way: it selects SDK
elements in the CATIA UI so the person can see what the agent means.

Reading, from live evidence (probe 47a, `Selection.Item(i)`):

    Item(i).Type        edge  -> a name ending in "Edge" ("RectilinearTriDimFeatEdge")
                        face  -> a name ending in "Face" ("PlanarFace")
                        feature -> its CATIA type ("Pad"), sketch -> "Sketch", Part -> "Part"
    Item(i).Reference   works for edges, faces and features; FAILS for a sketch (E_FAIL)
    Item(i).Value       works for every kind; a sketch is identified by it

An edge or face becomes an `Edge`/`Face` stamped with the current model generation, so it
goes stale like any snapshot element and is accepted by every feature that takes one. A
feature becomes its typed wrapper (`Pad`, `Hole`, ...), a sketch a `Sketch`, a body a
`Body`. Anything else -- a vertex, the Part itself, a kind the SDK does not wrap -- is
reported as what it is, never coerced.

Every item is checked to belong to THIS Part: the body that holds it must be one of this
Part's bodies by COM identity. An item whose owner cannot be established is refused
(`SelectionOutsidePartError`), not assumed. Reading is read-only: it neither changes the
selection nor advances the model generation.

Highlighting (`set`, `add`, `clear`) changes only the UI selection: live (probe 47b)
`Selection.Add(edge reference)` selected exactly that edge and the model was unchanged. The
count is read back after every add, because CATIA was seen to drop an item silently.
Like the topology search, both directions are refused unless this Part is the active one:
the selection of a non-active Part's editor was seen to act on the active Part instead.
"""

import dataclasses
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import pywintypes

from auto_3dx._com import automation_error
from auto_3dx.errors import (
    AutomationError,
    ParameterTypeError,
    SelectionCountError,
    SelectionOutsidePartError,
    SelectionTypeError,
    ValidationError,
)
from auto_3dx.geometry._topology_search import BodyIndex, owner_of
from auto_3dx.geometry.bodies import Body
from auto_3dx.geometry.deletion import require_active_part, require_selection
from auto_3dx.geometry.edges import Edge
from auto_3dx.geometry.faces import Face
from auto_3dx.geometry.part_design import (
    BOOLEAN_KINDS,
    CHAMFER_KIND,
    CIRCULAR_PATTERN_KIND,
    EDGE_FILLET_KIND,
    GROOVE_KIND,
    HOLE_KIND,
    MIRROR_KIND,
    MULTI_SECTION_SOLID_KIND,
    PAD_KIND,
    POCKET_KIND,
    RECTANGULAR_PATTERN_KIND,
    RIB_KIND,
    SHAFT_KIND,
    SHELL_KIND,
    SLOT_KIND,
    THICKNESS_KIND,
    BooleanOperation,
    Chamfer,
    CircularPattern,
    ConstRadEdgeFillet,
    Groove,
    Hole,
    Mirror,
    MultiSectionSolid,
    Pad,
    Pocket,
    RectangularPattern,
    Rib,
    Shaft,
    Shell,
    Slot,
    Thickness,
    _FeatureActivity,
)
from auto_3dx.geometry.sketch import Sketch

if TYPE_CHECKING:
    from auto_3dx.core.part import Part

SELECTED_EDGE: str = "edge"
SELECTED_FACE: str = "face"
SELECTED_VERTEX: str = "vertex"
SELECTED_FEATURE: str = "feature"
SELECTED_SKETCH: str = "sketch"
SELECTED_BODY: str = "body"
SELECTED_PART: str = "part"
SELECTED_OTHER: str = "other"
"""The kinds a selected item is classified as. Only edge, face, feature, sketch and body
carry an SDK wrapper; the others are reported with their CATIA type name."""

_FEATURE_WRAPPERS: "dict[str, type]" = {
    PAD_KIND: Pad,
    POCKET_KIND: Pocket,
    SHAFT_KIND: Shaft,
    GROOVE_KIND: Groove,
    MIRROR_KIND: Mirror,
    RIB_KIND: Rib,
    SLOT_KIND: Slot,
    MULTI_SECTION_SOLID_KIND: MultiSectionSolid,
    EDGE_FILLET_KIND: ConstRadEdgeFillet,
    CHAMFER_KIND: Chamfer,
    SHELL_KIND: Shell,
    THICKNESS_KIND: Thickness,
    HOLE_KIND: Hole,
    CIRCULAR_PATTERN_KIND: CircularPattern,
    RECTANGULAR_PATTERN_KIND: RectangularPattern,
    **{kind: BooleanOperation for kind in BOOLEAN_KINDS},
}
"""CATIA type name -> the wrapper `part.part_design` returns for that feature."""

_SKETCH_TYPE = "Sketch"
_BODY_TYPE = "Body"
_PART_TYPE = "Part"
_EDGE_SUFFIX = "Edge"
_FACE_SUFFIX = "Face"
_VERTEX_SUFFIX = "Vertex"
_FIRST_COM_INDEX = 1
_MAX_OWNER_DEPTH = 8
"""How far above a selected object to look for its body (`Sketch -> Pad -> Shapes -> Body`
is four levels, probe 42)."""


def classify(type_name: str) -> str:
    """The kind of a selected item, from its `SelectedElement.Type`.

    Args:
        type_name: What `Selection.Item(i).Type` reported.

    Returns:
        One of the `SELECTED_*` kinds.
    """
    if type_name.endswith(_EDGE_SUFFIX):
        return SELECTED_EDGE
    if type_name.endswith(_FACE_SUFFIX):
        return SELECTED_FACE
    if type_name.endswith(_VERTEX_SUFFIX):
        return SELECTED_VERTEX
    if type_name == _SKETCH_TYPE:
        return SELECTED_SKETCH
    if type_name == _BODY_TYPE:
        return SELECTED_BODY
    if type_name == _PART_TYPE:
        return SELECTED_PART
    if type_name in _FEATURE_WRAPPERS:
        return SELECTED_FEATURE
    return SELECTED_OTHER


@dataclasses.dataclass(frozen=True)
class SelectedItem:
    """One item of the CATIA selection, read into the SDK.

    Attributes:
        position: Its one-based position in the selection.
        kind: One of the `SELECTED_*` kinds.
        type_name: CATIA's own type name (`SelectedElement.Type`), such as
            ``"RectilinearTriDimFeatEdge"`` or ``"Pad"``.
        name: The object's name for a feature, sketch, body or Part; `None` for topology,
            whose names are BRep strings that identify nothing durable.
        element: The SDK wrapper -- an `Edge`, a `Face`, a feature wrapper, a `Sketch` or a
            `Body` -- or `None` for a kind the SDK does not wrap.
    """

    position: int
    kind: str
    type_name: str
    name: "str | None"
    element: Any

    def describe(self) -> str:
        """One line about this item, for messages and agents.

        Returns:
            For topology, the element's measured description; otherwise the kind, the
            CATIA type and the name.
        """
        if self.kind in (SELECTED_EDGE, SELECTED_FACE) and self.element is not None:
            return f"selected {self.element.describe()}"
        label = f"selected {self.kind} ({self.type_name})"
        return f"{label} {self.name!r}" if self.name is not None else label


def _read(label: str, read: Any) -> Any:
    try:
        return read()
    except pywintypes.com_error as error:
        raise automation_error(error, f"reading {label}") from error


def _parent(node: Any) -> Any:
    try:
        return node.Parent
    except (pywintypes.com_error, AttributeError):
        return None


class PartSelection:
    """The CATIA selection of the editor editing a Part, read and written through the SDK.

    Obtain it as `part.selection`.
    """

    def __init__(self, part: "Part", selection: Any, measurer: Any = None) -> None:
        """Initializes the namespace without contacting CATIA.

        Args:
            part: The `Part` whose selection this is.
            selection: The raw CATIA `Selection` of the editor editing it.
            measurer: The `GeometryMeasurer` selected edges and faces measure with.
        """
        self._part = part
        self._selection = selection
        self._measurer = measurer

    # --- reading ---------------------------------------------------------------------------

    def _raw(self) -> Any:
        selection = require_selection(self._selection)
        require_active_part(self._part.com_object)
        return selection

    def _raw_bodies(self) -> "list[Any]":
        bodies = _read("Part.Bodies", lambda: self._part.com_object.Bodies)
        count = int(_read("Bodies.Count", lambda: bodies.Count))
        return [
            _read("Bodies.Item", lambda index=index: bodies.Item(index))
            for index in range(_FIRST_COM_INDEX, count + _FIRST_COM_INDEX)
        ]

    def _this_parts_body(self, candidate: Any, bodies: "list[Any]") -> Any:
        """Returns `candidate` if it IS one of this Part's bodies (COM identity), else None."""
        if candidate is None:
            return None
        for body in bodies:
            try:
                if body == candidate:
                    return body
            except pywintypes.com_error:
                continue
        return None

    def _holding_body(self, value: Any, bodies: "list[Any]") -> Any:
        """The body of this Part that holds a selected object, found by walking `Parent`.

        Falls back to looking the object up by name in each body's `Shapes`/`Sketches` and
        comparing COM identity, for a chain that does not reach a body (seen live for
        consumed sketches).
        """
        node = value
        for _ in range(_MAX_OWNER_DEPTH):
            if node is None:
                break
            if type(node).__name__ == _BODY_TYPE:
                return self._this_parts_body(node, bodies)
            node = _parent(node)
        try:
            name = str(value.Name)
        except (pywintypes.com_error, AttributeError):
            return None
        for body in bodies:
            for member in ("Shapes", "Sketches"):
                try:
                    collection = getattr(body, member)
                    count = int(collection.Count)
                    for index in range(_FIRST_COM_INDEX, count + _FIRST_COM_INDEX):
                        item = collection.Item(index)
                        if str(item.Name) == name and item == value:
                            return body
                except (pywintypes.com_error, AttributeError):
                    continue
        return None

    def _outside(self, position: int, type_name: str) -> SelectionOutsidePartError:
        return SelectionOutsidePartError(
            f"Selected item {position} ({type_name}) could not be attributed to Part "
            f"{self._part.name!r}: none of its bodies provably holds it. Select it in this "
            "Part, or make this Part the active one."
        )

    def _topology(
        self, kind: str, item: Any, position: int, type_name: str, bodies: "list[Any]"
    ) -> "Edge | Face":
        reference = _read("SelectedElement.Reference", lambda: item.Reference)
        # No name fallback here: a name found in this Part's bodies proves nothing about
        # which Part the selected reference came from. Identity is checked instead.
        owner_body, _, feature_name = owner_of(reference)
        body = self._this_parts_body(owner_body, bodies)
        if body is None:
            feature = _parent(reference)
            body = self._holding_body(feature, bodies) if feature is not None else None
        if body is None:
            raise self._outside(position, type_name)
        try:
            owner_body_name: "str | None" = str(body.Name)
        except (pywintypes.com_error, AttributeError):
            owner_body_name = None
        index = BodyIndex(self._part.com_object)
        generation = self._part._generation
        if kind == SELECTED_EDGE:
            return Edge(
                reference,
                position,
                generation.value,
                body,
                owner_body_name,
                feature_name,
                self._measurer,
                generation,
                index.is_sketch(feature_name),
            )
        return Face(
            reference,
            position,
            generation.value,
            body,
            owner_body_name,
            feature_name,
            self._measurer,
            generation,
        )

    def _item(self, raw: Any, position: int, bodies: "list[Any]") -> SelectedItem:
        item = _read(f"Selection.Item({position})", lambda: raw.Item(position))
        type_name = str(_read("SelectedElement.Type", lambda: item.Type))
        kind = classify(type_name)
        if kind in (SELECTED_EDGE, SELECTED_FACE):
            topology = self._topology(kind, item, position, type_name, bodies)
            return SelectedItem(position, kind, type_name, None, topology)
        value = _read("SelectedElement.Value", lambda: item.Value)
        name = str(_read("the selected object's Name", lambda: value.Name))
        if kind == SELECTED_PART:
            if not _read("Part identity", lambda: value == self._part.com_object):
                raise self._outside(position, type_name)
            return SelectedItem(position, kind, type_name, name, None)
        if kind in (SELECTED_VERTEX, SELECTED_OTHER):
            return SelectedItem(position, kind, type_name, name, None)
        generation = self._part._generation
        if kind == SELECTED_BODY:
            body = self._this_parts_body(value, bodies)
            if body is None:
                raise self._outside(position, type_name)
            element: Any = Body(
                body, self._part.com_object, self._selection, generation, owner=self._part
            )
            return SelectedItem(position, kind, type_name, name, element)
        if self._holding_body(value, bodies) is None:
            raise self._outside(position, type_name)
        if kind == SELECTED_SKETCH:
            element = Sketch(value, generation, part_com_object=self._part.com_object)
        else:
            element = _FEATURE_WRAPPERS[type_name](value, generation)
        return SelectedItem(position, kind, type_name, name, element)

    def items(self) -> "list[SelectedItem]":
        """Reads every selected item, in selection order.

        Returns:
            One `SelectedItem` per item; an empty list when nothing is selected.

        Raises:
            ValidationError: If no editor selection is available.
            InactivePartError: If this Part is not the active one.
            SelectionOutsidePartError: If an item does not provably belong to this Part.
            AutomationError: If CATIA refuses a read.
        """
        raw = self._raw()
        count = int(_read("Selection.Count", lambda: raw.Count))
        if not count:
            return []
        bodies = self._raw_bodies()
        return [
            self._item(raw, position, bodies)
            for position in range(_FIRST_COM_INDEX, count + _FIRST_COM_INDEX)
        ]

    @property
    def count(self) -> int:
        """int: How many items are selected (`Selection.Count`)."""
        raw = self._raw()
        return int(_read("Selection.Count", lambda: raw.Count))

    def __len__(self) -> int:
        """Returns `count`."""
        return self.count

    def __iter__(self) -> Iterator[SelectedItem]:
        """Iterates `items()`."""
        return iter(self.items())

    def one(self) -> SelectedItem:
        """The one selected item, whatever its kind.

        Raises:
            SelectionCountError: If nothing, or more than one item, is selected.
            (and whatever `items()` raises)
        """
        items = self.items()
        if len(items) != 1:
            raise SelectionCountError(
                f"Exactly one selected item was expected; {len(items)} "
                f"{'is' if len(items) == 1 else 'are'} selected"
                + (": " + "; ".join(item.describe() for item in items) if items else "")
                + ". Select one item in CATIA and try again.",
                count=len(items),
            )
        return items[0]

    def _one_of(self, kind: str) -> Any:
        item = self.one()
        if item.kind != kind:
            raise SelectionTypeError(
                f"A selected {kind} was expected, but the selection is {item.describe()}. "
                f"Select one {kind} in CATIA and try again.",
                expected=kind,
                actual=(item.kind,),
            )
        return item.element

    def one_edge(self) -> Edge:
        """The one selected edge, as an `Edge` usable by any feature.

        Raises:
            SelectionCountError: If not exactly one item is selected.
            SelectionTypeError: If the item is not an edge.
            SelectionOutsidePartError: If it does not belong to this Part.
        """
        edge: Edge = self._one_of(SELECTED_EDGE)
        return edge

    def one_face(self) -> Face:
        """The one selected face, as a `Face` usable by any feature.

        Raises:
            SelectionCountError: If not exactly one item is selected.
            SelectionTypeError: If the item is not a face.
            SelectionOutsidePartError: If it does not belong to this Part.
        """
        face: Face = self._one_of(SELECTED_FACE)
        return face

    def one_feature(self) -> Any:
        """The one selected feature, as the wrapper `part.part_design` returns for its kind.

        Raises:
            SelectionCountError: If not exactly one item is selected.
            SelectionTypeError: If the item is not a feature the SDK wraps.
            SelectionOutsidePartError: If it does not belong to this Part.
        """
        return self._one_of(SELECTED_FEATURE)

    def one_sketch(self) -> Sketch:
        """The one selected sketch.

        Raises:
            SelectionCountError: If not exactly one item is selected.
            SelectionTypeError: If the item is not a sketch.
            SelectionOutsidePartError: If it does not belong to this Part.
        """
        sketch: Sketch = self._one_of(SELECTED_SKETCH)
        return sketch

    def _all_of(self, kind: str) -> "list[Any]":
        items = self.items()
        if not items:
            raise SelectionCountError(
                f"At least one selected {kind} was expected; nothing is selected.", count=0
            )
        others = [item for item in items if item.kind != kind]
        if others:
            raise SelectionTypeError(
                f"Every selected item was expected to be a {kind}, but "
                + "; ".join(item.describe() for item in others)
                + ". Nothing was guessed: select only the items you mean.",
                expected=kind,
                actual=tuple(item.kind for item in items),
            )
        return [item.element for item in items]

    def edges(self) -> "list[Edge]":
        """Every selected item, all of which must be edges.

        Raises:
            SelectionCountError: If nothing is selected.
            SelectionTypeError: If any selected item is not an edge.
        """
        return self._all_of(SELECTED_EDGE)

    def faces(self) -> "list[Face]":
        """Every selected item, all of which must be faces.

        Raises:
            SelectionCountError: If nothing is selected.
            SelectionTypeError: If any selected item is not a face.
        """
        return self._all_of(SELECTED_FACE)

    # --- highlighting ---------------------------------------------------------------------

    def _selectable(self, element: Any) -> Any:
        """The raw object `Selection.Add` takes for one SDK element, checked first."""
        if isinstance(element, (Edge, Face)):
            if not element._belongs_to(self._part._generation):
                raise ValidationError(
                    "This edge or face belongs to another Part; it cannot be highlighted "
                    "here. Nothing was changed."
                )
            noun = "edge" if isinstance(element, Edge) else "face"
            self._part._generation.require_current(
                element.generation, noun, f"part.topology.{noun}s()"
            )
            return element.com_object
        if isinstance(element, (_FeatureActivity, RectangularPattern, Sketch, Body)):
            wrapper: Any = element
            return wrapper.com_object
        raise ParameterTypeError(
            "Only an Edge, a Face, a feature, a Sketch or a Body can be highlighted, not "
            f"{type(element).__name__}."
        )

    def clear(self) -> None:
        """Deselects everything in the CATIA UI. The model is not touched.

        Raises:
            ValidationError: If no editor selection is available.
            InactivePartError: If this Part is not the active one.
            AutomationError: If CATIA refuses.
        """
        raw = self._raw()
        _read("Selection.Clear", raw.Clear)

    def add(self, *elements: Any) -> None:
        """Adds elements to the CATIA selection, so the user sees them highlighted.

        Only the UI selection changes: live (probe 47b) adding an edge selected exactly
        that edge and left the model unchanged, and the model generation does not advance.
        Every element is checked before anything is selected, and the count is read back.

        Args:
            *elements: `Edge`s and `Face`s from a current snapshot or the selection,
                feature wrappers, `Sketch`es or `Body`s of this Part.

        Raises:
            ParameterTypeError: If an element is none of those.
            ValidationError: If an edge or face belongs to another Part, or no editor
                selection is available.
            StaleSnapshotError: If an edge or face comes from an outdated snapshot.
            InactivePartError: If this Part is not the active one.
            AutomationError: If CATIA refuses an add, or drops an item silently.
        """
        raws = [self._selectable(element) for element in elements]
        raw = self._raw()
        before = int(_read("Selection.Count", lambda: raw.Count))
        for value in raws:
            _read("Selection.Add", lambda value=value: raw.Add(value))
        after = int(_read("Selection.Count", lambda: raw.Count))
        if after != before + len(raws):
            raise AutomationError(
                f"CATIA selected {after - before} of the {len(raws)} element(s) asked for "
                f"(the selection now holds {after}). The model was not changed; clear the "
                "selection and try again, or pass each element once."
            )

    def set(self, *elements: Any) -> None:
        """Replaces the CATIA selection with these elements (highlights exactly them).

        Same checks and guarantees as `add`; the previous selection is cleared only after
        every element has been checked.

        Args:
            *elements: As for `add`. None clears the selection.

        Raises:
            (as for `add`)
        """
        for element in elements:
            self._selectable(element)
        self.clear()
        if elements:
            self.add(*elements)

    def __repr__(self) -> str:
        """str: Debug representation; does not contact CATIA."""
        return "PartSelection()"
