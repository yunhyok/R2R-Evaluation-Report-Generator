"""Symmetric association statistics for two nominal label sources.

Used when neither side is ground truth for the other (for example electrical
``E-Invalid`` against an optical/VLM ``BAD``), where accuracy-type metrics would
depend on an arbitrary choice of "truth" side.

References
----------
- Agresti, A. (2013). *Categorical Data Analysis*, 3rd ed. Wiley.  Chi-square test of
  independence, odds ratio, relative risk, Fisher's exact test.
- Bergsma, W. (2013). A bias-correction for Cramér's V and Tschuprow's T.
  *Journal of the Korean Statistical Society*, 42(3), 323–328.
- Haberman, S. J. (1973). The analysis of residuals in cross-classified tables.
  *Biometrics*, 29(1), 205–220.  Adjusted standardized residuals.
- Theil, H. (1970). On the estimation of relationships involving qualitative
  variables. *American Journal of Sociology*, 76(1), 103–154.  Uncertainty coefficient.
- Cohen, J. (1960). A coefficient of agreement for nominal scales.
  *Educational and Psychological Measurement*, 20(1), 37–46.
- Cicchetti, D. V., & Feinstein, A. R. (1990). High agreement but low kappa: II.
  Resolving the paradoxes. *Journal of Clinical Epidemiology*, 43(6), 551–558.
  Positive / negative agreement.
- Woolf, B. (1955). On estimating the relation between blood group and disease.
  *Annals of Human Genetics*, 19(4), 251–253.  Log odds-ratio confidence interval.
- Haldane, J. B. S. (1956); Anscombe, F. J. (1956).  0.5 continuity correction for
  empty 2 x 2 cells.
- Holm, S. (1979). A simple sequentially rejective multiple test procedure.
  *Scandinavian Journal of Statistics*, 6(2), 65–70.
- Gorodkin, J. (2004). Comparing two K-category assignments by a K-category
  correlation coefficient. *Computational Biology and Chemistry*, 28(5–6), 367–374.
  Multi-class Matthews correlation coefficient.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np
from scipy import stats

Z95 = 1.959963984540054


def _key(label: object) -> str:
    """Case/spacing/punctuation-insensitive label key (same rule as :mod:`core`)."""
    return re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKC", str(label)).casefold())


COCHRAN_MIN_EXPECTED = 5.0
COCHRAN_MAX_LOW_FRACTION = 0.2


@dataclass(frozen=True)
class ContingencyTable:
    labels_a: tuple[str, ...]
    labels_b: tuple[str, ...]
    counts: tuple[tuple[int, ...], ...]

    @property
    def total(self) -> int:
        return int(sum(sum(row) for row in self.counts))

    @property
    def row_totals(self) -> tuple[int, ...]:
        return tuple(int(sum(row)) for row in self.counts)

    @property
    def column_totals(self) -> tuple[int, ...]:
        return tuple(int(sum(row[j] for row in self.counts)) for j in range(len(self.labels_b)))

    def as_array(self) -> np.ndarray:
        return np.asarray(self.counts, dtype=float)

    def cell(self, label_a: str, label_b: str) -> int:
        return self.counts[self.labels_a.index(label_a)][self.labels_b.index(label_b)]


def contingency(
    pairs: Iterable[tuple[str, str]],
    labels_a: Sequence[str] | None = None,
    labels_b: Sequence[str] | None = None,
) -> ContingencyTable:
    """Cross-tabulate ``(a, b)`` label pairs.  Unlisted labels are appended in first-seen order."""
    pairs = list(pairs)
    a_order = list(labels_a or ())
    b_order = list(labels_b or ())
    for a, b in pairs:
        if a not in a_order:
            a_order.append(a)
        if b not in b_order:
            b_order.append(b)
    counter = Counter(pairs)
    counts = tuple(tuple(counter[(a, b)] for b in b_order) for a in a_order)
    return ContingencyTable(tuple(a_order), tuple(b_order), counts)


@dataclass(frozen=True)
class ChiSquareResult:
    statistic: float | None
    dof: int
    p_value: float | None
    expected: tuple[tuple[float, ...], ...]
    min_expected: float | None
    low_expected_fraction: float | None
    cochran_warning: bool
    cramers_v: float | None
    cramers_v_corrected: float | None


def chi_square(table: ContingencyTable) -> ChiSquareResult:
    """Pearson chi-square test of independence with Cramér's V (raw and Bergsma-corrected).

    Rows/columns whose margin is zero are dropped before testing, because they carry
    no information and would make the expected table singular.  Values are ``None``
    when the reduced table has fewer than two rows or columns.
    """
    observed = table.as_array()
    keep_rows = observed.sum(axis=1) > 0
    keep_cols = observed.sum(axis=0) > 0
    reduced = observed[keep_rows][:, keep_cols]
    n = float(reduced.sum())
    r, k = reduced.shape
    if r < 2 or k < 2 or n <= 0:
        return ChiSquareResult(None, 0, None, (), None, None, False, None, None)
    statistic, p_value, dof, expected = stats.chi2_contingency(reduced, correction=False)
    expected_full = np.zeros_like(observed)
    expected_full[np.ix_(keep_rows, keep_cols)] = expected
    min_expected = float(expected.min())
    low_fraction = float((expected < COCHRAN_MIN_EXPECTED).mean())
    phi2 = statistic / n
    v = math.sqrt(phi2 / min(k - 1, r - 1))
    # Bergsma (2013) bias correction.
    phi2_corrected = max(0.0, phi2 - (k - 1) * (r - 1) / (n - 1)) if n > 1 else 0.0
    k_corrected = k - (k - 1) ** 2 / (n - 1) if n > 1 else k
    r_corrected = r - (r - 1) ** 2 / (n - 1) if n > 1 else r
    denominator = min(k_corrected - 1, r_corrected - 1)
    v_corrected = math.sqrt(phi2_corrected / denominator) if denominator > 0 else None
    return ChiSquareResult(
        float(statistic),
        int(dof),
        float(p_value),
        tuple(tuple(float(x) for x in row) for row in expected_full),
        min_expected,
        low_fraction,
        low_fraction > COCHRAN_MAX_LOW_FRACTION or min_expected < 1.0,
        float(v),
        v_corrected,
    )


def adjusted_residuals(table: ContingencyTable) -> tuple[tuple[float | None, ...], ...]:
    """Haberman (1973) adjusted standardized residuals, ~N(0, 1) under independence."""
    observed = table.as_array()
    n = observed.sum()
    if n <= 0:
        return tuple(tuple(None for _ in row) for row in table.counts)
    row_p = observed.sum(axis=1) / n
    col_p = observed.sum(axis=0) / n
    expected = np.outer(row_p, col_p) * n
    result: list[tuple[float | None, ...]] = []
    for i in range(observed.shape[0]):
        row: list[float | None] = []
        for j in range(observed.shape[1]):
            variance = expected[i, j] * (1 - row_p[i]) * (1 - col_p[j])
            if variance <= 0:
                row.append(None)
            else:
                row.append(float((observed[i, j] - expected[i, j]) / math.sqrt(variance)))
        result.append(tuple(row))
    return tuple(result)


def _entropy(probabilities: np.ndarray) -> float:
    p = probabilities[probabilities > 0]
    return float(-(p * np.log(p)).sum())


@dataclass(frozen=True)
class TheilU:
    u_b_given_a: float | None
    """Fraction of B's uncertainty explained by A."""

    u_a_given_b: float | None
    """Fraction of A's uncertainty explained by B."""


def theil_u(table: ContingencyTable) -> TheilU:
    observed = table.as_array()
    n = observed.sum()
    if n <= 0:
        return TheilU(None, None)
    joint = observed / n
    p_a = joint.sum(axis=1)
    p_b = joint.sum(axis=0)
    h_a = _entropy(p_a)
    h_b = _entropy(p_b)
    h_ab = _entropy(joint.ravel())
    mutual = h_a + h_b - h_ab
    return TheilU(
        None if h_b <= 0 else float(mutual / h_b),
        None if h_a <= 0 else float(mutual / h_a),
    )


@dataclass(frozen=True)
class TwoByTwo:
    """``a`` = both conditions, ``b`` = A only, ``c`` = B only, ``d`` = neither."""

    name: str
    a: int
    b: int
    c: int
    d: int
    odds_ratio: float | None
    odds_ratio_ci95: tuple[float, float] | None
    relative_risk: float | None
    phi: float | None
    yule_q: float | None
    fisher_p: float | None
    corrected: bool
    holm_p: float | None = None

    @property
    def total(self) -> int:
        return self.a + self.b + self.c + self.d


def two_by_two(name: str, a: int, b: int, c: int, d: int) -> TwoByTwo:
    """Association measures for one collapsed 2 x 2 cell of interest.

    Odds ratio and its Woolf CI use the Haldane–Anscombe 0.5 correction when any
    cell is empty (``corrected=True``).  Relative risk is the risk of B given A over
    the risk of B given not-A.  Fisher's exact test is two-sided.
    """
    total = a + b + c + d
    if total == 0:
        return TwoByTwo(name, a, b, c, d, None, None, None, None, None, None, False)
    corrected = 0 in (a, b, c, d)
    aa, bb, cc, dd = (x + 0.5 for x in (a, b, c, d)) if corrected else (a, b, c, d)
    odds_ratio = (aa * dd) / (bb * cc)
    se = math.sqrt(1 / aa + 1 / bb + 1 / cc + 1 / dd)
    ci = (math.exp(math.log(odds_ratio) - Z95 * se), math.exp(math.log(odds_ratio) + Z95 * se))
    risk_a = a / (a + b) if (a + b) else None
    risk_not_a = c / (c + d) if (c + d) else None
    relative_risk = (
        risk_a / risk_not_a if risk_a is not None and risk_not_a not in (None, 0) else None
    )
    phi_denominator = (a + b) * (c + d) * (a + c) * (b + d)
    phi = (a * d - b * c) / math.sqrt(phi_denominator) if phi_denominator > 0 else None
    yule_denominator = a * d + b * c
    yule_q = (a * d - b * c) / yule_denominator if yule_denominator > 0 else None
    _, fisher_p = stats.fisher_exact([[a, b], [c, d]], alternative="two-sided")
    return TwoByTwo(
        name,
        a,
        b,
        c,
        d,
        odds_ratio,
        ci,
        relative_risk,
        phi,
        yule_q,
        float(fisher_p),
        corrected,
    )


def collapse(
    table: ContingencyTable, labels_a: Iterable[str], labels_b: Iterable[str], name: str
) -> TwoByTwo:
    """Collapse ``table`` into ``A in labels_a`` x ``B in labels_b``."""
    set_a = {_key(label) for label in labels_a}
    set_b = {_key(label) for label in labels_b}
    a = b = c = d = 0
    for i, label_a in enumerate(table.labels_a):
        for j, label_b in enumerate(table.labels_b):
            count = table.counts[i][j]
            in_a = _key(label_a) in set_a
            in_b = _key(label_b) in set_b
            if in_a and in_b:
                a += count
            elif in_a:
                b += count
            elif in_b:
                c += count
            else:
                d += count
    return two_by_two(name, a, b, c, d)


def holm(p_values: Sequence[float | None]) -> tuple[float | None, ...]:
    """Holm (1979) step-down adjusted p-values; ``None`` entries are passed through."""
    indexed = [(p, i) for i, p in enumerate(p_values) if p is not None]
    m = len(indexed)
    adjusted: list[float | None] = [None] * len(p_values)
    running = 0.0
    for rank, (p, i) in enumerate(sorted(indexed)):
        running = max(running, min(1.0, (m - rank) * p))
        adjusted[i] = running
    return tuple(adjusted)


@dataclass(frozen=True)
class Agreement:
    kappa: float | None
    observed_agreement: float | None
    expected_agreement: float | None
    positive_agreement: float | None
    """Cicchetti–Feinstein PA for the positive class (2-class tables only)."""

    negative_agreement: float | None
    mcc: float | None
    """Matthews correlation coefficient (Gorodkin multi-class form)."""

    majority_baseline: float | None
    """Accuracy of always predicting the most frequent A-side label."""


def agreement(table: ContingencyTable, positive: str | None = None) -> Agreement:
    """Chance-corrected agreement for a square table sharing one label set.

    ``labels_a`` and ``labels_b`` must be equal as ordered tuples.  ``positive``
    selects the class for PA/NA in a two-label table (defaults to the second label,
    matching the ``(Pass, Fail)`` convention where ``Fail`` is positive).
    """
    if table.labels_a != table.labels_b:
        raise ValueError("agreement requires both sides to use the same ordered label set")
    observed = table.as_array()
    n = observed.sum()
    if n <= 0:
        return Agreement(None, None, None, None, None, None, None)
    diagonal = float(np.trace(observed))
    po = diagonal / n
    row_totals = observed.sum(axis=1)
    col_totals = observed.sum(axis=0)
    pe = float((row_totals * col_totals).sum() / (n * n))
    kappa = None if pe >= 1 else (po - pe) / (1 - pe)
    # Gorodkin (2004) multi-class MCC.
    numerator = diagonal * n - float((row_totals * col_totals).sum())
    denominator = math.sqrt(
        (n * n - float((col_totals**2).sum())) * (n * n - float((row_totals**2).sum()))
    )
    mcc = numerator / denominator if denominator > 0 else None
    pa = na = None
    if len(table.labels_a) == 2:
        pos = table.labels_a.index(positive) if positive in table.labels_a else 1
        neg = 1 - pos
        tp = observed[pos, pos]
        tn = observed[neg, neg]
        pa_denominator = 2 * tp + observed[pos, neg] + observed[neg, pos]
        na_denominator = 2 * tn + observed[pos, neg] + observed[neg, pos]
        pa = float(2 * tp / pa_denominator) if pa_denominator > 0 else None
        na = float(2 * tn / na_denominator) if na_denominator > 0 else None
    return Agreement(
        None if kappa is None else float(kappa),
        float(po),
        pe,
        pa,
        na,
        None if mcc is None else float(mcc),
        float(row_totals.max() / n),
    )
