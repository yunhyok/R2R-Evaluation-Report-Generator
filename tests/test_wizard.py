"""Offscreen, synchronous (test_mode) walk through the five-step wizard."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from openpyxl import load_workbook
from PySide6.QtWidgets import QComboBox

from r2r_evaluation_report import profile, schemes, wizard_backend
from r2r_evaluation_report.profile_workbook import verify_profile_workbook
from r2r_evaluation_report.wizard import NO_MEMBER, ComparisonDialog, WizardWindow

E5 = ("E-Normal", "E-NoActive", "E-Open", "E-Short", "E-Invalid")
GRID = [(r, n) for r in range(1, 27) for n in range(1, 39)]


def _write(path: Path, name: str, column: str, values) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Name", "Row", "Node", column])
        writer.writeheader()
        for index, (row, node) in enumerate(GRID):
            writer.writerow({"Name": name, "Row": row, "Node": node, column: values(index)})
    return path


@pytest.fixture
def files(tmp_path: Path) -> dict[str, Path]:
    def elec(index):
        return E5[index % 5]

    def optical(index):
        return "BAD" if elec(index) in {"E-Invalid", "E-Short"} and index % 3 else "GOOD"

    def ml(index):
        return {"E-Normal": "Normal", "E-NoActive": "Normal", "E-Open": "Open"}.get(
            elec(index), "Short"
        )

    return {
        "elec": _write(tmp_path / "elec.csv", "20260731_7kgf_sam1", "Status", elec),
        "human": _write(tmp_path / "human.csv", "20260731_sam1_slices", "label", optical),
        "ml": _write(tmp_path / "ml.csv", "20260731_7kgf_sam1", "prediction", ml),
    }


def test_backend_inspects_loads_and_validates(files: dict[str, Path], tmp_path: Path) -> None:
    info = wizard_backend.inspect_source(files["elec"])
    assert info.worksheets == ("CSV",) and not info.is_inspector
    specs = [
        profile.DatasetSpec("a", str(files["elec"]), "electrical_gt"),
        profile.DatasetSpec("b", str(files["human"]), "optical_human"),
    ]
    registry = schemes.load_registry(user_path="/nonexistent")
    load = wizard_backend.load_and_propose(specs, registry)
    assert load.suggested_schemes == {"a": "electrical_e5", "b": "optical_3"}
    rows = wizard_backend.alignment_rows(specs, load.datasets, load)
    assert rows[0]["members"]["b"] == "20260731_sam1_slices" and not rows[0]["auto"]["b"]
    bad = profile.ComparisonSpec(
        "x", "reference", "a", "b", mapping_a={"E-Normal": "Normal"}, categories=("Normal",)
    )
    problems = wizard_backend.validate_comparison(bad, E5, ("GOOD", "BAD"))
    assert any("A면 라벨에 매핑이 없습니다" in item for item in problems)
    assert any("B면 라벨에 매핑이 없습니다" in item for item in problems)
    with pytest.raises(wizard_backend.DataContractError):
        wizard_backend.load_and_propose([], registry)


def test_wizard_walks_all_steps_and_generates(qtbot, files: dict[str, Path], tmp_path) -> None:
    registry = schemes.load_registry(user_path="/nonexistent")
    window = WizardWindow(test_mode=True, registry=registry)
    qtbot.addWidget(window)
    window.show()
    assert not window.next_button.isEnabled()
    elec = window.add_dataset(str(files["elec"]), role="electrical_gt", title="Electrical")
    human = window.add_dataset(str(files["human"]), role="optical_human", title="Human")
    ml = window.add_dataset(str(files["ml"]), role="electrical_ml", title="ML")
    assert [spec.id for spec in window.dataset_specs()] == [elec, human, ml]
    window.run_preflight()
    assert window.load is not None and window.alignment_box.isVisible()
    # The exact-title ML sheet is auto-selected; the human sheet needs confirmation.
    human_box = window.alignment_table.cellWidget(0, 1)
    ml_box = window.alignment_table.cellWidget(0, 2)
    assert isinstance(human_box, QComboBox) and human_box.currentText() == NO_MEMBER
    assert ml_box.currentText() == "20260731_7kgf_sam1"
    window._confirm_all()
    assert human_box.currentText() == "20260731_sam1_slices"
    assert len(window.confirmed_alignments()) == 2
    assert window.next_button.isEnabled()
    window._next()
    assert window.stack.currentIndex() == 1
    schemes_chosen = {spec.id: spec.scheme for spec in window.dataset_specs()}
    assert schemes_chosen == {elec: "electrical_e5", human: "optical_3", ml: "ml_3class"}
    # A wrong scheme blocks the step; restoring it unblocks.
    window.set_scheme(human, "legacy_electrical")
    window._refresh_scheme_table()
    assert not window.next_button.isEnabled()
    window.set_scheme(human, "optical_3")
    window._refresh_scheme_table()
    assert window.next_button.isEnabled()
    window._next()
    assert window.stack.currentIndex() == 2
    e5 = registry.scheme("electrical_e5").labels
    window.add_comparison(
        profile.ComparisonSpec(
            "self",
            "reference",
            elec,
            ml,
            "Electrical vs ML",
            mapping_a=registry.preset("e5_to_3class").resolved_rules(e5),
            mapping_b={label: label for label in ("Normal", "Open", "Short")},
            categories=("Normal", "Open", "Short"),
        )
    )
    window.add_comparison(
        profile.ComparisonSpec(
            "cross",
            "association",
            elec,
            human,
            "Electrical vs human",
            cells=(profile.CellSpec("E-Invalid x BAD", ("E-Invalid",), ("BAD",)),),
        )
    )
    assert window.comparison_table.rowCount() == 2
    assert window.comparison_table.item(0, 5).text() == "확인"
    window._next()
    assert window.stack.currentIndex() == 3
    assert not window.next_button.isEnabled()
    output = tmp_path / "out" / "wizard.xlsx"
    output.parent.mkdir()
    window.output_edit.setText(str(output))
    window.title_edit.setText("wizard run")
    window._refresh_next()
    assert window.next_button.isEnabled()
    window._next()
    assert window.stack.currentIndex() == 4
    assert "Electrical vs ML" in window.summary_view.toPlainText()
    window.run_generate()
    assert window._last_outputs is not None, window.status_label.text()
    with_codes, color_only = window._last_outputs
    assert with_codes == output and color_only is not None and color_only.exists()
    assert output.with_suffix(".profile.json").exists()
    wb = load_workbook(with_codes)
    verify_profile_workbook(wb)
    assert wb.sheetnames[-3:] == ["C01", "C02", "Overall Summary"]
    saved = profile.ReportProfile.load(output.with_suffix(".profile.json"))
    assert [c.id for c in saved.comparisons] == ["self", "cross"]
    assert len(saved.alignments) == 1 and set(saved.alignments[0].members) == {elec, human, ml}

    # Reloading the profile into a fresh wizard restores datasets, comparisons and
    # (after preflight) the confirmed alignments.
    again = WizardWindow(test_mode=True, registry=registry)
    qtbot.addWidget(again)
    again.apply_profile(saved)
    assert [c.id for c in again.comparisons] == ["self", "cross"]
    again.run_preflight()
    assert len(again.confirmed_alignments()) == 2
    assert again.build_profile().alignments == saved.alignments

    # Editing step 1 invalidates the load and later outputs.
    window._go(0)
    window._remove_dataset()  # nothing selected: no-op
    window.dataset_table.selectRow(2)
    window._remove_dataset()
    assert window.load is None and window._last_outputs is None
    assert [c.id for c in window.comparisons] == ["cross"]


def test_comparison_dialog_builds_reference_and_association(qtbot, files, tmp_path) -> None:
    registry = schemes.load_registry(user_path="/nonexistent")
    specs = [
        profile.DatasetSpec("a", str(files["elec"]), "electrical_gt", "electrical_e5", title="E"),
        profile.DatasetSpec("b", str(files["ml"]), "electrical_ml", "ml_3class", title="M"),
        profile.DatasetSpec("c", str(files["human"]), "optical_human", "optical_3", title="H"),
    ]
    labels = {"a": E5, "b": ("Normal", "Open", "Short"), "c": ("GOOD", "BAD")}
    dialog = ComparisonDialog(None, specs, labels, registry)
    qtbot.addWidget(dialog)
    dialog.side_widgets["A"]["preset"].setCurrentIndex(
        dialog.side_widgets["A"]["preset"].findData("e5_to_3class")
    )
    built = dialog.build()
    assert built.kind == "reference" and built.a == "a" and built.b == "b"
    assert built.mapping_a["E-Invalid"] == "Exclude" and built.mapping_b["Open"] == "Open"
    assert built.categories == ("Normal", "Open", "Short") and built.strict_macro
    assert built.preset_a == "e5_to_3class" and built.preset_b is None
    assert not wizard_backend.validate_comparison(built, labels["a"], labels["b"])
    dialog._accept()
    assert dialog.result_spec == built

    other = ComparisonDialog(None, specs, labels, registry, used_ids={"cmp1"})
    qtbot.addWidget(other)
    other.kind_box.setCurrentIndex(1)
    other.b_box.setCurrentIndex(2)
    other._add_cell("inv x bad", "E-Invalid", "BAD")
    assoc = other.build()
    assert assoc.id == "cmp2" and assoc.kind == "association" and assoc.b == "c"
    assert assoc.mapping_a == {} and assoc.mapping_b == {} and assoc.categories == ()
    assert assoc.cells == (profile.CellSpec("inv x bad", ("E-Invalid",), ("BAD",)),)
    reopened = ComparisonDialog(None, specs, labels, registry, existing=assoc)
    qtbot.addWidget(reopened)
    assert reopened.build() == assoc
