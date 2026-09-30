"""The one topology search, run so that the user's CATIA selection survives it.

`Selection.Search` is the only verified route from a solid to feature-usable edge and
face references (`docs/conventions.md` section 1.2.2.2), and it works by replacing the
editor's selection with every hit. Left alone, taking a snapshot would throw away
whatever the user had selected in the UI. The contract says a snapshot must not
(`docs/api-design.md` section 7), so the search runs between a capture and a restore:

    values = [Selection.Item(i).Value for i in 1..Count]    # capture
    Clear(); Search(query); Item(i).Reference for each hit  # the verified search
    Clear(); Add(value) for each captured value             # restore
    Count == len(values)                                    # verify

Live evidence (2026-09-15): a selection of a Pad and a sketch, and a selection of six
`PlanarFace` items, both came back in order with the same names and types. A raw
`Reference` handed to `Selection.Add` was silently dropped without an error, so a
restore that does not throw is not trusted: the count is read back and compared.

CATIA can refuse a restore silently. With a solid's faces selected followed by the Pad
that owns them, re-adding the faces succeeded and re-adding the Pad left the count
unchanged. By then the user's selection has already been replaced, so raising would
protect nothing and would only discard a valid snapshot. An incomplete restore after a
successful search is therefore a `SelectionNotRestoredWarning`, not an error. A
selection that cannot even be captured is refused before anything changes.
"""

import warnings
from typing import Any

import pywintypes

from auto_3dx._com import automation_error, format_hresult, hresult_of
from auto_3dx.errors import AutomationError, SelectionNotRestoredWarning
from auto_3dx.geometry.deletion import require_active_part, require_selection

_FIRST_COM_INDEX = 1
_WARNING_STACKLEVEL = 4
"""Points the warning at the caller of `part.topology.edges()` or `faces()`."""


def _capture_selection(selection: Any) -> "list[Any]":
    """Reads the value of every currently selected item, in order.

    Args:
        selection: The raw CATIA `Selection` COM object.

    Returns:
        One raw `SelectedElement.Value` per selected item.

    Raises:
        AutomationError: The selection could not be read. Nothing has been changed:
            the search is refused rather than run against a selection that could not
            be put back.
    """
    try:
        count = int(selection.Count)
        return [
            selection.Item(position).Value
            for position in range(_FIRST_COM_INDEX, count + _FIRST_COM_INDEX)
        ]
    except pywintypes.com_error as error:
        raise AutomationError(
            "Refused to search topology: the current CATIA selection could not be read "
            f"(HRESULT={format_hresult(hresult_of(error))}), so it could not be restored "
            "afterwards. The selection and the model were not changed.",
            hresult_of(error),
        ) from error


def _restore_selection(selection: Any, captured: "list[Any]") -> "str | None":
    """Puts a captured selection back and checks that it actually came back.

    Args:
        selection: The raw CATIA `Selection` COM object.
        captured: The values returned by `_capture_selection`.

    Returns:
        `None` when the selection holds the same number of items as before, or a
        sentence describing what went wrong.
    """
    try:
        selection.Clear()
        for value in captured:
            selection.Add(value)
        restored = int(selection.Count)
    except pywintypes.com_error as error:
        return (
            "the CATIA selection could not be restored "
            f"(HRESULT={format_hresult(hresult_of(error))})"
        )
    if restored != len(captured):
        return (
            f"the CATIA selection held {len(captured)} item(s) before the search but "
            f"{restored} after restoring it"
        )
    return None


_BODY_KIND = "Body"
_MAX_OWNER_DEPTH = 6
"""How far above a reference to look for the body that owns it.

Measured chains (probe 42): a solid edge is `Pad -> Shapes -> Body`, and an edge of a
sketch a pad consumed is `Sketch -> Pad -> Shapes -> Body`. Six levels leaves room for
a longer chain without walking the whole document.
"""


class BodyIndex:
    """Finds the body that holds a feature, by looking in every body of the Part.

    The fallback for `owner_of` when walking `Parent` does not reach a body. Live
    (2026-09-21, after a session restart) a sketch consumed by a pad reported a `Parent`
    chain of generic `AnyObject` wrappers that never reached its body, while in probe 42
    the same chain was `Sketch -> Pad -> Shapes -> Body`. Membership is read from the
    model: each body's `Shapes` and `Sketches` are listed by name, once per snapshot, and a
    feature is attributed to a body only when exactly one body holds that name. A name
    held by two bodies stays unknown rather than guessed.
    """

    def __init__(self, part_com_object: Any) -> None:
        """Initializes the index without reading anything yet.

        Args:
            part_com_object: The raw Part whose bodies are searched.
        """
        self._part = part_com_object
        self._bodies_by_name: "dict[str, list[Any]] | None" = None
        self._sketch_names: "set[str]" = set()
        self._shape_names: "set[str]" = set()

    def _build(self) -> "dict[str, list[Any]]":
        found: dict[str, list[Any]] = {}
        sketches: set[str] = set()
        shapes: set[str] = set()
        try:
            bodies = self._part.Bodies
            for body_index in range(_FIRST_COM_INDEX, int(bodies.Count) + _FIRST_COM_INDEX):
                body = bodies.Item(body_index)
                for collection, names in ((body.Shapes, shapes), (body.Sketches, sketches)):
                    if collection is None:
                        continue
                    for index in range(
                        _FIRST_COM_INDEX, int(collection.Count) + _FIRST_COM_INDEX
                    ):
                        name = str(collection.Item(index).Name)
                        names.add(name)
                        holders = found.setdefault(name, [])
                        if not any(holder is body for holder in holders):
                            holders.append(body)
        except (pywintypes.com_error, AttributeError):
            return {}
        self._sketch_names, self._shape_names = sketches, shapes
        return found

    def is_sketch(self, feature_name: "str | None") -> "bool | None":
        """Whether a reference's owner feature is a sketch rather than a solid feature.

        A Part-wide edge search also returns the edges of every sketch a feature consumed
        (probe 46y: a block's search returned 16 edges, its 12 plus the profile's 4), and
        their `Reference.Parent` is the sketch (probe 42). They bound no face of the solid.

        Returns:
            `True` when only a body's `Sketches` holds that name, `False` when only a
            body's `Shapes` does, and `None` when neither or both do, or the model could
            not be read -- unknown rather than guessed.
        """
        if feature_name is None:
            return None
        if self._bodies_by_name is None:
            self._bodies_by_name = self._build()
        in_sketches = feature_name in self._sketch_names
        in_shapes = feature_name in self._shape_names
        if in_sketches == in_shapes:
            return None
        return in_sketches

    def __call__(self, feature_name: str) -> "tuple[Any, str | None]":
        """Returns `(body, body_name)` for the one body holding `feature_name`.

        Returns:
            `(None, None)` when no body, or more than one, holds that name.
        """
        if self._bodies_by_name is None:
            self._bodies_by_name = self._build()
        holders = self._bodies_by_name.get(feature_name, [])
        if len(holders) != 1:
            return None, None
        try:
            return holders[0], str(holders[0].Name)
        except (pywintypes.com_error, AttributeError):
            return holders[0], None


def owner_of(
    reference: Any, fallback: "BodyIndex | None" = None
) -> "tuple[Any, str | None, str | None]":
    """Finds the body a topology reference belongs to, by walking its owner chain.

    `Reference.Parent` is the feature the edge or face came from -- a `Pad` for a solid
    edge, the `Sketch` for an edge of a sketch a pad consumed (probe 42, live) -- and
    walking `Parent` from there reaches the `Body` that holds it. Everything here is
    read from the model, so a snapshot taken in one process owns as much as one taken
    in another; nothing is remembered between them.

    When the walk does not reach a body -- live, a consumed sketch's `Parent` can be a
    chain of generic wrappers that never gets there -- `fallback` looks the feature up by
    name in the Part's bodies (`BodyIndex`).

    Args:
        reference: One raw `Reference` from a topology search.
        fallback: A `BodyIndex` of the Part, consulted only when the walk fails.

    Returns:
        `(body, body_name, feature_name)`, where `body` is the raw owning `Body` COM
        object. Any element is `None` when CATIA did not report it: ownership is a
        guard, and an unknown owner must not turn a working call into a failure.
    """
    try:
        feature = reference.Parent
    except (pywintypes.com_error, AttributeError):
        return None, None, None
    try:
        feature_name = str(feature.Name)
    except (pywintypes.com_error, AttributeError):
        feature_name = None
    node = feature
    for _ in range(_MAX_OWNER_DEPTH):
        if node is None:
            break
        if type(node).__name__ == _BODY_KIND:
            try:
                return node, str(node.Name), feature_name
            except (pywintypes.com_error, AttributeError):
                return node, None, feature_name
        try:
            node = node.Parent
        except (pywintypes.com_error, AttributeError):
            break
    if fallback is not None and feature_name is not None:
        body, body_name = fallback(feature_name)
        if body is not None:
            return body, body_name, feature_name
    return None, None, feature_name


def search_references(
    selection: Any, query: str, part_com_object: Any = None, scope: Any = None
) -> "list[Any]":
    """Runs one topology search and returns its references, preserving the selection.

    Args:
        selection: The raw CATIA `Selection` COM object of the editor editing the Part.
        query: The exact `Selection.Search` query, for example `"Topology.Edge,all"`.
            A query ending in `",sel"` searches inside the current selection, which is
            what `scope` sets up.
        part_com_object: The raw Part being searched. When given, the search is refused
            unless that Part is the active one (`geometry.deletion.require_active_part`).
        scope: An optional raw COM object to select before searching, so that a
            `",sel"` query finds only what belongs to it. Live (probe 42): selecting one
            body and searching `"Topology.Edge,sel"` returned that body's edges only,
            and it followed the selection rather than the In-Work Object.

    Returns:
        One raw `Reference` per hit, in search order.

    Raises:
        ValidationError: `selection` is `None`.
        AutomationError: The selection could not be captured (nothing was changed),
            or the search failed. The model itself is never changed by a search.

    Warns:
        SelectionNotRestoredWarning: The search succeeded, but the selection did not
            come back exactly. The returned references are still valid.
    """
    require_selection(selection)
    require_active_part(part_com_object)
    captured = _capture_selection(selection)
    try:
        selection.Clear()
        if scope is not None:
            selection.Add(scope)
        selection.Search(query)
        count = int(selection.Count)
        references = [
            selection.Item(position).Reference
            for position in range(_FIRST_COM_INDEX, count + _FIRST_COM_INDEX)
        ]
    except pywintypes.com_error as search_error:
        problem = _restore_selection(selection, captured)
        failure = automation_error(search_error, f"running Selection.Search({query!r})")
        if problem is not None:
            failure = AutomationError(
                f"{failure} In addition, {problem}.", failure.hresult
            )
        raise failure from search_error
    except BaseException:
        # Not a CATIA failure, but the user's selection has already been replaced;
        # put it back on the way out without masking the original exception.
        _restore_selection(selection, captured)
        raise
    problem = _restore_selection(selection, captured)
    if problem is not None:
        warnings.warn(
            f"The topology search succeeded, but {problem}. Re-select in the CATIA UI "
            "if the selection matters; the snapshot is valid and the model was not "
            "changed.",
            SelectionNotRestoredWarning,
            stacklevel=_WARNING_STACKLEVEL,
        )
    return references
