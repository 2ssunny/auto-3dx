"""Maintenance 46af: put the session's carried-over hole settings back to CATIA's defaults.

CATIA gives a new hole the settings of the previous one (probe 46q). Probes and live tests
that make flat or through-all holes therefore change what the next hole -- including one made
in the CATIA UI -- starts with. This script makes one hole with the settings a fresh session
had (probe 46m: diameter 12, V bottom, blind), then makes a second hole without writing
anything and reads what it inherited, to prove the restore. Both are deleted, with the block.

    $env:AUTO3DX_LIVE_PART = "3D Shape00422558"
    python -u scripts/probes/46af_restore_hole_session_defaults.py
"""

from _micro import (
    block_fixture,
    delete,
    marker,
    planar_face,
    require_blank_target,
    step,
    sweep,
    update_if_needed,
    verify_blank,
)

PREFIX = "AUTO3DX_P46AF"
FRESH_DIAMETER, V_BOTTOM, BLIND = 12.0, 1, 0


def main() -> None:
    catia, part = require_blank_target()
    raw = part.com_object
    pad = setter = reader = None
    try:
        pad, _ = block_fixture(part, f"{PREFIX}_BLOCK")
        top = planar_face(part, (0, 0, 1), (0, 0, 1))
        factory = step("Part.ShapeFactory", lambda: raw.ShapeFactory)
        setter = step(
            "AddNewHoleFromPoint (the one that sets the defaults)",
            lambda: factory.AddNewHoleFromPoint(-10.0, 0.0, 20.0, top.com_object, 8.0),
        )
        step("setter.Name = ...", lambda: setattr(setter, "Name", f"{PREFIX}_SET"))
        step("Diameter.Value = 12", lambda: setattr(setter.Diameter, "Value", FRESH_DIAMETER))
        step("BottomType = 1", lambda: setattr(setter, "BottomType", V_BOTTOM))
        step("BottomLimit.LimitMode = 0", lambda: setattr(setter.BottomLimit, "LimitMode", BLIND))
        step("Part.Update", raw.Update)
        reader = step(
            "AddNewHoleFromPoint (reads what it inherits)",
            lambda: factory.AddNewHoleFromPoint(10.0, 0.0, 20.0, top.com_object, 8.0),
        )
        step("reader.Name = ...", lambda: setattr(reader, "Name", f"{PREFIX}_READ"))
        inherited = (
            step("inherited Diameter", lambda: reader.Diameter.Value),
            step("inherited BottomType", lambda: reader.BottomType),
            step("inherited LimitMode", lambda: reader.BottomLimit.LimitMode),
        )
        marker(f"[RESULT] a new hole now starts with (diameter, bottom, limit) = {inherited}")
    finally:
        if reader is not None:
            delete(catia, reader, f"{PREFIX}_READ")
        if setter is not None:
            delete(catia, setter, f"{PREFIX}_SET")
        if pad is not None:
            delete(catia, pad, f"{PREFIX}_BLOCK")
        sweep(catia, part, PREFIX)
        update_if_needed(part)
        verify_blank(part)


if __name__ == "__main__":
    main()
