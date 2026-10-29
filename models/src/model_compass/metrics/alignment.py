"""Matching kernels.

- Greedy overlap (docs/METRICS.md §1): column maxima for precision, row maxima for recall over a
  per-pair token-overlap matrix. One prediction may claim credit against several gold values.
  The headline overlap scores use this scheme (DECISIONS 0006).
- Non-crossing alignment: same kernel, matches may not cross.
- Optimal one-to-one assignment: only for complex instances, which have no order.
"""

from __future__ import annotations

import difflib
import functools
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


@functools.lru_cache(maxsize=2_000_000)
def pair_token_overlap(gold: str, pred: str) -> tuple[float, float]:
    """(precision, recall) of one prediction against one gold value: the longest common
    contiguous token run over each side's token count. Cached: the tag choice asks for the
    same pair many times."""
    gold_tokens, pred_tokens = gold.split(), pred.split()
    if not gold_tokens or not pred_tokens or not set(gold_tokens).intersection(pred_tokens):
        return 0.0, 0.0
    matcher = difflib.SequenceMatcher(None, gold_tokens, pred_tokens)
    _, _, longest = matcher.find_longest_match(0, len(gold_tokens), 0, len(pred_tokens))
    if not longest:
        return 0.0, 0.0
    return longest / len(pred_tokens), longest / len(gold_tokens)


def greedy_overlap(golds: Sequence[str], preds: Sequence[str]) -> tuple[float, float]:
    """Callers pass sorted sequences: set order varies with the hash seed, and summation order
    would otherwise drift by ~1 ULP between runs."""
    precision = [[0.0] * len(preds) for _ in golds]
    recall = [[0.0] * len(preds) for _ in golds]
    for j, pred in enumerate(preds):
        for i, gold in enumerate(golds):
            p, r = pair_token_overlap(gold, pred)
            if p or r:
                precision[i][j] = p
                recall[i][j] = r
    return (
        sum(max(column) for column in zip(*precision, strict=True)),
        sum(max(row) for row in recall),
    )


def optimal_pairs(scores: Sequence[Sequence[float]]) -> list[tuple[int, int]]:
    """Maximum-weight one-to-one matching (Hungarian); zero-score pairs are dropped."""
    if not scores or not scores[0]:
        return []
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    matrix = np.asarray(scores, dtype=float)
    rows, columns = linear_sum_assignment(-matrix)
    return [(int(i), int(j)) for i, j in zip(rows, columns, strict=True) if matrix[i, j] > 0.0]


def ordered_bases(values: frozenset[str]) -> tuple[str, ...]:
    """The value sequence the ``#position`` suffixes encode, suffixes stripped; unpositioned
    values (the sentinel) last."""

    def key(value: str) -> tuple[int, int, str]:
        head, _, tail = value.rpartition("#")
        return (0, int(tail), head) if tail.isdigit() else (1, 0, value)

    out: list[str] = []
    for value in sorted(values, key=key):
        head, _, tail = value.rpartition("#")
        out.append(head if tail.isdigit() else value)
    return tuple(out)


@functools.lru_cache(maxsize=100_000)
def aligned_em(gold: frozenset[str], pred: frozenset[str]) -> int:
    """Longest common subsequence of the two ordered base sequences."""
    left, right = ordered_bases(gold), ordered_bases(pred)
    if not left or not right:
        return 0
    previous = [0] * (len(right) + 1)
    for item in left:
        current = [0]
        for index, other in enumerate(right, 1):
            current.append(
                previous[index - 1] + 1
                if item == other
                else max(previous[index], current[index - 1])
            )
        previous = current
    return previous[-1]


@functools.lru_cache(maxsize=100_000)
def aligned_overlap(gold: frozenset[str], pred: frozenset[str]) -> tuple[float, float]:
    """Maximum-weight non-crossing alignment; each pair contributes its token overlap."""
    if not gold and (not pred or pred == frozenset({""})):
        return 1.0, 1.0
    if not gold or not pred or pred == frozenset({""}):
        return 0.0, 0.0
    left, right = ordered_bases(gold), ordered_bases(pred)
    zero = (0.0, 0.0, 0.0)
    previous: list[tuple[float, float, float]] = [zero] * (len(right) + 1)
    for item in left:
        current: list[tuple[float, float, float]] = [zero]
        for index, other in enumerate(right, 1):
            precision, recall = pair_token_overlap(item, other)
            take = (
                previous[index - 1][0] + precision + recall,
                previous[index - 1][1] + precision,
                previous[index - 1][2] + recall,
            )
            current.append(max(previous[index], current[index - 1], take, key=lambda t: t[0]))
        previous = current
    return previous[-1][1], previous[-1][2]
