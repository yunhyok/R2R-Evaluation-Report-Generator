# v0.9.0

- Sample map sheets now show the measurement itself: a dataset exported by R2R-TXT-Converter
  (`_merged.csv` voltage-headed current columns, `_raw.csv` `I_<voltage>V` columns, or the same
  table as `.xlsx`) keeps every device's gate sweep, and right below that dataset's raw-label map
  the sheet embeds one image with all `rows x nodes` transfer curves (`log10|I|` vs `V`, one axis
  pair per sample, curve coloured by the device's label, grey where no usable sweep). Identical
  sweep tables (an ImageMarker write-back) are drawn once; datasets without sweep columns are
  unchanged.
- New output option "map 시트에 측정 transfer curve 격자 포함" (`options.sweep_maps`, default on,
  inert without spatial maps); README records the number of embedded grids and reopen
  verification checks it against the images present. The self-test's synthetic measurement now
  carries sweep columns so the packaged build exercises the image path.
- Application icon (report page with the 26 x 38 label map and a verdict badge) for the window,
  taskbar, EXE and installer; `assets/icon.svg` + `scripts/build_icon.py`.
- New dependency `Pillow==12.3.0`.

# v0.8.0

- Partial sample blocks are opt-in: the block-selection dialog gains "불완전한 블록도 포함 허용".
  When on, a block with fewer coordinates than the grid can be included as a partial sample
  (status `부분 (480/988)`, bulk button "불완전 블록까지 모두 포함"); the consent is stored in the
  profile as `datasets[].allow_partial` and honoured by `--profile`. Off (the default) keeps the
  complete-array contract; a file whose blocks are all incomplete used to stop at "포함할 샘플이
  없습니다".
- Comparisons score only coordinates present on both sides; coordinates present on one side only
  are reported as *Unpaired coordinates* (overall and per sample) and never substituted. Maps
  cover the whole grid, painting absent coordinates `(no data)` (white) with the title
  `(present/size coordinates)`; agreement and co-occurrence maps show them as `Missing`.
- Coverage is recorded everywhere a reader looks: README *Partial blocks* column and a new
  *Warnings (non-blocking)* section (one line per partial sample), Alignment *coverage* columns,
  Overall Summary *Coverage* column in the comparison-groups block.
- Grids still have to match the primary dataset; a 20 × 24 array is a partial block inside the
  26 × 38 grid.

# v0.7.0

- Good / Bad / Open prediction sets from R2R-Machine-Learning 0.6.0 (`visual_3class`) now load:
  `prob_<class>` probability columns are read for any class set with the same contract (supplied
  together, in [0, 1], summing to 1 within 1e-5). Until now the `prob_Open` header matched the
  electrical alias and the parser demanded `prob_Normal`/`prob_Short` too, rejecting the file.
  `R2RRecord.class_probabilities` keeps the per-class values; the legacy trio fields are filled only
  for Normal/Open/Short exports.
- New comparison group `optical_ml` ("광학 ML 예측 (Good/Bad/Open 육안 라벨 학습)"): an ML model
  trained on visual-inspection labels. Its predictions share the `optical_3` vocabulary, so human or
  VLM labels are its reference (reference comparison) and electrical status an association. The
  wizard pre-selects the group from the `prob_<class>` columns of an R2R-Machine-Learning export
  (Good/Bad/Open → `optical_ml`; Normal/Open/Short or E-5 → `electrical_ml`; custom → no suggestion).
- Labels of a dataset with a declared scheme are reported and compared in the scheme's spelling
  (`Good` → `GOOD`); category targets inside one comparison that differ only in case collapse to one
  category (first declared spelling wins). Before, human `GOOD` vs ML `Good` under identity mappings
  silently produced a six-category matrix with accuracy 0. `Label_Audit` gains an *Observed
  spellings* column.
- Overall Summary names the visual-label ML group; the self-test adds a Good/Bad/Open prediction
  dataset with a binary reference comparison and a raw-status association.

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
