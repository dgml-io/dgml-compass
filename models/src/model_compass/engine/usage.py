"""``usage.jsonl``: one row per model call, written by dgml under ``--debug``.

dgml names a document in a row's ``context`` for some operations and not others, so a
workspace's cost cannot be split per document. We never spread the total evenly: the summary
reports what the rows support and sets ``cost_partial`` when any spend is unattributed.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, ConfigDict, Field

from model_compass.errors import EngineError

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

USAGE_FILENAME: Final[str] = "usage.jsonl"


class UsageEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    at: datetime | None = None
    operation: str = ""
    model: str = ""
    cost_usd: float | None = 0.0
    """``None``: recorded but unpriced -- counted, adds nothing, flagged; never free."""
    prompt_tokens: int | None = 0
    completion_tokens: int | None = 0
    total_tokens: int | None = 0
    cache_read_tokens: int | None = 0
    cache_creation_tokens: int | None = 0
    duration_s: float = 0.0
    outcome: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    @property
    def document(self) -> str | None:
        value = self.context.get("doc") or self.context.get("document") or self.context.get("file")
        return str(value) if value else None


class UsageSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    present: bool = False
    n_events: int = 0
    n_failed: int = 0
    n_unpriced: int = 0
    unpriced_models: tuple[str, ...] = ()
    total_cost_usd: float = 0.0
    attributed_cost_usd: float = 0.0
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    total_duration_s: float = 0.0
    by_model: dict[str, float] = Field(default_factory=dict)
    by_operation: dict[str, float] = Field(default_factory=dict)
    by_document: dict[str, float] = Field(default_factory=dict)
    durations_s: tuple[float, ...] = ()
    label_models: tuple[str, ...] = ()
    """Models that actually served a ``label`` call; checked against the configured one."""

    @property
    def cost_partial(self) -> bool:
        return (
            not self.present
            or self.n_unpriced > 0
            or self.attributed_cost_usd < self.total_cost_usd - 1e-9
        )

    @property
    def unattributed_cost_usd(self) -> float:
        return max(0.0, self.total_cost_usd - self.attributed_cost_usd)


def parse_usage(lines: Iterable[str]) -> Iterator[UsageEvent]:
    for number, line in enumerate(lines, start=1):
        if not (text := line.strip()):
            continue
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise EngineError(
                f"usage.jsonl line {number} is not JSON: {text[:120]}", code="bad_usage_row"
            ) from exc
        if isinstance(raw, dict):
            yield UsageEvent.model_validate(raw)


def summarize(events: Iterable[UsageEvent]) -> UsageSummary:
    totals = dict.fromkeys(
        (
            "n_events",
            "n_failed",
            "n_unpriced",
            "total_tokens",
            "prompt_tokens",
            "completion_tokens",
            "cache_read_tokens",
            "cache_creation_tokens",
        ),
        0,
    )
    cost = attributed = duration = 0.0
    by_model: dict[str, float] = {}
    by_operation: dict[str, float] = {}
    by_document: dict[str, float] = {}
    durations: list[float] = []
    label_models: set[str] = set()
    unpriced_models: set[str] = set()
    for event in events:
        totals["n_events"] += 1
        totals["n_failed"] += 0 if event.outcome == "ok" else 1
        for key in (
            "total_tokens",
            "prompt_tokens",
            "completion_tokens",
            "cache_read_tokens",
            "cache_creation_tokens",
        ):
            totals[key] += getattr(event, key) or 0
        event_cost = event.cost_usd if event.cost_usd is not None else 0.0
        if event.cost_usd is None:
            totals["n_unpriced"] += 1
            if event.model:
                unpriced_models.add(event.model)
        cost += event_cost
        duration += event.duration_s
        durations.append(event.duration_s)
        by_model[event.model] = round(by_model.get(event.model, 0.0) + event_cost, 10)
        by_operation[event.operation] = round(
            by_operation.get(event.operation, 0.0) + event_cost, 10
        )
        if event.operation == "label" and event.model:
            label_models.add(event.model)
        if (document := event.document) is not None:
            attributed += event_cost
            by_document[document] = round(by_document.get(document, 0.0) + event_cost, 10)
    return UsageSummary(
        present=totals["n_events"] > 0,
        total_cost_usd=round(cost, 10),
        attributed_cost_usd=round(attributed, 10),
        total_duration_s=round(duration, 6),
        by_model=by_model,
        by_operation=by_operation,
        by_document=by_document,
        durations_s=tuple(durations),
        label_models=tuple(sorted(label_models)),
        unpriced_models=tuple(sorted(unpriced_models)),
        **totals,
    )


def read_usage(path: Path) -> UsageSummary:
    """A missing file is a run made without ``--debug``: ``present=False``, cost partial."""
    if not path.is_file():
        return UsageSummary(present=False)
    return summarize(parse_usage(path.read_text(encoding="utf-8").splitlines()))
