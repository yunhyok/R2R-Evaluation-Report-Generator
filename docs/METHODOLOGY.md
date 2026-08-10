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
