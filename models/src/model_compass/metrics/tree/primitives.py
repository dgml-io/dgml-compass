"""Pure comparison primitives: clustering agreement, entropy, cosine, rank order, box overlap,
word edit operations."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from itertools import combinations
from typing import TYPE_CHECKING, Final

from model_compass.metrics.alignment import f1

if TYPE_CHECKING:
    from collections.abc import Sequence

    from model_compass.metrics.tree.flatten import Box

MAX_TAU_CHUNKS: Final[int] = 600
"""Chunks sampled for the O(n^2) Kendall tau; as for ``compare.MAX_PAIR_CHUNKS``, past this
the cost stops being free without changing the estimate much."""


def _c2(n: float) -> float:
    return n * (n - 1) / 2.0


def adjusted_rand(la: Sequence[object], lb: Sequence[object]) -> float | None:
    """Adjusted Rand Index between two labellings of the same items."""
    n = len(la)
    if n < 2:
        return None
    cont: Counter[tuple[object, object]] = Counter(zip(la, lb, strict=True))
    ca: Counter[object] = Counter(la)
    cb: Counter[object] = Counter(lb)
    sum_ij = sum(_c2(v) for v in cont.values())
    sum_a = sum(_c2(v) for v in ca.values())
    sum_b = sum(_c2(v) for v in cb.values())
    total = _c2(n)
    if total == 0:
        return None
    expected = sum_a * sum_b / total
    maximum = (sum_a + sum_b) / 2.0
    if maximum == expected:
        # Both labellings degenerate (one cluster, or all singletons): perfect but meaningless
        # agreement. The guard metrics say which case it is.
        return 1.0
    return (sum_ij - expected) / (maximum - expected)


def bcubed(
    reference: Sequence[object], other: Sequence[object]
) -> tuple[float, float, float] | None:
    """BCubed precision / recall / F1 with ``reference`` as the reference labelling.

    Low precision: ``other`` merged what the reference kept apart. Low recall: ``other`` split
    what the reference had together. From the contingency table, so O(cells).
    """
    n = len(reference)
    if n == 0:
        return None
    cont: Counter[tuple[object, object]] = Counter(zip(reference, other, strict=True))
    ca: Counter[object] = Counter(reference)
    cb: Counter[object] = Counter(other)
    precision = sum(v * v / cb[j] for (_i, j), v in cont.items()) / n
    recall = sum(v * v / ca[i] for (i, _j), v in cont.items()) / n
    return precision, recall, f1(precision, recall)


def entropy(counts: Counter[object]) -> float:
    total = sum(counts.values())
    if total <= 0:
        return 0.0
    return -sum((v / total) * math.log2(v / total) for v in counts.values() if v)


def cosine(a: Counter[object], b: Counter[object]) -> float | None:
    if not a or not b:
        return None
    dot = sum(v * b[k] for k, v in a.items() if k in b)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else None


def kendall_tau(seq: Sequence[int]) -> float | None:
    """Kendall tau of a sequence against its sorted order, on the first ``MAX_TAU_CHUNKS``."""
    if len(seq) < 2:
        return None
    use = seq[:MAX_TAU_CHUNKS]
    concordant = discordant = 0
    for i, j in combinations(range(len(use)), 2):
        d = use[j] - use[i]
        if d > 0:
            concordant += 1
        elif d < 0:
            discordant += 1
    total = concordant + discordant
    return (concordant - discordant) / total if total else None


def box_iou(sa: Sequence[Box], sb: Sequence[Box]) -> float | None:
    """IoU of two multi-box ``origin`` sets, per page, each side as the exact union of its
    boxes (coordinate compression, so overlapping boxes on one side are not double-counted)."""
    if not sa or not sb:
        return None
    by_page: dict[int, tuple[list[tuple[int, int, int, int]], list[tuple[int, int, int, int]]]]
    by_page = defaultdict(lambda: ([], []))
    for p, x1, y1, x2, y2 in sa:
        if x2 > x1 and y2 > y1:
            by_page[p][0].append((x1, y1, x2, y2))
    for p, x1, y1, x2, y2 in sb:
        if x2 > x1 and y2 > y1:
            by_page[p][1].append((x1, y1, x2, y2))
    area_a = area_b = inter = 0.0
    for rects_a, rects_b in by_page.values():
        xs = sorted({v for r in rects_a + rects_b for v in (r[0], r[2])})
        ys = sorted({v for r in rects_a + rects_b for v in (r[1], r[3])})
        for i in range(len(xs) - 1):
            x1, x2 = xs[i], xs[i + 1]
            for j in range(len(ys) - 1):
                y1, y2 = ys[j], ys[j + 1]
                cell = (x2 - x1) * (y2 - y1)
                in_a = any(r[0] <= x1 and r[2] >= x2 and r[1] <= y1 and r[3] >= y2 for r in rects_a)
                in_b = any(r[0] <= x1 and r[2] >= x2 and r[1] <= y1 and r[3] >= y2 for r in rects_b)
                area_a += cell if in_a else 0.0
                area_b += cell if in_b else 0.0
                inter += cell if (in_a and in_b) else 0.0
    union = area_a + area_b - inter
    return inter / union if union > 0 else None


def common_prefix(x: Sequence[int], y: Sequence[int]) -> int:
    n = 0
    for p, q in zip(x, y, strict=False):
        if p != q:
            break
        n += 1
    return n


def text_edit_ops(
    n_gold: int, n_pred: int, pairs: Sequence[tuple[int, int]]
) -> tuple[int, int, int]:
    """Word ``(insertions, deletions, substitutions)`` turning the predicted stream into gold.

    Read off the gaps between consecutive aligned pairs, as ``SequenceMatcher`` opcodes would
    be: a gap of ``g`` gold and ``p`` predicted tokens is ``min(g, p)`` substitutions plus the
    remainder as insertions (gold side) or deletions (predicted side). The alignment is
    ``SequenceMatcher``'s, not a minimal Levenshtein one, so this is an upper bound that is
    tight on the near-identical streams the gate admits.
    """
    ins = dele = sub = 0
    last_g = last_p = -1
    for ig, ip in (*pairs, (n_gold, n_pred)):
        g = ig - last_g - 1
        p = ip - last_p - 1
        s = min(g, p)
        sub += s
        ins += g - s
        dele += p - s
        last_g, last_p = ig, ip
    return ins, dele, sub
