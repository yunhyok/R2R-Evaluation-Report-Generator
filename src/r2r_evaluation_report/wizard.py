"""Linear five-step wizard: datasets → label schemes → comparisons → output → generate.

Each step can only be entered once the previous one is complete, and editing an
earlier step invalidates the later ones.  All domain work goes through
:mod:`wizard_backend`; QWidgets are touched on the GUI thread only.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from threading import Event
from typing import Any

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import wizard_backend as backend
from .core import DEFAULT_GRID, SampleCandidate, default_sample_selection
from .profile import (
    ROLE_TITLES,
    CellSpec,
    ComparisonSpec,
    DatasetSpec,
    ProfileError,
    ProfileOptions,
    ReportProfile,
    label_orders,
    suggest_role,
)
from .schemes import EXCLUDE, SchemeRegistry, load_registry
from .workbook import derive_color_only_path

STEP_TITLES = ("1 데이터셋", "2 라벨 체계", "3 비교 정의", "4 출력 옵션", "5 생성")
KIND_TITLES = {"reference": "자기 평가 (A가 정답)", "association": "교차 연관 (대칭)"}
NO_SCHEME = "(미등록 — 원본 라벨 그대로)"
NO_PRESET = "(원본 라벨 그대로)"
NO_MEMBER = "(연결 안 함)"
ALL_SHEETS = "(모든 시트)"


class _Worker(QThread):
    progress = Signal(int, str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, job: Callable[[Callable[[int, str], None]], Any]) -> None:
        super().__init__()
        self._job = job

    def run(self) -> None:
        try:
            self.succeeded.emit(self._job(lambda v, t: self.progress.emit(int(v), str(t))))
        except backend.GenerationCancelled:
            self.failed.emit("작업을 취소했습니다.")
        except Exception as exc:  # surfaced verbatim; the backend messages are specific
            self.failed.emit(str(exc) or "알 수 없는 오류가 발생했습니다.")


def _combo(items, current: str | None = None, *, editable: bool = False) -> QComboBox:
    box = QComboBox()
    box.setEditable(editable)
    box.addItems([str(item) for item in items])
    if current is not None:
        index = box.findText(str(current))
        if index >= 0:
            box.setCurrentIndex(index)
        elif editable:
            box.setEditText(str(current))
    return box


def _table(headers: tuple[str, ...]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setStretchLastSection(True)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    return table


def _item(text: str, *, editable: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if not editable:
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    return item


# ------------------------------------------------------------------- dialogs


class ComparisonDialog(QDialog):
    """Define one comparison: kind, sides, per-side mapping, categories, 2x2 cells."""

    def __init__(
        self,
        parent: QWidget | None,
        specs: list[DatasetSpec],
        labels: dict[str, tuple[str, ...]],
        registry: SchemeRegistry,
        existing: ComparisonSpec | None = None,
        used_ids: set[str] = frozenset(),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("비교 정의")
        self.setMinimumWidth(860)
        self.specs = specs
        self.labels = labels
        self.registry = registry
        self.used_ids = set(used_ids)
        self.result_spec: ComparisonSpec | None = None
        layout = QVBoxLayout(self)
        form = QFormLayout()
        default_id = existing.id if existing else self._next_id()
        self.id_edit = QLineEdit(default_id)
        self.title_edit = QLineEdit(existing.title if existing else "")
        self.kind_box = _combo(KIND_TITLES.values())
        self.a_box = _combo([spec.label for spec in specs])
        self.b_box = _combo([spec.label for spec in specs])
        if len(specs) > 1:
            self.b_box.setCurrentIndex(1)
        form.addRow("식별자", self.id_edit)
        form.addRow("제목", self.title_edit)
        form.addRow("종류", self.kind_box)
        form.addRow("A면 데이터셋", self.a_box)
        form.addRow("B면 데이터셋", self.b_box)
        layout.addLayout(form)
        self.kind_help = QLabel()
        self.kind_help.setWordWrap(True)
        self.kind_help.setStyleSheet("color: #5f6b7a;")
        layout.addWidget(self.kind_help)
        sides = QHBoxLayout()
        self.side_widgets: dict[str, dict[str, Any]] = {}
        for side in ("A", "B"):
            group = QGroupBox(f"{side}면 라벨 매핑")
            group_layout = QVBoxLayout(group)
            preset_box = QComboBox()
            table = _table(("원본 라벨", "범주"))
            group_layout.addWidget(QLabel("프리셋"))
            group_layout.addWidget(preset_box)
            group_layout.addWidget(table)
            sides.addWidget(group)
            self.side_widgets[side] = {"preset": preset_box, "table": table}
        layout.addLayout(sides)
        categories_row = QFormLayout()
        self.categories_edit = QLineEdit()
        self.categories_edit.setPlaceholderText(
            "공통 범주 순서 (쉼표 구분) — 자기 평가에서 행렬 축"
        )
        self.positive_edit = QLineEdit()
        self.positive_edit.setPlaceholderText("양성 범주 (2범주일 때 PA/NA 계산; 예: Fail)")
        categories_row.addRow("공통 범주", self.categories_edit)
        categories_row.addRow("양성 범주", self.positive_edit)
        layout.addLayout(categories_row)
        self.cells_group = QGroupBox("관심 2×2 셀 (교차 연관) — 라벨은 쉼표로 여러 개 가능")
        cells_layout = QVBoxLayout(self.cells_group)
        self.cells_table = _table(("이름", "A 라벨", "B 라벨"))
        cells_buttons = QHBoxLayout()
        add_cell = QPushButton("셀 추가")
        remove_cell = QPushButton("셀 삭제")
        add_cell.clicked.connect(self._add_cell)
        remove_cell.clicked.connect(
            lambda: self.cells_table.removeRow(self.cells_table.currentRow())
        )
        cells_buttons.addWidget(add_cell)
        cells_buttons.addWidget(remove_cell)
        cells_buttons.addStretch(1)
        cells_layout.addLayout(cells_buttons)
        cells_layout.addWidget(self.cells_table)
        layout.addWidget(self.cells_group)
        self.problems_label = QLabel()
        self.problems_label.setWordWrap(True)
        self.problems_label.setStyleSheet("color: #b00020;")
        layout.addWidget(self.problems_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.kind_box.currentIndexChanged.connect(self._kind_changed)
        self.a_box.currentIndexChanged.connect(lambda: self._side_changed("A"))
        self.b_box.currentIndexChanged.connect(lambda: self._side_changed("B"))
        for side in ("A", "B"):
            self.side_widgets[side]["preset"].currentIndexChanged.connect(
                lambda _i, s=side: self._preset_changed(s)
            )
        if existing is not None:
            self._load_existing(existing)
        else:
            self._side_changed("A")
            self._side_changed("B")
            self._kind_changed()

    # -- helpers
    def _next_id(self) -> str:
        index = 1
        while f"cmp{index}" in self.used_ids:
            index += 1
        return f"cmp{index}"

    def _kind(self) -> str:
        return "reference" if self.kind_box.currentIndex() == 0 else "association"

    def _spec(self, side: str) -> DatasetSpec:
        box = self.a_box if side == "A" else self.b_box
        return self.specs[box.currentIndex()]

    def _kind_changed(self) -> None:
        reference = self._kind() == "reference"
        self.cells_group.setVisible(not reference)
        self.kind_help.setText(
            "A면이 정답(ground truth), B면이 예측입니다. 두 면을 같은 공통 범주로 매핑해야 하며 "
            "confusion matrix·정밀도/재현율/F1·κ·MCC·다수 클래스 기준선을 계산합니다."
            if reference
            else "어느 면도 정답이 아닙니다. 교차표·χ²·Cramér's V·조정 잔차·Theil's U와 "
            "선택한 2×2 셀의 odds ratio·Fisher p를 계산합니다. 매핑은 선택 사항입니다 "
            "(비우면 원본 라벨 그대로)."
        )
        self._refresh_categories()

    def _side_changed(self, side: str) -> None:
        spec = self._spec(side)
        preset_box: QComboBox = self.side_widgets[side]["preset"]
        preset_box.blockSignals(True)
        preset_box.clear()
        preset_box.addItem(NO_PRESET)
        for preset_id in backend.presets_for(self.registry, spec.scheme):
            preset_box.addItem(f"{preset_id} — {self.registry.preset(preset_id).title}", preset_id)
        preset_box.blockSignals(False)
        self._preset_changed(side)

    def _preset_changed(self, side: str) -> None:
        spec = self._spec(side)
        preset_box: QComboBox = self.side_widgets[side]["preset"]
        preset_id = preset_box.currentData()
        labels = self.labels.get(spec.id, ())
        mapping, targets = backend.default_mapping(self.registry, spec.scheme, preset_id, labels)
        self._fill_mapping_table(side, labels, mapping, targets)
        self._refresh_categories()

    def _fill_mapping_table(self, side, labels, mapping, targets) -> None:
        table: QTableWidget = self.side_widgets[side]["table"]
        table.clearContents()
        table.setRowCount(0)
        table.setRowCount(len(labels))
        choices = [*targets, EXCLUDE] if EXCLUDE not in targets else list(targets)
        for row, label in enumerate(labels):
            table.setItem(row, 0, _item(label))
            box = _combo(choices, mapping.get(label), editable=True)
            box.currentTextChanged.connect(self._refresh_categories)
            table.setCellWidget(row, 1, box)
        table.resizeColumnsToContents()

    def _mapping(self, side: str) -> dict[str, str]:
        table: QTableWidget = self.side_widgets[side]["table"]
        mapping: dict[str, str] = {}
        for row in range(table.rowCount()):
            label = table.item(row, 0).text()
            widget = table.cellWidget(row, 1)
            value = widget.currentText().strip() if isinstance(widget, QComboBox) else ""
            if value:
                mapping[label] = value
        return mapping

    def _refresh_categories(self, *_: Any) -> None:
        if self._kind() != "reference" and not self.categories_edit.text().strip():
            return
        if self.categories_edit.isModified():
            return
        ordered: list[str] = []
        for side in ("A", "B"):
            for value in self._mapping(side).values():
                if value != EXCLUDE and value not in ordered:
                    ordered.append(value)
        self.categories_edit.setText(", ".join(ordered))

    def _add_cell(self, name: str = "", a: str = "", b: str = "") -> None:
        row = self.cells_table.rowCount()
        self.cells_table.insertRow(row)
        self.cells_table.setItem(row, 0, _item(name or f"cell{row + 1}", editable=True))
        self.cells_table.setItem(row, 1, _item(a, editable=True))
        self.cells_table.setItem(row, 2, _item(b, editable=True))

    def _load_existing(self, spec: ComparisonSpec) -> None:
        ids = [item.id for item in self.specs]
        self.kind_box.setCurrentIndex(0 if spec.kind == "reference" else 1)
        self.a_box.setCurrentIndex(ids.index(spec.a))
        self.b_box.setCurrentIndex(ids.index(spec.b))
        self._side_changed("A")
        self._side_changed("B")
        for side, mapping, preset_id in (
            ("A", spec.mapping_a, spec.preset_a),
            ("B", spec.mapping_b, spec.preset_b),
        ):
            box: QComboBox = self.side_widgets[side]["preset"]
            index = box.findData(preset_id) if preset_id else -1
            box.blockSignals(True)
            box.setCurrentIndex(max(index, 0))
            box.blockSignals(False)
            side_spec = self._spec(side)
            labels = self.labels.get(side_spec.id, ())
            targets = spec.categories or tuple(dict.fromkeys(mapping.values()))
            full = {label: mapping.get(label, label if not mapping else "") for label in labels}
            self._fill_mapping_table(side, labels, full, targets)
        self.categories_edit.setText(", ".join(spec.categories))
        self.categories_edit.setModified(True)
        self.positive_edit.setText(spec.positive or "")
        for cell in spec.cells:
            self._add_cell(cell.name, ", ".join(cell.labels_a), ", ".join(cell.labels_b))
        self._kind_changed()

    def build(self) -> ComparisonSpec:
        kind = self._kind()
        spec_a = self._spec("A")
        spec_b = self._spec("B")
        mapping_a = self._mapping("A")
        mapping_b = self._mapping("B")
        identity_a = all(k == v for k, v in mapping_a.items())
        identity_b = all(k == v for k, v in mapping_b.items())
        if kind == "association":
            # Identity mappings are noise for the symmetric view: drop them so the
            # table keeps raw labels, but keep explicit Exclude rows.
            if identity_a:
                mapping_a = {}
            if identity_b:
                mapping_b = {}
        categories = tuple(
            part.strip() for part in self.categories_edit.text().split(",") if part.strip()
        )
        cells = []
        for row in range(self.cells_table.rowCount()):
            name = self.cells_table.item(row, 0).text().strip()
            a = tuple(
                p.strip() for p in self.cells_table.item(row, 1).text().split(",") if p.strip()
            )
            b = tuple(
                p.strip() for p in self.cells_table.item(row, 2).text().split(",") if p.strip()
            )
            cells.append(CellSpec(name or f"cell{row + 1}", a, b))
        preset_a = self.side_widgets["A"]["preset"].currentData()
        preset_b = self.side_widgets["B"]["preset"].currentData()
        return ComparisonSpec(
            self.id_edit.text().strip() or self._next_id(),
            kind,  # type: ignore[arg-type]
            spec_a.id,
            spec_b.id,
            self.title_edit.text().strip(),
            mapping_a,
            mapping_b,
            categories if kind == "reference" else (),
            self.positive_edit.text().strip() or None,
            cells=tuple(cells) if kind == "association" else (),
            strict_macro=len(categories) > 2 if kind == "reference" else True,
            preset_a=preset_a,
            preset_b=preset_b,
        )

    def _accept(self) -> None:
        try:
            spec = self.build()
        except ProfileError as error:
            self.problems_label.setText(str(error))
            return
        problems = backend.validate_comparison(
            spec, self.labels.get(spec.a, ()), self.labels.get(spec.b, ())
        )
        if spec.id in self.used_ids:
            problems.append(f"식별자 {spec.id!r}가 이미 사용 중입니다.")
        if problems:
            self.problems_label.setText("\n".join(problems))
            return
        self.result_spec = spec
        self.accept()


class SampleSelectionDialog(QDialog):
    """Choose which sample blocks of one dataset become samples.

    Shown when a file repeats a Name (the same array measured twice, or two source
    sheets sharing a Name) or contains incomplete arrays.  Complete blocks are
    included by default under ``Name`` / ``Name #2`` …; incomplete blocks cannot be
    included; identical blocks are flagged so a duplicated sheet can be dropped.
    """

    def __init__(
        self,
        parent: QWidget | None,
        dataset_label: str,
        candidates: Sequence[SampleCandidate],
        existing: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"샘플 블록 선택 — {dataset_label}")
        self.setMinimumSize(1000, 560)
        self.candidates = list(candidates)
        self.selection: dict[str, str] = {}
        layout = QVBoxLayout(self)
        groups = backend.selection_summary(self.candidates)
        repeated = sum(1 for items in groups.values() if len(items) > 1)
        incomplete = sum(1 for item in self.candidates if not item.complete)
        intro = QLabel(
            f"이 파일에는 이름이 반복되는 샘플 {repeated}개, 불완전한 블록 {incomplete}개가 "
            "있습니다. 포함할 블록을 고르고 필요하면 샘플 이름을 바꾸세요. 같은 이름의 블록을 "
            "둘 다 포함하면 별도 샘플(#2, #3…)로 처리되고, 하나만 남기면 그 블록이 그 이름의 "
            "샘플이 됩니다. 불완전한 블록(좌표 수 부족)은 포함할 수 없습니다. "
            "'동일 내용'은 다른 블록과 좌표·라벨이 완전히 같은 경우입니다."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.only_issues = QCheckBox("문제가 있는 이름만 표시")
        self.only_issues.setChecked(True)
        self.only_issues.toggled.connect(self._refresh_visibility)
        layout.addWidget(self.only_issues)
        self.table = _table(
            (
                "포함",
                "샘플 이름",
                "원본 이름",
                "회차",
                "시트",
                "행 범위",
                "행 수",
                "좌표",
                "상태",
                "라벨 분포",
            )
        )
        layout.addWidget(self.table, 1)
        selection = dict(existing) if existing else default_sample_selection(self.candidates)
        digests: dict[str, str] = {}
        self._issue_rows: list[bool] = []
        self.table.setRowCount(len(self.candidates))
        for row, item in enumerate(self.candidates):
            group = groups[item.name]
            issue = len(group) > 1 or not item.complete
            self._issue_rows.append(issue)
            include = QCheckBox()
            include.setChecked(item.key in selection)
            include.setEnabled(item.complete)
            include.toggled.connect(self._refresh_problems)
            self.table.setCellWidget(row, 0, include)
            title = _item(selection.get(item.key, item.default_title), editable=True)
            title.setData(Qt.UserRole, item.key)
            self.table.setItem(row, 1, title)
            self.table.setItem(row, 2, _item(item.name))
            self.table.setItem(row, 3, _item(f"#{item.occurrence + 1} / {len(group)}"))
            self.table.setItem(row, 4, _item(item.worksheet))
            self.table.setItem(row, 5, _item(f"{item.first_row}–{item.last_row}"))
            self.table.setItem(row, 6, _item(str(item.row_count)))
            self.table.setItem(row, 7, _item(f"{item.unique_coordinates}/{item.grid_size}"))
            if not item.complete:
                status = "불완전"
            elif item.content_digest in digests:
                status = f"동일 내용 ({digests[item.content_digest]})"
            else:
                status = "완전"
            if item.complete:
                digests.setdefault(item.content_digest, item.default_title)
            status_item = _item(status)
            if status != "완전":
                status_item.setForeground(Qt.red if not item.complete else Qt.darkYellow)
            self.table.setItem(row, 8, status_item)
            distribution = ", ".join(
                f"{label} {count}" for label, count in sorted(item.label_counts.items())
            )
            self.table.setItem(row, 9, _item(distribution))
        self.table.itemChanged.connect(self._refresh_problems)
        self.table.resizeColumnsToContents()
        self.problems_label = QLabel()
        self.problems_label.setWordWrap(True)
        self.problems_label.setStyleSheet("color: #b00020;")
        layout.addWidget(self.problems_label)
        buttons = QHBoxLayout()
        all_complete = QPushButton("완전한 블록 모두 포함")
        first_only = QPushButton("이름마다 첫 완전 블록만")
        all_complete.clicked.connect(lambda: self._bulk(first_only=False))
        first_only.clicked.connect(lambda: self._bulk(first_only=True))
        buttons.addWidget(all_complete)
        buttons.addWidget(first_only)
        buttons.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)
        buttons.addWidget(box)
        layout.addLayout(buttons)
        self._refresh_visibility()
        self._refresh_problems()

    def _refresh_visibility(self) -> None:
        only = self.only_issues.isChecked()
        for row, issue in enumerate(self._issue_rows):
            self.table.setRowHidden(row, only and not issue)

    def _bulk(self, *, first_only: bool) -> None:
        seen: set[str] = set()
        for row, item in enumerate(self.candidates):
            box = self.table.cellWidget(row, 0)
            if not item.complete:
                box.setChecked(False)
                continue
            if first_only and item.name in seen:
                box.setChecked(False)
            else:
                box.setChecked(True)
                seen.add(item.name)
                if first_only:
                    self.table.item(row, 1).setText(item.name)
        self._refresh_problems()

    def current_selection(self) -> dict[str, str]:
        selection: dict[str, str] = {}
        for row, item in enumerate(self.candidates):
            box = self.table.cellWidget(row, 0)
            if box is not None and box.isChecked():
                selection[item.key] = self.table.item(row, 1).text().strip() or item.default_title
        return selection

    def _refresh_problems(self, *_: Any) -> None:
        problems = backend.validate_selection(self.candidates, self.current_selection())
        self.problems_label.setText("\n".join(problems))

    def _accept(self) -> None:
        selection = self.current_selection()
        problems = backend.validate_selection(self.candidates, selection)
        if problems:
            self.problems_label.setText("\n".join(problems))
            return
        self.selection = selection
        self.accept()


# -------------------------------------------------------------------- window


class WizardWindow(QMainWindow):
    """Linear report wizard.  ``test_mode`` runs backend jobs synchronously."""

    def __init__(self, *, test_mode: bool = False, registry: SchemeRegistry | None = None) -> None:
        super().__init__()
        self.test_mode = test_mode
        self.registry = registry or load_registry()
        self.load: backend.LoadResult | None = None
        self.comparisons: list[ComparisonSpec] = []
        self.cancel_event = Event()
        self._thread: _Worker | None = None
        self._pending: Callable[[Any], None] | None = None
        self._result: tuple[Any] | None = None
        self._dataset_counter = 0
        self._pending_alignments: list[tuple[str, str, str]] = []
        self._last_outputs: tuple[Path, Path | None] | None = None
        self.setWindowTitle("R2R 평가 리포트 생성기 — 단계형")
        self.setMinimumSize(1080, 720)
        self._build()
        self._go(0)

    # ---------------------------------------------------------------- layout
    def _build(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        self.step_label = QLabel()
        self.step_label.setStyleSheet("font-size: 15px; font-weight: 700;")
        root.addWidget(self.step_label)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.stack.addWidget(self._page_datasets())
        self.stack.addWidget(self._page_schemes())
        self.stack.addWidget(self._page_comparisons())
        self.stack.addWidget(self._page_output())
        self.stack.addWidget(self._page_generate())
        nav = QHBoxLayout()
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.back_button = QPushButton("이전")
        self.next_button = QPushButton("다음")
        self.back_button.clicked.connect(lambda: self._go(self.stack.currentIndex() - 1))
        self.next_button.clicked.connect(self._next)
        nav.addWidget(self.status_label, 1)
        nav.addWidget(self.back_button)
        nav.addWidget(self.next_button)
        root.addLayout(nav)

    def _page_datasets(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel(
            "비교할 파일을 모두 추가합니다. 첫 번째 행이 기준(primary) 데이터셋이며 샘플 정렬의 "
            "축이 됩니다. 측정 CSV/XLSX, R2R-Machine-Learning 예측, ImageMarker 라벨, "
            "Printed-Device-AI-Inspector 내보내기(image_path)를 지원합니다."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        buttons = QHBoxLayout()
        self.add_button = QPushButton("파일 추가…")
        remove = QPushButton("제거")
        up = QPushButton("위로")
        down = QPushButton("아래로")
        load_profile = QPushButton("프로파일 불러오기…")
        self.add_button.clicked.connect(self._add_dataset_dialog)
        remove.clicked.connect(self._remove_dataset)
        up.clicked.connect(lambda: self._move_dataset(-1))
        down.clicked.connect(lambda: self._move_dataset(1))
        load_profile.clicked.connect(self._load_profile_dialog)
        for widget in (self.add_button, remove, up, down, load_profile):
            buttons.addWidget(widget)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.dataset_table = _table(("제목", "역할", "시트", "모델 열", "행", "노드", "파일"))
        layout.addWidget(self.dataset_table, 2)
        self.preflight_button = QPushButton("불러오기·정렬 검사")
        self.preflight_button.clicked.connect(self.run_preflight)
        layout.addWidget(self.preflight_button)
        self.alignment_box = QGroupBox(
            "샘플 정렬 — 기준 데이터셋의 샘플마다 다른 데이터셋의 시트를 확인"
        )
        alignment_layout = QVBoxLayout(self.alignment_box)
        self.alignment_table = _table(("기준 샘플",))
        self.confirm_all_button = QPushButton("제안 전체 확인")
        self.confirm_all_button.clicked.connect(self._confirm_all)
        alignment_layout.addWidget(self.alignment_table)
        alignment_layout.addWidget(self.confirm_all_button)
        layout.addWidget(self.alignment_box, 2)
        self.alignment_box.setVisible(False)
        return page

    def _page_schemes(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel(
            "각 데이터셋의 라벨 체계를 확인합니다. 체계 밖 라벨이 있으면 체계를 바꾸거나 "
            "'(미등록)'을 선택해 원본 라벨 그대로 진행합니다. 체계는 label_schemes.json에서 "
            "관리합니다."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.scheme_table = _table(("데이터셋", "체계", "관측 라벨", "체계 밖 라벨"))
        layout.addWidget(self.scheme_table)
        return page

    def _page_comparisons(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel(
            "출력할 비교를 정의합니다. 비교가 없어도 공간 map과 라벨 분포만으로 리포트를 만들 수 "
            "있습니다. 자기 평가는 공통 범주 매핑이 필요하고, 교차 연관은 원본 라벨 그대로 또는 "
            "매핑 후 대칭 지표를 계산합니다."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        buttons = QHBoxLayout()
        add = QPushButton("비교 추가…")
        edit = QPushButton("편집…")
        remove = QPushButton("삭제")
        add.clicked.connect(self._add_comparison)
        edit.clicked.connect(self._edit_comparison)
        remove.clicked.connect(self._remove_comparison)
        for widget in (add, edit, remove):
            buttons.addWidget(widget)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.comparison_table = _table(("식별자", "종류", "A", "B", "제목", "상태"))
        layout.addWidget(self.comparison_table)
        return page

    def _page_output(self) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        self.title_edit = QLineEdit()
        row = QHBoxLayout()
        self.output_edit = QLineEdit()
        browse = QPushButton("찾아보기…")
        browse.clicked.connect(self._choose_output)
        row.addWidget(self.output_edit, 1)
        row.addWidget(browse)
        self.maps_check = QCheckBox("샘플별 공간 map 시트 (S01…) 포함")
        self.maps_check.setChecked(True)
        self.joined_check = QCheckBox("Joined_Data 시트 포함")
        self.joined_check.setChecked(True)
        self.color_only_check = QCheckBox("색상 전용 사본(-color-only.xlsx) 함께 생성")
        self.color_only_check.setChecked(True)
        save_profile = QPushButton("프로파일 JSON 저장…")
        save_profile.clicked.connect(self._save_profile_dialog)
        layout.addRow("리포트 제목", self.title_edit)
        layout.addRow("출력 통합문서", row)
        layout.addRow(self.maps_check)
        layout.addRow(self.joined_check)
        layout.addRow(self.color_only_check)
        layout.addRow(save_profile)
        return page

    def _page_generate(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.summary_view = QPlainTextEdit()
        self.summary_view.setReadOnly(True)
        layout.addWidget(self.summary_view, 1)
        controls = QHBoxLayout()
        self.generate_button = QPushButton("Excel 생성")
        self.cancel_button = QPushButton("취소")
        self.cancel_button.setEnabled(False)
        self.generate_button.clicked.connect(self.run_generate)
        self.cancel_button.clicked.connect(self._cancel)
        controls.addWidget(self.generate_button)
        controls.addWidget(self.cancel_button)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)
        opens = QHBoxLayout()
        self.open_workbook_button = QPushButton("통합문서 열기")
        self.open_color_button = QPushButton("색상 전용 열기")
        self.open_folder_button = QPushButton("폴더 열기")
        self.open_workbook_button.clicked.connect(lambda: self._open(0))
        self.open_color_button.clicked.connect(lambda: self._open(1))
        self.open_folder_button.clicked.connect(lambda: self._open(2))
        for widget in (self.open_workbook_button, self.open_color_button, self.open_folder_button):
            widget.hide()
            opens.addWidget(widget)
        opens.addStretch(1)
        layout.addLayout(opens)
        return page

    # ------------------------------------------------------------ navigation
    def _go(self, index: int) -> None:
        index = max(0, min(index, self.stack.count() - 1))
        self.stack.setCurrentIndex(index)
        self.step_label.setText(
            "  ›  ".join(
                f"[{title}]" if i == index else title for i, title in enumerate(STEP_TITLES)
            )
        )
        self.back_button.setEnabled(index > 0)
        self.next_button.setVisible(index < self.stack.count() - 1)
        if index == 1:
            self._refresh_scheme_table()
        elif index == 2:
            self._refresh_comparison_table()
        elif index == 4:
            self.summary_view.setPlainText(self._summary_text())
        self._refresh_next()

    def _next(self) -> None:
        message = self._blocker(self.stack.currentIndex())
        if message:
            self._error(message)
            return
        self._go(self.stack.currentIndex() + 1)

    def _blocker(self, index: int) -> str | None:
        if index == 0:
            if self.load is None:
                return "먼저 '불러오기·정렬 검사'를 실행하세요."
            if len(self.dataset_specs()) > 1 and not self.confirmed_alignments():
                return "확인된 샘플 정렬이 하나도 없습니다."
        if index == 1:
            for spec in self.dataset_specs():
                if spec.scheme and self._extra_labels(spec):
                    return (
                        f"{spec.label}: 체계 밖 라벨이 있습니다. "
                        "체계를 바꾸거나 미등록을 선택하세요."
                    )
        if index == 3:
            output = self.output_edit.text().strip()
            if not output or Path(output).suffix.casefold() != ".xlsx":
                return "출력 통합문서(.xlsx) 경로를 지정하세요."
            if not Path(output).parent.is_dir():
                return "출력 폴더를 찾을 수 없습니다."
            inputs = {Path(spec.path).resolve() for spec in self.dataset_specs()}
            if Path(output).resolve() in inputs:
                return "출력 파일은 입력 파일과 달라야 합니다."
        return None

    def _refresh_next(self) -> None:
        self.next_button.setEnabled(self._blocker(self.stack.currentIndex()) is None)

    def _invalidate_from(self, index: int) -> None:
        """Editing step ``index`` discards derived state of later steps."""
        if index <= 0:
            self.load = None
            self.alignment_table.setRowCount(0)
            self.alignment_box.setVisible(False)
        if index <= 2:
            valid = {spec.id for spec in self.dataset_specs()}
            self.comparisons = [c for c in self.comparisons if c.a in valid and c.b in valid]
        self._last_outputs = None
        self.result_label.clear()
        for widget in (self.open_workbook_button, self.open_color_button, self.open_folder_button):
            widget.hide()
        self._refresh_next()

    # ----------------------------------------------------------- step 1 data
    def add_dataset(
        self,
        path: str,
        *,
        role: str = "other",
        title: str = "",
        scheme: str | None = None,
        worksheet: str | None = None,
        model_column: str | None = None,
        grid: tuple[int, int] = (DEFAULT_GRID.rows, DEFAULT_GRID.nodes),
        dataset_id: str | None = None,
        samples: Mapping[str, str] | None = None,
    ) -> str:
        info = backend.inspect_source(path)
        existing = {spec.id for spec in self.dataset_specs()}
        if not dataset_id or dataset_id in existing:
            while True:
                self._dataset_counter += 1
                dataset_id = f"d{self._dataset_counter}"
                if dataset_id not in existing:
                    break
        row = self.dataset_table.rowCount()
        self.dataset_table.insertRow(row)
        if info.is_inspector and not model_column and info.inspector_models:
            model_column = info.inspector_models[0]
        # Inspector exports say which provider produced each column, so the
        # comparison group (cloud VLM vs Local LLM) is pre-selected from it.
        if role == "other":
            role = suggest_role(info.is_inspector, model_column) or role
        default_title = backend.default_title(path, model_column if info.is_inspector else None)
        title_item = _item(title or default_title, editable=True)
        title_item.setData(Qt.UserRole, dataset_id)
        title_item.setData(Qt.UserRole + 1, scheme)
        title_item.setData(Qt.UserRole + 2, dict(samples or {}))
        # Whether the source is an Inspector export is kept on the item: the
        # model combo's isEnabled() is False whenever the page is disabled during
        # a background job, which used to drop the model column mid-preflight.
        title_item.setData(Qt.UserRole + 3, bool(info.is_inspector))
        self.dataset_table.setItem(row, 0, title_item)
        role_box = _combo(ROLE_TITLES.values(), ROLE_TITLES.get(role, ROLE_TITLES["other"]))
        self.dataset_table.setCellWidget(row, 1, role_box)
        sheet_box = _combo([ALL_SHEETS, *info.worksheets], worksheet or ALL_SHEETS)
        sheet_box.setEnabled(info.worksheets != ("CSV",))
        self.dataset_table.setCellWidget(row, 2, sheet_box)
        model_box = _combo(info.inspector_models or ["—"], model_column)
        model_box.setEnabled(info.is_inspector)
        self.dataset_table.setCellWidget(row, 3, model_box)
        if info.is_inspector:
            model_box.currentTextChanged.connect(
                lambda text, item=title_item, box=role_box, source=path: self._model_changed(
                    item, box, source, text
                )
            )
        for col, value in ((4, grid[0]), (5, grid[1])):
            spin = QSpinBox()
            spin.setRange(1, 999)
            spin.setValue(int(value))
            spin.valueChanged.connect(lambda *_: self._invalidate_from(0))
            self.dataset_table.setCellWidget(row, col, spin)
        self.dataset_table.setItem(row, 6, _item(str(path)))
        for widget in (role_box, sheet_box, model_box):
            widget.currentIndexChanged.connect(lambda *_: self._invalidate_from(0))
        self.dataset_table.resizeColumnsToContents()
        self._invalidate_from(0)
        return dataset_id

    def _model_changed(self, title_item, role_box, path: str, model_column: str) -> None:
        """Follow a model-column change: re-suggest the comparison group and default title."""
        suggested = suggest_role(True, model_column)
        if suggested:
            role_box.setCurrentText(ROLE_TITLES[suggested])
        current = title_item.text().strip()
        defaults = {backend.default_title(path, m) for m in ("", *self._models_of(path))}
        if not current or current in defaults:
            title_item.setText(backend.default_title(path, model_column))

    def _models_of(self, path: str) -> tuple[str, ...]:
        for row in range(self.dataset_table.rowCount()):
            if self.dataset_table.item(row, 6).text() == path:
                box = self.dataset_table.cellWidget(row, 3)
                return tuple(box.itemText(i) for i in range(box.count()))
        return ()

    def dataset_specs(self) -> list[DatasetSpec]:
        specs: list[DatasetSpec] = []
        for row in range(self.dataset_table.rowCount()):
            title_item = self.dataset_table.item(row, 0)
            role_box = self.dataset_table.cellWidget(row, 1)
            sheet_box = self.dataset_table.cellWidget(row, 2)
            model_box = self.dataset_table.cellWidget(row, 3)
            role = next(
                (key for key, value in ROLE_TITLES.items() if value == role_box.currentText()),
                "other",
            )
            sheet = sheet_box.currentText()
            model = model_box.currentText() if title_item.data(Qt.UserRole + 3) else None
            specs.append(
                DatasetSpec(
                    title_item.data(Qt.UserRole),
                    self.dataset_table.item(row, 6).text(),
                    role,
                    title_item.data(Qt.UserRole + 1),
                    () if sheet == ALL_SHEETS else (sheet,),
                    self.dataset_table.cellWidget(row, 4).value(),
                    self.dataset_table.cellWidget(row, 5).value(),
                    model,
                    title_item.text().strip(),
                    dict(title_item.data(Qt.UserRole + 2) or {}),
                )
            )
        return specs

    def set_samples(self, dataset_id: str, selection: Mapping[str, str]) -> None:
        """Record the chosen sample blocks for a dataset (see SampleSelectionDialog)."""
        for row in range(self.dataset_table.rowCount()):
            item = self.dataset_table.item(row, 0)
            if item.data(Qt.UserRole) == dataset_id:
                item.setData(Qt.UserRole + 2, dict(selection))
        self._invalidate_from(0)

    def _add_dataset_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "데이터 파일 선택", "", "데이터 (*.csv *.xlsx)")
        if path:
            try:
                self.add_dataset(path)
            except Exception as error:
                self._error(f"파일을 읽을 수 없습니다: {error}")

    def _remove_dataset(self) -> None:
        row = self.dataset_table.currentRow()
        if row >= 0:
            self.dataset_table.removeRow(row)
            self._invalidate_from(0)

    def _move_dataset(self, delta: int) -> None:
        row = self.dataset_table.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < self.dataset_table.rowCount():
            return
        specs = self.dataset_specs()
        specs[row], specs[target] = specs[target], specs[row]
        self._set_dataset_specs(specs)
        self.dataset_table.selectRow(target)

    def _set_dataset_specs(self, specs: list[DatasetSpec]) -> None:
        self.dataset_table.setRowCount(0)
        for spec in specs:
            self.add_dataset(
                spec.path,
                role=spec.role,
                title=spec.title,
                scheme=spec.scheme,
                worksheet=spec.worksheets[0] if spec.worksheets else None,
                model_column=spec.model_column,
                grid=(spec.grid_rows, spec.grid_nodes),
                dataset_id=spec.id,
                samples=spec.samples,
            )

    def run_preflight(self) -> None:
        """Step 1 check: inspect sample blocks (asking when ambiguous), then load and align."""
        specs = self.dataset_specs()
        if not specs:
            self._error("데이터셋을 하나 이상 추가하세요.")
            return

        def inspect_job(progress):
            return backend.pending_sample_selections(specs, progress)

        self._run(inspect_job, self._sample_inspection_done, "샘플 블록을 검사하는 중…")

    def _sample_inspection_done(self, pending: dict[str, tuple[SampleCandidate, ...]]) -> None:
        labels = {spec.id: spec.label for spec in self.dataset_specs()}
        for dataset_id, candidates in pending.items():
            selection = self.choose_samples(dataset_id, labels[dataset_id], candidates)
            if selection is None:
                self.status_label.setText("샘플 블록 선택을 취소했습니다. 검사를 다시 실행하세요.")
                return
            self.set_samples(dataset_id, selection)
        specs = self.dataset_specs()

        def job(progress):
            return backend.load_and_propose(specs, self.registry, progress)

        self._run(job, self._preflight_done, "파일을 읽고 샘플을 정렬하는 중…")

    def choose_samples(
        self, dataset_id: str, label: str, candidates: Sequence[SampleCandidate]
    ) -> dict[str, str] | None:
        """Open the block-selection dialog; ``test_mode`` takes the default selection."""
        if self.test_mode:
            return default_sample_selection(candidates)
        dialog = SampleSelectionDialog(self, label, candidates)
        if dialog.exec() != QDialog.Accepted:
            return None
        return dialog.selection

    def _preflight_done(self, load: backend.LoadResult) -> None:
        self.load = load
        for row in range(self.dataset_table.rowCount()):
            item = self.dataset_table.item(row, 0)
            dataset_id = item.data(Qt.UserRole)
            if item.data(Qt.UserRole + 1) is None:
                item.setData(Qt.UserRole + 1, load.suggested_schemes.get(dataset_id))
        self._fill_alignment_table()
        if self._pending_alignments:
            self.set_alignments(self._pending_alignments)
            self._pending_alignments = []
        self.status_label.setText(
            f"{len(load.datasets)}개 데이터셋을 읽었습니다. "
            "샘플 정렬을 확인한 뒤 다음으로 진행하세요."
        )
        self._refresh_next()

    def set_alignments(self, confirmed: list[tuple[str, str, str]]) -> None:
        """Select ``(dataset_id, primary_sample, member_sheet)`` triples in the alignment table."""
        specs = self.dataset_specs()
        columns = {spec.id: index for index, spec in enumerate(specs[1:], 1)}
        for dataset_id, sample, sheet in confirmed:
            column = columns.get(dataset_id)
            if column is None:
                continue
            for r in range(self.alignment_table.rowCount()):
                if self.alignment_table.item(r, 0).text() == sample:
                    box = self.alignment_table.cellWidget(r, column)
                    if box is not None and box.findText(sheet) >= 0:
                        box.setCurrentText(sheet)
        self._refresh_next()

    def _fill_alignment_table(self) -> None:
        specs = self.dataset_specs()
        assert self.load is not None
        rows = backend.alignment_rows(specs, self.load.datasets, self.load)
        headers = ["기준 샘플", *[spec.label for spec in specs[1:]]]
        self.alignment_table.clearContents()
        self.alignment_table.setRowCount(0)
        self.alignment_table.setColumnCount(len(headers))
        self.alignment_table.setHorizontalHeaderLabels(headers)
        self.alignment_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self.alignment_table.setItem(r, 0, _item(row["sample"]))
            for c, spec in enumerate(specs[1:], 1):
                choices = [NO_MEMBER, *backend.member_choices(spec, self.load.datasets)]
                suggested = row["members"][spec.id]
                box = _combo(choices, suggested if row["auto"][spec.id] else NO_MEMBER)
                box.setProperty("suggested", suggested)
                box.setToolTip(
                    f"제안: {suggested}" + ("" if row["auto"][spec.id] else " (확인 필요)")
                    if suggested
                    else "제안 없음"
                )
                box.currentIndexChanged.connect(lambda *_: self._refresh_next())
                self.alignment_table.setCellWidget(r, c, box)
        self.alignment_table.resizeColumnsToContents()
        self.alignment_box.setVisible(len(specs) > 1)

    def _confirm_all(self) -> None:
        for r in range(self.alignment_table.rowCount()):
            for c in range(1, self.alignment_table.columnCount()):
                box = self.alignment_table.cellWidget(r, c)
                suggested = box.property("suggested")
                if suggested:
                    box.setCurrentText(suggested)
        self._refresh_next()

    def confirmed_alignments(self) -> list[tuple[str, str, str]]:
        specs = self.dataset_specs()
        confirmed: list[tuple[str, str, str]] = []
        for r in range(self.alignment_table.rowCount()):
            sample = self.alignment_table.item(r, 0).text()
            for c, spec in enumerate(specs[1:], 1):
                box = self.alignment_table.cellWidget(r, c)
                if box is not None and box.currentText() != NO_MEMBER:
                    confirmed.append((spec.id, sample, box.currentText()))
        return confirmed

    # -------------------------------------------------------- step 2 schemes
    def _extra_labels(self, spec: DatasetSpec) -> tuple[str, ...]:
        if not spec.scheme or self.load is None:
            return ()
        scheme = self.registry.scheme(spec.scheme)
        return tuple(
            label
            for label in self.load.raw_labels.get(spec.id, ())
            if scheme.canonical(label) is None
        )

    def _refresh_scheme_table(self) -> None:
        specs = self.dataset_specs()
        self.scheme_table.clearContents()
        self.scheme_table.setRowCount(0)
        self.scheme_table.setRowCount(len(specs))
        for row, spec in enumerate(specs):
            self.scheme_table.setItem(row, 0, _item(spec.label))
            box = QComboBox()
            box.addItem(NO_SCHEME, None)
            for scheme in self.registry.schemes.values():
                box.addItem(f"{scheme.id} — {scheme.title}", scheme.id)
            box.setCurrentIndex(max(box.findData(spec.scheme), 0))
            box.currentIndexChanged.connect(lambda _i, r=row: self._scheme_changed(r))
            self.scheme_table.setCellWidget(row, 1, box)
            labels = self.load.raw_labels.get(spec.id, ()) if self.load else ()
            self.scheme_table.setItem(row, 2, _item(", ".join(labels)))
            extra = _item(", ".join(self._extra_labels(spec)))
            if extra.text():
                extra.setForeground(Qt.red)
            self.scheme_table.setItem(row, 3, extra)
        self.scheme_table.resizeColumnsToContents()

    def _scheme_changed(self, row: int) -> None:
        box = self.scheme_table.cellWidget(row, 1)
        self.dataset_table.item(row, 0).setData(Qt.UserRole + 1, box.currentData())
        self._invalidate_from(2)
        self._refresh_scheme_table()

    def set_scheme(self, dataset_id: str, scheme_id: str | None) -> None:
        for row in range(self.dataset_table.rowCount()):
            item = self.dataset_table.item(row, 0)
            if item.data(Qt.UserRole) == dataset_id:
                item.setData(Qt.UserRole + 1, scheme_id)
        self._invalidate_from(2)

    # ---------------------------------------------------- step 3 comparisons
    def _labels_by_dataset(self) -> dict[str, tuple[str, ...]]:
        if self.load is None:
            return {}
        return label_orders(
            ReportProfile(tuple(self.dataset_specs())), self.load.datasets, self.registry
        )

    def _refresh_comparison_table(self) -> None:
        specs = {spec.id: spec for spec in self.dataset_specs()}
        labels = self._labels_by_dataset()
        self.comparison_table.setRowCount(len(self.comparisons))
        for row, spec in enumerate(self.comparisons):
            problems = backend.validate_comparison(
                spec, labels.get(spec.a, ()), labels.get(spec.b, ())
            )
            values = (
                spec.id,
                KIND_TITLES[spec.kind],
                specs[spec.a].label,
                specs[spec.b].label,
                spec.title,
                "확인" if not problems else "; ".join(problems),
            )
            for col, value in enumerate(values):
                item = _item(value)
                if col == 5 and problems:
                    item.setForeground(Qt.red)
                self.comparison_table.setItem(row, col, item)
        self.comparison_table.resizeColumnsToContents()
        self._refresh_next()

    def add_comparison(self, spec: ComparisonSpec) -> None:
        if any(item.id == spec.id for item in self.comparisons):
            raise ProfileError(f"comparison id {spec.id!r} already exists")
        self.comparisons.append(spec)
        self._invalidate_from(3)
        self._refresh_comparison_table()

    def _add_comparison(self) -> None:
        specs = self.dataset_specs()
        if len(specs) < 2:
            self._error("비교하려면 데이터셋이 두 개 이상 필요합니다.")
            return
        dialog = ComparisonDialog(
            self,
            specs,
            self._labels_by_dataset(),
            self.registry,
            used_ids={item.id for item in self.comparisons},
        )
        if dialog.exec() == QDialog.Accepted and dialog.result_spec is not None:
            self.add_comparison(dialog.result_spec)

    def _edit_comparison(self) -> None:
        row = self.comparison_table.currentRow()
        if row < 0:
            return
        current = self.comparisons[row]
        dialog = ComparisonDialog(
            self,
            self.dataset_specs(),
            self._labels_by_dataset(),
            self.registry,
            current,
            used_ids={item.id for item in self.comparisons if item.id != current.id},
        )
        if dialog.exec() == QDialog.Accepted and dialog.result_spec is not None:
            self.comparisons[row] = dialog.result_spec
            self._invalidate_from(3)
            self._refresh_comparison_table()

    def _remove_comparison(self) -> None:
        row = self.comparison_table.currentRow()
        if 0 <= row < len(self.comparisons):
            del self.comparisons[row]
            self._invalidate_from(3)
            self._refresh_comparison_table()

    # ---------------------------------------------------------- step 4 output
    def _choose_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "출력 통합문서 저장", "", "Excel (*.xlsx)")
        if path:
            self.output_edit.setText(path if path.casefold().endswith(".xlsx") else f"{path}.xlsx")
            self._refresh_next()

    def build_profile(self) -> ReportProfile:
        specs = self.dataset_specs()
        base = ReportProfile(tuple(specs))
        primary_samples = [
            self.alignment_table.item(r, 0).text() for r in range(self.alignment_table.rowCount())
        ]
        if not primary_samples and self.load is not None:
            primary_samples = [sheet.title for sheet in self.load.datasets[specs[0].id].sheets]
        alignments = backend.build_alignments(base, self.confirmed_alignments(), primary_samples)
        return ReportProfile(
            tuple(specs),
            tuple(self.comparisons),
            alignments,
            ProfileOptions(
                self.title_edit.text().strip(),
                self.maps_check.isChecked(),
                self.color_only_check.isChecked(),
                self.joined_check.isChecked(),
            ),
        )

    def _save_profile_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "프로파일 저장", "", "JSON (*.json)")
        if path:
            try:
                self.build_profile().save(path)
                self.status_label.setText(f"프로파일을 저장했습니다: {path}")
            except Exception as error:
                self._error(str(error))

    def _load_profile_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "프로파일 불러오기", "", "JSON (*.json)")
        if path:
            try:
                self.apply_profile(ReportProfile.load(path))
            except Exception as error:
                self._error(str(error))

    def apply_profile(self, profile: ReportProfile) -> None:
        """Prefill every step from a saved profile (alignments re-confirmed after preflight)."""
        self._set_dataset_specs(list(profile.datasets))
        primary_id = profile.primary.id
        self._pending_alignments = [
            (dataset_id, alignment.sample, sheet)
            for alignment in profile.alignments
            for dataset_id, sheet in alignment.members.items()
            if dataset_id != primary_id
        ]
        self.comparisons = list(profile.comparisons)
        self.title_edit.setText(profile.options.title)
        self.maps_check.setChecked(profile.options.spatial_maps)
        self.joined_check.setChecked(profile.options.joined_data)
        self.color_only_check.setChecked(profile.options.color_only_copy)
        self.status_label.setText("프로파일을 불러왔습니다. '불러오기·정렬 검사'를 실행하세요.")

    # -------------------------------------------------------- step 5 generate
    def _summary_text(self) -> str:
        try:
            profile = self.build_profile()
        except ProfileError as error:
            return f"프로파일 오류: {error}"
        lines = [f"리포트 제목: {profile.options.title or '(없음)'}", "", "데이터셋:"]
        for spec in profile.datasets:
            lines.append(
                f"  - {spec.label} [{ROLE_TITLES.get(spec.role, spec.role)}] "
                f"체계={spec.scheme or '미등록'} 격자={spec.grid_rows}x{spec.grid_nodes}"
                f" — {spec.path}"
            )
        lines += ["", f"정렬된 샘플: {len(profile.alignments)}", "", "비교:"]
        if not profile.comparisons:
            lines.append("  (없음 — map과 라벨 분포만 출력)")
        for spec in profile.comparisons:
            lines.append(f"  - {spec.id} [{KIND_TITLES[spec.kind]}] {spec.title}")
        lines += ["", f"출력: {self.output_edit.text().strip()}"]
        if profile.options.color_only_copy:
            lines.append(f"색상 전용: {derive_color_only_path(self.output_edit.text().strip())}")
        lines.append(
            f"프로파일 JSON: {Path(self.output_edit.text().strip()).with_suffix('.profile.json')}"
        )
        return "\n".join(lines)

    def run_generate(self) -> None:
        if self.load is None:
            self._error("데이터셋을 다시 불러오세요.")
            return
        try:
            profile = self.build_profile()
        except ProfileError as error:
            self._error(str(error))
            return
        output = Path(self.output_edit.text().strip())
        existing = [p for p in (output, derive_color_only_path(output)) if p.exists()]
        if existing and not self.test_mode:
            answer = QMessageBox.question(
                self,
                "기존 파일 덮어쓰기",
                "다음 파일을 덮어쓸까요?\n" + "\n".join(map(str, existing)),
            )
            if answer != QMessageBox.Yes:
                return
        datasets = self.load.datasets
        self.cancel_event = Event()
        cancel = self.cancel_event

        def job(progress):
            return backend.generate(
                profile,
                datasets,
                output,
                cancel_event=cancel,
                progress=progress,
                registry=self.registry,
            )

        self._run(job, self._generate_done, "Excel 통합문서를 생성하는 중…")

    def _generate_done(self, outputs: tuple[Path, Path | None]) -> None:
        self._last_outputs = outputs
        with_codes, color_only = outputs
        text = f"생성 완료:\n코드 포함: {with_codes}"
        if color_only:
            text += f"\n색상 전용: {color_only}"
        text += f"\n프로파일: {with_codes.with_suffix('.profile.json')}"
        self.result_label.setText(text)
        self.open_workbook_button.show()
        self.open_color_button.setVisible(color_only is not None)
        self.open_folder_button.show()

    def _open(self, which: int) -> None:
        if not self._last_outputs:
            return
        with_codes, color_only = self._last_outputs
        target = (with_codes, color_only, with_codes.parent)[which]
        if target:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    # ------------------------------------------------------------- plumbing
    def _run(self, job, done: Callable[[Any], None], status: str) -> None:
        if self._thread is not None:
            self._error("이전 작업이 끝나기를 기다리세요.")
            return
        self.status_label.setText(status)
        self._set_busy(True)
        if self.test_mode:
            try:
                result = job(lambda v, t: self.progress.setValue(int(v)))
            except backend.GenerationCancelled:
                self._failed("작업을 취소했습니다.")
            except Exception as error:
                self._failed(str(error))
            else:
                before = self.status_label.text()
                done(result)
                if self.status_label.text() == before:
                    self.status_label.setText("완료했습니다.")
            finally:
                self._set_busy(False)
            return
        self._pending = done
        self._thread = _Worker(job)
        self._thread.progress.connect(self._progress, Qt.QueuedConnection)
        self._thread.succeeded.connect(self._succeeded, Qt.QueuedConnection)
        self._thread.failed.connect(self._failed, Qt.QueuedConnection)
        self._thread.finished.connect(self._cleanup, Qt.QueuedConnection)
        self._thread.start()

    @Slot(int, str)
    def _progress(self, value: int, text: str) -> None:
        self.progress.setValue(value)
        if not self.cancel_event.is_set():
            self.status_label.setText(text)

    @Slot(object)
    def _succeeded(self, result: object) -> None:
        # Delivered from _cleanup, once the worker thread is released: the
        # continuation may start the next job (preflight = inspect, then load),
        # and _run refuses to start while self._thread is still set.
        self._result = (result,)

    @Slot(str)
    def _failed(self, message: str) -> None:
        self._pending = None
        self._result = None
        self.status_label.setText(message)
        if message != "작업을 취소했습니다.":
            self._error(message)

    def _cleanup(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = None
        pending, result = self._pending, self._result
        self._pending = None
        self._result = None
        self._set_busy(False)
        if pending is not None and result is not None:
            before = self.status_label.text()
            pending(result[0])
            if self.status_label.text() == before:
                self.status_label.setText("완료했습니다.")

    def _set_busy(self, busy: bool) -> None:
        for widget in (
            self.stack,
            self.back_button,
            self.next_button,
            self.generate_button,
            self.preflight_button,
        ):
            widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        if not busy:
            self._refresh_next()

    def _cancel(self) -> None:
        self.cancel_event.set()
        self.cancel_button.setEnabled(False)
        self.status_label.setText("취소 요청을 보냈습니다…")

    def _error(self, message: str) -> None:
        self.status_label.setText(message)
        if not self.test_mode:
            QMessageBox.warning(self, "확인 필요", message)


def run_wizard(argv: list[str] | None = None, *, smoke_test: bool = False) -> int:
    app = QApplication.instance() or QApplication(argv or [])
    window = WizardWindow()
    window.show()
    if smoke_test:
        QTimer.singleShot(1500, app.quit)
    return app.exec()
