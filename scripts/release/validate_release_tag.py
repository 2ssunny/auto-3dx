"""Checks a GitHub Release tag against the version the source tree declares.

A release is published only when its tag is a plain `vX.Y.Z` and `X.Y.Z` equals
`[project].version` in `pyproject.toml`. The workflow never writes the version: the tagged
source must already declare it, so what is published is exactly what was reviewed.

    python scripts/release/validate_release_tag.py --tag v1.0.0 --pyproject pyproject.toml

On success it prints the version and, under GitHub Actions, writes `version=X.Y.Z` to
`$GITHUB_OUTPUT`. On failure it prints a GitHub `::error::` line and exits with status 1.
Standard library only.
"""

import argparse
import os
import re
import sys
import tomllib
from pathlib import Path

TAG_PATTERN = re.compile(r"^v([0-9]+\.[0-9]+\.[0-9]+)$")


class ReleaseTagError(ValueError):
    """The tag or the declared version makes the release unsafe to publish."""


def version_from_tag(tag: str) -> str:
    """Returns `X.Y.Z` for a `vX.Y.Z` tag.

    Raises:
        ReleaseTagError: If the tag is not exactly `v` followed by three numbers.
    """
    match = TAG_PATTERN.fullmatch(tag)
    if match is None:
        raise ReleaseTagError(
            f"Release tag {tag!r} is not of the form vX.Y.Z (for example v1.0.0)."
        )
    return match.group(1)


def declared_version(pyproject: Path) -> str:
    """Returns the static `[project].version` of a `pyproject.toml`.

    Raises:
        ReleaseTagError: If the file has no static version (a dynamic one cannot be
            checked against the tag before building).
    """
    project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
    if "version" in project.get("dynamic", []):
        raise ReleaseTagError(
            f"{pyproject} declares a dynamic version; release needs a static one."
        )
    version = project.get("version")
    if not isinstance(version, str) or not version:
        raise ReleaseTagError(f"{pyproject} has no [project].version.")
    return version


def validate(tag: str, pyproject: Path) -> str:
    """Returns the release version when the tag and the source tree agree.

    Raises:
        ReleaseTagError: If the tag is malformed or names a different version.
    """
    tagged = version_from_tag(tag)
    declared = declared_version(pyproject)
    if tagged != declared:
        raise ReleaseTagError(
            f"Release tag {tag!r} names version {tagged}, but pyproject.toml declares "
            f"{declared}. Set the version in the source, commit it, and tag that commit."
        )
    return declared


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", required=True, help="The GitHub Release tag, such as v1.0.0.")
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    arguments = parser.parse_args(argv)
    try:
        version = validate(arguments.tag, arguments.pyproject)
    except ReleaseTagError as error:
        print(f"::error::{error}")
        return 1
    print(f"Release tag {arguments.tag} matches package version {version}.")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"version={version}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
