"""Tests for the unit catalogue and non-Length parameter types.

Verified live against B428_Cloud (probes 23/24, `docs/conventions.md`
sections 1.1.2 and 6.15):

    CreateReal(name, 1.5)     -> RealParam   Value writable
    CreateInteger(name, 7)    -> IntParam    Value writable
    CreateString(name, "abc") -> StrParam    Value writable
    CreateBoolean(name, True) -> BoolParam   Value writable
    CreateDimension(name, magnitude, value)  -> type depends on magnitude
    CreateDimension with a bogus magnitude   -> com_error

Only `Length` and `Angle` get a derived wrapper type; every other magnitude
(`Mass`, `Volume`, `Time`, ...) comes back as a generic `Dimension`, so
`type(obj).__name__` alone cannot tell them apart -- the magnitude comes from
`Dimension.Unit`. `RealParam`/`IntParam`/`StrParam`/`BoolParam` have no `Unit`
at all.

`Parameters.Units`: 1887 entries, 339 distinct magnitudes in the real
installation; the fake here is seeded with a handful (Length/Angle/Mass/
Volume) so `symbols()`/`supports()` have something real to exercise.

`Value` is always in the parameter's own internal unit -- the library never
converts. A `unit` argument only checks the caller meant the unit the
parameter actually has.
"""

from collections.abc import Callable
from typing import Any

import pytest

from auto_3dx.errors import (
    AmbiguousNameError,
    ParameterAlreadyExistsError,
    ParameterTypeError,
    UnsupportedMagnitudeError,
    UnsupportedUnitError,
)
from auto_3dx.parameters.collection import ParameterCollection
from auto_3dx.parameters.parameter import (
    BOOLEAN_KIND,
    DIMENSION_KIND,
    INTEGER_KIND,
    MILLIMETRE,
    REAL_KIND,
    STRING_KIND,
    Parameter,
)
from auto_3dx.parameters.units import UnitCatalogue

MASS_NAME = "AUTO3DX_MASS"


@pytest.fixture
def raw_parameters(parameters_collection_factory: Callable[..., Any]) -> Any:
    """A fake `Parameters` COM object with no user parameters yet."""
    return parameters_collection_factory([])


@pytest.fixture
def catalogue(raw_parameters: Any) -> UnitCatalogue:
    """A `UnitCatalogue` over the default-seeded fake `Units` collection."""
    return UnitCatalogue(raw_parameters)


@pytest.fixture
def empty_collection(raw_parameters: Any) -> ParameterCollection:
    """A `ParameterCollection` with no parameters, as an open Part may have."""
    return ParameterCollection(raw_parameters)


def _dimension(
    dimension_fake_factory: Callable[..., Any],
    name: str = MASS_NAME,
    value: float = 2.0,
    magnitude: str = "Mass",
    symbol: str = "kg",
    unit_name: str = "Kilogram",
) -> Any:
    """Builds a generic-`Dimension`-kind fake for a non-Length/Angle magnitude."""
    return dimension_fake_factory(
        "Dimension", name=name, value=value, magnitude=magnitude, symbol=symbol, unit_name=unit_name
    )


# --- UnitCatalogue -----------------------------------------------------------


def test_magnitudes_are_sorted_and_distinct(catalogue: UnitCatalogue) -> None:
    """The default fake seed carries four magnitudes; `magnitudes()` sorts them."""
    assert catalogue.magnitudes() == ["Angle", "Length", "Mass", "Volume"]


def test_units_and_symbols_return_that_magnitudes_entries(catalogue: UnitCatalogue) -> None:
    """`units()`/`symbols()` only return entries for the requested magnitude."""
    mass_units = catalogue.units("Mass")

    assert [unit.symbol for unit in mass_units] == ["kg", "g", "T"]
    assert all(unit.magnitude == "Mass" for unit in mass_units)
    assert catalogue.symbols("Mass") == ["kg", "g", "T"]
    assert catalogue.symbols("Volume") == ["m3", "L"]


def test_supports_true_for_a_known_pair_false_otherwise(catalogue: UnitCatalogue) -> None:
    """`supports()` checks both the magnitude and the symbol."""
    assert catalogue.supports("Length", "mm") is True
    assert catalogue.supports("Length", "furlong") is False
    assert catalogue.supports("Bogus", "mm") is False


def test_units_collection_enumerated_only_once_across_several_queries(
    parameters_collection_factory: Callable[..., Any],
    units_collection_factory: Callable[..., Any],
) -> None:
    """1887 real entries makes re-enumerating per query a genuine defect."""
    entries = [
        ("Millimeter", "Length", "mm"),
        ("Kilogram", "Mass", "kg"),
        ("Gram", "Mass", "g"),
    ]
    units_com = units_collection_factory(entries=entries)
    raw = parameters_collection_factory(units=units_com)
    fresh_catalogue = UnitCatalogue(raw)

    fresh_catalogue.magnitudes()
    fresh_catalogue.units("Length")
    fresh_catalogue.symbols("Mass")
    fresh_catalogue.supports("Mass", "kg")

    # Count and Item together must reflect exactly ONE enumeration pass, no
    # matter how many query methods were called afterward.
    assert units_com.count_calls == 1
    assert units_com.item_calls == [1, 2, 3]


# --- create_real / create_integer / create_string / create_boolean ----------


def test_create_real_calls_create_real_with_a_float(
    empty_collection: ParameterCollection,
) -> None:
    """`create_real` must go through `CreateReal`, not `CreateDimension`."""
    created = empty_collection.create_real("AUTO3DX_REAL", 2)

    assert empty_collection.com_object.create_real_calls == [("AUTO3DX_REAL", 2.0)]
    assert empty_collection.com_object.create_calls == []
    assert isinstance(empty_collection.com_object.create_real_calls[0][1], float)
    assert created.kind == REAL_KIND == "RealParam"


def test_create_integer_calls_create_integer_with_an_int(
    empty_collection: ParameterCollection,
) -> None:
    """`iValue` for `CreateInteger` is a COM long, so it must stay an `int`."""
    created = empty_collection.create_integer("AUTO3DX_INT", 7)

    assert empty_collection.com_object.create_integer_calls == [("AUTO3DX_INT", 7)]
    assert isinstance(empty_collection.com_object.create_integer_calls[0][1], int)
    assert created.kind == INTEGER_KIND == "IntParam"


def test_create_string_calls_create_string_with_a_str(
    empty_collection: ParameterCollection,
) -> None:
    """`create_string` must go through `CreateString`."""
    created = empty_collection.create_string("AUTO3DX_STR", "abc")

    assert empty_collection.com_object.create_string_calls == [("AUTO3DX_STR", "abc")]
    assert created.kind == STRING_KIND == "StrParam"


def test_create_boolean_calls_create_boolean_with_a_bool(
    empty_collection: ParameterCollection,
) -> None:
    """`create_boolean` must go through `CreateBoolean`."""
    created = empty_collection.create_boolean("AUTO3DX_BOOL", True)

    assert empty_collection.com_object.create_boolean_calls == [("AUTO3DX_BOOL", True)]
    assert created.kind == BOOLEAN_KIND == "BoolParam"


# --- create_dimension ---------------------------------------------------------


def test_create_dimension_mass_calls_create_dimension_with_the_magnitude(
    empty_collection: ParameterCollection,
) -> None:
    """A non-Length/Angle magnitude still goes through `CreateDimension`."""
    created = empty_collection.create_dimension(MASS_NAME, "Mass", 2)

    assert empty_collection.com_object.create_calls == [(MASS_NAME, "Mass", 2.0)]
    assert created.kind == DIMENSION_KIND == "Dimension"
    assert created.magnitude == "Mass"


def test_create_dimension_rejects_an_unknown_magnitude_before_com(
    empty_collection: ParameterCollection,
) -> None:
    """The magnitude is checked against the unit catalogue before COM is touched."""
    with pytest.raises(UnsupportedMagnitudeError):
        empty_collection.create_dimension("AUTO3DX_BOGUS", "Bogus", 1)

    assert empty_collection.com_object.create_calls == []


# --- Parameter.magnitude / Parameter.unit -------------------------------------


def test_magnitude_reads_unit_magnitude_for_a_dimensional_kind(
    dimension_fake_factory: Callable[..., Any],
) -> None:
    """A generic `Dimension`'s actual quantity comes from `Unit.Magnitude`."""
    parameter = Parameter(_dimension(dimension_fake_factory))

    assert parameter.magnitude == "Mass"


@pytest.mark.parametrize(
    "factory_name",
    ["real_param_factory", "int_param_factory", "str_param_factory", "bool_param_factory"],
)
def test_magnitude_is_none_for_unitless_kinds_whose_unit_raises(
    request: pytest.FixtureRequest,
    factory_name: str,
) -> None:
    """`RealParam`/`IntParam`/`StrParam`/`BoolParam` have no `Unit` at all."""
    factory = request.getfixturevalue(factory_name)
    parameter = Parameter(factory())

    assert parameter.magnitude is None


def test_unit_reads_unit_symbol_when_available(
    dimension_fake_factory: Callable[..., Any],
) -> None:
    """`Unit.Symbol` is the verified way to read a dimensional parameter's unit."""
    parameter = Parameter(_dimension(dimension_fake_factory))

    assert parameter.unit == "kg"


def test_unit_falls_back_to_millimetre_for_a_bare_length_fake(fake_length: Any) -> None:
    """Pre-catalogue fakes have no `Unit` at all; this fallback keeps them passing."""
    parameter = Parameter(fake_length)

    assert parameter.unit == MILLIMETRE == "mm"


# --- Parameter.set() dispatch for Real/Integer/String/Boolean ----------------


def test_set_real_accepts_a_float_and_rejects_a_unit(
    real_param_factory: Callable[..., Any],
) -> None:
    """A `RealParam` has no unit at all, so any `unit` argument is an error."""
    fake = real_param_factory()
    parameter = Parameter(fake)

    parameter.set(3.5)

    assert fake.Value == 3.5
    with pytest.raises(UnsupportedUnitError):
        parameter.set(3.5, unit="mm")


def test_set_real_rejects_a_non_numeric_value(real_param_factory: Callable[..., Any]) -> None:
    """A string value must not silently coerce."""
    parameter = Parameter(real_param_factory())

    with pytest.raises(ParameterTypeError):
        parameter.set("3.5")  # type: ignore[arg-type]


def test_set_integer_accepts_an_int_and_rejects_a_bool(
    int_param_factory: Callable[..., Any],
) -> None:
    """`bool` is a subclass of `int`, so it must be refused explicitly."""
    fake = int_param_factory()
    parameter = Parameter(fake)

    parameter.set(7)

    assert fake.Value == 7
    with pytest.raises(ParameterTypeError):
        parameter.set(True)  # type: ignore[arg-type]


def test_set_string_accepts_a_str_and_rejects_a_number(
    str_param_factory: Callable[..., Any],
) -> None:
    """A `StrParam` must not accept a number as if it were stringifiable."""
    fake = str_param_factory()
    parameter = Parameter(fake)

    parameter.set("abc")

    assert fake.Value == "abc"
    with pytest.raises(ParameterTypeError):
        parameter.set(5)  # type: ignore[arg-type]


def test_set_boolean_accepts_a_bool_and_rejects_an_int(
    bool_param_factory: Callable[..., Any],
) -> None:
    """A `BoolParam` must not accept a plain `int`, even 0/1."""
    fake = bool_param_factory()
    parameter = Parameter(fake)

    parameter.set(True)

    assert fake.Value is True
    with pytest.raises(ParameterTypeError):
        parameter.set(1)  # type: ignore[arg-type]


# --- Parameter.set() dispatch for dimensional kinds ---------------------------


def test_set_dimensional_accepts_its_own_unit(dimension_fake_factory: Callable[..., Any]) -> None:
    """A unit argument matching the parameter's actual unit is accepted."""
    fake = _dimension(dimension_fake_factory)
    parameter = Parameter(fake)

    parameter.set(5, unit="kg")

    assert fake.Value == 5.0


def test_set_dimensional_rejects_a_different_unit_without_converting(
    dimension_fake_factory: Callable[..., Any],
) -> None:
    """auto_3dx never converts units; a mismatch is refused, not silently fixed."""
    fake = _dimension(dimension_fake_factory)
    parameter = Parameter(fake)

    with pytest.raises(UnsupportedUnitError):
        parameter.set(5, unit="g")

    assert fake.Value == 2.0


def test_set_150_with_no_unit_still_works(fake_length: Any) -> None:
    """The no-unit call path must behave exactly as before this feature existed."""
    parameter = Parameter(fake_length)

    parameter.set(150)

    assert fake_length.Value == 150.0


# --- ensure_real / ensure_integer / ensure_string / ensure_boolean ----------


@pytest.mark.parametrize(
    ("ensure_method", "kind", "value"),
    [
        ("ensure_real", REAL_KIND, 2.5),
        ("ensure_integer", INTEGER_KIND, 3),
        ("ensure_string", STRING_KIND, "abc"),
        ("ensure_boolean", BOOLEAN_KIND, True),
    ],
)
def test_ensure_non_length_creates_when_absent(
    empty_collection: ParameterCollection,
    ensure_method: str,
    kind: str,
    value: Any,
) -> None:
    """A missing name is created with the right kind."""
    ensured = getattr(empty_collection, ensure_method)("AUTO3DX_PARAM", value)

    assert ensured.kind == kind


@pytest.mark.parametrize(
    ("ensure_method", "factory_name", "value"),
    [
        ("ensure_real", "real_param_factory", 9.0),
        ("ensure_integer", "int_param_factory", 11),
        ("ensure_string", "str_param_factory", "xyz"),
        ("ensure_boolean", "bool_param_factory", False),
    ],
)
def test_ensure_non_length_updates_when_present(
    request: pytest.FixtureRequest,
    parameters_collection_factory: Callable[..., Any],
    ensure_method: str,
    factory_name: str,
    value: Any,
) -> None:
    """An existing parameter of the right kind is updated in place, not duplicated."""
    factory = request.getfixturevalue(factory_name)
    fake = factory(name="AUTO3DX_PARAM")
    raw = parameters_collection_factory([(fake.Name, fake)])
    collection = ParameterCollection(raw)

    getattr(collection, ensure_method)("AUTO3DX_PARAM", value)

    assert fake.Value == value
    assert raw.create_real_calls == []
    assert raw.create_integer_calls == []
    assert raw.create_string_calls == []
    assert raw.create_boolean_calls == []


@pytest.mark.parametrize(
    ("ensure_method", "value"),
    [
        ("ensure_real", 9.0),
        ("ensure_integer", 9),
        ("ensure_string", "x"),
        ("ensure_boolean", True),
    ],
)
def test_ensure_non_length_refuses_to_repurpose_a_different_kind(
    parameters_collection_factory: Callable[..., Any],
    fake_length: Any,
    ensure_method: str,
    value: Any,
) -> None:
    """A name held by a Length must not be silently overwritten."""
    raw = parameters_collection_factory([(fake_length.Name, fake_length)])
    collection = ParameterCollection(raw)

    with pytest.raises(ParameterTypeError):
        getattr(collection, ensure_method)(fake_length.Name, value)

    assert raw.create_real_calls == []
    assert raw.create_integer_calls == []
    assert raw.create_string_calls == []
    assert raw.create_boolean_calls == []


# --- ensure_dimension ----------------------------------------------------------


def test_ensure_dimension_creates_when_absent(empty_collection: ParameterCollection) -> None:
    """A missing name is created with the requested magnitude."""
    ensured = empty_collection.ensure_dimension(MASS_NAME, "Mass", 2.0)

    assert ensured.magnitude == "Mass"
    assert empty_collection.com_object.create_calls == [(MASS_NAME, "Mass", 2.0)]


def test_ensure_dimension_updates_when_present(
    parameters_collection_factory: Callable[..., Any],
    dimension_fake_factory: Callable[..., Any],
) -> None:
    """A same-magnitude existing `Dimension` is updated in place."""
    fake = _dimension(dimension_fake_factory, name=MASS_NAME)
    raw = parameters_collection_factory([(fake.Name, fake)])
    collection = ParameterCollection(raw)

    collection.ensure_dimension(MASS_NAME, "Mass", 9.0)

    assert fake.Value == 9.0
    assert raw.create_calls == []


def test_ensure_dimension_refuses_a_different_magnitude_of_the_same_generic_kind(
    parameters_collection_factory: Callable[..., Any],
    dimension_fake_factory: Callable[..., Any],
) -> None:
    """A generic `Dimension` kind alone cannot distinguish Mass from Volume."""
    fake = _dimension(dimension_fake_factory, name=MASS_NAME, magnitude="Mass", symbol="kg")
    raw = parameters_collection_factory([(fake.Name, fake)])
    collection = ParameterCollection(raw)

    with pytest.raises(ParameterTypeError):
        collection.ensure_dimension(MASS_NAME, "Volume", 9.0)

    assert fake.Value == 2.0
    assert raw.create_calls == []


def test_ensure_dimension_refuses_an_existing_non_dimension_kind(
    parameters_collection_factory: Callable[..., Any],
    fake_length: Any,
) -> None:
    """A name held by a Length is a different kind from a generic Dimension."""
    raw = parameters_collection_factory([(fake_length.Name, fake_length)])
    collection = ParameterCollection(raw)

    with pytest.raises(ParameterTypeError):
        collection.ensure_dimension(fake_length.Name, "Mass", 9.0)

    assert raw.create_calls == []


# --- duplicate/ambiguous name guards, shared by every create_*/ensure_* -----


_CREATE_CALLS: "list[tuple[str, tuple[Any, ...]]]" = [
    ("create_real", ("AUTO3DX_DUP", 1.0)),
    ("create_integer", ("AUTO3DX_DUP", 1)),
    ("create_string", ("AUTO3DX_DUP", "x")),
    ("create_boolean", ("AUTO3DX_DUP", True)),
    ("create_dimension", ("AUTO3DX_DUP", "Mass", 1.0)),
]

_ENSURE_CALLS: "list[tuple[str, tuple[Any, ...]]]" = [
    ("ensure_real", ("AUTO3DX_DUP", 1.0)),
    ("ensure_integer", ("AUTO3DX_DUP", 1)),
    ("ensure_string", ("AUTO3DX_DUP", "x")),
    ("ensure_boolean", ("AUTO3DX_DUP", True)),
    ("ensure_dimension", ("AUTO3DX_DUP", "Mass", 1.0)),
]


@pytest.mark.parametrize(("create_method", "args"), _CREATE_CALLS)
def test_create_refuses_an_existing_name(
    parameters_collection_factory: Callable[..., Any],
    real_param_factory: Callable[..., Any],
    create_method: str,
    args: "tuple[Any, ...]",
) -> None:
    """CATIA would silently accept the duplicate; the library refuses first."""
    existing = real_param_factory(name="AUTO3DX_DUP")
    raw = parameters_collection_factory([(existing.Name, existing)])
    collection = ParameterCollection(raw)

    with pytest.raises(ParameterAlreadyExistsError):
        getattr(collection, create_method)(*args)

    assert raw.create_calls == []
    assert raw.create_real_calls == []
    assert raw.create_integer_calls == []
    assert raw.create_string_calls == []
    assert raw.create_boolean_calls == []


@pytest.mark.parametrize(("create_method", "args"), _CREATE_CALLS)
def test_create_refuses_two_or_more_matches(
    parameters_collection_factory: Callable[..., Any],
    real_param_factory: Callable[..., Any],
    create_method: str,
    args: "tuple[Any, ...]",
) -> None:
    """A name-based lookup must not guess which of several matches to touch."""
    first = real_param_factory(name="AUTO3DX_DUP")
    second = real_param_factory(name="AUTO3DX_DUP")
    raw = parameters_collection_factory([(first.Name, first), (second.Name, second)])
    collection = ParameterCollection(raw)

    with pytest.raises(AmbiguousNameError):
        getattr(collection, create_method)(*args)

    assert raw.create_calls == []
    assert raw.create_real_calls == []
    assert raw.create_integer_calls == []
    assert raw.create_string_calls == []
    assert raw.create_boolean_calls == []


@pytest.mark.parametrize(("ensure_method", "args"), _ENSURE_CALLS)
def test_ensure_refuses_two_or_more_matches(
    parameters_collection_factory: Callable[..., Any],
    real_param_factory: Callable[..., Any],
    ensure_method: str,
    args: "tuple[Any, ...]",
) -> None:
    """`ensure_*` must not silently pick one of several same-named matches."""
    first = real_param_factory(name="AUTO3DX_DUP")
    second = real_param_factory(name="AUTO3DX_DUP")
    raw = parameters_collection_factory([(first.Name, first), (second.Name, second)])
    collection = ParameterCollection(raw)

    with pytest.raises(AmbiguousNameError):
        getattr(collection, ensure_method)(*args)


def test_create_and_ensure_never_call_part_update(
    empty_collection: ParameterCollection,
    part_factory: Callable[..., Any],
) -> None:
    """Creation/`ensure` is batchable; the caller decides when to update."""
    part = part_factory(parameters=empty_collection.com_object)

    empty_collection.create_real("AUTO3DX_A", 1.0)
    empty_collection.create_integer("AUTO3DX_B", 1)
    empty_collection.create_string("AUTO3DX_C", "x")
    empty_collection.create_boolean("AUTO3DX_D", True)
    empty_collection.create_dimension("AUTO3DX_E", "Mass", 1.0)
    empty_collection.ensure_real("AUTO3DX_A", 2.0)
    empty_collection.ensure_integer("AUTO3DX_B", 2)
    empty_collection.ensure_string("AUTO3DX_C", "y")
    empty_collection.ensure_boolean("AUTO3DX_D", False)
    empty_collection.ensure_dimension("AUTO3DX_E", "Mass", 2.0)

    assert part.update_calls == 0
