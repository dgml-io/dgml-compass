"""What a cell cost, how big its output is, how often it failed, how long it took.

Definitions: docs/METRICS.md §3.

Billed tokens (from ``usage.jsonl``) and estimated ones (chars/4, ``est_`` prefix) never mix.
Every metric is ``None`` when it cannot be computed; ``absent`` names it. ``cost_partial`` is
carried as a warning so aggregation can refuse to compare flagged and unflagged cells.

Role prices (additive): the billed cost split in the shares ``usage.jsonl`` shows --
``transcribe`` calls to the transcriber, ``label`` and ``links`` calls to the labeler --
divided by pages; ``cost_per_page_pipeline`` is the whole cost per page, emitted only when one
model fills both slots.
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from model_compass.engine.usage import UsageSummary

CHARS_PER_TOKEN: Final[float] = 4.0
"""Only for the representation-cost ratio, never for a billed figure."""
_ORIGIN_ATTR: Final[re.Pattern[str]] = re.compile(r'\sdg:origin="[^"]*"')
_ELEMENT: Final[re.Pattern[str]] = re.compile(r"<(?!/|\?|!)")

ALL_ECONOMICS_METRICS: Final[tuple[str, ...]] = (
    "cost_usd",
    "cost_per_doc",
    "cost_per_page",
    "tokens_per_doc",
    "tokens_per_page",
    "f1_per_dollar",
    "f1_per_1k_tokens",
    "expansion_x",
    "origin_overhead_pct",
    "chars_per_element",
    "est_dgml_tokens",
    "llm_failure_rate",
    "missing_dgml_rate",
    "seconds_per_doc",
    "seconds_per_page",
    "call_p50_s",
    "call_p95_s",
)
ROLE_OF_OPERATION: Final[dict[str, str]] = {
    "transcribe": "transcribe",
    "label": "label",
    "links": "label",
}
ROLE_PRICE_METRICS: Final[tuple[str, ...]] = (
    "cost_per_page_transcribe",
    "cost_per_page_label",
    "cost_per_page_pipeline",
)


def percentile_nearest_rank(values: Sequence[float], quantile: float) -> float | None:
    """``sorted[ceil(q*n) - 1]``: with small n this is the max, the honest tail answer."""
    if not values:
        return None
    if not 0.0 < quantile <= 1.0:
        raise ValueError(f"quantile must be in (0, 1], got {quantile}")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(quantile * len(ordered)) - 1))]


@dataclass(frozen=True)
class RepresentationCost:
    documents: int = 0
    pages: int = 0
    elements: int = 0
    dgml_chars: int = 0
    origin_chars: int = 0
    source_chars: int = 0


def representation_cost(
    dgml_texts: Iterable[str], page_word_counts: Iterable[Sequence[int]]
) -> RepresentationCost:
    """Output size against source size. ``+1`` per word approximates whitespace."""
    documents = dgml_chars = origin_chars = elements = pages = source_chars = 0
    for text in dgml_texts:
        documents += 1
        dgml_chars += len(text)
        origin_chars += sum(len(m) for m in _ORIGIN_ATTR.findall(text))
        elements += len(_ELEMENT.findall(text))
    for lengths in page_word_counts:
        pages += 1
        source_chars += sum(length + 1 for length in lengths)
    return RepresentationCost(documents, pages, elements, dgml_chars, origin_chars, source_chars)


def _per(value: float | None, denominator: int) -> float | None:
    return None if value is None or not denominator else value / denominator


@dataclass(frozen=True)
class Economics:
    documents: int = 0
    pages: int = 0
    files_expected: int = 0
    llm_calls: int = 0
    failed_calls: int = 0
    total_tokens: int = 0
    cost_usd: float | None = None
    unattributed_cost_usd: float = 0.0
    cost_partial: bool = False
    durations_s: tuple[float, ...] = ()
    representation: RepresentationCost = RepresentationCost()
    f1: float | None = None

    @property
    def values(self) -> dict[str, float]:
        """Computable metrics only, in ALL_ECONOMICS_METRICS order."""
        rep, cost, tokens, durations = (
            self.representation,
            self.cost_usd,
            self.total_tokens,
            self.durations_s,
        )
        candidates: dict[str, float | None] = {
            "cost_usd": cost,
            "cost_per_doc": _per(cost, self.documents),
            "cost_per_page": _per(cost, self.pages),
            "tokens_per_doc": _per(float(tokens), self.documents) if tokens else None,
            "tokens_per_page": _per(float(tokens), self.pages) if tokens else None,
            "f1_per_dollar": self.f1 / cost if self.f1 is not None and cost else None,
            "f1_per_1k_tokens": (
                self.f1 / (tokens / 1000.0) if self.f1 is not None and tokens else None
            ),
            "expansion_x": rep.dgml_chars / rep.source_chars if rep.source_chars else None,
            "origin_overhead_pct": (
                100.0 * rep.origin_chars / rep.dgml_chars if rep.dgml_chars else None
            ),
            "chars_per_element": rep.dgml_chars / rep.elements if rep.elements else None,
            "est_dgml_tokens": rep.dgml_chars / CHARS_PER_TOKEN if rep.dgml_chars else None,
            "llm_failure_rate": (
                100.0 * self.failed_calls / self.llm_calls if self.llm_calls else None
            ),
            # clamped: more documents than expected files means the expectation is wrong
            "missing_dgml_rate": (
                100.0 * max(0, self.files_expected - self.documents) / self.files_expected
                if self.files_expected
                else None
            ),
            "seconds_per_doc": _per(sum(durations), self.documents) if durations else None,
            "seconds_per_page": _per(sum(durations), self.pages) if durations else None,
            "call_p50_s": statistics.median(durations) if durations else None,
            "call_p95_s": percentile_nearest_rank(durations, 0.95),
        }
        return {name: float(v) for name, v in candidates.items() if v is not None}

    @property
    def absent(self) -> tuple[str, ...]:
        values = self.values
        return tuple(name for name in ALL_ECONOMICS_METRICS if name not in values)

    @property
    def counts(self) -> dict[str, int]:
        counts = {
            "documents": self.documents,
            "pages": self.pages,
            "files_expected": self.files_expected,
            "llm_calls": self.llm_calls,
            "failed_calls": self.failed_calls,
            "total_tokens": self.total_tokens,
            "elements": self.representation.elements,
            "dgml_chars": self.representation.dgml_chars,
            "source_chars": self.representation.source_chars,
        }
        if self.cost_partial:
            # micros: counts are integers, and a fraction of a cent must not round to "none"
            counts["unattributed_cost_micros"] = round(self.unattributed_cost_usd * 1_000_000)
        return counts

    def warnings(self) -> tuple[str, ...]:
        flags = (
            ("cost_partial", self.cost_partial),
            ("no_usage_telemetry", not self.llm_calls),
            ("no_documents", not self.documents),
            ("no_page_text", not self.pages),
            ("no_expected_file_count", not self.files_expected),
            ("no_quality_score", self.f1 is None),
        )
        return tuple(name for name, on in flags if on)


def compute_economics(
    usage: UsageSummary,
    representation: RepresentationCost,
    *,
    files_expected: int = 0,
    f1: float | None = None,
) -> Economics:
    """``documents`` is the DGML count (falling back to documents the usage rows name), so a
    generation shortfall stays visible as ``missing_dgml_rate``."""
    return Economics(
        documents=representation.documents or len(usage.by_document),
        pages=representation.pages,
        files_expected=files_expected,
        llm_calls=usage.n_events,
        failed_calls=usage.n_failed,
        total_tokens=usage.total_tokens,
        cost_usd=usage.total_cost_usd if usage.present else None,
        unattributed_cost_usd=usage.unattributed_cost_usd,
        cost_partial=usage.cost_partial,
        durations_s=tuple(usage.durations_s),
        representation=representation,
        f1=f1,
    )


def role_prices(
    economics: Economics, by_operation: Mapping[str, float], *, same_model: bool
) -> dict[str, float]:
    """Per-role price per page; see the module docstring. Empty without cost or pages."""
    cost, pages = economics.cost_usd, economics.pages
    if not cost or not pages:
        return {}
    by_role: dict[str, float] = {}
    for operation, spent in by_operation.items():
        if (role := ROLE_OF_OPERATION.get(operation)) is not None:
            by_role[role] = by_role.get(role, 0.0) + spent
    total = sum(by_role.values())
    out: dict[str, float] = {}
    if total > 0:
        for role in ("transcribe", "label"):
            if role in by_role:
                out[f"cost_per_page_{role}"] = cost * by_role[role] / total / pages
    if same_model:
        out["cost_per_page_pipeline"] = cost / pages
    return out
