"""Paired inference for ``compare`` (docs/METRICS.md §5).

The resampling unit is the docset, never the document: documents within a docset share a
template (design effect 2.7-5.1 on this corpus), so resampling documents understates every
interval. Too little data is refused, never returned as a number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import numpy as np
from scipy import stats as _scipy_stats

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

MIN_DOCSETS: Final[int] = 2
"""Resampling one docset returns that docset, every time."""

DEFAULT_CONFIDENCE: Final[float] = 0.95
DEFAULT_RESAMPLES: Final[int] = 10_000


@dataclass(frozen=True)
class Interval:
    point: float
    low: float
    high: float
    confidence: float = DEFAULT_CONFIDENCE
    n: int = 0


@dataclass(frozen=True)
class ArmComparison:
    """A paired comparison of two arms over the docsets both scored."""

    mean_delta: float
    ci: Interval
    p_value: float
    n_pairs: int
    n_a_only: int = 0
    n_b_only: int = 0
    wins: int = 0
    losses: int = 0
    ties: int = 0


def bootstrap_ci(
    values: Sequence[float],
    *,
    statistic: Callable[[np.ndarray], float] | None = None,
    confidence: float = DEFAULT_CONFIDENCE,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = 0,
) -> Interval | None:
    """Percentile bootstrap over docsets (one value per docset). Seeded: a replay must
    reproduce the interval."""
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    if resamples < 1:
        raise ValueError(f"resamples must be positive, got {resamples}")
    array = np.asarray([v for v in values if math.isfinite(v)], dtype=float)
    if array.size < MIN_DOCSETS:
        return None
    func = statistic or (lambda sample: float(np.mean(sample)))
    draws = np.random.default_rng(seed).integers(0, array.size, size=(resamples, array.size))
    samples = np.array([func(array[row]) for row in draws], dtype=float)
    samples = samples[np.isfinite(samples)]
    if samples.size == 0:
        return None
    tail = (1.0 - confidence) / 2.0
    low, high = np.quantile(samples, [tail, 1.0 - tail])
    return Interval(float(func(array)), float(low), float(high), confidence, int(array.size))


def compare_arms(
    a: Mapping[str, float],
    b: Mapping[str, float],
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = 0,
) -> ArmComparison:
    """``b - a`` paired on the shared docsets: bootstrap CI of the mean delta, Wilcoxon
    (zsplit) p-value, win/loss/tie counts. Raises below two shared docsets -- an unpaired
    comparison over different docsets measures the corpus, not the arms."""
    shared = sorted(set(a) & set(b))
    if len(shared) < MIN_DOCSETS:
        raise ValueError(
            f"paired comparison needs at least {MIN_DOCSETS} shared docsets, got {len(shared)} "
            f"(arm A has {len(a)}, arm B has {len(b)})"
        )
    finite = [d for d in (b[key] - a[key] for key in shared) if math.isfinite(d)]
    if len(finite) < MIN_DOCSETS:
        raise ValueError(f"only {len(finite)} shared docsets have finite values on both arms")
    ci = bootstrap_ci(finite, confidence=confidence, resamples=resamples, seed=seed)
    assert ci is not None  # guarded by the length check
    # Wilcoxon needs a non-zero difference to rank; all ties is p = 1 by definition.
    p_value = (
        float(_scipy_stats.wilcoxon(finite, zero_method="zsplit").pvalue)
        if any(d != 0.0 for d in finite)
        else 1.0
    )
    return ArmComparison(
        mean_delta=float(np.mean(finite)),
        ci=ci,
        p_value=p_value,
        n_pairs=len(finite),
        n_a_only=len(set(a) - set(b)),
        n_b_only=len(set(b) - set(a)),
        wins=sum(1 for d in finite if d > 0),
        losses=sum(1 for d in finite if d < 0),
        ties=sum(1 for d in finite if d == 0),
    )
