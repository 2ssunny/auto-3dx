"""Wrapper around the 3DEXPERIENCE ``Part`` COM object.

:class:`Part` exposes only the verified surface of the CATIA ``Part`` object:
its name, its parameters, its sketches, its planes, its Part Design features,
its topology, its measurements, ``IsUpToDate()``, and ``Update()``. Unverified
members are intentionally not wrapped here.

A ``Part`` is the unit of state (``docs/api-design.md`` section 2). Every wrapper of
the same CATIA Part shares one model generation, matched by COM identity, and hands it
to every collection it builds. A mutation made through any of them, or through another
wrapper of the same Part, makes every outstanding topology snapshot stale.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pywintypes

from auto_3dx._com import automation_error, format_hresult, hresult_of
from auto_3dx._generation import shared_generation
from auto_3dx.errors import (
    Auto3dxError,
    AutomationError,
    BodyNotFoundError,
    FeatureNotFoundError,
    NoActiveEditorError,
    ParameterTypeError,
    PartUpdateError,
)
from auto_3dx.formulas.collection import FormulaCollection
from auto_3dx.geometry.bodies import Body, BodyCollection
from auto_3dx.geometry.facts import GeometryMeasurer
from auto_3dx.geometry.part_design import (
    WORK_AT_FEATURES as _WORK_AT_FEATURES,
)
from auto_3dx.geometry.part_design import PartDesign
from auto_3dx.geometry.planes import PlaneCollection
from auto_3dx.geometry.sketch import SketchCollection
from auto_3dx.geometry.topology import Topology
from auto_3dx.inspect import Inspector
from auto_3dx.measurement.inertia import SolidMeasurement
from auto_3dx.parameters.collection import ParameterCollection


def _shapes_of(body_com_object: Any) -> "list[Any]":
    """Lists a body's features, tolerating a CATIA collection that reports none."""
    try:
        shapes = body_com_object.Shapes
        count = int(shapes.Count)
        return [shapes.Item(index) for index in range(1, count + 1)]
    except (pywintypes.com_error, AttributeError):
        return []


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
        # Shared by COM identity: `Catia.active_part()` builds a new wrapper on every
        # call, and each must see the others' mutations.
        self._generation = shared_generation(com_object)
        self._topology: Topology | None = None
        self._parameters: ParameterCollection | None = None
        self._sketches: SketchCollection | None = None
        self._part_design: PartDesign | None = None
        self._planes: PlaneCollection | None = None
        self._formulas: FormulaCollection | None = None
        self._measurement: SolidMeasurement | None = None
        self._inspector: Inspector | None = None
        self._bodies: BodyCollection | None = None
        # Raw bodies of the enclosing `work_in` blocks, innermost last. Transient: it
        # exists only while a `with` block runs, never across calls or processes.
        self._work_bodies: list[Any] = []
        # Raw In-Work targets of every enclosing `work_in`/`work_at` block, innermost
        # last, so the innermost block decides where a new feature is created.
        self._work_targets: list[Any] = []

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
                parameters_com_object,
                generation=self._generation,
                dependents_of=self._formulas_reading,
            )
        return self._parameters

    def _formulas_reading(self, parameter: Any) -> "list[Any]":
        """Returns the formulas that read a parameter, for the removal guard.

        Args:
            parameter: The `Parameter` about to be removed.

        Returns:
            The formulas reading it, read from `Relations` in the live model.
        """
        return self.formulas.reading(parameter)

    @property
    def sketches(self) -> SketchCollection:
        """SketchCollection: The sketches on the Part's main body.

        Built on first access and cached afterwards. The collection is given the
        raw ``Part`` object because it needs both ``OriginElements`` (for the
        support planes) and ``MainBody`` (for the sketches themselves).
        """
        if self._sketches is None:
            self._sketches = SketchCollection(
                self._com_object,
                self._selection,
                generation=self._generation,
                body_target=self._target_body,
            )
        return self._sketches

    @property
    def part_design(self) -> PartDesign:
        """PartDesign: The Part Design features (pads) on the Part's main body.

        Built on first access and cached afterwards.
        """
        if self._part_design is None:
            self._part_design = PartDesign(
                self._com_object,
                self._selection,
                self._generation,
                self._target_body,
                self._in_work_target,
            )
        return self._part_design

    @property
    def topology(self) -> Topology:
        """Topology: Edge and face snapshots of the Part's solid.

        Built on first access and cached afterwards. Its snapshots are stamped with
        this Part's model generation, so they are refused once anything reachable
        from this Part changes the model (``docs/api-design.md`` section 7).

        ``edges()``/``faces()`` cover the whole Part, every body's topology in one list,
        unless they are scoped: pass ``body=`` or take the snapshot inside
        ``part.work_in(body)``, where they follow that body like everything else does.
        """
        if self._topology is None:
            self._topology = Topology(
                self._selection,
                self._generation,
                self._com_object,
                self._target_body,
                self._resolve_topology_body,
                GeometryMeasurer(self._editor) if self._editor is not None else None,
            )
        return self._topology

    def _resolve_topology_body(self, body: Any) -> Any:
        """Turns a `body` argument of `part.topology` into a raw CATIA body.

        Args:
            body: A `Body`, the name of one, or a raw body COM object.

        Returns:
            The raw `Body` COM object to search inside.

        Raises:
            BodyNotFoundError: If a name matches no body of this Part.
            AmbiguousNameError: If a name matches more than one.
        """
        if isinstance(body, str):
            return self.bodies.get(body).com_object
        return getattr(body, "com_object", body)

    @property
    def planes(self) -> PlaneCollection:
        """PlaneCollection: Offset and angled planes to sketch on.

        Built on first access and cached afterwards, like every other namespace
        here. The collection itself holds no state: it finds its geometrical set
        and its planes in the live Part, so a collection built in a later process
        sees the planes an earlier one created (``planes.list()``/``names()``/
        ``get(name)``) and can remove them.

        A plane from here can be passed straight to
        ``sketches.create(name, support=plane)``; the three origin-plane
        strings still work unchanged.
        """
        if self._planes is None:
            self._planes = PlaneCollection(
                self._com_object, self._selection, self._generation, self._target_body
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
            self._measurement = SolidMeasurement(
                self._editor, self._main_body, self.is_up_to_date
            )
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

    @property
    def bodies(self) -> BodyCollection:
        """BodyCollection: The Part's bodies, read from the live model.

        Built on first access and cached; the collection itself holds no state, so a
        body created by another process is found by name.
        """
        if self._bodies is None:
            self._bodies = BodyCollection(self._com_object, self._selection, self._generation)
        return self._bodies

    @contextmanager
    def work_in(self, body: "Body | str") -> Iterator[Body]:
        """Models in one body for the duration of a `with` block.

        Inside the block `part.sketches` and `part.part_design` create, list, get and
        remove in that body, and every feature is created with that body as the
        In-Work Object (probe 41: `ShapeFactory` builds in the In-Work Body, while
        sketches must be added through the body's own `Sketches`). Planes made inside the
        block hand the In-Work Object back to that body rather than the main body.

        On leaving the block, normally or through an exception, the In-Work Object that
        was current before is put back and read back to confirm it. Blocks nest. Nothing
        is remembered after the block ends.

        Args:
            body: A `Body` of this Part, or the name of one.

        Yields:
            The target `Body`.

        Raises:
            ParameterTypeError: If `body` is neither a `Body` nor a name, or belongs to
                another Part.
            BodyNotFoundError: If the body is not in this Part now.
            AutomationError: If the In-Work Object cannot be read, set, or restored. When
                the block itself raised, a failed restore is added to that exception as a
                note instead of replacing it.
        """
        target = self._resolve_work_body(body)
        try:
            previous = self._com_object.InWorkObject
        except pywintypes.com_error as error:
            raise automation_error(error, "reading Part.InWorkObject") from error
        self._work_bodies.append(target.com_object)
        self._work_targets.append(target.com_object)
        try:
            try:
                self._com_object.InWorkObject = target.com_object
            except pywintypes.com_error as error:
                raise automation_error(error, "making the body the In-Work Object") from error
            yield target
        except BaseException as error:
            self._work_bodies.pop()
            self._work_targets.pop()
            problem = self._put_back_in_work(previous)
            if problem is not None:
                error.add_note(problem)
            raise
        else:
            self._work_bodies.pop()
            self._work_targets.pop()
            problem = self._put_back_in_work(previous)
            if problem is not None:
                raise AutomationError(problem)

    def _target_body(self) -> Any:
        """Returns the raw body of the innermost `work_in` block, or `None` outside one."""
        return self._work_bodies[-1] if self._work_bodies else None

    @contextmanager
    def work_at(self, feature: Any) -> Iterator[Any]:
        """Models at an existing feature's position in the history for one block.

        ``work_in(body)`` chooses WHICH BODY to model in; this chooses WHERE IN THAT
        BODY'S HISTORY the next feature goes. Observed live (probe 43) on a body holding
        ``PAD`` then ``FILLET``:

        * In-Work Object before the block was ``FILLET`` (the last feature created).
        * Inside ``work_at(pad)`` it was ``PAD``.
        * A pad created inside the block landed **immediately after** the target, giving
          ``PAD, PAD2, FILLET``: CATIA inserts after the In-Work feature rather than
          appending to the end, and the fillet stayed downstream of the new feature.
        * Creating that feature moved the In-Work Object onto it, exactly as it does
          outside a block.
        * ``Part.Update()`` afterwards succeeded and the volume included both pads.

        That is the whole of the verified behaviour. This is not tree reordering: nothing
        here moves an existing feature, and only the insertion point changes.

        Sketches still go to the body being modelled in, so combine this with
        ``work_in(body)`` when the target feature is not in the main body. On leaving the
        block, normally or through an exception, the In-Work Object that was current
        before is put back and read back to confirm it. Blocks nest.

        Args:
            feature: A Part Design feature wrapper from ``part.part_design`` -- a ``Pad``,
                ``Pocket``, ``Shaft``, ``Groove``, fillet, chamfer, and so on.

        Yields:
            The same feature wrapper, for convenience.

        Raises:
            ParameterTypeError: If ``feature`` is not a feature wrapper, or belongs to
                another Part. Raw COM objects are refused: a wrapper is what the SDK can
                check.
            FeatureNotFoundError: If the feature is no longer in this Part.
            AutomationError: If the In-Work Object cannot be read, set, or restored. When
                the block itself raised, a failed restore is added to that exception as a
                note instead of replacing it.
        """
        target = self._resolve_work_feature(feature)
        try:
            previous = self._com_object.InWorkObject
        except pywintypes.com_error as error:
            raise automation_error(error, "reading Part.InWorkObject") from error
        self._work_targets.append(target)
        try:
            try:
                self._com_object.InWorkObject = target
            except pywintypes.com_error as error:
                raise automation_error(
                    error, "making the feature the In-Work Object"
                ) from error
            yield feature
        except BaseException as error:
            self._work_targets.pop()
            problem = self._put_back_in_work(previous)
            if problem is not None:
                error.add_note(problem)
            raise
        else:
            self._work_targets.pop()
            problem = self._put_back_in_work(previous)
            if problem is not None:
                raise AutomationError(problem)

    def _resolve_work_feature(self, feature: Any) -> Any:
        """Returns the raw COM object of a feature wrapper that is in this Part now.

        Args:
            feature: The wrapper the caller passed.

        Returns:
            Its raw COM object, found in one of this Part's bodies.

        Raises:
            ParameterTypeError: If it is not a feature wrapper of this SDK, or its
                feature belongs to another Part.
            FeatureNotFoundError: If it is no longer in this Part.
        """
        if not isinstance(feature, _WORK_AT_FEATURES):
            raise ParameterTypeError(
                "work_at() takes a Part Design feature from part.part_design (a Pad, "
                f"Pocket, fillet, ...), not {type(feature).__name__}."
            )
        com_object = feature.com_object
        for body in self.bodies.list():
            for shape in _shapes_of(body.com_object):
                try:
                    if bool(shape == com_object):
                        return com_object
                except pywintypes.com_error:
                    continue
        raise FeatureNotFoundError(
            "The feature passed to work_at() is not in this Part. A feature of another "
            "Part cannot set this Part's In-Work Object."
        )

    def _in_work_target(self) -> Any:
        """Returns the innermost work context's raw target, or `None` outside one.

        A `work_at` feature and a `work_in` body share one stack, so the innermost block
        wins: `part_design` makes that object the In-Work Object before each creation.
        """
        return self._work_targets[-1] if self._work_targets else None

    def _resolve_work_body(self, body: "Body | str") -> Body:
        """Turns a `Body` or a body name into a `Body` found in this Part now."""
        if isinstance(body, str):
            return self.bodies.get(body)
        if not isinstance(body, Body):
            raise ParameterTypeError(
                f"work_in() takes a Body or a body name, not {type(body).__name__}."
            )
        for candidate in self.bodies.list():
            try:
                if bool(candidate.com_object == body.com_object):
                    return candidate
            except pywintypes.com_error:
                continue
        if not bool(body._part_com_object == self._com_object):
            raise ParameterTypeError("work_in() was given a body that belongs to another Part.")
        raise BodyNotFoundError("The body passed to work_in() is no longer in this Part.")

    def _put_back_in_work(self, previous: Any) -> "str | None":
        """Restores the captured In-Work Object; returns a problem description or `None`."""
        try:
            self._com_object.InWorkObject = previous
            restored = bool(self._com_object.InWorkObject == previous)
        except pywintypes.com_error as error:
            return (
                "The In-Work Object from before work_in() could not be restored "
                f"(HRESULT={format_hresult(hresult_of(error))})."
            )
        if not restored:
            return "The In-Work Object did not return to the object it was before work_in()."
        return None

    def _issues_after_failure(self) -> "tuple[Any, ...]":
        """Reads per-feature state after a failed rebuild, without ever raising.

        Attached to `PartUpdateError.issues` so a caller sees what CATIA reported at the
        moment of failure. A failure to read is swallowed: the rebuild error is the one that
        matters, and a diagnostic must never replace it.

        Returns:
            The `UpdateIssue` tuple, or an empty tuple if it could not be read.
        """
        try:
            return self.inspect.update_issues()
        except (Auto3dxError, pywintypes.com_error, AttributeError, TypeError):
            return ()

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

    def update(self, target: Any = None) -> None:
        """Recompute the Part, or one object in it, by calling CATIA.

        This is the only method in the SDK that rebuilds the model
        (``docs/api-design.md`` section 6). It advances the model generation whether
        it succeeds or fails: the rebuild is when CATIA recomputes topology, and a
        failed rebuild leaves the model in a state the caller must repair.

        With no argument it calls ``Part.Update()`` and rebuilds everything. Given a
        ``target`` it calls ``Part.UpdateObject(target)``, which rebuilds that object
        alone: live (probe 42) that made a body whose pad had never been rebuilt up to
        date and measurable while the rest of the Part stayed as it was, and it did not
        move the In-Work Object. ``body.update()`` is the same call, spelled from the
        body.

        **After ``PartUpdateError``, prefer repair over deletion.** The feature that
        failed is still in the model and every later update fails while the model stays
        invalid, but that does not mean the feature is the problem. When the failure
        followed an edit to something that used to work -- a dimension, a parameter, a
        formula -- put the old value back and update again: live, a pad taken from 30 mm
        to 1 mm broke a fillet that depended on it, and restoring 30 mm rebuilt the Part
        with the fillet intact (``docs/conventions.md`` section 1.10). Remove the new
        feature only when it never built in the first place, or when there is nothing to
        roll back to.

        Does not call Save, and does not touch ``Part.Relations`` or any other
        unverified API.

        Args:
            target: The object to rebuild: a wrapper such as a ``Body``, or a raw CATIA
                object. Defaults to the whole Part.

        Raises:
            PartUpdateError: The rebuild failed, or the call is unusable in this release.
        """
        call = "Part.Update()" if target is None else "Part.UpdateObject()"
        target_com_object = (
            None if target is None else getattr(target, "com_object", target)
        )
        with self._generation.mutation():
            try:
                if target_com_object is None:
                    self._com_object.Update()
                else:
                    self._com_object.UpdateObject(target_com_object)
            except pywintypes.com_error as error:
                hresult = hresult_of(error)
                failure = PartUpdateError(
                    f"{call} failed (HRESULT={format_hresult(hresult)}).", hresult
                )
                failure.issues = self._issues_after_failure()
                raise failure from error
            except (AttributeError, TypeError) as error:
                # A dispatch member missing or rejecting its arguments is a real
                # possibility in some releases. Anything broader is left unmapped so
                # a bug in this library is not reported as a CATIA failure.
                raise PartUpdateError(
                    f"{call} is unusable in this release: {type(error).__name__}."
                ) from error

    def __repr__(self) -> str:
        """str: Debug representation showing the wrapped Part's name."""
        try:
            name = self.name
        except Auto3dxError:
            name = "<unknown>"
        return f"Part(name={name!r})"
