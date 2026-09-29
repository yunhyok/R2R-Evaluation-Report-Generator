"""Reproduce the historical acceptance vectors plus v0.3.0 paired outputs."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import replace
from pathlib import Path

from r2r_evaluation_report.core import evaluate, parse_dataset, preflight
from r2r_evaluation_report.workbook import generate_workbook_pair, verify_workbook

EXPECTED_THREE = ((8806, 193, 37), (0, 0, 0), (0, 0, 0))
EXPECTED_BINARY = ((5117, 178), (4359, 226))
EXPECTED_EXPANDED = ((9476, 202, 202), (0, 0, 0), (0, 0, 0))
EXPECTED_VALUES = {
    "accuracy": 0.5407894736842105,
    "balanced_accuracy": 0.5078372736980526,
    "macro_f1": 0.39172170244309334,
    "weighted_f1": 0.4133610640421923,
    "measurement_pass_rate": 0.5359311740890689,
    "prediction_pass_rate": 0.9591093117408906,
}


def _close(actual: float | None, expected: float) -> None:
    if actual is None or not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12):
        raise AssertionError(f"Expected {expected!r}, received {actual!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("measurement", type=Path)
    parser.add_argument("prediction", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--confirm-proposed-mappings",
        action="store_true",
        help="Explicitly approve the deterministic date/kg/SAM proposals for this acceptance run.",
    )
    args = parser.parse_args()
    measurement = parse_dataset(args.measurement, "measurement")
    prediction = parse_dataset(args.prediction, "prediction")
    audit = preflight(measurement, prediction)
    if any(proposal.requires_confirmation for proposal in audit.proposals):
        if not args.confirm_proposed_mappings:
            raise SystemExit("Mapping confirmation is required; rerun with the explicit flag.")
    proposals = tuple(replace(item, requires_confirmation=False) for item in audit.proposals)
    result = evaluate(measurement, prediction, proposals)
    if result.blocked:
        raise AssertionError(
            f"Acceptance evaluation blocked: mappings={result.mapping_errors}, "
            f"statuses={result.unresolved_measurement_statuses}, "
            f"predictions={result.unknown_predictions}"
        )
    assert len(measurement.sheets) == 10
    assert sum(len(sheet.records) for sheet in measurement.sheets) == 9_880
    assert len(prediction.sheets) == 11
    assert sum(len(sheet.records) for sheet in prediction.sheets) == 10_868
    assert len(result.sheet_evaluations) == 10
    assert len(audit.prediction_only_sheets) == 1
    assert sum(len(sheet.excluded) for sheet in result.sheet_evaluations) == 844
    assert result.overall_three_class is not None
    assert result.overall_binary is not None
    assert result.overall_expanded_normal is not None
    assert result.overall_yield is not None
    assert result.overall_three_class.matrix == EXPECTED_THREE
    assert result.overall_three_class.total == 9_036
    assert result.overall_three_class.macro_f1 is None
    assert result.overall_binary.matrix == EXPECTED_BINARY
    assert result.overall_binary.total == 9_880
    assert result.overall_expanded_normal.matrix == EXPECTED_EXPANDED
    assert result.overall_expanded_normal.total == 9_880
    expanded_normal = next(
        item for item in result.overall_expanded_normal.per_class if item.label == "Normal"
    )
    _close(expanded_normal.recall, 9476 / 9880)
    assert result.overall_expanded_normal.macro_f1 is None
    for field, expected in EXPECTED_VALUES.items():
        source = result.overall_yield if field.endswith("pass_rate") else result.overall_binary
        _close(getattr(source, field), expected)
    fail = next(item for item in result.overall_binary.per_class if item.label == "Fail")
    _close(fail.recall, 0.049291166848418756)
    _close(fail.f1, 0.09059931850070155)
    _, color_only = generate_workbook_pair(args.output, result)
    verify_workbook(args.output)
    verify_workbook(color_only)
    evidence = {
        "output": str(args.output.resolve()),
        "color_only_output": str(color_only.resolve()),
        "measurement_sha256": result.measurement_sources[0].sha256,
        "prediction_sha256": result.prediction_sources[0].sha256,
        "measurement_samples": len(measurement.sheets),
        "prediction_samples": len(prediction.sheets),
        "prediction_only": list(audit.prediction_only_sheets),
        "three_class_matrix": result.overall_three_class.matrix,
        "binary_matrix": result.overall_binary.matrix,
        "expanded_normal_matrix": result.overall_expanded_normal.matrix,
        **EXPECTED_VALUES,
        "fail_recall": fail.recall,
        "fail_f1": fail.f1,
    }
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    print("REAL_ACCEPTANCE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
