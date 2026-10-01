"""Checks that `dist/` holds exactly the wheel and sdist of one expected version.

Run after `python -m build`. It requires exactly one `auto_3dx-<version>-py3-none-any.whl`
and one `auto_3dx-<version>.tar.gz`, and reads the metadata INSIDE each one: the
distribution name, the version, and the Apache-2.0 license with its LICENSE file. A file
name alone could disagree with the metadata pip actually installs. When the
`trove-classifiers` package is installed it also checks every classifier, because PyPI
rejects an upload with an unknown one and `twine check` does not.

    python scripts/release/check_dist.py --dist dist --expected-version 1.0.0

Exits with status 1 and a GitHub `::error::` line on the first problem. Standard library,
plus `trove-classifiers` when installed.
"""

import argparse
import sys
import tarfile
import zipfile
from email.parser import HeaderParser
from pathlib import Path

DISTRIBUTION = "auto-3dx"
NORMALIZED = "auto_3dx"
LICENSE_EXPRESSION = "Apache-2.0"


class DistError(ValueError):
    """The built artifacts are not exactly what should be published."""


def _metadata(text: str, label: str, version: str) -> None:
    headers = HeaderParser().parsestr(text)
    if headers.get("Name") != DISTRIBUTION:
        raise DistError(f"{label}: Name is {headers.get('Name')!r}, expected {DISTRIBUTION!r}.")
    if headers.get("Version") != version:
        raise DistError(f"{label}: Version is {headers.get('Version')!r}, expected {version!r}.")
    if headers.get("License-Expression") != LICENSE_EXPRESSION:
        raise DistError(
            f"{label}: License-Expression is {headers.get('License-Expression')!r}, "
            f"expected {LICENSE_EXPRESSION!r}."
        )
    if "LICENSE" not in headers.get_all("License-File", []):
        raise DistError(f"{label}: the LICENSE file is not declared (License-File).")
    known = _known_classifiers()
    if known is not None:
        unknown = [c for c in headers.get_all("Classifier", []) if c not in known]
        if unknown:
            raise DistError(f"{label}: PyPI would reject unknown classifiers {unknown}.")


def _known_classifiers() -> "frozenset[str] | None":
    """The official classifier list, or `None` when `trove-classifiers` is not installed."""
    try:
        from trove_classifiers import classifiers
    except ImportError:
        return None
    return frozenset(classifiers)


def check(dist: Path, version: str) -> "list[Path]":
    """Returns the wheel and sdist paths when both are exactly right.

    Raises:
        DistError: If an artifact is missing, extra, misnamed, or carries wrong metadata.
    """
    files = sorted(path for path in dist.iterdir() if path.is_file())
    wheel = dist / f"{NORMALIZED}-{version}-py3-none-any.whl"
    sdist = dist / f"{NORMALIZED}-{version}.tar.gz"
    if sorted([wheel, sdist]) != files:
        raise DistError(
            f"{dist} must contain exactly {wheel.name} and {sdist.name}; it contains "
            f"{[path.name for path in files]}."
        )
    with zipfile.ZipFile(wheel) as archive:
        info = f"{NORMALIZED}-{version}.dist-info"
        names = set(archive.namelist())
        _metadata(archive.read(f"{info}/METADATA").decode("utf-8"), wheel.name, version)
        if not any(name.startswith(f"{info}/") and name.endswith("LICENSE") for name in names):
            raise DistError(f"{wheel.name}: LICENSE is not packaged in {info}/.")
        if f"{NORMALIZED}/__init__.py" not in names:
            raise DistError(f"{wheel.name}: the {NORMALIZED} package is missing.")
    with tarfile.open(sdist) as archive:
        root = f"{NORMALIZED}-{version}"
        member = archive.extractfile(f"{root}/PKG-INFO")
        if member is None:
            raise DistError(f"{sdist.name}: PKG-INFO is missing.")
        _metadata(member.read().decode("utf-8"), sdist.name, version)
        if f"{root}/LICENSE" not in archive.getnames():
            raise DistError(f"{sdist.name}: LICENSE is not included.")
    return [wheel, sdist]


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--expected-version", required=True)
    arguments = parser.parse_args(argv)
    try:
        artifacts = check(arguments.dist, arguments.expected_version)
    except (DistError, OSError, KeyError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"::error::{error}")
        return 1
    for artifact in artifacts:
        print(f"OK {artifact.name} ({artifact.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
