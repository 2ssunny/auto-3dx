"""Tests for the update policy (`docs/api-design.md` section 6).

`part.update()` and `body.update()` are the only methods in the SDK that rebuild the
model: the first calls `Part.Update()` for everything, the second `Part.UpdateObject()`
for one body (`part.update(body)` is the same call from the Part). A rebuild is
observable, it can fail, and a failed rebuild makes every later rebuild fail until the
model is repaired. A caller -- especially an AI agent -- must be able to point at the one
line where it happened, so no constructor, setter, `ensure` or removal may rebuild
implicitly.

This is checked against the source rather than through fakes, because a fake only
covers the paths a test happens to drive. Scanning the parsed source catches an
`Update()` call added anywhere, including in a code path no test exercises.
"""

import ast
import pathlib

PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "auto_3dx"
REBUILD_METHODS = ("Update", "UpdateObject")
# The only functions allowed to rebuild, whole-Part and per-body.
REBUILD_OWNERS = {
    ("core/part.py", "update"),
    ("geometry/bodies.py", "update"),
}


def _update_calls() -> "list[tuple[str, str, int]]":
    """Finds every `<expression>.Update(...)`/`.UpdateObject(...)` call in the source.

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
                    and node.func.attr in REBUILD_METHODS
                ):
                    calls.append((relative, function.name, node.lineno))
    return calls


def test_the_package_source_was_found() -> None:
    """Guards against this test passing vacuously on an empty scan."""
    assert (PACKAGE_ROOT / "core" / "part.py").is_file()


def test_only_the_update_methods_rebuild_the_model() -> None:
    """Every rebuild call lives in `Part.update()` or `Body.update()`, nowhere else."""
    offenders = [
        f"{path}:{line} in {function}()"
        for path, function, line in _update_calls()
        if (path, function) not in REBUILD_OWNERS
    ]

    assert offenders == [], (
        "Only Part.update() and Body.update() may rebuild; an implicit rebuild hides "
        f"where a rebuild happened and where it failed: {offenders}"
    )


def test_both_update_methods_really_do_rebuild() -> None:
    """The allowed call sites must actually exist, or the policy is meaningless."""
    owners = {(path, function) for path, function, _ in _update_calls()}

    assert REBUILD_OWNERS <= owners


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
