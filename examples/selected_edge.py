"""Round the straight edge the user selected in CATIA, then highlight the new round face.

A human-in-the-loop pattern: the user clicks one edge in the 3D view, the script reads it
through `part.selection` as an ordinary `Edge`, fillets it, and highlights the fillet's
cylindrical face so the user can see the result. Selecting and highlighting never change the
model; only the fillet and `part.update()` do.

Select exactly one straight edge of a solid in the active Part, then run:

    python examples/selected_edge.py

It never saves. Review the result in CATIA and save it yourself if you want to keep it.
"""

from auto_3dx import Catia
from auto_3dx.errors import Auto3dxError, SelectionCountError, SelectionTypeError

FILLET_NAME = "AUTO3DX_EXAMPLE_SELECTED_ROUND"
RADIUS_MM = 2.0


def main() -> None:
    """Fillets the selected edge and highlights the faces it now borders."""
    part = Catia.attach().active_part()
    try:
        edge = part.selection.one_edge()
    except (SelectionCountError, SelectionTypeError) as error:
        raise SystemExit(f"Select exactly one edge in CATIA first: {error}") from error
    print(f"Selected: {edge.describe()}")

    body = part.bodies.get(edge.owner_body_name or part.bodies.main.name)
    fillet = body.features.fillet(FILLET_NAME, edges=edge, radius=RADIUS_MM)
    part.update()
    print(f"Created {fillet.name} with radius {fillet.radius} mm")

    # The model changed, so `edge` is stale now. Find the new round face by meaning and
    # show the user the faces around it.
    round_face = part.geometry.find_cylindrical_face(radius=RADIUS_MM, body=body)
    part.selection.set(round_face)
    print(f"Highlighted the new round face: {round_face.describe()}")
    print("Done. Nothing was saved -- save from CATIA if you want to keep this.")


if __name__ == "__main__":
    try:
        main()
    except Auto3dxError as error:
        raise SystemExit(f"{error!r}") from error
