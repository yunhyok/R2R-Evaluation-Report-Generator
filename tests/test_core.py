from __future__ import annotations

import csv
import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from openpyxl import Workbook

CORE = Path(__file__).parents[1] / "src" / "r2r_evaluation_report" / "core.py"
SPEC = importlib.util.spec_from_file_location("r2r_evaluation_report.core", CORE)
assert SPEC and SPEC.loader
core = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = core
SPEC.loader.exec_module(core)


def _grid_rows(value_column: str, value_for, *, name: str = "SAM 11") -> list[dict[str, object]]:
    return [
        {
            "Name": name,
            "Row": f"{row:02d}",
            "Node": f"{node:02d}",
            value_column: value_for(row, node),
        }
        for row in range(1, 27)
        for node in range(1, 39)
    ]


def _csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def test_csv_contract_preserves_optional_fields_and_accepts_leading_zero_coordinates(
    tmp_path: Path,
) -> None:
    rows = _grid_rows("prediction", lambda _r, _n: "Normal")
    for row in rows:
        row.update(
            {
                "confidence": "0.8",
                "review_required": "false",
                "prob_Normal": "0.8",
                "prob_Open": "0.1",
                "prob_Short": "0.1",
                "provenance": "model-v1",
                "source": "run.csv",
            }
        )
    source = tmp_path / "prediction.csv"
    _csv(source, rows)
    dataset = core.parse_dataset(source, "prediction")
    record = dataset.sheets[0].records[0]
    assert dataset.sheets[0].source.encoding == "utf-8-sig"
    assert (record.row, record.node, record.prob_normal, record.provenance) == (
        1,
        1,
        0.8,
        "model-v1",
    )


@pytest.mark.parametrize(
    "change, expected",
    [
        (
            lambda rows: rows.__setitem__(1, {**rows[1], "Row": "01", "Node": "01"}),
            "duplicate coordinate",
        ),
        (lambda rows: rows.__setitem__(0, {**rows[0], "Row": "27"}), "outside Row 1..26"),
        (lambda rows: rows.pop(), "expected exactly 988"),
    ],
)
def test_coordinate_contract_rejects_duplicate_out_of_range_and_missing(
    tmp_path: Path, change, expected: str
) -> None:
    rows = _grid_rows("Status", lambda _r, _n: "Pass")
    change(rows)
    source = tmp_path / "measurement.csv"
    _csv(source, rows)
    with pytest.raises(core.DataContractError, match=expected):
        core.parse_dataset(source, "measurement")


def test_probability_contract_rejects_bad_sum(tmp_path: Path) -> None:
    rows = _grid_rows("prediction", lambda _r, _n: "Normal")
    for row in rows:
        row.update({"prob Normal": "0.2", "prob Open": "0.2", "prob Short": "0.2"})
    source = tmp_path / "bad.csv"
    _csv(source, rows)
    with pytest.raises(core.DataContractError, match="sum to 1"):
        core.parse_dataset(source, "prediction")


def test_mapping_and_evaluation_vectors_include_exclusion_and_binary_rules(tmp_path: Path) -> None:
    statuses = {
        (1, 1): "Pass",
        (1, 2): "No Active",
        (1, 3): "None",
        (1, 4): "Open",
        (1, 5): "Short",
        (1, 6): "No Gate Effect",
    }
    measurements = _grid_rows("Status", lambda r, n: statuses.get((r, n), "Pass"))
    predictions = _grid_rows("prediction", lambda r, n: "Open" if (r, n) == (1, 1) else "Normal")
    measurement_path = tmp_path / "measurement.csv"
    prediction_path = tmp_path / "prediction.csv"
    _csv(measurement_path, measurements)
    _csv(prediction_path, predictions)
    measured = core.parse_dataset(measurement_path, "measurement")
    predicted = core.parse_dataset(prediction_path, "prediction")
    result = core.evaluate(measured, predicted)
    assert not result.blocked
    evaluation = result.sheet_evaluations[0]
    assert len(evaluation.excluded) == 1
    assert evaluation.mapped_three_class.matrix[0][1] == 1  # Pass predicted Open
    assert evaluation.operational_binary.matrix == ((982, 1), (5, 0))
    assert evaluation.operational_binary.total == 988
    assert evaluation.mapped_three_class.macro_f1 is not None
    assert evaluation.mapped_three_class.per_class[1].f1 == 0
    assert result.overall_three_class.accuracy_ci95 is not None
    assert result.measurement_sources[0].worksheet == "CSV"
    assert result.status_mapping.binary["nogateeffect"] == "Fail"
    assert evaluation.yield_stats.total == 988
    assert evaluation.yield_stats.measurement_pass_count == 983
    assert evaluation.yield_stats.measurement_pass_ci95 is not None


def test_three_class_macro_f1_is_na_when_any_target_has_zero_support() -> None:
    metrics = core._metrics(core.TARGET_CLASSES, [("Normal", "Normal")], strict_macro=True)
    assert metrics.macro_f1 is None
    assert metrics.per_class[1].recall is None


def test_xlsx_discovery_finds_header_bearing_sheet_and_honours_selection(tmp_path: Path) -> None:
    workbook = Workbook()
    ignored = workbook.active
    ignored.title = "Notes"
    ignored.append(["free text"])
    sheet = workbook.create_sheet("SAM 11")
    sheet.append(["metadata"])
    sheet.append(["Name", "Row", "Node", "Status"])
    for row in _grid_rows("Status", lambda _r, _n: "Pass"):
        sheet.append(list(row.values()))
    source = tmp_path / "measurement.xlsx"
    workbook.save(source)
    info = core.discover_worksheets(source, "measurement")
    assert [(item.title, item.header_row) for item in info] == [("SAM 11", 2)]
    parsed = core.parse_dataset(source, "measurement", worksheets="SAM 11")
    assert len(parsed.sheets[0].records) == 988


def test_csv_is_split_and_evaluated_as_complete_name_sample_units(tmp_path: Path) -> None:
    measurement_rows = _grid_rows("Status", lambda _r, _n: "Pass", name="SAM 10")
    measurement_rows += _grid_rows("Status", lambda _r, _n: "Pass", name="SAM 11")
    prediction_rows = _grid_rows("prediction", lambda _r, _n: "Normal", name="SAM 10")
    prediction_rows += _grid_rows("prediction", lambda _r, _n: "Normal", name="SAM 11")
    measurement_path = tmp_path / "measurement.csv"
    prediction_path = tmp_path / "prediction.csv"
    _csv(measurement_path, measurement_rows)
    _csv(prediction_path, prediction_rows)
    measured = core.parse_dataset(measurement_path, "measurement")
    predicted = core.parse_dataset(prediction_path, "prediction")
    assert [sheet.title for sheet in measured.sheets] == ["SAM 10", "SAM 11"]
    assert [len(sheet.records) for sheet in measured.sheets] == [988, 988]
    result = core.evaluate(measured, predicted)
    assert not result.blocked
    assert result.overall_binary.total == 1976


def test_evaluation_blocks_unmatched_measurement_sample(tmp_path: Path) -> None:
    measurement_rows = _grid_rows("Status", lambda _r, _n: "Pass", name="SAM 10")
    measurement_rows += _grid_rows("Status", lambda _r, _n: "Pass", name="SAM 11")
    prediction_rows = _grid_rows("prediction", lambda _r, _n: "Normal", name="SAM 10")
    measurement_path = tmp_path / "measurement.csv"
    prediction_path = tmp_path / "prediction.csv"
    _csv(measurement_path, measurement_rows)
    _csv(prediction_path, prediction_rows)
    result = core.evaluate(
        core.parse_dataset(measurement_path, "measurement"),
        core.parse_dataset(prediction_path, "prediction"),
    )
    assert result.blocked
    assert "SAM 11" in result.mapping_errors[0]


def test_nondefault_status_needs_both_three_class_and_binary_rules(tmp_path: Path) -> None:
    measurement_rows = _grid_rows("Status", lambda _r, _n: "Review")
    prediction_rows = _grid_rows("prediction", lambda _r, _n: "Normal")
    measurement_path = tmp_path / "measurement.csv"
    prediction_path = tmp_path / "prediction.csv"
    _csv(measurement_path, measurement_rows)
    _csv(prediction_path, prediction_rows)
    measured = core.parse_dataset(measurement_path, "measurement")
    predicted = core.parse_dataset(prediction_path, "prediction")
    one_rule = core.evaluate(measured, predicted, status_rules={"Review": "Normal"})
    assert one_rule.blocked
    assert one_rule.unresolved_measurement_statuses == ("Review",)
    both_rules = core.evaluate(
        measured,
        predicted,
        status_rules={"Review": "Normal"},
        binary_status_rules={"Review": "Fail"},
    )
    assert not both_rules.blocked


def test_token_signature_normalises_yy_dates_sam_and_kg_but_requires_confirmation() -> None:
    measurement = core.ParsedSheet(
        "measurement",
        core.SourceMetadata("measurement.xlsx", "a", 0, 0, worksheet="20260701 SAM 05 6kgf"),
        (),
        {},
        "Measured sample",
    )
    good_prediction = core.ParsedSheet(
        "prediction",
        core.SourceMetadata("prediction.xlsx", "b", 0, 0, worksheet="260701-p3meemt-sam5-6kg"),
        (),
        {},
        "Prediction six",
    )
    other_kg = core.ParsedSheet(
        "prediction",
        core.SourceMetadata("prediction.xlsx", "b", 0, 0, worksheet="260701 SAM 05 8kgf"),
        (),
        {},
        "Prediction eight",
    )
    audit = core.propose_mappings((measurement,), (good_prediction, other_kg))
    proposal = audit.proposals[0]
    assert (proposal.method, proposal.prediction_sheet, proposal.requires_confirmation) == (
        "signature",
        "Prediction six",
        True,
    )
    assert audit.unmatched_measurement_sheets == ("Measured sample",)


def test_token_signature_accepts_real_underscore_sample_names() -> None:
    assert core._signature("20260619-P3MEEMT(1-3)_7kgf_100_sam1") == (
        "date:260619",
        "kg:7",
        "sam:1",
    )
    assert core._signature("260619 p3meet ac 7kg 100mm, SAM 1") == (
        "date:260619",
        "kg:7",
        "sam:1",
    )


def test_join_uses_coordinates_after_sample_mapping_not_raw_names() -> None:
    source_a = core.SourceMetadata("m.csv", "a", 0, 0, worksheet="CSV")
    source_b = core.SourceMetadata("p.csv", "b", 0, 0, worksheet="CSV")
    measurement = core.ParsedSheet(
        "measurement",
        source_a,
        (core.R2RRecord("20260701_original", 1, 1, "Pass"),),
        {},
        "20260701_original",
    )
    prediction = core.ParsedSheet(
        "prediction",
        source_b,
        (core.R2RRecord("260701 normalized", 1, 1, "Normal"),),
        {},
        "260701 normalized",
    )
    joined = core.join_records(measurement, prediction)
    assert len(joined) == 1
    assert joined[0].measurement is not None
    assert joined[0].prediction is not None


def test_mapping_suggestions_never_reuse_one_prediction() -> None:
    source = core.SourceMetadata("source.csv", "a", 0, 0, worksheet="CSV")
    measurements = (
        core.ParsedSheet("measurement", source, (), {}, "alpha device one"),
        core.ParsedSheet("measurement", source, (), {}, "alpha device two"),
    )
    predictions = (core.ParsedSheet("prediction", source, (), {}, "alpha device"),)
    audit = core.propose_mappings(measurements, predictions)
    assert len(audit.proposals) == 1
    assert len({item.prediction_sheet for item in audit.proposals}) == len(audit.proposals)


def test_evaluation_audit_records_confirmed_mapping_and_prediction_only() -> None:
    measurement_source = core.SourceMetadata("m.csv", "a", 0, 0, worksheet="CSV")
    prediction_source = core.SourceMetadata("p.csv", "b", 0, 0, worksheet="CSV")
    measurement = core.ParsedSheet(
        "measurement",
        measurement_source,
        (core.R2RRecord("20260701_sample_sam1", 1, 1, "Pass"),),
        {},
        "20260701_sample_sam1",
    )
    prediction = core.ParsedSheet(
        "prediction",
        prediction_source,
        (core.R2RRecord("260701 SAM 1", 1, 1, "Normal"),),
        {},
        "260701 SAM 1",
    )
    extra = core.ParsedSheet(
        "prediction",
        prediction_source,
        (core.R2RRecord("260701 SAM 99", 1, 1, "Normal"),),
        {},
        "260701 SAM 99",
    )
    measured = core.ParsedDataset("measurement", "m.csv", (measurement,))
    predicted = core.ParsedDataset("prediction", "p.csv", (prediction, extra))
    proposed = core.preflight(measured, predicted).proposals[0]
    result = core.evaluate(
        measured,
        predicted,
        (replace(proposed, requires_confirmation=False),),
    )
    assert not result.blocked
    assert not result.mappings.proposals[0].requires_confirmation
    assert result.mappings.unmatched_measurement_sheets == ()
    assert result.mappings.prediction_only_sheets == ("260701 SAM 99",)


def test_unknown_status_and_prediction_block_scoring(tmp_path: Path) -> None:
    measurement_rows = _grid_rows("Status", lambda r, n: "Mystery" if (r, n) == (1, 1) else "Pass")
    prediction_rows = _grid_rows(
        "prediction", lambda r, n: "Alien" if (r, n) == (1, 2) else "Normal"
    )
    measurement_path = tmp_path / "m.csv"
    prediction_path = tmp_path / "p.csv"
    _csv(measurement_path, measurement_rows)
    _csv(prediction_path, prediction_rows)
    result = core.evaluate(
        core.parse_dataset(measurement_path, "measurement"),
        core.parse_dataset(prediction_path, "prediction"),
    )
    assert result.blocked
    assert result.unresolved_measurement_statuses == ("Mystery",)
    assert result.unknown_predictions == ("Alien",)
    assert not result.sheet_evaluations


def test_synthetic_evaluation_is_deterministic_and_contract_complete() -> None:
    first = core.build_synthetic_evaluation()
    second = core.build_synthetic_evaluation()
    assert not first.blocked
    assert first.overall_three_class == second.overall_three_class
    assert first.overall_three_class.total < 988  # No Gate Effect remains audited as an exclusion.
    assert first.sheet_evaluations[0].confidence_review.probability_count == 988
