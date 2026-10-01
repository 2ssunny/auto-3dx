"""Smoke-checks an INSTALLED auto-3dx, as a user gets it from the wheel.

Run it with the interpreter of a clean environment the wheel was installed into, from a
directory outside the source tree:

    <venv>/python <repo>/scripts/release/smoke_installed.py --expected-version 1.0.0 \
        --forbid-path <repo>

It checks that the distribution metadata reports the expected version, that `auto_3dx` is
imported from that environment and not from the source tree, that the public entry points
import, and that importing loads neither `com3dx` nor anything that needs a running
3DEXPERIENCE session. It never calls `Catia.attach()`. Standard library plus the installed
package only.
"""

import argparse
import importlib
import importlib.metadata
import sys
from pathlib import Path

PUBLIC_IMPORTS = {
    "auto_3dx": ("Catia", "Part", "Auto3dxError"),
    "auto_3dx.errors": ("HolePlacementMismatchError", "SelectionCountError"),
    "auto_3dx.geometry": ("PartSelection", "Counterbore", "Countersink"),
}


class SmokeError(RuntimeError):
    """The installed package is not what was built, or imports something it must not."""


def run(expected_version: str, forbidden: "Path | None") -> str:
    """Returns where `auto_3dx` was imported from when every check passes.

    Raises:
        SmokeError: On the first failed check.
    """
    installed = importlib.metadata.version("auto-3dx")
    if installed != expected_version:
        raise SmokeError(f"Installed auto-3dx is {installed}, expected {expected_version}.")
    package = importlib.import_module("auto_3dx")
    location = Path(package.__file__ or "").resolve()
    if forbidden is not None and location.is_relative_to(forbidden.resolve()):
        raise SmokeError(f"auto_3dx was imported from the source tree ({location}).")
    for module_name, names in PUBLIC_IMPORTS.items():
        module = importlib.import_module(module_name)
        missing = [name for name in names if not hasattr(module, name)]
        if missing:
            raise SmokeError(f"{module_name} lacks public names {missing}.")
    if "com3dx" in sys.modules:
        raise SmokeError("Importing auto_3dx loaded com3dx; import must not need 3DEXPERIENCE.")
    return str(location)


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--forbid-path", type=Path, help="The source tree, which must not be used.")
    arguments = parser.parse_args(argv)
    try:
        location = run(arguments.expected_version, arguments.forbid_path)
    except (SmokeError, ImportError, importlib.metadata.PackageNotFoundError) as error:
        print(f"::error::{error}")
        return 1
    print(f"auto-3dx {arguments.expected_version} imports cleanly from {location}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
