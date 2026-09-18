"""Acceptance: an enclosure split into bodies, one of which can be hidden.

A small stand-in for the enclosure workflow, not the real model. Five bodies, each with
its own pad, in the disposable test Part:

    AUTO3DX_ENC_OuterHousing       a shell-like outer block
    AUTO3DX_ENC_LEDTray            inside it
    AUTO3DX_ENC_ElectronicsFloor
    AUTO3DX_ENC_SpeakerMounts
    AUTO3DX_ENC_MountingBosses

    $env:AUTO3DX_LIVE_PART = "AUTO3DX_MULTIBODY_TEST"
    python scripts/acceptance/multi_body_enclosure.py create
    python scripts/acceptance/multi_body_enclosure.py verify
    python scripts/acceptance/multi_body_enclosure.py remove

`create` builds the bodies through `part.work_in` and hides the outer housing. `verify`,
in a fresh process, finds every body by name, checks each holds only its own pad, that the
outer housing is hidden while the internal bodies are shown, and shows the housing again.
`remove` deletes only these five bodies. Public auto_3dx API only; nothing is saved.
"""

import math
import os
import sys

from auto_3dx import Catia
from auto_3dx.errors import BodyNotFoundError

PART_ENV_VAR = "AUTO3DX_LIVE_PART"
PREFIX = "AUTO3DX_ENC_"
# name -> (x, y, width, depth, z height) of the pad in that body, in millimetres
BODIES = {
    f"{PREFIX}OuterHousing": (0.0, 0.0, 120.0, 80.0, 60.0),
    f"{PREFIX}LEDTray": (200.0, 0.0, 60.0, 40.0, 5.0),
    f"{PREFIX}ElectronicsFloor": (300.0, 0.0, 80.0, 60.0, 3.0),
    f"{PREFIX}SpeakerMounts": (400.0, 0.0, 30.0, 30.0, 10.0),
    f"{PREFIX}MountingBosses": (450.0, 0.0, 10.0, 10.0, 15.0),
}
OUTER = f"{PREFIX}OuterHousing"


def target_part():
    target = os.environ.get(PART_ENV_VAR, "").strip()
    if not target:
        sys.exit(f"Refusing to run: set {PART_ENV_VAR} to the disposable test Part.")
    catia = Catia.attach()
    part = catia.active_part()
    caption = catia.active_window_title
    if target not in (part.name, caption):
        sys.exit(
            f"Refusing to run: the active Part is {part.name!r} ({caption!r}), not {target!r}."
        )
    return part


def create() -> None:
    part = target_part()
    before = part.inspect.in_work_object()
    try:
        for name, (x, y, width, depth, height) in BODIES.items():
            body = part.bodies.create(name)
            with part.work_in(body):
                sketch = part.sketches.create(f"{name}_SKETCH", support="XY")
                with sketch.edit() as editor:
                    editor.rectangle(width, depth, origin_x=x, origin_y=y)
                part.part_design.create_pad(f"{name}_PAD", sketch, height)
            part.update()
        assert part.inspect.in_work_object() == before
        part.bodies.get(OUTER).hide()
        print(part.inspect.summary().render())
        print("create: OK, outer housing hidden, exiting without cleanup")
    except BaseException:
        print("create FAILED; removing only what this run made")
        remove()
        raise


def verify() -> None:
    part = target_part()
    names = part.bodies.names()
    print("bodies:", names)
    for name, (x, y, width, depth, height) in BODIES.items():
        body = part.bodies.get(name)
        assert [(f.name, f.kind) for f in body.features] == [(f"{name}_PAD", "Pad")], (
            name
        )
        volume = part.measurement.measure(body).volume_mm3 if name != OUTER else None
        visible = body.is_visible
        print(
            f"  {name}: features={[f.name for f in body.features]} visible={visible} "
            f"volume={volume}"
        )
        if name == OUTER:
            assert visible is False, "the outer housing should still be hidden"
        else:
            assert visible is True, f"{name} should be visible"
            assert math.isclose(volume, width * depth * height, rel_tol=1e-6), volume
    assert part.is_up_to_date()
    part.bodies.get(OUTER).show()
    assert part.bodies.get(OUTER).is_visible is True
    print("verify: OK, outer housing shown again")


def remove() -> None:
    part = target_part()
    for name in reversed(list(BODIES)):
        try:
            part.bodies.remove(name, delete_contents=True)
        except BodyNotFoundError:
            pass
    part.update()
    left = [name for name in part.bodies.names() if name.startswith(PREFIX)]
    assert not left, left
    print("remove: OK, bodies left:", part.bodies.names())


if __name__ == "__main__":
    phases = {"create": create, "verify": verify, "remove": remove}
    if len(sys.argv) != 2 or sys.argv[1] not in phases:
        sys.exit(f"usage: {sys.argv[0]} {{{'|'.join(phases)}}}")
    phases[sys.argv[1]]()
