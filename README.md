# auto-3dx

auto-3dx is a Python library for automating 3DEXPERIENCE CATIA Part Design from an external
Python process. It attaches to a running 3DEXPERIENCE session over Windows COM, edits the
Part that is open there, and reads the model back as plain Python values -- with typed
errors, explicit rebuilds, and topology selected by measured geometry rather than by index.

It is designed to be used by people writing scripts and by AI agents working alongside a
CAD user.

## Installation

auto-3dx 1.0.0 is published to PyPI with the v1.0.0 release:

```powershell
python -m pip install auto-3dx
```

Install it into a virtual environment (standard CPython or Conda). The distribution name is
`auto-3dx`; the import name is `auto_3dx`. To work on the SDK itself, see
[CONTRIBUTING.md](https://github.com/2ssunny/auto-3dx/blob/main/CONTRIBUTING.md).

## Requirements

- **Windows**, 64-bit **Python 3.11 – 3.14**.
- An installed, licensed **3DEXPERIENCE CATIA**. Using it within its license is your
  responsibility.
- A **running session with the Part open** when you call `Catia.attach()`. auto-3dx attaches
  to that session; it never launches 3DEXPERIENCE or opens documents. Installing and
  importing the package need no session.
- **`com3dx.py` from your 3DEXPERIENCE installation.** It is not distributed on PyPI and is
  found at run time (from the `CATIA.Application` COM registration, or from the
  `AUTO_3DX_COM3DX_PATH` environment variable or an explicit path).
- `pywin32`, installed automatically.

Live behaviour is verified on the `B428_Cloud` release of 3DEXPERIENCE; other releases are
not verified.

## Quick start

Open a Part in 3DEXPERIENCE, then:

```python
from auto_3dx import Catia

part = Catia.attach().part_named("MY_PART")        # or catia.active_part()
body = part.bodies.main

sketch = part.sketches.create("PLATE_PROFILE", support="XY")
sketch.centered_rectangle(width=60.0, height=40.0, constraints="fully")
body.features.pad("PLATE", sketch, 10.0, direction="+Z")
part.update()                                        # nothing rebuilds implicitly

top = part.geometry.top_face()                       # found by measured geometry
hole = body.features.hole("BOLT", support=top, center=(15.0, 0.0),
                          diameter=4.0, limit="through_all")
body.features.circular_pattern("BOLTS", feature=hole, instances=6,
                               full_circle=True, axis="Z")
part.update()

print(part.inspect.facts("volume", "up_to_date"))   # targeted, read-only
```

Nothing is saved: review the result in CATIA and save it there if you want to keep it.

## Capabilities

- **Session and Parts:** attach to a running session, list editors, choose a Part by name.
- **Parameters and formulas:** typed parameters with unit checks, formulas with dependency
  guards.
- **Sketches:** sketches on origin planes, reference planes or planar faces; lines, circles,
  arcs, splines, polygons; geometric and dimensional constraints; a fully constrained
  rectangle helper; geometry read-back.
- **Reference planes:** offset and angled planes, including a plane offset from a face on a
  chosen material side.
- **Part Design:** Pad, Pocket (with explicit direction), Hole (blind, up-to-next,
  through-all; flat or V bottom; counterbore and countersink), Fillet, Chamfer, Shell,
  Thickness, Shaft, Groove, Mirror, Rib, Slot, multi-sections solid, rectangular and
  circular patterns (including full-circle), multi-body Booleans, and feature suppression.
- **Editing:** change feature dimensions, plane offsets and pattern counts in place; insert
  features at a chosen history position.
- **Topology:** face and edge snapshots with measured facts, semantic queries with strict
  cardinality, measured face/edge adjacency, and finders such as `top_face()`.
- **User selection:** read the edge, face, feature or sketch the user selected in CATIA, and
  highlight elements for the user.
- **Inspection and measurement:** targeted facts, one-feature and one-sketch reads, a full
  model summary, update diagnostics, and volume/area/mass/centre of gravity.

## Designed for agents

- **Explicit effects.** Edits never rebuild implicitly; `part.update()` is the one rebuild.
  Reads never change the model or the user's selection.
- **No guessing.** Topology is chosen by what it is (`planar()`, `radius_near()`,
  `adjacent_to(face)`, ...) and `one()` refuses both "nothing" and "several", listing the
  measured candidates. Directions that cannot be known raise instead of guessing.
- **Stale detection.** Face and edge handles go stale when the model changes and raise
  `StaleSnapshotError` before CATIA is touched.
- **Typed errors** in five categories that say what to do next; a `ValidationError` means
  nothing reached CATIA.
- **Verified placement.** A positioned hole's origin is read back; CATIA's silent snap to a
  circle centre is corrected or reported as `HolePlacementMismatchError`.
- **Plain values.** Inspection returns frozen dataclasses, and `describe()` gives one-line
  facts about a face, an edge or a selected item.

## Safety and limitations

- auto-3dx never launches 3DEXPERIENCE, never creates PLM objects (create and open the Part
  in the UI first), and never calls `Save`, `PLMPropagate` or any export. Edits stay unsaved
  in your session until you save in the UI.
- Use the public `auto_3dx` API. `com_object` on each wrapper is an expert escape hatch that
  bypasses validation and staleness checks; it is not part of the normal workflow.
- 1.0.0 does not support Product/Assembly editing, persistent topology identity across
  rebuilds, multi-edge fillets, hole threads or reversal, or measured facts for cones,
  spheres and splines. See the
  [full list](https://github.com/2ssunny/auto-3dx/blob/main/docs/v1.0.0.md#17-limitations).

## Documentation

- [User guide for v1.0.0](https://github.com/2ssunny/auto-3dx/blob/main/docs/v1.0.0.md) --
  the complete public API by capability, with the rules behind it.
- [Examples](https://github.com/2ssunny/auto-3dx/tree/main/examples) -- runnable scripts.
- [API design contract](https://github.com/2ssunny/auto-3dx/blob/main/docs/api-design.md) --
  the architecture rules for contributors.

## Contributing

See [CONTRIBUTING.md](https://github.com/2ssunny/auto-3dx/blob/main/CONTRIBUTING.md) for the
branch workflow, tests (unit tests in CI, live CATIA tests run locally), and the rules for
public API changes.

## License

auto-3dx is licensed under the
[Apache License 2.0](https://github.com/2ssunny/auto-3dx/blob/main/LICENSE).
3DEXPERIENCE, CATIA and `com3dx` are products of Dassault Systèmes and are not covered by
this license.
