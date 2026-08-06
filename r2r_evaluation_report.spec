# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

project = Path(SPECPATH)

a = Analysis(
    [str(project / "scripts" / "pyinstaller_entry.py")],
    pathex=[str(project / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[
        "PySide6",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "openpyxl",
        "openpyxl.chart",
        "openpyxl.styles",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "IPython",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "_pytest",
        "matplotlib",
        "numpy",
        "pandas",
        "pytest",
        "scipy",
        "sklearn",
        "tkinter",
        "torch",
    ],
    noarchive=False,
)
# A developer shell may expose Conda's version-suffixed ICU 73 binaries.
# Qt 6.11 on supported Windows uses the OS icuuc.dll shim with unversioned
# exports; bundling Conda's icuuc.dll shadows that shim and makes QtCore fail
# with WinError 127. Keep the companion ICU data DLL and remove only the
# incompatible unversioned loader.
excluded_environment_icu = {"icuuc.dll"}
a.binaries = [
    entry
    for entry in a.binaries
    if Path(entry[0]).name.casefold() not in excluded_environment_icu
]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="R2REvaluationReportGenerator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
