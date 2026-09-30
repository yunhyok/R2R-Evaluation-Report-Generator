"""Report profiles: N label datasets, confirmed sample alignment, and comparison specs.

A :class:`ReportProfile` is the complete, serialisable description of one report
run.  Saving it next to the workbook (and dumping it into the README sheet) makes
a report reproducible from the CLI with ``--profile``, and lets scripts or an
assistant author runs without touching the GUI.

Two comparison kinds exist:

* ``reference`` — side A is ground truth for side B (electrical measurement vs
  the ML model trained on it).  Confusion matrix, precision/recall/F1, kappa,
  MCC and the majority-class baseline.
* ``association`` — neither side is truth (electrical ``E-Invalid`` vs optical
  ``BAD``).  Symmetric measures from :mod:`association`.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from . import association as assoc
from .core import (
    DEFAULT_GRID,
    DataContractError,
    Grid,
    MappingProposal,
    Metrics,
    ParsedDataset,
    R2RRecord,
    SourceMetadata,
    _metrics,
    _normalise,
    parse_dataset,
    propose_mappings,
)
from .schemes import EXCLUDE, WILDCARD, SchemeRegistry, load_registry

ComparisonKind = Literal["reference", "association"]
PROFILE_SCHEMA_VERSION = 1
ROLES: tuple[str, ...] = (
    "electrical_gt",
    "electrical_ml",
    "optical_human",
    "optical_vlm",
    "other",
)


class ProfileError(ValueError):
    """Raised for an inconsistent profile (unknown ids, missing mappings, ...)."""


# --------------------------------------------------------------------------- specs


@dataclass(frozen=True)
class DatasetSpec:
    id: str
    path: str
    role: str = "other"
    scheme: str | None = None
    worksheets: tuple[str, ...] = ()
    grid_rows: int = DEFAULT_GRID.rows
    grid_nodes: int = DEFAULT_GRID.nodes
    model_column: str | None = None
    title: str = ""

    @property
    def grid(self) -> Grid:
        return Grid(self.grid_rows, self.grid_nodes)

    @property
    def label(self) -> str:
        return self.title or self.id

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "path": self.path,
            "role": self.role,
            "scheme": self.scheme,
            "grid": [self.grid_rows, self.grid_nodes],
        }
        if self.worksheets:
            data["worksheets"] = list(self.worksheets)
        if self.model_column:
            data["model_column"] = self.model_column
        if self.title:
            data["title"] = self.title
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DatasetSpec:
        grid = data.get("grid") or [DEFAULT_GRID.rows, DEFAULT_GRID.nodes]
        worksheets = data.get("worksheets") or ()
        if isinstance(worksheets, str):
            worksheets = (worksheets,)
        return cls(
            str(data["id"]),
            str(data["path"]),
            str(data.get("role") or "other"),
            data.get("scheme") or None,
            tuple(str(item) for item in worksheets),
            int(grid[0]),
            int(grid[1]),
            data.get("model_column") or None,
            str(data.get("title") or ""),
        )


@dataclass(frozen=True)
class CellSpec:
    """One collapsed 2 x 2 of interest: ``A in labels_a`` against ``B in labels_b``."""

    name: str
    labels_a: tuple[str, ...]
    labels_b: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "a": list(self.labels_a), "b": list(self.labels_b)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CellSpec:
        return cls(
            str(data["name"]),
            tuple(str(x) for x in data.get("a") or ()),
            tuple(str(x) for x in data.get("b") or ()),
        )


@dataclass(frozen=True)
class ComparisonSpec:
    id: str
    kind: ComparisonKind
    a: str
    b: str
    title: str = ""
    mapping_a: Mapping[str, str] = field(default_factory=dict)
    mapping_b: Mapping[str, str] = field(default_factory=dict)
    categories: tuple[str, ...] = ()
    positive: str | None = None
    exclude_a: tuple[str, ...] = ()
    exclude_b: tuple[str, ...] = ()
    cells: tuple[CellSpec, ...] = ()
    strict_macro: bool = True
    preset_a: str | None = None
    preset_b: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("reference", "association"):
            raise ProfileError(f"comparison {self.id!r}: kind must be reference or association")
        if self.a == self.b:
            raise ProfileError(f"comparison {self.id!r}: sides must be different datasets")
        if self.kind == "reference" and not self.categories:
            targets = tuple(
                dict.fromkeys(
                    value
                    for mapping in (self.mapping_a, self.mapping_b)
                    for value in mapping.values()
                    if value != EXCLUDE
                )
            )
            object.__setattr__(self, "categories", targets)

    @property
    def label(self) -> str:
        return self.title or self.id

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "a": self.a,
            "b": self.b,
            "title": self.title,
            "mapping_a": dict(self.mapping_a),
            "mapping_b": dict(self.mapping_b),
            "categories": list(self.categories),
            "positive": self.positive,
            "exclude_a": list(self.exclude_a),
            "exclude_b": list(self.exclude_b),
            "cells": [cell.to_dict() for cell in self.cells],
            "strict_macro": self.strict_macro,
        }
        if self.preset_a:
            data["preset_a"] = self.preset_a
        if self.preset_b:
            data["preset_b"] = self.preset_b
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ComparisonSpec:
        return cls(
            str(data["id"]),
            str(data["kind"]),  # type: ignore[arg-type]
            str(data["a"]),
            str(data["b"]),
            str(data.get("title") or ""),
            {str(k): str(v) for k, v in (data.get("mapping_a") or {}).items()},
            {str(k): str(v) for k, v in (data.get("mapping_b") or {}).items()},
            tuple(str(x) for x in data.get("categories") or ()),
            data.get("positive") or None,
            tuple(str(x) for x in data.get("exclude_a") or ()),
            tuple(str(x) for x in data.get("exclude_b") or ()),
            tuple(CellSpec.from_dict(item) for item in data.get("cells") or ()),
            bool(data.get("strict_macro", True)),
            data.get("preset_a") or None,
            data.get("preset_b") or None,
        )


@dataclass(frozen=True)
class AlignmentSpec:
    """Confirmed sample identity: primary sample title -> member sheet per dataset."""

    sample: str
    members: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {"sample": self.sample, "members": dict(self.members)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AlignmentSpec:
        return cls(str(data["sample"]), {str(k): str(v) for k, v in data["members"].items()})


@dataclass(frozen=True)
class ProfileOptions:
    title: str = ""
    spatial_maps: bool = True
    color_only_copy: bool = True
    joined_data: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "spatial_maps": self.spatial_maps,
            "color_only_copy": self.color_only_copy,
            "joined_data": self.joined_data,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProfileOptions:
        return cls(
            str(data.get("title") or ""),
            bool(data.get("spatial_maps", True)),
            bool(data.get("color_only_copy", True)),
            bool(data.get("joined_data", True)),
        )


@dataclass(frozen=True)
class ReportProfile:
    datasets: tuple[DatasetSpec, ...]
    comparisons: tuple[ComparisonSpec, ...] = ()
    alignments: tuple[AlignmentSpec, ...] = ()
    options: ProfileOptions = field(default_factory=ProfileOptions)

    def __post_init__(self) -> None:
        ids = [item.id for item in self.datasets]
        if len(ids) != len(set(ids)):
            raise ProfileError("dataset ids must be unique")
        if not ids:
            raise ProfileError("a profile needs at least one dataset")
        known = set(ids)
        comparison_ids = [item.id for item in self.comparisons]
        if len(comparison_ids) != len(set(comparison_ids)):
            raise ProfileError("comparison ids must be unique")
        for comparison in self.comparisons:
            for side in (comparison.a, comparison.b):
                if side not in known:
                    raise ProfileError(
                        f"comparison {comparison.id!r} references unknown dataset {side!r}"
                    )
        seen_samples: set[str] = set()
        used: dict[str, set[str]] = defaultdict(set)
        for alignment in self.alignments:
            if alignment.sample in seen_samples:
                raise ProfileError(f"sample {alignment.sample!r} is aligned twice")
            seen_samples.add(alignment.sample)
            for dataset_id, sheet in alignment.members.items():
                if dataset_id not in known:
                    raise ProfileError(f"alignment references unknown dataset {dataset_id!r}")
                if sheet in used[dataset_id]:
                    raise ProfileError(f"{dataset_id!r} sheet {sheet!r} is aligned to two samples")
                used[dataset_id].add(sheet)

    @property
    def primary(self) -> DatasetSpec:
        return self.datasets[0]

    def dataset(self, dataset_id: str) -> DatasetSpec:
        for item in self.datasets:
            if item.id == dataset_id:
                return item
        raise ProfileError(f"unknown dataset {dataset_id!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "options": self.options.to_dict(),
            "datasets": [item.to_dict() for item in self.datasets],
            "alignments": [item.to_dict() for item in self.alignments],
            "comparisons": [item.to_dict() for item in self.comparisons],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ReportProfile:
        version = data.get("schema_version", PROFILE_SCHEMA_VERSION)
        if version != PROFILE_SCHEMA_VERSION:
            raise ProfileError(f"unsupported profile schema_version {version!r}")
        return cls(
            tuple(DatasetSpec.from_dict(item) for item in data.get("datasets") or ()),
            tuple(ComparisonSpec.from_dict(item) for item in data.get("comparisons") or ()),
            tuple(AlignmentSpec.from_dict(item) for item in data.get("alignments") or ()),
            ProfileOptions.from_dict(data.get("options") or {}),
        )

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"

    def save(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(self.dumps(), encoding="utf-8")
        return destination

    @classmethod
    def load(cls, path: str | Path) -> ReportProfile:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as error:
            raise ProfileError(f"{path}: cannot read profile: {error}") from error
        return cls.from_dict(data)


# ------------------------------------------------------------------ loading + alignment


def load_datasets(profile: ReportProfile) -> dict[str, ParsedDataset]:
    """Parse every dataset as a generic ``label`` source.

    Legacy measurement/prediction files are valid ``label`` files too; parsing them
    that way keeps the value vocabulary free while ``role`` records the intent.
    """
    return {
        spec.id: parse_dataset(
            spec.path,
            "label",
            spec.worksheets or None,
            grid=spec.grid,
            model_column=spec.model_column,
        )
        for spec in profile.datasets
    }


@dataclass(frozen=True)
class AlignmentProposal:
    dataset_id: str
    proposals: tuple[MappingProposal, ...]
    unmatched_primary: tuple[str, ...]
    unmatched_member: tuple[str, ...]


def propose_alignments(
    profile: ReportProfile, datasets: Mapping[str, ParsedDataset]
) -> tuple[AlignmentProposal, ...]:
    """Pair every non-primary dataset's samples with the primary dataset's samples."""
    primary = datasets[profile.primary.id]
    result: list[AlignmentProposal] = []
    for spec in profile.datasets[1:]:
        audit = propose_mappings(primary.sheets, datasets[spec.id].sheets)
        result.append(
            AlignmentProposal(
                spec.id,
                audit.proposals,
                audit.unmatched_measurement_sheets,
                audit.unmatched_prediction_sheets,
            )
        )
    return tuple(result)


def auto_alignments(
    profile: ReportProfile, proposals: Iterable[AlignmentProposal]
) -> tuple[AlignmentSpec, ...]:
    """Alignments that need no confirmation (exact title matches only)."""
    members: dict[str, dict[str, str]] = defaultdict(dict)
    for item in proposals:
        for proposal in item.proposals:
            if not proposal.requires_confirmation:
                members[proposal.measurement_sheet][item.dataset_id] = proposal.prediction_sheet
    primary_id = profile.primary.id
    return tuple(
        AlignmentSpec(sample, {primary_id: sample, **found}) for sample, found in members.items()
    )


def alignments_from_confirmed(
    profile: ReportProfile, confirmed: Iterable[tuple[str, str, str]]
) -> tuple[AlignmentSpec, ...]:
    """Build alignments from ``(dataset_id, primary_sample, member_sheet)`` triples."""
    members: dict[str, dict[str, str]] = defaultdict(dict)
    primary_id = profile.primary.id
    for dataset_id, sample, sheet in confirmed:
        if dataset_id == primary_id:
            continue
        if dataset_id in members[sample]:
            raise ProfileError(f"sample {sample!r} is aligned twice for dataset {dataset_id!r}")
        members[sample][dataset_id] = sheet
    used: dict[str, set[str]] = defaultdict(set)
    for found in members.values():
        for dataset_id, sheet in found.items():
            if sheet in used[dataset_id]:
                raise ProfileError(f"{dataset_id!r} sheet {sheet!r} is aligned to two samples")
            used[dataset_id].add(sheet)
    return tuple(
        AlignmentSpec(sample, {primary_id: sample, **found}) for sample, found in members.items()
    )


# ------------------------------------------------------------------------ joined data


@dataclass(frozen=True)
class MultiRecord:
    sample: str
    row: int
    node: int
    records: Mapping[str, R2RRecord | None]

    def value(self, dataset_id: str) -> str | None:
        record = self.records.get(dataset_id)
        return record.value if record else None


@dataclass(frozen=True)
class SampleData:
    sample: str
    members: Mapping[str, str]
    records: tuple[MultiRecord, ...]
    grid: Grid


def join_aligned(
    profile: ReportProfile,
    datasets: Mapping[str, ParsedDataset],
    alignments: Sequence[AlignmentSpec],
) -> tuple[SampleData, ...]:
    sheets = {
        dataset_id: {sheet.title: sheet for sheet in dataset.sheets}
        for dataset_id, dataset in datasets.items()
    }
    grid = datasets[profile.primary.id].grid
    canonical = {dataset_id: dataset.canonical_map for dataset_id, dataset in datasets.items()}
    samples: list[SampleData] = []
    for alignment in alignments:
        per_dataset: dict[str, dict[tuple[int, int], R2RRecord]] = {}
        for dataset_id, title in alignment.members.items():
            sheet = sheets.get(dataset_id, {}).get(title)
            if sheet is None:
                raise ProfileError(
                    f"alignment {alignment.sample!r}: {dataset_id}:{title} not found"
                )
            spelling = canonical[dataset_id]
            per_dataset[dataset_id] = {
                record.coordinate: replace(
                    record, value=spelling.get(_normalise(record.value), record.value)
                )
                for record in sheet.records
            }
        coordinates = sorted({key for table in per_dataset.values() for key in table})
        records = tuple(
            MultiRecord(
                alignment.sample,
                row,
                node,
                {dataset_id: table.get((row, node)) for dataset_id, table in per_dataset.items()},
            )
            for row, node in coordinates
        )
        samples.append(SampleData(alignment.sample, dict(alignment.members), records, grid))
    return tuple(samples)


# ------------------------------------------------------------------------- evaluation


@dataclass(frozen=True)
class ReferenceStats:
    metrics: Metrics
    agreement: assoc.Agreement
    raw_table: assoc.ContingencyTable
    excluded: int
    pairs: int


@dataclass(frozen=True)
class AssociationStats:
    table: assoc.ContingencyTable
    chi: assoc.ChiSquareResult
    residuals: tuple[tuple[float | None, ...], ...]
    theil: assoc.TheilU
    cells: tuple[assoc.TwoByTwo, ...]
    agreement: assoc.Agreement | None
    excluded: int
    pairs: int


@dataclass(frozen=True)
class ComparisonResult:
    spec: ComparisonSpec
    overall: ReferenceStats | AssociationStats | None
    per_sample: Mapping[str, ReferenceStats | AssociationStats]
    unmapped_a: tuple[str, ...]
    unmapped_b: tuple[str, ...]
    labels_a: tuple[str, ...]
    labels_b: tuple[str, ...]


@dataclass(frozen=True)
class ProfileResult:
    profile: ReportProfile
    datasets: Mapping[str, ParsedDataset]
    samples: tuple[SampleData, ...]
    comparisons: tuple[ComparisonResult, ...]
    blocked: bool
    errors: tuple[str, ...]
    unregistered: Mapping[str, tuple[str, ...]]
    sources: Mapping[str, tuple[SourceMetadata, ...]]
    label_orders: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def labels(self, dataset_id: str) -> tuple[str, ...]:
        """Raw labels of a dataset in scheme order (registered) or first-seen order."""
        return self.label_orders.get(dataset_id) or self.datasets[dataset_id].raw_labels


def _map_value(
    raw: str, mapping: Mapping[str, str], exclude: Iterable[str]
) -> tuple[str | None, bool]:
    """Return ``(category, dropped)``; ``category`` is ``None`` when unmapped."""
    key = _normalise(raw)
    if not key:
        return None, False
    if key in {_normalise(item) for item in exclude}:
        return None, True
    if not mapping:
        return raw, False
    lookup = {
        (WILDCARD if str(item).strip() == WILDCARD else _normalise(item)): value
        for item, value in mapping.items()
    }
    target = lookup.get(key, lookup.get(WILDCARD))
    if target is None:
        return None, False
    if target == EXCLUDE:
        return None, True
    return target, False


def _label_order(
    spec: ComparisonSpec,
    mapping: Mapping[str, str],
    exclude: Iterable[str],
    raw_labels: Sequence[str],
) -> tuple[str, ...]:
    """Row/column order of one side: categories, mapping targets, or raw labels."""
    if spec.kind == "reference":
        return spec.categories
    if mapping:
        targets = [value for value in mapping.values() if value != EXCLUDE]
        return tuple(dict.fromkeys(targets))
    excluded = {_normalise(item) for item in exclude}
    return tuple(label for label in raw_labels if _normalise(label) not in excluded)


def _pairs_for(
    spec: ComparisonSpec, records: Iterable[MultiRecord]
) -> tuple[list[tuple[str, str]], int, set[str], set[str]]:
    pairs: list[tuple[str, str]] = []
    excluded = 0
    unmapped_a: set[str] = set()
    unmapped_b: set[str] = set()
    for record in records:
        raw_a = record.value(spec.a)
        raw_b = record.value(spec.b)
        if raw_a is None or raw_b is None:
            continue
        cat_a, drop_a = _map_value(raw_a, spec.mapping_a, spec.exclude_a)
        cat_b, drop_b = _map_value(raw_b, spec.mapping_b, spec.exclude_b)
        if drop_a or drop_b:
            excluded += 1
            continue
        if spec.kind == "reference":
            # A category outside the declared axis cannot be placed in the matrix; treat it
            # as a coverage gap so the run blocks instead of raising deep inside _metrics.
            if cat_a is not None and cat_a not in spec.categories:
                cat_a = None
            if cat_b is not None and cat_b not in spec.categories:
                cat_b = None
        if cat_a is None:
            unmapped_a.add(raw_a)
        if cat_b is None:
            unmapped_b.add(raw_b)
        if cat_a is None or cat_b is None:
            continue
        pairs.append((cat_a, cat_b))
    return pairs, excluded, unmapped_a, unmapped_b


def _reference_stats(
    spec: ComparisonSpec, pairs: Sequence[tuple[str, str]], excluded: int, raw_pairs
) -> ReferenceStats:
    categories = spec.categories
    metrics = _metrics(categories, pairs, strict_macro=spec.strict_macro)
    table = assoc.ContingencyTable(categories, categories, metrics.matrix)
    return ReferenceStats(
        metrics,
        assoc.agreement(table, spec.positive),
        assoc.contingency(raw_pairs),
        excluded,
        len(pairs),
    )


def _association_stats(
    spec: ComparisonSpec,
    pairs: Sequence[tuple[str, str]],
    excluded: int,
    labels_a: Sequence[str],
    labels_b: Sequence[str],
) -> AssociationStats:
    table = assoc.contingency(pairs, labels_a, labels_b)
    cells = [assoc.collapse(table, cell.labels_a, cell.labels_b, cell.name) for cell in spec.cells]
    holm = assoc.holm([cell.fisher_p for cell in cells])
    cells = [replace(cell, holm_p=adjusted) for cell, adjusted in zip(cells, holm, strict=True)]
    shared = table.labels_a == table.labels_b and len(table.labels_a) >= 2
    return AssociationStats(
        table,
        assoc.chi_square(table),
        assoc.adjusted_residuals(table),
        assoc.theil_u(table),
        tuple(cells),
        assoc.agreement(table, spec.positive) if shared else None,
        excluded,
        len(pairs),
    )


def evaluate_comparison(
    spec: ComparisonSpec,
    samples: Sequence[SampleData],
    datasets: Mapping[str, ParsedDataset],
    orders: Mapping[str, Sequence[str]] | None = None,
) -> ComparisonResult:
    orders = orders or {}
    raw_a = tuple(orders.get(spec.a) or datasets[spec.a].raw_labels)
    raw_b = tuple(orders.get(spec.b) or datasets[spec.b].raw_labels)
    labels_a = _label_order(spec, spec.mapping_a, spec.exclude_a, raw_a)
    labels_b = _label_order(spec, spec.mapping_b, spec.exclude_b, raw_b)
    for cell in spec.cells:
        for side, wanted, available in (
            ("A", cell.labels_a, labels_a),
            ("B", cell.labels_b, labels_b),
        ):
            known = {_normalise(label) for label in available}
            unknown = [label for label in wanted if _normalise(label) not in known]
            if unknown:
                raise ProfileError(
                    f"cell {cell.name!r}: side {side} label(s) not on the axis: "
                    + ", ".join(unknown)
                )
    per_sample: dict[str, ReferenceStats | AssociationStats] = {}
    all_pairs: list[tuple[str, str]] = []
    all_raw: list[tuple[str, str]] = []
    total_excluded = 0
    unmapped_a: set[str] = set()
    unmapped_b: set[str] = set()
    for sample in samples:
        if spec.a not in sample.members or spec.b not in sample.members:
            continue
        pairs, excluded, missing_a, missing_b = _pairs_for(spec, sample.records)
        unmapped_a |= missing_a
        unmapped_b |= missing_b
        raw_pairs = [
            (record.value(spec.a) or "", record.value(spec.b) or "")
            for record in sample.records
            if record.value(spec.a) is not None and record.value(spec.b) is not None
        ]
        all_pairs.extend(pairs)
        all_raw.extend(raw_pairs)
        total_excluded += excluded
        if unmapped_a or unmapped_b:
            continue
        per_sample[sample.sample] = (
            _reference_stats(spec, pairs, excluded, raw_pairs)
            if spec.kind == "reference"
            else _association_stats(spec, pairs, excluded, labels_a, labels_b)
        )
    if unmapped_a or unmapped_b:
        overall = None
        per_sample = {}
    elif spec.kind == "reference":
        overall = _reference_stats(spec, all_pairs, total_excluded, all_raw)
    else:
        overall = _association_stats(spec, all_pairs, total_excluded, labels_a, labels_b)
    return ComparisonResult(
        spec,
        overall,
        per_sample,
        tuple(sorted(unmapped_a)),
        tuple(sorted(unmapped_b)),
        labels_a,
        labels_b,
    )


def label_orders(
    profile: ReportProfile,
    datasets: Mapping[str, ParsedDataset],
    registry: SchemeRegistry | None = None,
) -> dict[str, tuple[str, ...]]:
    """Raw labels per dataset ordered by the declared scheme, then any extras as seen."""
    registry = registry or load_registry()
    orders: dict[str, tuple[str, ...]] = {}
    for spec in profile.datasets:
        observed = datasets[spec.id].raw_labels
        if not spec.scheme:
            orders[spec.id] = observed
            continue
        scheme = registry.scheme(spec.scheme)
        by_key = {_normalise(label): label for label in observed}
        ordered = [
            by_key[_normalise(label)] for label in scheme.labels if _normalise(label) in by_key
        ]
        extras = [label for label in observed if scheme.canonical(label) is None]
        orders[spec.id] = tuple(ordered + extras)
    return orders


def unregistered_labels(
    profile: ReportProfile,
    datasets: Mapping[str, ParsedDataset],
    registry: SchemeRegistry | None = None,
) -> dict[str, tuple[str, ...]]:
    """Raw labels a dataset carries that its declared scheme does not list."""
    registry = registry or load_registry()
    result: dict[str, tuple[str, ...]] = {}
    for spec in profile.datasets:
        if not spec.scheme:
            continue
        scheme = registry.scheme(spec.scheme)
        extra = tuple(
            label for label in datasets[spec.id].raw_labels if scheme.canonical(label) is None
        )
        if extra:
            result[spec.id] = extra
    return result


def evaluate_profile(
    profile: ReportProfile,
    datasets: Mapping[str, ParsedDataset] | None = None,
    *,
    registry: SchemeRegistry | None = None,
) -> ProfileResult:
    """Load (if needed), align, join and evaluate every comparison in ``profile``.

    The result is ``blocked`` when a dataset carries labels outside its declared
    scheme, when a comparison meets a label its mapping does not cover, or when
    no sample could be aligned.  Nothing is inferred silently.
    """
    datasets = dict(datasets) if datasets is not None else load_datasets(profile)
    errors: list[str] = []
    alignments = profile.alignments
    if not alignments:
        alignments = auto_alignments(profile, propose_alignments(profile, datasets))
    if len(profile.datasets) == 1:
        alignments = tuple(
            AlignmentSpec(sheet.title, {profile.primary.id: sheet.title})
            for sheet in datasets[profile.primary.id].sheets
        )
    if not alignments:
        errors.append("no sample could be aligned across the datasets")
    for spec in profile.datasets:
        if datasets[spec.id].grid != profile.primary.grid:
            errors.append(f"dataset {spec.id!r} grid differs from the primary dataset grid")
    samples = join_aligned(profile, datasets, alignments) if not errors else ()
    registry = registry or load_registry()
    unregistered = unregistered_labels(profile, datasets, registry)
    orders = label_orders(profile, datasets, registry)
    for dataset_id, labels in unregistered.items():
        errors.append(f"dataset {dataset_id!r} has labels outside its scheme: {', '.join(labels)}")
    comparisons: list[ComparisonResult] = []
    for spec in profile.comparisons:
        try:
            result = evaluate_comparison(spec, samples, datasets, orders)
        except (DataContractError, ValueError) as error:
            errors.append(f"comparison {spec.id!r}: {error}")
            continue
        if result.unmapped_a:
            errors.append(
                f"comparison {spec.id!r}: side A labels without mapping: "
                + ", ".join(result.unmapped_a)
            )
        if result.unmapped_b:
            errors.append(
                f"comparison {spec.id!r}: side B labels without mapping: "
                + ", ".join(result.unmapped_b)
            )
        comparisons.append(result)
    return ProfileResult(
        profile,
        datasets,
        samples,
        tuple(comparisons),
        bool(errors),
        tuple(errors),
        unregistered,
        {
            dataset_id: tuple(sheet.source for sheet in dataset.sheets)
            for dataset_id, dataset in datasets.items()
        },
        orders,
    )


# ---------------------------------------------------------------- legacy convenience


def legacy_profile(
    measurement_path: str,
    prediction_path: str,
    *,
    registry: SchemeRegistry | None = None,
    measurement_sheets: Sequence[str] = (),
    prediction_sheets: Sequence[str] = (),
) -> ReportProfile:
    """The v0.2–v0.4 report expressed as a profile: 3-class, binary and Expanded Normal."""
    registry = registry or load_registry()
    legacy = registry.scheme("legacy_electrical").labels
    ml = registry.scheme("ml_3class").labels
    three = registry.preset("legacy_to_3class").resolved_rules(legacy)
    binary = registry.preset("legacy_to_binary").resolved_rules(legacy)
    expanded = registry.preset("legacy_to_expanded_normal").resolved_rules(legacy)
    ml_binary = registry.preset("ml_to_binary").resolved_rules(ml)
    identity = {label: label for label in ml}
    return ReportProfile(
        (
            DatasetSpec(
                "measurement",
                measurement_path,
                "electrical_gt",
                "legacy_electrical",
                tuple(measurement_sheets),
                title="Measurement",
            ),
            DatasetSpec(
                "prediction",
                prediction_path,
                "electrical_ml",
                "ml_3class",
                tuple(prediction_sheets),
                title="Prediction",
            ),
        ),
        (
            ComparisonSpec(
                "three_class",
                "reference",
                "measurement",
                "prediction",
                "3-class (Normal / Open / Short)",
                three,
                identity,
                ml,
                preset_a="legacy_to_3class",
            ),
            ComparisonSpec(
                "binary",
                "reference",
                "measurement",
                "prediction",
                "Operational binary (Pass / Fail)",
                binary,
                ml_binary,
                ("Pass", "Fail"),
                positive="Fail",
                strict_macro=False,
                preset_a="legacy_to_binary",
                preset_b="ml_to_binary",
            ),
            ComparisonSpec(
                "expanded_normal",
                "reference",
                "measurement",
                "prediction",
                "Expanded Normal scenario",
                expanded,
                identity,
                ml,
                preset_a="legacy_to_expanded_normal",
            ),
        ),
    )
