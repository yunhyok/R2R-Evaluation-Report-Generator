"""Capture deterministic source-UI screenshots after a real-data preflight."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from threading import Event

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QCheckBox, QScrollArea

from r2r_evaluation_report.gui import CoreWorkflowAdapter, MainWindow, WorkflowContext


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("measurement", type=Path)
    parser.add_argument("prediction", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("capture_dir", type=Path)
    parser.add_argument("--scale-label", default="100")
    args = parser.parse_args()

    args.capture_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    adapter = CoreWorkflowAdapter()
    window = MainWindow(adapter=adapter, test_mode=True)
    window.resize(1180, 860)
    window.measurement_edit.setText(str(args.measurement.resolve()))
    window.prediction_edit.setText(str(args.prediction.resolve()))
    window.output_edit.setText(str(args.output.resolve()))
    context = WorkflowContext(
        str(args.measurement.resolve()),
        str(args.prediction.resolve()),
        str(args.output.resolve()),
        None,
        None,
        [],
        [],
        Event(),
        lambda _value, _message: None,
    )
    result = adapter.preflight(context)
    window._apply_preflight(result)
    for row in range(window.mapping_table.rowCount()):
        checkbox = window.mapping_table.cellWidget(row, 3)
        if isinstance(checkbox, QCheckBox) and checkbox.isEnabled():
            checkbox.setChecked(True)
    window._refresh_generate_state()
    window.progress_bar.setValue(100)
    window.status_label.setText("사전 검사가 완료되었습니다.")
    window.show()
    app.processEvents()

    scroll = window.findChild(QScrollArea)
    if scroll is None:
        raise RuntimeError("main scroll area not found")
    top_path = args.capture_dir / f"ui-{args.scale_label}-top.png"
    bottom_path = args.capture_dir / f"ui-{args.scale_label}-bottom.png"
    if not window.grab().save(str(top_path)):
        raise RuntimeError(f"failed to save {top_path}")
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    app.processEvents()
    if not window.grab().save(str(bottom_path)):
        raise RuntimeError(f"failed to save {bottom_path}")

    print(
        json.dumps(
            {
                "qt_scale_factor": os.environ.get("QT_SCALE_FACTOR", "1"),
                "device_pixel_ratio": window.devicePixelRatioF(),
                "logical_size": [window.width(), window.height()],
                "scroll_maximum": scroll.verticalScrollBar().maximum(),
                "mapping_rows": window.mapping_table.rowCount(),
                "label_rows": window.label_table.rowCount(),
                "generate_enabled": window.generate_button.isEnabled(),
                "top": str(top_path.resolve()),
                "bottom": str(bottom_path.resolve()),
            },
            ensure_ascii=False,
        )
    )
    window.close()
    QCoreApplication.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
