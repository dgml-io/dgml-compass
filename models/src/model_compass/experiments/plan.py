"""A spec turned into a priced, reviewable plan, before anything is spent.

- **What will run.** Cells and draws, with every dropped docset or finished cell named and why.
- **What it costs.** Priced by :mod:`model_compass.pricing` from the ``prices_file`` setting
  (``conf/prices.yaml``); the prices travel with the run as ``prices.json``. An unpriced model is
  named, never priced at zero.
- **What is already done.** On resume a draw is complete only if its ``status.json`` says so
  *and* its ``result.json`` exists; ``retry_empty`` also re-runs succeeded draws with no DGML.

:meth:`RunPlan.to_manifest` is where a run's record (:mod:`model_compass.experiments.manifest`)
starts, and :mod:`model_compass.experiments.run` folds events into it.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, ConfigDict, Field

from model_compass.corpus.sampling import documents_per_draw
from model_compass.domain import MetricFamily, ModelSlot
from model_compass.errors import ConfigError
from model_compass.experiments.cells import Cell, Draw, expand_cells, expand_draws
from model_compass.experiments.manifest import (
    SCHEMA_VERSION,
    CellRecord,
    CellStatus,
    Costs,
    EnvironmentInfo,
    Provenance,
    RunManifest,
    RunOutcome,
)
from model_compass.experiments.spec import ExperimentSpec
from model_compass.ids import RUN_ID_TIMESTAMP_FORMAT
from model_compass.ids import run_id as make_run_id
from model_compass.pricing import (
    CostEstimate,
    ModelPrice,
    estimate_generation,
    estimate_seconds,
    settings_prices,
)
from model_compass.runs import RESULT_FILENAME, artifact_prefix, draw_subdir

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from model_compass.config import Settings
    from model_compass.corpus.models import Corpus, Docset

log = logging.getLogger(__name__)

STATUS_FILENAME: Final[str] = "status.json"
CELLS_FILENAME: Final[str] = "cells.json"
CREDENTIAL_ENV_NAMES: Final[tuple[str, ...]] = (
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
)

# -- the plan ----------------------------------------------------------------------------


def cell_dir(run_dir: Path, cell_id: str) -> Path:
    return run_dir / artifact_prefix(cell_id)


def draw_dir(run_dir: Path, cell_id: str, index: int, *, draws: int) -> Path:
    """A single-draw cell keeps the flat ``cells/<id>/`` layout; otherwise ``draws/<NN>/``."""
    base = cell_dir(run_dir, cell_id)
    return base if draws <= 1 else draw_subdir(base, index)


def read_status(directory: Path) -> dict[str, Any] | None:
    try:
        status = json.loads((directory / STATUS_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return status if isinstance(status, dict) else None


def is_complete(
    directory: Path, *, accept_dry_run: bool = True, retry_empty: bool = False
) -> bool:
    """Done means ``status.json`` says so AND ``result.json`` exists. A ``dry_run`` status is
    evidence only to another dry run; under ``retry_empty`` a succeeded draw with documents but
    no DGML is not done either."""
    if not (directory / RESULT_FILENAME).is_file():
        return False
    status = read_status(directory)
    if status is None:
        return False
    accepted = (
        (CellStatus.SUCCEEDED, CellStatus.DRY_RUN) if accept_dry_run else (CellStatus.SUCCEEDED,)
    )
    if status.get("status") not in accepted:
        return False
    return not (
        retry_empty
        and status.get("status") == CellStatus.SUCCEEDED
        and int(status.get("n_documents") or 0) > 0
        and int(status.get("n_with_xml") or 0) == 0
    )


def recorded_cost(directory: Path) -> float | None:
    status = read_status(directory)
    if status is None or status.get("cost_usd") is None:
        return None
    try:
        return float(status["cost_usd"])
    except (TypeError, ValueError):
        return None


def write_cells(run_dir: Path, cells: list[Cell]) -> Path:
    """Merge into ``cells.json``: a resumed run plans only incomplete cells, and the finished
    ones must stay describable."""
    path = run_dir / CELLS_FILENAME
    existing: dict[str, Any] = {}
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        existing = loaded if isinstance(loaded, dict) else {}
    for cell in cells:
        existing[cell.cell_id] = cell.model_dump(mode="json")
    _write(path, json.dumps(dict(sorted(existing.items())), indent=2) + "\n")
    return path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class DropReason(StrEnum):
    ALREADY_COMPLETE = "already_complete"
    NO_GOLD = "no_gold"
    UNMAPPED_SHAPE = "unmapped_shape"
    NO_DOCUMENTS = "no_documents"


class DroppedCell(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cell_id: str
    ref: str
    reason: DropReason
    detail: str = ""
    draws_total: int = 0
    cost_usd: float = 0.0


class CellPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = SCHEMA_VERSION
    cell: Cell
    draws: tuple[Draw, ...] = ()
    """The draws to execute; on resume only the incomplete ones."""
    draws_done: int = 0
    n_documents: int = 0
    """Documents one draw generates."""
    estimate: CostEstimate = CostEstimate()
    """The cost of ONE draw."""
    seconds: float = 0.0

    @property
    def cell_id(self) -> str:
        return self.cell.cell_id

    @property
    def draws_total(self) -> int:
        return len(self.draws) + self.draws_done

    @property
    def estimated_usd(self) -> float:
        return round(self.estimate.usd * max(1, len(self.draws)), 6)


class RunPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = SCHEMA_VERSION
    run_id: str
    spec: ExperimentSpec
    cells: tuple[CellPlan, ...] = ()
    dropped: tuple[DroppedCell, ...] = ()
    provenance: Provenance
    environment: EnvironmentInfo
    budget_usd: float
    max_parallel_cells: int = 1
    prices: dict[str, ModelPrice] = Field(default_factory=dict)

    @property
    def n_documents(self) -> int:
        return sum(item.n_documents for item in self.cells)

    @property
    def n_draws(self) -> int:
        return sum(max(1, len(item.draws)) for item in self.cells)

    @property
    def n_document_runs(self) -> int:
        return sum(item.n_documents * max(1, len(item.draws)) for item in self.cells)

    @property
    def estimated_usd(self) -> float:
        return round(sum(item.estimated_usd for item in self.cells), 6)

    @property
    def estimated_seconds(self) -> float:
        serial = sum(item.seconds for item in self.cells)
        return round(serial / max(1, self.max_parallel_cells), 1)

    @property
    def unpriced_models(self) -> tuple[str, ...]:
        return tuple(sorted({m for item in self.cells for m in item.estimate.unpriced_models}))

    @property
    def headroom_usd(self) -> float:
        return round(self.budget_usd - self.estimated_usd, 6)

    @property
    def within_budget(self) -> bool:
        return self.estimated_usd <= self.budget_usd

    @property
    def created_at(self) -> datetime:
        """From the run id, not the clock, so replaying the log onto a fresh base reproduces
        the live manifest exactly."""
        stamp, _, _ = self.run_id.rpartition("-")
        try:
            return datetime.strptime(stamp, RUN_ID_TIMESTAMP_FORMAT).replace(tzinfo=UTC)
        except ValueError:
            return datetime.fromtimestamp(0, tz=UTC)

    @property
    def already_complete(self) -> tuple[DroppedCell, ...]:
        return tuple(
            d for d in self.dropped if d.cell_id and d.reason is DropReason.ALREADY_COMPLETE
        )

    def to_manifest(self) -> RunManifest:
        """Planned cells pending, plus every cell a resume found complete, recorded as
        succeeded with its cost, so scoring sees the whole run."""
        cells = {
            item.cell_id: CellRecord(
                cell_id=item.cell_id,
                draws_total=max(1, item.draws_total),
                draws_completed=item.draws_done,
            )
            for item in self.cells
        }
        for done in self.already_complete:
            cells[done.cell_id] = CellRecord(
                cell_id=done.cell_id,
                status=CellStatus.SUCCEEDED,
                draws_total=max(1, done.draws_total),
                draws_completed=max(1, done.draws_total),
                cost_usd=done.cost_usd,
                artifact_prefix=artifact_prefix(done.cell_id),
            )
        return RunManifest(
            run_id=self.run_id,
            created_at=self.created_at,
            updated_at=self.created_at,
            spec=self.spec,
            provenance=self.provenance,
            environment=self.environment,
            cells=dict(sorted(cells.items())),
            costs=Costs(actual_usd=round(sum(d.cost_usd for d in self.already_complete), 10)),
            outcome=RunOutcome.PENDING,
        )

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    def render(self) -> str:
        """The plan as a plain-text table, totals and drops."""
        rows = [("cell_id", "docset", "shape", "docs/draw", "draws", "models", "est. $")]
        for item in self.cells:
            cell = item.cell
            models = ", ".join(
                f"{key.rsplit('.', 1)[-1]}={value}"
                for key, value in sorted(cell.settings_dict.items())
                if key.endswith("model")
            )
            draws = str(len(item.draws))
            if item.draws_done:
                draws += f" (+{item.draws_done} done)"
            rows.append(
                (
                    cell.cell_id,
                    cell.ref,
                    cell.shape or "-",
                    str(item.n_documents),
                    draws,
                    models or "-",
                    f"{item.estimated_usd:,.4f}",
                )
            )
        widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
        lines = [f"{self.spec.name}  ({self.run_id})"]
        lines += ["  ".join(v.ljust(w) for v, w in zip(row, widths, strict=True)) for row in rows]
        lines.append(
            f"{len(self.cells)} cells x {self.spec.draws} draw(s) over "
            f"{len({item.cell.ref for item in self.cells})} docsets = {self.n_document_runs} "
            f"document-runs ({self.n_draws} draws to execute, "
            f"{self.spec.corpus.sampling.value} document sampling)"
        )
        headroom = f"${self.headroom_usd:,.2f} headroom" if self.within_budget else "OVER BUDGET"
        lines.append(
            f"estimated ${self.estimated_usd:,.2f} against a ${self.budget_usd:,.2f} budget "
            f"({headroom}), ~{self.estimated_seconds / 3600:,.1f}h wall clock at "
            f"{self.max_parallel_cells}x concurrency"
        )
        if self.unpriced_models:
            lines.append(
                f"{len(self.unpriced_models)} model(s) have no price in the price list, so the "
                f"estimate is a floor: {', '.join(self.unpriced_models)}"
            )
        for entry in self.dropped:
            lines.append(
                f"not run: {entry.cell_id or entry.ref}  {entry.reason.value}  {entry.detail}"
            )
        if self.provenance.any_dirty:
            dirty = ", ".join(n for n, r in self.provenance.repos.items() if r.dirty)
            lines.append(f"uncommitted changes in: {dirty}")
        return "\n".join(lines)


def _reject(spec: ExperimentSpec, docset: Docset) -> tuple[DropReason, str] | None:
    if not docset.documents:
        return DropReason.NO_DOCUMENTS, "the docset directory holds no selected documents"
    if MetricFamily.EXTRACTION in spec.metrics and spec.corpus.require_gold and not docset.has_gold:
        return DropReason.NO_GOLD, "extraction metrics were requested but this docset has no gold"
    if spec.corpus.shapes and docset.shape is None:
        return DropReason.UNMAPPED_SHAPE, "the spec filters by shape and this docset has none"
    return None


def plan(
    spec: ExperimentSpec,
    settings: Settings,
    corpus: Corpus,
    *,
    prices: Mapping[str, ModelPrice] | None = None,
    provenance: Provenance | None = None,
    resume_run_id: str | None = None,
    retry_empty: bool = False,
    dry_run: bool = False,
    budget_usd: float | None = None,
    now: datetime | None = None,
) -> RunPlan:
    """Expand, filter, price and (on resume) subtract finished draws. Reads, never writes.

    ``prices`` default to the ``prices_file`` setting. ``budget_usd`` (the CLI's
    ``--budget-usd``) wins over the spec's, which wins over the settings default.
    """
    from model_compass.scoring import resolve_families

    resolve_families(spec.metrics)  # fail now, not after a paid sweep
    runnable: list[Docset] = []
    dropped: list[DroppedCell] = []
    for docset in corpus.docsets:
        if (reason := _reject(spec, docset)) is not None:
            dropped.append(
                DroppedCell(cell_id="", ref=docset.ref, reason=reason[0], detail=reason[1])
            )
        else:
            runnable.append(docset)
    if not runnable:
        raise ConfigError(
            f"experiment {spec.name!r} selects no runnable docsets; "
            + "; ".join(f"{item.ref}: {item.detail}" for item in dropped[:3]),
            code="empty_selection",
        )
    priced = dict(settings_prices(settings) if prices is None else prices)
    documents = {d.ref: documents_per_draw(d, spec.corpus) for d in corpus.docsets}
    planned: list[CellPlan] = []
    for cell in expand_cells(spec, runnable):
        n_documents = documents.get(cell.ref, 0)
        planned.append(
            CellPlan(
                cell=cell,
                draws=expand_draws(cell),
                n_documents=n_documents,
                estimate=estimate_generation(
                    n_documents=n_documents,
                    generation_model=cell.model_for(ModelSlot.GENERATION),
                    label_model=cell.model_for(ModelSlot.LABEL),
                    prices=priced,
                ),
                seconds=estimate_seconds(n_documents=n_documents, draws=spec.draws),
            )
        )

    fingerprint = provenance.model_dump(mode="json") if provenance else {}
    identifier = resume_run_id or make_run_id(spec.model_dump(mode="json"), fingerprint, now=now)
    if resume_run_id:
        planned, skipped = _resume(
            planned,
            settings.runs_dir / resume_run_id,
            accept_dry_run=dry_run,
            retry_empty=retry_empty,
        )
        dropped.extend(skipped)

    if budget_usd is None:
        budget_usd = spec.budget_usd if spec.budget_usd is not None else settings.budget_usd
    environment = EnvironmentInfo(
        executor="local",
        storage_uri=str(settings.runs_dir),
        max_parallel_cells=settings.max_parallel_cells,
        max_parallel_calls=settings.max_parallel_calls,
        budget_usd=budget_usd,
        dry_run=dry_run,
        model_ids=tuple(sorted({m for item in planned for m in item.cell.models})),
        credential_env_names_present=tuple(n for n in CREDENTIAL_ENV_NAMES if os.environ.get(n)),
    )
    return RunPlan(
        run_id=identifier,
        spec=spec,
        cells=tuple(planned),
        dropped=tuple(dropped),
        provenance=provenance or Provenance(python_version="", package_version=""),
        environment=environment,
        budget_usd=budget_usd,
        max_parallel_cells=settings.max_parallel_cells,
        prices=priced,
    )


def _resume(
    planned: list[CellPlan], run_dir: Path, *, accept_dry_run: bool, retry_empty: bool
) -> tuple[list[CellPlan], list[DroppedCell]]:
    def done(directory: Path) -> bool:
        return is_complete(directory, accept_dry_run=accept_dry_run, retry_empty=retry_empty)

    remaining: list[CellPlan] = []
    skipped: list[DroppedCell] = []
    for item in planned:
        total = len(item.draws)
        base = cell_dir(run_dir, item.cell_id)
        if total > 1 and done(base):
            # flat artifacts under a multi-draw cell come from the flat layout: one execution
            # stands for the whole cell, and re-running its draws would pay again
            skipped.append(
                DroppedCell(
                    cell_id=item.cell_id,
                    ref=item.cell.ref,
                    reason=DropReason.ALREADY_COMPLETE,
                    detail="status.json says succeeded and result.json is present (flat layout)",
                    draws_total=total,
                    cost_usd=recorded_cost(base) or 0.0,
                )
            )
            continue
        pending = tuple(
            draw
            for draw in item.draws
            if not done(draw_dir(run_dir, item.cell_id, draw.index, draws=total))
        )
        if pending:
            remaining.append(
                item.model_copy(update={"draws": pending, "draws_done": total - len(pending)})
            )
            continue
        cost = recorded_cost(base)
        if total > 1 and cost is None:
            cost = sum(
                recorded_cost(draw_dir(run_dir, item.cell_id, d.index, draws=total)) or 0.0
                for d in item.draws
            )
        skipped.append(
            DroppedCell(
                cell_id=item.cell_id,
                ref=item.cell.ref,
                reason=DropReason.ALREADY_COMPLETE,
                detail=(
                    "status.json says succeeded and result.json is present"
                    if total <= 1
                    else f"all {total} draws have a succeeded status.json and a result.json"
                ),
                draws_total=max(1, total),
                cost_usd=round(cost or 0.0, 10),
            )
        )
    log.info("resume planned: %d to run, %d complete", len(remaining), len(skipped))
    return remaining, skipped
