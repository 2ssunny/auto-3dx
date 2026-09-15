"""High-level access to CATIA parameters.

This package wraps the raw CATIA `Parameter` and `Parameters` COM objects so
callers work with typed, documented Python objects instead of raw COM.
"""

from auto_3dx.parameters.collection import ParameterCollection
from auto_3dx.parameters.parameter import (
    ANGLE_KIND,
    ANGLE_MAGNITUDE,
    BOOLEAN_KIND,
    DIMENSION_KIND,
    DIMENSIONAL_KINDS,
    INTEGER_KIND,
    LENGTH_KIND,
    LENGTH_MAGNITUDE,
    MILLIMETRE,
    NAME_SEPARATOR,
    REAL_KIND,
    STRING_KIND,
    SUPPORTED_LENGTH_UNITS,
    Parameter,
    ParameterInfo,
)
from auto_3dx.parameters.units import UnitCatalogue, UnitInfo

__all__ = [
    "Parameter",
    "ParameterInfo",
    "ParameterCollection",
    "UnitCatalogue",
    "UnitInfo",
    "LENGTH_KIND",
    "LENGTH_MAGNITUDE",
    "ANGLE_KIND",
    "ANGLE_MAGNITUDE",
    "DIMENSION_KIND",
    "DIMENSIONAL_KINDS",
    "REAL_KIND",
    "INTEGER_KIND",
    "STRING_KIND",
    "BOOLEAN_KIND",
    "MILLIMETRE",
    "NAME_SEPARATOR",
    "SUPPORTED_LENGTH_UNITS",
]
