"""Measures a solid's volume, area, mass, centre of gravity, and inertia box.

Verified against a live B428_Cloud session (`scripts/probes/30_measurement.py`;
each COM signature there is quoted with the type-library file it came from).
The measurement services live on the `Editor`, not on `Part` or `Selection`:

    Editor.GetService(iService) -> Service

Two service names answered, out of five tried; the other three (including the
otherwise-plausible `"CATIAInertiaService"`) raised a COM error, so these
names are known only by experiment, not from the type library:

    InertiaService.GetInertiaElement(iSelectedItem) -> Inertia
        Inertia.GetVolume() -> double
        Inertia.GetArea() -> double
        Inertia.GetMass() -> double
        Inertia.GetCOGPosition(oXCOG, oYCOG, oZCOG)


A third service, `MeasurableService`, also answered `GetService` but nothing
was ever measured through it -- it is not verified, and is deliberately not
used here.

Two behaviours are easy to get wrong and both are load-bearing:

* Every value above comes back in SI units -- metres and cubic metres --
  while the rest of this library speaks millimetres. A block measured live
  read `volume=2.88e-05 m3`, `cog=(0.030, 0.020, 0.006) m`, which is exactly
  28800 mm3 at (30, 20, 6) mm for a 60x40x12 mm block. Every value this
  module returns is pre-converted to millimetre-based units, and the
  dataclass fields are named with their unit (`volume_mm3`, `cog_mm`, ...) so
  a caller cannot silently treat a metre value as a millimetre one.
* `GetCOGPosition` looks like it takes three by-reference out-parameters, but
  pywin32 returns them as a plain tuple instead of mutating anything:
  `x, y, z = inertia.GetCOGPosition()`. Likewise `GetBoundingBox` needs two
  3-element seed sequences and RETURNS `(origin, lengths)`; calling it with no
  arguments raises a type mismatch (verified live).

`InertiaBoxService` is deliberately absent. It answered `GetService`, and
`GetInertiaBoxElement(...).GetBoundingBox((0.0,)*3, (0.0,)*3)` once returned a
real 60x40x12 mm box for the verified block -- but in a later session the same
call on the same unchanged model returned all zeros, while volume and centre of
gravity stayed exact. Every call shape was retried: tuple and list seeds, nine
element seeds, the raw body, a `Reference`, the pad, the Part itself, and after
priming with `GetInertiaElement`/`OnlyMainBody`. All zeros. A measurement that
silently reports zero instead of failing is worse than no measurement, and the
box was principal-inertia-axis aligned rather than axis aligned anyway, so it
could not answer "how big is this along X" even when it worked.
"""

import dataclasses
import warnings
from collections.abc import Callable
from typing import Any

import pywintypes

from auto_3dx._com import automation_error
from auto_3dx.errors import AutomationError, ValidationError

INERTIA_SERVICE_NAME: str = "InertiaService"
"""The `iService` string `Editor.GetService` accepts for volume/area/mass/COG.

Not documented in the type library -- found by trying candidate strings
against a live session and seeing which ones `GetService` answered.
"""

METRES_TO_MILLIMETRES: float = 1_000.0
"""Length conversion factor: the Inertia service reports lengths in metres."""

SQUARE_METRES_TO_SQUARE_MILLIMETRES: float = METRES_TO_MILLIMETRES**2
"""Area conversion factor, derived from `METRES_TO_MILLIMETRES` so the mm2/m2
relationship (a factor of a million, not a thousand) is never typed as a bare
magic number."""

CUBIC_METRES_TO_CUBIC_MILLIMETRES: float = METRES_TO_MILLIMETRES**3
"""Volume conversion factor, derived from `METRES_TO_MILLIMETRES` so the
mm3/m3 relationship (a factor of a billion) is never typed as a bare magic
number -- this is exactly the mistake that silently makes a measurement look
1000x or 1e9x too small."""

@dataclasses.dataclass(frozen=True)
class MassProperties:
    """Immutable snapshot of one solid's volume, area, mass, and centre of gravity.

    Every field is already converted out of CATIA's native SI units into this
    library's usual millimetre-based units, and named after its unit so a
    caller cannot mistake which one they are holding.

    Attributes:
        volume_mm3: Volume, in cubic millimetres.
        area_mm2: Surface area, in square millimetres.
        mass_kg: Mass, in kilograms. Mass has no length dimension, so unlike
            the other fields here it is CATIA's raw SI value, unconverted --
            named with its unit for the same reason as the others.
        cog_mm: The centre of gravity as an `(x, y, z)` tuple, in millimetres.
    """

    volume_mm3: float
    area_mm2: float
    mass_kg: float
    cog_mm: "tuple[float, float, float]"


class SolidMeasurement:
    """Measures solids through an `Editor`'s Inertia service.

    Both measurement services come from `Editor.GetService`, not from `Part`
    or `Selection`, so this class needs the raw `Editor` COM object rather
    than a `Part`. `Catia.active_editor()` returns it.

    The two services are fetched from `GetService` at most once each and
    cached for the life of this object: re-fetching a service on every
    `measure()` call would be a wasted COM round trip for
    something that does not change while the editor stays open.

    This class never calls `Part.Update()`, `Save()`, or `PLMPropagate()` --
    measuring a solid is read-only by construction, since none of its methods
    take anything but the item to measure.
    """

    def __init__(
        self,
        editor_com_object: Any,
        default_target: Callable[[], Any] | None = None,
    ) -> None:
        """Stores the raw Editor COM object without contacting it yet.

        Args:
            editor_com_object: The raw CATIA `Editor` COM object whose
                `GetService` exposes measurement -- typically
                `Catia.active_editor()`.
            default_target: Returns the raw item `measure()` uses when called
                with no argument. `Part.measurement` supplies the Part's main
                body, so ordinary use never has to reach for a raw COM object
                (`docs/api-design.md` section 9). It is called at measurement
                time rather than here, so each call reads the body afresh.
        """
        self._editor_com_object = editor_com_object
        self._default_target = default_target
        self._inertia_service: Any = None

    @property
    def com_object(self) -> Any:
        """Any: The raw underlying `Editor` COM object, the SDK's escape hatch."""
        return self._editor_com_object

    @property
    def editor_com_object(self) -> Any:
        """Any: Deprecated alias of `com_object`, kept until 1.0.

        Every other wrapper exposes its Automation object as `com_object`, and
        `docs/api-design.md` section 9 makes that the one escape hatch.
        """
        warnings.warn(
            "SolidMeasurement.editor_com_object is deprecated; use com_object.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self._editor_com_object

    def _inertia_service_com_object(self) -> Any:
        """Returns the raw `InertiaService`, fetching and caching it on first use.

        Returns:
            The raw `InertiaService` COM object.

        Raises:
            Auto3dxError: `Editor.GetService(INERTIA_SERVICE_NAME)` failed.
        """
        if self._inertia_service is None:
            try:
                service = self._editor_com_object.GetService(INERTIA_SERVICE_NAME)
            except pywintypes.com_error as error:
                raise automation_error(error, "requesting the inertia service") from error
            if service is None:
                raise AutomationError(
                    f"Editor.GetService({INERTIA_SERVICE_NAME!r}) returned no service."
                )
            self._inertia_service = service
        return self._inertia_service

    def _read_default_target(self) -> Any:
        """Reads the item `measure()` uses when it is given none.

        Returns:
            The raw item the default target produces.

        Raises:
            ValidationError: If there is no default target. Raised before any
                COM call.
            Auto3dxError: If reading the default target fails in COM.
        """
        if self._default_target is None:
            raise ValidationError(
                "No item was given and this SolidMeasurement has no default "
                "target. Pass the item to measure, or use part.measurement, "
                "which measures the Part's main body by default."
            )
        try:
            return self._default_target()
        except pywintypes.com_error as error:
            raise automation_error(error, "reading the default measurement target") from error

    def measure(self, item: Any = None) -> MassProperties:
        """Measures volume, area, mass, and centre of gravity for one solid.

        Verified with both a raw `MainBody` and a
        `Part.CreateReferenceFromObject(body)`, which gave identical results,
        so either form of `item` works.

        Args:
            item: The raw CATIA item to measure (a `Body`/`MainBody`, or a
                `Reference` built from one). Omit it to measure the default
                target, which is the Part's main body when this object came
                from `part.measurement`.

        Returns:
            A `MassProperties` with every value already converted out of
            CATIA's native metres/cubic-metres into this library's
            millimetre-based units.

        Raises:
            Auto3dxError: The underlying COM call failed unexpectedly (for
                example, `item` is not something the service can measure).
        """
        if item is None:
            item = self._read_default_target()
        service = self._inertia_service_com_object()
        try:
            inertia = service.GetInertiaElement(item)
            volume_m3 = float(inertia.GetVolume())
            area_m2 = float(inertia.GetArea())
            mass_kg = float(inertia.GetMass())
            # Looks like three by-reference out-params in the type library;
            # pywin32 actually RETURNS them as a tuple instead of mutating
            # anything passed in (verified live).
            x_m, y_m, z_m = (
                float(value) for value in inertia.GetCOGPosition()
            )
        except pywintypes.com_error as error:
            raise automation_error(error, "measuring mass properties") from error
        except (AttributeError, TypeError, ValueError) as error:
            raise AutomationError(
                "InertiaService returned invalid mass-property data."
            ) from error
        return MassProperties(
            volume_mm3=volume_m3 * CUBIC_METRES_TO_CUBIC_MILLIMETRES,
            area_mm2=area_m2 * SQUARE_METRES_TO_SQUARE_MILLIMETRES,
            mass_kg=mass_kg,
            cog_mm=(
                x_m * METRES_TO_MILLIMETRES,
                y_m * METRES_TO_MILLIMETRES,
                z_m * METRES_TO_MILLIMETRES,
            ),
        )

    def __repr__(self) -> str:
        """str: Debug representation; does not contact CATIA."""
        return "SolidMeasurement()"
