"""High-level access to CATIA parameters.

This package wraps the raw CATIA `Parameter` and `Parameters` COM objects so
callers work with typed, documented Python objects instead of raw COM.
"""

from auto_3dx.parameters.collection import ParameterCollection
from auto_3dx.parameters.parameter import (
    LENGTH_KIND,
    LENGTH_MAGNITUDE,
    MILLIMETRE,
    NAME_SEPARATOR,
    SUPPORTED_LENGTH_UNITS,
    Parameter,
    ParameterInfo,
)

__all__ = [
    "Parameter",
    "ParameterInfo",
    "ParameterCollection",
    "LENGTH_KIND",
    "LENGTH_MAGNITUDE",
    "MILLIMETRE",
    "NAME_SEPARATOR",
    "SUPPORTED_LENGTH_UNITS",
]
