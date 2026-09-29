"""Openpyxl-only, auditable workbook rendering for R2R evaluations.

The renderer consumes the public evaluation result by attribute or mapping key.
It intentionally avoids importing the core dataclasses so the workbook layer can
also be exercised with small duck-typed fixtures.
"""

from __future__ import annotations

import os
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.pagebreak import Break

ROWS = 26
NODES = 38
MAP_HEADING_ROWS = (8, 43, 78, 113)
MAP_BODY_ROWS = (9, 44, 79, 114)
REPORT_TITLES = ("Measurement", "Prediction", "Binary Agreement", "Expanded Normal scenario")
THREE_LABELS = ("Normal", "Open", "Short")
BINARY_LABELS = ("Pass", "Fail")
JOINED_HEADERS = (
    "Sample Name",
    "Row",
    "Node",
    "Measurement Raw",
    "Canonical",
    "Prediction",
    "P(Normal)",
    "P(Open)",
    "P(Short)",
    "Measurement Binary",
    "Prediction Binary",
    "Agreement",
    "Source Row",
    "Expanded Normal Actual",
    "Expanded Normal Agreement",
    "Expanded Normal Result",
)

MEASUREMENT_STYLES = {
    "Pass": ("P", "00FFFF"),
    "No Active": ("NA", "00B0F0"),
    "Short": ("S", "FFC000"),
    "None": ("N", "FF0000"),
    "Open": ("O", "FF00FF"),
    "No Gate Effect": ("NG", "7030A0"),
}
PREDICTION_STYLES = {
    "Normal": ("N", "00FFFF"),
    "Open": ("O", "FF00FF"),
    "Short": ("S", "FFC000"),
}
AGREEMENT_STYLES = {
    "TP": ("TP", "92D050"),
    "TN": ("TN", "00FFFF"),
    "FP": ("FP", "FFC000"),
    "FN": ("FN", "FF0000"),
    "N/A": ("N/A", "D9EAD3"),
}
UNKNOWN_STYLE = ("?", "D9EAD3")

THIN = Side(style="thin", color="808080")
MAP_BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
SECTION_FILL = PatternFill("solid", fgColor="D9EAF7")
HEADER_FONT = Font(color="FFFFFF", bold=True)


class WorkbookCancelled(RuntimeError):
    """Raised without replacing an existing output when export is cancelled."""


def derive_color_only_path(output_path: str | Path) -> Path:
    """Return the deterministic sibling used for the fills-only workbook."""
    output = Path(output_path)
    suffix = ".xlsx" if output.suffix.lower() == ".xlsx" else output.suffix or ".xlsx"
    stem = output.stem if output.suffix else output.name
    return output.with_name(f"{stem}-color-only{suffix}")


def _value(item: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(item, Mapping) and name in item:
            return item[name]
        if hasattr(item, name):
            return getattr(item, name)
    return default


def _items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return list(value.values())
    if isinstance(value, str | bytes):
        return []
    try:
        return list(value)
    except TypeError:
        return [value]


def _text(value: Any, default: str = "") -> str:
    return default if value is None else str(value).strip()


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKC", _text(value)).casefold()
    return re.sub(r"[^a-z0-9]+", "", text)


def _samples(evaluation: Any) -> list[Any]:
    for field in (
        "sheet_evaluations",
        "sample_results",
        "samples",
        "sheets",
        "reports",
        "evaluations",
    ):
        value = _value(evaluation, field)
        if value is not None:
            return _items(value)
    return [evaluation] if _records(evaluation) else []


def _records(sample: Any) -> list[Any]:
    for field in ("joined", "joined_rows", "records", "rows", "data"):
        value = _value(sample, field)
        if value is not None:
            return _items(value)
    return []


def _sample_name(sample: Any, index: int) -> str:
    return _text(
        _value(
            sample,
            "measurement_sheet",
            "sample_name",
            "name",
            "sheet_name",
            "display_name",
        ),
        f"Sample {index}",
    )


def _nested_record(row: Any, field: str) -> Any | None:
    candidate = _value(row, field)
    if isinstance(candidate, Mapping) or (
        candidate is not None and hasattr(candidate, "value") and hasattr(candidate, "row")
    ):
        return candidate
    return None


def _has_joined_sides(row: Any) -> bool:
    return (
        isinstance(row, Mapping)
        and ("measurement" in row or "prediction" in row)
        or (hasattr(row, "measurement") and hasattr(row, "prediction"))
    )


def _raw_measurement(row: Any) -> str:
    measurement = _nested_record(row, "measurement")
    if measurement is not None:
        return _text(_value(measurement, "value", "status"), "N/A")
    return _text(
        _value(
            row,
            "measurement_raw",
            "raw_status",
            "status",
            "measurement_status",
            "actual_raw",
        ),
        "N/A",
    )


def _prediction(row: Any) -> str:
    prediction = _nested_record(row, "prediction")
    if prediction is not None:
        return _text(_value(prediction, "value"), "N/A")
    return _text(
        _value(row, "prediction", "predicted", "predicted_class", "class_name"),
        "N/A",
    )


def _profile_maps(evaluation: Any) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    profile = _value(evaluation, "status_mapping", "mapping_profile")
    three = _value(profile, "three_class", default={}) if profile is not None else {}
    binary = _value(profile, "binary", default={}) if profile is not None else {}
    expanded = (
        _value(profile, "expanded_normal", "expanded", default={})
        if profile is not None
        else {}
    )
    direct_binary = _value(evaluation, "binary_status_mapping", default={})
    if not binary and direct_binary:
        binary = direct_binary
    defaults_three = {
        "pass": "Normal",
        "noactive": "Normal",
        "none": "Normal",
        "open": "Open",
        "short": "Short",
        "nogateeffect": "Exclude",
    }
    defaults_binary = {
        "pass": "Pass",
        "noactive": "Fail",
        "none": "Fail",
        "open": "Fail",
        "short": "Fail",
        "nogateeffect": "Fail",
    }
    defaults_expanded = {
        "pass": "Normal",
        "noactive": "Normal",
        "none": "Normal",
        "open": "Open",
        "short": "Short",
        "nogateeffect": "Normal",
    }
    resolved_three = dict(defaults_three)
    resolved_binary = dict(defaults_binary)
    resolved_expanded = dict(defaults_expanded)
    if isinstance(three, Mapping):
        resolved_three.update({_norm(key): _text(value) for key, value in three.items()})
    if isinstance(binary, Mapping):
        resolved_binary.update({_norm(key): _text(value) for key, value in binary.items()})
    if isinstance(expanded, Mapping):
        resolved_expanded.update({_norm(key): _text(value) for key, value in expanded.items()})
    return resolved_three, resolved_binary, resolved_expanded


def _canonical(row: Any, evaluation: Any) -> str:
    explicit = _text(_value(row, "canonical", "actual", "measurement_class", "mapped_actual"))
    if explicit:
        return explicit
    raw = _raw_measurement(row)
    if raw == "N/A":
        return "N/A"
    three, _binary, _expanded = _profile_maps(evaluation)
    return three.get(_norm(raw), "N/A")


def _complete_pair(row: Any) -> bool:
    if _has_joined_sides(row):
        return (
            _nested_record(row, "measurement") is not None
            and _nested_record(row, "prediction") is not None
        )
    return _raw_measurement(row) != "N/A" and _prediction(row) != "N/A"


def _binary_actual(row: Any, evaluation: Any) -> str:
    explicit = _text(_value(row, "actual_binary", "measurement_binary", "binary_actual"))
    if explicit:
        return explicit
    if not _complete_pair(row):
        return "N/A"
    raw = _raw_measurement(row)
    _three, binary, _expanded = _profile_maps(evaluation)
    mapped = binary.get(_norm(raw))
    if mapped in BINARY_LABELS:
        return mapped
    return "Pass" if _norm(raw) == "pass" else "Fail"


def _binary_predicted(row: Any) -> str:
    explicit = _text(_value(row, "predicted_binary", "prediction_binary", "binary_prediction"))
    if explicit:
        return explicit
    if not _complete_pair(row):
        return "N/A"
    predicted = _prediction(row)
    if predicted == "Normal":
        return "Pass"
    if predicted in {"Open", "Short"}:
        return "Fail"
    return "N/A"


def _expanded_actual(row: Any, evaluation: Any) -> str:
    explicit = _text(_value(row, "expanded_normal_actual", "expanded_actual"))
    if explicit:
        return explicit
    if not _complete_pair(row):
        return "N/A"
    raw = _raw_measurement(row)
    _three, _binary, expanded = _profile_maps(evaluation)
    mapped = expanded.get(_norm(raw))
    return mapped if mapped in THREE_LABELS else "N/A"


def _expanded_agreement(row: Any, evaluation: Any) -> str:
    explicit = _text(_value(row, "expanded_normal_agreement", "expanded_agreement"))
    if explicit:
        return explicit
    actual = _expanded_actual(row, evaluation)
    predicted = _prediction(row)
    if actual not in THREE_LABELS or predicted not in THREE_LABELS:
        return "N/A"
    return "Agree" if actual == predicted else "Disagree"


def _agreement(row: Any, evaluation: Any) -> str:
    explicit = _text(_value(row, "agreement", "binary_agreement"))
    if explicit:
        return explicit
    actual = _binary_actual(row, evaluation)
    predicted = _binary_predicted(row)
    if "N/A" in {actual, predicted}:
        return "N/A"
    return {
        ("Fail", "Fail"): "TP",
        ("Pass", "Pass"): "TN",
        ("Pass", "Fail"): "FP",
        ("Fail", "Pass"): "FN",
    }[(actual, predicted)]


def _coordinate(row: Any) -> tuple[int | None, int | None]:
    item = _nested_record(row, "measurement") or _nested_record(row, "prediction") or row
    try:
        row_index = int(_value(item, "row", "row_index", "Row"))
        node_index = int(_value(item, "node", "node_index", "Node"))
    except (TypeError, ValueError):
        return None, None
    if not 1 <= row_index <= ROWS or not 1 <= node_index <= NODES:
        return None, None
    return row_index, node_index


def _probability(row: Any, key: str) -> Any:
    item = _nested_record(row, "prediction") or row
    probabilities = _value(item, "probabilities", "probs", default={}) or {}
    default = ""
    if isinstance(probabilities, Mapping):
        default = probabilities.get(key, probabilities.get(key.lower(), ""))
    return _value(item, f"prob_{key.lower()}", f"p_{key.lower()}", default=default)


def _source_row(row: Any) -> Any:
    item = _nested_record(row, "measurement") or _nested_record(row, "prediction") or row
    return _value(item, "source_row", "source_index", "line_number", "input_row")


def _fill(color: str) -> PatternFill:
    return PatternFill("solid", fgColor=color)


def _set_section(cell: Any, title: str) -> None:
    cell.value = title
    cell.font = Font(bold=True)
    cell.fill = SECTION_FILL


def _title(ws: Any, text: str, end_column: str = "BM") -> None:
    ws.merge_cells(f"A1:{end_column}1")
    cell = ws["A1"]
    cell.value = text
    cell.font = Font(size=16, bold=True, color="FFFFFF")
    cell.fill = HEADER_FILL
    cell.alignment = Alignment(horizontal="left")


def _style_header_row(ws: Any, row: int, start_col: int, end_col: int) -> None:
    for cell in ws.iter_cols(
        min_col=start_col,
        max_col=end_col,
        min_row=row,
        max_row=row,
    ):
        cell[0].fill = HEADER_FILL
        cell[0].font = HEADER_FONT
        cell[0].alignment = Alignment(horizontal="center", vertical="center")


def _style_map_area(ws: Any, heading_row: int, body_row: int, title: str) -> None:
    _set_section(ws.cell(heading_row - 1, 3), title)
    top_left = ws.cell(heading_row, 3, "Row / Node")
    top_left.font = Font(bold=True, size=8)
    top_left.border = MAP_BORDER
    top_left.alignment = Alignment(horizontal="center", vertical="center")
    for node in range(1, NODES + 1):
        cell = ws.cell(heading_row, 3 + node, node)
        cell.font = Font(bold=True, size=8)
        cell.border = MAP_BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for row_index in range(1, ROWS + 1):
        label = ws.cell(body_row + row_index - 1, 3, row_index)
        label.font = Font(bold=True, size=8)
        label.border = MAP_BORDER
        label.alignment = Alignment(horizontal="center", vertical="center")
        for node in range(1, NODES + 1):
            cell = ws.cell(body_row + row_index - 1, 3 + node)
            cell.border = MAP_BORDER
            cell.alignment = Alignment(horizontal="center", vertical="center")
    for col in range(3, 42):
        ws.column_dimensions[get_column_letter(col)].width = 2.5
    for row in range(heading_row, body_row + ROWS):
        ws.row_dimensions[row].height = 17


def _write_map(
    ws: Any,
    body_row: int,
    values: Mapping[tuple[int, int], tuple[str, str]],
    *,
    show_codes: bool = True,
) -> None:
    for (row_index, node_index), (code, color) in values.items():
        cell = ws.cell(body_row + row_index - 1, 3 + node_index)
        cell.value = code if show_codes else None
        cell.fill = _fill(color)
        cell.font = Font(size=7, bold=True)


def _write_legend(
    ws: Any,
    start_row: int,
    start_col: int,
    title: str,
    styles: Mapping[str, tuple[str, str]],
) -> None:
    _set_section(ws.cell(start_row, start_col), title)
    for offset, (label, (code, color)) in enumerate(styles.items(), 1):
        code_cell = ws.cell(start_row + offset, start_col, code)
        code_cell.fill = _fill(color)
        code_cell.font = Font(bold=True)
        code_cell.alignment = Alignment(horizontal="center")
        ws.cell(start_row + offset, start_col + 1, label)


def _write_matrix(
    ws: Any,
    start_row: int,
    start_col: int,
    title: str,
    row_labels: Sequence[str],
    column_labels: Sequence[str],
    counts: Mapping[tuple[str, str], int],
) -> tuple[int, int]:
    _set_section(ws.cell(start_row, start_col), title)
    header_row = start_row + 1
    ws.cell(header_row, start_col, "Actual / Pred")
    for offset, label in enumerate(column_labels, 1):
        ws.cell(header_row, start_col + offset, label)
    for row_offset, actual in enumerate(row_labels, 1):
        ws.cell(header_row + row_offset, start_col, actual)
        for col_offset, predicted in enumerate(column_labels, 1):
            ws.cell(
                header_row + row_offset,
                start_col + col_offset,
                int(counts.get((actual, predicted), 0)),
            )
    end_row = header_row + len(row_labels)
    end_col = start_col + len(column_labels)
    for row in ws.iter_rows(
        min_row=header_row,
        max_row=end_row,
        min_col=start_col,
        max_col=end_col,
    ):
        for cell in row:
            cell.border = MAP_BORDER
            cell.alignment = Alignment(horizontal="center")
    return end_row, end_col


def _safe_divide(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _wilson(successes: int, total: int) -> tuple[float, float] | None:
    if not total:
        return None
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    spread = (
        z * ((proportion * (1 - proportion) + z * z / (4 * total)) / total) ** 0.5 / denominator
    )
    return max(0.0, centre - spread), min(1.0, centre + spread)


def _fallback_metrics(
    rows: Sequence[Any],
    evaluation: Any,
    labels: Sequence[str],
    binary: bool,
    expanded: bool = False,
) -> dict[str, Any]:
    pairs: list[tuple[str, str]] = []
    for row in rows:
        if binary:
            actual, predicted = _binary_actual(row, evaluation), _binary_predicted(row)
        else:
            actual = _expanded_actual(row, evaluation) if expanded else _canonical(row, evaluation)
            predicted = _prediction(row)
        if actual in labels and predicted in labels:
            pairs.append((actual, predicted))
    index = {label: position for position, label in enumerate(labels)}
    matrix = [[0 for _ in labels] for _ in labels]
    for actual, predicted in pairs:
        matrix[index[actual]][index[predicted]] += 1
    total = len(pairs)
    correct = sum(matrix[pos][pos] for pos in range(len(labels)))
    per_class: list[dict[str, Any]] = []
    f1s: list[float] = []
    recalls: list[float] = []
    weighted = 0.0
    for position, label in enumerate(labels):
        tp = matrix[position][position]
        support = sum(matrix[position])
        fn = support - tp
        fp = sum(row[position] for row in matrix) - tp
        tn = total - tp - fn - fp
        precision = _safe_divide(tp, tp + fp)
        recall = _safe_divide(tp, support)
        f1 = (
            None
            if precision is None or recall is None or precision + recall == 0
            else 2 * precision * recall / (precision + recall)
        )
        specificity = _safe_divide(tn, tn + fp)
        per_class.append(
            {
                "label": label,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "support": support,
                "specificity": specificity,
                "false_positive_rate": None if specificity is None else 1 - specificity,
                "false_negative_rate": _safe_divide(fn, fn + tp),
                "recall_ci95": _wilson(tp, support),
            }
        )
        if recall is not None:
            recalls.append(recall)
        if f1 is not None:
            f1s.append(f1)
            weighted += f1 * support
    return {
        "labels": tuple(labels),
        "matrix": tuple(tuple(row) for row in matrix),
        "accuracy": _safe_divide(correct, total),
        "accuracy_ci95": _wilson(correct, total),
        "balanced_accuracy": sum(recalls) / len(recalls) if recalls else None,
        "macro_f1": sum(f1s) / len(f1s) if f1s else None,
        "weighted_f1": weighted / total if total else None,
        "per_class": tuple(per_class),
        "total": total,
    }


def _fallback_yield(rows: Sequence[Any], evaluation: Any) -> dict[str, Any]:
    complete = [row for row in rows if _complete_pair(row)]
    measurement_passes = sum(_binary_actual(row, evaluation) == "Pass" for row in complete)
    prediction_passes = sum(_binary_predicted(row) == "Pass" for row in complete)
    total = len(complete)
    return {
        "total": total,
        "measurement_pass_count": measurement_passes,
        "measurement_pass_rate": _safe_divide(measurement_passes, total),
        "measurement_pass_ci95": _wilson(measurement_passes, total),
        "prediction_pass_count": prediction_passes,
        "prediction_pass_rate": _safe_divide(prediction_passes, total),
        "prediction_pass_ci95": _wilson(prediction_passes, total),
    }


def _sample_metrics(sample: Any, rows: Sequence[Any], evaluation: Any) -> tuple[Any, Any, Any, Any]:
    three = _value(sample, "mapped_three_class", "three_class_metrics")
    binary = _value(sample, "operational_binary", "binary_metrics")
    expanded = _value(sample, "expanded_normal", "expanded_normal_metrics", "expanded_metrics")
    yield_stats = _value(sample, "yield_stats", "yield")
    if three is None:
        three = _fallback_metrics(rows, evaluation, THREE_LABELS, binary=False)
    if binary is None:
        binary = _fallback_metrics(rows, evaluation, BINARY_LABELS, binary=True)
    if expanded is None:
        expanded = _fallback_metrics(rows, evaluation, THREE_LABELS, binary=False, expanded=True)
    if yield_stats is None:
        yield_stats = _fallback_yield(rows, evaluation)
    return three, binary, expanded, yield_stats


def _overall_metrics(
    evaluation: Any,
    samples: Sequence[Any],
) -> tuple[Any, Any, Any, Any, list[Any]]:
    rows = [row for sample in samples for row in _records(sample)]
    three = _value(evaluation, "overall_three_class")
    binary = _value(evaluation, "overall_binary")
    expanded = _value(evaluation, "overall_expanded_normal", "overall_expanded")
    yield_stats = _value(evaluation, "overall_yield", "yield_stats")
    if three is None:
        three = _fallback_metrics(rows, evaluation, THREE_LABELS, binary=False)
    if binary is None:
        binary = _fallback_metrics(rows, evaluation, BINARY_LABELS, binary=True)
    if expanded is None:
        expanded = _fallback_metrics(
            rows,
            evaluation,
            THREE_LABELS,
            binary=False,
            expanded=True,
        )
    if yield_stats is None:
        yield_stats = _fallback_yield(rows, evaluation)
    return three, binary, expanded, yield_stats, rows


def _metric_counts(metrics: Any) -> Counter[tuple[str, str]]:
    labels = tuple(_value(metrics, "labels", default=()) or ())
    matrix = tuple(_value(metrics, "matrix", default=()) or ())
    counts: Counter[tuple[str, str]] = Counter()
    for row_index, actual in enumerate(labels):
        if row_index >= len(matrix):
            continue
        for col_index, predicted in enumerate(labels):
            if col_index < len(matrix[row_index]):
                counts[(actual, predicted)] = int(matrix[row_index][col_index])
    return counts


def _class_metric(metrics: Any, label: str) -> Any | None:
    for item in _items(_value(metrics, "per_class", default=())):
        if _text(_value(item, "label")) == label:
            return item
    return None


def _raw_counts(sample: Any, rows: Sequence[Any]) -> Counter[tuple[str, str]]:
    authoritative = _value(sample, "raw_status_by_prediction")
    counts: Counter[tuple[str, str]] = Counter()
    if isinstance(authoritative, Mapping):
        for raw, predictions in authoritative.items():
            if isinstance(predictions, Mapping):
                for predicted, count in predictions.items():
                    counts[(_text(raw), _text(predicted))] += int(count)
        return counts
    for row in rows:
        if _complete_pair(row):
            counts[(_raw_measurement(row), _prediction(row))] += 1
    return counts


def _format_metric(cell: Any, value: Any) -> None:
    if value is None:
        cell.value = "N/A"
    else:
        cell.value = value
        cell.number_format = "0.0%"


def _write_general_metrics(
    ws: Any,
    start_row: int,
    start_col: int,
    title: str,
    metrics: Any,
    yield_stats: Any | None = None,
) -> int:
    _set_section(ws.cell(start_row, start_col), title)
    rows: list[tuple[str, Any, Any, Any]] = [
        ("Accuracy", _value(metrics, "accuracy"), None, None),
        (
            "Accuracy CI95",
            None,
            *(_value(metrics, "accuracy_ci95") or (None, None)),
        ),
        ("Balanced accuracy", _value(metrics, "balanced_accuracy"), None, None),
        ("Macro F1", _value(metrics, "macro_f1"), None, None),
        ("Weighted F1", _value(metrics, "weighted_f1"), None, None),
    ]
    if yield_stats is not None:
        rows.extend(
            [
                (
                    "Measurement pass rate",
                    _value(yield_stats, "measurement_pass_rate"),
                    None,
                    None,
                ),
                (
                    "Measurement pass CI95",
                    None,
                    *(_value(yield_stats, "measurement_pass_ci95") or (None, None)),
                ),
                (
                    "Prediction pass rate",
                    _value(yield_stats, "prediction_pass_rate"),
                    None,
                    None,
                ),
                (
                    "Prediction pass CI95",
                    None,
                    *(_value(yield_stats, "prediction_pass_ci95") or (None, None)),
                ),
            ]
        )
    for offset, (label, value, lower, upper) in enumerate(rows, 1):
        row = start_row + offset
        ws.cell(row, start_col, label)
        if value is not None:
            _format_metric(ws.cell(row, start_col + 1), value)
        elif lower is not None or upper is not None:
            _format_metric(ws.cell(row, start_col + 2), lower)
            _format_metric(ws.cell(row, start_col + 3), upper)
        else:
            ws.cell(row, start_col + 1, "N/A")
    return start_row + len(rows)


def _write_class_metrics(
    ws: Any,
    start_row: int,
    start_col: int,
    title: str,
    metrics: Any,
    labels: Sequence[str],
) -> int:
    _set_section(ws.cell(start_row, start_col), title)
    headers = (
        "Class",
        "Precision",
        "Recall",
        "F1",
        "Support",
        "Specificity",
        "FPR",
        "FNR",
        "Recall CI low",
        "Recall CI high",
    )
    for offset, header in enumerate(headers):
        ws.cell(start_row + 1, start_col + offset, header)
    _style_header_row(ws, start_row + 1, start_col, start_col + len(headers) - 1)
    for row_offset, label in enumerate(labels, 2):
        item = _class_metric(metrics, label)
        ws.cell(start_row + row_offset, start_col, label)
        values = (
            _value(item, "precision") if item is not None else None,
            _value(item, "recall") if item is not None else None,
            _value(item, "f1") if item is not None else None,
            _value(item, "support") if item is not None else 0,
            _value(item, "specificity") if item is not None else None,
            _value(item, "false_positive_rate") if item is not None else None,
            _value(item, "false_negative_rate") if item is not None else None,
        )
        for col_offset, value in enumerate(values, 1):
            cell = ws.cell(start_row + row_offset, start_col + col_offset)
            if col_offset == 4:
                cell.value = value
                cell.number_format = "#,##0"
            else:
                _format_metric(cell, value)
        interval = _value(item, "recall_ci95") if item is not None else None
        lower, upper = interval or (None, None)
        _format_metric(ws.cell(start_row + row_offset, start_col + 8), lower)
        _format_metric(ws.cell(start_row + row_offset, start_col + 9), upper)
    return start_row + 1 + len(labels)


def _write_report_panel(
    ws: Any,
    sample: Any,
    rows: Sequence[Any],
    evaluation: Any,
) -> None:
    for col in range(43, 66):
        ws.column_dimensions[get_column_letter(col)].width = 10
    three_metrics, binary_metrics, expanded_metrics, yield_stats = _sample_metrics(
        sample, rows, evaluation
    )

    total = int(_value(yield_stats, "total", default=0) or 0)
    measured_pass = int(_value(yield_stats, "measurement_pass_count", default=0) or 0)
    predicted_pass = int(_value(yield_stats, "prediction_pass_count", default=0) or 0)
    ws["AQ4"], ws["AR4"], ws["AS4"] = "Class", "Measurement", "Prediction"
    ws["AQ5"], ws["AR5"], ws["AS5"] = "Pass", measured_pass, predicted_pass
    ws["AQ6"], ws["AR6"], ws["AS6"] = (
        "Fail",
        total - measured_pass,
        total - predicted_pass,
    )
    _style_header_row(ws, 4, 43, 45)
    ws["AU4"] = "Operational yield"
    ws["AU5"], ws["AV5"] = "Complete pairs", total
    ws["AU6"], ws["AV6"] = "Measurement pass", _value(yield_stats, "measurement_pass_rate")
    ws["AU7"], ws["AV7"] = "Prediction pass", _value(yield_stats, "prediction_pass_rate")
    for cell in (ws["AV6"], ws["AV7"]):
        _format_metric(cell, cell.value)
    _write_legend(ws, 4, 52, "Measurement legend", MEASUREMENT_STYLES)
    ws["BD4"] = "Page 1 definition"
    ws["BD5"] = "Measurement colors preserve raw statuses. Yield uses complete pairs."
    ws.merge_cells("BD5:BM8")
    ws["BD5"].alignment = Alignment(wrap_text=True, vertical="top")
    comparison_chart = BarChart()
    comparison_chart.title = "Measurement vs prediction pass/fail"
    comparison_chart.add_data(
        Reference(ws, min_col=44, max_col=45, min_row=4, max_row=6),
        titles_from_data=True,
    )
    comparison_chart.set_categories(Reference(ws, min_col=43, min_row=5, max_row=6))
    comparison_chart.height = 7
    comparison_chart.width = 14
    comparison_chart.y_axis.title = "Count"
    ws.add_chart(comparison_chart, "AQ11")

    actual_distribution = Counter(_canonical(row, evaluation) for row in rows)
    prediction_distribution = Counter(_prediction(row) for row in rows)
    distribution_labels = ("Normal", "Open", "Short", "Exclude", "N/A")
    ws["AQ43"], ws["AR43"], ws["AS43"] = "Class", "Measurement", "Prediction"
    for row, label in enumerate(distribution_labels, 44):
        ws.cell(row, 43, label)
        ws.cell(row, 44, actual_distribution[label])
        ws.cell(row, 45, prediction_distribution[label])
    _style_header_row(ws, 43, 43, 45)
    confidence = _value(sample, "confidence_review")
    ws["AU43"] = "Confidence / review"
    confidence_rows = (
        ("Confidence count", _value(confidence, "confidence_count", default=0)),
        ("Confidence mean", _value(confidence, "confidence_mean")),
        ("Review required", _value(confidence, "review_required_count", default=0)),
        ("Review rate", _value(confidence, "review_required_rate")),
        ("Probability count", _value(confidence, "probability_count", default=0)),
    )
    for row, (label, value) in enumerate(confidence_rows, 44):
        ws.cell(row, 47, label)
        ws.cell(row, 48, "N/A" if value is None else value)
    for row in (45, 47):
        if isinstance(ws.cell(row, 48).value, float):
            ws.cell(row, 48).number_format = "0.0%"
    _write_legend(ws, 43, 52, "Prediction legend", PREDICTION_STYLES)
    ws["BD43"] = "Page 2 definition"
    ws["BD44"] = "Prediction distributions include every joined coordinate; missing is N/A."
    ws.merge_cells("BD44:BM48")
    ws["BD44"].alignment = Alignment(wrap_text=True, vertical="top")
    class_chart = BarChart()
    class_chart.title = "Mapped measurement vs prediction classes"
    class_chart.add_data(
        Reference(ws, min_col=44, max_col=45, min_row=43, max_row=48),
        titles_from_data=True,
    )
    class_chart.set_categories(Reference(ws, min_col=43, min_row=44, max_row=48))
    class_chart.height = 7
    class_chart.width = 14
    class_chart.y_axis.title = "Count"
    ws.add_chart(class_chart, "AQ51")

    raw_counts = _raw_counts(sample, rows)
    raw_labels = sorted({actual for actual, _predicted in raw_counts}, key=_norm)
    _write_matrix(
        ws,
        76,
        43,
        "Raw status x prediction",
        raw_labels,
        THREE_LABELS,
        raw_counts,
    )
    _write_matrix(
        ws,
        76,
        49,
        "Mapped 3x3",
        THREE_LABELS,
        THREE_LABELS,
        _metric_counts(three_metrics),
    )
    _write_matrix(
        ws,
        76,
        55,
        "Binary 2x2",
        BINARY_LABELS,
        BINARY_LABELS,
        _metric_counts(binary_metrics),
    )
    _write_legend(ws, 76, 60, "Agreement legend", AGREEMENT_STYLES)
    _write_general_metrics(
        ws,
        86,
        43,
        "Binary metrics (Fail positive)",
        binary_metrics,
        yield_stats,
    )
    _write_class_metrics(
        ws,
        96,
        43,
        "Binary class metrics",
        binary_metrics,
        BINARY_LABELS,
    )
    _write_general_metrics(ws, 86, 53, "Mapped 3-class metrics", three_metrics)
    _write_class_metrics(
        ws,
        92,
        53,
        "3-class metrics",
        three_metrics,
        THREE_LABELS,
    )
    _write_matrix(
        ws,
        113,
        43,
        "Expanded Normal scenario 3x3",
        THREE_LABELS,
        THREE_LABELS,
        _metric_counts(expanded_metrics),
    )
    ws["AW113"], ws["AX113"], ws["AY113"] = "Class", "Actual", "Prediction"
    for row, label in enumerate(THREE_LABELS, 114):
        ws.cell(row, 49, label)
        ws.cell(row, 50, sum(_expanded_actual(item, evaluation) == label for item in rows))
        ws.cell(row, 51, sum(_prediction(item) == label for item in rows))
    _style_header_row(ws, 113, 49, 51)
    _write_legend(ws, 113, 60, "Expanded Normal legend", PREDICTION_STYLES)
    _write_general_metrics(ws, 122, 43, "Expanded Normal scenario metrics", expanded_metrics)
    _write_class_metrics(
        ws, 122, 53, "Expanded Normal class metrics", expanded_metrics, THREE_LABELS
    )
    ws["AQ136"] = (
        "Limitation: Expanded Normal is an additional image-observability/reporting assumption, "
        "not a relabeling of original electrical ground truth. No Gate Effect is mapped to Normal; "
        "Short remains Short. Raw, mapped 3-class, and Fail-positive binary results are preserved."
    )
    ws.merge_cells("AQ136:BM142")
    ws["AQ136"].alignment = Alignment(wrap_text=True, vertical="top")
    ws["AQ101"] = (
        "Definitions: Fail is the positive binary class. Every complete pair is binary-eligible, "
        "including three-class Exclude statuses such as No Gate Effect. Missing pairs only are "
        "N/A. Precision/recall/F1/specificity/FPR/FNR and Wilson intervals follow the "
        "authoritative evaluation result; zero-denominator values display N/A."
    )
    ws.merge_cells("AQ101:BM107")
    ws["AQ101"].alignment = Alignment(wrap_text=True, vertical="top")


def _report_sheet(
    wb: Workbook,
    sample: Any,
    index: int,
    evaluation: Any,
    *,
    show_map_codes: bool = True,
) -> Any:
    ws = wb.create_sheet(f"R{index:02d}")
    rows = _records(sample)
    name = _sample_name(sample, index)
    _title(ws, f"R2R Evaluation Report — {name}")
    ws["A3"] = f"Full sample name: {name}"
    ws["A4"] = f"Joined coordinates: {len(rows):,} | Grid: {ROWS} x {NODES}"
    for heading, body, title in zip(
        MAP_HEADING_ROWS,
        MAP_BODY_ROWS,
        REPORT_TITLES,
        strict=True,
    ):
        _style_map_area(ws, heading, body, title)
    measurement_values: dict[tuple[int, int], tuple[str, str]] = {}
    prediction_values: dict[tuple[int, int], tuple[str, str]] = {}
    agreement_values: dict[tuple[int, int], tuple[str, str]] = {}
    expanded_values: dict[tuple[int, int], tuple[str, str]] = {}
    for row in rows:
        coordinate = _coordinate(row)
        if coordinate[0] is None:
            continue
        raw = _raw_measurement(row)
        predicted = _prediction(row)
        agreement = _agreement(row, evaluation)
        measurement_values[coordinate] = MEASUREMENT_STYLES.get(raw, UNKNOWN_STYLE)
        prediction_values[coordinate] = PREDICTION_STYLES.get(predicted, UNKNOWN_STYLE)
        agreement_values[coordinate] = AGREEMENT_STYLES.get(agreement, UNKNOWN_STYLE)
        expanded_actual = _expanded_actual(row, evaluation)
        expanded_values[coordinate] = PREDICTION_STYLES.get(expanded_actual, UNKNOWN_STYLE)
    _write_map(ws, 9, measurement_values, show_codes=show_map_codes)
    _write_map(ws, 44, prediction_values, show_codes=show_map_codes)
    _write_map(ws, 79, agreement_values, show_codes=show_map_codes)
    _write_map(ws, 114, expanded_values, show_codes=show_map_codes)
    _write_report_panel(ws, sample, rows, evaluation)
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth = 1
    # Leave vertical pagination unconstrained so Excel honors the two explicit
    # horizontal page breaks below.  Setting FitToHeight=3 causes desktop
    # Excel to recalculate and collapse the four map bands into fewer logical pages.
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = "A1:BM142"
    # Break.id is the row after which openpyxl emits the break.  39/74 therefore
    # begin pages before Excel rows 40 and 75.
    ws.row_breaks.append(Break(id=39))
    ws.row_breaks.append(Break(id=74))
    ws.row_breaks.append(Break(id=109))
    return ws


def _source_rows(evaluation: Any) -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for kind, field in (
        ("Measurement", "measurement_sources"),
        ("Prediction", "prediction_sources"),
    ):
        for source in _items(_value(evaluation, field)):
            identity = (
                kind,
                _value(source, "path"),
                _value(source, "sha256"),
                _value(source, "size"),
                _value(source, "mtime_ns"),
                _value(source, "encoding"),
                _value(source, "worksheet"),
            )
            if identity not in seen:
                seen.add(identity)
                rows.append((kind, source))
    return rows


def _readme_sheet(
    wb: Workbook,
    evaluation: Any,
    *,
    show_map_codes: bool = True,
) -> None:
    ws = wb.active
    ws.title = "README"
    _title(ws, "R2R Evaluation Workbook — operational and provenance record", "J")
    notes = (
        (
            "Operational binary",
            "Fail is positive. The final binary status profile applies to every complete pair; "
            "No Gate Effect remains binary Fail even when excluded from mapped 3-class scoring.",
        ),
        (
            "N/A semantics",
            "N/A denotes a missing pair, unknown/unresolved input, or an undefined metric "
            "denominator. It is not substituted with zero.",
        ),
        (
            "Workbook scope",
            "Joined_Data contains coordinate keys and evaluation fields only; no 201-point "
            "measurement sweeps are copied into this report.",
        ),
        (
            "Expanded Normal scenario limitation",
            "This is an additional image-observability/reporting assumption, not a relabeling of "
            "electrical ground truth. It maps No Gate Effect to Normal while retaining Short as "
            "Short; raw, mapped 3-class, and binary results remain unchanged.",
        ),
    )
    for row, (label, value) in enumerate(notes, 3):
        ws.cell(row, 1, label).font = Font(bold=True)
        ws.cell(row, 2, value).alignment = Alignment(wrap_text=True, vertical="top")
    ws.cell(7, 1, "Map display mode").font = Font(bold=True)
    display_mode = (
        "Codes + fills"
        if show_map_codes
        else "Color fills only; map body codes intentionally blank"
    )
    ws.cell(7, 2, display_mode)
    source_start = 8
    ws.cell(source_start, 1, "Source provenance")
    _set_section(ws.cell(source_start, 1), "Source provenance")
    source_headers = (
        "Kind",
        "Path",
        "SHA256",
        "Size bytes",
        "mtime_ns",
        "Encoding",
        "Worksheet",
    )
    for col, header in enumerate(source_headers, 1):
        ws.cell(source_start + 1, col, header)
    _style_header_row(ws, source_start + 1, 1, len(source_headers))
    sources = _source_rows(evaluation)
    if not sources:
        ws.cell(source_start + 2, 1, "Not supplied")
    for row, (kind, source) in enumerate(sources, source_start + 2):
        ws.cell(row, 1, kind)
        ws.cell(row, 2, _text(_value(source, "path")))
        ws.cell(row, 3, _text(_value(source, "sha256")))
        ws.cell(row, 4, _value(source, "size"))
        ws.cell(row, 5, _value(source, "mtime_ns"))
        ws.cell(row, 6, _text(_value(source, "encoding"), "N/A"))
        ws.cell(row, 7, _text(_value(source, "worksheet"), "N/A"))
        ws.cell(row, 4).number_format = "#,##0"
        ws.cell(row, 5).number_format = "0"
    profile_start = source_start + max(len(sources), 1) + 4
    _set_section(ws.cell(profile_start, 1), "Final status mapping profile")
    headers = (
        "Normalized raw status",
        "Mapped 3-class",
        "Operational binary",
        "Expanded Normal scenario",
    )
    for col, header in enumerate(headers, 1):
        ws.cell(profile_start + 1, col, header)
    _style_header_row(ws, profile_start + 1, 1, 4)
    three, binary, expanded = _profile_maps(evaluation)
    for row, raw in enumerate(sorted(set(three) | set(binary) | set(expanded)), profile_start + 2):
        ws.cell(row, 1, raw)
        ws.cell(row, 2, three.get(raw, "N/A"))
        ws.cell(row, 3, binary.get(raw, "N/A"))
        ws.cell(row, 4, expanded.get(raw, "N/A"))
    ws.column_dimensions["A"].width = 25
    ws.column_dimensions["B"].width = 70
    ws.column_dimensions["C"].width = 68
    for col in "DEFG":
        ws.column_dimensions[col].width = 18
    ws.freeze_panes = "A10"
    ws.sheet_view.showGridLines = False


def _mapping_audit_sheet(wb: Workbook, evaluation: Any, samples: Sequence[Any]) -> None:
    ws = wb.create_sheet("Mapping_Audit")
    _title(ws, "Mapping audit", "J")
    headers = (
        "Measurement Sample",
        "Prediction Sample",
        "Audit Status",
        "Method",
        "Requires Confirmation",
        "Signature / Raw Status",
        "Canonical",
        "Operational Binary",
        "Expanded Normal",
        "Note",
    )
    for col, header in enumerate(headers, 1):
        ws.cell(3, col, header)
    _style_header_row(ws, 3, 1, len(headers))
    row = 4
    audit = _value(evaluation, "mappings")
    for proposal in _items(_value(audit, "proposals")):
        confirmation = bool(_value(proposal, "requires_confirmation"))
        method = _text(_value(proposal, "method"), "unknown")
        ws.cell(row, 1, _text(_value(proposal, "measurement_sheet")))
        ws.cell(row, 2, _text(_value(proposal, "prediction_sheet")))
        ws.cell(row, 3, "heuristic confirmation" if confirmation else method)
        ws.cell(row, 4, method)
        ws.cell(row, 5, confirmation)
        ws.cell(row, 6, ", ".join(map(str, _items(_value(proposal, "signature")))))
        row += 1
    for name in _items(_value(audit, "prediction_only_sheets")):
        ws.cell(row, 2, name)
        ws.cell(row, 3, "unmatched prediction-only")
        row += 1
    for name in _items(_value(audit, "unmatched_measurement_sheets")):
        ws.cell(row, 1, name)
        ws.cell(row, 3, "unmatched measurement-only")
        row += 1
    three, binary, expanded = _profile_maps(evaluation)
    for raw in _items(_value(evaluation, "unresolved_measurement_statuses")):
        ws.cell(row, 3, "unknown mapping")
        ws.cell(row, 6, raw)
        ws.cell(row, 7, three.get(_norm(raw), "N/A"))
        ws.cell(row, 8, binary.get(_norm(raw), "N/A"))
        ws.cell(row, 9, expanded.get(_norm(raw), "N/A"))
        row += 1
    for prediction in _items(_value(evaluation, "unknown_predictions")):
        ws.cell(row, 2, prediction)
        ws.cell(row, 3, "unknown prediction")
        row += 1
    for error in _items(_value(evaluation, "mapping_errors")):
        ws.cell(row, 3, "mapping error")
        ws.cell(row, 10, error)
        row += 1
    if row == 4 and samples:
        for index, sample in enumerate(samples, 1):
            ws.cell(row, 1, _sample_name(sample, index))
            ws.cell(row, 3, "evaluated")
            row += 1
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:J{max(row - 1, 3)}"
    widths = (30, 30, 24, 14, 20, 28, 18, 20, 22, 60)
    for col, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = width


def _joined_sheet(
    wb: Workbook,
    evaluation: Any,
    samples: Sequence[Any],
) -> None:
    ws = wb.create_sheet("Joined_Data")
    _title(ws, "Joined coordinate-level data", "P")
    for col, header in enumerate(JOINED_HEADERS, 1):
        ws.cell(3, col, header)
    _style_header_row(ws, 3, 1, len(JOINED_HEADERS))
    output_row = 4
    for index, sample in enumerate(samples, 1):
        for row in _records(sample):
            coordinate = _coordinate(row)
            values = (
                _sample_name(sample, index),
                coordinate[0],
                coordinate[1],
                _raw_measurement(row),
                _canonical(row, evaluation),
                _prediction(row),
                _probability(row, "Normal"),
                _probability(row, "Open"),
                _probability(row, "Short"),
                _binary_actual(row, evaluation),
                _binary_predicted(row),
                _agreement(row, evaluation),
                _source_row(row),
                _expanded_actual(row, evaluation),
                _expanded_agreement(row, evaluation),
                "Included" if _expanded_actual(row, evaluation) in THREE_LABELS else "Excluded/N/A",
            )
            for col, value in enumerate(values, 1):
                ws.cell(output_row, col, value)
            output_row += 1
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:P{max(output_row - 1, 3)}"
    widths = (32, 8, 8, 22, 16, 14, 12, 12, 12, 20, 18, 12, 12, 22, 24, 20)
    for col, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = width


def _summary_kpi_row(
    metrics: Any,
    three_metrics: Any,
    yield_stats: Any,
    excluded: int,
    missing: int,
) -> list[Any]:
    pass_metrics = _class_metric(metrics, "Pass")
    fail_metrics = _class_metric(metrics, "Fail")
    return [
        _value(metrics, "total", default=0),
        _value(three_metrics, "total", default=0),
        excluded,
        missing,
        _value(metrics, "accuracy"),
        _value(metrics, "balanced_accuracy"),
        _value(metrics, "macro_f1"),
        _value(metrics, "weighted_f1"),
        _value(pass_metrics, "precision"),
        _value(pass_metrics, "recall"),
        _value(fail_metrics, "precision"),
        _value(fail_metrics, "recall"),
        _value(fail_metrics, "f1"),
        _value(yield_stats, "measurement_pass_rate"),
        _value(yield_stats, "prediction_pass_rate"),
    ]


def _summary_sheet(wb: Workbook, evaluation: Any, samples: Sequence[Any]) -> None:
    ws = wb.create_sheet("Overall Summary")
    _title(ws, "Overall Summary", "Q")
    headers = (
        "Scope / Sample",
        "Binary pairs",
        "3-class scored",
        "3-class excluded",
        "Missing pairs",
        "Accuracy",
        "Balanced accuracy",
        "Macro F1",
        "Weighted F1",
        "Pass precision",
        "Pass recall",
        "Fail precision",
        "Fail recall",
        "Fail F1",
        "Measurement pass rate",
        "Prediction pass rate",
    )
    for col, header in enumerate(headers, 1):
        ws.cell(3, col, header)
    _style_header_row(ws, 3, 1, len(headers))
    overall_three, overall_binary, overall_expanded, overall_yield, all_rows = _overall_metrics(
        evaluation, samples
    )
    overall_missing = sum(not _complete_pair(row) for row in all_rows)
    overall_excluded = sum(
        len(_items(_value(sample, "excluded", default=()))) for sample in samples
    )
    ws.cell(4, 1, "OVERALL")
    for col, value in enumerate(
        _summary_kpi_row(
            overall_binary,
            overall_three,
            overall_yield,
            overall_excluded,
            overall_missing,
        ),
        2,
    ):
        ws.cell(4, col, "N/A" if value is None else value)
    for index, sample in enumerate(samples, 1):
        row_number = 4 + index
        rows = _records(sample)
        three, binary, _expanded, yield_stats = _sample_metrics(sample, rows, evaluation)
        excluded = len(_items(_value(sample, "excluded", default=())))
        missing = sum(not _complete_pair(row) for row in rows)
        ws.cell(row_number, 1, _sample_name(sample, index))
        for col, value in enumerate(
            _summary_kpi_row(binary, three, yield_stats, excluded, missing),
            2,
        ):
            ws.cell(row_number, col, "N/A" if value is None else value)
    data_last = 4 + len(samples)
    for row in range(4, data_last + 1):
        for col in range(6, 17):
            if isinstance(ws.cell(row, col).value, int | float):
                ws.cell(row, col).number_format = "0.0%"
    chart = BarChart()
    chart.title = "Measurement vs prediction pass rate"
    chart.add_data(
        Reference(ws, min_col=15, max_col=16, min_row=3, max_row=data_last),
        titles_from_data=True,
    )
    chart.set_categories(Reference(ws, min_col=1, min_row=4, max_row=data_last))
    chart.height = 7
    chart.width = 14
    chart.y_axis.numFmt = "0%"
    chart_row = data_last + 3
    ws.add_chart(chart, f"A{chart_row}")

    # Keep the native chart below the KPI table and start the detailed tables
    # on a dedicated second A3 page.  This avoids Excel scattering the summary
    # over several horizontal print pages.
    section_row = data_last + 22
    _write_matrix(
        ws,
        section_row,
        1,
        "Overall mapped 3x3",
        THREE_LABELS,
        THREE_LABELS,
        _metric_counts(overall_three),
    )
    _write_matrix(
        ws,
        section_row,
        7,
        "Overall binary 2x2",
        BINARY_LABELS,
        BINARY_LABELS,
        _metric_counts(overall_binary),
    )
    raw_counts: Counter[tuple[str, str]] = Counter()
    for sample in samples:
        raw_counts.update(_raw_counts(sample, _records(sample)))
    raw_labels = sorted({actual for actual, _predicted in raw_counts}, key=_norm)
    raw_end, _ = _write_matrix(
        ws,
        section_row,
        13,
        "Overall raw status x prediction",
        raw_labels,
        THREE_LABELS,
        raw_counts,
    )
    distribution_row = max(section_row + 7, raw_end + 2)
    _set_section(ws.cell(distribution_row, 1), "Overall class distributions")
    ws.cell(distribution_row + 1, 1, "Class")
    ws.cell(distribution_row + 1, 2, "Measurement")
    ws.cell(distribution_row + 1, 3, "Prediction")
    _style_header_row(ws, distribution_row + 1, 1, 3)
    actual_distribution = Counter(_canonical(row, evaluation) for row in all_rows)
    predicted_distribution = Counter(_prediction(row) for row in all_rows)
    distribution_labels = ("Normal", "Open", "Short", "Exclude", "N/A")
    for offset, label in enumerate(distribution_labels, 2):
        ws.cell(distribution_row + offset, 1, label)
        ws.cell(distribution_row + offset, 2, actual_distribution[label])
        ws.cell(distribution_row + offset, 3, predicted_distribution[label])

    rank_row = distribution_row
    _set_section(ws.cell(rank_row, 6), "Fail recall / F1 rank")
    ws.cell(rank_row + 1, 6, "Rank")
    ws.cell(rank_row + 1, 7, "Sample")
    ws.cell(rank_row + 1, 8, "Fail recall")
    ws.cell(rank_row + 1, 9, "Fail F1")
    _style_header_row(ws, rank_row + 1, 6, 9)
    ranked: list[tuple[str, Any, Any]] = []
    for index, sample in enumerate(samples, 1):
        _three, binary, _expanded, _yield = _sample_metrics(sample, _records(sample), evaluation)
        fail = _class_metric(binary, "Fail")
        ranked.append(
            (
                _sample_name(sample, index),
                _value(fail, "recall") if fail is not None else None,
                _value(fail, "f1") if fail is not None else None,
            )
        )
    ranked.sort(
        key=lambda item: (
            item[2] is not None,
            item[2] if item[2] is not None else -1,
            item[1] if item[1] is not None else -1,
        ),
        reverse=True,
    )
    for rank, (name, recall, f1) in enumerate(ranked, 1):
        row = rank_row + 1 + rank
        ws.cell(row, 6, rank)
        ws.cell(row, 7, name)
        _format_metric(ws.cell(row, 8), recall)
        _format_metric(ws.cell(row, 9), f1)

    audit_row = distribution_row
    _set_section(ws.cell(audit_row, 11), "Exclusions / unmatched audit")
    audit_entries = [
        ("3-class excluded / missing", overall_excluded),
        ("Missing pairs", overall_missing),
    ]
    mapping = _value(evaluation, "mappings")
    for name in _items(_value(mapping, "unmatched_measurement_sheets")):
        audit_entries.append(("Unmatched measurement", name))
    for name in _items(_value(mapping, "prediction_only_sheets")):
        audit_entries.append(("Prediction-only", name))
    for status in _items(_value(evaluation, "unresolved_measurement_statuses")):
        audit_entries.append(("Unknown mapping", status))
    for error in _items(_value(evaluation, "mapping_errors")):
        audit_entries.append(("Mapping error", error))
    for offset, (label, value) in enumerate(audit_entries, 1):
        ws.cell(audit_row + offset, 11, label)
        ws.cell(audit_row + offset, 12, value)
    ws.cell(audit_row + len(audit_entries) + 2, 11, "See Mapping_Audit for full details.")

    for col in range(1, 18):
        ws.column_dimensions[get_column_letter(col)].width = 18
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["G"].width = 42
    ws.column_dimensions["K"].width = 28
    ws.column_dimensions["L"].width = 40
    ws.column_dimensions["M"].width = 22
    ws.column_dimensions["O"].width = 22
    ws.column_dimensions["P"].width = 22
    ws.row_dimensions[3].height = 30
    for cell in ws[3]:
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in range(4, data_last + 1):
        ws.cell(row, 1).alignment = Alignment(vertical="center", wrap_text=True)
        ws.row_dimensions[row].height = 42
    for row in range(rank_row + 2, rank_row + len(ranked) + 2):
        ws.cell(row, 7).alignment = Alignment(vertical="center", wrap_text=True)
        ws.row_dimensions[row].height = max(ws.row_dimensions[row].height or 15, 42)
    for row in range(audit_row + 1, audit_row + len(audit_entries) + 1):
        ws.cell(row, 11).alignment = Alignment(vertical="center", wrap_text=True)
        ws.cell(row, 12).alignment = Alignment(vertical="center", wrap_text=True)
        ws.row_dimensions[row].height = max(ws.row_dimensions[row].height or 15, 26)
    ws.freeze_panes = "A4"
    ws.sheet_view.showGridLines = False
    second_page_last = max(
        distribution_row + len(distribution_labels) + 1,
        rank_row + len(ranked) + 1,
        audit_row + len(audit_entries) + 2,
    )
    # Dedicated third A3 page for the Expanded Normal scenario keeps the
    # existing second-page tables untouched and avoids overlap.
    scenario_start = second_page_last + 3
    _set_section(ws.cell(scenario_start, 1), "Expanded Normal scenario — per-sample KPI")
    scenario_headers = ("Sample", "Total", "Accuracy", "Macro F1", "Weighted F1", "Normal support")
    for col, header in enumerate(scenario_headers, 1):
        ws.cell(scenario_start + 1, col, header)
    _style_header_row(ws, scenario_start + 1, 1, len(scenario_headers))
    for index, sample in enumerate(samples, 1):
        _three, _binary, expanded, _yield = _sample_metrics(sample, _records(sample), evaluation)
        row = scenario_start + 1 + index
        ws.cell(row, 1, _sample_name(sample, index))
        ws.cell(row, 2, _value(expanded, "total", default=0))
        _format_metric(ws.cell(row, 3), _value(expanded, "accuracy"))
        _format_metric(ws.cell(row, 4), _value(expanded, "macro_f1"))
        _format_metric(ws.cell(row, 5), _value(expanded, "weighted_f1"))
        normal_metric = _class_metric(expanded, "Normal")
        ws.cell(row, 6, _value(normal_metric, "support", default=0))
    overall_row = scenario_start + 2 + len(samples)
    ws.cell(overall_row, 1, "OVERALL")
    ws.cell(overall_row, 2, _value(overall_expanded, "total", default=0))
    _format_metric(ws.cell(overall_row, 3), _value(overall_expanded, "accuracy"))
    _format_metric(ws.cell(overall_row, 4), _value(overall_expanded, "macro_f1"))
    _format_metric(ws.cell(overall_row, 5), _value(overall_expanded, "weighted_f1"))
    normal_metric = _class_metric(overall_expanded, "Normal")
    ws.cell(overall_row, 6, _value(normal_metric, "support", default=0))
    matrix_row = overall_row + 3
    _write_matrix(
        ws, matrix_row, 1, "Overall Expanded Normal scenario 3x3", THREE_LABELS, THREE_LABELS,
        _metric_counts(overall_expanded)
    )
    scenario_distribution_row = matrix_row
    _set_section(ws.cell(scenario_distribution_row, 7), "Expanded Normal class distribution")
    ws.cell(scenario_distribution_row + 1, 7, "Class")
    ws.cell(scenario_distribution_row + 1, 8, "Actual")
    ws.cell(scenario_distribution_row + 1, 9, "Prediction")
    _style_header_row(ws, scenario_distribution_row + 1, 7, 9)
    expanded_actual_distribution = Counter(_expanded_actual(row, evaluation) for row in all_rows)
    for offset, label in enumerate(THREE_LABELS, 2):
        ws.cell(scenario_distribution_row + offset, 7, label)
        ws.cell(scenario_distribution_row + offset, 8, expanded_actual_distribution[label])
        ws.cell(scenario_distribution_row + offset, 9, predicted_distribution[label])
    _write_general_metrics(
        ws, matrix_row + 7, 1, "Expanded Normal general metrics", overall_expanded
    )
    _write_class_metrics(
        ws, matrix_row + 7, 8, "Expanded Normal class metrics", overall_expanded, THREE_LABELS
    )
    limitation_row = matrix_row + 15
    ws.cell(
        limitation_row,
        1,
        "Limitation: Expanded Normal is an image-observability/reporting assumption, "
        "not electrical ground-truth relabeling. No Gate Effect maps to Normal; "
        "Short remains Short.",
    )
    ws.merge_cells(
        start_row=limitation_row, start_column=1, end_row=limitation_row + 2, end_column=17
    )
    ws.cell(limitation_row, 1).alignment = Alignment(wrap_text=True, vertical="top")
    summary_last_row = limitation_row + 2
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = f"A1:Q{summary_last_row}"
    ws.row_breaks.append(Break(id=section_row - 1))
    ws.row_breaks.append(Break(id=scenario_start - 1))


def _cancelled(check: Callable[[], bool] | Any | None) -> bool:
    if check is None:
        return False
    if callable(check):
        return bool(check())
    is_set = getattr(check, "is_set", None)
    return bool(is_set()) if callable(is_set) else bool(check)


def _chart_formula(series: Any, kind: str) -> str:
    source = series.val if kind == "value" else series.cat
    for reference_name in ("numRef", "strRef"):
        reference = getattr(source, reference_name, None)
        if reference is not None and reference.f:
            return reference.f
    return ""


def verify_workbook_structure(path_or_workbook: str | Path | Workbook) -> None:
    """Raise ``ValueError`` when a saved report violates the structural contract."""
    close = False
    if isinstance(path_or_workbook, Workbook):
        wb = path_or_workbook
    else:
        wb = load_workbook(path_or_workbook)
        close = True
    try:
        if wb.sheetnames[:3] != ["README", "Mapping_Audit", "Joined_Data"]:
            raise ValueError("README, Mapping_Audit, Joined_Data must be first")
        if wb.sheetnames[-1] != "Overall Summary":
            raise ValueError("Overall Summary must be last")
        reports = wb.sheetnames[3:-1]
        expected_reports = [f"R{index:02d}" for index in range(1, len(reports) + 1)]
        if reports != expected_reports:
            raise ValueError("Report tabs must be ordered safe Rnn identifiers")
        joined = wb["Joined_Data"]
        if (
            tuple(joined.cell(3, col).value for col in range(1, len(JOINED_HEADERS) + 1))
            != JOINED_HEADERS
        ):
            raise ValueError("Joined_Data has an unexpected data contract")
        if joined.freeze_panes != "A4" or joined.auto_filter.ref is None:
            raise ValueError("Joined_Data must retain freeze panes and filter")
        for name in reports:
            ws = wb[name]
            if not _text(ws["A1"].value).startswith("R2R Evaluation Report — "):
                raise ValueError(f"{name}: full report title missing")
            if not str(ws.print_area).endswith("!$A$1:$BM$142"):
                raise ValueError(f"{name}: print area must be A1:BM142")
            if ws.max_row > 142 or ws.max_column > 65:
                raise ValueError(f"{name}: content extends beyond print area")
            if ws.page_setup.orientation != "landscape" or str(ws.page_setup.paperSize) != str(
                ws.PAPERSIZE_A3
            ):
                raise ValueError(f"{name}: expected A3 landscape")
            if ws.page_setup.fitToWidth != 1 or ws.page_setup.fitToHeight != 0:
                raise ValueError(f"{name}: expected fit to one page wide / automatic height")
            if [item.id for item in ws.row_breaks.brk] != [39, 74, 109]:
                raise ValueError(f"{name}: expected breaks before rows 40, 75, and 110")
            if any(
                ws.column_dimensions[get_column_letter(col)].width != 2.5 for col in range(3, 42)
            ):
                raise ValueError(f"{name}: map columns C:AO must be 2.5")
            for heading, body in zip(MAP_HEADING_ROWS, MAP_BODY_ROWS, strict=True):
                if ws.cell(heading, 3).value != "Row / Node":
                    raise ValueError(f"{name}: map header missing at C{heading}")
                if ws.cell(heading, 41).value != 38 or ws.cell(body + 25, 3).value != 26:
                    raise ValueError(f"{name}: incomplete 26x38 axes")
                if ws.cell(body + 25, 41).border.left.style != "thin":
                    raise ValueError(f"{name}: incomplete 26x38 body")
                if any(ws.row_dimensions[row].height != 17 for row in range(heading, body + ROWS)):
                    raise ValueError(f"{name}: map rows must be exactly 17 pt")
            if ws["AZ4"].value != "Measurement legend":
                raise ValueError(f"{name}: measurement legend is outside page band")
            if ws["AZ43"].value != "Prediction legend":
                raise ValueError(f"{name}: prediction legend is outside page band")
            if ws["BH76"].value != "Agreement legend":
                raise ValueError(f"{name}: agreement legend is outside page band")
            if ws.cell(113, 3).value != "Row / Node":
                raise ValueError(f"{name}: expanded scenario map is missing")
            if ws["AW113"].value != "Class" or ws["BH113"].value != "Expanded Normal legend":
                raise ValueError(f"{name}: expanded scenario distribution/legend is missing")
            if len(ws._charts) != 2:
                raise ValueError(f"{name}: expected exactly two native charts")
            first, second = ws._charts
            first_values = [_chart_formula(series, "value") for series in first.series]
            second_values = [_chart_formula(series, "value") for series in second.series]
            if not all(f"'{name}'!$A" in formula for formula in first_values + second_values):
                raise ValueError(f"{name}: chart series are not native sheet references")
            if "$AR$5:$AR$6" not in first_values[0] or "$AS$5:$AS$6" not in first_values[1]:
                raise ValueError(f"{name}: pass/fail chart source is incorrect")
            if "$AR$44:$AR$48" not in second_values[0]:
                raise ValueError(f"{name}: class chart source is incorrect")
            if first.anchor._from.row != 10 or second.anchor._from.row != 50:
                raise ValueError(f"{name}: charts do not stay within their page bands")
        summary = wb["Overall Summary"]
        if len(summary._charts) != 1:
            raise ValueError("Overall Summary requires one native pass-rate chart")
        if summary["A4"].value != "OVERALL":
            raise ValueError("Overall Summary authoritative overall row is missing")
        if summary.page_setup.fitToWidth != 1 or summary.page_setup.fitToHeight != 0:
            raise ValueError("Overall Summary must print one A3 page wide")
        if not str(summary.print_area).startswith("'Overall Summary'!$A$1:$Q$"):
            raise ValueError("Overall Summary print area is invalid")
        if len(summary.row_breaks.brk) != 2:
            raise ValueError("Overall Summary requires two logical page breaks")
    finally:
        if close:
            wb.close()


def verify_workbook(path: str | Path) -> None:
    """Verify a saved workbook by reopening it through openpyxl."""
    verify_workbook_structure(path)


def _render_verified(
    path: Path,
    evaluation: Any,
    cancel_check: Callable[[], bool] | Any | None,
    *,
    show_map_codes: bool,
) -> None:
    """Render one candidate to ``path`` and verify it before any commit."""
    workbook: Workbook | None = None
    try:
        if _cancelled(cancel_check):
            raise WorkbookCancelled("Workbook generation was cancelled")
        workbook = Workbook()
        samples = _samples(evaluation)
        _readme_sheet(workbook, evaluation, show_map_codes=show_map_codes)
        _mapping_audit_sheet(workbook, evaluation, samples)
        _joined_sheet(workbook, evaluation, samples)
        for index, sample in enumerate(samples, 1):
            if _cancelled(cancel_check):
                raise WorkbookCancelled("Workbook generation was cancelled")
            _report_sheet(workbook, sample, index, evaluation, show_map_codes=show_map_codes)
        _summary_sheet(workbook, evaluation, samples)
        if _cancelled(cancel_check):
            raise WorkbookCancelled("Workbook generation was cancelled")
        workbook.save(path)
        workbook.close()
        workbook = None
        verify_workbook_structure(path)
        if _cancelled(cancel_check):
            raise WorkbookCancelled("Workbook generation was cancelled")
    finally:
        if workbook is not None:
            workbook.close()


def generate_workbook(
    output_path: str | Path | Any,
    evaluation: Any | str | Path,
    cancel_check: Callable[[], bool] | Any | None = None,
) -> Path:
    """Generate and atomically replace ``output_path`` after reopen verification.

    The documented order is ``(output_path, evaluation, cancel_check=None)``.
    ``(evaluation, output_path)`` remains accepted for thin legacy callers.
    """
    if not isinstance(output_path, str | Path) and isinstance(evaluation, str | Path):
        output_path, evaluation = evaluation, output_path
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f".{output.stem}.partial.xlsx")
    try:
        partial.unlink(missing_ok=True)
        _render_verified(partial, evaluation, cancel_check, show_map_codes=True)
        os.replace(partial, output)
        return output
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def _restore_destination(destination: Path, backup: Path, existed: bool) -> None:
    if existed:
        if backup.exists():
            os.replace(backup, destination)
    else:
        destination.unlink(missing_ok=True)


def generate_workbook_pair(
    output_path: str | Path,
    evaluation: Any,
    cancel_check: Callable[[], bool] | Any | None = None,
) -> tuple[Path, Path]:
    """Generate, verify, and transactionally commit text and fills-only workbooks.

    Both candidates are rendered and reopened before either destination is
    changed. If cancellation or a commit error occurs, existing destinations
    are restored and temporary partial/backup files are removed. A process
    crash during the tiny commit window remains an unavoidable filesystem
    boundary; a stale transaction backup blocks automatic rerun and may require
    manual recovery.
    """
    output = Path(output_path)
    color_only = derive_color_only_path(output)
    if output.resolve() == color_only.resolve():
        raise ValueError("With-text and color-only output paths must differ")
    output.parent.mkdir(parents=True, exist_ok=True)
    color_only.parent.mkdir(parents=True, exist_ok=True)
    partials = (
        output.with_name(f".{output.stem}.partial.xlsx"),
        color_only.with_name(f".{color_only.stem}.partial.xlsx"),
    )
    backups = (
        output.with_name(f".{output.stem}.backup.xlsx"),
        color_only.with_name(f".{color_only.stem}.backup.xlsx"),
    )
    destinations = (output, color_only)
    existed = tuple(path.exists() for path in destinations)
    committed = [False, False]
    committed_all = False
    created_backups: set[Path] = set()
    try:
        for path in partials:
            path.unlink(missing_ok=True)
        stale_backups = [path for path in backups if path.exists()]
        if stale_backups:
            names = ", ".join(str(path) for path in stale_backups)
            raise RuntimeError(
                f"Stale transaction backup exists; recover or remove it first: {names}"
            )
        _render_verified(partials[0], evaluation, cancel_check, show_map_codes=True)
        _render_verified(partials[1], evaluation, cancel_check, show_map_codes=False)
        if _cancelled(cancel_check):
            raise WorkbookCancelled("Workbook generation was cancelled")
        for index, destination in enumerate(destinations):
            if existed[index]:
                os.replace(destination, backups[index])
                created_backups.add(backups[index])
            try:
                os.replace(partials[index], destination)
            except BaseException:
                _restore_destination(destination, backups[index], existed[index])
                raise
            committed[index] = True
        committed_all = True
        for backup in created_backups:
            try:
                backup.unlink(missing_ok=True)
            except Exception:
                # The pair is committed; a locked backup is recoverable and
                # must not trigger rollback after both destinations changed.
                pass
        return destinations
    except BaseException:
        if not committed_all:
            for index in reversed(range(2)):
                if committed[index]:
                    _restore_destination(destinations[index], backups[index], existed[index])
                elif existed[index] and backups[index] in created_backups:
                    _restore_destination(destinations[index], backups[index], True)
        for path in partials:
            path.unlink(missing_ok=True)
        for backup in created_backups:
            try:
                backup.unlink(missing_ok=True)
            except Exception:
                pass
        raise
