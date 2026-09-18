"""Live checks for Phase 2: editing an existing model through the public API.

Each test builds its own `AUTO3DX_IT_EDIT_*` objects on the disposable Part named by
`AUTO3DX_LIVE_PART`, proves one capability against the running CATIA, and removes exactly
what it made. Nothing is saved.

What only a live session can show:

* a feature dimension written through a setter survives `Part.Update()`, changes the
  geometry, is read back by a fresh wrapper, and rolls back;
* a sketch element created in an earlier editing session is found again by its CATIA name
  and accepted by a new constraint;
* `work_at(feature)` inserts the next feature immediately after that feature and restores
  the previous In-Work Object, including after an exception;
* a formula that reads a user parameter blocks that parameter's removal, and removal works
  once the formula is gone.
"""

import math
import sys
from typing import Any

import pytest

pytestmark = pytest.mark.integration

if sys.platform != "win32":
    pytest.skip("Windows COM is required.", allow_module_level=True)

pytest.importorskip("pywintypes", reason="pywin32 is required.")

from auto_3dx import Catia  # noqa: E402
from auto_3dx.errors import (  # noqa: E402
    Auto3dxError,
    CatiaConnectionError,
    NoActiveEditorError,
    NoActivePartError,
    ParameterInUseError,
    ParameterTypeError,
    SketchElementNotFoundError,
)

PREFIX = "AUTO3DX_IT_EDIT_"
SKETCH, PAD, FILLET = f"{PREFIX}SKETCH", f"{PREFIX}PAD", f"{PREFIX}FILLET"
GUIDE_SKETCH = f"{PREFIX}GUIDE"
INSERT_SKETCH, INSERT_PAD = f"{PREFIX}INSERT_SKETCH", f"{PREFIX}INSERT_PAD"
PARAMETER, FORMULA = f"{PREFIX}PARAM", f"{PREFIX}FORMULA"
SIDE, HEIGHT = 40.0, 30.0
RADIUS, WIDER = 4.0, 8.0
INSERT_SIDE, INSERT_HEIGHT, INSERT_X = 10.0, 6.0, 150.0


@pytest.fixture
def part() -> Any:
    """Returns the active Part, skipping when no suitable session is available."""
    try:
        catia = Catia.attach()
    except CatiaConnectionError as error:
        pytest.skip(f"No running 3DEXPERIENCE session: {error}")
    try:
        return catia.active_part()
    except (NoActiveEditorError, NoActivePartError) as error:
        pytest.skip(f"No Part is being edited: {error}")


def _skip_if_ours_exist(part: Any, names: "set[str]") -> None:
    existing = set(part.sketches.names()) | {f.name for f in part.inspect.features()}
    if names & existing:
        pytest.skip("Objects with this test's names already exist; they are not ours.")


def _solid_edge(part: Any, feature_name: str) -> Any:
    edges = [
        edge
        for edge in part.topology.edges(body="PartBody")
        if edge.owner_feature_name == feature_name
    ]
    assert edges, f"no edge owned by {feature_name!r}"
    return edges[0]


def _build_block(part: Any) -> None:
    sketch = part.sketches.create(SKETCH, support="XY")
    with sketch.edit() as editor:
        editor.rectangle(SIDE, SIDE)
    part.part_design.create_pad(PAD, sketch, HEIGHT)
    part.update()


def _cleanup(part: Any) -> None:
    for step in (
        lambda: part.formulas.remove(FORMULA),
        lambda: part.parameters.remove(PARAMETER),
        lambda: part.part_design.remove_edge_fillet(FILLET),
        lambda: part.part_design.remove_pad(INSERT_PAD),
        lambda: part.sketches.remove(INSERT_SKETCH),
        lambda: part.part_design.remove_pad(PAD),
        lambda: part.sketches.remove(SKETCH),
        lambda: part.sketches.remove(GUIDE_SKETCH),
    ):
        try:
            step()
        except Auto3dxError:
            pass
    part.update()


def test_an_existing_fillet_radius_is_edited_rebuilt_and_rolled_back(part: Any) -> None:
    _skip_if_ours_exist(part, {SKETCH, PAD, FILLET})
    before = part.inspect.summary()

    try:
        _build_block(part)
        part.part_design.create_edge_fillet(FILLET, _solid_edge(part, PAD), RADIUS)
        part.update()
        fillet = part.part_design.get_edge_fillet(FILLET)
        assert fillet.radius == pytest.approx(RADIUS)
        volume = part.measurement.measure().volume_mm3

        fillet.set_radius(WIDER)
        assert fillet.radius == pytest.approx(WIDER)
        part.update()
        widened = part.measurement.measure().volume_mm3
        assert widened < volume, "a wider fillet removes more material"

        # A second wrapper holds nothing from the first: the value is in the model.
        fresh = Catia.attach().active_part().part_design.get_edge_fillet(FILLET)
        assert fresh.radius == pytest.approx(WIDER)

        # The rollback path Phase 1 documented, now for a dimension edit.
        fillet.set_radius(RADIUS)
        part.update()
        assert math.isclose(part.measurement.measure().volume_mm3, volume, rel_tol=1e-9)
        assert FILLET in [f.name for f in part.part_design.edge_fillets]
    finally:
        _cleanup(part)

    after = part.inspect.summary()
    assert [(f.name, f.kind) for f in after.features] == [
        (f.name, f.kind) for f in before.features
    ]


def test_a_hole_diameter_and_depth_are_editable(part: Any) -> None:
    hole_name = f"{PREFIX}HOLE"
    _skip_if_ours_exist(part, {SKETCH, PAD, hole_name})

    try:
        _build_block(part)
        faces = part.topology.faces(body="PartBody")
        part.part_design.create_hole(hole_name, faces[0], 5.0)
        part.update()
        hole = part.part_design.get_hole(hole_name)
        assert hole.depth == pytest.approx(5.0)
        volume = part.measurement.measure().volume_mm3

        hole.set_diameter(12.0)
        hole.set_depth(12.0)
        part.update()
        assert hole.diameter == pytest.approx(12.0)
        assert hole.depth == pytest.approx(12.0)
        assert part.measurement.measure().volume_mm3 < volume

        fresh = Catia.attach().active_part().part_design.get_hole(hole_name)
        assert fresh.depth == pytest.approx(12.0)
    finally:
        try:
            part.part_design.remove_hole(hole_name)
        except Auto3dxError:
            pass
        _cleanup(part)


def test_a_sketch_element_is_rediscovered_by_name_and_reused(part: Any) -> None:
    """Element amnesia: the Python objects that drew the geometry are gone."""
    _skip_if_ours_exist(part, {GUIDE_SKETCH})

    try:
        sketch = part.sketches.create(GUIDE_SKETCH, support="XY")
        with sketch.edit() as editor:
            editor.line(-90.0, -90.0, -50.0, -90.0)
            editor.line(-90.0, -70.0, -50.0, -70.0)
            editor.circle(-70.0, -40.0, 5.0)
        part.update()
        del sketch

        fresh = Catia.attach().active_part().sketches.get(GUIDE_SKETCH)
        names = fresh.element_names()
        assert {"Line.1", "Line.2", "Circle.1"} <= set(names)

        first = fresh.get_element("Line.1")
        second = fresh.get_element("Line.2")
        circle = fresh.get_element("Circle.1")
        assert (first.name, first.kind) == ("Line.1", "Line2D")
        assert circle.radius == pytest.approx(5.0)
        with pytest.raises(ParameterTypeError):
            first.radius
        with pytest.raises(SketchElementNotFoundError):
            fresh.get_element("Line.99")
        assert [element.name for element in fresh.elements()] == names

        # The point of rediscovery: a new constraint on elements this process never drew.
        with fresh.edit() as editor:
            constraint = editor.parallel(first, second)
        part.update()
        assert constraint.name
        assert part.is_up_to_date()
    finally:
        _cleanup(part)

    assert GUIDE_SKETCH not in part.sketches.names()


def test_work_at_inserts_after_the_feature_and_restores_the_in_work_object(
    part: Any,
) -> None:
    _skip_if_ours_exist(part, {SKETCH, PAD, FILLET, INSERT_SKETCH, INSERT_PAD})

    try:
        _build_block(part)
        part.part_design.create_edge_fillet(FILLET, _solid_edge(part, PAD), RADIUS)
        part.update()
        pad = part.part_design.get_pad(PAD)
        before_iwo = part.inspect.in_work_object()
        assert before_iwo is not None and before_iwo.name == FILLET

        sketch = part.sketches.create(INSERT_SKETCH, support="XY")
        with sketch.edit() as editor:
            editor.rectangle(INSERT_SIDE, INSERT_SIDE, origin_x=INSERT_X)

        with part.work_at(pad) as target:
            assert target is pad
            inside = part.inspect.in_work_object()
            assert inside is not None and inside.name == PAD
            part.part_design.create_pad(INSERT_PAD, sketch, INSERT_HEIGHT)
        part.update()

        tree = [feature.name for feature in part.inspect.features()]
        assert tree.index(INSERT_PAD) == tree.index(PAD) + 1, (
            "CATIA inserts the new feature immediately after the In-Work feature"
        )
        assert tree.index(FILLET) == len(tree) - 1
        restored = part.inspect.in_work_object()
        assert restored is not None and restored.name == before_iwo.name
        assert part.is_up_to_date()

        with pytest.raises(RuntimeError):
            with part.work_at(pad):
                raise RuntimeError("boom")
        after_error = part.inspect.in_work_object()
        assert after_error is not None and after_error.name == before_iwo.name

        with pytest.raises(ParameterTypeError):
            with part.work_at(part.bodies.main):
                pass
    finally:
        _cleanup(part)


def test_a_formula_blocks_removing_the_parameter_it_reads(part: Any) -> None:
    _skip_if_ours_exist(part, {SKETCH, PAD})
    if PARAMETER in [p.short_name for p in part.inspect.parameters()]:
        pytest.skip("A parameter with this test's name already exists; it is not ours.")

    try:
        _build_block(part)
        part.parameters.create_length(PARAMETER, 12.0)
        source = part.formulas.relation_name(part.parameters.get(PARAMETER))
        part.formulas.create(
            FORMULA, part.part_design.get_pad(PAD).depth_parameter(), f"{source} * 2"
        )
        part.update()
        body_before = part.formulas.get(FORMULA).body

        assert part.formulas.get(FORMULA).inputs()
        assert [f.name for f in part.parameters.dependents(PARAMETER)] == [FORMULA]

        with pytest.raises(ParameterInUseError, match=FORMULA):
            part.parameters.remove(PARAMETER)

        # Nothing was changed: no 'deleted_*' rewrite, no broken rebuild state.
        assert PARAMETER in [p.short_name for p in part.inspect.parameters()]
        assert part.formulas.get(FORMULA).body == body_before
        assert "deleted_" not in part.formulas.get(FORMULA).body
        assert part.is_up_to_date()

        # The supported lifecycle: the formula first, then the parameter.
        part.formulas.remove(FORMULA)
        assert part.parameters.dependents(PARAMETER) == []
        part.parameters.remove(PARAMETER)
        assert PARAMETER not in [p.short_name for p in part.inspect.parameters()]
    finally:
        _cleanup(part)
