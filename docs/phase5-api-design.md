# Phase 5 API design: a thin intent layer on a verified low-level SDK

Status: **implemented and live-validated** (2026-09-27). Sections 1-3 are the audit of the
pre-Phase-5 API and the evidence gathered live. Sections 4-8 were written as the design before
any code; they now describe what is implemented, and section 9 records the live results. The
architectural rules that outlive this phase are in `docs/api-design.md` section 20.

Baseline: auto-3dx `6a74d07` (develop, version 0.1.0, 1156 unit tests), benchmark
`auto-3dx-benchmark` v1.0.0 (`4cb69a7`, read only). Live target: the disposable Part
`3D Shape00422558` on B428_Cloud.

Contract documents this builds on: `docs/api-design.md` (the architectural contract, which
wins on conflict) and `docs/conventions.md` section 1 (measured COM facts).

---

## 1. Three layers

```text
LEVEL 3  intent API        auto_3dx.highlevel      body.features.pad(...), part.geometry.top_face(),
                                                   sketch.rectangle(...), part.inspect.facts(...)
            |  calls only the public Level 2 API; imports no pywintypes/win32com; never
            |  touches `com_object`
LEVEL 2  composable API    part.sketches, part.part_design, part.topology, snapshot.query(),
                           part.measurement, part.inspect, part.update(), typed errors
            |
LEVEL 1  internal          geometry/*.py private helpers, _com.py, _generation.py, transport
```

A Level 3 call always resolves to Level 2 calls a user could have written by hand. When the
intent layer cannot express something, the Level 2 call it would have made is the fallback.

## 2. Audit of the current public API (read from the code, not the older docs)

### 2.1 Level 2 as it exists

| Area | Public API | Notes |
|---|---|---|
| Session | `Catia.attach()`, `active_part()`, `part_named()`, `parts()`, `editors()`, `active_window_title` | |
| Part | `name`, `update(target=None)`, `is_up_to_date(target=None)`, `work_in(body)`, `work_at(feature)` | only `update()`/`Body.update()` rebuild |
| Bodies | `part.bodies.list/names/get/create/remove`, property `part.bodies.main`; `Body.name/is_main/features/sketch_names/is_up_to_date/update/hide/show/is_visible` | `Body.features` is a **tuple of `FeatureInfo`** |
| Sketches | `part.sketches.create(name, support="XY"|plane)`, `ensure/get/list/names/remove`; `Sketch.edit()` -> `SketchEditor` (`line/circle/arc/point/spline/rectangle/set_construction` + 10 constraint methods); `Sketch.elements()/get_element()/element_names()/axis_data()/support()/constraints` | the prompt's `create_sketch`/`sketch.add_line` are `sketches.create`/`editor.line` here |
| Elements | `SketchElement.name/kind/radius/sketch/com_object` | no coordinates (probe 43 used the wrong call form, see 3.1) |
| Constraints | `Constraint.name/type_code/status/value/set_value/dimension_parameter`; `ConstraintCollection.list/get/remove/count/broken_count` | |
| Planes | `part.planes.create_offset/create_angle/list/get/remove/dependents`, `OffsetPlane.offset/set_offset`, `AnglePlane.angle/set_angle` | |
| Features | `part.part_design.create_/get_/remove_/<kind>s` for pad, pocket, shaft, groove, mirror, rib, slot, multi-section solid, edge fillet, chamfer, shell, thickness, hole, rectangular and circular pattern, four booleans; `ensure_*` where identity is provable | `create_hole(name, face, depth)` has no position; circular pattern is Z-only |
| Feature values | `Pad.height/set_height`, `SketchFeature.depth/set_depth/direction/set_direction/reverse_direction`, `ConstRadEdgeFillet.radius/set_radius`, `Chamfer.length1/angle`, `Hole.diameter/depth`, `Shell.*_thickness`, `Thickness.offset`, `CircularPattern.angular_instances/angular_spacing_deg`, `is_active/activate/deactivate` | all setters are methods; no property setters |
| Topology | `part.topology.edges(body=...)`/`faces(body=...)` snapshots; `Edge/Face.geometry` measured facts; `snapshot.query()` with type/orientation/size/position/owner steps and `one()/first()/all()` | stale handles refused before COM |
| Measurement | `part.measurement.measure(item=None)` -> `MassProperties` | refuses a target that is not up to date |
| Inspection | `part.inspect.summary()/features()/sketches()/parameters()/bodies()/geometrical_sets()/topology()/in_work_object()/update_issues()` | `summary()` includes two topology searches |
| Errors | five categories under `Auto3dxError` | |

### 2.2 Convenience that already exists

`SketchEditor.rectangle` (four lines, no constraints), `Pad.height` alias, `part.work_in(name)`
accepting a body name, `topology.edges(body="PartBody")`, `measure()` defaulting to the main
body, `Sketch.support()` round-tripping into `create(support=...)`.

### 2.3 Naming inconsistencies

- `part.bodies.main` is a property while `list()/names()` are methods. It stays a property:
  changing it would break every Phase 1-4 script. Phase 5 does **not** add `main()`.
- `Body.features` returns data (`FeatureInfo` tuple) while the intent API wants a namespace
  there. Resolved compatibly in 5.1.
- Feature setters are methods (`set_radius`) while the natural spelling is an assignment
  (`fillet.radius = 5`). Phase 5 adds property setters that call the same methods.
- `Pad.height` vs `SketchFeature.depth` for one quantity; the intent layer uses `length` for a
  pad and `depth` for a pocket and hole.
- `create_chamfer(name, edge, length1, length2_or_angle, propagation, orientation)` exposes
  plain integers with unknown meaning; the intent layer hides them behind verified defaults.

### 2.4 Awkward call sequences

```python
# a rectangle on XY padded 20 mm, today
sketch = part.sketches.create("Base", support="XY")
with sketch.edit() as editor:
    editor.rectangle(50, 30, origin_x=0, origin_y=0)
part.part_design.create_pad("Base", sketch, 20)          # which body? implicit
part.update()

# "the top face", today
faces = part.topology.faces(body="PartBody")
top = faces.query().planar().normal_parallel((0, 0, 1)).extreme((0, 0, 1)).one()
```

Nothing here is wrong; it is just several lines of CAD mechanics per intent.

### 2.5 Capabilities the benchmark could not bind (SDK_COMPATIBILITY.md, v1.0.0)

Sketch on a planar face; hole position and through-all; circular pattern about an axis other
than global Z; sketch line coordinates and circle centres; face/edge adjacency; a way to name a
rectangle's width constraint. Phase 5 addresses the first four in Level 2 and records the fifth
as unresolved (3.1).

### 2.6 Expensive patterns

Measured on B428_Cloud: a face or edge snapshot 0.2-1.0 s, one element measurement about
10 ms, `inspect.summary()` 1-3.5 s because it always runs both topology searches, one
`Part.Update()` 5-90 ms, one `measurement.measure()` 25-120 ms. An agent that only needs "is it
up to date and what is the volume" pays for two B-rep searches through `summary()`. Phase 5 adds
targeted reads (5.6).

### 2.7 Compatibility constraints

- Every Phase 1-4 signature keeps working unchanged; new parameters are keyword-only with
  defaults that reproduce today's behaviour.
- `Body.features` keeps being a tuple of `FeatureInfo` (it becomes a tuple subclass).
- The package root stays small (`api-design.md` 13); the intent layer is reached through
  attributes, and importable for type hints from `auto_3dx.highlevel`.
- `docs/api-design.md` invariants hold: explicit `update()`, generation/staleness, no Save.

---

## 3. Live evidence (probe 46 series, 2026-09-27)

The first, monolithic probe 46 left 3DEXPERIENCE busy and unresponsive during its first
stage (sketch geometry reads, several of them **inside an open edition**, plus several
constraints on one rectangle). Output was buffered, so the call was not identified; the
session had to be restarted by the user and nothing leaked into the target Part.

From then on every question was a micro-probe (`scripts/probes/46*_*.py`, shared scaffolding in
`scripts/probes/_micro.py`): exact target check, blank-baseline check, one uncertain capability,
a flushed `BEFORE`/`AFTER` marker around every Automation call, run unbuffered, cleanup, and a
re-verified blank baseline. No micro-probe hung; CATIA answered after every one.

Classification: **VERIFIED_LIVE**, **TYPELIB_ONLY** (declared, never called), **FAILED_LIVE**,
**HANGS_CATIA**, **UNKNOWN**.

### 3.1 Evidence ledger

| Probe | Automation call(s) | Result | Class |
|---|---|---|---|
| 46 (stage 1) | many sketch reads during an open edition + rectangle constraints | CATIA unresponsive; call not identified | HANGS_CATIA (unattributed) |
| 46a | `Line2D.GetEndPoints(seed4)` after `CloseEdition` | `(10, 5, 40, 25)` (1e-14 noise) | VERIFIED_LIVE |
| 46b | `Circle2D.GetCenter(seed2)`, `Radius` after close | `(20, 15)`, `4.0` (probe 43 omitted the seed) | VERIFIED_LIVE |
| 46c | arc `GetCenter`, `Radius`, `GetEndPoints` | end points `(-14,-10)`,`(-20,-4)`: arc parameters are **radians** | VERIFIED_LIVE |
| 46ab | closed circle `GetEndPoints` | start == end: a closed circle is told from an arc | VERIFIED_LIVE |
| 46d | `Constraint.Name/Type/Mode/Status/Dimension.Value` after close | `Length.1`, 5, **0 = driving**, 0 = OK, 30.0 | VERIFIED_LIVE |
| 46e | `GetConstraintElement(1).DisplayName` | the constrained element's name, `Line.1` | VERIFIED_LIVE |
| 46ac | `GetConstraintElement(1)` and `(2)` on a perpendicularity | `Line.1`, `Line.2` | VERIFIED_LIVE |
| 46f | `Construction` read after close | `False` / `True` as written | VERIFIED_LIVE |
| 46g | `Point2D.GetCoordinates(seed2)` after close | `(-5, 7.5)` | VERIFIED_LIVE |
| 46h | element fetched by `GeometricElements.Item(name)` in a fresh attach, then reads | same values; collection holds `AbsoluteAxis` (`Axis2D`) first | VERIFIED_LIVE |
| — | any geometry read **while the edition is open** | not repeated on purpose | UNKNOWN (suspected in the hang) |
| 46i | `Sketches.Add(<top planar face Reference>)`, `GetAbsoluteAxisData`, `Part.Update` | sketch created; frame `(0,0,20 | X | Y)`; update ok | VERIFIED_LIVE |
| 46j | same on the bottom and +X side faces | frames `(0,0,0 | X | -Y)`, `(30,-20,0 | Y | Z)`: normal **outward** both times; origin is not the face centre | VERIFIED_LIVE |
| 46aa | same on a pocket floor (recessed face) | normal `+Z`, outward | VERIFIED_LIVE |
| 46k | circle on a top-face sketch + `AddNewPocket(sketch, 4)` default direction | `DirectionOrientation` 1; removed exactly 113.097 mm3 at (10, 5, 18): cuts **into** the material; local (u, v) maps through the frame | VERIFIED_LIVE |
| 46l | pad height 20 -> 30, update | face sketch origin moved to z = 30, pocket followed | VERIFIED_LIVE |
| — | `Sketches.Add(<cylindrical face>)` | not attempted; the SDK refuses non-planar faces before COM | UNKNOWN |
| 46m | `AddNewHoleFromPoint(10, 5, 20, top, 8)`, `GetOrigin(seed3)` | placed at (10, 5, 20); default diameter 12, depth 8 | VERIFIED_LIVE |
| 46n | `BottomLimit.LimitMode = 2` (`catUpToLastLimit`) | removed exactly the through volume; CATIA **rewrote the depth** to 20, and switching back to blind kept 20 | VERIFIED_LIVE |
| 46o | `BottomType = 0` | flat bottom, exact cylinder volume; default was V (1), 120 degrees | VERIFIED_LIVE |
| 46q | new hole, no writes | inherited `BottomType` 0 from 46o: **hole defaults are carried over from the last hole** | VERIFIED_LIVE |
| 46r | `BottomType = 1`, `BottomAngle.Value` | V, 120, exact 46m volume (and the session default restored) | VERIFIED_LIVE |
| 46q | `BottomAngle.Value` on a flat hole | E_FAIL | FAILED_LIVE |
| 46s | `Diameter`, `BottomType`, `LimitMode` all written **before** the first update | exact through volume, origin kept | VERIFIED_LIVE |
| 46p | hole on the +X side face, `GetDirection(seed3)` | `(-1, 0, 0)`: into the material; origin kept | VERIFIED_LIVE |
| — | `Hole.Reverse()`, `SetOrigin`, `SetDirection`, threads, counterbores | not attempted | TYPELIB_ONLY |
| 46t | `AddNewCircPattern(... PlaneYZ/ZX/XY as centre and axis ...)` | YZ -> X axis, ZX -> Y axis, XY -> Z axis (COG-identified) | VERIFIED_LIVE |
| 46u | cylindrical face Reference as centre and axis | rotation about the cylinder axis (exact volume and COG) | VERIFIED_LIVE |
| 46v | linear edge Reference as centre and axis | rotation about the edge (exact volume and COG) | VERIFIED_LIVE |
| 46w | `CircularPatternParameters = 1` (complete crown) | write accepted and read back, **geometry unchanged**; reading the default fails | FAILED_LIVE |
| 46x | `iIsReversedRotationAxis` False / True about Z | False: clockwise seen from +Z; True: counter-clockwise | VERIFIED_LIVE (Z only) |
| 46y | face selected + `Search("Topology.Edge,sel")` | 0 hits | FAILED_LIVE |
| 46z, 46z2 | `MeasurableBetween.DistanceMinToPoint` (with and without output seeds) | "Invalid number of parameters" | FAILED_LIVE |
| 46ad | four H/V constraints on one rectangle | created; normalised to `Parallelism` (type 8); update ok | VERIFIED_LIVE |
| 46ae | the same plus two length constraints with values | 6 constraints, all OK; update ok | VERIFIED_LIVE |
| 46u (cleanup) | delete a pad whose face had served as a pattern axis | its sketch **was not** cascade-deleted | VERIFIED_LIVE (recorded) |

### 3.2 What the evidence decides

- Sketch geometry can be read, but only with the edition closed. The SDK refuses a read while
  an edition of that sketch is open instead of risking the unidentified hang.
- Sketch-on-face is real: planar faces only, and the frame must be exposed because its origin
  is not the face centre. A face sketch's normal was outward on all four faces tried, which is
  what makes `into_material` answerable for a sketch the SDK created on a face.
- Hole placement, diameter, flat/V bottom and through-all are all verified, but defaults are
  session state, so the SDK writes every attribute it cares about explicitly.
- Circular patterns can turn about X, Y, Z, a cylindrical face's axis or a linear edge. Crown
  mode does not work; total angles are converted into a spacing instead.
- No verified adjacency route exists. Phase 5 ships an honest plane-coincidence filter and
  leaves adjacency unresolved.

---

## 4. Level 2 additions

Every item cites the evidence in 3.1. Existing signatures are unchanged.

### 4.1 Sketch geometry (46a-46h, 46ab, 46ac)

```python
line.geometry()        # LineGeometry(start=(10, 5), end=(40, 25), length_mm=36.06)
circle.geometry()      # CircleGeometry(center=(20, 15), radius_mm=4.0, is_closed=True,
                       #                start=(24, 15), end=(24, 15))
point.geometry()       # PointGeometry(position=(-5.0, 7.5))
line.is_construction   # bool, read from `Construction`
constraint.mode        # "driving" | "driven"
constraint.element_name(1)   # "Line.1"; position 2 verified on a two-element constraint
sketch.frame()         # SketchFrame(origin, x_axis, y_axis, normal) from axis data,
                       # .to_global((u, v)) -> (x, y, z), .to_local((x, y, z)) -> (u, v)
sketch.geometry()      # SketchGeometry(name, frame, lines, circles, points, constraints,
                       #                other_elements) -- plain values, no COM objects
```

- Coordinates are sketch-local millimetres; `frame().to_global` maps them to the Part.
- Elements of kinds without verified reads (`Axis2D`, splines, control points, ellipses) are
  listed by name and kind in `other_elements`; `geometry()` on one raises
  `UnsupportedOperationError`.
- A read while that sketch's `edit()` block is open raises `ValidationError` before COM.

### 4.2 Sketch on a planar face (46i, 46j, 46k, 46l, 46aa)

```python
top = part.topology.faces(body="PartBody").query().planar() \
          .normal_parallel((0, 0, 1)).extreme((0, 0, 1)).one()
sketch = part.sketches.create("PocketProfile", support=top)
sketch.frame().origin        # a corner of the face, not its centre
sketch.created_on_face       # True: this wrapper put it on a face
```

Refused before COM: a `Face` from a stale snapshot (`StaleSnapshotError`), from another Part
(`ValidationError`), from another body than the one the sketch goes into
(`CrossBodyReferenceError`), or whose measured surface is not planar
(`UnsupportedSupportError`). No `ensure` for face sketches (no readable face identity).
`Sketch.support()` keeps returning `None` for a face sketch.

### 4.3 Hole placement and limits (46m, 46n, 46o, 46p, 46q, 46r, 46s)

```python
hole = part.part_design.create_hole(
    "H1", top, 10.0,                     # unchanged positional form
    origin=(20.0, 15.0, 20.0),           # AddNewHoleFromPoint; must lie in the face's plane
    diameter=6.0, bottom="flat",         # written before the first update
)
part.part_design.create_hole("H2", top, origin=(0, 0, 20), diameter=6, limit="through_all")
hole.origin, hole.direction              # GetOrigin / GetDirection
hole.limit                               # "blind" | "through_all" | "other"
hole.set_limit("blind", depth=8.0)       # blind needs a depth: CATIA overwrote it (46n)
hole.bottom, hole.set_bottom("v")        # "flat" | "v"
```

- Without `origin` the verified `AddNewHole(face, depth)` path runs as before, except that the
  limit is now always written (blind when a depth is given). CATIA carries the previous hole's
  limit over: after the Phase 5 live stages made through-all holes, the unchanged Phase 2 test
  `create_hole(face, 5)` came out through-all with depth 30. Writing the limit keeps the call
  meaning what it says; `LimitMode` writes are verified (46n, 46s).
- `diameter=None`/`bottom=None` leave CATIA's carried-over values (46q) and the docstring says so;
  the intent API always passes them.
- The drilling direction is CATIA's default, verified into the material on two faces; no
  reversal is offered (`Reverse()` is TYPELIB_ONLY).

### 4.4 Circular pattern axes (46t, 46u, 46v, 46x)

```python
part.part_design.create_circular_pattern("P", seed, 6, 60.0, axis="X")      # or "Y", "Z"
part.part_design.create_circular_pattern("P", seed, 6, 60.0, axis=bore_face) # cylindrical Face
part.part_design.create_circular_pattern("P", seed, 6, 60.0, axis=edge)      # linear Edge
part.part_design.create_circular_pattern("P", seed, 2, 90.0, axis="Z", reverse=True)
```

Face and edge axes get the same staleness and ownership checks as fillets, and are measured
first: a non-cylindrical face or a non-linear edge is refused. `reverse` flips the sense; only
for Z is the sense documented (46x). The existing Z-only calls are unchanged.

### 4.5 Plane-coincidence filter (replaces the adjacency request, 46y/46z)

`EdgeQuery.on_plane_of(face, tolerance_mm=1e-3)` keeps edges whose measured start, middle and
end points lie in the plane of a planar face. It is a geometric fact, not topology: it does not
claim the edge bounds that face. It covers the common "rim of the hole on the top face" query.

### 4.6 Property setters

`pad.length`/`pad.height`, `pocket.depth`, `fillet.radius`, `chamfer.length1`/`angle`,
`hole.diameter`/`depth`, `plane.offset`, `plane.angle`, `pattern.instances`,
`pattern.spacing_deg` become assignable. Each setter calls the existing `set_*` method, so
validation, units (millimetres/degrees), the generation advance and "no rebuild" are identical.

### 4.7 Errors

- `UnsupportedOperationError(ValidationError)`: the SDK cannot do this safely (unverified
  element kind, a direction it cannot determine, more than one fillet edge, ...).
- `UnknownFactError(ValidationError)`: a fact name `facts()` does not know.
- `FactUnavailableError(ConflictError)`: a requested fact cannot be read in the current state.

---

## 5. Level 3: the intent API (`auto_3dx.highlevel`)

### 5.1 Navigation

```python
body = part.bodies.main                 # property, unchanged
body = part.bodies.get("ToolBody")
sketch = part.sketches.create("BaseProfile", support="XY")   # Level 2, already intuitive
sketch = body.sketches.create("Profile", support=part.planes.get("P"))   # new: in that body
```

`Body.features` becomes `BodyFeatures`, a `tuple` subclass: it is still the `FeatureInfo` tuple
(same equality, length, iteration, indexing), and it also carries the intent methods below. The
tuple is the listing when it was read; the methods always act on the live model.

### 5.2 Sketch primitives

```python
sketch.rectangle(width=50, height=30, origin=(0, 0), constraints="none")
sketch.centered_rectangle(width=50, height=30, center=(0, 0), constraints="orientation")
sketch.circle(center=(20, 15), radius=3)
```

Each call is one `edit()` session using `SketchEditor.line/circle` and the constraint methods.

| `constraints=` | What is created | Evidence |
|---|---|---|
| `"none"` (default) | four lines, no constraints | today's `editor.rectangle` |
| `"orientation"` | + horizontal x2, vertical x2 | 46ad |
| `"dimensioned"` | + lengths of the bottom and left sides | 46ae |

There is no `"fully"`: corner coincidence needs point constraints on line end points, which
have no live evidence, so no option claims full constraint.

### 5.3 Features

```python
base = body.features.pad("Base", profile=sketch, length=20, direction="+Z")
pocket = body.features.pocket("Pocket", profile=cut, depth=5, direction="into_material")
hole = body.features.hole("MountingHole", support=top, center=(20, 15), diameter=6,
                          limit="through_all", direction="into_material")
fillet = body.features.fillet("Fillet", edges=[edge], radius=3)
chamfer = body.features.chamfer("Chamfer", edge=edge, length=1.5)
pattern = body.features.circular_pattern("Bolts", feature=hole, instances=6,
                                         total_angle_deg=360, axis="Z")
part.update()
```

Every method runs `with part.work_in(body):` around one Level 2 call
(`create_pad/create_pocket/create_hole/create_edge_fillet/create_chamfer/
create_circular_pattern`). None of them rebuilds.

- `hole(center=(a, b))` on a face whose normal is parallel to a world axis means the two other
  world coordinates in X, Y, Z order (normal Z -> (x, y); X -> (y, z); Y -> (x, z)); the third
  coordinate comes from the face's plane. A 3-tuple is used as is. Anything else is refused.
- `fillet(edges=[...])` accepts exactly one edge: several edges in one fillet is TYPELIB_ONLY.
- `chamfer` uses the verified length/angle mode with angle 45 by default.
- `circular_pattern` takes exactly one of `spacing_deg` / `total_angle_deg`; 360 means a full
  circle (`360 / n`), anything else spreads the instances over the angle (`total / (n - 1)`).

### 5.4 Direction vocabulary

| Word | Pad / Pocket | Hole |
|---|---|---|
| omitted | CATIA default (pad along, pocket against the sketch normal) | CATIA default |
| `"along_normal"` / `"against_normal"` | the existing Level 2 values | refused |
| `"+X"` ... `"-Z"` | along or against, when the sketch normal is parallel to that axis; otherwise refused | refused |
| `"into_material"` / `"out_of_material"` | only for a sketch the SDK created on a face (normal outward, 46j/46aa); otherwise `UnsupportedOperationError` | `"into_material"` only (46m/46p) |

`"forward"`/`"reverse"` are not added: they would only rename along/against.

### 5.5 Semantic finders (`part.geometry`)

```python
part.geometry.top_face()                         # planar, normal // Z, extreme +Z
part.geometry.bottom_face()
part.geometry.find_planar_face(normal_parallel="X", extreme=("X", "max"))
part.geometry.find_cylindrical_face(radius=3, nearest=(20, 15, 10))
part.geometry.find_edge(kind="circle", radius=3, on_plane_of=top)
```

Each takes a fresh snapshot (scoped like `part.topology`) and composes `snapshot.query()`; the
answer is `one()`, so zero or several matches raise the existing typed errors. No index, no
descriptor, no normal sign.

### 5.6 Targeted inspection

```python
facts = part.inspect.facts("volume", "up_to_date", "feature_count")
facts["volume"]          # mm3
facts.values             # {"volume": ..., "up_to_date": True, "feature_count": 2}
facts.unavailable        # {"surface_area": "the main body has no solid yet"}, when so
```

| Fact | Read | Unit |
|---|---|---|
| `name` | `Part.Name` | |
| `up_to_date` | `part.is_up_to_date()` | |
| `volume`, `surface_area`, `mass`, `center_of_gravity` | one `part.measurement.measure()` for all of them | mm3, mm2, kg, mm |
| `feature_count`, `sketch_count` | main body shapes / sketches | |
| `body_count` | `part.bodies.names()` | |

No fact runs a topology search. A measurement refused because the body is not up to date, or
failing because the main body is empty, is reported in `unavailable`; other errors propagate.

---

## 6. Performance and update rules

- No Level 3 call rebuilds or runs `inspect.summary()`. Only finders search topology, and only
  once per call.
- Face-supported sketch creation measures the one face it was given (about 10 ms) to prove it
  is planar; hole origin validation reuses that measurement.
- `part.update()` stays explicit everywhere.

## 7. Testing plan

- Non-live: call mapping (fakes at the Level 2 boundary), an AST test that
  `auto_3dx/highlevel` imports no `pywintypes`/`win32com` and never reads `com_object`,
  direction and centre normalisation, finder composition, `facts()` never calling
  `Selection.Search`, typed errors, backward compatibility of every changed signature.
- Live (`tests/integration/test_phase5_live.py`, target `AUTO3DX_LIVE_PART`), staged, each
  stage cleaning up, followed by an A->B acceptance script.

## 8. Not in Phase 5

Face/edge adjacency; complete-crown and unequal patterns; hole reversal, threads,
counterbores; sketches on non-planar faces; `"fully"` constrained rectangles; reading geometry
inside an open edition; plane offset from a face; CADPlan/JSON plans, LLM integrations, MCP,
agent tool schemas and the skill (deferred by scope).

---

## 9. Live results (2026-09-27, `3D Shape00422558`)

| Run | Result |
|---|---|
| Micro-probes 46a-46z2, 46aa-46ae, 46af | 29 questions + 1 maintenance script; none hung; baseline re-verified after each |
| `test_phase5_live.py`, stage by stage | 11/11 passed, CATIA responsive and the Part blank after each stage |
| Full live suite (Phases 1-5), before the hole fix | 72 passed, 1 failed (legacy hole inherited through-all), 6 skipped |
| Full live suite, after the hole fix | **73 passed, 6 skipped** (the same six environment skips as before Phase 5) |
| `examples/build_part.py` (Phase 1 example) | unchanged behaviour; cleaned up |
| `examples/intent_api.py` | volume 23031.68 mm3 = the hand calculation; cleaned up |
| `inspect.facts("volume", "up_to_date", ...)` | 0.038 s, against 1-3.5 s for `inspect.summary()` |

Two facts came out of the live runs rather than the probes: a circular pattern whose seed is a
Hole works (stage 10: exactly six, then four holes' worth of material), and deleting a pad whose
face had served as a pattern axis leaves its sketch behind (46u cleanup). After the runs the
session's carried-over hole settings were put back to a fresh session's (Ø12, V, blind) and
confirmed on a new hole (`46af`).

---

## Migration status

| Item | Section | State |
|---|---|---|
| Probe 46 series and `_micro.py` scaffolding | 3 | Done |
| Sketch geometry reads, `frame()`, `geometry()` | 4.1 | Done |
| Sketch on a planar face | 4.2 | Done |
| Hole origin / diameter / bottom / through-all | 4.3 | Done; the limit is always written |
| Circular pattern X/Y, face and edge axes, `reverse` | 4.4 | Done |
| `EdgeQuery.on_plane_of` | 4.5 | Done |
| Property setters | 4.6 | Done |
| `auto_3dx.highlevel`: `BodyFeatures`, profiles, finders, facts | 5 | Done |
| Face/edge adjacency | 8 | Not available (two routes failed live) |
