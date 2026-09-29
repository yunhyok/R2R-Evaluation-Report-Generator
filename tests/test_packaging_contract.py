from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_dependencies_are_exact_and_lightweight() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert project["dependencies"] == ["PySide6==6.11.1", "openpyxl==3.1.5"]
    text = "\n".join(project["dependencies"]).casefold()
    for forbidden in ("pandas", "numpy", "torch", "scikit", "sklearn"):
        assert forbidden not in text


def test_installer_uses_production_and_disposable_contracts() -> None:
    installer = (ROOT / "installer" / "r2r_evaluation_report_generator.iss").read_text(
        encoding="utf-8"
    )
    assert "{BFA7031A-FBC3-4878-8893-9B83A28587DA}" in installer
    assert "{2E42973D-7A33-4CF3-91FD-7A4C62ACCC4F}" in installer
    assert "PrivilegesRequired=lowest" in installer
    assert r"{localappdata}\Programs\R2R Evaluation Report Generator" in installer


def test_pyinstaller_uses_absolute_import_launcher() -> None:
    spec = (ROOT / "r2r_evaluation_report.spec").read_text(encoding="utf-8")
    launcher = (ROOT / "scripts" / "pyinstaller_entry.py").read_text(encoding="utf-8")
    assert '"scripts" / "pyinstaller_entry.py"' in spec
    assert "from r2r_evaluation_report.cli import main" in launcher
    assert 'excluded_environment_icu = {"icuuc.dll"}' in spec


def test_repository_contract_excludes_data_and_binaries() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("/*.xlsx", "/*.csv", "/build/", "/dist/"):
        assert pattern in ignore
    assert "All Rights Reserved" in (ROOT / "LICENSE").read_text(encoding="utf-8")


def test_installed_actual_ui_verifier_is_disposable_and_pair_aware() -> None:
    script = (ROOT / "scripts" / "verify_installed_actual_ui.ps1").read_text(encoding="utf-8")
    assert "2E42973D-7A33-4CF3-91FD-7A4C62ACCC4F" in script
    assert "R2REvaluationReportGenerator-Verification-" in script
    assert "verify_actual_ui.ps1" in script
    assert "-color-only.xlsx" in script
    assert "0.6666667" in script and "0.8333333" in script and "Factor = '1'" in script
    assert "QT_QPA_PLATFORM = 'offscreen'" in script
    assert "INSTALLED_ACTUAL_UI_OK" in script
