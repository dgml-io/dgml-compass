"""The shared vocabulary: closed enums and the axis keys a spec may use (DECISIONS 0002)."""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, field_validator

AxisValue = bool | int | float | str


class ModelSlot(StrEnum):
    """The five model slots of a dgml config, named as its keys."""

    CLASSIFICATION = "classification.model"
    GENERATION = "generation.model"
    LABEL = "generation.label_model"
    SCHEMA = "grounded.schema_model"
    VALUES = "grounded.values_model"


class SchemaTier(StrEnum):
    NONE = "none"
    MAPPED = "mapped"
    RICH = "rich"
    SPEC = "spec"


class TextMode(StrEnum):
    DIGITAL = "digital"
    OCR = "ocr"
    HYBRID = "hybrid"


class Shape(StrEnum):
    """The closed set of document shapes."""

    PROSE_NARRATIVE = "prose_narrative"
    FORM = "form"
    TABLE_DENSE = "table_dense"
    HYBRID_COMPOSITE = "hybrid_composite"
    CORRESPONDENCE = "correspondence"
    COMPLEX_LAYOUT = "complex_layout"


class MetricFamily(StrEnum):
    """Metric families. ``shape`` is not scored; it stays so records that name it still
    parse and a spec asking for it gets a clear error."""

    EXTRACTION = "extraction"
    REFERENCE_FREE = "reference_free"
    ECONOMICS = "economics"
    TREE = "tree"
    SHAPE = "shape"


SCORED_FAMILIES: Final[tuple[MetricFamily, ...]] = (
    MetricFamily.EXTRACTION,
    MetricFamily.REFERENCE_FREE,
    MetricFamily.ECONOMICS,
    MetricFamily.TREE,
)

THINKING_MODES: Final[tuple[str, ...]] = ("disabled", "adaptive")
"""``generation.thinking`` values; dgml defaults to ``disabled``."""

AXIS_KEYS: Final[frozenset[str]] = frozenset(
    {slot.value for slot in ModelSlot}
    | {
        "schema_tier",
        "text_mode",
        "window_size",
        "temperature",
        "max_tokens",
        "max_files_per_docset",
        "generation.thinking",
    }
)
"""Keys valid in ``axes:`` and ``fixed:``. Closed on purpose: a typo such as
``generation.labelmodel`` must fail validation, not run a sweep where nothing varied."""


class DocsetRef(BaseModel):
    """``<org>/<docset_id>``. A bare docset id is refused: ids are only unique within an org."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    org: str
    docset_id: str

    @field_validator("org", "docset_id")
    @classmethod
    def _part(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        if "/" in value:
            raise ValueError("must not contain '/'; write '<org>/<docset_id>'")
        return value

    @classmethod
    def parse(cls, reference: str) -> Self:
        org, slash, docset_id = reference.partition("/")
        if not slash:
            raise ValueError(f"{reference!r} is not '<org>/<docset_id>'")
        return cls(org=org, docset_id=docset_id)

    def __str__(self) -> str:
        return f"{self.org}/{self.docset_id}"
