# auto-3dx API design contract

This document is the architectural contract for `auto-3dx`. New public API, and changes to
existing public API, are judged against it. Where the code and this document disagree, one of
them is a bug: fix the code, or change this document in the same commit with the reason.

It supersedes the older layering, error-hierarchy and root-export sections of
`docs/conventions.md` (sections 3, 5 and 6.7). The measured CATIA facts in
`docs/conventions.md` section 1 remain the ground truth this contract is built on.

Every section carries a status:

| Status | Meaning |
|---|---|
| Enforced | Implemented, and a test fails if it regresses. |
| Implemented | Implemented, but not yet pinned by a dedicated test. |
| Planned | Decided here, not yet implemented. The migration table at the end tracks it. |

---

## 1. What this SDK is

`auto-3dx` is a general-purpose Python SDK for the 3DEXPERIENCE CATIA Automation object model,
driven over Windows COM from an external process.

It exposes **generic modelling primitives**: parameters, planes, sketches, solid features,
topology references, measurement and inspection. A gear, a bracket, a housing or a wing is
built by composing those primitives. The core package never gains domain methods such as
`create_gear()`; those belong in examples, recipes or downstream packages.

Feature count is not a goal. A new CATIA capability is added when it fills a gap in the generic
primitives, validates an abstraction, or unlocks inspection, selection, measurement, export or
safety.

---

## 2. Object model

Status: Implemented, except where marked.

```text
Catia                                    one attached session
│  attach()  active_editor()  active_part()  editors()  parts()  part_named()
│
└── Part                                 one Part, bound to the editor editing it
    ├── parameters    ParameterCollection   user parameters, units, typed create/ensure
    ├── formulas      FormulaCollection     CATIA Relations (formulas)
    ├── planes        PlaneCollection       offset and angled reference planes
    ├── sketches      SketchCollection      Sketch -> edit() -> SketchEditor
    ├── part_design   PartDesign            solid features (Pad, Pocket, Hole, ...)
    ├── topology      Topology              edges() and faces() snapshots
    ├── measurement   SolidMeasurement      volume, area, mass, centre of gravity
    ├── inspect       Inspector             structured read-only model summary
    ├── is_up_to_date()                     CATIA rebuild status
    └── update()                            the only call that rebuilds the model
```

Rules:

- **A `Part` is the unit of state.** Everything reachable from a `Part` shares that Part's
  selection, editor and model generation (section 5). Obtain wrappers through the `Part`
  rather than constructing them from raw COM objects.
- **Namespaces are nouns, operations are verbs.** `part.sketches.create(...)`, never
  `part.create_sketch(...)`.
- `measurement` stays a noun, not `measure`, because its operation is already the verb:
  `part.measurement.measure()`.
- The name `export` is reserved for file export (section 12). It does not exist yet.

---

## 3. Naming conventions

Status: Implemented.

| Kind | Convention | Example |
|---|---|---|
| Collection attribute | plural noun | `part.sketches`, `part.planes` |
| Feature namespace | domain noun | `part.part_design` |
| Wrapper class | singular noun, CATIA's own term where it is clear | `Pad`, `Sketch`, `Chamfer` |
| Create | `create_<thing>` or `create` when the collection holds one kind | `planes.create_offset` |
| Create-or-reuse | `ensure_<thing>` / `ensure` | `parameters.ensure_length` |
| Lookup by name | `get_<thing>` / `get` | `part_design.get_pad` |
| Delete | `remove_<thing>` / `remove` | `sketches.remove` |
| Snapshot of transient state | noun method returning a snapshot | `topology.edges()` |
| Units in a field name | suffix with the unit when it is not millimetres | `volume_mm3`, `mass_kg` |

Values in the public API are millimetres and degrees unless a field name says otherwise.
Conversion from CATIA's internal SI units happens at the boundary, never in caller code.

---

## 4. Collection conventions

Status: Implemented for parameters, sketches, formulas, constraints and planes. Patterns and
topology are documented exceptions.

A collection holding **one kind** of named object offers, where live evidence supports it:

```python
collection.count            # property
collection.list()           # every item, as wrappers, in CATIA's order
collection.names()          # the names, in the same order
collection.get(name)        # exactly one item, or NotFoundError / AmbiguousNameError
name in collection
collection.create(...)      # or typed constructors: create_length, create_offset, ...
collection.ensure(...)      # only when "the same" can be proven from readable data
collection.remove(name)
```

Domain-specific constructors are preferred over one overloaded `create` when the kinds take
different arguments: `parameters.create_length(...)`, `planes.create_angle(...)`.

**A heterogeneous namespace** such as `part_design` groups several kinds. It uses per-kind
members (`pads`, `get_pad`, `create_pad`, `remove_pad`) instead of one generic set, because a
single `create` could not have a truthful signature.

Rules that apply everywhere:

1. **An operation exists only with live evidence.** If enumerating a CATIA collection has never
   been driven end to end, the wrapper does not offer `list()` or `get()` for it, and the gap is
   documented. `PlaneCollection` had no `list()` for this reason until probe 38 drove
   `HybridBodies` and `HybridShapes` end to end; it now offers `list`/`names`/`get`, and still no
   `ensure_*`: that is a deliberate scope choice, not a missing capability.
2. **Names are not unique in CATIA.** `get` enumerates and counts matches. Two matches raise
   `AmbiguousNameError`; it never silently picks the first.
3. **Existence is decided by enumeration**, never by catching a COM failure from a name lookup.
   A failed lookup does not distinguish "absent" from "transient failure", and treating it as
   absent lets retries pile up duplicates.
4. **`ensure` reuses only what readable data proves is the same.** A sketch is the same if its
   axis data matches; a pad if its sketch is the same COM object. Where no truthful comparison
   exists (edge and face features, planes), there is no `ensure`. A missing method is better
   than one that silently reuses the wrong geometry.
5. **`remove` takes a name when a verified name lookup exists, otherwise the wrapper.**
   `remove_rectangular_pattern(pattern)` and `planes.remove(plane)` take the wrapper.

---

## 5. Mutation semantics and model generation

Status: Enforced. Every collection and wrapper reachable from a `Part` shares its generation
(`tests/unit/test_part_generation_wiring.py`), and each mutation path is pinned by the
generation tests for its module: `test_model_generation.py`, `test_sketch_generation.py`,
`test_plane_generation.py` and `test_value_generation.py`. Every wrapper of the same CATIA
Part shares one generation (5.1, `test_shared_generation.py`, live
`test_shared_generation_live.py`).

Topology references are transient. A BRep name cannot be stored and re-resolved, and a rebuild
can change every edge and face name and index. Reusing an old reference after a change succeeds
or fails depending on whether that particular edge survived, which a caller cannot know. The
SDK therefore tracks a **model generation** and refuses stale references before calling CATIA.

### 5.1 The generation

- Each CATIA Part has exactly one generation counter. Every collection and wrapper obtained
  through a `Part` shares it.
- Every `Part` wrapper of the same CATIA Part shares that counter, matched by COM identity:
  two `active_part()` reads compare `==` while `is` differs, `part_named()` of the same name
  compares `==`, and a different open Part compares unequal (live, 2026-09-15). This holds
  across `active_part()`, `part_named()`, `parts()`, separate `Catia.attach()` calls and a
  `Part` built directly from the raw object, because `Part` itself looks the counter up.
- The registry is process-wide and keeps each Part it has seen for the life of the process.
  Forgetting one would let a later wrapper start again at zero while a snapshot from the old
  counter at zero still looked current. A comparison that fails counts as a different Part: a
  spare counter is safe, a counter shared between two Parts is not.
- The counter is private. Callers observe it only through staleness errors and the `generation`
  attribute on snapshots.

### 5.2 What advances it

The generation advances when **any** of these happens through the SDK:

| Operation | Advances | Why |
|---|---|---|
| Creating any feature, sketch, plane, parameter or formula | yes | the model gains an object |
| Removing any of them | yes | removing a feature changes topology exactly as adding one does |
| Writing a value: parameter `set`, feature `set_height` / `set_depth` / `set_*_angle`, constraint `set_value` | yes | a dimension change rebuilt a live solid from 20 edges to 29 with every name changed (probe 31) |
| `ensure_*` that writes to an existing object | yes | it is a value write |
| Renaming, activating or modifying a formula | yes | a formula can drive geometry |
| Closing a `sketch.edit()` session | yes | sketch geometry and constraints drive features |
| `part.update()`, whether it succeeds or fails | yes | the rebuild is when CATIA recomputes topology |
| Validation failure before any COM call | no | nothing reached CATIA |
| Read-only calls: `list`, `get`, `names`, measurement, inspection, snapshots | no | the model is unchanged |

**Parameter writes advance it even when the parameter drives nothing.** The SDK cannot tell
whether a parameter feeds a formula that feeds a dimension, so it assumes it does.

### 5.3 When it advances

The generation advances **as soon as the mutating COM call has been attempted**, before the SDK
returns or raises. A call that raised may still have changed the model: `AddNew*` can create a
feature and then fail its rename. Advancing on attempt, not on success, keeps that case safe.

A few calls advance the generation more than once for one logical change. Setting a value
while creating a sketch dimension, for example, advances it for the value write and again
when the edit session closes. Over-advancing only makes a snapshot stale sooner; it can never
let a stale reference through, so it is accepted rather than engineered away.

### 5.4 What it cannot see

Changes made outside the SDK, through the CATIA user interface or another script, are invisible
to the generation. A snapshot taken before such a change is not detected as stale. Take a fresh
snapshot immediately before using it.

### 5.5 Stale detection

Every topology handle records the generation of the snapshot it came from. Any operation that
consumes a handle compares it with the Part's current generation **before calling CATIA** and
raises `StaleSnapshotError` on mismatch. The model is untouched when this is raised.

---

## 6. Update policy

Status: Enforced. `tests/unit/test_update_policy.py` parses the package source and fails if
anything other than `Part.update()` calls `Update()`, or if anything calls `Save()` or
`PLMPropagate()`. `update()` advancing the generation is pinned by the generation tests.

**`part.update()` is the only method that rebuilds the model.** No constructor, setter, `ensure`
or removal calls `Part.Update()`.

```python
pad = part.part_design.create_pad("Base", sketch, 20.0)
part.update()
```

Why explicit:

- A rebuild is observable and can fail. A caller, and especially an AI agent, must be able to
  point at the line where the rebuild happened.
- A failed update leaves the feature in the tree, and **every later update fails until that
  feature is removed**. Hiding rebuilds inside constructors would scatter that failure across
  unrelated calls.
- Several mutations often form one valid state only together, such as a sketch and the pad
  built on it. Batching them before one rebuild avoids rebuilding invalid intermediate states.

After `part.update()` raises `PartUpdateError`:

1. The feature that caused it is still in the model.
2. Remove it with the matching `remove_*` method before doing anything else.
3. Do not retry blindly. The SDK does not roll back automatically, because removing a pad
   cascades to its sketch, which makes automatic rollback more dangerous than reporting.

`part.is_up_to_date()` reports CATIA's rebuild status. It is a rebuild-status query, not an
unsaved-change detector: a standalone parameter change does not make it return `False`.

---

## 7. Topology references

Status: Implemented. `part.part_design.snapshot_edges()` and `snapshot_faces()` remain as
deprecated aliases that warn and share the same generation; they will be removed before 1.0.

```python
edges = part.topology.edges()          # EdgeSnapshot of the whole solid
fillet = part.part_design.create_edge_fillet("F1", edges[0], 1.0)
part.update()

faces = part.topology.faces()          # a NEW snapshot: the model changed
part.part_design.create_shell("S1", faces[0], 2.0, 0.0)
```

- A snapshot covers the whole solid. No verified search scopes it to one feature.
- `Edge.index` is a position in one snapshot, not an identity.
- `Edge.descriptor` is CATIA's BRep string, for logging and comparison only. It cannot be stored
  and resolved later: `CreateReferenceFromBRepName` failed in every context tried.
- A snapshot is single-generation (section 5).
- Taking a snapshot does not leave the user's CATIA selection changed. The selection is
  captured before the search, restored afterwards and checked by count. When it cannot be
  captured, the snapshot is refused with `AutomationError` before anything changes. When
  CATIA silently refuses part of the restore (live: a Pad re-added after its own faces), the
  snapshot is still returned and `SelectionNotRestoredWarning` is emitted: the selection is
  already lost by then, so raising would only discard a valid snapshot.

**Persistent semantic identity is not solved.** A future selector may choose an edge or face by
measurable properties such as geometry type, normal, radius, area or position. No such selector
is public until the properties it depends on are live-verified and the choice is deterministic.

---

## 8. Error architecture

Status: Enforced. `tests/unit/test_errors.py` pins every class to its category, and
`tests/unit/test_error_classification.py` pins that every module translates COM failures
through `auto_3dx._com` and that guards raise by when they happen.

Warnings sit outside this hierarchy, so `except Auto3dxError` never hides one. A warning
reports a side effect the SDK could not fully undo after an operation that succeeded;
`SelectionNotRestoredWarning(UserWarning)` is the only one.

Errors are grouped by **what the caller can do about them**:

```text
Auto3dxError
├── SessionError             could not reach or use a running session
│   ├── Com3dxNotFoundError
│   ├── CatiaConnectionError
│   ├── NoActiveEditorError
│   └── NoActivePartError
├── ValidationError          rejected before any COM call; the model is untouched
│   ├── ParameterNameError
│   ├── ParameterTypeError
│   ├── UnsupportedUnitError
│   ├── UnsupportedMagnitudeError
│   ├── UnsupportedSupportError
│   └── StaleSnapshotError
├── NotFoundError            no object with that name exists
│   ├── ParameterNotFoundError
│   ├── SketchNotFoundError
│   ├── FeatureNotFoundError
│   ├── FormulaNotFoundError
│   └── ConstraintNotFoundError
├── ConflictError            the model's naming or state forbids the request
│   ├── ParameterAlreadyExistsError
│   ├── SketchAlreadyExistsError
│   ├── FormulaAlreadyExistsError
│   ├── FeatureConflictError
│   ├── SketchSupportMismatchError
│   └── AmbiguousNameError
└── AutomationError          CATIA rejected or failed a call
    ├── PartUpdateError
    └── PartialCreationError
```

Rules:

- **`ValidationError` guarantees the model is untouched.** Anything raised after a COM call was
  attempted must not be a `ValidationError`.
- **An unexpected COM failure is an `AutomationError`**, carrying the HRESULT in its message and
  as an attribute, with the original `pywintypes.com_error` chained via `raise ... from error`.
  `pywintypes.com_error` never escapes the SDK.
- **Only COM failures are mapped.** A Python exception from a bug inside the SDK propagates
  unchanged. Disguising a bug as a CATIA failure costs more debugging time than it saves.
  One exception: `AttributeError` and `TypeError` raised by a COM dispatch call itself are
  mapped, because a member missing from a release is a real possibility (`Shapes.Remove` does
  not exist in B428).
- COM error translation lives in one module, `auto_3dx._com`: `automation_error(error, action)`
  returns an `AutomationError` with the HRESULT as `hresult`. A module may keep the private
  name `_wrap_com_error` only as an alias of it, for sibling modules that import that name.
- A guard that refuses a request before any COM call raises a `ValidationError`, even when
  the refusal is about state rather than arguments: reusing a closed `SketchEditor`,
  re-entering `sketch.edit()`, or deleting without an editor selection. When CATIA returns
  data the SDK cannot use, such as non-numeric axis data, that is an `AutomationError`.
- Known naming debt: `ParameterTypeError` is also raised for non-parameter arguments such as an
  edge, a radius or a pattern spacing. It is a `ValidationError`, so catching the category is
  correct; renaming it is deferred until a caller needs to tell those cases apart.
- Messages are English sentences ending in a full stop, and say what the caller can do.

---

## 9. The raw COM escape hatch

Status: Implemented.

Every wrapper exposes its underlying Automation object as the read-only property `com_object`.
That is the one sanctioned escape hatch. There is no second alias such as `raw`.

Using it bypasses validation, generation tracking and every safety rule in this document.

Classification of raw COM crossing the public boundary:

| Where | Direction | Classification |
|---|---|---|
| `wrapper.com_object` | out | intentional escape hatch |
| `SketchEditor.line()` / `circle()` / ... | out | resolved: they return `SketchElement`, whose `com_object` is the raw 2D object |
| `set_center_line`, `set_construction`, constraint methods | in | resolved: accept a `SketchElement`; a raw 2D object is still accepted for compatibility |
| `part.measurement.measure()` | in | resolved: defaults to the main body, and an explicit raw item is still accepted |
| `EditorInfo.com_object` | out | intentional |

A normal workflow must never require the caller to reach for `com_object`. When one does, that
is a gap in the SDK.

A wrapper can carry facts a raw object cannot. A `SketchElement` records the sketch it was
drawn in, so passing an element from one sketch into another sketch's constraint or centre line
is refused with `ValidationError` before any COM call. Sketches are compared with COM `==`, which
is live-verified for sketches, not Python `is`. A raw object carries no owner and is not checked.
`SketchElement` deliberately exposes no geometry reads such as radius or coordinates: their live
evidence varies by property, so those stay behind `com_object` until each is verified.

---

## 10. Transport boundary

Status: Implemented.

- Only `auto_3dx.transport` knows how a session is found and attached: `com3dx`, installation
  discovery and `get3dxClient()`.
- Higher layers receive COM objects and never import `com3dx`.
- Higher layers may import `pywintypes` only to catch `com_error` at their boundary.
- Non-Windows backends are not designed for. There is no abstraction layer for them.

---

## 11. Inspection

Status: Implemented, pinned by `tests/unit/test_inspection.py` and live by
`tests/integration/test_inspection_live.py`.

Reading an existing model reliably matters as much as creating geometry, because an agent must
be able to find out what is there before it changes anything.

- Inspection is read-only. It never advances the generation, never rebuilds, and leaves the
  CATIA selection and In-Work Object as it found them.
- Results are frozen dataclasses. Text rendering is a layer on top, never the primary output.
- Each field is backed by a live-verified read. A field CATIA cannot report reliably is absent,
  not guessed.

```python
summary = part.inspect.summary()       # PartSummary, a frozen dataclass
summary.name                           # the Part name
summary.up_to_date                     # CATIA rebuild status
summary.features                       # FeatureInfo(name, kind, supported), tree order
summary.sketches                       # sketch names, tree order
summary.parameters                     # ParameterInfo for user parameters only
summary.bodies                         # BodyInfo(name, is_main, features, sketches)
summary.geometrical_sets               # GeometricalSetInfo(name, elements, nested_set_count)
summary.topology                       # TopologyCounts(edges, faces), None without a selection
summary.in_work_object                 # InWorkObjectInfo(name, kind, is_main_body), or None
part.inspect.in_work_object()          # the same value on its own
print(summary.render())                # human-readable text built from the data
```

`features` lists every item in the main body, including kinds created in the CATIA user
interface that the SDK does not wrap; `supported` says whether `part.part_design` can handle
that kind. Nothing in the model is hidden because the SDK cannot create it.

`bodies` includes the main body, recognised by COM identity rather than by name. A feature in
any other body has `supported=False`, because `part.part_design` works on the main body only.
`geometrical_sets` lists the sets directly under the Part with their elements' names and kinds.
`topology` counts come from `part.topology`, so the user's selection is restored (section 7)
and the generation does not advance.

`in_work_object` reports where CATIA puts the next feature: its `name`, its `kind` (the CATIA
wrapper type name) and `is_main_body` (COM identity with `MainBody`, not a name comparison).
It is `None` when CATIA reports no In-Work Object. The value never carries the COM object, so
an agent can check the In-Work Object without `part.com_object.InWorkObject`. Observed live
(2026-09-15): creating and editing a sketch left it unchanged, creating a pad made the new pad
the In-Work Object (`kind="Pad"`), and creating a plane handed it back to the main body
(`kind="Body"`, `is_main_body=True`). Removing features does not restore the previous one.
There is no public setter.

Deliberately absent, because no live read backs them yet: the contents of nested geometrical
sets (only their count is verified), geometrical sets inside a body, and sketches inside a
geometrical set.

---

## 12. Measurement, export and persistence

Status: measurement Implemented. Export probed live (probe 39) and not available: see below.

**Measurement** is a verification layer. A capability is exposed only when it is backed by
reproducible live evidence. An inertia bounding box once returned correct values and later
returned all zeros silently on an unchanged model, so it is not exposed.

**A missing capability is safer than a silently incorrect one.**

**Operations fall into three safety classes:**

| Class | Examples | Rule |
|---|---|---|
| Read | `list`, `get`, measurement, inspection | never changes the model |
| Model mutation | `create_*`, `set`, `remove_*`, `update` | changes the in-session model only; the user decides whether to keep it |
| Persistence | Save, PLMPropagate, writing or overwriting files | see below |

- The SDK never calls `Save()` or `PLMPropagate()`. In 3DEXPERIENCE they commit to the server
  and include every unsaved change in the session, not just the SDK's.
- File export is a persistence operation. When it exists it will take an explicit path, refuse
  to overwrite an existing file unless asked to, and never save the model as a side effect.
- **Export is not available in this installation.** The only Automation route is
  `PartDocument.ExportData(path, format)`, reached through `Application.Documents` by matching
  `PartDocument.Part` to the Part. On the active Part's document, which is PLM-backed (empty
  `Path`, opaque `FullName`), both `stp` and `stl` failed with `E_FAIL` and no description. No
  file was written and `Saved` did not change. A new non-Part editor appeared in the session
  after those attempts and could not be attributed with certainty, so export attempts are
  not repeated. `part.export` stays reserved and unimplemented.

---

## 13. Package root exports

Status: Enforced by `tests/unit/test_public_exports.py`, which also proves every class that
left the root is still importable from its own package.

`from auto_3dx import ...` offers only what an ordinary script needs to name directly:

```python
from auto_3dx import Catia, Part
from auto_3dx import (
    Auto3dxError, SessionError, ValidationError, NotFoundError, ConflictError,
    AutomationError, PartUpdateError, StaleSnapshotError,
)
```

Everything else is reached through attributes (`part.sketches`) and imported for type hints from
its module: `from auto_3dx.geometry import Sketch`, `from auto_3dx.errors import
SketchNotFoundError`. Every public class stays importable from its own package.

Why small: a large root makes every implementation class look like a stable entry point, turns
each internal rename into a breaking change, and hides which names an ordinary user needs.

---

## 14. Verification policy

Status: Enforced by review.

Evidence ranks, strongest first:

```text
live integration behaviour
  > official or local Automation documentation (the generated type library)
  > existing integration tests
  > unit tests with fakes
  > assumptions
```

- **Every COM call in the public API is backed by live evidence**: a probe under
  `scripts/probes/` and, for anything a caller relies on, an integration test.
- "Verified" means the call succeeded **and** `Part.Update()` succeeded afterwards, and where
  possible the observable result was checked. A call that did not throw proves nothing.
- Unit tests use fakes. They cannot catch a CATIA behaviour the fake does not reproduce;
  `Shapes.Remove` not existing and qualified parameter names both slipped past green unit tests.
- When live behaviour contradicts earlier work, correct the implementation, the tests, this
  document and the earlier conclusion together.
- There is no experimental namespace. Unverified behaviour lives in probes, not in the package.

---

## 15. Live test safety

Status: Enforced by review.

- Never save the test document.
- Every live mutation runs in `try/finally` and removes what it created.
- After a deliberately broken feature, remove it before continuing: a failed update poisons every
  later update.
- Restore the In-Work Object and the selection when a test changes them.
- Run only against a disposable Part named by `AUTO3DX_LIVE_PART`. The integration session
  refuses to start otherwise, and probes select the Part by that name. Remove only what the
  test created: never a whole shared container such as the `auto_3dx_Planes` set when it
  existed before the test (conventions 1.8 records the incident that made this a rule).
- Verify cleanup by counting what remains, not by trusting that removal did not throw.

---

## Migration status

| Item | Section | State |
|---|---|---|
| Shared model generation on `Part`: `PartDesign`, `Topology`, `update()` | 5 | Done |
| Shared model generation: sketches, planes, parameters, formulas, constraints | 5 | Done |
| One generation per CATIA Part across wrappers | 5 | Done |
| `part.topology` replacing `part_design.snapshot_edges` / `snapshot_faces` | 7 | Done |
| Topology snapshots restore the user's selection | 7 | Done |
| Error categories and `AutomationError` | 8 | Done |
| One COM error translation module: `_com.py` exists | 8 | Done |
| Every module translating COM failures through `_com.py` | 8 | Done |
| `Part.update()` maps only COM failures | 8 | Done |
| `measurement.measure()` defaults to the main body | 9 | Done |
| Small package root | 13 | Done |
| Test that only `Part.update()` rebuilds, and nothing saves | 6 | Done |
| `part.inspect`: name, rebuild status, features, sketches, user parameters | 11 | Done |
| `part.inspect`: bodies, geometrical sets, topology counts | 11 | Done |
| `part.inspect`: In-Work Object (`InWorkObjectInfo`) | 11 | Done |
| `part.planes`: `list`/`names`/`get`, and cleanup without in-memory state | 4 | Done |
| `sketch.support()` resolving user-defined planes, not only origin planes | 4 | Done |
| `part_design`: Multi-sections Solid (`MultiSectionSolid`, sections only) | 4 | Done; builds live for corner-free sections, no closing-point support |
| File export | 12 | Probed: unavailable for PLM-backed documents |
