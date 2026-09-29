"""Command-line entry points used by the GUI, CI, and installer verification."""

from __future__ import annotations

import argparse
import tempfile
from collections.abc import Sequence
from pathlib import Path

from . import __version__

SELF_TEST_MARKER = "R2R_EVALUATION_REPORT_SELF_TEST_OK"
SYNTHETIC_EXPORT_MARKER = "R2R_EVALUATION_REPORT_SYNTHETIC_EXPORT_OK"


def _write_synthetic(output: Path) -> None:
    from .core import build_synthetic_evaluation
    from .workbook import generate_workbook, verify_workbook

    evaluation = build_synthetic_evaluation()
    if evaluation.blocked or not evaluation.sheet_evaluations:
        raise RuntimeError("The deterministic synthetic evaluation is unexpectedly blocked.")
    generate_workbook(output, evaluation)
    verify_workbook(output)


def run_self_test() -> int:
    from .core import build_synthetic_evaluation
    from .workbook import generate_workbook_pair

    with tempfile.TemporaryDirectory(prefix="r2r-evaluation-report-self-test-") as directory:
        output = Path(directory) / "synthetic-evaluation-report.xlsx"
        _write_synthetic(output)
        if output.stat().st_size <= 0:
            raise RuntimeError("Synthetic workbook is empty.")
        for kind in ("measurement", "prediction"):
            generate_workbook_pair(
                Path(directory) / f"{kind}.xlsx", build_synthetic_evaluation(kind)
            )
        print(f"{SELF_TEST_MARKER} version={__version__} workbook_bytes={output.stat().st_size}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="R2R Evaluation Report Generator")
    parser.add_argument("--version", action="version", version=__version__)
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--self-test", action="store_true")
    operation.add_argument("--gui-smoke-test", action="store_true")
    operation.add_argument(
        "--synthetic-export",
        metavar="OUTPUT.xlsx",
        type=Path,
        help="Generate a deterministic synthetic workbook for package validation.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.self_test:
        return run_self_test()
    if args.synthetic_export:
        output = args.synthetic_export.expanduser().resolve()
        _write_synthetic(output)
        print(f"{SYNTHETIC_EXPORT_MARKER} path={output}")
        return 0

    from .gui import run_gui

    return run_gui(smoke_test=args.gui_smoke_test)


if __name__ == "__main__":
    raise SystemExit(main())
