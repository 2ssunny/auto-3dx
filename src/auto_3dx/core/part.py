"""Wrapper around the 3DEXPERIENCE ``Part`` COM object.

:class:`Part` exposes only the verified surface of the CATIA ``Part`` object:
its name, its parameters, its sketches, its planes, its Part Design features,
its topology, its measurements, ``IsUpToDate()``, and ``Update()``. Unverified
members are intentionally not wrapped here.

A ``Part`` is the unit of state (``docs/api-design.md`` section 2). It owns one model
generation and hands it to every collection it builds, so a mutation made through any
of them makes every outstanding topology snapshot stale.
"""

from typing import Any

import pywintypes

from auto_3dx._com import automation_error, format_hresult, hresult_of
from auto_3dx._generation import ModelGeneration
from auto_3dx.errors import (
    Auto3dxError,
    AutomationError,
    NoActiveEditorError,
    PartUpdateError,
)
from auto_3dx.formulas.collection import FormulaCollection
from auto_3dx.geometry.part_design import PartDesign
from auto_3dx.geometry.planes import PlaneCollection
from auto_3dx.geometry.sketch import SketchCollection
from auto_3dx.geometry.topology import Topology
from auto_3dx.inspect import Inspector
from auto_3dx.measurement.inertia import SolidMeasurement
from auto_3dx.parameters.collection import ParameterCollection


class Part:
    """Wrapper around a raw 3DEXPERIENCE ``Part`` COM object.

    Attributes:
        com_object: Read-only access to the raw ``Part`` COM object.
    """

    def __init__(self, com_object: Any, selection: Any = None, editor: Any = None) -> None:
        """Store the raw Part COM object and reset the cached collections.

        Args:
            com_object: The raw CATIA ``Part`` COM object.
            selection: The raw CATIA ``Selection`` COM object from the editor
                that is editing this Part. Only geometry deletion needs it,
                because neither ``Sketches`` nor ``Shapes`` has a ``Remove``
                method. :meth:`Catia.active_part` supplies it; a Part
                constructed directly without one can still read and create.
            editor: The raw CATIA ``Editor`` COM object editing this Part. Only
                measurement needs it, because the measurement services are
                reached through ``Editor.GetService`` rather than through the
                Part. :meth:`Catia.active_part` supplies it; without it
                :attr:`measurement` raises rather than guessing an editor.
        """
        self._com_object = com_object
        self._selection = selection
        self._editor = editor
        self._generation = ModelGeneration()
        self._topology: Topology | None = None
        self._parameters: ParameterCollection | None = None
        self._sketches: SketchCollection | None = None
        self._part_design: PartDesign | None = None
        self._planes: PlaneCollection | None = None
        self._formulas: FormulaCollection | None = None
        self._measurement: SolidMeasurement | None = None
        self._inspector: Inspector | None = None

    @property
    def com_object(self) -> Any:
        """Any: The raw ``Part`` COM object (escape hatch for testing)."""
        return self._com_object

    @property
    def name(self) -> str:
        """str: The Part's name (for example, ``"3D Shape00422533"``).

        Raises:
            Auto3dxError: Reading the underlying COM ``Name`` property failed.
        """
        try:
            return self._com_object.Name
        except pywintypes.com_error as error:
            raise automation_error(error, "reading Part.Name") from error

    @property
    def parameters(self) -> ParameterCollection:
        """ParameterCollection: The Part's parameters.

        Built from the raw COM ``Parameters`` object on first access and
        cached afterwards, so repeated access does not re-cross the COM
        boundary.

        Raises:
            Auto3dxError: Reading the underlying COM ``Parameters`` property
                failed.
        """
        if self._parameters is None:
            try:
                parameters_com_object = self._com_object.Parameters
            except pywintypes.com_error as error:
                raise automation_error(error, "reading Part.Parameters") from error
            self._parameters = ParameterCollection(
                parameters_com_object, generation=self._generation
            )
        return self._parameters

    @property
    def sketches(self) -> SketchCollection:
        """SketchCollection: The sketches on the Part's main body.

        Built on first access and cached afterwards. The collection is given the
        raw ``Part`` object because it needs both ``OriginElements`` (for the
        support planes) and ``MainBody`` (for the sketches themselves).
        """
        if self._sketches is None:
            self._sketches = SketchCollection(
                self._com_object, self._selection, generation=self._generation
            )
        return self._sketches

    @property
    def part_design(self) -> PartDesign:
        """PartDesign: The Part Design features (pads) on the Part's main body.

        Built on first access and cached afterwards.
        """
        if self._part_design is None:
            self._part_design = PartDesign(
                self._com_object, self._selection, self._generation
            )
        return self._part_design

    @property
    def topology(self) -> Topology:
        """Topology: Edge and face snapshots of the Part's solid.

        Built on first access and cached afterwards. Its snapshots are stamped with
        this Part's model generation, so they are refused once anything reachable
        from this Part changes the model (``docs/api-design.md`` section 7).
        """
        if self._topology is None:
            self._topology = Topology(self._selection, self._generation)
        return self._topology

    @property
    def planes(self) -> PlaneCollection:
        """PlaneCollection: Offset and angled planes to sketch on.

        Built on first access and cached afterwards. The cache matters here
        more than elsewhere: the collection owns the one geometrical set every
        plane it creates is appended to, so a fresh collection would create a
        second set.

        A plane from here can be passed straight to
        ``sketches.create(name, support=plane)``; the three origin-plane
        strings still work unchanged.
        """
        if self._planes is None:
            self._planes = PlaneCollection(
                self._com_object, self._selection, self._generation
            )
        return self._planes

    @property
    def formulas(self) -> FormulaCollection:
        """FormulaCollection: The Part's formulas (`Relations`).

        Built on first access and cached afterwards. The collection is given
        the raw `Part` object because it needs both `Relations` (the formulas)
        and `Parameters` (for `GetNameToUseInRelation`).
        """
        if self._formulas is None:
            self._formulas = FormulaCollection(
                self._com_object, generation=self._generation
            )
        return self._formulas

    @property
    def measurement(self) -> SolidMeasurement:
        """SolidMeasurement: Volume, area, mass and centre of gravity of a solid.

        Built on first access and cached afterwards. Unlike every other
        collection here this one is built from the ``Editor``, not the Part: the
        measurement services are reached through ``Editor.GetService``.

        Measuring is how a caller checks that geometry did what was asked, since
        ``Update()`` succeeding only means a feature rebuilt (``docs/status.md``
        2.6). ``part.measurement.measure()`` measures the Part's main body; pass a
        raw item to measure something else.

        Raises:
            NoActiveEditorError: If this Part was constructed without an editor,
                as happens when it is built directly from a raw COM object
                rather than through :meth:`Catia.active_part`.
        """
        if self._editor is None:
            raise NoActiveEditorError(
                "This Part was built without an editor, so it cannot be "
                "measured: the measurement services come from "
                "Editor.GetService. Obtain the Part through Catia.active_part() "
                "or Catia.part_named() instead."
            )
        if self._measurement is None:
            self._measurement = SolidMeasurement(self._editor, self._main_body)
        return self._measurement

    @property
    def inspect(self) -> Inspector:
        """Inspector: Reads what this Part already contains, without changing it.

        Built on first access and cached afterwards. Inspection never advances the
        model generation, never rebuilds, and leaves the selection and the In-Work
        Object as it found them (``docs/api-design.md`` section 11).
        """
        if self._inspector is None:
            self._inspector = Inspector(self)
        return self._inspector

    def _main_body(self) -> Any:
        """Returns the raw ``MainBody``, the default thing to measure.

        Read at measurement time, so a body replaced after the measurement
        object was built is still the one measured.

        Returns:
            The raw CATIA ``Body`` COM object.
        """
        return self._com_object.MainBody

    def is_up_to_date(self, target: Any = None) -> bool:
        """Reports whether CATIA considers a Part object up to date.

        The default target is this raw Part. A public auto_3dx wrapper may be
        passed directly and is unwrapped through its `com_object` property;
        raw CATIA dispatch objects are also accepted.

        Live verification showed a feature-driven transition: after changing
        a Pad height, Part/MainBody/Pad returned `False` before
        :meth:`update` and `True` afterward, while the unaffected Sketch
        stayed `True`. A standalone user Parameter change did not make the
        Part or MainBody return `False`, so this is a rebuild-status query,
        not a general unsaved-change detector.

        This method is read-only. It never calls `Update()`, `Save()`, or
        `PLMPropagate()`.

        Args:
            target: Optional wrapper or raw CATIA object to query. Defaults to
                this Part.

        Returns:
            CATIA's boolean up-to-date status.

        Raises:
            Auto3dxError: The COM call failed or returned a non-boolean value.
        """
        target_com_object = self._com_object if target is None else target
        if target is not None:
            try:
                target_com_object = target.com_object
            except (AttributeError, pywintypes.com_error):
                target_com_object = target
        try:
            result = self._com_object.IsUpToDate(target_com_object)
        except pywintypes.com_error as error:
            raise automation_error(error, "calling Part.IsUpToDate()") from error
        except (AttributeError, TypeError) as error:
            # A release without this member, or one that rejects the argument
            # shape, must not surface as a bare Python error from a COM call --
            # `Shapes.Remove` taught us that a missing member is a real
            # possibility here. Broader exceptions stay unmapped so genuine
            # bugs in this library are not disguised as CATIA failures.
            raise AutomationError(
                "Part.IsUpToDate() is unusable in this release: "
                f"{type(error).__name__}: {error}"
            ) from error
        if not isinstance(result, bool):
            raise AutomationError(
                "Part.IsUpToDate() returned a non-boolean value: "
                f"{type(result).__name__}."
            )
        return result

    def update(self) -> None:
        """Recompute the Part by calling ``Part.Update()``.

        This is the only method in the SDK that rebuilds the model
        (``docs/api-design.md`` section 6). It advances the model generation whether
        it succeeds or fails: the rebuild is when CATIA recomputes topology, and a
        failed rebuild leaves the model in a state the caller must repair.

        After ``PartUpdateError``, the feature that caused it is still in the model,
        and every later update fails until it is removed. Remove it before doing
        anything else.

        Does not call Save, and does not touch ``Part.Relations`` or any other
        unverified API.

        Raises:
            PartUpdateError: ``Part.Update()`` failed, or is unusable in this release.
        """
        with self._generation.mutation():
            try:
                self._com_object.Update()
            except pywintypes.com_error as error:
                hresult = hresult_of(error)
                raise PartUpdateError(
                    f"Part.Update() failed (HRESULT={format_hresult(hresult)}).", hresult
                ) from error
            except (AttributeError, TypeError) as error:
                # A dispatch member missing or rejecting its arguments is a real
                # possibility in some releases. Anything broader is left unmapped so
                # a bug in this library is not reported as a CATIA failure.
                raise PartUpdateError(
                    f"Part.Update() is unusable in this release: {type(error).__name__}."
                ) from error

    def __repr__(self) -> str:
        """str: Debug representation showing the wrapped Part's name."""
        try:
            name = self.name
        except Auto3dxError:
            name = "<unknown>"
        return f"Part(name={name!r})"
