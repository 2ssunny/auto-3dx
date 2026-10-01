# Contributing to auto-3dx

Thanks for helping. auto-3dx drives a live CAD session, so the rules below are mostly about
not surprising a user's model.

## Branches and pull requests

- `main` is the released line; `develop` is the integration branch.
- Work on a `feat/<name>`, `fix/<name>`, `docs/<name>` or `chore/<name>` branch from
  `develop`, and open the pull request against `develop`. Release-ready work reaches `main`
  through a pull request from `develop`.
- Use Angular-style messages: `feat(scope): ...`, `fix: ...`, `docs: ...`, `test: ...`,
  `ci: ...`, `chore: ...`.
- Never force-push a shared branch, and do not skip hooks.

## Development setup

```powershell
git clone https://github.com/2ssunny/auto-3dx.git
cd auto-3dx
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

Import the package through an installation like this one. Do not add `sys.path` or
`PYTHONPATH` hacks to code, tests or examples.

## Tests

**Unit tests** use fake COM objects and need no 3DEXPERIENCE:

```powershell
python -m pytest tests/unit -q
```

Every change to `src/` needs unit tests, and the suite must pass. Pull requests run:

| Workflow | When | What |
|---|---|---|
| `unit-tests` | every push and pull request | a regular (non-editable) install, then the unit suite on Windows, Python 3.11–3.14 |
| `package-check` | pull requests, pushes to `main` and `develop` | build sdist and wheel, `twine check --strict`, check the metadata in both, install the wheel into a clean environment and import it |

**Live integration tests** need a running, licensed 3DEXPERIENCE session and are never run
in CI. They are opt-in and run only against a **disposable** Part, named explicitly:

```powershell
$env:AUTO3DX_LIVE_PART = "<name of a disposable, blank Part>"
python -m pytest tests/integration -m integration -s -q
```

The suites refuse to start unless the active Part is the named one, create objects only
under their own name prefix, remove only what they created, and never save. A new live
behaviour should be established by a small, single-question probe (`scripts/probes/`)
before it reaches the package: a CATIA call returning an object is not evidence that the
feature is valid until a rebuild succeeds and the result is checked.

## Public API

- The public API is what `auto_3dx`, its public subpackages and their documented wrappers
  export. Keep it stable: add rather than change, and deprecate (with a
  `DeprecationWarning`) before removing.
- Public calls validate their arguments before any COM call and raise the typed errors of
  `auto_3dx.errors`; a `pywintypes.com_error` must not escape the library.
- Nothing in the library may call `Save`, `SaveAs`, `PLMPropagate` or an export, launch
  3DEXPERIENCE, or rebuild implicitly: `part.update()` is the only rebuild.
- The architecture rules are in
  [docs/api-design.md](https://github.com/2ssunny/auto-3dx/blob/main/docs/api-design.md).

**Documentation is part of the change.** A pull request that adds or changes public API also
updates [docs/v1.0.0.md](https://github.com/2ssunny/auto-3dx/blob/main/docs/v1.0.0.md) (or
the guide for the current version), the docstrings, and any affected example. Document
behaviour that was verified, not plans.

## Raw COM

- Raw Automation (`win32com`, `com3dx`, `com_object`, CATIA's `Selection`, `ShapeFactory`)
  belongs inside the library's implementation and in `scripts/probes/`, nowhere else.
- Consumer code -- examples, acceptance scripts, documentation snippets and user scripts --
  uses the public `auto_3dx` API only. `com_object` stays an expert escape hatch.
- Never select topology by list position, `index` or by parsing `descriptor`; use a
  semantic query and `one()`.

## Safety

- Live work happens in a disposable Part. Use distinctive names, clean up in `finally`, and
  confirm the cleanup by reading the model again.
- Never delete or modify objects you did not create.
- Never save from code; the user saves in the UI.

## Releasing (maintainers)

PyPI publishing is done by `.github/workflows/release.yml` when a GitHub Release is
**published**. **Pushing a tag alone does not publish to PyPI**, and neither does saving a
draft release.

1. Make sure `develop` is ready, then merge the release-ready work into `main`.
2. Make sure CI (`unit-tests`, `package-check`) passes on `main`.
3. Set `version` in `pyproject.toml` to the release version, and commit it with any
   documentation changes. The workflow never edits the version.
4. Create the tag `vX.Y.Z` on that `main` commit.
5. Create a GitHub Release from the tag, review the notes, and click **Publish release**.
6. `release.yml` then refuses to continue unless the tag is exactly `vX.Y.Z`, matches the
   `pyproject.toml` version, is not marked pre-release, and points to a commit reachable from
   `main`. It builds that exact commit, checks and smoke-installs the artifacts, and
   publishes those same artifacts through PyPI Trusted Publishing (no stored token).

PyPI versions are immutable. If a published version is broken, release a new version
(`1.0.1`); never try to replace an uploaded one.

## License

By contributing you agree that your contributions are licensed under the
[Apache License 2.0](https://github.com/2ssunny/auto-3dx/blob/main/LICENSE), the project's
license.
