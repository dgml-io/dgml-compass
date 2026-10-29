"""Extraction quality: the numbers the project is judged on (docs/METRICS.md §1). Pure functions.

- ``individual_*`` picks the predicted tag answering each gold label per document; ``global_*``
  once per docset. ``global <= individual``; the gap is the cost of inconsistent naming.
- Every emitted score is a percentage, except ``missing_dgml_rate``: a 0-1 fraction here
  (known defect 4 in docs/DECISIONS.md).
- An empty gold set is an answer: predicting nothing there scores 1 and still counts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal

from model_compass.corpus.refs import REF_KEY_SEP
from model_compass.metrics.alignment import aligned_em, aligned_overlap, f1, greedy_overlap
from model_compass.metrics.text import (
    EMPTY,
    occurrence_keys,
    positional_keys,
    score_key,
    split_key,
    strip_provenance,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

EvalType = Literal["em", "em_aligned", "overlap", "overlap_aligned"]
Scheme = Literal["positional", "occurrence"]

SCALE: Final[float] = 100.0
_BLANK: Final[frozenset[str]] = frozenset({"", EMPTY})

ALL_EXTRACTION_METRICS: Final[tuple[str, ...]] = tuple(
    [
        f"{scope}_{name}"
        for scope in ("individual", "global")
        for name in (
            "em_precision",
            "em_recall",
            "em_f1",
            "overlap_precision",
            "overlap_recall",
            "overlap_f1",
            "em_aligned_f1",
            "overlap_aligned_f1",
            "em_relaxed_f1",
            "overlap_relaxed_f1",
        )
    ]
    + [
        "value_only_em_recall",
        "value_only_em_precision",
        "value_only_em_f1",
        "value_only_overlap_recall",
        "value_only_overlap_precision",
        "value_only_overlap_f1",
        "naming_penalty",
    ]
)
"""Every name the family can emit; the ``absent`` tuple is drawn from this, in this order."""


def count_overlap(gold: set[str], pred: set[str]) -> tuple[float, float]:
    """Partial-credit mass for one pair of value sets; both empty is (1, 1)."""
    pred_is_empty = not pred or pred == {""}
    if not gold and pred_is_empty:
        return 1.0, 1.0
    if not gold or pred_is_empty:
        return 0.0, 0.0
    return greedy_overlap(sorted(gold), sorted(pred))


def compute_scores(
    golds: Mapping[str, set[str]], preds: Mapping[str, set[str]], *, eval_type: EvalType = "em"
) -> tuple[float, float, float]:
    """Micro-averaged (precision, recall, f1) as fractions."""
    if golds.keys() != preds.keys():
        raise ValueError(
            f"gold and prediction keys differ, e.g. {sorted(set(golds) ^ set(preds))[:5]}"
        )
    nb_gold = nb_pred = correct = 0
    precision_mass = recall_mass = 0.0
    for key in sorted(golds):
        gold, pred = golds[key], preds[key]
        # max(..., 1): an empty set still has a denominator
        nb_gold += max(len(gold), 1)
        nb_pred += max(len(pred), 1)
        if eval_type == "em":
            correct += 1 if not gold and not pred else len(gold & pred)
        elif eval_type == "em_aligned":
            correct += 1 if not gold and not pred else aligned_em(frozenset(gold), frozenset(pred))
        else:
            p_mass, r_mass = (
                aligned_overlap(frozenset(gold), frozenset(pred))
                if eval_type == "overlap_aligned"
                else count_overlap(gold, pred)
            )
            precision_mass += p_mass
            recall_mass += r_mass
    if eval_type in ("em", "em_aligned"):
        precision = correct / nb_pred if nb_pred else 0.0
        recall = correct / nb_gold if nb_gold else 0.0
    else:
        precision = precision_mass / nb_pred if nb_pred else 0.0
        recall = recall_mass / nb_gold if nb_gold else 0.0
    return precision, recall, f1(precision, recall)


def headline_scores(
    golds: Mapping[str, set[str]], preds: Mapping[str, set[str]], *, aligned: bool = False
) -> dict[str, float]:
    """The six headline scores; the aligned F1s are report-only, never used for matching."""
    em_p, em_r, em_f = compute_scores(golds, preds, eval_type="em")
    ov_p, ov_r, ov_f = compute_scores(golds, preds, eval_type="overlap")
    out = {
        "em_precision": SCALE * em_p,
        "em_recall": SCALE * em_r,
        "em_f1": SCALE * em_f,
        "overlap_precision": SCALE * ov_p,
        "overlap_recall": SCALE * ov_r,
        "overlap_f1": SCALE * ov_f,
    }
    if aligned:
        out["em_aligned_f1"] = SCALE * compute_scores(golds, preds, eval_type="em_aligned")[2]
        out["overlap_aligned_f1"] = (
            SCALE * compute_scores(golds, preds, eval_type="overlap_aligned")[2]
        )
    return out


def build_gold(
    entries: Mapping[str, Sequence[str]],
    file_ids: Iterable[str],
    labels: Sequence[str],
    *,
    scheme: Scheme = "positional",
) -> dict[str, set[str]]:
    """Gold keyed ``file__label``; missing pairs are the sentinel, never an empty set."""
    wanted, label_set = set(file_ids), set(labels)
    collected: dict[str, list[str]] = {}
    for raw_key, values in entries.items():
        file_id, separator, label = raw_key.partition(REF_KEY_SEP)
        if not separator or file_id not in wanted or label not in label_set:
            continue
        collected.setdefault(score_key(file_id, label), []).extend(
            strip_provenance(str(value))[0] for value in values
        )
    keyed = positional_keys if scheme == "positional" else occurrence_keys
    out = {key: keyed(values) for key, values in collected.items()}
    for file_id in sorted(wanted):
        for label in labels:
            out.setdefault(score_key(file_id, label), {EMPTY})
    return out


def build_predictions(
    tagged: Mapping[str, Mapping[str, Sequence[str]]],
    file_ids: Iterable[str],
    *,
    scheme: Scheme = "positional",
) -> dict[str, set[str]]:
    """Predictions keyed ``file__tag``, padded with the sentinel over the docset-wide union of
    predicted tags, like gold (DECISIONS 0014). Insertion order is preserved: it breaks ties."""
    keyed = positional_keys if scheme == "positional" else occurrence_keys
    out = {
        score_key(file_id, tag): keyed(list(values))
        for file_id, by_tag in tagged.items()
        for tag, values in by_tag.items()
    }
    tags = sorted({tag for by_tag in tagged.values() for tag in by_tag})
    for file_id in sorted(set(file_ids) | set(tagged)):
        for tag in tags:
            out.setdefault(score_key(file_id, tag), {EMPTY})
    return out


def _best(
    candidates: Iterable[dict[str, set[str]]], gold: Mapping[str, set[str]]
) -> dict[str, set[str]]:
    """Highest em_f1; else highest overlap_f1; else nothing. First to reach the best wins, so
    the order candidates arrive in is part of the metric."""
    best_em: tuple[float, dict[str, set[str]]] = (0.0, {})
    best_overlap: tuple[float, dict[str, set[str]]] = (0.0, {})
    for prediction in candidates:
        scores = headline_scores(gold, prediction)
        if scores["em_f1"] > best_em[0]:
            best_em = (scores["em_f1"], prediction)
        if scores["overlap_f1"] > best_overlap[0]:
            best_overlap = (scores["overlap_f1"], prediction)
    return best_em[1] if best_em[0] > 0 else best_overlap[1]


def score_individual(
    gold: Mapping[str, set[str]],
    predictions: Mapping[str, set[str]],
    file_ids: Sequence[str],
    labels: Sequence[str],
) -> dict[str, float]:
    """Per-document tag choice. Candidates in extractor (insertion) order, NOT sorted."""
    by_file: dict[str, dict[str, set[str]]] = {}
    for key, values in predictions.items():
        file_id, _ = split_key(key)
        by_file.setdefault(file_id, {})[key] = values
    chosen: dict[str, set[str]] = {}
    for label in labels:
        for file_id in sorted(file_ids):
            key = score_key(file_id, label)
            reference = {key: gold.get(key, set())}
            candidates = [{key: values} for values in by_file.get(file_id, {}).values()]
            chosen[key] = _best(candidates, reference).get(key, set())
    return headline_scores(dict(gold), chosen, aligned=True)


def score_global(
    gold: Mapping[str, set[str]],
    predictions: Mapping[str, set[str]],
    file_ids: Sequence[str],
    labels: Sequence[str],
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """One tag per gold label for the whole docset; also the per-label scores."""
    by_tag: dict[str, dict[str, set[str]]] = {}
    for key, values in predictions.items():
        file_id, tag = split_key(key)
        by_tag.setdefault(tag, {})[file_id] = values
    chosen: dict[str, set[str]] = {}
    per_label: dict[str, dict[str, float]] = {}
    for label in labels:
        reference = {
            score_key(fid, label): gold.get(score_key(fid, label), set())
            for fid in sorted(file_ids)
        }
        candidates = [
            {score_key(fid, label): bucket.get(fid, set()) for fid in sorted(file_ids)}
            for _, bucket in sorted(by_tag.items())
        ]
        winner = _best(candidates, reference) or {key: set() for key in reference}
        chosen.update(winner)
        per_label[label] = headline_scores(reference, winner, aligned=True)
    return headline_scores(dict(gold), chosen, aligned=True), per_label


def _pool(keyed: Mapping[str, set[str]], file_ids: set[str]) -> dict[str, set[str]]:
    pooled: dict[str, set[str]] = {file_id: set() for file_id in file_ids}
    for key, values in keyed.items():
        file_id, _ = split_key(key)
        if file_id in file_ids:
            pooled[file_id] |= {v for v in values if v and v not in _BLANK}
    return pooled


def value_only_scores(
    gold: Mapping[str, set[str]], predictions: Mapping[str, set[str]], file_ids: Iterable[str]
) -> dict[str, float]:
    """Values scored ignoring their tag names. Read recall: gold annotates a dozen
    fields, the generator tags hundreds, so precision is dominated by un-annotated values."""
    wanted = set(file_ids)
    golds, preds = _pool(gold, wanted), _pool(predictions, wanted)
    if not golds:
        return {}
    em_p, em_r, em_f = compute_scores(golds, preds, eval_type="em")
    ov_p, ov_r, ov_f = compute_scores(golds, preds, eval_type="overlap")
    return {
        "value_only_em_recall": SCALE * em_r,
        "value_only_em_precision": SCALE * em_p,
        "value_only_overlap_recall": SCALE * ov_r,
        "value_only_overlap_precision": SCALE * ov_p,
        "value_only_em_f1": SCALE * em_f,
        "value_only_overlap_f1": SCALE * ov_f,
    }


def per_type_scores(
    per_label: Mapping[str, Mapping[str, float]], types_by_label: Mapping[str, str]
) -> dict[str, dict[str, float]]:
    """Per-label scores averaged per gold type; a type with no labels is absent."""
    grouped: dict[str, list[Mapping[str, float]]] = {}
    for label, scores in per_label.items():
        if ref_type := types_by_label.get(label):
            grouped.setdefault(ref_type, []).append(scores)
    out: dict[str, dict[str, float]] = {}
    for ref_type, rows in sorted(grouped.items()):
        names = sorted({name for row in rows for name in row})
        out[ref_type] = {n: sum(row.get(n, 0.0) for row in rows) / len(rows) for n in names}
        out[ref_type]["n_labels"] = float(len(rows))
    return out


def score_docset(
    gold_entries: Mapping[str, Sequence[str]],
    predictions: Mapping[str, Mapping[str, Sequence[str]]],
    file_ids: Sequence[str],
    labels: Sequence[str],
    *,
    types_by_label: Mapping[str, str] | None = None,
) -> dict[str, float]:
    """Every extraction metric for one docset, under its published name (docs/METRICS.md §1)."""
    scored = sorted(set(file_ids))
    result: dict[str, float] = {}
    if not scored or not labels:
        return result
    for scheme in ("positional", "occurrence"):
        gold = build_gold(gold_entries, scored, labels, scheme=scheme)
        preds = build_predictions(predictions, scored, scheme=scheme)
        individual = score_individual(gold, preds, scored, labels)
        overall, per_label = score_global(gold, preds, scored, labels)
        if scheme == "occurrence":
            # The relaxed scheme contributes only its F1s (DECISIONS 0007).
            result["individual_em_relaxed_f1"] = individual["em_f1"]
            result["individual_overlap_relaxed_f1"] = individual["overlap_f1"]
            result["global_em_relaxed_f1"] = overall["em_f1"]
            result["global_overlap_relaxed_f1"] = overall["overlap_f1"]
            continue
        result.update({f"individual_{k}": v for k, v in individual.items()})
        result.update({f"global_{k}": v for k, v in overall.items()})
        blind = value_only_scores(gold, preds, scored)
        result.update(blind)
        # Tag-blind recall minus tagged recall. Not clamped: negative means a pooling bug.
        result["naming_penalty"] = blind["value_only_overlap_recall"] - individual["overlap_recall"]
        for ref_type, scores in per_type_scores(per_label, types_by_label or {}).items():
            for name, value in scores.items():
                result[f"per_type.{ref_type}.{name}"] = value
    return result
