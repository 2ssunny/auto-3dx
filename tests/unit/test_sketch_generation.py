"""Tests for the shared model generation in the sketch/constraint layer.

`docs/api-design.md` section 5 is the contract: every collection/wrapper in
this module gains an optional trailing `generation` parameter, shares it with
everything it constructs, and advances it exactly when a mutating COM call is
*attempted* -- never for a request rejected before COM, and never for a read.

Before this change, nothing in `geometry.sketch`/`geometry.constraint`
advanced the generation at all, even though a sketch or constraint edit drives
the solid features built on it (probe 31: a single dimension change rewrote a
live solid's edge set from 20 to 29, with every name changed).

CATIA is never contacted here. Every COM object is a small self-contained
fake identified purely by `type(obj).__name__`, following the same pattern as
`tests/conftest.py` and the existing `tests/unit/test_model_generation.py`.
"""

from typing import Any

import pytest
import pywintypes

from auto_3dx._generation import ModelGeneration
from auto_3dx.errors import (
    Auto3dxError,
    ParameterNameError,
    ParameterTypeError,
    SketchAlreadyExistsError,
    UnsupportedUnitError,
)
from auto_3dx.geometry.constraint import CONSTRAINT_LENGTH, Constraint
from auto_3dx.geometry.sketch import SUPPORT_XY, Sketch, SketchCollection

SKETCH_NAME = "AUTO3DX_TEST_SKETCH"

XY_AXIS_DATA: "tuple[float, ...]" = (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
"""Verified `GetAbsoluteAxisData` reference frame for `OriginElements.PlaneXY`."""


def _com_error() -> pywintypes.com_error:
    """Builds a `pywintypes.com_error`, as a failed CATIA call would raise."""
    return pywintypes.com_error(
        -2147352567,
        "Exception occurred.",
        (0, "CATIAParameters", "The method Item failed", None, 0, -2147467259),
        None,
    )


# --- Fakes -------------------------------------------------------------------


class AnyObject:
    """Fake CATIA origin-plane wrapper (`OriginElements.PlaneXY`, etc.)."""

    def __init__(self, name: str = "xy plane") -> None:
        self.Name = name


class OriginElements:
    """Fake CATIA `OriginElements`, exposing the three origin planes."""

    def __init__(self) -> None:
        self.PlaneXY = AnyObject("xy plane")
        self.PlaneYZ = AnyObject("yz plane")
        self.PlaneZX = AnyObject("zx plane")


class Dimension:
    """Fake `Dimension`, as exposed by a dimensional `Constraint`."""

    def __init__(self, value: float = 0.0) -> None:
        self.Value = value


class FakeConstraint:
    """Fake CATIA sketch `Constraint`.

    Reading `.Dimension` on a non-dimensional constraint raises, matching the
    real object (verified, `docs/conventions.md` 1.2.4) -- `Constraint._dimension`
    treats that as "no dimension", not a transient failure.
    """

    def __init__(
        self, name: str = "Length.1", type_code: int = CONSTRAINT_LENGTH, dimension: Any = None
    ) -> None:
        self.Name = name
        self.Type = type_code
        self.Status = 0
        self._dimension = dimension

    @property
    def Dimension(self) -> Any:
        if self._dimension is None:
            raise _com_error()
        return self._dimension


class Constraints:
    """Fake CATIA `Constraints` collection (`Sketch.Constraints`).

    `AddMonoEltCst`/`AddBiEltCst` always succeed here (this module is not
    exercising the "outside edition" trap, which is already covered by
    `tests/unit/test_constraints.py`) and return a dimensional `FakeConstraint`
    so `SketchEditor.length()` can be exercised.
    """

    def __init__(self, items: "list[FakeConstraint] | None" = None) -> None:
        self._items: list[FakeConstraint] = list(items or [])
        self.BrokenConstraintsCount = 0
        self.UnUpdatedConstraintsCount = 0

    @property
    def Count(self) -> int:
        return len(self._items)

    def Item(self, index: int) -> FakeConstraint:
        return self._items[index - 1]

    def AddMonoEltCst(self, iCstType: int, iElem: Any) -> FakeConstraint:
        constraint = FakeConstraint(
            name=f"Constraint.{len(self._items) + 1}",
            type_code=iCstType,
            dimension=Dimension(0.0),
        )
        self._items.append(constraint)
        return constraint

    def AddBiEltCst(self, iCstType: int, iFirst: Any, iSecond: Any) -> FakeConstraint:
        constraint = FakeConstraint(
            name=f"Constraint.{len(self._items) + 1}", type_code=iCstType, dimension=None
        )
        self._items.append(constraint)
        return constraint


class Line2D:
    """Fake CATIA `Line2D`, as returned by `Factory2D.CreateLine`."""

    def __init__(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.X1, self.Y1, self.X2, self.Y2 = x1, y1, x2, y2
        self.Construction = False


class Factory2D:
    """Fake CATIA `Factory2D`, as returned by `Sketch.OpenEdition()`."""

    def __init__(self) -> None:
        self.line_calls: list[tuple[float, float, float, float]] = []

    def CreateLine(self, iX1: float, iY1: float, iX2: float, iY2: float) -> Line2D:
        self.line_calls.append((iX1, iY1, iX2, iY2))
        return Line2D(iX1, iY1, iX2, iY2)


class GeometricElements:
    """Fake CATIA `GeometricElements` collection, exposed by a `Sketch`. Empty here."""

    Count = 0

    def Item(self, index: int) -> Any:
        raise _com_error()


class FakeSketch:
    """Fake CATIA `Sketch`.

    `Name` is writable and can be told to raise, mimicking the partial-creation
    case where `Sketches.Add` already mutated the model before the rename
    failed. `OpenEdition`/`CloseEdition` are counted, and `CloseEdition` can
    also be told to raise so a test can pin that the generation still
    advances exactly once even when the close itself fails.
    """

    def __init__(
        self,
        name: str = "Sketch.1",
        axis_data: "tuple[float, ...]" = XY_AXIS_DATA,
        name_write_exception: BaseException | None = None,
        close_edition_exception: BaseException | None = None,
        constraints: Any = None,
    ) -> None:
        self._name = name
        self._axis_data = axis_data
        self.name_write_exception = name_write_exception
        self.close_edition_exception = close_edition_exception
        self.open_edition_calls = 0
        self.close_edition_calls = 0
        self.factory2d = Factory2D()
        self.CenterLine: Any = None
        self.GeometricElements = GeometricElements()
        self.Constraints = constraints if constraints is not None else Constraints()

    @property
    def Name(self) -> str:
        return self._name

    @Name.setter
    def Name(self, value: str) -> None:
        if self.name_write_exception is not None:
            raise self.name_write_exception
        self._name = value

    def GetAbsoluteAxisData(self, seed: Any = None) -> "tuple[float, ...]":
        return self._axis_data

    def OpenEdition(self) -> Factory2D:
        self.open_edition_calls += 1
        return self.factory2d

    def CloseEdition(self) -> None:
        self.close_edition_calls += 1
        if self.close_edition_exception is not None:
            raise self.close_edition_exception


_PLANE_NAME_TO_AXIS_DATA: "dict[str, tuple[float, ...]]" = {"xy plane": XY_AXIS_DATA}


class Sketches:
    """Fake CATIA `Sketches` collection (1-based `Item`, `Count`, `Add`)."""

    def __init__(
        self,
        items: "list[FakeSketch] | None" = None,
        added_name_write_exception: BaseException | None = None,
    ) -> None:
        self._items: list[FakeSketch] = list(items or [])
        self.add_calls: list[Any] = []
        self.added_name_write_exception = added_name_write_exception

    @property
    def Count(self) -> int:
        return len(self._items)

    def Item(self, key: Any) -> Any:
        if isinstance(key, int):
            return self._items[key - 1]
        for item in self._items:
            if item.Name == key:
                return item
        raise _com_error()

    def Add(self, plane: Any) -> FakeSketch:
        self.add_calls.append(plane)
        axis_data = _PLANE_NAME_TO_AXIS_DATA.get(getattr(plane, "Name", None), XY_AXIS_DATA)
        sketch = FakeSketch(
            name=f"Sketch.{len(self._items) + 1}",
            axis_data=axis_data,
            name_write_exception=self.added_name_write_exception,
        )
        self._items.append(sketch)
        return sketch


class Body:
    """Fake CATIA `Body` (`Part.MainBody`), exposing `Sketches`."""

    def __init__(self, sketches: Any = None) -> None:
        self.Sketches = sketches if sketches is not None else Sketches()


class RawPart:
    """Fake CATIA `Part`, exposing only what `SketchCollection` reads."""

    def __init__(self, main_body: Any = None, origin_elements: Any = None) -> None:
        self.MainBody = main_body if main_body is not None else Body()
        self.OriginElements = origin_elements if origin_elements is not None else OriginElements()


class Selection:
    """Fake editor `Selection`, the only verified way to delete a sketch."""

    def __init__(self) -> None:
        self.deleted: list[Any] = []
        self._added: list[Any] = []

    def Clear(self) -> None:
        self._added = []

    def Add(self, com_object: Any) -> None:
        self._added.append(com_object)

    def Delete(self) -> None:
        self.deleted.extend(self._added)


# --- helpers -------------------------------------------------------------------


def _collection(sketches: Any = None, selection: Any = None) -> "tuple[SketchCollection, Any]":
    """Builds a `SketchCollection` sharing one fresh `ModelGeneration`."""
    generation = ModelGeneration()
    part = RawPart(main_body=Body(sketches=sketches))
    collection = SketchCollection(part, selection, generation)
    return collection, generation


# ---------------------------------------------------------------------------
# SketchCollection.create
# ---------------------------------------------------------------------------


def test_create_advances_the_generation_by_exactly_one() -> None:
    """A successful creation is one model change, no more."""
    collection, generation = _collection()

    collection.create(SKETCH_NAME, support=SUPPORT_XY)

    assert generation.value == 1


def test_create_rejected_by_a_bad_name_does_not_advance() -> None:
    """A name rejected before any COM call must leave the model untouched."""
    collection, generation = _collection()

    with pytest.raises(ParameterNameError):
        collection.create("", support=SUPPORT_XY)

    assert generation.value == 0


def test_create_rejected_by_a_duplicate_name_does_not_advance() -> None:
    """`SketchAlreadyExistsError` is raised before `Sketches.Add` is ever called."""
    existing = FakeSketch(name=SKETCH_NAME, axis_data=XY_AXIS_DATA)
    sketches = Sketches(items=[existing])
    collection, generation = _collection(sketches=sketches)

    with pytest.raises(SketchAlreadyExistsError):
        collection.create(SKETCH_NAME, support=SUPPORT_XY)

    assert generation.value == 0
    assert sketches.add_calls == []


def test_create_advances_even_when_the_follow_up_rename_fails() -> None:
    """`Sketches.Add` already mutated the model before the rename failed."""
    sketches = Sketches(added_name_write_exception=_com_error())
    collection, generation = _collection(sketches=sketches)

    with pytest.raises(Auto3dxError):
        collection.create(SKETCH_NAME, support=SUPPORT_XY)

    assert generation.value == 1


# ---------------------------------------------------------------------------
# SketchCollection.ensure
# ---------------------------------------------------------------------------


def test_ensure_advances_by_exactly_one_when_it_creates() -> None:
    """A missing sketch is created, which is one model change."""
    collection, generation = _collection()

    collection.ensure(SKETCH_NAME, support=SUPPORT_XY)

    assert generation.value == 1


def test_ensure_does_not_advance_when_it_reuses() -> None:
    """Reusing a matching existing sketch touches nothing in the model."""
    existing = FakeSketch(name=SKETCH_NAME, axis_data=XY_AXIS_DATA)
    sketches = Sketches(items=[existing])
    collection, generation = _collection(sketches=sketches)

    collection.ensure(SKETCH_NAME, support=SUPPORT_XY)

    assert generation.value == 0


# ---------------------------------------------------------------------------
# SketchCollection.remove
# ---------------------------------------------------------------------------


def test_remove_advances_the_generation_by_exactly_one() -> None:
    """Removing a sketch changes topology exactly as adding one does."""
    existing = FakeSketch(name=SKETCH_NAME, axis_data=XY_AXIS_DATA)
    sketches = Sketches(items=[existing])
    selection = Selection()
    collection, generation = _collection(sketches=sketches, selection=selection)

    collection.remove(SKETCH_NAME)

    assert generation.value == 1
    assert selection.deleted == [existing]


# ---------------------------------------------------------------------------
# Sketch.rename / Sketch.set_center_line
# ---------------------------------------------------------------------------


def test_rename_advances_the_generation_by_exactly_one() -> None:
    """A plain rename is a value write, so it must advance the counter."""
    generation = ModelGeneration()
    sketch = Sketch(FakeSketch(name="Sketch.1"), generation)

    sketch.rename("Renamed")

    assert generation.value == 1
    assert sketch.name == "Renamed"


def test_rename_rejected_by_a_bad_name_does_not_advance() -> None:
    """Name validation runs before any COM write."""
    generation = ModelGeneration()
    sketch = Sketch(FakeSketch(name="Sketch.1"), generation)

    with pytest.raises(ParameterNameError):
        sketch.rename("bad\\name")

    assert generation.value == 0
    assert sketch.name == "Sketch.1"


def test_set_center_line_advances_the_generation_by_exactly_one() -> None:
    """Setting the revolve axis changes the sketch that drives a Shaft/Groove."""
    generation = ModelGeneration()
    fake_sketch = FakeSketch(name="Sketch.1")
    sketch = Sketch(fake_sketch, generation)
    line = fake_sketch.factory2d.CreateLine(0.0, 0.0, 10.0, 0.0)

    sketch.set_center_line(line)

    assert generation.value == 1
    assert fake_sketch.CenterLine is line


# ---------------------------------------------------------------------------
# Sketch.edit()
# ---------------------------------------------------------------------------


def test_edit_advances_the_generation_exactly_once_on_the_happy_path() -> None:
    """Geometry and constraints made inside one session are one mutation."""
    generation = ModelGeneration()
    fake_sketch = FakeSketch(name="Sketch.1")
    sketch = Sketch(fake_sketch, generation)

    with sketch.edit() as editor:
        editor.line(0.0, 0.0, 10.0, 0.0)
        editor.line(0.0, 0.0, 0.0, 10.0)

    assert generation.value == 1


def test_edit_advances_exactly_once_even_when_the_body_raises() -> None:
    """A raise mid-session may still have left geometry behind, so it still counts."""
    generation = ModelGeneration()
    fake_sketch = FakeSketch(name="Sketch.1")
    sketch = Sketch(fake_sketch, generation)

    with pytest.raises(RuntimeError, match="boom"):
        with sketch.edit() as editor:
            editor.line(0.0, 0.0, 10.0, 0.0)
            raise RuntimeError("boom")

    assert generation.value == 1
    assert fake_sketch.close_edition_calls == 1


def test_edit_advances_exactly_once_even_when_close_edition_fails() -> None:
    """`CloseEdition()` is attempted either way, so the advance still happens."""
    generation = ModelGeneration()
    fake_sketch = FakeSketch(name="Sketch.1", close_edition_exception=_com_error())
    sketch = Sketch(fake_sketch, generation)

    with pytest.raises(Auto3dxError):
        with sketch.edit() as editor:
            editor.line(0.0, 0.0, 10.0, 0.0)

    assert generation.value == 1


# ---------------------------------------------------------------------------
# Constraint.set_value
# ---------------------------------------------------------------------------


def test_constraint_set_value_advances_the_generation_by_exactly_one() -> None:
    """A dimension write can rebuild the solid's whole topology (probe 31)."""
    generation = ModelGeneration()
    fake_constraint = FakeConstraint(dimension=Dimension(10.0))
    constraint = Constraint(fake_constraint, generation)

    constraint.set_value(25.0)

    assert generation.value == 1
    assert fake_constraint.Dimension.Value == 25.0


def test_constraint_set_value_rejected_by_a_bad_type_does_not_advance() -> None:
    """`bool` is an `int` subclass; it must be refused before any COM write."""
    generation = ModelGeneration()
    fake_constraint = FakeConstraint(dimension=Dimension(10.0))
    constraint = Constraint(fake_constraint, generation)

    with pytest.raises(ParameterTypeError):
        constraint.set_value(True)  # type: ignore[arg-type]

    assert generation.value == 0
    assert fake_constraint.Dimension.Value == 10.0


def test_constraint_set_value_rejected_by_an_unsupported_unit_does_not_advance() -> None:
    """An unsupported unit is rejected before any COM write."""
    generation = ModelGeneration()
    fake_constraint = FakeConstraint(dimension=Dimension(10.0))
    constraint = Constraint(fake_constraint, generation)

    with pytest.raises(UnsupportedUnitError):
        constraint.set_value(25.0, unit="cm")

    assert generation.value == 0


def test_constraint_set_value_on_a_non_dimensional_constraint_does_not_advance() -> None:
    """No `Dimension` means nothing was, or could have been, written."""
    generation = ModelGeneration()
    fake_constraint = FakeConstraint(dimension=None)
    constraint = Constraint(fake_constraint, generation)

    with pytest.raises(ParameterTypeError):
        constraint.set_value(25.0)

    assert generation.value == 0


# ---------------------------------------------------------------------------
# Shared generation: wrappers returned by list()/get()/create() share it.
# ---------------------------------------------------------------------------


def test_sketch_from_list_shares_the_collections_generation() -> None:
    """Mutating a `Sketch` obtained from `list()` advances the collection's counter."""
    existing = FakeSketch(name=SKETCH_NAME, axis_data=XY_AXIS_DATA)
    sketches = Sketches(items=[existing])
    collection, generation = _collection(sketches=sketches)

    [sketch] = collection.list()
    sketch.rename("Renamed")

    assert generation.value == 1


def test_sketch_from_get_shares_the_collections_generation() -> None:
    """Same guarantee through `get()`."""
    existing = FakeSketch(name=SKETCH_NAME, axis_data=XY_AXIS_DATA)
    sketches = Sketches(items=[existing])
    collection, generation = _collection(sketches=sketches)

    sketch = collection.get(SKETCH_NAME)
    sketch.rename("Renamed")

    assert generation.value == 1


def test_sketch_from_create_shares_the_collections_generation() -> None:
    """Same guarantee through `create()` -- the returned wrapper is not a copy."""
    collection, generation = _collection()

    sketch = collection.create(SKETCH_NAME, support=SUPPORT_XY)
    assert generation.value == 1

    sketch.rename("Renamed")

    assert generation.value == 2


def test_constraint_from_sketch_constraints_shares_the_sketch_generation() -> None:
    """A `Constraint` read from `sketch.constraints` shares the sketch's counter."""
    fake_dimension_constraint = FakeConstraint(dimension=Dimension(5.0))
    fake_sketch = FakeSketch(
        name="Sketch.1", constraints=Constraints(items=[fake_dimension_constraint])
    )
    generation = ModelGeneration()
    sketch = Sketch(fake_sketch, generation)

    [constraint] = sketch.constraints.list()
    constraint.set_value(40.0)

    assert generation.value == 1


def test_constraint_created_during_edit_shares_the_sketch_generation() -> None:
    """A `Constraint` `SketchEditor` creates also shares the sketch's generation."""
    generation = ModelGeneration()
    fake_sketch = FakeSketch(name="Sketch.1")
    sketch = Sketch(fake_sketch, generation)

    with sketch.edit() as editor:
        line = editor.line(0.0, 0.0, 10.0, 0.0)
        constraint = editor.length(line)

    # One advance for closing the session.
    assert generation.value == 1

    constraint.set_value(99.0)

    # A second, independent advance for the explicit value write afterwards.
    assert generation.value == 2


# ---------------------------------------------------------------------------
# Reads never advance the generation.
# ---------------------------------------------------------------------------


def test_reads_never_advance_the_generation() -> None:
    """`list`, `get`, `names`, `count`, `axis_data` and constraint reads are all reads."""
    existing = FakeSketch(name=SKETCH_NAME, axis_data=XY_AXIS_DATA)
    fake_dimension_constraint = FakeConstraint(dimension=Dimension(5.0))
    existing.Constraints = Constraints(items=[fake_dimension_constraint])
    sketches = Sketches(items=[existing])
    collection, generation = _collection(sketches=sketches)

    collection.list()
    collection.get(SKETCH_NAME)
    collection.names()
    assert collection.count == 1
    assert SKETCH_NAME in collection

    sketch = collection.get(SKETCH_NAME)
    sketch.axis_data()
    sketch.support()
    sketch.element_names()

    constraints = sketch.constraints
    constraints.list()
    constraints.names()
    assert constraints.count == 1
    assert constraints.broken_count == 0
    assert constraints.unupdated_count == 0
    constraint = constraints.get(fake_dimension_constraint.Name)
    assert constraint.value == 5.0

    assert generation.value == 0
