"""The run manifest and its event log: :meth:`RunManifest.apply` folds ``events.jsonl`` into it."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, Self

from pydantic import BaseModel, ConfigDict, Field

from model_compass.errors import CompassError
from model_compass.experiments.spec import ExperimentSpec

SCHEMA_VERSION: Final[int] = 1


def _now() -> datetime:
    return datetime.now(UTC)


class CellStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    DRY_RUN = "dry_run"
    CANCELLED = "cancelled"


class RunOutcome(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    BUDGET_ABORTED = "budget_aborted"
    CANCELLED = "cancelled"
    DRY_RUN = "dry_run"


class EventKind(StrEnum):
    RUN_STARTED = "run_started"
    CELL_STARTED = "cell_started"
    CELL_SUCCEEDED = "cell_succeeded"
    CELL_FAILED = "cell_failed"
    CELL_RETRIED = "cell_retried"
    """Not emitted by this version; kept so event logs that contain it still replay."""
    CELL_SKIPPED = "cell_skipped"
    CELL_RECOVERED = "cell_recovered"
    """No longer emitted; kept so event logs that contain it still replay."""
    BUDGET_WARNING = "budget_warning"
    """Not emitted by this version; kept so event logs that contain it still replay."""
    RUN_ABORTED = "run_aborted"
    RUN_FINISHED = "run_finished"


class RepoProvenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    path: str
    commit: str | None = None
    branch: str | None = None
    dirty: bool = False


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = SCHEMA_VERSION
    repos: dict[str, RepoProvenance] = Field(default_factory=dict)
    dgml_version: str | None = None
    python_version: str
    package_version: str
    corpus_hash: str | None = None
    prices_version: str | None = None
    captured_at: datetime = Field(default_factory=_now)

    @property
    def any_dirty(self) -> bool:
        return any(repo.dirty for repo in self.repos.values())


class EnvironmentInfo(BaseModel):
    """How the run was executed. Credential variable NAMES only, never values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    executor: str
    storage_uri: str
    profile: str | None = None
    max_parallel_cells: int
    max_parallel_calls: int
    budget_usd: float
    dry_run: bool = False
    model_ids: tuple[str, ...] = ()
    credential_env_names_present: tuple[str, ...] = ()


class Costs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    estimated_usd: float = 0.0
    actual_usd: float = 0.0
    by_model: dict[str, float] = Field(default_factory=dict)
    partial: bool = False


class CellRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    cell_id: str
    status: CellStatus = CellStatus.PENDING
    attempts: int = 0
    draws_total: int = 1
    draws_completed: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cost_usd: float = 0.0
    error_code: str | None = None
    error_message: str | None = None
    artifact_prefix: str | None = None


class RunEvent(BaseModel):
    """One line of ``events.jsonl``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = SCHEMA_VERSION
    at: datetime = Field(default_factory=_now)
    kind: EventKind
    cell_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class RunManifest(BaseModel):
    """Derived state: replaying ``events.jsonl`` onto the plan's manifest reproduces it."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    run_id: str
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    spec: ExperimentSpec
    provenance: Provenance
    environment: EnvironmentInfo
    cells: dict[str, CellRecord] = Field(default_factory=dict)
    costs: Costs = Field(default_factory=Costs)
    outcome: RunOutcome = RunOutcome.PENDING

    def _cell(self, cell_id: str | None) -> CellRecord:
        if cell_id is None or cell_id not in self.cells:
            raise CompassError(f"event names unknown cell {cell_id!r}", code="unknown_cell")
        return self.cells[cell_id]

    def apply(self, event: RunEvent) -> Self:
        """Fold one event in. A draw's success advances its cell; the cell succeeds with its
        last draw, and a failed draw keeps the cell failed whatever lands later."""
        payload = event.payload
        match event.kind:
            case EventKind.RUN_STARTED:
                self.outcome = RunOutcome.RUNNING
                self.costs.estimated_usd = float(payload.get("estimated_usd", 0.0))
            case EventKind.CELL_STARTED:
                record = self._cell(event.cell_id)
                record.status = CellStatus.RUNNING
                record.started_at = record.started_at or event.at
                record.attempts += 1
            case EventKind.CELL_RETRIED:
                record = self._cell(event.cell_id)
                record.status = CellStatus.RUNNING
                record.attempts += 1
            case EventKind.CELL_SUCCEEDED:
                record = self._cell(event.cell_id)
                cost = float(payload.get("cost_usd", 0.0))
                done = CellStatus.DRY_RUN if payload.get("dry_run") else CellStatus.SUCCEEDED
                if "draw_index" in payload:
                    record.draws_completed = min(record.draws_total, record.draws_completed + 1)
                    record.cost_usd = round(record.cost_usd + cost, 10)
                    if record.status is not CellStatus.FAILED:
                        finished = record.draws_completed >= record.draws_total
                        record.status = done if finished else CellStatus.RUNNING
                        if finished:
                            record.finished_at = event.at
                else:
                    record.status = done
                    record.finished_at = event.at
                    record.draws_completed = int(payload.get("draws_completed", record.draws_total))
                    record.cost_usd = cost
                record.artifact_prefix = payload.get("artifact_prefix") or record.artifact_prefix
                self._add_cost(cost, payload.get("by_model"))
            case EventKind.CELL_FAILED:
                record = self._cell(event.cell_id)
                cost = float(payload.get("cost_usd", 0.0))
                record.status = CellStatus.FAILED
                record.finished_at = event.at
                record.error_code = payload.get("code")
                record.error_message = payload.get("message")
                if "draw_index" in payload:
                    record.cost_usd = round(record.cost_usd + cost, 10)
                else:
                    record.cost_usd = float(payload.get("cost_usd", record.cost_usd))
                self._add_cost(cost, payload.get("by_model"))
            case EventKind.CELL_RECOVERED:
                record = self._cell(event.cell_id)
                cost = float(payload.get("cost_usd", 0.0))
                record.draws_completed = min(record.draws_total, record.draws_completed + 1)
                record.cost_usd = round(record.cost_usd + cost, 10)
                record.artifact_prefix = payload.get("artifact_prefix") or record.artifact_prefix
                if record.draws_completed >= record.draws_total:
                    record.status = CellStatus.SUCCEEDED
                    record.finished_at = event.at
                    record.error_code = None
                    record.error_message = None
                self._add_cost(cost, payload.get("by_model"))
            case EventKind.CELL_SKIPPED:
                record = self._cell(event.cell_id)
                reason = payload.get("reason")
                record.status = (
                    CellStatus.CANCELLED
                    if reason in ("cancelled", "budget_exceeded")
                    else CellStatus.SKIPPED
                )
                record.error_code = reason
            case EventKind.BUDGET_WARNING:
                self.costs.partial = bool(payload.get("partial", self.costs.partial))
            case EventKind.RUN_ABORTED:
                reason = payload.get("reason", RunOutcome.CANCELLED.value)
                self.outcome = (
                    RunOutcome.BUDGET_ABORTED
                    if reason == RunOutcome.BUDGET_ABORTED.value
                    else RunOutcome.CANCELLED
                )
            case EventKind.RUN_FINISHED:
                self.outcome = RunOutcome(payload.get("outcome") or self.derive_outcome())
        self.updated_at = event.at
        return self

    def _add_cost(self, amount: float, by_model: Any) -> None:
        self.costs.actual_usd = round(self.costs.actual_usd + amount, 10)
        if isinstance(by_model, dict):
            for model, value in by_model.items():
                self.costs.by_model[str(model)] = round(
                    self.costs.by_model.get(str(model), 0.0) + float(value), 10
                )

    def derive_outcome(self) -> RunOutcome:
        statuses = {record.status for record in self.cells.values()}
        if not statuses:
            return RunOutcome.PENDING
        if statuses == {CellStatus.DRY_RUN}:
            return RunOutcome.DRY_RUN
        if CellStatus.FAILED in statuses:
            done = statuses & {CellStatus.SUCCEEDED, CellStatus.DRY_RUN}
            return RunOutcome.PARTIAL if done else RunOutcome.FAILED
        if statuses & {CellStatus.PENDING, CellStatus.RUNNING}:
            return RunOutcome.RUNNING
        return RunOutcome.SUCCEEDED

    @classmethod
    def replay(cls, base: RunManifest, events: list[RunEvent]) -> RunManifest:
        manifest = base.model_copy(deep=True)
        for event in events:
            manifest.apply(event)
        return manifest

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)
