"""Build a parameterised pad in the Part that is currently being edited.

This is the workflow `auto-3dx` supports on this installation: you create the
Part in the 3DEXPERIENCE UI, then this library fills it in. Creating the PLM
object itself is not available through Automation here -- see
`docs/plm_object_creation.md`.

Run it with a Part editor active:

    python examples/build_part.py

It never saves. Review the result in CATIA and save it yourself if you want to
keep it.
"""

from auto_3dx import Catia
from auto_3dx.errors import Auto3dxError

WIDTH_PARAMETER = "AUTO3DX_WIDTH"
HEIGHT_PARAMETER = "AUTO3DX_HEIGHT"
THICKNESS_PARAMETER = "AUTO3DX_THICKNESS"
SKETCH_NAME = "AUTO3DX_BASE_SKETCH"
PAD_NAME = "AUTO3DX_BASE_PAD"

WIDTH = 60.0
HEIGHT = 40.0
THICKNESS = 12.0


def main() -> None:
    """Creates three parameters, a rectangular sketch, and a pad."""
    catia = Catia.attach()
    part = catia.active_part()
    print(f"Editing: {part.name}")

    parameters = part.parameters
    for name, value in (
        (WIDTH_PARAMETER, WIDTH),
        (HEIGHT_PARAMETER, HEIGHT),
        (THICKNESS_PARAMETER, THICKNESS),
    ):
        parameter = parameters.ensure_length(name, value)
        print(f"  parameter {parameter.short_name} = {parameter.value} {parameter.unit}")

    sketch = part.sketches.ensure(SKETCH_NAME, support="XY")
    print(f"  sketch {sketch.name!r} on {sketch.support()}")

    # A closed profile is required for the pad. edit() guarantees CloseEdition()
    # even if drawing raises.
    with sketch.edit() as editor:
        editor.rectangle(WIDTH, HEIGHT)
    part.update()

    pad = part.part_design.ensure_pad(PAD_NAME, sketch, THICKNESS)
    part.update()
    print(f"  pad {pad.name!r} height {pad.height} mm")

    print()
    print("Done. Nothing was saved -- save from CATIA if you want to keep this.")


if __name__ == "__main__":
    try:
        main()
    except Auto3dxError as error:
        raise SystemExit(f"{error!r}")
