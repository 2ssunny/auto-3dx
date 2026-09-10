"""Public API for auto_3dx: attach to a running 3DEXPERIENCE session and edit Part parameters."""

from auto_3dx.core.application import Catia
from auto_3dx.core.part import Part
from auto_3dx.errors import (
    Auto3dxError,
    CatiaConnectionError,
    Com3dxNotFoundError,
    FeatureConflictError,
    FeatureNotFoundError,
    NoActiveEditorError,
    NoActivePartError,
    ParameterAlreadyExistsError,
    ParameterNameError,
    ParameterNotFoundError,
    ParameterTypeError,
    PartUpdateError,
    SketchAlreadyExistsError,
    SketchNotFoundError,
    SketchSupportMismatchError,
    UnsupportedSupportError,
    UnsupportedUnitError,
)
from auto_3dx.geometry.part_design import Pad, PartDesign
from auto_3dx.geometry.sketch import Sketch, SketchCollection, SketchEditor
from auto_3dx.parameters.collection import ParameterCollection
from auto_3dx.parameters.parameter import Parameter, ParameterInfo

__all__ = [
    "Catia",
    "Part",
    "Parameter",
    "ParameterCollection",
    "ParameterInfo",
    "Pad",
    "PartDesign",
    "Sketch",
    "SketchCollection",
    "SketchEditor",
    "Auto3dxError",
    "CatiaConnectionError",
    "Com3dxNotFoundError",
    "FeatureConflictError",
    "FeatureNotFoundError",
    "NoActiveEditorError",
    "NoActivePartError",
    "ParameterAlreadyExistsError",
    "ParameterNameError",
    "ParameterNotFoundError",
    "ParameterTypeError",
    "PartUpdateError",
    "SketchAlreadyExistsError",
    "SketchNotFoundError",
    "SketchSupportMismatchError",
    "UnsupportedSupportError",
    "UnsupportedUnitError",
]
