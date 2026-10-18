"""Transfer-curve grid: the measured current sweeps of one sample in the rows x nodes layout.

The spatial map sheets paint one label per device.  A converter export also
carries the measurement itself — the gate-voltage sweep behind that label — and
this module draws every device's sweep as a small ``log10|I|`` vs ``V`` curve in
the same 26 x 38 arrangement, so a reader can see the measured behaviour next to
the verdicts.  Pillow renders the grid to one image per sample; openpyxl embeds
it in the sample sheet.  Nothing here depends on Qt.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO

import numpy as np
from PIL import Image, ImageDraw, ImageFont

CELL_WIDTH = 32
CELL_HEIGHT = 24
SUPERSAMPLE = 2
LEFT_MARGIN = 26
TOP_MARGIN = 14
BOTTOM_MARGIN = 14
RIGHT_MARGIN = 4
CURVE_PAD = 2
CURRENT_FLOOR = 1e-13
"""Smallest |I| drawn; the exported currents are quantised to ~1 nA so this is well below noise."""
DEFAULT_CURVE_COLOR = "1F4E78"
BACKGROUND = (255, 255, 255)
CELL_FILL = (255, 255, 255)
EMPTY_FILL = (236, 238, 241)
GRID_COLOR = (198, 203, 210)
TEXT_COLOR = (64, 70, 80)
FONT_SIZE = 8


@dataclass(frozen=True)
class SweepGrid:
    """A rendered grid and the shared axes every cell was drawn with."""

    image: Image.Image
    voltage_range: tuple[float, float]
    log_current_range: tuple[int, int]
    traces: int
    cells: int

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height

    @property
    def axis_note(self) -> str:
        low, high = self.log_current_range
        v_min, v_max = self.voltage_range
        return (
            f"x: V {v_min:g} to {v_max:g} V (left to right); "
            f"y: log10|I| {low} to {high} (1e{low} to 1e{high} A, bottom to top)"
        )

    def png_bytes(self) -> bytes:
        buffer = BytesIO()
        self.image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()


def _rgb(color: str) -> tuple[int, int, int]:
    text = color.strip().lstrip("#")
    if len(text) == 8:  # ARGB from openpyxl
        text = text[2:]
    if len(text) != 6:
        text = DEFAULT_CURVE_COLOR
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def log_current_bounds(traces: Iterable[np.ndarray]) -> tuple[int, int]:
    """Integer ``log10`` bounds shared by every cell: the floor exponent up to the sample max."""
    low = round(math.log10(CURRENT_FLOOR))
    high = low + 1
    for trace in traces:
        values = np.abs(np.asarray(trace, dtype=np.float64))
        values = values[np.isfinite(values)]
        if values.size:
            high = max(high, math.ceil(math.log10(max(float(values.max()), CURRENT_FLOOR))))
    return low, high


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - Pillow < 10.1 has no sized default font
        return ImageFont.load_default()


def render_sweep_grid(
    rows: int,
    nodes: int,
    voltages: Sequence[float],
    traces: Mapping[tuple[int, int], tuple[np.ndarray, str]],
    *,
    cell_width: int = CELL_WIDTH,
    cell_height: int = CELL_HEIGHT,
) -> SweepGrid:
    """Draw ``traces`` (coordinate -> (currents, hex colour)) as a ``rows x nodes`` grid.

    Every cell shares one voltage axis (``voltages``, left = lowest) and one
    ``log10|I|`` axis (see :func:`log_current_bounds`), so curves are comparable
    across the sample.  A coordinate without a trace, or whose trace is all NaN,
    is painted grey; NaN points inside a trace break the line.
    """
    if rows < 1 or nodes < 1:
        raise ValueError("rows and nodes must be positive")
    if len(voltages) < 2:
        raise ValueError("a sweep needs at least two voltage points")
    v_min, v_max = float(min(voltages)), float(max(voltages))
    if v_max <= v_min:
        raise ValueError("voltage axis must span a range")
    low, high = log_current_bounds(trace for trace, _color in traces.values())
    k = SUPERSAMPLE
    width = LEFT_MARGIN + nodes * cell_width + RIGHT_MARGIN
    height = TOP_MARGIN + rows * cell_height + BOTTOM_MARGIN
    image = Image.new("RGB", (width * k, height * k), BACKGROUND)
    draw = ImageDraw.Draw(image)
    font = _font(FONT_SIZE * k)
    small = _font((FONT_SIZE - 1) * k)
    x_scale = (cell_width - 2 * CURVE_PAD) * k / (v_max - v_min)
    y_scale = (cell_height - 2 * CURVE_PAD) * k / (high - low)
    drawn = 0
    for row in range(1, rows + 1):
        y0 = (TOP_MARGIN + (row - 1) * cell_height) * k
        for node in range(1, nodes + 1):
            x0 = (LEFT_MARGIN + (node - 1) * cell_width) * k
            entry = traces.get((row, node))
            segments = _segments(entry[0], voltages) if entry is not None else []
            fill = CELL_FILL if segments else EMPTY_FILL
            draw.rectangle(
                (x0, y0, x0 + cell_width * k - 1, y0 + cell_height * k - 1),
                fill=fill,
                outline=GRID_COLOR,
                width=max(1, k // 2),
            )
            if not segments:
                continue
            drawn += 1
            color = _rgb(entry[1]) if entry is not None else _rgb(DEFAULT_CURVE_COLOR)
            base_x = x0 + CURVE_PAD * k
            base_y = y0 + (cell_height - CURVE_PAD) * k
            for segment in segments:
                points = [
                    (
                        base_x + (voltage - v_min) * x_scale,
                        base_y - (min(max(value, low), high) - low) * y_scale,
                    )
                    for voltage, value in segment
                ]
                if len(points) == 1:
                    x, y = points[0]
                    draw.ellipse((x - k, y - k, x + k, y + k), fill=color)
                else:
                    draw.line(points, fill=color, width=k, joint="curve")
    for node in range(1, nodes + 1):
        x = (LEFT_MARGIN + (node - 0.5) * cell_width) * k
        draw.text((x, TOP_MARGIN * k / 2), str(node), fill=TEXT_COLOR, font=small, anchor="mm")
    for row in range(1, rows + 1):
        y = (TOP_MARGIN + (row - 0.5) * cell_height) * k
        draw.text(((LEFT_MARGIN - 3) * k, y), str(row), fill=TEXT_COLOR, font=font, anchor="rm")
    grid = SweepGrid(image, (v_min, v_max), (low, high), drawn, rows * nodes)
    draw.text(
        (LEFT_MARGIN * k, (height - BOTTOM_MARGIN / 2) * k),
        grid.axis_note + f"; {drawn}/{rows * nodes} traces",
        fill=TEXT_COLOR,
        font=small,
        anchor="lm",
    )
    final = image.resize((width, height), Image.Resampling.LANCZOS)
    return SweepGrid(final, grid.voltage_range, grid.log_current_range, drawn, rows * nodes)


def _segments(trace: np.ndarray, voltages: Sequence[float]) -> list[list[tuple[float, float]]]:
    """Split one trace into runs of finite points as ``(voltage, log10|I|)`` pairs."""
    values = np.asarray(trace, dtype=np.float64)
    if values.shape[0] != len(voltages):
        return []
    with np.errstate(divide="ignore", invalid="ignore"):
        logs = np.log10(np.maximum(np.abs(values), CURRENT_FLOOR))
    logs[~np.isfinite(values)] = np.nan
    segments: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for voltage, value in zip(voltages, logs, strict=True):
        if math.isnan(value):
            if current:
                segments.append(current)
                current = []
            continue
        current.append((float(voltage), float(value)))
    if current:
        segments.append(current)
    return segments


__all__ = ["SweepGrid", "log_current_bounds", "render_sweep_grid"]
