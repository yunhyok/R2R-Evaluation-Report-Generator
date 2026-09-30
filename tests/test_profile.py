"""Label-scheme registry, association statistics and profile-driven evaluation."""

from __future__ import annotations

import csv
import math
from pathlib import Path

import pytest

from r2r_evaluation_report import association as assoc
from r2r_evaluation_report import core, profile, schemes

GRID = [(row, node) for row in range(1, 27) for node in range(1, 39)]
LEGACY = ("Pass", "No Active", "None", "Open", "Short", "No Gate Effect")
E5 = ("E-Normal", "E-NoActive", "E-Open", "E-Short", "E-Invalid")
OPTICAL = ("GOOD", "BAD", "OPEN")


def _csv(path: Path, rows: list[dict[str, object]]) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _rows(name: str, column: str, values, extra=None) -> list[dict[str, object]]:
    return [
        {"Name": name, "Row": row, "Node": node, column: values(index, row, node), **(extra or {})}
        for index, (row, node) in enumerate(GRID)
    ]


# ------------------------------------------------------------------------- schemes


def test_bundled_registry_reproduces_legacy_hardcoded_rules() -> None:
    registry = schemes.load_registry(user_path="/nonexistent/label_schemes.json")
    legacy = registry.scheme("legacy_electrical").labels
    for preset_id, reference in (
        ("legacy_to_3class", core._DEFAULT_STATUS_RULES),
        ("legacy_to_binary", core._DEFAULT_BINARY_STATUS_RULES),
        ("legacy_to_expanded_normal", core._DEFAULT_EXPANDED_NORMAL_STATUS_RULES),
    ):
        resolved = registry.preset(preset_id).resolved_rules(legacy)
        assert {core._normalise(k): v for k, v in resolved.items()} == dict(reference)
    assert registry.identify(["e-open", "E-Normal"]) == ("electrical_e5",)
    assert registry.identify(["Pass", "GOOD"]) == ()
    assert registry.preset("e5_to_binary").map("E-Invalid") == schemes.EXCLUDE
    assert registry.preset("e5_to_binary").map("E-Short") == "Fail"
    assert registry.preset("e5_to_binary").map("E-Normal") == "Pass"


def test_user_registry_overlays_bundled_and_rejects_bad_targets(tmp_path: Path) -> None:
    user = tmp_path / "label_schemes.json"
    user.write_text(
        '{"schema_version": 1, "schemes": {"custom": {"labels": ["A", "B"]}},'
        ' "presets": {"custom_bin": {"source": "custom", "targets": ["Pass", "Fail"],'
        ' "rules": {"A": "Pass", "*": "Fail"}}}}',
        encoding="utf-8",
    )
    registry = schemes.load_registry(user_path=user)
    assert "legacy_electrical" in registry.schemes and "custom" in registry.schemes
    assert registry.preset("custom_bin").map("b") == "Fail"
    saved = schemes.save_registry(registry, tmp_path / "out" / "r.json")
    assert schemes.load_registry_file(saved).presets.keys() == registry.presets.keys()
    with pytest.raises(schemes.SchemeError):
        schemes.MappingPreset("bad", ("Pass",), {"A": "Nope"})
    with pytest.raises(schemes.SchemeError):
        schemes.LabelScheme("dup", ("A", "a"))


# --------------------------------------------------------------------- association


def test_association_matches_agresti_physicians_health_study() -> None:
    # Agresti (2013) Table 2.3: placebo 189/10845, aspirin 104/10933 (MI yes/no).
    table = assoc.ContingencyTable(
        ("placebo", "aspirin"), ("MI", "no MI"), ((189, 10845), (104, 10933))
    )
    chi = assoc.chi_square(table)
    assert chi.statistic == pytest.approx(25.01, abs=0.01)
    assert chi.dof == 1 and chi.p_value < 1e-6 and not chi.cochran_warning
    assert chi.cramers_v == pytest.approx(math.sqrt(25.01 / table.total), abs=1e-4)
    assert 0 < chi.cramers_v_corrected <= chi.cramers_v
    cell = assoc.collapse(table, ["placebo"], ["MI"], "placebo x MI")
    assert cell.odds_ratio == pytest.approx(1.832, abs=0.001)
    assert cell.odds_ratio_ci95[0] == pytest.approx(1.44, abs=0.01)
    assert cell.odds_ratio_ci95[1] == pytest.approx(2.33, abs=0.01)
    assert cell.relative_risk == pytest.approx(1.818, abs=0.001)
    assert cell.phi == pytest.approx(chi.cramers_v, abs=1e-6)
    assert not cell.corrected and cell.fisher_p < 1e-6
    residuals = assoc.adjusted_residuals(table)
    assert residuals[0][0] == pytest.approx(5.0, abs=0.01)
    assert residuals[0][0] == pytest.approx(-residuals[0][1], abs=1e-9)
    theil = assoc.theil_u(table)
    assert 0 < theil.u_b_given_a < 0.01 and 0 < theil.u_a_given_b < 0.01


def test_agreement_kappa_pa_na_mcc_and_majority_baseline() -> None:
    table = assoc.ContingencyTable(("Pass", "Fail"), ("Pass", "Fail"), ((20, 5), (10, 15)))
    result = assoc.agreement(table, positive="Fail")
    assert result.observed_agreement == pytest.approx(0.7)
    assert result.expected_agreement == pytest.approx(0.5)
    assert result.kappa == pytest.approx(0.4)
    assert result.positive_agreement == pytest.approx(2 * 15 / (2 * 15 + 5 + 10))
    assert result.negative_agreement == pytest.approx(2 * 20 / (2 * 20 + 5 + 10))
    assert result.mcc == pytest.approx(0.40824829)
    assert result.majority_baseline == pytest.approx(0.5)
    # Cicchetti–Feinstein paradox: very high agreement, tiny kappa, PA exposes it.
    skewed = assoc.ContingencyTable(("N", "P"), ("N", "P"), ((950, 20), (25, 5)))
    paradox = assoc.agreement(skewed, positive="P")
    assert paradox.observed_agreement > 0.95 and paradox.kappa < 0.2
    assert paradox.positive_agreement < 0.25 and paradox.negative_agreement > 0.97
    with pytest.raises(ValueError):
        assoc.agreement(assoc.ContingencyTable(("a",), ("b",), ((1,),)))


def test_two_by_two_zero_cell_uses_haldane_correction_and_holm_orders() -> None:
    cell = assoc.two_by_two("zero", 0, 10, 10, 10)
    assert cell.corrected and cell.odds_ratio == pytest.approx((0.5 * 10.5) / (10.5 * 10.5))
    assert cell.relative_risk == 0.0 and cell.yule_q == -1.0
    assert assoc.holm([0.01, 0.04, 0.03, None]) == (0.03, 0.06, 0.06, None)
    empty = assoc.chi_square(assoc.ContingencyTable(("a",), ("b",), ((3,),)))
    assert empty.statistic is None and empty.cramers_v is None


# ---------------------------------------------------------------- parsing adapters


def test_label_kind_reads_imagemarker_csv_and_custom_grid(tmp_path: Path) -> None:
    rows = [
        {"name": "sam1_x", "row": r, "node": n, "label": OPTICAL[(r + n) % 3]}
        for r in range(1, 3)
        for n in range(1, 5)
    ]
    source = _csv(tmp_path / "marker.csv", rows)
    dataset = core.parse_dataset(source, "label", grid=core.Grid(2, 4))
    assert dataset.grid.size == 8 and dataset.raw_labels == ("OPEN", "GOOD", "BAD")
    assert dataset.sheets[0].records[0].value == "OPEN"
    with pytest.raises(core.DataContractError, match="exactly 988"):
        core.parse_dataset(source, "label")


def test_label_kind_reads_inspector_matrix_and_long_exports(tmp_path: Path) -> None:
    matrix_rows = [
        {
            "image_path": f"C:/slices/20260731_7kgf_sam1_rgb_{r}_{n}.png",
            "image_sha256": "abc",
            "agreement": "full",
            "openai:gpt-x": OPTICAL[(r * n) % 3],
            "openai:gpt-x actual_model_id": "gpt-x-2026",
            "openai:gpt-x reason": "ok",
            "google:gemini-y": "GOOD",
            "google:gemini-y actual_model_id": "gemini-y",
            "google:gemini-y reason": "",
        }
        for r in range(1, 27)
        for n in range(1, 39)
    ]
    matrix = _csv(tmp_path / "matrix.csv", matrix_rows)
    headers = list(matrix_rows[0])
    assert core.inspector_model_columns(headers) == ("openai:gpt-x", "google:gemini-y")
    assert core.discover_worksheets(matrix, "label")[0].title == "CSV"
    with pytest.raises(core.DataContractError, match="choose the Inspector model column"):
        core.parse_dataset(matrix, "label")
    dataset = core.parse_dataset(matrix, "label", model_column="openai:gpt-x")
    assert dataset.sheets[0].title == "20260731_7kgf_sam1"
    assert set(dataset.raw_labels) == set(OPTICAL)
    other = core.parse_dataset(matrix, "label", model_column="google:gemini-y")
    assert other.raw_labels == ("GOOD",)
    with pytest.raises(core.DataContractError, match="kind='label'"):
        core.parse_dataset(matrix, "prediction", model_column="openai:gpt-x")

    long_rows = []
    for r, n in GRID:
        for provider, model in (("openai", "gpt-x"), ("google", "gemini-y")):
            long_rows.append(
                {
                    "task_id": f"{provider}-{r}-{n}",
                    "image_path": f"/data/20260731_7kgf_sam1_rgb_{r}_{n}.png",
                    "image_sha256": "abc",
                    "provider": provider,
                    "model_id": model,
                    "actual_model_id": model,
                    "agreement": "full",
                    "status": "succeeded" if provider == "openai" or (r, n) != (1, 1) else "failed",
                    "verdict": "BAD" if provider == "openai" else "GOOD",
                    "reason": "",
                }
            )
    long_csv = _csv(tmp_path / "long.csv", long_rows)
    assert core.inspector_model_columns(list(long_rows[0])) == ("verdict",)
    parsed = core.parse_dataset(long_csv, "label", model_column="openai:gpt-x")
    assert parsed.raw_labels == ("BAD",) and len(parsed.sheets[0].records) == 988
    with pytest.raises(core.DataContractError, match="expected exactly 988"):
        core.parse_dataset(long_csv, "label", model_column="google:gemini-y")


# ------------------------------------------------------------------------ profiles


@pytest.fixture
def legacy_files(tmp_path: Path) -> tuple[Path, Path]:
    def status(index, _r, _n):
        return LEGACY[index % 6]

    def prediction(index, _r, _n):
        mapped = core._DEFAULT_STATUS_RULES[core._normalise(LEGACY[index % 6])]
        predicted = "Normal" if mapped in {"Normal", "Exclude"} else mapped
        if index % 17 == 0:
            predicted = "Open" if predicted == "Normal" else "Normal"
        return predicted

    measurement = _csv(tmp_path / "measurement.csv", _rows("SAM 11", "Status", status))
    prediction_csv = _csv(tmp_path / "prediction.csv", _rows("SAM 11", "prediction", prediction))
    return measurement, prediction_csv


def _metrics_equal(left: core.Metrics, right: core.Metrics) -> None:
    assert left.labels == right.labels and left.matrix == right.matrix
    assert left.accuracy == right.accuracy and left.macro_f1 == right.macro_f1
    assert left.weighted_f1 == right.weighted_f1
    assert left.balanced_accuracy == right.balanced_accuracy
    assert left.per_class == right.per_class


def test_legacy_profile_reproduces_v04_evaluate(legacy_files: tuple[Path, Path]) -> None:
    measurement, prediction = legacy_files
    baseline = core.evaluate(
        core.parse_dataset(measurement, "measurement"),
        core.parse_dataset(prediction, "prediction"),
    )
    assert not baseline.blocked
    spec = profile.legacy_profile(str(measurement), str(prediction))
    result = profile.evaluate_profile(spec)
    assert not result.blocked, result.errors
    by_id = {item.spec.id: item for item in result.comparisons}
    _metrics_equal(by_id["three_class"].overall.metrics, baseline.overall_three_class)
    _metrics_equal(by_id["binary"].overall.metrics, baseline.overall_binary)
    _metrics_equal(by_id["expanded_normal"].overall.metrics, baseline.overall_expanded_normal)
    sheet = baseline.sheet_evaluations[0]
    _metrics_equal(by_id["three_class"].per_sample["SAM 11"].metrics, sheet.mapped_three_class)
    assert by_id["three_class"].overall.excluded == len(
        [item for item in sheet.excluded if item.measurement and item.prediction]
    )
    agreement = by_id["binary"].overall.agreement
    assert agreement.kappa is not None and agreement.majority_baseline is not None
    assert by_id["three_class"].overall.raw_table.labels_a == tuple(
        sorted(LEGACY, key=str.casefold)
    ) or set(by_id["three_class"].overall.raw_table.labels_a) == set(LEGACY)


def test_profile_round_trips_json_and_validates_ids(tmp_path: Path) -> None:
    spec = profile.legacy_profile("m.csv", "p.csv")
    spec = profile.ReportProfile(
        spec.datasets,
        (
            *spec.comparisons,
            profile.ComparisonSpec(
                "assoc",
                "association",
                "measurement",
                "prediction",
                cells=(profile.CellSpec("None x Open", ("None",), ("Open",)),),
            ),
        ),
        (profile.AlignmentSpec("SAM 11", {"measurement": "SAM 11", "prediction": "sam11"}),),
        profile.ProfileOptions(title="t", spatial_maps=False),
    )
    saved = spec.save(tmp_path / "profile.json")
    loaded = profile.ReportProfile.load(saved)
    assert loaded == spec
    assert loaded.comparisons[0].categories == ("Normal", "Open", "Short")
    with pytest.raises(profile.ProfileError):
        profile.ComparisonSpec("x", "reference", "a", "a")
    with pytest.raises(profile.ProfileError):
        profile.ReportProfile(
            spec.datasets, (profile.ComparisonSpec("x", "reference", "measurement", "ghost"),)
        )


def test_three_dataset_association_flags_unmapped_and_reports_cells(tmp_path: Path) -> None:
    def electrical(index, _r, _n):
        return E5[index % 5]

    def optical(index, _r, _n):
        # BAD co-occurs with E-Invalid and E-Short more often than chance.
        if E5[index % 5] in {"E-Invalid", "E-Short"}:
            return "BAD" if index % 3 else "GOOD"
        return "OPEN" if E5[index % 5] == "E-Open" and index % 2 else "GOOD"

    def ml(index, _r, _n):
        return {"E-Normal": "Normal", "E-NoActive": "Normal", "E-Open": "Open"}.get(
            E5[index % 5], "Short"
        )

    measurement = _csv(tmp_path / "e5.csv", _rows("20260731_7kgf_sam1", "Status", electrical))
    human = _csv(tmp_path / "human.csv", _rows("20260731_sam1_slices", "label", optical))
    model = _csv(tmp_path / "ml.csv", _rows("20260731_7kgf_sam1", "prediction", ml))
    registry = schemes.load_registry(user_path="/nonexistent")
    e5_labels = registry.scheme("electrical_e5").labels
    datasets = (
        profile.DatasetSpec("elec", str(measurement), "electrical_gt", "electrical_e5"),
        profile.DatasetSpec("human", str(human), "optical_human", "optical_3"),
        profile.DatasetSpec("ml", str(model), "electrical_ml", "ml_3class"),
    )
    comparisons = (
        profile.ComparisonSpec(
            "self",
            "reference",
            "elec",
            "ml",
            mapping_a=registry.preset("e5_to_3class").resolved_rules(e5_labels),
            mapping_b={label: label for label in ("Normal", "Open", "Short")},
            categories=("Normal", "Open", "Short"),
        ),
        profile.ComparisonSpec(
            "cross",
            "association",
            "elec",
            "human",
            cells=(
                profile.CellSpec("E-Invalid x BAD", ("E-Invalid",), ("BAD",)),
                profile.CellSpec("E-Short x BAD", ("E-Short",), ("BAD",)),
                profile.CellSpec("E-Open x OPEN", ("E-Open",), ("OPEN",)),
            ),
        ),
        profile.ComparisonSpec(
            "cross_binary",
            "association",
            "elec",
            "human",
            mapping_a=registry.preset("e5_to_binary").resolved_rules(e5_labels),
            mapping_b=registry.preset("optical_to_binary").resolved_rules(OPTICAL),
            positive="Fail",
        ),
    )
    # The human file shares date+sam tokens only (signature match), so auto alignment
    # (exact match only) leaves it out; a confirmed alignment must be supplied.
    spec = profile.ReportProfile(datasets, comparisons)
    loaded = profile.load_datasets(spec)
    proposals = profile.propose_alignments(spec, loaded)
    assert [item.dataset_id for item in proposals] == ["human", "ml"]
    assert proposals[0].proposals[0].requires_confirmation
    assert not proposals[1].proposals[0].requires_confirmation
    partial = profile.evaluate_profile(spec, loaded, registry=registry)
    assert not partial.blocked and partial.comparisons[1].overall.pairs == 0
    confirmed = profile.alignments_from_confirmed(
        spec,
        [
            ("human", "20260731_7kgf_sam1", "20260731_sam1_slices"),
            ("ml", "20260731_7kgf_sam1", "20260731_7kgf_sam1"),
        ],
    )
    result = profile.evaluate_profile(
        profile.ReportProfile(datasets, comparisons, confirmed), loaded, registry=registry
    )
    assert not result.blocked, result.errors
    by_id = {item.spec.id: item for item in result.comparisons}
    self_eval = by_id["self"].overall
    assert self_eval.pairs == 988 - 197 and self_eval.excluded == 197  # E-Invalid dropped
    assert self_eval.metrics.accuracy == 1.0 and self_eval.agreement.kappa == pytest.approx(1.0)
    cross = by_id["cross"].overall
    assert cross.table.labels_a == E5 and set(cross.table.labels_b) == set(OPTICAL)
    assert cross.excluded == 0 and cross.pairs == 988
    assert cross.chi.p_value < 1e-6 and cross.chi.cramers_v_corrected > 0.3
    invalid_bad = cross.cells[0]
    assert invalid_bad.name == "E-Invalid x BAD" and invalid_bad.odds_ratio > 1
    assert invalid_bad.holm_p is not None and invalid_bad.holm_p >= invalid_bad.fisher_p
    residual = cross.residuals[E5.index("E-Invalid")][cross.table.labels_b.index("BAD")]
    assert residual > 1.96
    assert cross.agreement is None  # different label sets: no kappa
    binary = by_id["cross_binary"].overall
    assert binary.table.labels_a == ("Pass", "Fail") == binary.table.labels_b
    assert binary.agreement is not None and binary.agreement.positive_agreement is not None
    assert binary.excluded == 197  # E-Invalid -> Exclude in the binary preset

    # Unmapped labels block instead of being scored silently.
    broken = profile.ComparisonSpec(
        "broken",
        "reference",
        "elec",
        "ml",
        mapping_a={"E-Normal": "Normal"},
        mapping_b={"Normal": "Normal"},
        categories=("Normal",),
    )
    blocked = profile.evaluate_profile(
        profile.ReportProfile(datasets, (broken,), confirmed), loaded, registry=registry
    )
    assert blocked.blocked and blocked.comparisons[0].overall is None
    assert "E-NoActive" in blocked.comparisons[0].unmapped_a
    wrong_scheme = profile.ReportProfile(
        (profile.DatasetSpec("elec", str(measurement), "electrical_gt", "legacy_electrical"),)
    )
    assert "E-Normal" in profile.evaluate_profile(wrong_scheme, registry=registry).errors[0]


# ------------------------------------------------------- review regressions (2026-09-30)


def test_map_value_wildcard_blank_and_reference_axis_guard() -> None:
    rules = {"Pass": "Pass", "*": "Fail"}
    assert profile._map_value("Open", rules, ()) == ("Fail", False)
    assert profile._map_value("pass", rules, ()) == ("Pass", False)
    assert profile._map_value("--", rules, ()) == (None, False)  # blank key never matches "*"
    assert profile._map_value("Open", {}, ("open",)) == (None, True)
    assert profile._map_value("Open", {"Open": schemes.EXCLUDE}, ()) == (None, True)


def _grid_csv(path: Path, name: str, column: str, values) -> Path:
    return _csv(path, _rows(name, column, values))


def test_spelling_variants_are_one_label_everywhere(tmp_path: Path) -> None:
    spellings = ("Pass", "PASS", "pass", "Open", "Short")
    a = _grid_csv(tmp_path / "a.csv", "s1", "Status", lambda i, _r, _n: spellings[i % 5])
    b = _grid_csv(tmp_path / "b.csv", "s1", "label", lambda i, _r, _n: ("GOOD", "BAD")[i % 2])
    spec = profile.ReportProfile(
        (profile.DatasetSpec("a", str(a)), profile.DatasetSpec("b", str(b))),
        (
            profile.ComparisonSpec(
                "cross",
                "association",
                "a",
                "b",
                cells=(profile.CellSpec("pass x bad", ("PASS",), ("bad",)),),
            ),
        ),
    )
    result = profile.evaluate_profile(spec, registry=schemes.load_registry(user_path="/none"))
    assert not result.blocked, result.errors
    table = result.comparisons[0].overall.table
    assert table.labels_a == ("Pass", "Open", "Short")
    assert table.row_totals[0] == sum(1 for i in range(988) if i % 5 in (0, 1, 2))
    assert result.samples[0].records[1].value("a") == "Pass"  # canonical spelling at join time
    cell = result.comparisons[0].overall.cells[0]
    assert cell.a + cell.b == table.row_totals[0]  # case-insensitive cell match
    from r2r_evaluation_report.workbook import generate_workbook

    generate_workbook(tmp_path / "out.xlsx", result)  # palette lookup no longer raises


def test_reference_category_outside_axis_blocks_instead_of_raising(tmp_path: Path) -> None:
    a = _grid_csv(tmp_path / "a.csv", "s1", "Status", lambda i, _r, _n: LEGACY[i % 6])
    b = _grid_csv(tmp_path / "b.csv", "s1", "prediction", lambda i, _r, _n: "Normal")
    spec = profile.ReportProfile(
        (profile.DatasetSpec("a", str(a)), profile.DatasetSpec("b", str(b))),
        (
            profile.ComparisonSpec(
                "ref",
                "reference",
                "a",
                "b",
                mapping_a={"Pass": "Pass", "*": "Fail"},
                mapping_b={"Normal": "Normal"},
                categories=("Pass", "Fail"),
            ),
        ),
    )
    result = profile.evaluate_profile(spec, registry=schemes.load_registry(user_path="/none"))
    assert result.blocked and result.comparisons[0].unmapped_b == ("Normal",)


def test_profile_rejects_duplicate_alignments_and_unknown_cell_labels(tmp_path: Path) -> None:
    datasets = (profile.DatasetSpec("a", "a.csv"), profile.DatasetSpec("b", "b.csv"))
    twice = profile.AlignmentSpec("s1", {"a": "s1", "b": "s1"})
    with pytest.raises(profile.ProfileError, match="aligned twice"):
        profile.ReportProfile(datasets, (), (twice, twice))
    with pytest.raises(profile.ProfileError, match="two samples"):
        profile.ReportProfile(
            datasets,
            (),
            (twice, profile.AlignmentSpec("s2", {"a": "s2", "b": "s1"})),
        )
    a = _grid_csv(tmp_path / "a.csv", "s1", "Status", lambda i, _r, _n: LEGACY[i % 6])
    b = _grid_csv(tmp_path / "b.csv", "s1", "label", lambda i, _r, _n: ("GOOD", "BAD")[i % 2])
    spec = profile.ReportProfile(
        (profile.DatasetSpec("a", str(a)), profile.DatasetSpec("b", str(b))),
        (
            profile.ComparisonSpec(
                "cross",
                "association",
                "a",
                "b",
                cells=(profile.CellSpec("typo", ("Nope",), ("BAD",)),),
            ),
        ),
    )
    result = profile.evaluate_profile(spec, registry=schemes.load_registry(user_path="/none"))
    assert result.blocked and "not on the axis" in result.errors[0]
