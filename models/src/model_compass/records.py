"""MetricRecord: one family's numbers for one (cell, docset, draw).

Wire format is stable, field for field and in the same order, so ``metrics/<cell_id>.jsonl``
files from earlier runs stay interchangeable. ``absent`` names metrics that could not be
computed -- never read them as 0.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from model_compass.domain import MetricFamily

METRIC_SCHEMA_VERSION: Final[int] = 1


class MetricRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = METRIC_SCHEMA_VERSION
    run_id: str
    cell_id: str
    org: str
    docset: str
    draw: int = Field(default=0, ge=0)
    family: MetricFamily
    values: dict[str, float] = Field(default_factory=dict)
    counts: dict[str, int] = Field(default_factory=dict)
    absent: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    computed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def ref(self) -> str:
        return f"{self.org}/{self.docset}"

    def get(self, name: str) -> float | None:
        """The value, or ``None`` when absent. Never a silent zero."""
        if name in self.absent:
            return None
        return self.values.get(name)
