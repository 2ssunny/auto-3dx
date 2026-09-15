"""The one place that turns a `pywintypes.com_error` into an SDK error.

Before this module the same translation was copied into six modules, each with its
own message format. A caller could not rely on the HRESULT being present, and an
unexpected COM failure surfaced as a bare `Auto3dxError`, indistinguishable from a
validation error. Every COM failure now becomes an `AutomationError` carrying the
HRESULT, with the original error chained by the caller's `raise ... from error`
(`docs/api-design.md` section 8).

This module is a leaf: it imports only `errors` and `pywintypes`.
"""

import pywintypes

from auto_3dx.errors import AutomationError

_HRESULT_MASK = 0xFFFFFFFF
"""Masks a signed COM HRESULT down to its unsigned 32-bit bit pattern for display."""


def hresult_of(error: pywintypes.com_error) -> int | None:
    """Returns the HRESULT a COM error carries.

    Args:
        error: The caught `pywintypes.com_error`.

    Returns:
        The signed HRESULT, or `None` when the error carries no integer code.
    """
    if not error.args:
        return None
    code = error.args[0]
    return code if isinstance(code, int) else None


def format_hresult(hresult: int | None) -> str:
    """Formats an HRESULT the way Windows documentation writes it.

    Args:
        hresult: A signed HRESULT, or `None`.

    Returns:
        A string such as ``"0x80020009"``, or ``"unknown"`` when there is none.
    """
    if hresult is None:
        return "unknown"
    return f"0x{hresult & _HRESULT_MASK:08X}"


def automation_error(error: pywintypes.com_error, action: str | None = None) -> AutomationError:
    """Builds the `AutomationError` for a failed COM call.

    The caller raises it with `raise automation_error(error) from error`, so the
    original COM error stays reachable as `__cause__`.

    Args:
        error: The caught `pywintypes.com_error`.
        action: What was being attempted, as a short phrase such as
            ``"reading Part.Name"``. Omitted when the call site has nothing more
            specific to say than that the call failed.

    Returns:
        An `AutomationError` whose message names the action and the HRESULT, and
        whose `hresult` attribute holds the code.
    """
    hresult = hresult_of(error)
    subject = f"Unexpected COM failure while {action}" if action else "Unexpected COM failure"
    return AutomationError(f"{subject} (HRESULT={format_hresult(hresult)}).", hresult)
