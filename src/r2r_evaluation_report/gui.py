"""PySide6 interface for the R2R evaluation workbook workflow.

The GUI deliberately keeps the domain work behind a small adapter.  This makes
the screen usable while the validation/workbook implementation evolves and,
more importantly, keeps all QWidget access on the GUI thread.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any, Protocol

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .workbook import derive_color_only_path

ALLOWED_INPUT_SUFFIXES = {".csv", ".xlsx"}
LABEL_CHOICES = ("Normal", "Open", "Short", "Exclude")
BINARY_CHOICES = ("선택 필요", "Pass", "Fail")


class OperationCancelled(Exception):
    """Raised by an adapter when the user cancels its operation."""


@dataclass(frozen=True)
class WorkflowContext:
    measurement_path: str
    prediction_path: str
    output_path: str
    measurement_sheet: str | None
    prediction_sheet: str | None
    mappings: list[dict[str, Any]]
    label_rules: list[dict[str, str]]
    cancel_event: Event
    progress: Callable[[int, str], None]


class WorkflowAdapter(Protocol):
    def preflight(self, context: WorkflowContext) -> dict[str, Any]: ...

    def generate(self, context: WorkflowContext) -> dict[str, Any]: ...


class CoreWorkflowAdapter:
    """Late-binding bridge to the package's domain workflow.

    Current core implementations can expose either ``preflight``/``generate``
    directly or a ``Workflow`` object with those methods.  Keeping this bridge
    narrow avoids coupling the UI to workbook internals.
    """

    def __init__(self) -> None:
        self._measurements: Any | None = None
        self._predictions: Any | None = None
        self._audit: Any | None = None
        self._source_selection: tuple[Any, ...] | None = None

    @staticmethod
    def _known_label(raw: str) -> str | None:
        normalized = "".join(char for char in raw.casefold() if char.isalnum())
        defaults = {
            "pass": "Normal",
            "noactive": "Normal",
            "none": "Normal",
            "open": "Open",
            "short": "Short",
            "nogateeffect": "Exclude",
        }
        return defaults.get(normalized)

    def _operation(self, name: str, context: WorkflowContext) -> dict[str, Any]:
        core = importlib.import_module("r2r_evaluation_report.core")
        target: Any = getattr(core, name, None)
        if target is None:
            workflow_type = getattr(core, "Workflow", None)
            if workflow_type is not None:
                target = getattr(workflow_type(), name, None)
        if target is None:
            raise RuntimeError(
                "핵심 처리 모듈이 준비되지 않았습니다. 패키지를 다시 설치한 뒤 재시도하세요."
            )
        result = target(context)
        return result if isinstance(result, dict) else {"result": result}

    def preflight(self, context: WorkflowContext) -> dict[str, Any]:
        core = importlib.import_module("r2r_evaluation_report.core")
        self._measurements = self._predictions = self._audit = None
        self._source_selection = None
        if not context.measurement_path and not context.prediction_path:
            raise RuntimeError("측정 데이터 또는 예측 결과 중 하나 이상을 선택하세요.")
        context.progress(8, "유효한 헤더와 워크시트를 찾는 중…")
        measurement_candidates = (
            core.discover_worksheets(context.measurement_path, "measurement")
            if context.measurement_path
            else ()
        )
        prediction_candidates = (
            core.discover_worksheets(context.prediction_path, "prediction")
            if context.prediction_path
            else ()
        )
        if (context.measurement_path and not measurement_candidates) or (
            context.prediction_path and not prediction_candidates
        ):
            raise RuntimeError(
                "필수 헤더(Name, Row, Node 및 Status/Prediction)를 가진 시트를 찾지 못했습니다."
            )
        measurement_names = [item.title for item in measurement_candidates]
        prediction_names = [item.title for item in prediction_candidates]
        needs_selection = (len(measurement_names) > 1 and not context.measurement_sheet) or (
            len(prediction_names) > 1 and not context.prediction_sheet
        )
        if needs_selection:
            return {
                "summary": (
                    "여러 유효 시트가 발견되었습니다. 검사할 시트를 선택한 뒤 "
                    "사전 검사를 다시 실행하세요."
                ),
                "measurement": {"sheet_candidates": measurement_names},
                "prediction": {"sheet_candidates": prediction_names},
            }
        selected_measurement = (
            context.measurement_sheet or measurement_names[0] if measurement_names else None
        )
        selected_prediction = (
            context.prediction_sheet or prediction_names[0] if prediction_names else None
        )
        context.progress(25, "선택한 시트의 26×38 좌표를 검사하는 중…")
        measurements = (
            core.parse_dataset(context.measurement_path, "measurement", selected_measurement)
            if context.measurement_path
            else None
        )
        if context.cancel_event.is_set():
            raise OperationCancelled()
        predictions = (
            core.parse_dataset(context.prediction_path, "prediction", selected_prediction)
            if context.prediction_path
            else None
        )
        if context.cancel_event.is_set():
            raise OperationCancelled()
        if measurements is None or predictions is None:
            dataset = measurements if measurements is not None else predictions
            description = core.describe_dataset(dataset)
            if description.blocked:
                raise RuntimeError(
                    "알 수 없는 예측 라벨: " + ", ".join(description.unknown_predictions)
                )
            self._measurements, self._predictions = measurements, predictions
            self._source_selection = (
                context.measurement_path,
                context.prediction_path,
                selected_measurement,
                selected_prediction,
            )
            kind_label = "측정" if measurements is not None else "예측"
            return {
                "single_source_ready": True,
                "summary": (
                    f"{kind_label} 단독 보고서: {len(dataset.sheets)}개 샘플의 라벨 맵과 "
                    "분포를 생성합니다. 비교 상대가 없어 F1·혼동행렬·일치도는 생략합니다."
                ),
                "measurement": {"sheet_candidates": measurement_names},
                "prediction": {"sheet_candidates": prediction_names},
            }
        context.progress(70, "시트 연결과 원본 라벨을 검사하는 중…")
        audit = core.preflight(measurements, predictions)
        self._measurements, self._predictions, self._audit = measurements, predictions, audit
        self._source_selection = (
            context.measurement_path,
            context.prediction_path,
            selected_measurement,
            selected_prediction,
        )
        mappings = [
            {
                "measurement": proposal.measurement_sheet,
                "prediction": proposal.prediction_sheet,
                "method": {
                    "exact": "정확한 시트명 일치",
                    "signature": "서명(날짜·조건) 일치",
                    "heuristic": "휴리스틱 이름 유사도",
                }[proposal.method],
                "requires_confirmation": proposal.requires_confirmation,
                "core_method": proposal.method,
            }
            for proposal in audit.proposals
        ]
        raw_statuses = sorted(
            {record.value for sheet in measurements.sheets for record in sheet.records},
            key=str.casefold,
        )
        unresolved = [raw for raw in raw_statuses if self._known_label(raw) is None]
        proposed_measurements = {proposal.measurement_sheet for proposal in audit.proposals}
        unmatched_measurements = [
            name for name in audit.unmatched_measurement_sheets if name not in proposed_measurements
        ]
        label_rules = [
            {
                "raw_status": raw,
                "class": self._known_label(raw) or "",
                "binary": (
                    "Pass"
                    if "".join(char for char in raw.casefold() if char.isalnum()) == "pass"
                    else "Fail"
                    if self._known_label(raw) is not None
                    else ""
                ),
                "expanded_normal": (
                    "Normal"
                    if "".join(char for char in raw.casefold() if char.isalnum())
                    in {"pass", "noactive", "none", "nogateeffect"}
                    else "Open"
                    if "".join(char for char in raw.casefold() if char.isalnum()) == "open"
                    else "Short"
                    if "".join(char for char in raw.casefold() if char.isalnum()) == "short"
                    else ""
                ),
            }
            for raw in raw_statuses
        ]
        return {
            "summary": (
                f"측정 {len(measurements.sheets)}개 샘플, "
                f"예측 {len(predictions.sheets)}개 샘플을 확인했습니다. "
                "원본 행 전체를 표에 표시하지 않고 시트 연결과 라벨만 검토합니다. "
                "확장 Normal은 No Gate Effect를 Normal로 보는 추가 관찰 가정이며 "
                "원본/기본 결과를 보존합니다."
            ),
            "measurement": {"sheet_candidates": measurement_names},
            "prediction": {"sheet_candidates": prediction_names},
            "mappings": mappings,
            "label_rules": label_rules,
            "unresolved_labels": unresolved,
            "unmatched_measurement_sheets": unmatched_measurements,
            "prediction_only_sheets": list(audit.prediction_only_sheets),
        }

    def generate(self, context: WorkflowContext) -> dict[str, Any]:
        if self._source_selection is None:
            raise RuntimeError("사전 검사를 먼저 완료한 뒤 생성하세요.")
        selection = (
            context.measurement_path,
            context.prediction_path,
            context.measurement_sheet or self._source_selection[2],
            context.prediction_sheet or self._source_selection[3],
        )
        if selection != self._source_selection:
            raise RuntimeError("입력 파일 또는 시트가 바뀌었습니다. 사전 검사를 다시 실행하세요.")
        core = importlib.import_module("r2r_evaluation_report.core")
        workbook = importlib.import_module("r2r_evaluation_report.workbook")
        if self._measurements is None or self._predictions is None:
            dataset = self._measurements if self._measurements is not None else self._predictions
            evaluation = core.describe_dataset(dataset)
        else:
            by_pair = {
                (proposal.measurement_sheet, proposal.prediction_sheet): proposal
                for proposal in self._audit.proposals
            }
            approved = []
            for row in context.mappings:
                if not row.get("confirmed"):
                    continue
                proposal = by_pair.get((row.get("measurement"), row.get("prediction")))
                if proposal is not None:
                    approved.append(
                        core.MappingProposal(
                            proposal.measurement_sheet,
                            proposal.prediction_sheet,
                            proposal.method,
                            False,
                            proposal.signature,
                        )
                        if proposal.requires_confirmation
                        else proposal
                    )
            if not approved:
                raise RuntimeError("확인된 측정·예측 시트 연결이 없습니다.")
            rules = {rule["raw_status"]: rule["class"] for rule in context.label_rules}
            binary_rules = {rule["raw_status"]: rule["binary"] for rule in context.label_rules}
            expanded_rules = {
                rule["raw_status"]: rule["expanded_normal"] for rule in context.label_rules
            }
            context.progress(12, "선택한 규칙으로 평가 지표를 계산하는 중…")
            evaluation = core.evaluate(
                self._measurements,
                self._predictions,
                approved,
                status_rules=rules,
                binary_status_rules=binary_rules,
                expanded_normal_status_rules=expanded_rules,
            )
        if evaluation.blocked:
            details = ", ".join(
                (
                    *evaluation.mapping_errors,
                    *evaluation.unresolved_measurement_statuses,
                    *evaluation.unknown_predictions,
                )
            )
            raise RuntimeError(f"매핑 또는 라벨 확인이 완료되지 않았습니다: {details}")
        if context.cancel_event.is_set():
            raise OperationCancelled()
        context.progress(55, "감사 가능한 Excel 통합문서를 작성하는 중…")
        output, color_only = workbook.generate_workbook_pair(
            context.output_path, evaluation, cancel_check=context.cancel_event
        )
        context.progress(95, "통합문서 구조를 검증하는 중…")
        workbook.verify_workbook(output)
        workbook.verify_workbook(color_only)
        return {"output_path": str(output), "color_only_path": str(color_only)}


class WorkflowWorker(QThread):
    """Runs an adapter operation without ever touching a QWidget."""

    progress = Signal(int, str)
    succeeded = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, adapter: WorkflowAdapter, operation: str, context: WorkflowContext) -> None:
        super().__init__()
        self.adapter = adapter
        self.operation = operation
        self.context = context

    def run(self) -> None:
        try:
            if self.context.cancel_event.is_set():
                raise OperationCancelled()
            self.progress.emit(1, "작업을 시작합니다…")
            result = getattr(self.adapter, self.operation)(self.context)
            if self.context.cancel_event.is_set():
                raise OperationCancelled()
            self.progress.emit(100, "완료했습니다.")
            self.succeeded.emit(self.operation, result)
        except OperationCancelled:
            self.failed.emit(self.operation, "작업을 취소했습니다.")
        except Exception as exc:  # adapters can supply more specific recovery text
            detail = str(exc) or "알 수 없는 오류가 발생했습니다."
            self.failed.emit(
                self.operation,
                "작업을 완료하지 못했습니다. 파일 경로, 필수 헤더, 26×38 좌표, "
                "또는 열려 있는 Excel 파일을 확인한 뒤 다시 시도하세요.\n"
                f"세부 원인: {detail}",
            )


class PathPreviewLabel(QLabel):
    """An elided, tooltip-backed preview for long Korean/network paths."""

    def __init__(self) -> None:
        super().__init__()
        self._path = ""
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setStyleSheet("color: #5f6b7a;")
        self.setMinimumWidth(1)

    def set_path(self, path: str) -> None:
        self._path = path
        self.setToolTip(path)
        self._refresh()

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        self.setText(
            self.fontMetrics().elidedText(self._path, Qt.ElideMiddle, max(20, self.width()))
        )


class MainWindow(QMainWindow):
    """Guided, auditable R2R evaluation-report screen."""

    def __init__(self, adapter: WorkflowAdapter | None = None, *, test_mode: bool = False) -> None:
        super().__init__()
        self.adapter = adapter or CoreWorkflowAdapter()
        self.test_mode = test_mode
        self.cancel_event = Event()
        self._thread: QThread | None = None
        self._worker: WorkflowWorker | None = None
        self._mapping_rows: list[dict[str, Any]] = []
        self._unresolved_labels: list[str] = []
        self._unmatched_measurements: list[str] = []
        self._last_output_path: str | None = None
        self._last_color_only_path: str | None = None
        self._single_source_ready = False
        self._file_buttons: list[QPushButton] = []
        self._build_ui()
        self._connect_signals()
        self._refresh_generate_state()

    def _build_ui(self) -> None:
        self.setWindowTitle("R2R 평가 리포트 생성기")
        self.setMinimumSize(820, 660)
        central = QWidget(self)
        self.setCentralWidget(central)
        shell = QVBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        shell.addWidget(scroll)
        root = QVBoxLayout(content)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)
        root.setAlignment(Qt.AlignTop)

        title = QLabel("R2R 평가 리포트 생성기")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        root.addWidget(title)
        subtitle = QLabel("파일 선택 → 사전 검사 → 연결·라벨 확인 → Excel 생성")
        subtitle.setStyleSheet("color: #5f6b7a;")
        root.addWidget(subtitle)
        input_hint = QLabel(
            "측정·예측 중 하나만 선택해도 라벨 맵과 분포를 생성합니다. "
            "두 파일을 선택하면 비교 보고서를 생성합니다."
        )
        input_hint.setWordWrap(True)
        root.addWidget(input_hint)

        input_box = QGroupBox("1. 입력과 출력 파일")
        input_layout = QGridLayout(input_box)
        input_layout.setColumnStretch(1, 1)
        self.measurement_edit, self.measurement_preview = self._path_row(
            input_layout, 0, "측정 데이터", "측정 CSV 또는 XLSX 파일", self._choose_measurement
        )
        self.prediction_edit, self.prediction_preview = self._path_row(
            input_layout, 1, "예측 결과", "예측 CSV 또는 XLSX 파일", self._choose_prediction
        )
        self.measurement_edit.setClearButtonEnabled(True)
        self.prediction_edit.setClearButtonEnabled(True)
        self.output_edit, self.output_preview = self._path_row(
            input_layout,
            2,
            "출력 통합문서",
            "생성할 XLSX 파일 경로",
            self._choose_output,
            save=True,
        )
        color_only_label = QLabel("색상 전용 파생 경로")
        self.color_only_preview = PathPreviewLabel()
        self.color_only_preview.setAccessibleName("색상 전용 파생 출력 경로 미리보기")
        self.color_only_preview.setToolTip("출력 통합문서와 함께 생성되는 색상 전용 파일")
        input_layout.addWidget(color_only_label, 6, 0)
        input_layout.addWidget(self.color_only_preview, 6, 1)
        self.preflight_button = QPushButton("사전 검사")
        self.preflight_button.setAccessibleName("사전 검사 실행")
        input_layout.addWidget(self.preflight_button, 6, 2)
        root.addWidget(input_box)

        self.sheet_box = QGroupBox("2. XLSX 시트 선택")
        sheet_form = QFormLayout(self.sheet_box)
        self.measurement_sheet_combo = QComboBox()
        self.prediction_sheet_combo = QComboBox()
        self.measurement_sheet_combo.setAccessibleName("측정 데이터 시트 선택")
        self.prediction_sheet_combo.setAccessibleName("예측 결과 시트 선택")
        sheet_form.addRow("측정 시트", self.measurement_sheet_combo)
        sheet_form.addRow("예측 시트", self.prediction_sheet_combo)
        self.sheet_box.setVisible(False)
        root.addWidget(self.sheet_box)

        self.summary_label = QLabel("파일을 선택한 뒤 사전 검사를 실행하세요.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setFrameShape(QFrame.StyledPanel)
        self.summary_label.setStyleSheet("padding: 8px; background: #f7f9fc;")
        self.summary_label.setAccessibleName("사전 검사 요약")
        root.addWidget(self.summary_label)

        mapping_box = QGroupBox("3. 측정·예측 샘플 연결 확인")
        self.mapping_box = mapping_box
        mapping_layout = QVBoxLayout(mapping_box)
        self.mapping_table = QTableWidget(0, 4)
        self.mapping_table.setHorizontalHeaderLabels(
            ("측정 샘플", "예측 샘플", "연결 방법", "명시적 확인")
        )
        self.mapping_table.setAccessibleName("측정 예측 매핑 표")
        self.mapping_table.setAlternatingRowColors(True)
        self.mapping_table.horizontalHeader().setStretchLastSection(True)
        self.mapping_table.setMinimumHeight(130)
        mapping_layout.addWidget(self.mapping_table)
        mapping_actions = QHBoxLayout()
        mapping_actions.addStretch(1)
        self.confirm_all_mappings_button = QPushButton("제안 연결 전체 확인")
        self.confirm_all_mappings_button.setAccessibleName("모든 제안 연결 명시적 확인")
        self.confirm_all_mappings_button.setEnabled(False)
        mapping_actions.addWidget(self.confirm_all_mappings_button)
        mapping_layout.addLayout(mapping_actions)
        self.prediction_only_label = QLabel("")
        self.prediction_only_label.setWordWrap(True)
        self.prediction_only_label.setStyleSheet("color: #a04a00;")
        self.prediction_only_label.setAccessibleName("예측 전용 시트 경고")
        mapping_layout.addWidget(self.prediction_only_label)
        self.unmatched_measurement_label = QLabel("")
        self.unmatched_measurement_label.setWordWrap(True)
        self.unmatched_measurement_label.setStyleSheet("color: #b00020; font-weight: 600;")
        self.unmatched_measurement_label.setAccessibleName("미매칭 측정 샘플 경고")
        mapping_layout.addWidget(self.unmatched_measurement_label)
        root.addWidget(mapping_box)

        label_box = QGroupBox("4. 라벨 규칙 확인")
        self.label_box = label_box
        label_layout = QVBoxLayout(label_box)
        self.label_table = QTableWidget(0, 4)
        self.label_table.setHorizontalHeaderLabels(
            ("원본 상태", "3-클래스", "이진 판정", "확장 Normal")
        )
        self.label_table.setAccessibleName("라벨 규칙 표")
        self.label_table.setAlternatingRowColors(True)
        self.label_table.horizontalHeader().setStretchLastSection(True)
        self.label_table.setMinimumHeight(130)
        label_layout.addWidget(self.label_table)
        self.unresolved_label = QLabel("")
        self.unresolved_label.setWordWrap(True)
        self.unresolved_label.setStyleSheet("color: #b00020; font-weight: 600;")
        self.unresolved_label.setAccessibleName("미해결 라벨 경고")
        label_layout.addWidget(self.unresolved_label)
        root.addWidget(label_box)

        bottom = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setAccessibleName("작업 진행률")
        bottom.addWidget(self.progress_bar, 1)
        self.cancel_button = QPushButton("취소")
        self.cancel_button.setAccessibleName("현재 작업 취소")
        bottom.addWidget(self.cancel_button)
        self.generate_button = QPushButton("Excel 생성")
        self.generate_button.setDefault(True)
        self.generate_button.setAccessibleName("Excel 통합문서 생성")
        bottom.addWidget(self.generate_button)
        root.addLayout(bottom)

        self.status_label = QLabel("준비됨")
        self.status_label.setAccessibleName("작업 상태")
        root.addWidget(self.status_label)
        self.output_result_label = QLabel("")
        self.output_result_label.setWordWrap(True)
        self.output_result_label.setAccessibleName("생성된 두 통합문서 경로")
        self.output_result_label.setStyleSheet("color: #2d5f3f;")
        root.addWidget(self.output_result_label)
        result_buttons = QHBoxLayout()
        result_buttons.addStretch(1)
        self.open_workbook_button = QPushButton("코드 포함 통합문서 열기")
        self.open_color_only_button = QPushButton("색상 전용 통합문서 열기")
        self.open_folder_button = QPushButton("출력 폴더 열기")
        self.open_workbook_button.setAccessibleName("생성된 통합문서 열기")
        self.open_color_only_button.setAccessibleName("생성된 색상 전용 통합문서 열기")
        self.open_folder_button.setAccessibleName("출력 폴더 열기")
        result_buttons.addWidget(self.open_workbook_button)
        result_buttons.addWidget(self.open_color_only_button)
        result_buttons.addWidget(self.open_folder_button)
        root.addLayout(result_buttons)
        self.open_workbook_button.hide()
        self.open_color_only_button.hide()
        self.open_folder_button.hide()
        self.cancel_button.setEnabled(False)

    def _path_row(
        self,
        layout: QGridLayout,
        row: int,
        caption: str,
        accessible: str,
        chooser: Callable[[], None],
        *,
        save: bool = False,
    ) -> tuple[QLineEdit, PathPreviewLabel]:
        label = QLabel(caption)
        edit = QLineEdit()
        edit.setPlaceholderText(".xlsx" if save else ".csv 또는 .xlsx")
        edit.setAccessibleName(accessible)
        edit.setToolTip(accessible)
        button = QPushButton("저장 위치…" if save else "찾아보기…")
        button.setAccessibleName(f"{caption} 파일 선택")
        button.clicked.connect(chooser)
        self._file_buttons.append(button)
        preview = PathPreviewLabel()
        layout.addWidget(label, row * 2, 0)
        layout.addWidget(edit, row * 2, 1)
        layout.addWidget(button, row * 2, 2)
        layout.addWidget(preview, row * 2 + 1, 1, 1, 2)
        return edit, preview

    def _connect_signals(self) -> None:
        self.measurement_edit.textChanged.connect(self._paths_changed)
        self.prediction_edit.textChanged.connect(self._paths_changed)
        self.output_edit.textChanged.connect(self._paths_changed)
        self.preflight_button.clicked.connect(self.start_preflight)
        self.confirm_all_mappings_button.clicked.connect(self._confirm_all_mappings)
        self.generate_button.clicked.connect(self.start_generation)
        self.cancel_button.clicked.connect(self.cancel_current_operation)
        self.open_workbook_button.clicked.connect(self.open_workbook)
        self.open_color_only_button.clicked.connect(self.open_color_only_workbook)
        self.open_folder_button.clicked.connect(self.open_folder)
        self.measurement_sheet_combo.currentIndexChanged.connect(self._sheet_changed)
        self.prediction_sheet_combo.currentIndexChanged.connect(self._sheet_changed)

    def _choose_measurement(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "측정 데이터 선택", "", "데이터 파일 (*.csv *.xlsx)"
        )
        if path:
            self.measurement_edit.setText(path)

    def _choose_prediction(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "예측 결과 선택", "", "데이터 파일 (*.csv *.xlsx)"
        )
        if path:
            self.prediction_edit.setText(path)

    def _choose_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "출력 통합문서 저장", "", "Excel 통합문서 (*.xlsx)"
        )
        if path:
            self.output_edit.setText(path if path.lower().endswith(".xlsx") else f"{path}.xlsx")

    def _paths_changed(self) -> None:
        self._single_source_ready = False
        self._set_sheet_candidates(self.measurement_sheet_combo, [])
        self._set_sheet_candidates(self.prediction_sheet_combo, [])
        self.measurement_preview.set_path(self.measurement_edit.text())
        self.prediction_preview.set_path(self.prediction_edit.text())
        self.output_preview.set_path(self.output_edit.text())
        output = self.output_edit.text().strip()
        self.color_only_preview.set_path(str(derive_color_only_path(output)) if output else "")
        self._mapping_rows.clear()
        self._unresolved_labels.clear()
        self._unmatched_measurements.clear()
        self._last_output_path = None
        self._last_color_only_path = None
        self.mapping_table.setRowCount(0)
        self.confirm_all_mappings_button.setEnabled(False)
        self.label_table.setRowCount(0)
        self.sheet_box.setVisible(False)
        self.prediction_only_label.clear()
        self.unmatched_measurement_label.clear()
        self.unresolved_label.clear()
        self.output_result_label.clear()
        self.open_workbook_button.hide()
        self.open_color_only_button.hide()
        self.open_folder_button.hide()
        self._refresh_generate_state()

    def _sheet_changed(self, *_: Any) -> None:
        self._single_source_ready = False
        self._set_mappings([])
        self._set_label_rules([])
        self.summary_label.setText("시트가 변경되었습니다. 사전 검사를 다시 실행하세요.")
        self._refresh_generate_state()

    def _validate_paths(self) -> str | None:
        entries = (
            ("측정 데이터", self.measurement_edit.text()),
            ("예측 결과", self.prediction_edit.text()),
        )
        if not any(value.strip() for _, value in entries):
            return "측정 데이터 또는 예측 결과 중 하나 이상을 선택하세요."
        for name, value in entries:
            if not value.strip():
                continue
            if Path(value).suffix.lower() not in ALLOWED_INPUT_SUFFIXES:
                return f"{name}는 CSV 또는 XLSX 파일이어야 합니다."
            if not Path(value).is_file():
                return (
                    f"{name} 파일을 찾을 수 없습니다. 경로와 네트워크 드라이브 연결을 확인하세요."
                )
        output = self.output_edit.text().strip()
        if not output:
            return "생성할 XLSX 파일 경로를 지정하세요."
        if Path(output).suffix.lower() != ".xlsx":
            return "출력 파일은 .xlsx 확장자여야 합니다."
        parent = Path(output).parent
        if not parent.is_dir():
            return "출력 폴더를 찾을 수 없습니다. 저장 위치를 다시 지정하세요."
        inputs = {Path(value.strip()).resolve() for _, value in entries if value.strip()}
        if inputs.intersection({Path(output).resolve(), derive_color_only_path(output).resolve()}):
            return "출력 파일은 입력 파일과 다른 경로를 지정하세요."
        return None

    def start_preflight(self) -> None:
        message = self._validate_paths()
        if message:
            self._show_error(message)
            return
        self._single_source_ready = False
        self._set_mappings([])
        self._set_label_rules([])
        self._start_operation("preflight")

    def start_generation(self) -> None:
        if not self.generate_button.isEnabled():
            self._show_error("사전 검사 결과의 매핑과 모든 라벨 규칙을 먼저 확인하세요.")
            return
        output = Path(self.output_edit.text())
        color_only = derive_color_only_path(output)
        existing = [path for path in (output, color_only) if path.exists()]
        if existing and not self.test_mode:
            answer = QMessageBox.question(
                self,
                "기존 파일 덮어쓰기",
                "다음 파일을 덮어쓸까요?\n" + "\n".join(map(str, existing)),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        self._start_operation("generate")

    def _make_context(self) -> WorkflowContext:
        def progress(value: int, text: str) -> None:
            # This callback may be called by the worker thread; queued signal is safe.
            if self._worker is not None:
                self._worker.progress.emit(max(0, min(100, int(value))), str(text))

        return WorkflowContext(
            self.measurement_edit.text().strip(),
            self.prediction_edit.text().strip(),
            self.output_edit.text().strip(),
            self._sheet_value(self.measurement_sheet_combo),
            self._sheet_value(self.prediction_sheet_combo),
            self._current_mappings(),
            self._current_label_rules(),
            self.cancel_event,
            progress,
        )

    @staticmethod
    def _sheet_value(combo: QComboBox) -> str | None:
        return combo.currentData() or (combo.currentText() if combo.count() else None)

    def _start_operation(self, operation: str) -> None:
        if self._thread is not None:
            self.status_label.setText("이전 작업을 정리하는 중입니다. 잠시 후 다시 시도하세요.")
            return
        self.cancel_event = Event()
        self._set_working(
            True,
            "사전 검사 중…" if operation == "preflight" else "두 Excel 통합문서 생성 중…",
        )
        self._thread = WorkflowWorker(self.adapter, operation, self._make_context())
        self._worker = self._thread
        self._worker.progress.connect(self._update_progress, Qt.QueuedConnection)
        self._worker.succeeded.connect(self._operation_succeeded, Qt.QueuedConnection)
        self._worker.failed.connect(self._operation_failed, Qt.QueuedConnection)
        self._thread.finished.connect(self._cleanup_thread, Qt.QueuedConnection)
        self._thread.start()

    def cancel_current_operation(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self.cancel_event.set()
            self.cancel_button.setEnabled(False)
            self.status_label.setText(
                "취소 요청을 보냈습니다. 현재 단계가 안전하게 끝나면 중단합니다…"
            )

    @Slot(int, str)
    def _update_progress(self, value: int, text: str) -> None:
        self.progress_bar.setValue(value)
        if not self.cancel_event.is_set():
            self.status_label.setText(text)

    @Slot(str, object)
    def _operation_succeeded(self, operation: str, result: object) -> None:
        self.status_label.setText(
            "사전 검사가 완료되었습니다."
            if operation == "preflight"
            else "코드 포함·색상 전용 두 Excel 통합문서를 생성했습니다."
        )
        if operation == "preflight":
            self._apply_preflight(result if isinstance(result, dict) else {})
        else:
            output_path = (
                result.get("output_path") if isinstance(result, dict) else self.output_edit.text()
            )
            color_only_path = (
                result.get("color_only_path")
                if isinstance(result, dict)
                else str(derive_color_only_path(output_path or self.output_edit.text()))
            )
            self._last_output_path = str(output_path or self.output_edit.text())
            self._last_color_only_path = str(
                color_only_path or derive_color_only_path(self._last_output_path)
            )
            self.output_result_label.setText(
                "생성 완료:\n"
                f"코드 포함: {self._last_output_path}\n"
                f"색상 전용: {self._last_color_only_path}"
            )
            self.open_workbook_button.show()
            self.open_color_only_button.show()
            self.open_folder_button.show()

    @Slot(str, str)
    def _operation_failed(self, operation: str, message: str) -> None:
        self.status_label.setText(message)
        if message != "작업을 취소했습니다.":
            self._show_error(message)

    def _cleanup_thread(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None
        self._set_working(False, self.status_label.text())
        self._refresh_generate_state()

    def _set_working(self, working: bool, status: str) -> None:
        for widget in (
            self.measurement_edit,
            self.prediction_edit,
            self.output_edit,
            self.preflight_button,
            self.measurement_sheet_combo,
            self.prediction_sheet_combo,
            self.mapping_table,
            self.confirm_all_mappings_button,
            self.label_table,
            self.generate_button,
            *self._file_buttons,
        ):
            widget.setEnabled(not working)
        self.cancel_button.setEnabled(working)
        self.progress_bar.setValue(0 if working else self.progress_bar.value())
        self.status_label.setText(status)

    def _apply_preflight(self, result: dict[str, Any]) -> None:
        self._single_source_ready = bool(result.get("single_source_ready"))
        # Accepted aliases allow the core package to return a clear domain model.
        measurement = result.get("measurement") or result.get("measurement_summary") or {}
        prediction = result.get("prediction") or result.get("prediction_summary") or {}
        self.summary_label.setText(
            result.get("summary") or self._summary_text(measurement, prediction)
        )
        self._set_sheet_candidates(
            self.measurement_sheet_combo, measurement.get("sheet_candidates", [])
        )
        self._set_sheet_candidates(
            self.prediction_sheet_combo, prediction.get("sheet_candidates", [])
        )
        show_sheets = (
            self.measurement_sheet_combo.count() > 1 or self.prediction_sheet_combo.count() > 1
        )
        self.sheet_box.setVisible(show_sheets)
        mappings = result.get("mappings") or result.get("mapping_rows") or []
        self._set_mappings(mappings)
        rules = result.get("label_rules") or result.get("labels") or []
        self._set_label_rules(rules)
        prediction_only = (
            result.get("prediction_only_sheets") or result.get("prediction_only") or []
        )
        if prediction_only:
            names = ", ".join(map(str, prediction_only))
            warning = f"주의: 예측 전용 시트(측정값 없음)가 발견되었습니다: {names}. "
            self.prediction_only_label.setText(
                warning + "생성 보고서의 감사(Audit) 시트에 별도로 기록됩니다."
            )
        else:
            self.prediction_only_label.clear()
        self._unmatched_measurements = list(
            result.get("unmatched_measurement_sheets") or result.get("unmatched_measurements") or []
        )
        if self._unmatched_measurements:
            self.unmatched_measurement_label.setText(
                "생성 차단: 대응 예측이 없는 측정 샘플 — "
                + ", ".join(map(str, self._unmatched_measurements))
            )
        else:
            self.unmatched_measurement_label.clear()
        self._unresolved_labels = list(result.get("unresolved_labels") or [])
        self._refresh_generate_state()

    @staticmethod
    def _summary_text(measurement: dict[str, Any], prediction: dict[str, Any]) -> str:
        return (
            f"측정 데이터: {measurement.get('summary', '확인됨')}  |  "
            f"예측 결과: {prediction.get('summary', '확인됨')}"
        )

    @staticmethod
    def _set_sheet_candidates(combo: QComboBox, candidates: list[Any]) -> None:
        previous = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        for candidate in candidates:
            if isinstance(candidate, dict):
                name = str(
                    candidate.get("name")
                    or candidate.get("sheet")
                    or candidate.get("title")
                    or "시트"
                )
                combo.addItem(name, candidate.get("name") or candidate.get("sheet") or name)
            else:
                combo.addItem(str(candidate), str(candidate))
        if previous and combo.findText(previous) >= 0:
            combo.setCurrentText(previous)
        combo.blockSignals(False)

    def _set_mappings(self, rows: list[Any]) -> None:
        self._mapping_rows = [
            dict(row) if isinstance(row, dict) else {"measurement": str(row)} for row in rows
        ]
        self.mapping_table.setRowCount(len(self._mapping_rows))
        for index, row in enumerate(self._mapping_rows):
            measurement = str(row.get("measurement") or row.get("measurement_sheet") or "")
            prediction = str(row.get("prediction") or row.get("prediction_sheet") or "")
            method = str(row.get("method") or row.get("match_method") or "명시적")
            for column, value in enumerate((measurement, prediction, method)):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.mapping_table.setItem(index, column, item)
            suggested = bool(row.get("requires_confirmation") or row.get("heuristic"))
            checkbox = QCheckBox("확인")
            checkbox.setAccessibleName(f"{measurement} 제안 연결 확인")
            checkbox.setChecked(not suggested)
            checkbox.setEnabled(suggested)
            checkbox.toggled.connect(self._refresh_generate_state)
            self.mapping_table.setCellWidget(index, 3, checkbox)
        self.mapping_table.resizeColumnsToContents()
        self.confirm_all_mappings_button.setEnabled(
            any(
                bool(
                    (checkbox := self.mapping_table.cellWidget(index, 3))
                    and checkbox.isEnabled()
                    and not checkbox.isChecked()
                )
                for index in range(self.mapping_table.rowCount())
            )
        )

    def _confirm_all_mappings(self) -> None:
        for index in range(self.mapping_table.rowCount()):
            checkbox = self.mapping_table.cellWidget(index, 3)
            if isinstance(checkbox, QCheckBox) and checkbox.isEnabled():
                checkbox.setChecked(True)
        self.confirm_all_mappings_button.setEnabled(False)
        self._refresh_generate_state()

    def _set_label_rules(self, rows: list[Any]) -> None:
        self.label_table.setRowCount(len(rows))
        for index, source in enumerate(rows):
            row = dict(source) if isinstance(source, dict) else {"raw_status": str(source)}
            raw = str(row.get("raw_status") or row.get("raw") or row.get("status") or "")
            item = QTableWidgetItem(raw)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.label_table.setItem(index, 0, item)
            class_combo = QComboBox()
            class_combo.addItems(LABEL_CHOICES)
            chosen = str(row.get("class") or row.get("three_class") or "")
            if chosen in LABEL_CHOICES:
                class_combo.setCurrentText(chosen)
            else:
                class_combo.insertItem(0, "선택 필요")
                class_combo.setCurrentIndex(0)
            class_combo.setAccessibleName(f"{raw} 3-클래스 라벨")
            class_combo.currentTextChanged.connect(self._refresh_generate_state)
            self.label_table.setCellWidget(index, 1, class_combo)
            binary_combo = QComboBox()
            binary_combo.addItems(BINARY_CHOICES)
            binary = str(row.get("binary") or row.get("binary_label") or "")
            binary_combo.setCurrentText(binary if binary in BINARY_CHOICES else "선택 필요")
            binary_combo.setAccessibleName(f"{raw} 이진 판정 라벨")
            binary_combo.currentTextChanged.connect(self._refresh_generate_state)
            self.label_table.setCellWidget(index, 2, binary_combo)
            expanded_combo = QComboBox()
            expanded_combo.addItems(["선택 필요", *LABEL_CHOICES])
            expanded = str(row.get("expanded_normal") or "")
            expanded_combo.setCurrentText(expanded if expanded in LABEL_CHOICES else "선택 필요")
            expanded_combo.setAccessibleName(f"{raw} 확장 Normal 판정 라벨")
            expanded_combo.currentTextChanged.connect(self._refresh_generate_state)
            self.label_table.setCellWidget(index, 3, expanded_combo)
        self.label_table.resizeColumnsToContents()

    def _current_mappings(self) -> list[dict[str, Any]]:
        rows = [dict(row) for row in self._mapping_rows]
        for index, row in enumerate(rows):
            checkbox = self.mapping_table.cellWidget(index, 3)
            row["confirmed"] = bool(checkbox and checkbox.isChecked())
        return rows

    def _current_label_rules(self) -> list[dict[str, str]]:
        rules = []
        for index in range(self.label_table.rowCount()):
            item = self.label_table.item(index, 0)
            class_combo = self.label_table.cellWidget(index, 1)
            binary_combo = self.label_table.cellWidget(index, 2)
            expanded_combo = self.label_table.cellWidget(index, 3)
            rules.append(
                {
                    "raw_status": item.text() if item else "",
                    "class": class_combo.currentText()
                    if isinstance(class_combo, QComboBox)
                    else "",
                    "binary": binary_combo.currentText()
                    if isinstance(binary_combo, QComboBox)
                    else "",
                    "expanded_normal": expanded_combo.currentText()
                    if isinstance(expanded_combo, QComboBox)
                    else "",
                }
            )
        return rules

    def _refresh_generate_state(self, *_: Any) -> None:
        confirmed = bool(self._mapping_rows) and all(
            bool((checkbox := self.mapping_table.cellWidget(index, 3)) and checkbox.isChecked())
            for index in range(self.mapping_table.rowCount())
        )
        rules = self._current_label_rules()
        unresolved = [
            rule["raw_status"]
            for rule in rules
            if rule["class"] == "선택 필요"
            or rule["binary"] == "선택 필요"
            or rule["expanded_normal"] == "선택 필요"
        ]
        self._unresolved_labels = unresolved
        pending = bool(unresolved)
        self.unresolved_label.setText(
            "생성 차단: 미해결 원본 라벨 — " + ", ".join(unresolved) if unresolved else ""
        )
        comparison = bool(
            self.measurement_edit.text().strip() and self.prediction_edit.text().strip()
        )
        self.mapping_box.setVisible(comparison)
        self.label_box.setVisible(comparison)
        valid_paths = self._validate_paths() is None
        working = self._thread is not None and self._thread.isRunning()
        self.generate_button.setEnabled(
            valid_paths
            and ((confirmed and bool(rules)) if comparison else self._single_source_ready)
            and not pending
            and not self._unmatched_measurements
            and not working
        )

    def _show_error(self, message: str) -> None:
        self.status_label.setText(message)
        if not self.test_mode:
            QMessageBox.warning(self, "확인 필요", message)

    def open_workbook(self) -> None:
        if not self._last_output_path or not Path(self._last_output_path).is_file():
            self._show_error("마지막으로 생성한 통합문서를 찾을 수 없습니다.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_output_path))

    def open_color_only_workbook(self) -> None:
        if not self._last_color_only_path or not Path(self._last_color_only_path).is_file():
            self._show_error("색상 전용 통합문서를 찾을 수 없습니다.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_color_only_path))

    def open_folder(self) -> None:
        if not self._last_output_path:
            self._show_error("마지막 출력 폴더 정보가 없습니다.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._last_output_path).parent)))


def run_gui(argv: list[str] | None = None, *, smoke_test: bool = False) -> int:
    """Run the GUI entry point; ``argv`` is retained for test launchers."""
    app = QApplication.instance() or QApplication(argv or [])
    window = MainWindow()
    window.show()
    if smoke_test:
        QTimer.singleShot(1500, app.quit)
    return app.exec()
