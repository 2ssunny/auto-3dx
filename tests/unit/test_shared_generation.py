"""Every wrapper of one CATIA Part shares one model generation (`docs/api-design.md` 5.1).

`Catia.active_part()` builds a new `Part` wrapper on every call, and so do
`part_named()` and a second `Catia.attach()`. When each wrapper owned its own counter,
a snapshot taken through one wrapper stayed "current" after another wrapper of the
same model rebuilt it. The generation is now keyed by COM identity: live, two reads of
the active Part compare `==` while `is` differs, and a different open Part compares
unequal (2026-09-15). These fakes model exactly that with `__eq__`.
"""

from typing import Any

import pytest
import pywintypes

from auto_3dx.core.application import Catia
from auto_3dx.core.part import Part
from auto_3dx.errors import StaleSnapshotError

FILLET_RADIUS = 1.0


class _Selected:
    """Fake `SelectedElement`."""

    def __init__(self, reference: Any) -> None:
        self.Reference = reference
        self.Value = reference


class _Selection:
    """Fake `Selection` whose search returns two edges."""

    def __init__(self) -> None:
        self.items: list[_Selected] = []

    @property
    def Count(self) -> int:  # noqa: N802 - COM property name
        return len(self.items)

    def Item(self, index: int) -> _Selected:  # noqa: N802 - COM method name
        return self.items[index - 1]

    def Clear(self) -> None:  # noqa: N802 - COM method name
        self.items = []

    def Search(self, query: str) -> None:  # noqa: N802 - COM method name
        self.items = [_Selected(object()), _Selected(object())]

    def Add(self, value: Any) -> None:  # noqa: N802 - COM method name
        self.items.append(_Selected(value))


class _ComPart:
    """Fake COM `Part` proxy: a new proxy per read, equal when it is the same Part."""

    def __init__(self, identity: object, name: str = "3D Shape1") -> None:
        self._identity = identity
        self.Name = name
        self.update_calls = 0

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _ComPart) and other._identity is self._identity

    def __hash__(self) -> int:
        return id(self._identity)

    def Update(self) -> None:  # noqa: N802 - COM method name
        self.update_calls += 1


class _UncomparableComPart(_ComPart):
    """Fake proxy whose comparison fails, as a released COM object's might."""

    def __eq__(self, other: object) -> bool:
        raise pywintypes.com_error(-2147418113, "Catastrophic failure", None, None)

    __hash__ = _ComPart.__hash__


def _generation(part: Part) -> int:
    """Reads a Part's generation through a public accessor."""
    return part.part_design.snapshot_generation


def test_two_wrappers_of_one_raw_part_share_a_generation(part_factory: Any) -> None:
    raw = part_factory()
    first, second = Part(raw), Part(raw)

    second.update()

    assert _generation(first) == _generation(second) == 1


def test_equal_proxies_of_one_part_share_a_generation() -> None:
    identity = object()
    first = Part(_ComPart(identity))
    second = Part(_ComPart(identity))
    assert first.com_object is not second.com_object

    second.update()

    assert _generation(first) == 1


def test_a_snapshot_is_stale_after_another_wrapper_rebuilds(part_factory: Any) -> None:
    raw = part_factory()
    first = Part(raw, selection=_Selection())
    second = Part(raw, selection=_Selection())
    snapshot = first.topology.edges()

    second.update()

    with pytest.raises(StaleSnapshotError):
        first.part_design.create_edge_fillet("AUTO3DX_FILLET", snapshot[0], FILLET_RADIUS)
    assert int(raw.MainBody.Shapes.Count) == 0


def test_different_parts_keep_independent_generations() -> None:
    first = Part(_ComPart(object(), "A"))
    second = Part(_ComPart(object(), "B"))

    second.update()

    assert _generation(first) == 0
    assert _generation(second) == 1


def test_a_failed_comparison_is_treated_as_a_different_part() -> None:
    known = Part(_ComPart(object()))
    known.update()

    uncomparable = Part(_UncomparableComPart(object()))

    assert _generation(uncomparable) == 0
    assert _generation(Part(known.com_object)) == 1


_CatiaComPart = type("Part", (_ComPart,), {})
"""`Catia` recognises a Part by `type(obj).__name__ == "Part"`, as CATIA reports it."""


def _session(
    application_factory: Any, editors_factory: Any, editor_factory: Any, raw: Any
) -> Any:
    """Builds a one-Part session whose editor hands out `raw` as its active object."""
    editor = editor_factory(active_object=raw, name="CATIAEditor0", selection=_Selection())
    return application_factory(active_editor=editor, editors=editors_factory(items=[editor]))


def test_catia_lookups_of_one_part_share_a_generation(
    application_factory: Any, editors_factory: Any, editor_factory: Any
) -> None:
    raw = _CatiaComPart(object(), "3D Shape00422534")
    application = _session(application_factory, editors_factory, editor_factory, raw)
    catia = Catia(application)

    active = catia.active_part()
    named = catia.part_named("3D Shape00422534")
    from_another_catia = Catia(application).active_part()
    snapshot = active.topology.edges()

    named.update()

    assert _generation(from_another_catia) == 1
    with pytest.raises(StaleSnapshotError):
        active.part_design.create_edge_fillet("AUTO3DX_FILLET", snapshot[0], FILLET_RADIUS)
