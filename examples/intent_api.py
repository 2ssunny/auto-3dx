"""Build a small mounting plate with the Phase 5 intent API.

A 60 x 40 x 10 plate, a pocket cut into its top face, a through hole on the top face
patterned six times around the plate's centre, and a rounded vertical edge -- using only
`part.sketches`, `sketch.rectangle`/`circle`, `body.features.*`, `part.geometry.*` and
`part.inspect.facts`. Every call is a thin wrapper over the Level 2 API shown in the comment
beside it, which is the fallback when the intent API cannot express something.

Run it with a disposable Part editor active:

    python examples/intent_api.py

It never saves and never rebuilds except where `part.update()` is written. Review the result
in CATIA and save it yourself if you want to keep it; remove it otherwise.
"""

from auto_3dx import Catia
from auto_3dx.errors import Auto3dxError

PREFIX = "AUTO3DX_EXAMPLE_"


def main() -> None:
    """Builds the plate and prints targeted facts about it."""
    catia = Catia.attach()
    part = catia.active_part()
    body = part.bodies.main  # a property, as it has always been
    print(f"Editing: {part.name}")

    # sketches.create + one edit() session drawing four lines.
    sketch = part.sketches.create(f"{PREFIX}PLATE_SK", support="XY")
    sketch.centered_rectangle(width=60.0, height=40.0, constraints="dimensioned")
    # part_design.create_pad inside part.work_in(body); "+Z" is read from the sketch frame.
    body.features.pad(f"{PREFIX}PLATE", profile=sketch, length=10.0, direction="+Z")
    part.update()

    # topology.faces().query().planar().normal_parallel(Z).extreme(+Z).one()
    top = part.geometry.top_face()
    pocket_sketch = part.sketches.create(f"{PREFIX}POCKET_SK", support=top)
    corner = pocket_sketch.frame().to_local((-20.0, -10.0, 10.0))
    pocket_sketch.rectangle(width=10.0, height=6.0, origin=corner)
    # A sketch created on a face points out of the material, so "into_material" is known.
    body.features.pocket(f"{PREFIX}POCKET", pocket_sketch, 3.0, direction="into_material")
    part.update()

    top = part.geometry.top_face()  # the model changed: find it again
    # part_design.create_hole(..., origin=, diameter=, limit=, bottom=) with every attribute
    # written explicitly, because CATIA carries hole settings over from the previous hole.
    hole = body.features.hole(
        f"{PREFIX}HOLE", support=top, center=(15.0, 0.0), diameter=4.0, limit="through_all"
    )
    # part_design.create_circular_pattern(..., 60.0, "Z"): a full circle of six.
    body.features.circular_pattern(
        f"{PREFIX}BOLTS", feature=hole, instances=6, total_angle_deg=360, axis="Z"
    )
    part.update()

    edge = part.geometry.find_edge(kind="line", parallel="Z", nearest=(30.0, 20.0, 5.0))
    fillet = body.features.fillet(f"{PREFIX}ROUND", edges=[edge], radius=3.0)
    part.update()
    fillet.radius = 4.0  # set_radius(4.0): no rebuild until the next update
    part.update()

    facts = part.inspect.facts("volume", "up_to_date", "feature_count")
    print(
        f"  volume {facts['volume']:.1f} mm3, up to date {facts['up_to_date']}, "
        f"{facts['feature_count']} features"
    )
    print("Done. Nothing was saved -- save from CATIA if you want to keep this.")


if __name__ == "__main__":
    try:
        main()
    except Auto3dxError as error:
        # Typed errors say what to do; the model is left as CATIA left it.
        print(f"{type(error).__name__}: {error}")
        raise
