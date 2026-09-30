# Evaluation methodology and evidence boundary

## Design references

- ERC grid and palette reference: `C:\Users\yunhy\OneDrive\Documents\ERC_ML_20260320.xlsx`,
  worksheet `251002 AC 3 min stay-sam 1`, grid `C8:AO34`, legend `AO1:AP5`.
- Spatial map, confusion matrix, accuracy/precision/recall/F1 structure:
  `C:\Users\yunhy\OneDrive\Documents\GB-TEST BED ver2.7.docx`, Figure 5 and Table 1.
- Full 26 × 38 inspection/yield context:
  `C:\Users\yunhy\OneDrive\Documents\TFT test bed Y.C_F ver2.4.1.pdf`.
- Canonical mapping implementation used as the code-level rule:
  `C:\Users\yunhy\OneDrive\Documents\R2R Machine Learning\src\r2r_ml\data.py`, line 21 onward.

These references define layout and reporting structure. The binary conversion below is an explicit
operational assumption, not a claim that the source papers used the same binary ontology.

## Canonical three-class view

- `Pass`, `No Active`, `None` → `Normal`
- `Open` → `Open`
- `Short` → `Short`
- `No Gate Effect` → excluded from three-class evaluation

Unknown raw statuses are never inferred. Export is blocked until the operator records both an
explicit three-class mapping and an operational binary mapping.

## Operational binary view

- Measurement: exact raw `Pass` → `Pass`; every other explicitly mapped status → `Fail`
- Prediction: `Normal` → `Pass`; `Open` or `Short` → `Fail`
- Positive class: `Fail`

With matrix rows as actual and columns as predicted, `actual Fail / predicted Pass` is `FN` and is
highlighted red. `actual Pass / predicted Fail` is `FP`.

## Metrics

For a class treated one-vs-rest:

- `precision = TP / (TP + FP)`
- `recall = TP / (TP + FN)`
- `F1 = 2 × precision × recall / (precision + recall)`
- `specificity = TN / (TN + FP)`
- `FPR = FP / (FP + TN)`
- `FNR = FN / (FN + TP)`
- `accuracy = correct / total`
- `balanced accuracy = mean(Pass recall, Fail recall)`

Macro-F1 is the unweighted mean of defined class F1 values under the reporting contract. Weighted-F1
uses actual class support. The workbook also reports measurement and prediction pass rates with a
two-sided Wilson 95% confidence interval (`z = 1.959963984540054`).

## Undefined values

Precision, recall, F1, specificity, FPR, FNR, or a confidence interval is `N/A` when its required
denominator/support is absent. A supported class with errors but no true positive has F1 `0`; a class
with no actual support has F1 `N/A`. Three-class macro-F1 is `N/A` unless every target class
(`Normal`, `Open`, `Short`) has actual support. Undefined values are never silently replaced by zero.

## Traceability

Every generated workbook records input absolute paths, SHA-256, size, modification time, selected
worksheet, confirmed sample mapping, raw-to-canonical rules, and raw-to-binary rules. `Joined_Data`
stores only evaluation fields and source row identifiers; wide measurement sweep columns remain in
the hashed source file rather than being copied into the report.
Expanded Normal is an additional image-observability/reporting assumption, not relabeling of the
electrical ground truth. It maps No Gate Effect to Normal and keeps Short as Short; source and
existing three-class/binary results remain authoritative.

## Paired workbook display contract (v0.3.0)

The GUI performs one evaluation and renders two candidates: the selected output path retains the
backward-compatible code-and-fill workbook, while a deterministic `<stem>-color-only.xlsx` sibling
contains the same workbook with only the four 26 × 38 map body ranges (`D9:AO34`, `D44:AO69`,
`D79:AO104`, `D114:AO139`) blank. Fills, borders, dimensions, axes, legends, matrices, charts,
tables, audit data, and non-map content are not display-mode transforms and remain present. Both
candidates are reopened and structurally verified before either destination is committed. Existing
destinations are restored on cancellation, verification failure, or commit failure; a process crash
inside the short two-file commit window is an unavoidable filesystem boundary. A stale transaction
backup blocks automatic rerun so that it cannot be silently discarded; manual recovery/removal may
be required before retrying.

## Single-source label reports (v0.4.0)

Exactly one supplied input selects a descriptive measurement-only or prediction-only report.
The existing parser still requires 988 unique coordinates per sample. All supplied samples are
included; missing reference data is not synthesized and no sample matching or label remapping is
performed. Measurement labels, including custom TXT Converter rule outputs, are preserved literally.
Prediction labels retain the Normal/Open/Short validation contract.

Each sample has one 26 x 38 map, a code/color legend, and label counts/shares. Shares use that
sample's coordinate count; overall shares use all supplied coordinates, without averaging sample
percentages. The overall count chart starts at zero and uses the map colors. Source_Data retains
original labels, coordinates, source-row/provenance fields and available prediction confidences.
No F1, accuracy, confusion matrix, agreement, or Expanded Normal comparison is calculated.

The code-and-fill and color-only workbooks share the existing verified pair-commit and rollback
path; only D9:AO34 in each single-source report is cleared in the color-only copy. README records
the input kind and why comparison results are absent. Switching inputs or source worksheets
requires a fresh preflight; output paths cannot replace either source input.

## Profile reports: N datasets and selectable comparisons (v0.5.0)

A **report profile** (JSON, saved next to every workbook as `<stem>.profile.json` and embedded in
the README sheet) describes one run: the datasets, their label schemes, the confirmed sample
alignment, the comparisons, and the output options. `--profile FILE` regenerates the report
headlessly. The v0.2–v0.4 report is the profile produced by `profile.legacy_profile()`; its
three-class, binary, and Expanded Normal metrics are identical to `core.evaluate()` (regression
tested), while the workbook layout is the generic profile layout below.

### Label schemes

Raw label vocabularies live in `schemes/label_schemes.json` (bundled; a user copy at
`%APPDATA%\R2R Evaluation Report Generator\label_schemes.json` may add or override entries).
Each dataset declares a scheme; labels outside the declared scheme block the run instead of being
scored. Mapping presets (`legacy_to_3class`, `e5_to_binary`, `optical_to_binary`, …) express
raw → category rules; `Exclude` drops a record from that comparison and `*` is a fallback.
The bundled legacy presets reproduce the v0.2 hard-coded rules exactly.

Supported sources: measurement CSV/XLSX (`Name, Row, Node, Status`), R2R-Machine-Learning
predictions (`name, row, node, prediction`), ImageMarker 2.x exports (`Status` write-back or
`name,row,node,label` CSV) and Printed-Device-AI-Inspector long/matrix CSV (`image_path`, identity
parsed from `<name>_rgb_<row>_<node>.png`; the model is chosen as `provider:model_id`). The grid is
a dataset property (default 26 × 38); every sample must still supply exactly `rows × nodes`
unique coordinates.

### Comparison kinds

* **reference** — side A is ground truth for side B. Confusion matrix (rows actual, columns
  predicted), accuracy with Wilson CI, balanced accuracy, macro/weighted F1, per-class
  precision/recall/F1/specificity/FPR/FNR, Cohen's κ, multi-class MCC (Gorodkin 2004), and the
  **majority-class baseline** (share of A's largest class), so an accuracy below the baseline is
  visible in the report itself. Three-class macro-F1 keeps the strict `N/A` rule.
* **association** — neither side is truth (for example electrical `E-Invalid` against optical
  `BAD`). Accuracy-type metrics are deliberately not reported because they depend on which side is
  declared "truth". Reported instead:

  | Level | Statistic | Reference |
  |---|---|---|
  | whole r × c table | counts, row %, column %, expected counts, Pearson χ² and p, Cramér's V and the Bergsma bias-corrected V | Agresti 2013; Bergsma 2013 |
  | per cell | adjusted standardized residual, ~N(0,1) under independence; \|z\| > 1.96 highlighted | Haberman 1973 |
  | direction | Theil's U(B\|A) and U(A\|B) | Theil 1970 |
  | selected 2 × 2 cells | a/b/c/d, odds ratio with Woolf 95 % CI (Haldane–Anscombe 0.5 correction when a cell is empty), relative risk, φ, Yule's Q, two-sided Fisher exact p, Holm-adjusted p across the selected cells | Agresti 2013; Holm 1979 |
  | shared categories only | Cohen's κ with positive and negative agreement | Cohen 1960; Cicchetti & Feinstein 1990 |

  A Cochran warning is raised when more than 20 % of expected counts are below 5 or any is below 1.
  Undefined values stay `N/A`; a p-value that underflows double precision is printed as `< 1E-300`.

### Workbook layout

`README → Label_Audit → Alignment → Joined_Data (optional) → S01…Snn (optional) → C01…Cnn →
Overall Summary`. Each `Snn` sheet stacks, per aligned sample, one map per dataset (raw labels),
one agreement map per reference comparison (Match / Mismatch / Excluded / Missing) and one
co-occurrence map per selected 2 × 2 cell (Both / A only / B only / Neither). Map blocks are
`rows + 10` worksheet rows tall starting at row 8, columns `C…`, 2.5 wide; page breaks separate the
blocks. The color-only sibling clears only the map bodies. Verification reopens both files and
checks sheet order, map axes for the recorded grid, fills, and comparison titles.
