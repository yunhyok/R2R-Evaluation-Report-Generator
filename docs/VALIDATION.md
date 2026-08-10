# Validation record — v0.2.0-rc.1

Validation date: 2026-08-11 (Asia/Seoul).
Platform: Windows 11 `10.0.26200`, Python `3.12.13`, PySide6/Qt `6.11.1`,
openpyxl `3.1.5`, PyInstaller `6.21.0`, Inno Setup `6.7.3`.

## Static and automated tests

- `python -m ruff check .`: passed.
- `python -m pytest`: **36 passed**.
- Source self-test: `R2R_EVALUATION_REPORT_SELF_TEST_OK version=0.2.0`, deterministic workbook reopened.
- Frozen executable self-test and GUI smoke: passed.
- Source-only guard: `SOURCE_ONLY_GUARD_OK tracked_files=30`.
- Packaging contract: **4 passed**.
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
- Expanded Normal scenario, rows Actual Normal/Open/Short and columns Predicted Normal/Open/Short:
  `[[9476, 202, 202], [0, 0, 0], [0, 0, 0]]`; total `9,880`.
- Expanded Normal recall `95.9109%`, Normal F1 `97.9128%`; strict macro-F1 `N/A`.
- Existing mapped 3-class and Fail-positive binary values are unchanged.

Authoritative acceptance workbook:
`validation/R2R-Evaluation-Acceptance-20260810.xlsx`, 1,146,026 bytes,
SHA-256 `62C92726CBFE5EA10B31DC91AAFCAEE5AD21252DA83358DEC2C9C9DD8752087F`.

## Workbook and Excel visual QA

- Reopen/structural verifier passed with sheet order
  `README, Mapping_Audit, Joined_Data, R01…R10, Overall Summary` (14 sheets).
- Each report uses print area `A1:BM142`, row breaks `[39, 74, 109]`, and exactly four A3 landscape
  pages; Overall Summary is exactly three A3 landscape pages.
- Microsoft Excel PDF export confirmed these exact page counts. All ten Expanded Normal report pages
  and the summary scenario page were raster/visual checked; representative R01, R10 and summary
  workbooks showed no overlap or clipping.
- Excel-native charts have verified source formulas; each report has two charts and the summary one.

## UI/UX and packaged/installed execution

- Source UI preflight used the two representative real files without loading 9,880 raw rows into a
  GUI table. Captures passed at effective DPR `1.0`, `1.25`, and `1.5` (host native 150%; Qt factors
  `0.6666667`, `0.8333333`, `1`). The fourth label-mapping column was visible and generation enabled.
- Source and frozen GUI smoke passed at effective `100%`, `125%`, and `150%`; frozen actual UI workflow passed.
- Frozen executable Windows UI Automation completed: set both real inputs and output, preflight,
  explicitly confirm all ten proposals, generate, expose open-output controls, close.
  Generated workbook reopened with all 14 sheets and authoritative KPI values.
- Installed disposable lifecycle and actual UI workflow passed at effective `100%`, `125%`, and `150%`,
  including clean uninstall.
- Direct, packaged, and installed generated workbooks all passed the verifier and had the same Expanded
  Normal matrix and print breaks.
- Overwrite ownership, disabled controls while working, cancellation, error recovery and output-open
  visibility are covered by GUI/unit integration tests.

## Installer lifecycle and artifacts

Disposable AppId `{2E42973D-7A33-4CF3-91FD-7A4C62ACCC4F}` was validated independently at each
effective scale `100%`, `125%`, and `150%` (Qt factors `0.6666667`, `0.8333333`, and `1` on the
host-native 150% display):

`fresh install → installed self-test → synthetic export → GUI smoke → same-installer upgrade →
post-upgrade self-test → uninstall → executable/registry/residual check`

All three runs emitted `INSTALLER_LIFECYCLE_OK`.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Frozen EXE | 60,315,655 | `F3D7AD820C4F8FEF95FE225819E7EE7465F68CDF291D534DD78A0D361978026B` |
| Production installer | 61,564,988 | `009EE3CFEB91AD6C25BA01FE1447C759EE0F5A3E8DC3584DE63B650677ABF32B` |
| Disposable installer | 61,565,005 | `CF5A6B3998D8AE8677A9DC12D99B480C0E6DCAF63EAE6E5D9C5B45042E4F1ECA` |

The production installer is unsigned. A possible Windows SmartScreen reputation warning is a code
signing/reputation condition and is recorded separately from the completed functional validation.

## Packaging defect closed during validation

A Conda directory on the build host exposed an incompatible ICU 73 `icuuc.dll`. PyInstaller copied
it, shadowing the Windows ICU shim and causing frozen `QtCore` WinError 127. PE import/export evidence
showed Qt 6.11 requires unversioned ICU symbols while the Conda DLL exports `_73` symbols. The spec
now removes only the accidental `icuuc.dll` and retains `icudt73.dll`; one-file GUI and all installer
gates above passed after the correction.
