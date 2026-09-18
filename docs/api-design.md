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
anything other than `Part.update()` or `Body.update()` calls `Update()`/`UpdateObject()`, or if
anything calls `Save()` or `PLMPropagate()`. `update()` advancing the generation is pinned by the
generation tests.

**`part.update()` and `body.update()` are the only methods that rebuild the model.** No
constructor, setter, `ensure` or removal rebuilds.

```python
pad = part.part_design.create_pad("Base", sketch, 20.0)
part.update()                       # Part.Update(): everything

with part.work_in(tray):
    part.part_design.create_pad("TrayFloor", tray_sketch, 3.0)
tray.update()                       # Part.UpdateObject(tray): that body alone
part.update(tray)                   # the same call, spelled from the Part
```

**A body created or edited inside `work_in` is not rebuilt by leaving the block.** Until
something rebuilds it, `body.is_up_to_date` is `False`, CATIA has no valid solid for it, and
measuring it fails inside the inertia service, which is why measurement refuses it first
(section 12). `body.update()` rebuilds one body without touching the rest of the Part and
without moving the In-Work Object (live, probe 42).

Why explicit:

- A rebuild is observable and can fail. A caller, and especially an AI agent, must be able to
  point at the line where the rebuild happened.
- A failed update leaves the feature in the tree, and **every later update fails until that
  feature is removed**. Hiding rebuilds inside constructors would scatter that failure across
  unrelated calls.
- Several mutations often form one valid state only together, such as a sketch and the pad
  built on it. Batching them before one rebuild avoids rebuilding invalid intermediate states.

After a rebuild raises `PartUpdateError`, **repair the model; deletion is the last step, not
the first.** Nothing was rolled back and nothing was deleted, and every later update fails while
the model stays invalid.

1. Identify what the failure followed.
2. If it followed an edit to something that already worked -- a dimension, a parameter, a formula
   -- put the old value back and update again. Live (probe 42): a pad taken from 30 mm to 1 mm
   broke a 5 mm fillet that depended on it; `part.update()` raised, the fillet stayed in the
   tree, and restoring 30 mm rebuilt the Part with the fillet intact and the same volume as
   before.
3. Confirm the repair with `part.is_up_to_date()`.
4. Only if there is nothing to roll back -- a newly created feature that never built, or an
   edit whose previous value is unknown -- remove the offending feature with the matching
   `remove_*` method.

The SDK does not roll back automatically. It cannot know which change the caller meant to keep,
and removing a pad cascades to its sketch, so an automatic rollback would destroy more than it
repairs. Do not retry blindly.

`part.is_up_to_date()` reports CATIA's rebuild status. It is a rebuild-status query, not an
unsaved-change detector: a standalone parameter change does not make it return `False`.

---

## 7. Topology references

Status: Implemented. `part.part_design.snapshot_edges()` and `snapshot_faces()` remain as
deprecated aliases that warn and share the same generation; they will be removed before 1.0.

```python
edges = part.topology.edges()            # every body's edges, in one flat list
edges = part.topology.edges(body=tray)   # that body's edges only
edges = part.topology.edges(body=None)   # the whole Part, even inside work_in

edge = [e for e in edges if e.owner_feature_name == "TrayFloor"][0]
fillet = part.part_design.create_edge_fillet("F1", edge, 1.0)
part.update()

faces = part.topology.faces(body=tray)   # a NEW snapshot: the model changed
part.part_design.create_shell("S1", faces[0], 2.0, 0.0)
```

**A Part-wide snapshot mixes bodies, so topology is scoped and owned.** `Topology.Edge,all`
returns the edges of every body in the Part together, and CATIA will happily build a feature in
one body from another body's edge, failing only at the next `Part.Update()`. Two things prevent
that:

- **Scoping.** `edges(body=...)`/`faces(body=...)` select that body and search
  `Topology.Edge,sel`, which live returned only that body's topology and followed the selection,
  not the In-Work Object (probe 42). Inside `part.work_in(body)` a snapshot follows the work
  body by default, like sketches and features; `body=None` still asks for the whole Part.
  Outside a work context, and with no `body` argument, the search is Part-wide exactly as before.
- **Ownership.** Every `Edge`/`Face` carries `owner_body`, `owner_body_name` and
  `owner_feature_name`, read at snapshot time by walking `Reference.Parent` up to the owning
  `Body`. `PartDesign` compares that body with the one it is building in and raises
  `CrossBodyReferenceError` before calling `ShapeFactory`, so the model is untouched. Ownership
  is re-read from the model on every snapshot, never remembered between calls or processes.
  When CATIA reports no owner, the guard allows the call: refusing on a missing answer would
  break valid work. That is the one gap in this guard.

A body's edges include the wire edges of the sketches its features consumed, which a fillet
cannot use; `owner_feature_name` is how a caller picks a solid edge.

- A snapshot covers one body or the whole Part. No verified search scopes it to one feature.
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

**Only the active Part.** `Selection.Search` through a non-active Part's editor searched the
active Part (live, 2026-09-17: five open Parts all reported the active Part's counts). Every
Selection-based operation, which is topology search, deletion through `remove_*` and body
visibility, therefore checks `Part.Application.ActiveEditor.ActiveObject == Part` before touching
CATIA and raises `InactivePartError` (a `SessionError`) otherwise. The guard stays until a
per-editor path is verified. Parameters, formulas, creation and measurement do not use the
selection and are not guarded.

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
any body reports `supported` by its kind alone, because `part.work_in(body)` lets
`part.part_design` create and find features in any body (section 16). The top-level
`features` and `sketches` fields still describe the main body only; each `BodyInfo` carries its
own, and `render()` lists every body's features.
`geometrical_sets` lists the sets directly under the Part with their elements' names and kinds.
`topology` counts come from `part.topology`, so the user's selection is restored (section 7)
and the generation does not advance. It is `None` for a Part that is not the active one, whose
search would count the active Part instead (section 7).

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

**Measurement refuses a target CATIA has not rebuilt.** A body whose features have not been
rebuilt has no valid solid: the inertia service accepts it and then fails at `GetArea` with a
bare `E_FAIL` (live, probe 42). `part.measurement.measure()` checks `Part.IsUpToDate(item)`
first and raises `TargetNotUpToDateError`, naming the body and saying to call `part.update()` or
`body.update()`. It never rebuilds anything itself: measurement stays read-only, so a measured
number never hides a model change. When the status cannot be read, the measurement goes ahead
and CATIA decides.

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
- After a deliberately broken update, repair the model before continuing: roll the edit back and
  update again, and remove the feature only when it never built (section 6). A test that leaves
  the model invalid makes every later test fail.
- Restore the In-Work Object and the selection when a test changes them.
- Run only against a disposable Part named by `AUTO3DX_LIVE_PART`. The integration session
  refuses to start otherwise, and probes select the Part by that name. Remove only what the
  test created: never a whole shared container such as the `auto_3dx_Planes` set when it
  existed before the test (conventions 1.8 records the incident that made this a rule).
- Verify cleanup by counting what remains, not by trusting that removal did not throw.
- Acceptance scripts use public API only, including the target check:
  `catia.active_window_title` gives the document title that `Part.Name` does not.
- `AUTO3DX_LIVE_PART` matches the active Part's `Part.Name` or its 3DEXPERIENCE title, which
  Automation exposes only as the active window caption (`Part.Name` of a titled Part is still
  `3D Shape…`).
- A test that makes a plane records whether `auto_3dx_Planes` existed and removes the set
  only if the test created it and it is empty again.

---

## 16. Bodies and the In-Work Body

Status: Implemented, pinned by `tests/unit/test_multi_body.py`, live by
`tests/integration/test_multi_body_live.py` and the two `scripts/acceptance/multi_body_*`
scripts (conventions 1.9).

```python
housing = part.bodies.create("OuterHousing")   # the In-Work Object is put back afterwards
part.bodies.names()                            # ["PartBody", "OuterHousing"]
part.bodies.get("OuterHousing")                # Body; BodyNotFoundError / AmbiguousNameError
part.bodies.main                               # the main body, by COM identity

with part.work_in(housing):                    # or part.work_in("OuterHousing")
    sketch = part.sketches.create("SHELL_SKETCH", support="XY")
    ...
    part.part_design.create_pad("SHELL_PAD", sketch, 40)
part.update()

housing.features                               # FeatureInfo tuple, tree order
housing.sketch_names
housing.hide(); housing.is_visible             # False
housing.show()
part.bodies.remove("OuterHousing", delete_contents=True)
```

- **Bodies are found in the model, never remembered.** A new process finds the same bodies by
  name. `Body.is_main` is COM identity with `MainBody`, not the name `PartBody`.
- **A body has its own rebuild.** Leaving a `work_in` block does not rebuild anything;
  `body.is_up_to_date` reports that, `body.update()` rebuilds that body alone (section 6), and
  measurement refuses a body that has not been rebuilt (section 12). A snapshot taken inside a
  work context covers that body (section 7).
- **`work_in` is the only way to model in another body.** Inside the block, `part.sketches`
  adds to the body's own `Sketches`, `part.part_design` creates and looks up features in that
  body, and the body is made the In-Work Object immediately before every factory call,
  because a new feature takes the In-Work Object over. A plane made inside the block hands the
  In-Work Object back to the work body, not the main body. Outside any block nothing touches
  the In-Work Object, exactly as before.
- **Restoration is guaranteed on every exit.** The previous In-Work Object is put back and
  read back whether the block ends normally or raises. A failed restore after an exception is
  added to that exception as a note rather than replacing it; after a clean block it raises
  `AutomationError`. Blocks nest and restore in order. The target stack is transient and is
  empty after the block.
- **No silent fallback.** Something that is not a `Body` or a name, or a body of another Part,
  raises `ParameterTypeError`; a body not in the Part raises `BodyNotFoundError`. Nothing ever
  falls back to the main body.
- **`create` leaves the In-Work Object where it was.** `Bodies.Add` moves it to the new body;
  `create` puts it back, including when naming fails (`PartialCreationError`).
- **Visibility goes through `Selection.VisProperties`**, so it follows the selection rules of
  section 7: the user's selection is restored, and the Part must be active. `is_visible` is
  exposed because `GetShow` read-back was verified live; an unknown state raises
  `AutomationError` rather than being guessed. Hiding or showing advances the generation.
- **Removal is guarded.** The main body is never removed (`BodyRemovalError`). A body with
  features, sketches or geometrical sets is removed only with `delete_contents=True`, and everything in it goes
  with it. If the In-Work Object was inside the removed body it becomes the main body;
  otherwise it is kept. A hidden or empty body cannot be measured (CATIA E_FAIL).

Not supported: boolean operations (Add, Remove, Intersect, Assemble), renaming or reordering
bodies, geometrical sets inside a body, a public In-Work Object setter outside `work_in`,
Products and assemblies, and any Selection-based operation on a non-active Part.

---

## 17. Editing an existing model

Status: Implemented, pinned by `tests/unit/test_editing.py`, live by
`tests/integration/test_editing_live.py` and `scripts/acceptance/phase2_editing.py`
(conventions 1.11).

Creating geometry is only half the job: an agent that reconnects to a model it did not
build has to be able to change it. Four things make that possible, and each one reads the
model rather than remembering anything in Python.

**Feature dimensions are edited in place.**

```python
fillet = part.part_design.get_edge_fillet("F1")
previous = fillet.radius
fillet.set_radius(8.0)          # no rebuild happens here
part.update()
```

Editing beats deleting and recreating, which would re-resolve the edges or faces the
feature consumes. Only dimensions verified end to end are exposed -- read, written,
rebuilt, geometry changed, and read back by a fresh wrapper: `ConstRadEdgeFillet.radius`,
`Chamfer.length1`/`angle`, `Hole.diameter`/`depth`, `Shell.internal_thickness`/
`external_thickness`, `Thickness.offset`, alongside the `Pad`/`Pocket` depth and the
`Shaft`/`Groove` angles that already existed. Conventions 1.11 holds the full matrix,
including what was deliberately left out: `Chamfer.Length2`, which CATIA refused to write
in the mode this SDK creates, and the rectangular pattern's dimensions, which are
unverified.

A setter validates like every other setter (unit, finite positive value), advances the
generation, and does not rebuild -- so several edits batch into one `part.update()`. After
a failed update, put the old value back and update again (section 6): live, a fillet taken
from 4 mm to 8 mm and back returned the exact original volume.

**Sketch elements are found again by name.**

```python
sketch = part.sketches.get("PROFILE")     # drawn by another process
sketch.element_names()                    # ['AbsoluteAxis', 'Line.1', 'Line.2', 'Circle.1']
line = sketch.get_element("Line.1")
with sketch.edit() as editor:
    editor.parallel(line, sketch.get_element("Line.2"))
```

The name CATIA gives an element is its durable identity; a collection index is not. A
rediscovered `SketchElement` carries its `name`, its `kind` and its owning sketch, so it
goes straight back into the constraint methods, which still require `edit()`. Reading does
not. `radius` is exposed for circles because it reads live; line coordinates are not
exposed at all, because this release's `Line2D` has no coordinate members (conventions
1.11). A missing name raises `SketchElementNotFoundError` listing what the sketch does
hold.

**`work_at(feature)` chooses the history position.**

```python
with part.work_at(part.part_design.get_pad("BASE")):
    part.part_design.create_pad("RIB", sketch, 6.0)   # lands right after BASE
part.update()
```

`work_in(body)` chooses which body to model in; `work_at(feature)` chooses where in that
body's history the next feature goes. Observed live: with a tree of `PAD, FILLET`, working
at `PAD` and creating a pad produced `PAD, NEW, FILLET` -- CATIA inserts immediately after
the In-Work feature, and the downstream fillet stays downstream. It is not tree
reordering: no existing feature moves.

It takes a feature wrapper from `part.part_design`, never a raw COM object and never a
body (`work_in` is for bodies), refuses a feature belonging to another Part, and restores
the exact previous In-Work Object on every exit, including after an exception. The two
contexts nest and the innermost one decides.

**A parameter a formula reads cannot be removed by accident.**

```python
part.parameters.dependents("L_box")       # [Formula(name='DriveL')]
part.parameters.remove("L_box")           # ParameterInUseError; nothing changed
part.formulas.remove("DriveL")
part.parameters.remove("L_box")           # now it is safe
```

CATIA removes such a parameter silently and rewrites the formula body to
`deleted_L_box * 2`, leaving an orphaned relation and a Part that is no longer up to date
(live). The guard asks each formula for its own inputs through `Formula.GetInParameter`,
so the answer comes from the model and works in any process; formula bodies are never
parsed. `force=True` accepts the orphan deliberately.

**Verified limitation.** Only formulas are covered. `Relations` can also hold rules,
checks, laws, programs and design tables, none of which expose a verified input list, so a
parameter used only by one of those is not reported as in use.

---

## 18. Patterns, booleans, constraint removal and suppression

Status: Implemented, pinned by `tests/unit/test_phase3.py`, live by
`tests/integration/test_phase3_live.py` and `scripts/acceptance/phase3_operations.py`
(conventions 1.12).

**Circular pattern.** One bolt hole becomes a bolt circle.

```python
seed = part.part_design.get_pocket("BOLT_HOLE")
pattern = part.part_design.create_circular_pattern("BOLT_CIRCLE", seed, 6, 60.0)
part.update()
pattern.set_angular_instances(8)      # no rebuild here either
part.update()
```

Only the Z axis is offered. Passing the XY plane as both rotation centre and rotation axis
patterned around Z and removed exactly five extra holes' worth of material; the other two
origin planes rotated about something else that the test geometry could not identify, so
`axis` accepts `"Z"` and refuses the rest (`UnsupportedSupportError`). The angular row's
`angular_instances` and `angular_spacing_deg` are readable and writable; `radial_instances`
is read-only, because this SDK always creates one radial row. The seed feature must belong
to the body being patterned in, checked with the same ownership machinery as topology
references (`CrossBodyReferenceError`).

**Multi-body booleans.** All four were verified with exact volumes:

```python
with part.work_in(housing):                       # the target is the body in work
    cut = part.part_design.create_boolean_remove("CUT_CORE", core_body)
part.update()
cut.tool_body_name                                # 'core_body', read from the model
```

`create_boolean_remove`, `create_boolean_add`, `create_boolean_intersect` and
`create_boolean_assemble` each take one tool body, by wrapper or by name. A tool body that
is the target itself, belongs to another Part, or has already been consumed is refused with
`BooleanOperationError` before CATIA is called.

**The tool body is consumed, and removal is destructive.** After the operation the tool body
reports `InBooleanOperation` and disappears from `part.bodies`; `BooleanOperation.tool_body_name`
is how its name is still readable, in any process. Deleting the boolean deletes that body
with it -- live, it did not come back and its name could no longer be found -- so
`remove_boolean(name, delete_consumed_body=True)` makes the caller say so. This is the one
place in the SDK where removing a feature destroys something else, and the asymmetry is
deliberate.

**Constraint removal.**

```python
sketch.constraints.remove("Parallelism.1")        # or a Constraint from the collection
part.update()
```

`Constraints.Remove` takes an index, and removing one renumbers the rest, so the collection
is enumerated and matched by the constraint or its name -- never by an index a caller holds.
The removal runs inside a sketch edition, which is how every other constraint operation
already works; inside an open `with sketch.edit()` block that session is reused rather than
nested, and the edition is always closed in a `finally`.

**Feature suppression.**

```python
fillet.deactivate()
part.update()                    # the fillet's material comes back; the feature stays
fillet.activate()
part.update()                    # and the filleted volume returns exactly
```

`is_active`, `activate()` and `deactivate()` are on every Part Design feature wrapper. CATIA
keeps the state in a `BoolParam` called `Activity` inside `Part.Parameters`, not on the
feature, so the wrapper walks its own `Parent` chain to the Part and reads it there. Like
every other setter, these do not rebuild.

Suppression can change the whole solid, so it advances the model generation: topology
snapshots taken before it are refused with `StaleSnapshotError` (section 7).

**Verified limitation.** Suppressing a feature that later features depend on makes the next
`Part.Update()` fail: live, suppressing a pad under a fillet did exactly that, leaving the
Part not up to date with everything still in the tree. The repair is the one from section 6
-- activate it again and update -- and the SDK does not try to predict which suppressions
are safe.

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
| `part.topology.edges(body=...)`/`faces(body=...)`, implicit inside `work_in` | 7 | Done |
| `Edge`/`Face` ownership and `CrossBodyReferenceError` | 7 | Done; unknown owner is allowed through |
| `body.update()` / `part.update(body)` for a non-main body | 6 | Done |
| Measurement refuses a target that is not up to date | 12 | Done |
| `Parameter.value` reads an `EnumParam` through `ValueAsString()` | 4 | Done; writing unverified |
| Sketch support refuses a plane that was never rebuilt | 4 | Done |
| `PartUpdateError` recovery: roll the edit back before deleting | 6 | Done (documentation and guidance) |
| Topology ownership across processes | 7 | Re-read per snapshot; nothing persists, by design |
| Feature dimension editing (fillet, chamfer, hole, shell, thickness) | 17 | Done; per-dimension evidence in conventions 1.11 |
| `sketch.get_element(name)` / `elements()`, `SketchElement.name`/`radius` | 17 | Done; line coordinates unavailable in this release |
| `part.work_at(feature)` | 17 | Done; CATIA inserts after the In-Work feature |
| `part.parameters.dependents()` and the removal guard | 17 | Done for formulas; rules/checks/laws not covered |
| Circular pattern (`create_circular_pattern`, editable angular row) | 18 | Done; Z axis only |
| Multi-body booleans: remove, add, intersect, assemble | 18 | Done; tool body is consumed |
| `remove_boolean(..., delete_consumed_body=True)` | 18 | Done; deletion destroys the consumed body |
| `sketch.constraints.remove()` | 18 | Done; runs inside a sketch edition |
| Feature suppression (`is_active`/`activate`/`deactivate`) | 18 | Done; advances the generation |
| `catia.active_window_title` | 15 | Done; the only window read, so acceptance needs no raw COM |
| `part.bodies`: `list`/`names`/`get`/`main`/`create`/guarded `remove` | 16 | Done |
| `part.work_in(body)`: sketches and Part Design in a chosen body, In-Work Object restored | 16 | Done |
| `Body.hide()`/`show()`/`is_visible` via `Selection.VisProperties` | 16 | Done |
| Selection-based operations refuse a non-active Part (`InactivePartError`) | 7 | Done; per-editor search unsolved |
| File export | 12 | Probed: unavailable for PLM-backed documents |
