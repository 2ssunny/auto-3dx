"""Tests for the update policy (`docs/api-design.md` section 6).

`part.update()` is the only method in the SDK that rebuilds the model. A rebuild is
observable, it can fail, and a failed rebuild poisons every later rebuild until the
offending feature is removed. A caller -- especially an AI agent -- must be able to
point at the one line where it happened, so no constructor, setter, `ensure` or
removal may rebuild implicitly.

This is checked against the source rather than through fakes, because a fake only
covers the paths a test happens to drive. Scanning the parsed source catches an
`Update()` call added anywhere, including in a code path no test exercises.
"""

import ast
import pathlib

PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "auto_3dx"
REBUILD_METHOD = "Update"
# The one module, and the one function in it, allowed to rebuild.
REBUILD_OWNER = ("core/part.py", "update")


def _update_calls() -> "list[tuple[str, str, int]]":
    """Finds every `<expression>.Update(...)` call in the package source.

    Returns:
        One `(relative path, enclosing function name, line)` entry per call.
    """
    calls: list[tuple[str, str, int]] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        relative = path.relative_to(PACKAGE_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(function):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == REBUILD_METHOD
                ):
                    calls.append((relative, function.name, node.lineno))
    return calls


def test_the_package_source_was_found() -> None:
    """Guards against this test passing vacuously on an empty scan."""
    assert (PACKAGE_ROOT / "core" / "part.py").is_file()


def test_only_part_update_rebuilds_the_model() -> None:
    """Every `Update()` call lives in `Part.update()`, and nowhere else."""
    offenders = [
        f"{path}:{line} in {function}()"
        for path, function, line in _update_calls()
        if (path, function) != REBUILD_OWNER
    ]

    assert offenders == [], (
        "Only Part.update() may call Update(); an implicit rebuild hides where a "
        f"rebuild happened and where it failed: {offenders}"
    )


def test_part_update_does_rebuild() -> None:
    """The allowed call site must actually exist, or the policy is meaningless."""
    owners = {(path, function) for path, function, _ in _update_calls()}

    assert REBUILD_OWNER in owners


def test_the_sdk_never_saves_or_propagates() -> None:
    """Persistence is a separate safety class the SDK never enters.

    In 3DEXPERIENCE, `Save()` and `PLMPropagate()` commit to the server and include
    every unsaved change in the session, not just the SDK's own.
    """
    forbidden = {"Save", "PLMPropagate"}
    offenders = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        relative = path.relative_to(PACKAGE_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in forbidden
            ):
                offenders.append(f"{relative}:{node.lineno} calls {node.func.attr}()")

    assert offenders == []
