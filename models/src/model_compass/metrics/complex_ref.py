"""Grouped-instance scoring against ``*.complex_ref.json`` (docs/METRICS.md §1).

Per (document, type): a list of instances is *verified* and matched one-to-one; ``[]`` is
*verified absent* (any prediction is a false positive, the document still counts); ``null`` is
*unverified* and skipped, counted in ``complex_n_unverified``.

The pipeline does not produce complex predictions yet, so today these records carry the
denominators (``complex_n_*``) and zero scores (known defect 1 in docs/DECISIONS.md).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from model_compass.corpus.refs import InstanceState
from model_compass.metrics.alignment import f1, optimal_pairs
from model_compass.metrics.text import normalize_text

if TYPE_CHECKING:
    from model_compass.corpus.refs import ComplexRef, ComplexTypeSpec

MemberValue = str | tuple[str, ...] | None
Instance = Mapping[str, MemberValue]


def _as_multiset(value: MemberValue) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = normalize_text(value)
        return [normalized] if normalized else []
    return sorted(item for item in (normalize_text(part) for part in value) if item)


def member_f1(gold: MemberValue, pred: MemberValue) -> float:
    """Exact for a scalar, multiset F1 for a list; both absent is agreement."""
    left, right = _as_multiset(gold), _as_multiset(pred)
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    remaining = list(right)
    matched = 0
    for item in left:
        if item in remaining:
            remaining.remove(item)
            matched += 1
    return f1(matched / len(right), matched / len(left))


def instance_similarity(gold: Instance, pred: Instance, spec: ComplexTypeSpec) -> float:
    """Mean member F1; optional members only count when gold records them."""
    optional = set(spec.optional)
    members = [m for m in spec.members if m not in optional or _as_multiset(gold.get(m))]
    if not members:
        return 0.0
    return sum(member_f1(gold.get(m), pred.get(m)) for m in members) / len(members)


def _exact(gold: Instance, pred: Instance, spec: ComplexTypeSpec) -> bool:
    return all(_as_multiset(gold.get(m)) == _as_multiset(pred.get(m)) for m in spec.members)


def score_complex(
    reference: ComplexRef, predictions: Mapping[str, Mapping[str, Sequence[Instance]]]
) -> dict[str, float]:
    """``predictions`` is ``{file_id: {type_name: [instance, ...]}}``."""
    n_verified = n_absent = n_unverified = exact_matches = total_gold = total_pred = 0
    matched_mass = 0.0
    for entry in reference.entries:
        spec = reference.types.get(entry.type_name)
        if spec is None:
            continue
        predicted = list(predictions.get(entry.file_id, {}).get(entry.type_name, ()))
        if entry.state is InstanceState.UNVERIFIED:
            n_unverified += 1
            continue
        if entry.state is InstanceState.ABSENT:
            n_absent += 1
            total_pred += len(predicted)
            continue
        n_verified += 1
        gold_instances = [instance.members for instance in entry.instances]
        total_gold += len(gold_instances)
        total_pred += len(predicted)
        if not gold_instances or not predicted:
            continue
        scores = [[instance_similarity(g, p, spec) for p in predicted] for g in gold_instances]
        for i, j in optimal_pairs(scores):
            matched_mass += scores[i][j]
            exact_matches += 1 if _exact(gold_instances[i], predicted[j], spec) else 0

    precision = matched_mass / total_pred if total_pred else 0.0
    recall = matched_mass / total_gold if total_gold else 0.0
    exact_p = exact_matches / total_pred if total_pred else 0.0
    exact_r = exact_matches / total_gold if total_gold else 0.0
    return {
        "complex_instance_precision": 100.0 * precision,
        "complex_instance_recall": 100.0 * recall,
        "complex_instance_f1": 100.0 * f1(precision, recall),
        "complex_exact_instance_f1": 100.0 * f1(exact_p, exact_r),
        "complex_n_verified": float(n_verified),
        "complex_n_absent": float(n_absent),
        "complex_n_unverified": float(n_unverified),
        "complex_n_types": float(len(reference.types)),
    }
