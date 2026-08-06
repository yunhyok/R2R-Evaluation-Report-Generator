# Validation record — v0.1.0-rc.1

Validation date: 2026-08-07 (Asia/Seoul).
Platform: Windows 11 `10.0.26200`, Python `3.12.13`, PySide6/Qt `6.11.1`,
openpyxl `3.1.5`, PyInstaller `6.21.0`, Inno Setup `6.7.3`.

## Static and automated tests

- `python -m ruff check .`: passed.
- `python -m pytest`: **36 passed**.
- Source self-test: `R2R_EVALUATION_REPORT_SELF_TEST_OK`, deterministic workbook reopened.
- Frozen executable self-test: passed.
- Source-only guard is rerun after staging; repository rules reject CSV/XLS/XLSX/EXE/MSI/model files
  and build/dist/runs paths.
- Runtime dependency contract: exactly `PySide6==6.11.1`, `openpyxl==3.1.5`; pandas, NumPy and
  Torch are not runtime dependencies.

## Representative real-data acceptance

Inputs remain outside the repository.

| Source | Rows/samples | SHA-256 |
|---|---:|---|
| Measurement `20260731 data_merged_prediction-set-20260804.csv` | 9,880 / 10 | `35bbeda6a94691c60f3270590afa3ae73b14efd066b229e881e3b5b5c77b913a` |
| Prediction `predictions.csv` | 10,868 / 11 | `cf8e917abfe74560be082a825bddfd1e1d0196378e78838166bafca39afbabec` |

- Ten signature mappings were explicitly confirmed.
- Prediction-only audit entry: `260701 p3meemt 8mg-ac 8kgf 350- sam 11_2` (988 rows).
- Three-class scored/excluded: `9,036 / 844`.
- Mapped 3×3 rows Normal/Open/Short: `[[8806, 193, 37], [0, 0, 0], [0, 0, 0]]`.
- Open F1, Short F1 and 3-class macro-F1: `N/A` because actual support is absent.
- Binary 2×2, rows Actual Pass/Fail and columns Predicted Pass/Fail:
  `[[5117, 178], [4359, 226]]`.
- Accuracy `54.0789%`; balanced accuracy `50.7837%`; Fail recall `4.9291%`;
  Fail F1 `9.0599%`; macro-F1 `39.1722%`; weighted-F1 `41.3361%`.
- Measurement/prediction pass rate: `53.5931% / 95.9109%`.

Authoritative acceptance workbook:
`validation/R2R-Evaluation-Acceptance-20260807.xlsx`, 998,576 bytes,
SHA-256 `014C97CAB6E9D0DBF8484DC685BA281B405FB8A10B27E989EAF76AAC0118B082`.

## Workbook and Excel visual QA

- Reopen/structural verifier passed with sheet order
  `README, Mapping_Audit, Joined_Data, R01…R10, Overall Summary` (14 sheets).
- Every report body contains exactly 988 nonblank cells in all three maps.
- `C:AO` width `2.5`; map rows height `17 pt`; print area `A1:BM107`.
- Excel-native charts have verified source formulas; each report has two charts and the summary one.
- Microsoft Excel PDF export: each `R01…R10` is exactly three A3 landscape pages;
  `Overall Summary` is two logical A3 pages.
- All 30 report pages plus both summary pages were rasterized and visually checked for map, legend,
  matrix, chart and text overlap. An initial two-page report pagination and seven-page fragmented
  summary were corrected before release.

## UI/UX and packaged/installed execution

- Source UI preflight used the two representative real files without loading 9,880 raw rows into a
  GUI table. Top/bottom captures were checked at logical scale factors `1`, `1.25`, and `1.5`;
  a native Windows render at system 150% verified Korean glyphs, long `V:`/OneDrive paths and scroll.
- Source and frozen GUI smoke passed at `100%`, `125%`, and `150%`.
- Frozen executable Windows UI Automation completed: set both real inputs and output, preflight,
  explicitly confirm all ten proposals, generate, expose open-output controls, close.
  Generated workbook reopened with all 14 sheets and authoritative KPI values.
- Installed disposable build completed the same real-data UI workflow and generated a separately
  verified workbook before clean uninstall.
- Overwrite ownership, disabled controls while working, cancellation, error recovery and output-open
  visibility are covered by GUI/unit integration tests.

## Installer lifecycle and artifacts

Disposable AppId `{2E42973D-7A33-4CF3-91FD-7A4C62ACCC4F}` was validated independently at each scale
factor `1`, `1.25`, and `1.5`:

`fresh install → installed self-test → synthetic export → GUI smoke → same-installer upgrade →
post-upgrade self-test → uninstall → executable/registry/residual check`

All three runs emitted `INSTALLER_LIFECYCLE_OK`.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Frozen EXE | 60,310,166 | `4F2C3BF027F66DD93AB86473FB8B899F0BE90B30070ECE43A6A6971C28218DB3` |
| Production installer | 61,558,575 | `D9A470B125599FC88A1509476AF50D5AA5332ACE02916A740B07ABB2FE8DA732` |
| Disposable installer | 61,558,594 | `65E9736F75D9F7D97C47BCCDB8E0675F72571C123C3E090EBD82E633DD0CAC28` |

The production installer is unsigned. A possible Windows SmartScreen reputation warning is a code
signing/reputation condition and is recorded separately from the completed functional validation.

## Packaging defect closed during validation

A Conda directory on the build host exposed an incompatible ICU 73 `icuuc.dll`. PyInstaller copied
it, shadowing the Windows ICU shim and causing frozen `QtCore` WinError 127. PE import/export evidence
showed Qt 6.11 requires unversioned ICU symbols while the Conda DLL exports `_73` symbols. The spec
now removes only the accidental `icuuc.dll` and retains `icudt73.dll`; one-file GUI and all installer
gates above passed after the correction.
