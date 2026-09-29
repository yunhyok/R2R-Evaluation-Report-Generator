# Stable release validation — v0.4.0

Validation date: 2026-09-30 (Asia/Seoul).

- Ruff passed; the full pytest suite passed **52 tests**. After the final chart/UI adjustments,
  the affected GUI and single-source tests passed **16 tests**.
- CSV and XLSX checks covered measurement-only and prediction-only input, custom literal
  measurement labels, all supplied samples, missing coordinates, unknown predictions, stale
  worksheet selection, input/output collisions, and switching between single/paired input.
- Source self-test and the final frozen executable checks passed. Self-test now exports and
  verifies comparison, measurement-only, and prediction-only workbook pairs.
- Both single-source UI screens passed offscreen captures at DPR 1.0, 1.25, and 1.5. Generated
  maps and summaries for both display variants were exported read-only through native Excel:
  all eight checked PDFs were one A3 landscape page; map and summary renders were inspected.
- The final disposable installer passed fresh install, installed self-test, synthetic export,
  offscreen GUI smoke, same-installer upgrade, post-upgrade self-test, and uninstall at each
  scale factor 1.0, 1.25, and 1.5. Installation roots and uninstall entries were removed.
- The production installation was preserved. This release's new acceptance checks use synthetic
  inputs and offscreen UI; real research data and a visible installed user workflow were not rerun.
- The final executable archive contains 218 entries and no research-data, model-weight, or
  private-key file extensions. Source-only and staged-secret checks run before publication.
- Runtime dependencies and the proprietary license remain unchanged; installers are unsigned.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Frozen EXE | 61,154,073 | `81745F1E41A93B73D5EDC1D3E9826DBBBE4B4484D0F8AB88C504A5C4525154E4` |
| Production installer | 62,384,121 | `3D70C4C213F03529B4913A9A98A2A0ABFCD8BCD3CCCBAE0937EB2657B49C4149` |
| Disposable installer | 62,384,141 | `B411B6B6E6B8C80069829A94F138FF15AC378807AC62177264D84A20A7F1EF85` |

Publication status is recorded in the
[v0.4.0 release](https://github.com/yunhyok/R2R-Evaluation-Report-Generator/releases/tag/v0.4.0).

# Stable release validation — v0.3.0

Validation date: 2026-09-30 (Asia/Seoul).

- Ruff passed; pytest **43 passed**; source self-test passed at version 0.3.0.
- Source-only guard passed. Gitleaks found no secrets in all existing Git history or the
  candidate source snapshot. Research inputs and generated workbooks remain outside Git.
- A fresh PyInstaller build passed packaged self-test and offscreen GUI smoke. Its archive
  contained 218 entries, with no research-data, model-weight, or private-key file extensions.
- Fresh production and disposable installers were compiled from the tested source. The disposable
  installer passed fresh install, installed self-test, synthetic workbook export, offscreen GUI
  smoke, same-installer upgrade, post-upgrade self-test, and uninstall. The disposable executable,
  installation directory, and uninstall registry entries were removed successfully.
- The already-running production installation was preserved.
- The real-research-data, visible UI, and multi-DPI acceptance checks dated 2026-08-26 below are
  historical evidence; they were not repeated for this publication. No application source was
  changed after the 43-test run and before the fresh build.
- Installers remain unsigned. Public repository visibility does not change `LICENSE`.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Frozen EXE | 61,144,308 | `62C9CA0C0A56D54A6279944143C95AF9BF95BDA49A1C34CAF73A7AF85B67CE80` |
| Production installer | 62,374,832 | `32CA8D40FB303FCBD8E4DF36EAAC02DBDC7E9E815CF3EA0C6AE0F4441A16C489` |
| Disposable installer | 62,374,847 | `04C9FCD9FD4F31669446CC6E3FF4BEC126E5C900A24C7B4FDE14F1FE3A693F00` |

Remote publication status is recorded in [PR #1](https://github.com/yunhyok/R2R-Evaluation-Report-Generator/pull/1)
and the [v0.3.0 release](https://github.com/yunhyok/R2R-Evaluation-Report-Generator/releases/tag/v0.3.0).

# Historical validation record — v0.3.0

Validation date: 2026-08-26 (Asia/Seoul).

The v0.3.0 source, packaged, installed, real-data, paired-output, and DPI evidence below was
Sol-verified locally. GitHub publication and release staging were not performed in this turn.

## Static and automated tests

- `python -m ruff check .`: passed.
- `python -m pytest`: **43 passed**.
- Source self-test: `R2R_EVALUATION_REPORT_SELF_TEST_OK version=0.3.0`.
- Source-only guard: `SOURCE_ONLY_GUARD_OK`.
- Runtime dependency contract remains exactly `PySide6==6.11.1`, `openpyxl==3.1.5`.

## Real-data paired acceptance

The acceptance run used 10 measurement samples (9,880 rows), 11 prediction samples (10,868 rows),
and one prediction-only sample. All expected mapped 3-class, operational binary, Expanded Normal,
yield, and per-sample KPI values matched the established acceptance vectors.

The source pair contained 14 sheets (10 report tabs). The code-and-fill workbook had 39,520 map body
codes; the color-only workbook had 0. Every non-map value, report fill/border style, dimension,
print setting, legend, chart, and matrix matched between the pair, apart from the intentional README
display-mode marker. Artifact-tool formula/error search returned 0, and every color-only report tab
rendered and passed visual inspection.

| Workbook | Bytes | SHA-256 |
|---|---:|---|
| `R2R-Evaluation-Acceptance-20260826.xlsx` | 1,146,061 | `47ca6b36ac2ecc0fedb57eabfe0d66ee651c91445556b75fb99cf6acfbad96bf` |
| `R2R-Evaluation-Acceptance-20260826-color-only.xlsx` | 1,134,519 | `8a7d1bd0d5f9f64f6df9a0e9238fac4d90d9b4ee3d9f50a00bd42fdaf96c740d` |

## UI, packaged, and installed evidence

- Source UI captures passed at effective 100%, 125%, and 150% with DPR 1.0, 1.25, and 1.5.
- Packaged executable self-test and GUI smoke passed at effective 100%, 125%, and 150%; the
  packaged actual paired UI workflow passed once at the default host 150% scale.
- Installed disposable actual paired UI passed at effective 100%, 125%, and 150%. Independent
  checks confirmed correct map counts for all six generated workbooks (three code-and-fill and three
  color-only outputs).
- After uninstall, the executable, install root, and HKCU/HKLM uninstall keys were absent.

## Installer artifacts and lifecycle

The standard disposable lifecycle for AppId `{2E42973D-7A33-4CF3-91FD-7A4C62ACCC4F}` completed one
fresh install, installed self-test, synthetic export, GUI smoke, same-installer upgrade, and hidden
uninstall run. Separately, the installed-real-UI harness repeated offscreen GUI smoke and actual
paired UI at effective 100%, 125%, and 150% before uninstall. The production and disposable installers are unsigned; Windows SmartScreen
may show a reputation warning, which is separate from functional validation.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Production installer | 61,572,742 | `FFEDC9CF7E4B73936E6D76F6D0BEFA8D160782EC760B1609155859F84A73364A` |
| Disposable installer | 61,572,757 | `A6E78B91FC70F9E92D555E0A09105C450A45F20A16A16EFAF892918C99752992` |

GitHub commits, pull requests, and releases were not published in this turn.

# Historical validation record — v0.2.0-rc.1

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
