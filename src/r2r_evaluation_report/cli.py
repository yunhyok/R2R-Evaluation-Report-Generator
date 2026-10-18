"""Command-line entry points used by the GUI, CI, and installer verification."""

from __future__ import annotations

import argparse
import tempfile
from collections.abc import Sequence
from pathlib import Path

from . import __version__

SELF_TEST_MARKER = "R2R_EVALUATION_REPORT_SELF_TEST_OK"
SYNTHETIC_EXPORT_MARKER = "R2R_EVALUATION_REPORT_SYNTHETIC_EXPORT_OK"
PROFILE_EXPORT_MARKER = "R2R_EVALUATION_REPORT_PROFILE_EXPORT_OK"


def _write_synthetic(output: Path) -> None:
    from .core import build_synthetic_evaluation
    from .workbook import generate_workbook, verify_workbook

    evaluation = build_synthetic_evaluation()
    if evaluation.blocked or not evaluation.sheet_evaluations:
        raise RuntimeError("The deterministic synthetic evaluation is unexpectedly blocked.")
    generate_workbook(output, evaluation)
    verify_workbook(output)


_VISUAL_PROBABILITIES = {
    "Good": (0.9, 0.05, 0.05),
    "Bad": (0.05, 0.9, 0.05),
    "Open": (0.05, 0.05, 0.9),
}
SYNTHETIC_SWEEP_VOLTAGES = tuple(float(v) for v in range(-20, 21, 2))
"""Gate voltages of the synthetic measurement sweep (21 points, -20 V .. +20 V)."""


def _synthetic_sweep(status: str, voltages) -> tuple[str, ...]:
    """A deterministic p-type transfer curve (or a flat/open/short trace) per legacy status."""
    import math

    key = status.casefold()
    values = []
    for voltage in voltages:
        if key == "pass":
            current = 5e-9 + 1e-6 / (1.0 + math.exp((voltage + 5.0) / 2.0))
        elif key == "no active":
            current = 2e-8 + 1e-8 / (1.0 + math.exp((voltage + 5.0) / 2.0))
        elif key == "no gate effect":
            current = 3e-7
        elif key == "open":
            current = 1e-11
        elif key == "short":
            current = 1e-5
        else:  # None: negative noise-level current, the converter's cond1 case
            current = -2e-9
        values.append(f"{current:.6e}")
    return tuple(values)


def _write_synthetic_visual_predictions(path: Path, joined) -> None:
    """R2R-Machine-Learning ``visual_3class`` export derived from the synthetic statuses.

    Same column layout as the real tool (``prob_Good / prob_Bad / prob_Open``), a
    controlled error pattern, and lower-case ``Good / Bad / Open`` spellings so the
    self-test exercises the case-insensitive match against the ``optical_3`` scheme.
    """
    import csv

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "name",
                "row",
                "node",
                "prediction",
                "confidence",
                "review_required",
                "prob_Good",
                "prob_Bad",
                "prob_Open",
            ]
        )
        for index, row in enumerate(joined):
            record = row.measurement
            status = record.value.casefold()
            verdict = "Good" if status == "pass" else "Open" if status == "open" else "Bad"
            if index % 19 == 0:
                verdict = "Bad" if verdict == "Good" else "Good"
            probabilities = _VISUAL_PROBABILITIES[verdict]
            writer.writerow(
                [
                    record.name,
                    record.row,
                    record.node,
                    verdict,
                    "0.9",
                    str(index % 23 == 0).lower(),
                    *probabilities,
                ]
            )


def _write_synthetic_profile(directory: Path) -> Path:
    """Round-trip the synthetic evaluation through the profile path (schemes + scipy).

    Besides the legacy measurement / electrical-prediction pair, the profile carries
    a visual-label ML prediction set (comparison group ``optical_ml``) so that the
    packaged self-test covers the Good / Bad / Open path end to end.
    """
    import csv

    from .core import build_synthetic_evaluation
    from .profile import (
        CellSpec,
        ComparisonSpec,
        DatasetSpec,
        ReportProfile,
        evaluate_profile,
        legacy_profile,
    )
    from .schemes import load_registry
    from .workbook import generate_workbook_pair, verify_workbook

    evaluation = build_synthetic_evaluation()
    sheet = evaluation.sheet_evaluations[0]
    paths = {}
    for kind, column in (("measurement", "Status"), ("prediction", "prediction")):
        path = directory / f"synthetic-{kind}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            # The measurement file carries the converter's sweep columns too, so the
            # self-test renders (and the packaged build bundles) the transfer-curve grid.
            sweep = SYNTHETIC_SWEEP_VOLTAGES if kind == "measurement" else ()
            writer.writerow(["Name", "Row", "Node", column, *(f"{v:.5f}" for v in sweep)])
            for row in sheet.joined:
                record = getattr(row, kind)
                currents = _synthetic_sweep(record.value, sweep) if sweep else ()
                writer.writerow([record.name, record.row, record.node, record.value, *currents])
        paths[kind] = path
    visual_path = directory / "synthetic-visual-ml.csv"
    _write_synthetic_visual_predictions(visual_path, sheet.joined)
    registry = load_registry()
    base = legacy_profile(str(paths["measurement"]), str(paths["prediction"]), registry=registry)
    legacy = registry.scheme("legacy_electrical").labels
    optical = registry.scheme("optical_3").labels
    profile = ReportProfile(
        (
            *base.datasets,
            DatasetSpec(
                "visual_ml",
                str(visual_path),
                "optical_ml",
                "optical_3",
                title="Visual ML (Good/Bad/Open)",
            ),
        ),
        (
            *base.comparisons,
            ComparisonSpec(
                "association",
                "association",
                "measurement",
                "prediction",
                "Raw status vs prediction (association)",
                cells=(CellSpec("None x Open", ("None",), ("Open",)),),
            ),
            ComparisonSpec(
                "visual_binary",
                "reference",
                "measurement",
                "visual_ml",
                "Operational binary vs visual-label ML (Pass / Fail)",
                registry.preset("legacy_to_binary").resolved_rules(legacy),
                registry.preset("optical_to_binary").resolved_rules(optical),
                ("Pass", "Fail"),
                positive="Fail",
                strict_macro=False,
                preset_a="legacy_to_binary",
                preset_b="optical_to_binary",
            ),
            ComparisonSpec(
                "visual_association",
                "association",
                "measurement",
                "visual_ml",
                "Raw status vs visual-label ML (association)",
                cells=(CellSpec("Short x BAD", ("Short",), ("BAD",)),),
            ),
        ),
        options=base.options,
    )
    result = evaluate_profile(profile, registry=registry)
    if result.blocked:
        raise RuntimeError("Synthetic profile evaluation is unexpectedly blocked.")
    output = directory / "synthetic-profile-report.xlsx"
    with_codes, color_only = generate_workbook_pair(output, result)
    verify_workbook(with_codes)
    verify_workbook(color_only)
    return with_codes


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
        profile_output = _write_synthetic_profile(Path(directory))
        print(
            f"{SELF_TEST_MARKER} version={__version__} workbook_bytes={output.stat().st_size} "
            f"profile_workbook_bytes={profile_output.stat().st_size}"
        )
    return 0


def run_profile(profile_path: Path, output: Path | None) -> int:
    """Headless generation from a saved report profile (the wizard's JSON)."""
    from .profile import ReportProfile, load_datasets
    from .wizard_backend import generate

    profile = ReportProfile.load(profile_path)
    destination = output or profile_path.with_suffix(".xlsx")
    datasets = load_datasets(profile)

    def progress(value: int, text: str) -> None:
        print(f"[{value:3d}%] {text}")

    with_codes, color_only = generate(profile, datasets, destination, progress=progress)
    print(f"{PROFILE_EXPORT_MARKER} path={with_codes}")
    if color_only is not None:
        print(f"{PROFILE_EXPORT_MARKER} color_only={color_only}")
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
    operation.add_argument(
        "--profile",
        metavar="PROFILE.json",
        type=Path,
        help="Generate a report headlessly from a saved report profile.",
    )
    operation.add_argument(
        "--legacy-ui",
        action="store_true",
        help="Open the v0.4 two-input screen instead of the step wizard.",
    )
    parser.add_argument(
        "--output",
        metavar="OUTPUT.xlsx",
        type=Path,
        help="Destination workbook for --profile (default: next to the profile).",
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
    if args.profile:
        output = args.output.expanduser().resolve() if args.output else None
        return run_profile(args.profile.expanduser().resolve(), output)
    if args.legacy_ui:
        from .gui import run_gui

        return run_gui(smoke_test=args.gui_smoke_test)

    from .wizard import run_wizard

    return run_wizard(smoke_test=args.gui_smoke_test)


if __name__ == "__main__":
    raise SystemExit(main())
