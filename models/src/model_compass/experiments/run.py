"""Executing a plan locally, and leaving a record that can be trusted afterwards.

The draw is the unit of execution (DECISIONS 0017): each builds its own workspace over its own
document sample from its cell's docset only (DECISIONS 0015) and writes under
``cells/<cell_id>/[draws/NN/]``. Draws run in a bounded thread pool (``pool.py``); each is
rate limited per provider and reserves its estimate against the budget before it starts, then
settles on its measured cost (DECISIONS 0016). A reservation that would pass the cap stops
submission: in-flight draws finish, the rest are cancelled, and the run ends ``budget_aborted``.

Every state change is appended to ``events.jsonl`` and folded into ``manifest.json``;
replaying the log onto the plan's manifest reproduces it. A failed draw fails its cell and the
run carries on (``partial``). Ctrl-C stops submission the same way a budget breach does.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from model_compass.corpus.loader import load_checked_corpus
from model_compass.corpus.sampling import draw_corpus
from model_compass.domain import ModelSlot
from model_compass.engine.dgml_cli import DgmlCli
from model_compass.engine.generate import DrawResult, generate
from model_compass.engine.workspace import build_workspace, plan_only
from model_compass.errors import BudgetExceeded, ConfigError, EngineError
from model_compass.experiments.manifest import (
    CellStatus,
    EventKind,
    RunEvent,
    RunManifest,
    RunOutcome,
)
from model_compass.experiments.plan import (
    STATUS_FILENAME,
    DropReason,
    cell_dir,
    draw_dir,
    plan,
    read_status,
    write_cells,
)
from model_compass.experiments.pool import (
    BudgetGuard,
    Outcome,
    Pool,
    RateLimiter,
    Task,
    provider_of,
)
from model_compass.experiments.provenance import (
    capture_provenance,
    corpus_fingerprint,
    require_clean_corpus,
)
from model_compass.experiments.spec import dump_spec
from model_compass.pricing import write_run_prices
from model_compass.runs import (
    MANIFEST_FILENAME,
    RESULT_FILENAME,
    SIDECAR_FILENAME,
    artifact_prefix,
    draw_subdir,
)

if TYPE_CHECKING:
    from model_compass.config import Settings
    from model_compass.corpus.models import Corpus
    from model_compass.experiments.cells import Cell, Draw
    from model_compass.experiments.plan import CellPlan, RunPlan
    from model_compass.experiments.spec import ExperimentSpec
    from model_compass.pricing import ModelPrice

log = logging.getLogger(__name__)

EVENTS_FILENAME: Final[str] = "events.jsonl"
SPEC_FILENAME: Final[str] = "spec.resolved.yaml"
GENERATION_FAILED_CODE: Final[str] = "generation_failed"

DgmlFactory = Callable[["Cell", Path], DgmlCli]
"""Builds the dgml client for one draw's workspace; tests inject a double."""


# -- the record --------------------------------------------------------------------------


class _Recorder:
    """Appends to ``events.jsonl``, folds into the manifest, flushes both after every event.

    The log is rewritten whole on each append, so a run killed between events leaves a
    parseable file (the write is not atomic: a kill mid-write can truncate it).
    It starts empty: a resumed run's log holds only that invocation's events.
    """

    def __init__(self, run_dir: Path, manifest: RunManifest) -> None:
        self._run_dir = run_dir
        self.manifest = manifest
        self.events: list[RunEvent] = []
        self._lock = threading.Lock()

    def record(self, kind: EventKind, *, cell_id: str | None = None, **payload: Any) -> None:
        event = RunEvent(kind=kind, cell_id=cell_id, payload=payload)
        with self._lock:
            self.events.append(event)
            (self._run_dir / EVENTS_FILENAME).write_text(
                "".join(item.model_dump_json() + "\n" for item in self.events), encoding="utf-8"
            )
            self.manifest.apply(event)
            (self._run_dir / MANIFEST_FILENAME).write_text(
                self.manifest.to_json(), encoding="utf-8"
            )


def read_events(run_dir: Path) -> list[RunEvent]:
    path = run_dir / EVENTS_FILENAME
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [RunEvent.model_validate_json(line) for line in lines if line.strip()]


# -- one draw --------------------------------------------------------------------------------


def draw_workspace(work_root: Path, cell_id: str, draw_index: int, *, draws: int) -> Path:
    base = work_root / cell_id
    if draws > 1:
        base = draw_subdir(base, draw_index)
    return base / "workspace"


def draw_status(result: DrawResult) -> CellStatus:
    """``failed`` only when dgml reported every document failed and none has DGML. A draw with
    some DGML stays ``succeeded`` (``missing_dgml_rate`` reports it), as does one whose
    documents are ``not_reported`` (a delivery defect, not a generation failure)."""
    if result.dry_run:
        return CellStatus.DRY_RUN
    if (
        result.documents
        and result.n_with_xml == 0
        and all(document.status == "failed" for document in result.documents)
    ):
        return CellStatus.FAILED
    return CellStatus.SUCCEEDED


def generation_failure(result: DrawResult) -> EngineError:
    """The error a draw with nothing generated fails with: its documents' commonest code."""
    codes: dict[str, int] = {}
    message = ""
    for document in result.documents:
        code = document.error_code or "unknown"
        codes[code] = codes.get(code, 0) + 1
        message = message or document.error_message or ""
    for outcome in result.docsets:
        message = message or outcome.error_message or ""
    dominant = max(codes, key=lambda c: (codes[c], c)) if codes else "unknown"
    n = len(result.documents)
    return EngineError(
        f"no DGML for any of {n} document(s): {dominant} x{codes.get(dominant, 0)}"
        + (f" -- {message[:500]}" if message else ""),
        code=GENERATION_FAILED_CODE,
        cell_id=result.cell_id,
        draw_index=result.draw_index,
        document_error_code=dominant,
        document_error_codes=codes,
        n_documents=n,
        cost_usd=result.cost_usd,
    )


def persist_draw(
    directory: Path, cell_id: str, result: DrawResult, status: CellStatus
) -> Path:
    """result.json, usage.jsonl, dgml/<xml_path>, then status.json -- last, because it plus
    result.json is what marks the draw complete."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / RESULT_FILENAME).write_text(result.model_dump_json(indent=2), encoding="utf-8")
    workspace = Path(result.workspace)
    if result.usage.present and (workspace / "usage.jsonl").is_file():
        shutil.copyfile(workspace / "usage.jsonl", directory / "usage.jsonl")
    for document in result.documents:
        if document.xml_path and (workspace / document.xml_path).is_file():
            target = directory / "dgml" / document.xml_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(workspace / document.xml_path, target)
    status_json = {
        "cell_id": cell_id,
        "draw_index": result.draw_index,
        "status": status,
        "n_documents": len(result.documents),
        "n_with_xml": result.n_with_xml,
        "missing_dgml_rate": round(result.missing_dgml_rate, 6),
        "cost_usd": result.cost_usd,
        "cost_partial": result.usage.cost_partial,
        "warnings": list(result.warnings),
    }
    (directory / STATUS_FILENAME).write_text(
        json.dumps(status_json, indent=2, sort_keys=True), encoding="utf-8"
    )
    return directory


def write_cell_summary(run_dir: Path, cell_id: str, *, draws: int) -> Path | None:
    """Roll a multi-draw cell's draw statuses up into ``cells/<id>/status.json`` once every
    draw has succeeded."""
    if draws <= 1:
        return None
    statuses = []
    for index in range(draws):
        status = read_status(draw_dir(run_dir, cell_id, index, draws=draws))
        if status is None or status.get("status") not in (CellStatus.SUCCEEDED, CellStatus.DRY_RUN):
            return None
        statuses.append(status)
    n_documents = sum(int(item.get("n_documents", 0)) for item in statuses)
    n_with_xml = sum(int(item.get("n_with_xml", 0)) for item in statuses)
    summary = {
        "cell_id": cell_id,
        "status": (
            CellStatus.DRY_RUN
            if all(s.get("status") == CellStatus.DRY_RUN for s in statuses)
            else CellStatus.SUCCEEDED
        ),
        "draws_total": draws,
        "draws_completed": len(statuses),
        "n_documents": n_documents,
        "n_with_xml": n_with_xml,
        "missing_dgml_rate": round(1.0 - n_with_xml / n_documents, 6) if n_documents else 0.0,
        "cost_usd": round(sum(float(item.get("cost_usd", 0.0)) for item in statuses), 10),
        "cost_partial": any(bool(item.get("cost_partial")) for item in statuses),
        "warnings": [w for item in statuses for w in item.get("warnings", [])],
    }
    path = cell_dir(run_dir, cell_id) / STATUS_FILENAME
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _draw_task(
    item: CellPlan,
    draw: Draw,
    *,
    spec: ExperimentSpec,
    corpus: Corpus,
    settings: Settings,
    run_dir: Path,
    work_root: Path,
    prices: dict[str, ModelPrice],
    dry_run: bool,
    started: Callable[[str], None],
    dgml_client: DgmlFactory | None,
) -> Task:
    cell = item.cell
    draws = max(1, item.draws_total)
    sampled = draw_corpus(corpus, cell, spec, draw.index)
    directory = draw_dir(run_dir, cell.cell_id, draw.index, draws=draws)
    workspace = draw_workspace(work_root, cell.cell_id, draw.index, draws=draws)

    def call() -> float:
        started(cell.cell_id)
        if dry_run:
            planned = plan_only(cell, sampled, workspace, draw_index=draw.index)
            # the documents this draw WOULD generate: what a later real run must reproduce
            sidecar = directory / "workspace" / SIDECAR_FILENAME
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            sidecar.write_text(planned.to_json(), encoding="utf-8")
            result = generate(
                cell, planned, None, dry_run=True, prices=prices, draw_index=draw.index
            )
            persist_draw(directory, cell.cell_id, result, CellStatus.DRY_RUN)
            return 0.0
        workspace.mkdir(parents=True, exist_ok=True)
        cli = (
            dgml_client(cell, workspace)
            if dgml_client is not None
            else DgmlCli(
                workspace=workspace,
                repo_root=settings.dgml_repo if settings.dgml_repo.is_dir() else None,
                log_dir=directory / "logs",
            )
        )
        built = build_workspace(cell, sampled, cli, artifact_dir=directory, draw_index=draw.index)
        result = generate(
            cell,
            built,
            cli,
            max_parallel_calls=settings.max_parallel_calls,
            draw_index=draw.index,
        )
        status = draw_status(result)
        persist_draw(directory, cell.cell_id, result, status)  # the evidence, either way
        if status is CellStatus.FAILED:
            raise generation_failure(result)
        return result.usage.total_cost_usd

    return Task(
        cell_id=cell.cell_id,
        draw_index=draw.index if draws > 1 else None,
        call=call,
        # a dry run reserves nothing: it spends nothing, and the plan reports the projection
        estimated_usd=0.0 if dry_run else item.estimate.usd,
        provider=None if dry_run else provider_of(cell.model_for(ModelSlot.GENERATION)),
    )


# -- the run ---------------------------------------------------------------------------------


def execute(
    built: RunPlan,
    settings: Settings,
    corpus: Corpus,
    *,
    dry_run: bool = False,
    dgml_client: DgmlFactory | None = None,
    limiter: RateLimiter | None = None,
) -> RunManifest:
    """Run a plan. Returns the manifest whatever the outcome, including a bad one."""
    run_dir = settings.runs_dir / built.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = built.to_manifest()
    (run_dir / SPEC_FILENAME).write_text(dump_spec(built.spec), encoding="utf-8")
    (run_dir / MANIFEST_FILENAME).write_text(manifest.to_json(), encoding="utf-8")
    write_cells(run_dir, [item.cell for item in built.cells])
    write_run_prices(
        run_dir,
        built.prices,
        source=str(settings.prices_file),
        version=manifest.provenance.prices_version,
    )
    recorder = _Recorder(run_dir, manifest)
    recorder.record(EventKind.RUN_STARTED, estimated_usd=built.estimated_usd)

    seen: set[str] = set()
    seen_lock = threading.Lock()

    def started(cell_id: str) -> None:
        with seen_lock:
            if cell_id in seen:
                return
            seen.add(cell_id)
        recorder.record(EventKind.CELL_STARTED, cell_id=cell_id)

    work_root = settings.work_dir / built.run_id
    tasks = [
        _draw_task(
            item,
            draw,
            spec=built.spec,
            corpus=corpus,
            settings=settings,
            run_dir=run_dir,
            work_root=work_root,
            prices=built.prices,
            dry_run=dry_run,
            started=started,
            dgml_client=dgml_client,
        )
        for item in built.cells
        for draw in item.draws
    ]
    for dropped in built.dropped:
        if dropped.reason is not DropReason.ALREADY_COMPLETE and dropped.cell_id in manifest.cells:
            recorder.record(
                EventKind.CELL_SKIPPED, cell_id=dropped.cell_id, reason=dropped.reason.value
            )
    draws_of = {item.cell_id: max(1, item.draws_total) for item in built.cells}
    pool = Pool(
        workers=settings.max_parallel_cells,
        budget=BudgetGuard(built.budget_usd),
        limiter=limiter or RateLimiter(),
    )
    breach: BudgetExceeded | None = None
    try:
        for outcome in pool.submit(tasks):
            _record(recorder, outcome, dry_run=dry_run)
            if outcome.status is CellStatus.SUCCEEDED and outcome.task.draw_index is not None:
                write_cell_summary(
                    run_dir, outcome.task.cell_id, draws=draws_of[outcome.task.cell_id]
                )
    except BudgetExceeded as exc:
        breach = exc
        log.warning("run %s budget aborted: %s", built.run_id, exc.message)
        recorder.record(
            EventKind.RUN_ABORTED,
            reason=RunOutcome.BUDGET_ABORTED.value,
            projected_usd=exc.context.get("projected_usd"),
            actual_usd=exc.context.get("actual_usd"),
        )
    outcome = RunOutcome.BUDGET_ABORTED if breach else recorder.manifest.derive_outcome()
    recorder.record(EventKind.RUN_FINISHED, outcome=outcome.value)
    return recorder.manifest


def _record(recorder: _Recorder, outcome: Outcome, *, dry_run: bool) -> None:
    task = outcome.task
    per_draw: dict[str, Any] = {} if task.draw_index is None else {"draw_index": task.draw_index}
    if outcome.status is CellStatus.SUCCEEDED:
        recorder.record(
            EventKind.CELL_SUCCEEDED,
            cell_id=task.cell_id,
            cost_usd=outcome.cost_usd or 0.0,
            dry_run=dry_run,
            artifact_prefix=artifact_prefix(task.cell_id),
            **per_draw,
        )
    elif outcome.status is CellStatus.CANCELLED:
        recorder.record(
            EventKind.CELL_SKIPPED,
            cell_id=task.cell_id,
            reason=outcome.error_code or "cancelled",
            **per_draw,
        )
    else:
        recorder.record(
            EventKind.CELL_FAILED,
            cell_id=task.cell_id,
            code=outcome.error_code or "task_failed",
            message=outcome.error_message or "",
            cost_usd=outcome.cost_usd or 0.0,
            **per_draw,
        )


def run(
    spec: ExperimentSpec,
    settings: Settings,
    *,
    dry_run: bool = False,
    resume_run_id: str | None = None,
    retry_empty: bool = False,
    yes: bool = False,
    budget_usd: float | None = None,
    dgml_client: DgmlFactory | None = None,
    corpus: Corpus | None = None,
    prices: dict[str, ModelPrice] | None = None,
    allow_dirty_corpus: bool = False,
) -> RunManifest:
    """Plan and execute ``spec``. A paid run needs ``yes=True`` (the CLI's confirmation);
    ``dry_run`` writes the whole run directory with estimates and calls nothing paid."""
    corpus = corpus if corpus is not None else load_checked_corpus(spec, settings)
    provenance = capture_provenance(settings, corpus_hash=corpus_fingerprint(corpus))
    require_clean_corpus(provenance, allow_dirty=allow_dirty_corpus)
    built = plan(
        spec,
        settings,
        corpus,
        prices=prices,
        provenance=provenance,
        resume_run_id=resume_run_id,
        retry_empty=retry_empty,
        dry_run=dry_run,
        budget_usd=budget_usd,
    )
    if not dry_run and not yes:
        raise ConfigError(
            f"run {built.run_id} would spend up to ${built.estimated_usd:,.2f} "
            f"(cap ${built.budget_usd:,.2f}); confirm it, or dry-run it first",
            code="confirmation_required",
            estimated_usd=built.estimated_usd,
        )
    return execute(built, settings, corpus, dry_run=dry_run, dgml_client=dgml_client)
