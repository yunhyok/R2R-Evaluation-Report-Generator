from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Event
from time import sleep

from PySide6.QtCore import Qt

from r2r_evaluation_report.gui import (
    CoreWorkflowAdapter,
    MainWindow,
    OperationCancelled,
    WorkflowContext,
)
from scripts.create_synthetic_inputs import create_inputs


class FakeAdapter:
    def __init__(self, *, fail: bool = False, delay: bool = False) -> None:
        self.fail = fail
        self.delay = delay
        self.generated_context: WorkflowContext | None = None

    def preflight(self, context: WorkflowContext) -> dict:
        context.progress(30, "헤더를 검사하는 중…")
        if self.fail:
            raise RuntimeError("헤더를 읽을 수 없습니다. CSV 열 이름을 확인하세요.")
        return {
            "summary": "측정 100행, 예측 100행을 확인했습니다.",
            "measurement": {"sheet_candidates": ["측정"]},
            "prediction": {"sheet_candidates": ["예측"]},
            "mappings": [
                {
                    "measurement": "측정",
                    "prediction": "예측",
                    "method": "휴리스틱 키 연결",
                    "heuristic": True,
                }
            ],
            "label_rules": [
                {"raw_status": "OK", "class": "Normal", "binary": "Pass"},
                {"raw_status": "미상"},
            ],
            "unresolved_labels": ["미상"],
            "prediction_only_sheets": ["예측_보류"],
        }

    def generate(self, context: WorkflowContext) -> dict:
        self.generated_context = context
        if self.delay:
            for number in range(40):
                if context.cancel_event.is_set():
                    raise OperationCancelled()
                context.progress(number * 2, "통합문서 작성 중…")
                sleep(0.005)
        if self.fail:
            raise RuntimeError("통합문서를 저장할 수 없습니다. 파일 권한을 확인하세요.")
        Path(context.output_path).write_bytes(b"fake xlsx")
        return {"output_path": context.output_path}


def _make_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    measurement = tmp_path / "측정.csv"
    prediction = tmp_path / "예측.csv"
    output = tmp_path / "결과.xlsx"
    measurement.write_text("name,status\na,OK\n", encoding="utf-8")
    prediction.write_text("name,prediction\na,Normal\n", encoding="utf-8")
    return measurement, prediction, output


def _fill_paths(window: MainWindow, tmp_path: Path) -> tuple[Path, Path, Path]:
    measurement, prediction, output = _make_files(tmp_path)
    window.measurement_edit.setText(str(measurement))
    window.prediction_edit.setText(str(prediction))
    window.output_edit.setText(str(output))
    return measurement, prediction, output


def test_initial_state(qtbot) -> None:
    window = MainWindow(adapter=FakeAdapter(), test_mode=True)
    qtbot.addWidget(window)
    window.show()

    assert window.windowTitle() == "R2R 평가 리포트 생성기"
    assert not window.generate_button.isEnabled()
    assert not window.cancel_button.isEnabled()
    assert not window.sheet_box.isVisible()
    assert window.measurement_edit.accessibleName() == "측정 CSV 또는 XLSX 파일"


def test_path_validation_reports_recovery(qtbot, tmp_path: Path) -> None:
    window = MainWindow(adapter=FakeAdapter(), test_mode=True)
    qtbot.addWidget(window)
    window.measurement_edit.setText(str(tmp_path / "wrong.txt"))
    window.prediction_edit.setText(str(tmp_path / "prediction.csv"))
    window.output_edit.setText(str(tmp_path / "report.xlsx"))
    window.start_preflight()

    assert "CSV 또는 XLSX" in window.status_label.text()


def test_mapping_confirmation_and_unresolved_label_block_generation(qtbot, tmp_path: Path) -> None:
    window = MainWindow(adapter=FakeAdapter(), test_mode=True)
    qtbot.addWidget(window)
    _fill_paths(window, tmp_path)
    window.start_preflight()
    qtbot.waitUntil(lambda: "완료" in window.status_label.text(), timeout=3000)

    assert "예측 전용" in window.prediction_only_label.text()
    assert "미상" in window.unresolved_label.text()
    assert not window.generate_button.isEnabled()
    assert window.confirm_all_mappings_button.isEnabled()

    # Confirming a heuristic alone is insufficient while a raw label is unresolved.
    qtbot.mouseClick(window.confirm_all_mappings_button, Qt.LeftButton)
    checkbox = window.mapping_table.cellWidget(0, 3)
    assert checkbox.isChecked()
    assert not window.confirm_all_mappings_button.isEnabled()
    assert not window.generate_button.isEnabled()

    unresolved_combo = window.label_table.cellWidget(1, 1)
    binary_combo = window.label_table.cellWidget(1, 2)
    expanded_combo = window.label_table.cellWidget(1, 3)
    window.label_table.cellWidget(0, 3).setCurrentText("Normal")
    unresolved_combo.setCurrentText("Open")
    binary_combo.setCurrentText("Fail")
    expanded_combo.setCurrentText("Open")
    assert window.generate_button.isEnabled()


def test_working_controls_cancel_and_success_state(qtbot, tmp_path: Path) -> None:
    adapter = FakeAdapter(delay=True)
    window = MainWindow(adapter=adapter, test_mode=True)
    qtbot.addWidget(window)
    window.show()
    _, _, output = _fill_paths(window, tmp_path)
    window._set_mappings([{"measurement": "측정", "prediction": "예측", "method": "명시적"}])
    window._set_label_rules(
        [{"raw_status": "OK", "class": "Normal", "binary": "Pass", "expanded_normal": "Normal"}]
    )
    window._refresh_generate_state()

    window.start_generation()
    qtbot.waitUntil(lambda: not window.measurement_edit.isEnabled(), timeout=1000)
    assert window.cancel_button.isEnabled()
    window.cancel_current_operation()
    assert "취소 요청" in window.status_label.text()
    assert window.cancel_event.is_set()
    assert window._thread is not None
    assert window._thread.wait(3000)
    qtbot.waitUntil(lambda: window.status_label.text() == "작업을 취소했습니다.", timeout=3000)
    qtbot.waitUntil(lambda: window._thread is None, timeout=3000)
    assert window.measurement_edit.isEnabled()

    adapter.delay = False
    window.start_generation()
    assert window._thread is not None
    assert window._thread.wait(3000)
    qtbot.waitUntil(lambda: window.open_workbook_button.isVisible(), timeout=3000)
    assert output.is_file()
    assert window._last_output_path == str(output)
    assert window.open_folder_button.isVisible()

    window.output_edit.setText(str(tmp_path / "다른 결과.xlsx"))
    assert not window.open_workbook_button.isVisible()
    assert window._last_output_path is None


def test_unmatched_measurement_sample_blocks_generation(qtbot, tmp_path: Path) -> None:
    window = MainWindow(adapter=FakeAdapter(), test_mode=True)
    qtbot.addWidget(window)
    _fill_paths(window, tmp_path)
    window._apply_preflight(
        {
            "mappings": [
                {
                    "measurement": "측정 1",
                    "prediction": "예측 1",
                    "method": "정확",
                }
            ],
            "label_rules": [
                {
                    "raw_status": "Pass",
                    "class": "Normal",
                    "binary": "Pass",
                    "expanded_normal": "Normal",
                }
            ],
            "unmatched_measurement_sheets": ["측정 2"],
        }
    )
    window._refresh_generate_state()
    assert "측정 2" in window.unmatched_measurement_label.text()
    assert not window.generate_button.isEnabled()


def test_generation_failure_shows_actionable_error(qtbot, tmp_path: Path) -> None:
    window = MainWindow(adapter=FakeAdapter(fail=True), test_mode=True)
    qtbot.addWidget(window)
    _fill_paths(window, tmp_path)
    window._set_mappings([{"measurement": "측정", "prediction": "예측", "method": "명시적"}])
    window._set_label_rules(
        [{"raw_status": "OK", "class": "Normal", "binary": "Pass", "expanded_normal": "Normal"}]
    )
    window._refresh_generate_state()
    window.start_generation()
    qtbot.waitUntil(lambda: "권한" in window.status_label.text(), timeout=3000)
    assert window.measurement_edit.isEnabled()


def test_real_adapter_handles_multi_name_mapping_and_binary_rules(tmp_path: Path) -> None:
    measurement, prediction = create_inputs(tmp_path / "긴 한글 합성 입력")
    output = tmp_path / "긴 한글 결과 경로" / "평가 결과.xlsx"
    output.parent.mkdir()
    adapter = CoreWorkflowAdapter()
    context = WorkflowContext(
        str(measurement),
        str(prediction),
        str(output),
        None,
        None,
        [],
        [],
        Event(),
        lambda _value, _text: None,
    )
    result = adapter.preflight(context)
    assert len(result["mappings"]) == 2
    assert all(item["requires_confirmation"] for item in result["mappings"])
    assert result["prediction_only_sheets"] == ["260807 p3meemt 8kgf 350 SAM 99"]
    assert not result["unmatched_measurement_sheets"]
    approved = [{**item, "confirmed": True} for item in result["mappings"]]
    generated = adapter.generate(
        replace(context, mappings=approved, label_rules=result["label_rules"])
    )
    assert generated["output_path"] == str(output)
    assert output.is_file()
