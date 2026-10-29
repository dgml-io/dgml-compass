"""The cost model: a price list, token-count estimates per draw, and the run's ``prices.json``.

It sits outside ``experiments`` so the engine can price a draw without importing the planner.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import TYPE_CHECKING, Final

import yaml
from pydantic import BaseModel, ConfigDict, Field

from model_compass.domain import ModelSlot
from model_compass.errors import ConfigError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from model_compass.config import Settings

log = logging.getLogger(__name__)

PRICES_SCHEMA_VERSION: Final[int] = 1
PRICES_FILENAME: Final[str] = "prices.json"

COST_CONSTANTS: Final[dict[str, float]] = {
    "TRANSCRIBE_PROMPT_OVERHEAD": 1_500,
    "XML_EXPANSION": 1.5,
    "TRANSCRIBE_MIN_OUTPUT": 600,
    "DOCS_PER_BATCH": 10,
    "LABEL_INPUT": 20_000,
    "LABEL_OUTPUT": 3_000,
}
"""Token counts per transcribe window and per label batch."""

ASSUMPTIONS: Final[dict[str, float]] = {
    "pages_per_document": 10.0,
    "text_tokens_per_page": 1_200.0,
}
"""Planning stand-ins for the static PDF profile that does not exist at planning time."""

TIME_ASSUMPTIONS: Final[dict[str, float]] = {
    "seconds_per_document": 30.0,
    "seconds_per_label_batch": 150.0,
}

_MTOK: Final[float] = 1_000_000.0


class ModelPrice(BaseModel):
    """Per-million-token prices for one model."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    input_per_mtok: float | None = None
    output_per_mtok: float | None = None

    @property
    def priced(self) -> bool:
        return self.input_per_mtok is not None and self.output_per_mtok is not None

    def cost(self, *, prompt_tokens: float, completion_tokens: float) -> float:
        if not self.priced:
            return 0.0
        return (
            prompt_tokens * (self.input_per_mtok or 0.0)
            + completion_tokens * (self.output_per_mtok or 0.0)
        ) / _MTOK


class CostEstimate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    usd: float = 0.0
    by_slot: dict[str, float] = Field(default_factory=dict)
    assumptions: dict[str, float] = Field(default_factory=dict)
    unpriced_models: tuple[str, ...] = ()
    basis: str = "assumption"


def load_prices(prices_file: Path | str) -> dict[str, ModelPrice]:
    path = Path(prices_file)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(
            f"price list not found at {path}; set DGC_PRICES_FILE", code="prices_missing"
        ) from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}", code="prices_invalid") from exc
    prices: dict[str, ModelPrice] = {}
    for entry in (raw or {}).get("models") or []:
        if isinstance(entry, dict) and entry.get("id"):
            price = ModelPrice.model_validate(entry)
            prices[price.id] = price
    if not prices:
        raise ConfigError(f"{path} lists no models", code="prices_invalid")
    return prices


def settings_prices(settings: Settings) -> dict[str, ModelPrice]:
    """The configured prices, or none: a plan that cannot price a model says so, not fails."""
    try:
        return load_prices(settings.prices_file)
    except ConfigError as exc:
        log.warning("prices unavailable: %s", exc.message)
        return {}


def estimate_generation(
    *,
    n_documents: int,
    generation_model: str | None,
    label_model: str | None,
    prices: Mapping[str, ModelPrice],
) -> CostEstimate:
    """What ``docset generate`` costs for ``n_documents``: per-page transcription plus one
    labelling call per batch of ``DOCS_PER_BATCH`` documents. Grounding and classification are
    not modelled; no sweep varies them."""
    pages = ASSUMPTIONS["pages_per_document"]
    per_page = ASSUMPTIONS["text_tokens_per_page"]
    if n_documents <= 0:
        return CostEstimate(assumptions=dict(ASSUMPTIONS))
    unpriced: list[str] = []
    by_slot: dict[str, float] = {}

    generation_price = prices.get(generation_model or "")
    if generation_model and (generation_price is None or not generation_price.priced):
        unpriced.append(generation_model)
        generation_price = None
    if generation_price is not None:
        total_pages = n_documents * pages
        prompt = total_pages * (per_page + COST_CONSTANTS["TRANSCRIBE_PROMPT_OVERHEAD"])
        completion = total_pages * max(
            per_page * COST_CONSTANTS["XML_EXPANSION"],
            COST_CONSTANTS["TRANSCRIBE_MIN_OUTPUT"],
        )
        by_slot[ModelSlot.GENERATION.value] = round(
            generation_price.cost(prompt_tokens=prompt, completion_tokens=completion), 6
        )

    label_price = prices.get(label_model or "")
    if label_model and (label_price is None or not label_price.priced):
        unpriced.append(label_model)
        label_price = None
    if label_price is not None:
        calls = max(1, math.ceil(n_documents / COST_CONSTANTS["DOCS_PER_BATCH"]))
        by_slot[ModelSlot.LABEL.value] = round(
            label_price.cost(
                prompt_tokens=calls * COST_CONSTANTS["LABEL_INPUT"],
                completion_tokens=calls * COST_CONSTANTS["LABEL_OUTPUT"],
            ),
            6,
        )

    return CostEstimate(
        usd=round(sum(by_slot.values()), 6),
        by_slot=by_slot,
        assumptions={"pages_per_document": pages, "text_tokens_per_page": per_page},
        unpriced_models=tuple(sorted(set(unpriced))),
        basis="cost model + price list + stated assumptions",
    )


def estimate_seconds(*, n_documents: int, draws: int = 1) -> float:
    """Serial wall clock for one cell; order-of-magnitude, from recorded usage rows."""
    if n_documents <= 0:
        return 0.0
    batches = max(1, math.ceil(n_documents / COST_CONSTANTS["DOCS_PER_BATCH"]))
    per_draw = (
        n_documents * TIME_ASSUMPTIONS["seconds_per_document"]
        + batches * TIME_ASSUMPTIONS["seconds_per_label_batch"]
    )
    return round(per_draw * max(1, draws), 3)


def write_run_prices(
    run_dir: Path,
    prices: Mapping[str, ModelPrice],
    *,
    source: str = "",
    version: str | None = None,
) -> Path:
    """``prices.json``: the price list the run was planned with, written even when empty."""
    payload = {
        "schema_version": PRICES_SCHEMA_VERSION,
        "source": source,
        "version": version,
        "models": {name: price.model_dump(mode="json") for name, price in sorted(prices.items())},
    }
    path = run_dir / PRICES_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_run_prices(run_dir: Path) -> dict[str, ModelPrice]:
    path = run_dir / PRICES_FILENAME
    if not path.is_file():
        return {}
    models = json.loads(path.read_text(encoding="utf-8")).get("models") or {}
    return {name: ModelPrice.model_validate(entry) for name, entry in models.items()}
