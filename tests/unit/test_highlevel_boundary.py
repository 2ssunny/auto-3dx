"""The intent layer (`auto_3dx.highlevel`) never touches COM and never rebuilds.

Level 3 must be built only from the public Level 2 API (`docs/phase5-api-design.md`
section 1). These tests parse every module of the package and fail on anything that would
let it bypass Level 2:

* importing a COM library (`pywintypes`, `pythoncom`, `win32com`, `com3dx`) or the SDK's
  own COM plumbing (`auto_3dx._com`, `auto_3dx.transport`);
* reading `com_object` / `_com_object` -- the raw escape hatch;
* touching a member spelled like a CATIA Automation member (`.Shapes`, `.Update`,
  `.GetOrigin`, ...): every one of those lives behind Level 2;
* reaching into another object's private state (`other._x`), which would couple the intent
  layer to Level 2 internals;
* calling `update()` or `summary()`: Level 3 never rebuilds and never runs the full
  inspection.
"""

import ast
from pathlib import Path

import pytest

import auto_3dx.highlevel

PACKAGE = Path(auto_3dx.highlevel.__file__).parent
MODULES = sorted(PACKAGE.glob("*.py"))
FORBIDDEN_IMPORTS = (
    "pywintypes",
    "pythoncom",
    "win32com",
    "com3dx",
    "auto_3dx._com",
    "auto_3dx.transport",
)
OWN_OBJECT_NAMES = {"self", "cls", "instance"}
FORBIDDEN_CALLS = {"update", "summary"}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_the_package_has_modules_to_check() -> None:
    names = {path.stem for path in MODULES}

    assert {"directions", "facts", "features", "finders", "profiles"} <= names


@pytest.mark.parametrize("path", MODULES, ids=lambda path: path.stem)
def test_no_com_library_is_imported(path: Path) -> None:
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert not name.startswith(FORBIDDEN_IMPORTS), f"{path.name} imports {name}"


@pytest.mark.parametrize("path", MODULES, ids=lambda path: path.stem)
def test_no_raw_com_member_is_touched(path: Path) -> None:
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Attribute):
            continue
        attribute = node.attr
        assert attribute not in ("com_object", "_com_object"), (
            f"{path.name}:{node.lineno} reads {attribute}"
        )
        assert not attribute[:1].isupper(), (
            f"{path.name}:{node.lineno} touches .{attribute}, a CATIA-style member"
        )
        if attribute.startswith("_") and not attribute.startswith("__"):
            owner = node.value
            assert isinstance(owner, ast.Name) and owner.id in OWN_OBJECT_NAMES, (
                f"{path.name}:{node.lineno} reaches into another object's .{attribute}"
            )


@pytest.mark.parametrize("path", MODULES, ids=lambda path: path.stem)
def test_nothing_rebuilds_or_runs_the_full_summary(path: Path) -> None:
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in FORBIDDEN_CALLS, (
                f"{path.name}:{node.lineno} calls .{node.func.attr}()"
            )
