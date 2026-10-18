"""Render assets/icon.svg into the PNG/ICO files the app, EXE and installer use.

Run after editing the SVG::

    python scripts/build_icon.py

Outputs (committed, so builds need neither Qt SVG nor Pillow at build time):
- src/r2r_evaluation_report/assets/icon.png  (256 px, window icon on non-Windows)
- src/r2r_evaluation_report/assets/icon.ico  (16/24/32/48/64/128/256, EXE + installer)
- assets/icon-preview.png                     (row of the rendered sizes, for review)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "assets" / "icon.svg"
PACKAGE_ASSETS = ROOT / "src" / "r2r_evaluation_report" / "assets"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(renderer: QSvgRenderer, size: int) -> QImage:
    image = QImage(QSize(size, size), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()
    return image


def main() -> int:
    QGuiApplication.instance() or QGuiApplication(sys.argv)
    renderer = QSvgRenderer(str(SVG))
    if not renderer.isValid():
        print(f"cannot parse {SVG}", file=sys.stderr)
        return 1
    PACKAGE_ASSETS.mkdir(parents=True, exist_ok=True)
    images = {size: render(renderer, size) for size in SIZES}
    images[256].save(str(PACKAGE_ASSETS / "icon.png"), "PNG")

    from PIL import Image

    frames = []
    for size in SIZES:
        path = ROOT / "assets" / f"_tmp_{size}.png"
        images[size].save(str(path), "PNG")
        frames.append(Image.open(path).convert("RGBA"))
    # Pillow writes one ICO holding every listed size, each from its own frame.
    frames[-1].save(
        PACKAGE_ASSETS / "icon.ico",
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=frames[:-1],
    )
    for size in SIZES:
        (ROOT / "assets" / f"_tmp_{size}.png").unlink()

    preview = Image.new(
        "RGBA", (sum(SIZES) + 16 * (len(SIZES) + 1), 256 + 32), (255, 255, 255, 255)
    )
    x = 16
    for size, frame in zip(SIZES, frames, strict=True):
        preview.paste(frame, (x, 16 + (256 - size) // 2), frame)
        x += size + 16
    preview.save(ROOT / "assets" / "icon-preview.png")
    print("wrote", PACKAGE_ASSETS / "icon.png", PACKAGE_ASSETS / "icon.ico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
