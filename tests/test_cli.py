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
