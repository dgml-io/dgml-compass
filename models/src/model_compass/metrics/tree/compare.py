"""Gold-anchored tree comparison: segmentation, labelling, shape, grounding, edits.

Definitions: docs/METRICS.md §4.

Side A is the corpus's gold DGML for a document, side B the prediction, so directional
measures read as "what the prediction did to gold": low ``bcubed_precision`` = merged what
gold kept apart, low ``bcubed_recall`` = split what gold had together.

Both documents are flattened to a reading-order token stream whose tokens carry their chunk
(the text-bearing element: tag, depth, ancestor path, ``dg:origin`` boxes). One
``SequenceMatcher`` alignment of the two streams feeds every metric. ``alignable_fraction``
gates the rest: a pair below :data:`ALIGNABLE_MIN` is counted, not averaged.

A token's tag is the nearest enclosing *semantic* element, so a labeler that wraps text in
``dg:chunk`` is not read as a vocabulary collapse; ``direct_label_rate_pred`` reports the
wrapping itself. Scores are 0-1, not 0-100 (ARI and tau reach -1); counts, ratios and
entropies are raw. ``path_bag_cosine`` and ``chunk_jaccard`` are not emitted (see
docs/DECISIONS.md).
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import TYPE_CHECKING, Final

from model_compass.metrics.alignment import f1
from model_compass.metrics.tree.flatten import FlatDoc, align_chunks, align_tokens, flatten
from model_compass.metrics.tree.primitives import (
    adjusted_rand,
    bcubed,
    box_iou,
    common_prefix,
    cosine,
    entropy,
    kendall_tau,
    text_edit_ops,
)
from model_compass.metrics.tree.ted import MAX_TED_NODES, TED_METRICS, tree_edit_metrics

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from xml.etree import ElementTree

ALIGNABLE_MIN: Final[float] = 0.5
"""Below this ``alignable_fraction`` a document pair contributes to no mean. Half the tokens
unmatched means the two sides transcribed different documents, or one of them lost half the
page; a tree agreement computed over the other half says nothing about the tree."""

MAX_PAIR_CHUNKS: Final[int] = 400
"""Chunks used by the O(n^2) pairwise comparisons (``group_agreement``, ``lca_*``). 400 is
~80k pairs, where the cost stops being free without changing the estimate much."""

PATH_SUFFIX: Final[int] = 2
"""Tags of the root-to-chunk path kept by ``path_suffix_cosine`` -- the pq-gram idea: compare
local tree context, because the full path is renamed wholesale when the root is."""

COMPARABILITY_METRICS: Final[tuple[str, ...]] = ("alignable_fraction", "token_len_ratio")
SEGMENTATION_METRICS: Final[tuple[str, ...]] = (
    "seg_ari",
    "coseg_agreement",
    "boundary_f1",
    "chunk_jaccard_bag",
)
LABELING_METRICS: Final[tuple[str, ...]] = (
    "label_ari",
    "bcubed_precision",
    "bcubed_recall",
    "bcubed_f1",
    "tag_exact_agreement",
    "tag_vocab_jaccard",
    "direct_label_rate_gold",
    "direct_label_rate_pred",
)
SHAPE_METRICS: Final[tuple[str, ...]] = (
    "depth_match",
    "group_agreement",
    "lca_depth_match",
    "lca_depth_mae",
    "path_suffix_cosine",
    "struct_path_cosine",
    "leaf_order_tau",
)
TREE_GROUNDING_METRICS: Final[tuple[str, ...]] = (
    "origin_iou_mean",
    "origin_iou_gt50",
    "origin_page_match",
    "grounded_rate_gold",
    "grounded_rate_pred",
)
GUARD_METRICS: Final[tuple[str, ...]] = (
    "chunk_count_ratio",
    "tag_count_ratio",
    "element_count_ratio",
    "mean_chunk_tokens_gold",
    "mean_chunk_tokens_pred",
    "tag_entropy_gold",
    "tag_entropy_pred",
)
TEXT_EDIT_METRICS: Final[tuple[str, ...]] = ("text_ins", "text_del", "text_sub", "text_wer")
EDIT_METRICS: Final[tuple[str, ...]] = (*TED_METRICS, *TEXT_EDIT_METRICS)
"""Edit distances, prediction -> gold: TEDS and tree operations (`metrics.tree.ted`),
word operations over the reading-order streams (:func:`text_edit_ops`). docs/METRICS.md §4."""

LEVEL_DEPTHS: Final[tuple[int, ...]] = (1, 2, 3)
"""Element depths (root = 0, ``dg:`` frames counted) compared by :func:`level_metrics`. The
metric names carry the depth, so changing this tuple changes the record schema."""

LEVEL_MATCH_MIN: Final[float] = 0.5
"""Token Dice at or above which a gold and a predicted level segment count as the same unit."""

_LEVEL_STEMS: Final[tuple[str, ...]] = (
    "level_count_ratio",
    "level_precision",
    "level_recall",
    "level_f1",
    "level_text_dice",
    "level_exact",
)
LEVEL_METRICS: Final[tuple[str, ...]] = tuple(
    f"{stem}_d{depth}" for depth in LEVEL_DEPTHS for stem in _LEVEL_STEMS
)
"""Per-depth comparison of the concatenated text under each element at that depth
(docs/METRICS.md §4)."""

ALL_TREE_METRICS: Final[tuple[str, ...]] = (
    *COMPARABILITY_METRICS,
    *SEGMENTATION_METRICS,
    *LABELING_METRICS,
    *SHAPE_METRICS,
    *TREE_GROUNDING_METRICS,
    *GUARD_METRICS,
    *EDIT_METRICS,
    *LEVEL_METRICS,
)
"""Every metric the tree family can emit."""


def _direct_rate(doc: FlatDoc) -> float | None:
    """Token-weighted share of text sitting directly in a semantic element."""
    total = sum(c.n_tokens for c in doc.chunks)
    if not total:
        return None
    return sum(c.n_tokens for c in doc.chunks if not c.tag.startswith("dg:")) / total


def _segments(doc: FlatDoc, depth: int) -> list[int | None]:
    """Per token, the index of its ancestor element at ``depth`` (``None`` above that depth)."""
    return [
        doc.chunks[c].anc[depth] if len(doc.chunks[c].anc) > depth else None for c in doc.tok_chunk
    ]


def level_metrics(
    gold: FlatDoc, pred: FlatDoc, pairs: Sequence[tuple[int, int]], depth: int
) -> dict[str, float]:
    """Compare the elements at ``depth`` by the text they cover, concatenated in reading order.

    A *segment* is one element at that depth together with all its descendants' text. Gold and
    predicted segments are scored by token Dice over the shared alignment
    (``2 * aligned tokens in both / (len_gold + len_pred)``) and matched one-to-one, greedily by
    Dice. ``level_precision`` / ``level_recall`` / ``level_f1`` count matches at or above
    :data:`LEVEL_MATCH_MIN`; ``level_text_dice`` is the mean matched Dice over gold segments
    (unmatched = 0); ``level_exact`` the share of gold segments whose match has identical text.
    Empty when gold has no text at that depth.
    """
    seg_g = _segments(gold, depth)
    seg_p = _segments(pred, depth)
    text_g: dict[int, list[str]] = defaultdict(list)
    text_p: dict[int, list[str]] = defaultdict(list)
    for tok, seg in zip(gold.tokens, seg_g, strict=True):
        if seg is not None:
            text_g[seg].append(tok)
    for tok, seg in zip(pred.tokens, seg_p, strict=True):
        if seg is not None:
            text_p[seg].append(tok)
    if not text_g:
        return {}
    shared: Counter[tuple[int, int]] = Counter()
    for ig, ip in pairs:
        a, b = seg_g[ig], seg_p[ip]
        if a is not None and b is not None:
            shared[(a, b)] += 1
    scored = sorted(
        ((2 * n / (len(text_g[a]) + len(text_p[b])), a, b) for (a, b), n in shared.items()),
        key=lambda t: (-t[0], t[1], t[2]),
    )
    used_g: set[int] = set()
    used_p: set[int] = set()
    matched: list[tuple[float, int, int]] = []
    for dice, a, b in scored:
        if a in used_g or b in used_p:
            continue
        used_g.add(a)
        used_p.add(b)
        matched.append((dice, a, b))
    n_g, n_p = len(text_g), len(text_p)
    hits = sum(1 for dice, _a, _b in matched if dice >= LEVEL_MATCH_MIN)
    precision = hits / n_p if n_p else None
    recall = hits / n_g
    out: dict[str, float] = {
        f"level_count_ratio_d{depth}": n_p / n_g,
        f"level_recall_d{depth}": recall,
        f"level_text_dice_d{depth}": sum(dice for dice, _a, _b in matched) / n_g,
        f"level_exact_d{depth}": sum(1 for _d, a, b in matched if text_g[a] == text_p[b]) / n_g,
    }
    if precision is not None:
        out[f"level_precision_d{depth}"] = precision
        out[f"level_f1_d{depth}"] = f1(precision, recall)
    return out


# --------------------------------------------------------------------------- #
# One document pair
# --------------------------------------------------------------------------- #
def _put(out: dict[str, float], name: str, value: float | None) -> None:
    """Record ``value`` unless it is absent (``None``) or undefined (NaN)."""
    if value is not None and not math.isnan(value):
        out[name] = float(value)


def _comparability(
    gold: FlatDoc, pred: FlatDoc, pairs: Sequence[tuple[int, int]]
) -> dict[str, float]:
    out: dict[str, float] = {}
    ng, np_, m = len(gold.tokens), len(pred.tokens), len(pairs)
    _put(out, "alignable_fraction", 2 * m / (ng + np_) if (ng + np_) else None)
    _put(out, "token_len_ratio", np_ / ng if ng else None)
    return out


def _segmentation(
    gold: FlatDoc,
    pred: FlatDoc,
    pairs: Sequence[tuple[int, int]],
    chunk_g: Sequence[int],
    chunk_p: Sequence[int],
) -> dict[str, float]:
    out: dict[str, float] = {}
    _put(out, "seg_ari", adjusted_rand(chunk_g, chunk_p))
    agree = total = 0
    bnd_g = bnd_p = both = 0
    for k in range(len(pairs) - 1):
        ig, ip = pairs[k]
        jg, jp = pairs[k + 1]
        if jg != ig + 1 or jp != ip + 1:
            continue  # not adjacent on both sides: not a comparable event
        total += 1
        same_g = chunk_g[k] == chunk_g[k + 1]
        same_p = chunk_p[k] == chunk_p[k + 1]
        agree += same_g == same_p
        bnd_g += not same_g
        bnd_p += not same_p
        both += (not same_g) and (not same_p)
    _put(out, "coseg_agreement", agree / total if total else None)
    precision = both / bnd_p if bnd_p else None
    recall = both / bnd_g if bnd_g else None
    _put(
        out,
        "boundary_f1",
        f1(precision, recall)
        if precision is not None and recall is not None and (precision + recall)
        else None,
    )
    bag_g: Counter[str] = Counter(c.norm for c in gold.chunks)
    bag_p: Counter[str] = Counter(c.norm for c in pred.chunks)
    union = sum((bag_g | bag_p).values())
    _put(out, "chunk_jaccard_bag", sum((bag_g & bag_p).values()) / union if union else None)
    return out


def _labelling(
    gold: FlatDoc, pred: FlatDoc, tag_g: Sequence[str], tag_p: Sequence[str]
) -> dict[str, float]:
    """Name-blind first, then name-bound."""
    out: dict[str, float] = {}
    _put(out, "label_ari", adjusted_rand(tag_g, tag_p))
    bc = bcubed(tag_g, tag_p)
    if bc:
        out["bcubed_precision"], out["bcubed_recall"], out["bcubed_f1"] = bc
    _put(
        out,
        "tag_exact_agreement",
        sum(1 for x, y in zip(tag_g, tag_p, strict=True) if x == y) / len(tag_g) if tag_g else None,
    )
    vocab_g = {c.sem_tag for c in gold.chunks}
    vocab_p = {c.sem_tag for c in pred.chunks}
    _put(
        out,
        "tag_vocab_jaccard",
        len(vocab_g & vocab_p) / len(vocab_g | vocab_p) if (vocab_g | vocab_p) else None,
    )
    _put(out, "direct_label_rate_gold", _direct_rate(gold))
    _put(out, "direct_label_rate_pred", _direct_rate(pred))
    return out


def _shape(
    gold: FlatDoc, pred: FlatDoc, chunk_pairs: Sequence[tuple[int, int]]
) -> dict[str, float]:
    out: dict[str, float] = {}
    if len(chunk_pairs) >= 2:
        _put(
            out,
            "depth_match",
            sum(1 for ig, ip in chunk_pairs if gold.chunks[ig].depth == pred.chunks[ip].depth)
            / len(chunk_pairs),
        )
        use = chunk_pairs[:MAX_PAIR_CHUNKS]
        g_agree = g_total = lca_eq = lca_abs = 0
        for (ig1, ip1), (ig2, ip2) in combinations(use, 2):
            g_total += 1
            same_parent_g = gold.chunks[ig1].parent == gold.chunks[ig2].parent
            same_parent_p = pred.chunks[ip1].parent == pred.chunks[ip2].parent
            g_agree += same_parent_g == same_parent_p
            dg = common_prefix(gold.chunks[ig1].anc, gold.chunks[ig2].anc)
            dp = common_prefix(pred.chunks[ip1].anc, pred.chunks[ip2].anc)
            lca_abs += abs(dg - dp)
            lca_eq += dg == dp
        _put(out, "group_agreement", g_agree / g_total if g_total else None)
        _put(out, "lca_depth_match", lca_eq / g_total if g_total else None)
        _put(out, "lca_depth_mae", lca_abs / g_total if g_total else None)
        _put(out, "leaf_order_tau", kendall_tau([ip for _ig, ip in chunk_pairs]))
    _put(
        out,
        "path_suffix_cosine",
        cosine(
            Counter(c.path[-PATH_SUFFIX:] for c in gold.chunks),
            Counter(c.path[-PATH_SUFFIX:] for c in pred.chunks),
        ),
    )
    _put(
        out,
        "struct_path_cosine",
        cosine(
            Counter(c.struct_path for c in gold.chunks),
            Counter(c.struct_path for c in pred.chunks),
        ),
    )
    return out


def _grounding(
    gold: FlatDoc, pred: FlatDoc, chunk_pairs: Sequence[tuple[int, int]]
) -> dict[str, float]:
    out: dict[str, float] = {}
    ious = [
        v
        for ig, ip in chunk_pairs
        if (v := box_iou(gold.chunks[ig].boxes, pred.chunks[ip].boxes)) is not None
    ]
    _put(out, "origin_iou_mean", sum(ious) / len(ious) if ious else None)
    _put(out, "origin_iou_gt50", sum(1 for v in ious if v > 0.5) / len(ious) if ious else None)
    page_pairs = [
        (gold.chunks[ig].boxes[0][0], pred.chunks[ip].boxes[0][0])
        for ig, ip in chunk_pairs
        if gold.chunks[ig].boxes and pred.chunks[ip].boxes
    ]
    _put(
        out,
        "origin_page_match",
        sum(1 for p, q in page_pairs if p == q) / len(page_pairs) if page_pairs else None,
    )
    _put(out, "grounded_rate_gold", sum(1 for c in gold.chunks if c.boxes) / len(gold.chunks))
    _put(out, "grounded_rate_pred", sum(1 for c in pred.chunks if c.boxes) / len(pred.chunks))
    return out


def _guards(gold: FlatDoc, pred: FlatDoc) -> dict[str, float]:
    """Triviality guards: what a degenerate prediction would move."""
    out: dict[str, float] = {}
    vocab_g = {c.sem_tag for c in gold.chunks}
    vocab_p = {c.sem_tag for c in pred.chunks}
    _put(out, "chunk_count_ratio", len(pred.chunks) / len(gold.chunks))
    _put(out, "tag_count_ratio", len(vocab_p) / len(vocab_g) if vocab_g else None)
    _put(out, "element_count_ratio", pred.n_elements / gold.n_elements if gold.n_elements else None)
    _put(out, "mean_chunk_tokens_gold", len(gold.tokens) / len(gold.chunks))
    _put(out, "mean_chunk_tokens_pred", len(pred.tokens) / len(pred.chunks))
    _put(out, "tag_entropy_gold", entropy(Counter(c.sem_tag for c in gold.chunks)))
    _put(out, "tag_entropy_pred", entropy(Counter(c.sem_tag for c in pred.chunks)))
    return out


def _text_edits(gold: FlatDoc, pred: FlatDoc, pairs: Sequence[tuple[int, int]]) -> dict[str, float]:
    """Word edit operations, prediction -> gold."""
    out: dict[str, float] = {}
    ng = len(gold.tokens)
    ins, dele, sub = text_edit_ops(ng, len(pred.tokens), pairs)
    _put(out, "text_ins", ins)
    _put(out, "text_del", dele)
    _put(out, "text_sub", sub)
    _put(out, "text_wer", (ins + dele + sub) / ng if ng else None)
    return out


def compare_documents(gold: FlatDoc, pred: FlatDoc) -> dict[str, float]:
    """Every tree metric for one gold/prediction pair. Absent metrics are simply not present.

    Returns an empty mapping when either side has no text at all: there is nothing to align.
    """
    if gold.empty or pred.empty:
        return {}
    pairs = align_tokens(gold, pred)
    chunk_pairs = align_chunks(gold, pred, pairs)
    chunk_g = [gold.tok_chunk[ig] for ig, _ in pairs]
    chunk_p = [pred.tok_chunk[ip] for _, ip in pairs]
    tag_g = [gold.chunks[gold.tok_chunk[ig]].sem_tag for ig, _ in pairs]
    tag_p = [pred.chunks[pred.tok_chunk[ip]].sem_tag for _, ip in pairs]
    out: dict[str, float] = {
        **_comparability(gold, pred, pairs),
        **_segmentation(gold, pred, pairs, chunk_g, chunk_p),
        **_labelling(gold, pred, tag_g, tag_p),
        **_shape(gold, pred, chunk_pairs),
        **_grounding(gold, pred, chunk_pairs),
        **_guards(gold, pred),
        **_text_edits(gold, pred, pairs),
    }
    for depth in LEVEL_DEPTHS:
        out.update(level_metrics(gold, pred, pairs, depth))
    return out


# --------------------------------------------------------------------------- #
# One docset
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DocsetTree:
    """The tree family's answer for one docset: means over the alignable document pairs."""

    values: dict[str, float]
    n_compared: int
    """Document pairs with gold XML and a prediction that both carried text."""
    n_alignable: int
    """Of those, pairs at or above :data:`ALIGNABLE_MIN`; the means are over these."""
    n_unalignable: int
    n_without_gold_xml: int
    warnings: tuple[str, ...] = ()

    @property
    def absent(self) -> tuple[str, ...]:
        return tuple(name for name in ALL_TREE_METRICS if name not in self.values)


def compare_docset(
    pairs: Iterable[tuple[ElementTree.Element | None, ElementTree.Element]],
    *,
    alignable_min: float = ALIGNABLE_MIN,
    max_ted_nodes: int = MAX_TED_NODES,
) -> DocsetTree:
    """Score a docset from ``(gold root or None, predicted root)`` pairs.

    ``alignable_fraction`` and ``token_len_ratio`` are averaged over every compared pair, so the
    gate is visible; every other metric is averaged over the pairs that passed it.
    """
    per_doc: list[dict[str, float]] = []
    without_gold = ted_skipped = 0
    for gold_root, pred_root in pairs:
        if gold_root is None:
            without_gold += 1
            continue
        scores = compare_documents(flatten(gold_root), flatten(pred_root))
        if scores:
            # TED only for pairs the gate admits: it is the expensive part, and a tree distance
            # between two different transcriptions is not a measurement either.
            if scores.get("alignable_fraction", 0.0) >= alignable_min:
                ted = tree_edit_metrics(gold_root, pred_root, max_nodes=max_ted_nodes)
                if ted is None:
                    ted_skipped += 1
                else:
                    scores.update(ted)
            per_doc.append(scores)
    alignable = [d for d in per_doc if d.get("alignable_fraction", 0.0) >= alignable_min]
    values: dict[str, float] = {}
    for name in COMPARABILITY_METRICS:
        vals = [d[name] for d in per_doc if name in d]
        if vals:
            values[name] = sum(vals) / len(vals)
    for name in ALL_TREE_METRICS:
        if name in COMPARABILITY_METRICS:
            continue
        vals = [d[name] for d in alignable if name in d]
        if vals:
            values[name] = sum(vals) / len(vals)
    warnings: list[str] = []
    if without_gold:
        warnings.append(f"no_gold_xml:{without_gold}")
    if ted_skipped:
        warnings.append(f"ted_skipped_over_{max_ted_nodes}_nodes:{ted_skipped}")
    if per_doc and not alignable:
        warnings.append("unalignable")
    if not per_doc:
        warnings.append("nothing_to_compare")
    return DocsetTree(
        values=values,
        n_compared=len(per_doc),
        n_alignable=len(alignable),
        n_unalignable=len(per_doc) - len(alignable),
        n_without_gold_xml=without_gold,
        warnings=tuple(warnings),
    )
