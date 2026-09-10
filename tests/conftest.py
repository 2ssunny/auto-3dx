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

    def __init__(self, name: str = "Part1", parameters: Any = None) -> None:
        self.Name = name
        self._parameters = parameters
        self.parameters_access_count = 0
        self.update_calls = 0
        self.update_exception: BaseException | None = None

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


class Editor:
    """Fake CATIA `Editor`, as returned by `Application.ActiveEditor`."""

    def __init__(self, active_object: Any = None, name: str = "Editor1") -> None:
        self.ActiveObject = active_object
        self.Name = name


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
