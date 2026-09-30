from __future__ import annotations

from pathlib import Path

from r2r_evaluation_report import cli


def test_synthetic_export_and_self_test(tmp_path: Path, capsys) -> None:
    output = tmp_path / "synthetic.xlsx"
    assert cli.main(["--synthetic-export", str(output)]) == 0
    assert output.is_file()
    assert cli.SYNTHETIC_EXPORT_MARKER in capsys.readouterr().out

    assert cli.run_self_test() == 0
    assert cli.SELF_TEST_MARKER in capsys.readouterr().out


def test_profile_cli_generates_next_to_profile(tmp_path: Path, capsys) -> None:
    import csv

    from r2r_evaluation_report.core import build_synthetic_evaluation
    from r2r_evaluation_report.profile import legacy_profile

    sheet = build_synthetic_evaluation().sheet_evaluations[0]
    paths = {}
    for kind, column in (("measurement", "Status"), ("prediction", "prediction")):
        path = tmp_path / f"{kind}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Name", "Row", "Node", column])
            for row in sheet.joined:
                record = getattr(row, kind)
                writer.writerow([record.name, record.row, record.node, record.value])
        paths[kind] = path
    profile_path = tmp_path / "run.json"
    legacy_profile(str(paths["measurement"]), str(paths["prediction"])).save(profile_path)
    assert cli.main(["--profile", str(profile_path)]) == 0
    out = capsys.readouterr().out
    assert cli.PROFILE_EXPORT_MARKER in out and "[100%]" in out
    assert (tmp_path / "run.xlsx").is_file() and (tmp_path / "run-color-only.xlsx").is_file()
    assert (tmp_path / "run.profile.json").is_file()
    custom = tmp_path / "custom" / "report.xlsx"
    assert cli.main(["--profile", str(profile_path), "--output", str(custom)]) == 0
    assert custom.is_file()
