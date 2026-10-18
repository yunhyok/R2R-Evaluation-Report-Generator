"""Bundled, read-only application resources (the program icon) and app identity.

The path helpers are Qt-free so the CLI and tests can import them; only
:func:`apply_application_identity` touches PySide6, and it imports it lazily.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ASSETS = Path(__file__).resolve().parent / "assets"
APPLICATION_NAME = "R2R Evaluation Report Generator"
ORGANIZATION_NAME = "Yunhyok"
WINDOWS_APP_USER_MODEL_ID = "Yunhyok.R2REvaluationReportGenerator"


def _existing(path: Path) -> Path | None:
    return path if path.is_file() else None


def app_icon_path() -> Path | None:
    """The multi-size Windows icon, falling back to the 256 px PNG elsewhere."""
    if sys.platform.startswith("win"):
        return _existing(ASSETS / "icon.ico") or _existing(ASSETS / "icon.png")
    return _existing(ASSETS / "icon.png") or _existing(ASSETS / "icon.ico")


def _set_windows_app_user_model_id() -> None:
    """Group taskbar buttons under this app (not python.exe) and show its icon there."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_USER_MODEL_ID)
    except (AttributeError, OSError):  # pragma: no cover - non-Windows or restricted shell
        pass


def apply_application_identity(app: Any) -> Any:
    """Name the application and install the icon on ``app`` (a QApplication); returns the QIcon."""
    from PySide6.QtGui import QIcon

    _set_windows_app_user_model_id()
    app.setApplicationName(APPLICATION_NAME)
    app.setOrganizationName(ORGANIZATION_NAME)
    path = app_icon_path()
    icon = QIcon(str(path)) if path is not None else QIcon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    return icon


__all__ = [
    "APPLICATION_NAME",
    "ASSETS",
    "ORGANIZATION_NAME",
    "WINDOWS_APP_USER_MODEL_ID",
    "app_icon_path",
    "apply_application_identity",
]
