# v0.6.0

- New comparison group `optical_vlm_local` ("Local LLM"): Inspector model columns from a local
  provider (`lmstudio`, `ollama`, `llamacpp`, `vllm`, `local`) are pre-sorted into it, other
  providers into `optical_vlm` (cloud). One export can be added once per model; default titles
  carry `[provider:model_id]`; changing the model column re-suggests the group and default title.
- README sheet gains *Comparison group*, *Role key* and *Provider* (`lmstudio (local)`,
  `gemini (cloud)`) columns; Overall Summary gains a *Comparison groups (dataset roles)* block.
  Metrics are unchanged; see METHODOLOGY "Comparison groups and the Local LLM group".
- Fixed (v0.5.1 regression): the GUI preflight never started its second stage (load after
  sample-block inspection) in real threaded mode and stopped at "이전 작업이 끝나기를 기다리세요.";
  job results are now delivered after the worker thread is released. A threaded-mode regression
  test covers preflight and generate.
- Fixed: the Inspector model column was dropped while the page was disabled during a job
  ("choose the Inspector model column").

# v0.5.1

- Repeated sample Names and incomplete arrays no longer reject a merged converter CSV: the parser
  splits each Name into occurrences (a repeated coordinate starts a new block) and the wizard
  opens a block-selection dialog (include / rename / drop, identical blocks flagged, incomplete
  blocks excluded). The choice is stored in the profile (`datasets[].samples`) so `--profile`
  reproduces it. The strict one-per-Name contract still applies when no selection is given.
- Printed-Device-AI-Inspector `.xlsx` exports (Run / Results / Matrix / Attempts) are read
  directly (Matrix preferred); long-format exports list concrete `provider:model_id` choices.
- A task without a verdict (failed, unknown outcome) keeps its coordinate under the reserved
  `(missing)` label: accepted by every scheme, excluded from every comparison, grey on maps.
- Primary-dataset samples without an aligned partner stay in the report (maps only).
- Fixed an O(n²) label-canonicalisation scan that made 70-sample reports take >10 minutes
  (now ~30 s for the full pair).

# v0.5.0

- Linear five-step wizard (datasets → label schemes → comparisons → output → generate) replaces
  the two-input screen as the default GUI; `--legacy-ui` still opens the v0.4 screen.
- Any number of label datasets: measurement/prediction files, ImageMarker labels and
  Printed-Device-AI-Inspector `image_path` exports (model column selectable). The grid is a
  dataset property (default 26 × 38).
- Label schemes and mapping presets move to `schemes/label_schemes.json` (bundled + user overlay);
  the legacy presets reproduce the v0.2 rules exactly. Labels outside a declared scheme block the
  run.
- Comparisons are user-defined and omittable: `reference` (confusion matrix, F1, κ, MCC,
  majority-class baseline) and `association` (χ², Bergsma-corrected Cramér's V, Haberman adjusted
  residuals, Theil's U, per-cell odds ratio / Fisher / Holm, κ + PA/NA when categories are shared).
- New workbook layout with per-sample spatial maps, agreement and co-occurrence maps, one sheet per
  comparison, and the report profile embedded in README; `<stem>.profile.json` is saved beside the
  output and `--profile FILE [--output X]` regenerates headlessly.
- Runtime dependencies now include `numpy` and `scipy` (exactly pinned); the PyInstaller spec ships
  them and the schemes JSON. Self-test additionally renders a profile report.

# v0.4.0

- Measurement-only and prediction-only inputs now generate 26 x 38 label maps, label counts/shares,
  source coordinate data, and overall label-distribution charts.
- Single-source reports omit comparison metrics, matching controls, and label-remapping controls.
  Existing two-input comparison reports are preserved.
- Custom measurement labels remain literal; prediction labels and complete-grid validation remain
  strict. Prediction-only reports include all prediction samples.
- Both code-and-color and color-only workbooks are produced. Input changes require fresh preflight,
  and output/input path collisions are blocked.
- Packaged/installed self-tests now exercise both single-source modes as well as comparison.

# v0.3.0

- Added one-operation paired export: code-and-fill workbook plus deterministic `-color-only.xlsx`.
- Added two-candidate verification and rollback-safe dual-destination commit for GUI generation.
- GUI now previews both paths, confirms all existing destinations together, and exposes separate
  open buttons for each workbook and the containing folder.
- Version/installer metadata bumped to 0.3.0. Source, real-data, packaged, installed, paired-output,
  and installer lifecycle validation passed on 2026-08-26; see `docs/VALIDATION.md`.
- Stable release preparation includes a fresh source/installer validation on 2026-09-30;
  see `docs/VALIDATION.md`. Installers remain unsigned, so Windows SmartScreen reputation warnings
  are possible. Repository visibility does not change the terms in `LICENSE`.

# v0.2.0-rc.1

- Added auditable Expanded Normal scenario analysis, mapping No Gate Effect to Normal while keeping Short separate.
- Preserved raw, mapped 3-class, and Fail-positive binary outputs; added scenario maps, metrics, and audit fields.
- Validation completed 2026-08-11 across source, frozen, packaged, and installed workflows; see
  `docs/VALIDATION.md` for acceptance workbook hashes, matrix evidence, page counts, and artifact checksums.

# v0.1.0-rc.1

Initial private release candidate of R2R Evaluation Report Generator.

## Included

- Korean PySide6 guided workflow for measurement/prediction CSV or XLSX inputs.
- Strict 26 × 38 coordinate validation, explicit signature mapping confirmation and unknown-label
  blocking.
- Raw cross-table, mapped three-class and Fail-positive operational binary evaluation.
- Per-device three-map A3 reports, provenance-focused joined data and overall KPI/ranking summary.
- Atomic workbook replacement with reopen verification and cancellation cleanup.
- Per-user Inno Setup installer with production and disposable validation AppIds.

## Evidence

- Ruff passed; pytest 36/36 passed.
- Representative 9,880-row measurement acceptance reproduced every planned matrix and KPI.
- Excel visual QA covered 10 × 3 report pages and a two-page overall summary.
- Source, frozen and installed UI paths were exercised; frozen/installed real-data UI generation
  succeeded.
- Disposable installer fresh/upgrade/uninstall lifecycle passed at 100/125/150% scale factors.

## Known distribution note

The installer is not code-signed, so Windows SmartScreen may show a reputation warning. No functional
failure was observed in the isolated installer tests.
