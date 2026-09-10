class Auto3dxError(Exception):
    """Base class for all errors raised by auto_3dx."""


class Com3dxNotFoundError(Auto3dxError):
    """Raised when the installed com3dx.py helper module cannot be located."""


class CatiaConnectionError(Auto3dxError):
    """Raised when attaching to a running 3DEXPERIENCE session fails."""


class NoActiveEditorError(Auto3dxError):
    """Raised when the application has no ActiveEditor."""


class NoActivePartError(Auto3dxError):
    """Raised when the ActiveEditor's ActiveObject is missing or not a Part."""


class ParameterNotFoundError(Auto3dxError):
    """Raised when a parameter cannot be found by name in a Parameters collection."""


class ParameterTypeError(Auto3dxError):
    """Raised when a parameter's kind or a supplied value's type is unsupported."""


class ParameterNameError(Auto3dxError):
    """Raised when a requested parameter name is not usable.

    CATIA accepts an empty name (auto-naming the parameter ``Length.3``) and a
    name containing the ``\\`` container separator, both of which produce a
    parameter the caller cannot reliably address afterwards.
    """


class ParameterAlreadyExistsError(Auto3dxError):
    """Raised when creating a parameter whose name is already taken.

    CATIA silently accepts a duplicate name and creates a second parameter
    reporting the identical name, which only one lookup can ever reach. The
    library refuses instead of corrupting the model that way.
    """


class UnsupportedUnitError(Auto3dxError):
    """Raised when a unit other than a supported one is requested for a parameter."""


class PartUpdateError(Auto3dxError):
    """Raised when Part.Update() fails."""
