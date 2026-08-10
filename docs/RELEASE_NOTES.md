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
