"""Shared fixtures for auto_3dx tests.

The library identifies CATIA COM object "kinds" purely by
``type(obj).__name__`` (see docs/conventions.md section 4). That means a
plain Python class named e.g. ``Length`` is already a valid fake for a CATIA
Length parameter -- no COM machinery required. This module builds small fake
classes that mimic the handful of CATIA objects/collections the library
touches, plus a couple of factories for constructing `pywintypes.com_error`
so the error-conversion code paths can be exercised without a real CATIA
session.
"""

from collections.abc import Callable
from typing import Any

import pytest
import pywintypes


_UNSET: Any = object()
"""Sentinel for "no override supplied", so `None` can itself be a test value."""


def make_com_error() -> pywintypes.com_error:
    """Builds a realistic `pywintypes.com_error`, as raised by a failed COM call.

    The arguments mirror an actual failure observed against a real
    3DEXPERIENCE session (`Parameters.Item` on a missing name), so tests that
    assert on error-conversion behavior exercise a representative HRESULT.

    Returns:
        A fresh `pywintypes.com_error` instance.
    """
    return pywintypes.com_error(
        -2147352567,
        "Exception occurred.",
        (0, "CATIAParameters", "The method Item failed", None, 0, -2147467259),
        None,
    )


def make_raising_fake(class_name: str, **raising_attrs: BaseException) -> Any:
    """Builds a fake COM object whose named attributes raise on access.

    Useful for testing that wrapper classes convert a `pywintypes.com_error`
    raised by the underlying COM layer into an `Auto3dxError` subclass.

    Args:
        class_name: Name to give the fake's dynamically created class. The
            library identifies COM "kind" via `type(obj).__name__`, so this
            lets a raising fake also masquerade as a particular CATIA type.
        **raising_attrs: Maps an attribute name to the exception instance
            that should be raised whenever that attribute is read.

    Returns:
        An instance of a class named `class_name` where each attribute in
        `raising_attrs` raises the corresponding exception on access.
    """

    def _make_property(exc: BaseException) -> property:
        def _getter(self: Any) -> Any:
            raise exc

        return property(_getter)

    namespace = {name: _make_property(exc) for name, exc in raising_attrs.items()}
    fake_cls = type(class_name, (), namespace)
    return fake_cls()


class Length:
    """Fake CATIA `Length` parameter. `type(obj).__name__ == "Length"`."""

    def __init__(self, name: str = "Length1", value: float = 100.0) -> None:
        self.Name = name
        self.Value = value


class Real:
    """Fake CATIA `Real` parameter -- a non-Length parameter kind."""

    def __init__(self, name: str = "Real1", value: float = 42.0) -> None:
        self.Name = name
        self.Value = value


class Parameters:
    """Fake CATIA `Parameters` collection.

    Supports 1-based `Item(int)` indexing and `Item(str)` name lookup, like
    the real COM collection. A missing name raises `pywintypes.com_error`,
    matching the real collection's behavior. Every call to `Item` is recorded
    in `item_calls` so tests can assert on the exact indices/names used
    (e.g. to pin the 1-based indexing contract).
    """

    def __init__(
        self,
        items: list[tuple[str, Any]] | None = None,
        container: str = "3D Shape00422533",
    ) -> None:
        self._items: list[tuple[str, Any]] = list(items or [])
        self.container = container
        self.item_calls: list[Any] = []
        self.create_calls: list[tuple[str, str, Any]] = []
        self.remove_calls: list[str] = []

    @property
    def Count(self) -> int:
        return len(self._items)

    def Item(self, key: Any) -> Any:
        self.item_calls.append(key)
        if isinstance(key, int):
            index = key - 1
            if 0 <= index < len(self._items):
                return self._items[index][1]
            raise make_com_error()
        for name, obj in self._items:
            if name == key:
                return obj
        # A qualified name resolves too, matching the real collection, which
        # accepts both "Span" and "3D Shape00422533\\Span".
        for name, obj in self._items:
            if name.rsplit("\\", 1)[-1] == str(key).rsplit("\\", 1)[-1]:
                return obj
        raise make_com_error()

    def CreateDimension(self, iName: str, iMagnitude: str, iValue: float) -> Any:
        """Mimics the real method, which qualifies the stored name.

        The real `CreateDimension` also accepts a duplicate name and creates a
        second parameter with the identical name. This fake reproduces that so a
        test can prove the library refuses before ever reaching COM.
        """
        self.create_calls.append((iName, iMagnitude, iValue))
        created = Length(name=f"{self.container}\\{iName}", value=iValue)
        self._items.append((created.Name, created))
        return created

    def Remove(self, iIndex: Any) -> None:
        self.remove_calls.append(iIndex)
        for position, (name, _) in enumerate(self._items):
            if name == iIndex:
                del self._items[position]
                return
        raise make_com_error()


class Part:
    """Fake CATIA `Part`.

    `Update` records how many times it was called and can be configured to
    raise. `Save` raises `AssertionError` unconditionally: the library must
    never call `Save` on any code path, so any test wiring this fake in gets
    an immediate, loud failure if that rule is ever broken.
    """

    def __init__(
        self,
        name: str = "Part1",
        parameters: Any = None,
        origin_elements: Any = None,
        main_body: Any = None,
        shape_factory: Any = None,
    ) -> None:
        self.Name = name
        self._parameters = parameters
        self.parameters_access_count = 0
        self.update_calls = 0
        self.update_exception: BaseException | None = None
        # Geometry layer additions (docs/conventions.md sections 6.9/6.10).
        # All default to freshly built fakes so existing callers that only
        # pass `name`/`parameters` are unaffected.
        self.OriginElements = origin_elements if origin_elements is not None else OriginElements()
        self.MainBody = main_body if main_body is not None else Body()
        # Wire the factory to this body's Shapes so a created pad is findable,
        # as it is in a real session.
        self.ShapeFactory = (
            shape_factory
            if shape_factory is not None
            else ShapeFactory(shapes=self.MainBody.Shapes)
        )

    @property
    def Parameters(self) -> Any:
        self.parameters_access_count += 1
        return self._parameters

    def Update(self) -> None:
        self.update_calls += 1
        if self.update_exception is not None:
            raise self.update_exception

    def Save(self) -> None:
        raise AssertionError("Part.Save must never be called by auto_3dx.")


class VPMRootOccurrence:
    """Fake CATIA `VPMRootOccurrence` -- the assembly-context ActiveObject."""

    def __init__(self, name: str = "Product1") -> None:
        self.Name = name


class Selection:
    """Fake CATIA `Selection`, as returned by `Editor.Selection`.

    This is the ONLY verified way to delete geometry: neither `Sketches` nor
    `Shapes` has a `Remove` method. The fake records the call order so tests can
    assert the `Clear` -> `Add` -> `Delete` sequence, and `deleted` holds the
    objects that were actually removed.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.delete_exception: BaseException | None = None
        # Fails the Nth Clear (1-based). The trailing cleanup Clear is the one
        # whose failure used to be swallowed, leaving a dirty live selection.
        self.clear_exception: BaseException | None = None
        self.failing_clear_ordinal: int | None = None

    def Clear(self) -> None:
        self.calls.append("Clear")
        ordinal = self.calls.count("Clear")
        if self.clear_exception is not None and (
            self.failing_clear_ordinal is None or ordinal == self.failing_clear_ordinal
        ):
            raise self.clear_exception
        self.added.clear()

    def Add(self, com_object: Any) -> None:
        self.calls.append("Add")
        self.added.append(com_object)

    def Delete(self) -> None:
        self.calls.append("Delete")
        if self.delete_exception is not None:
            raise self.delete_exception
        self.deleted.extend(self.added)


class Editor:
    """Fake CATIA `Editor`, as returned by `Application.ActiveEditor`."""

    def __init__(
        self,
        active_object: Any = None,
        name: str = "Editor1",
        selection: Any = None,
    ) -> None:
        self.ActiveObject = active_object
        self.Name = name
        self.Selection = selection if selection is not None else Selection()


class Application:
    """Fake CATIA `Application`, as returned by `attach_running_application`."""

    def __init__(self, active_editor: Any = None, name: str = "3DEXPERIENCE") -> None:
        self.ActiveEditor = active_editor
        self.Name = name


@pytest.fixture
def com_error_factory() -> Callable[[], pywintypes.com_error]:
    """Returns a factory producing fresh `pywintypes.com_error` instances."""
    return make_com_error


@pytest.fixture
def raising_fake_factory() -> Callable[..., Any]:
    """Returns the `make_raising_fake` factory."""
    return make_raising_fake


@pytest.fixture
def length_parameter_factory() -> Callable[..., Length]:
    """Returns a factory for fake `Length` parameters."""
    return Length


@pytest.fixture
def real_parameter_factory() -> Callable[..., Real]:
    """Returns a factory for fake non-Length (`Real`) parameters."""
    return Real


@pytest.fixture
def parameters_collection_factory() -> Callable[..., Parameters]:
    """Returns a factory for fake `Parameters` collections."""
    return Parameters


@pytest.fixture
def part_factory() -> Callable[..., Part]:
    """Returns a factory for fake `Part` objects."""
    return Part


@pytest.fixture
def vpm_root_occurrence_factory() -> Callable[..., VPMRootOccurrence]:
    """Returns a factory for fake `VPMRootOccurrence` objects."""
    return VPMRootOccurrence


@pytest.fixture
def editor_factory() -> Callable[..., Editor]:
    """Returns a factory for fake `Editor` objects."""
    return Editor


@pytest.fixture
def application_factory() -> Callable[..., Application]:
    """Returns a factory for fake `Application` objects."""
    return Application


@pytest.fixture
def fake_length(length_parameter_factory: Callable[..., Length]) -> Length:
    """A single fake Length parameter with default name/value."""
    return length_parameter_factory()


@pytest.fixture
def fake_real(real_parameter_factory: Callable[..., Real]) -> Real:
    """A single fake non-Length parameter with default name/value."""
    return real_parameter_factory()


# ---------------------------------------------------------------------------
# Geometry fakes (docs/conventions.md sections 1.2, 1.3, 6.9, 6.10).
#
# These mimic the COM objects touched by the sketch/pad ("geometry") layer.
# As with the parameter fakes above, "kind" identification is purely by
# `type(obj).__name__`, so plain classes are sufficient fakes.
# ---------------------------------------------------------------------------

XY_AXIS_DATA: tuple[float, ...] = (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
"""9-tuple `GetAbsoluteAxisData` returns for a sketch built on `PlaneXY` (verified)."""

YZ_AXIS_DATA: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
"""9-tuple `GetAbsoluteAxisData` returns for a sketch built on `PlaneYZ` (verified)."""

ZX_AXIS_DATA: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0)
"""9-tuple `GetAbsoluteAxisData` returns for a sketch built on `PlaneZX` (verified)."""

UNRECOGNISED_AXIS_DATA: tuple[float, ...] = (1.0, 2.0, 3.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
"""An axis frame matching none of the three verified supports (offset origin)."""


class AnyObject:
    """Fake CATIA `AnyObject` wrapper.

    Real `OriginElements` planes come back typed this way, NOT as `Plane`
    (docs/conventions.md 1.2). `type(obj).__name__ == "AnyObject"`, matching
    the real, unhelpful wrapper type CATIA hands back for them.
    """

    def __init__(self, name: str = "xy plane") -> None:
        self.Name = name


class OriginElements:
    """Fake CATIA `OriginElements`, exposing the three origin planes.

    Each plane is an `AnyObject` (never a `Plane`), and must be looked up by
    attribute (`PlaneXY`/`PlaneYZ`/`PlaneZX`), never by type.
    """

    def __init__(self) -> None:
        self.PlaneXY = AnyObject("xy plane")
        self.PlaneYZ = AnyObject("yz plane")
        self.PlaneZX = AnyObject("zx plane")


_PLANE_NAME_TO_AXIS_DATA: dict[str, tuple[float, ...]] = {
    "xy plane": XY_AXIS_DATA,
    "yz plane": YZ_AXIS_DATA,
    "zx plane": ZX_AXIS_DATA,
}


class Line2D:
    """Fake CATIA `Line2D`, as returned by `Factory2D.CreateLine`."""

    def __init__(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.X1, self.Y1, self.X2, self.Y2 = x1, y1, x2, y2


class Circle2D:
    """Fake CATIA `Circle2D`, as returned by `Factory2D.CreateClosedCircle`."""

    def __init__(self, center_x: float, center_y: float, radius: float) -> None:
        self.CenterX, self.CenterY, self.Radius = center_x, center_y, radius


class Point2D:
    """Fake CATIA `Point2D`, as returned by `Factory2D.CreatePoint`."""

    def __init__(self, x: float, y: float) -> None:
        self.X, self.Y = x, y


class Factory2D:
    """Fake CATIA `Factory2D`, as returned by `Sketch.OpenEdition()`.

    Records every `CreateLine` / `CreateClosedCircle` / `CreatePoint` call
    (in argument order) so tests can assert the exact coordinates emitted.
    """

    def __init__(self) -> None:
        self.line_calls: list[tuple[float, float, float, float]] = []
        self.circle_calls: list[tuple[float, float, float]] = []
        self.point_calls: list[tuple[float, float]] = []

    def CreateLine(self, iX1: float, iY1: float, iX2: float, iY2: float) -> Line2D:
        self.line_calls.append((iX1, iY1, iX2, iY2))
        return Line2D(iX1, iY1, iX2, iY2)

    def CreateClosedCircle(self, iCx: float, iCy: float, iR: float) -> Circle2D:
        self.circle_calls.append((iCx, iCy, iR))
        return Circle2D(iCx, iCy, iR)

    def CreatePoint(self, iX: float, iY: float) -> Point2D:
        self.point_calls.append((iX, iY))
        return Point2D(iX, iY)


class GeometricElements:
    """Fake CATIA `GeometricElements` collection, exposed by a `Sketch`."""

    def __init__(self, items: list[Any] | None = None) -> None:
        self._items: list[Any] = list(items or [])

    @property
    def Count(self) -> int:
        return len(self._items)

    def Item(self, index: int) -> Any:
        position = index - 1
        if 0 <= position < len(self._items):
            return self._items[position]
        raise make_com_error()


class Sketch:
    """Fake CATIA `Sketch`.

    `Name` is writable, matching the real object. `GetAbsoluteAxisData`
    returns whichever 9-tuple the sketch was constructed with, mimicking one
    of the three verified support frames (or an unrecognised one). Every
    `OpenEdition`/`CloseEdition` call is counted so tests can pin the
    open-edition lifecycle (docs/conventions.md 6.9: `edit()` must always
    close, even when the caller's block raises).
    """

    def __init__(
        self,
        name: str = "Sketch.1",
        axis_data: tuple[float, ...] = XY_AXIS_DATA,
        identity: Any = None,
        name_write_exception: BaseException | None = None,
        axis_data_result: Any = _UNSET,
    ) -> None:
        self._identity = identity if identity is not None else object()
        self._name = name
        self._axis_data = axis_data
        self._axis_data_result = axis_data_result
        self.name_write_exception = name_write_exception
        self.open_edition_calls = 0
        self.close_edition_calls = 0
        self.factory2d = Factory2D()
        self.GeometricElements = GeometricElements()

    @property
    def Name(self) -> str:
        return self._name

    @Name.setter
    def Name(self, value: str) -> None:
        # The real Name write can fail after Sketches.Add already mutated the
        # model, which is the partial-creation case the library must report.
        if self.name_write_exception is not None:
            raise self.name_write_exception
        self._name = value

    def __eq__(self, other: object) -> bool:
        """Models COM identity: `==` compares the underlying object, `is` does not.

        Verified in scripts/probes/14_identity_and_duplicates.py -- two wrappers
        for the same CATIA object compare equal while `a is b` is False.
        """
        if not isinstance(other, Sketch):
            return NotImplemented
        return other._identity is self._identity

    def __hash__(self) -> int:
        return id(self._identity)

    def another_wrapper(self) -> "Sketch":
        """Returns a DISTINCT wrapper for the same underlying sketch."""
        return Sketch(name=self._name, axis_data=self._axis_data, identity=self._identity)

    def GetAbsoluteAxisData(self, oAxisData: Any = None) -> Any:
        if self._axis_data_result is not _UNSET:
            return self._axis_data_result
        return self._axis_data

    def OpenEdition(self) -> Factory2D:
        self.open_edition_calls += 1
        return self.factory2d

    def CloseEdition(self) -> None:
        self.close_edition_calls += 1


class Sketches:
    """Fake CATIA `Sketches` collection (1-based `Item`, `Count`, `Add`).

    `Add(plane)` returns a new fake `Sketch` whose `GetAbsoluteAxisData`
    matches the plane passed in, keyed off the plane's `Name` -- exactly the
    only signal a real `AnyObject` plane carries (docs/conventions.md 1.2).
    Every call is recorded in `add_calls` so tests can assert which plane was
    used to create a sketch.
    """

    def __init__(
        self,
        items: list[tuple[str, Any]] | None = None,
        item_by_name_exception: BaseException | None = None,
        enumeration_exception: BaseException | None = None,
        added_name_write_exception: BaseException | None = None,
    ) -> None:
        self._items: list[tuple[str, Any]] = list(items or [])
        self.add_calls: list[Any] = []
        self.added_name_write_exception = added_name_write_exception
        # A COM failure on Item(name) must NOT be read as "does not exist":
        # doing so creates a duplicate on a retry (fail-open).
        self.item_by_name_exception = item_by_name_exception
        # A COM failure during enumeration must surface as Auto3dxError, never
        # as a not-found error.
        self.enumeration_exception = enumeration_exception

    @property
    def Count(self) -> int:
        if self.enumeration_exception is not None:
            raise self.enumeration_exception
        return len(self._items)

    def Item(self, key: Any) -> Any:
        if isinstance(key, int):
            if self.enumeration_exception is not None:
                raise self.enumeration_exception
            index = key - 1
            if 0 <= index < len(self._items):
                return self._items[index][1]
            raise make_com_error()
        if self.item_by_name_exception is not None:
            raise self.item_by_name_exception
        # Look up by the sketch's CURRENT Name, not the key recorded at Add
        # time: `SketchCollection.create` renames the sketch right after adding
        # it, so a stored key would immediately go stale.
        for _, obj in self._items:
            if getattr(obj, "Name", None) == key:
                return obj
        raise make_com_error()

    def Remove_is_deliberately_absent(self) -> None:
        """`Sketches` has no `Remove` in the real type library (conventions 1.2).

        Named so it cannot be mistaken for the COM method. Deletion goes through
        `Editor.Selection`; see tests/unit/test_geometry_deletion.py.
        """

    def _discard(self, com_object: Any) -> None:
        """Drops a sketch, as a selection-based delete does. Test-only helper."""
        self._items = [entry for entry in self._items if entry[1] is not com_object]

    def Add(self, plane: Any) -> Sketch:
        self.add_calls.append(plane)
        axis_data = _PLANE_NAME_TO_AXIS_DATA.get(
            getattr(plane, "Name", None), UNRECOGNISED_AXIS_DATA
        )
        sketch = Sketch(
            name=f"Sketch.{len(self._items) + 1}",
            axis_data=axis_data,
            # The model is already mutated at this point; a failing Name write
            # afterwards is the partial-creation case.
            name_write_exception=self.added_name_write_exception,
        )
        self._items.append((sketch.Name, sketch))
        return sketch


class Dimension:
    """Fake CATIA `Dimension`, as exposed by `Limit.Dimension`."""

    def __init__(self, value: float = 0.0) -> None:
        self.Value = value


class Limit:
    """Fake CATIA `Limit`, as exposed by `Pad.FirstLimit`/`Pad.SecondLimit`."""

    def __init__(self, value: float = 0.0) -> None:
        self.Dimension = Dimension(value)


class Pad:
    """Fake CATIA `Pad`, as returned by `ShapeFactory.AddNewPad`.

    `FirstLimit.Dimension.Value` carries the pad's height, matching the real
    object (docs/conventions.md 1.2: verified `Value == 15.0` for a pad made
    with `AddNewPad(sketch, 15)`).
    """

    def __init__(
        self,
        name: str = "Pad.1",
        sketch: Any = None,
        height: float = 0.0,
        name_write_exception: BaseException | None = None,
    ) -> None:
        self._name = name
        self.name_write_exception = name_write_exception
        self.Sketch = sketch
        self.FirstLimit = Limit(height)
        self.SecondLimit = Limit(0.0)

    @property
    def Name(self) -> str:
        return self._name

    @Name.setter
    def Name(self, value: str) -> None:
        # AddNewPad already added solid material before this write; a failure
        # here is the partial-creation case the library must report.
        if self.name_write_exception is not None:
            raise self.name_write_exception
        self._name = value


class Shapes:
    """Fake CATIA `Shapes` collection (1-based `Item`, `Count`), holding Pads."""

    def __init__(self, items: list[tuple[str, Any]] | None = None) -> None:
        self._items: list[tuple[str, Any]] = list(items or [])

    @property
    def Count(self) -> int:
        return len(self._items)

    def Item(self, key: Any) -> Any:
        if isinstance(key, int):
            index = key - 1
            if 0 <= index < len(self._items):
                return self._items[index][1]
            raise make_com_error()
        # By current Name: `create_pad` renames the pad after `AddNewPad`.
        for _, obj in self._items:
            if getattr(obj, "Name", None) == key:
                return obj
        raise make_com_error()

    def _append(self, com_object: Any) -> None:
        """Registers a pad, as the real `AddNewPad` does. Test-only helper."""
        self._items.append((getattr(com_object, "Name", ""), com_object))

    def _discard(self, com_object: Any) -> None:
        """Drops a pad, as a selection-based delete does. Test-only helper."""
        self._items = [entry for entry in self._items if entry[1] is not com_object]


class Body:
    """Fake CATIA `Body` (`Part.MainBody`), exposing `Sketches` and `Shapes`."""

    def __init__(self, sketches: Any = None, shapes: Any = None) -> None:
        self.Sketches = sketches if sketches is not None else Sketches()
        self.Shapes = shapes if shapes is not None else Shapes()


class ShapeFactory:
    """Fake CATIA `ShapeFactory`.

    Records every `AddNewPad` call (sketch, height) so tests can assert the
    exact arguments -- in particular, that the height arrived as a `float`
    and that the raw COM sketch object (not a wrapper) was passed.
    """

    def __init__(
        self,
        shapes: Any = None,
        pad_name_write_exception: BaseException | None = None,
    ) -> None:
        self.add_new_pad_calls: list[tuple[Any, float]] = []
        self._pad_count = 0
        # The real AddNewPad registers the pad in the body's Shapes collection,
        # which is how `PartDesign.get_pad` finds it afterwards.
        self.shapes = shapes
        self.pad_name_write_exception = pad_name_write_exception

    def AddNewPad(self, iSketch: Any, iHeight: float) -> Pad:
        self.add_new_pad_calls.append((iSketch, iHeight))
        self._pad_count += 1
        pad = Pad(
            name=f"Pad.{self._pad_count}",
            sketch=iSketch,
            height=iHeight,
            name_write_exception=self.pad_name_write_exception,
        )
        if self.shapes is not None:
            self.shapes._append(pad)
        return pad


@pytest.fixture
def any_object_factory() -> Callable[..., AnyObject]:
    """Returns a factory for fake `AnyObject` planes."""
    return AnyObject


@pytest.fixture
def origin_elements_factory() -> Callable[..., OriginElements]:
    """Returns a factory for fake `OriginElements`."""
    return OriginElements


@pytest.fixture
def factory2d_factory() -> Callable[..., Factory2D]:
    """Returns a factory for fake `Factory2D` objects."""
    return Factory2D


@pytest.fixture
def sketch_factory() -> Callable[..., Sketch]:
    """Returns a factory for fake `Sketch` objects."""
    return Sketch


@pytest.fixture
def sketches_factory() -> Callable[..., Sketches]:
    """Returns a factory for fake `Sketches` collections."""
    return Sketches


@pytest.fixture
def dimension_factory() -> Callable[..., Dimension]:
    """Returns a factory for fake `Dimension` objects."""
    return Dimension


@pytest.fixture
def limit_factory() -> Callable[..., Limit]:
    """Returns a factory for fake `Limit` objects."""
    return Limit


@pytest.fixture
def pad_factory() -> Callable[..., Pad]:
    """Returns a factory for fake `Pad` objects."""
    return Pad


@pytest.fixture
def shapes_factory() -> Callable[..., Shapes]:
    """Returns a factory for fake `Shapes` collections."""
    return Shapes


@pytest.fixture
def body_factory() -> Callable[..., Body]:
    """Returns a factory for fake `Body` objects (`Part.MainBody`)."""
    return Body


@pytest.fixture
def shape_factory_factory() -> Callable[..., ShapeFactory]:
    """Returns a factory for fake `ShapeFactory` objects."""
    return ShapeFactory


@pytest.fixture
def selection_factory() -> Callable[..., Selection]:
    """Returns a factory for fake `Selection` objects."""
    return Selection
