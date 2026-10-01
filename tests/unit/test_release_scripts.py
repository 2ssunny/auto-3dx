"""The release guards in scripts/release/: tag/version agreement and artifact checks.

These scripts decide whether `.github/workflows/release.yml` may publish to PyPI, so their
refusals are tested as carefully as their passes. They are loaded from their files, as the
workflow runs them, rather than imported as a package.
"""

import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

RELEASE_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "release"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, RELEASE_SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tags = _load("validate_release_tag")
dist = _load("check_dist")


def _pyproject(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(body, encoding="utf-8")
    return path


# --- tag and version -----------------------------------------------------------------------


def test_a_matching_tag_passes_and_reports_the_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    pyproject = _pyproject(tmp_path, '[project]\nname = "auto-3dx"\nversion = "1.0.0"\n')

    assert tags.main(["--tag", "v1.0.0", "--pyproject", str(pyproject)]) == 0
    assert output.read_text(encoding="utf-8") == "version=1.0.0\n"
    assert "matches package version 1.0.0" in capsys.readouterr().out


def test_a_tag_for_another_version_fails_before_publishing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    pyproject = _pyproject(tmp_path, '[project]\nversion = "1.0.0"\n')

    assert tags.main(["--tag", "v1.0.1", "--pyproject", str(pyproject)]) == 1
    assert "::error::" in capsys.readouterr().out
    assert not output.exists()  # no version is handed to the build job


@pytest.mark.parametrize(
    "tag",
    [
        "1.0.0",
        "v1.0",
        "v1.0.0-rc.1",
        "v1.0.0.post1",
        "V1.0.0",
        "v01.0.0x",
        " v1.0.0",
        "v1.0.0\n",
        "",
    ],
)
def test_a_malformed_tag_is_rejected(tmp_path: Path, tag: str) -> None:
    pyproject = _pyproject(tmp_path, '[project]\nversion = "1.0.0"\n')

    with pytest.raises(tags.ReleaseTagError, match="vX.Y.Z"):
        tags.validate(tag, pyproject)


def test_a_dynamic_or_missing_version_cannot_be_released(tmp_path: Path) -> None:
    dynamic = _pyproject(tmp_path, '[project]\ndynamic = ["version"]\n')
    with pytest.raises(tags.ReleaseTagError, match="dynamic"):
        tags.validate("v1.0.0", dynamic)
    missing = _pyproject(tmp_path, '[project]\nname = "auto-3dx"\n')
    with pytest.raises(tags.ReleaseTagError, match="no \\[project\\].version"):
        tags.validate("v1.0.0", missing)


def test_the_repository_pyproject_declares_a_releasable_version() -> None:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    version = tags.declared_version(pyproject)

    assert tags.validate(f"v{version}", pyproject) == version


# --- built artifacts -----------------------------------------------------------------------


def _metadata(
    version: str,
    license_expression: str = "Apache-2.0",
    license_file: bool = True,
    classifier: str = "Operating System :: Microsoft :: Windows",
) -> str:
    lines = [
        "Metadata-Version: 2.4",
        "Name: auto-3dx",
        f"Version: {version}",
        f"License-Expression: {license_expression}",
        f"Classifier: {classifier}",
    ]
    if license_file:
        lines.append("License-File: LICENSE")
    return "\n".join(lines) + "\n\n"


def _artifacts(folder: Path, version: str, **metadata: object) -> None:
    folder.mkdir()
    info = f"auto_3dx-{version}.dist-info"
    with zipfile.ZipFile(folder / f"auto_3dx-{version}-py3-none-any.whl", "w") as wheel:
        wheel.writestr("auto_3dx/__init__.py", "")
        wheel.writestr(f"{info}/METADATA", _metadata(version, **metadata))  # type: ignore[arg-type]
        wheel.writestr(f"{info}/licenses/LICENSE", "Apache License")
    with tarfile.open(folder / f"auto_3dx-{version}.tar.gz", "w:gz") as sdist:
        for name, text in (
            ("PKG-INFO", _metadata(version, **metadata)),  # type: ignore[arg-type]
            ("LICENSE", "Apache License"),
        ):
            data = text.encode("utf-8")
            member = tarfile.TarInfo(f"auto_3dx-{version}/{name}")
            member.size = len(data)
            sdist.addfile(member, io.BytesIO(data))


def test_a_correct_wheel_and_sdist_pass(tmp_path: Path) -> None:
    _artifacts(tmp_path / "dist", "1.0.0")

    assert dist.main(["--dist", str(tmp_path / "dist"), "--expected-version", "1.0.0"]) == 0


def test_artifacts_of_another_version_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _artifacts(tmp_path / "dist", "1.0.0")

    assert dist.main(["--dist", str(tmp_path / "dist"), "--expected-version", "1.0.1"]) == 1
    assert "must contain exactly" in capsys.readouterr().out


def test_a_missing_or_extra_artifact_fails(tmp_path: Path) -> None:
    _artifacts(tmp_path / "dist", "1.0.0")
    (tmp_path / "dist" / "auto_3dx-1.0.0.tar.gz").unlink()
    with pytest.raises(dist.DistError):
        dist.check(tmp_path / "dist", "1.0.0")

    _artifacts(tmp_path / "other", "1.0.0")
    (tmp_path / "other" / "auto_3dx-0.9.0-py3-none-any.whl").write_bytes(b"")
    with pytest.raises(dist.DistError, match="exactly"):
        dist.check(tmp_path / "other", "1.0.0")


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ({"license_expression": "MIT"}, "License-Expression"),
        ({"license_file": False}, "License-File"),
    ],
)
def test_wrong_license_metadata_fails(tmp_path: Path, metadata: dict, message: str) -> None:
    _artifacts(tmp_path / "dist", "1.0.0", **metadata)

    with pytest.raises(dist.DistError, match=message):
        dist.check(tmp_path / "dist", "1.0.0")


def test_an_unknown_classifier_fails_when_the_official_list_is_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _artifacts(tmp_path / "dist", "1.0.0", classifier="Topic :: Not A Real Classifier")
    monkeypatch.setattr(dist, "_known_classifiers", lambda: frozenset({"Topic :: Real"}))

    with pytest.raises(dist.DistError, match="unknown classifiers"):
        dist.check(tmp_path / "dist", "1.0.0")
