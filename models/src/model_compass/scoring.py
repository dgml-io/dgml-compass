"""``dgc score``: a run's stored artifacts in, ``metrics/<cell_id>.jsonl`` out.

- Nothing is scored that cannot be joined to gold: a draw without its sidecar is skipped and
  named, not scored on a guess. A dry-run draw is never scored.
- Every draw is scored on its own and its records carry its index.
- Under random sampling the corpus keeps the whole docset, so each draw is narrowed to the
  documents its sidecar lists before gold is built.
- Extraction runs first: economics reads its ``individual_overlap_f1``.
- ``workers > 1`` scores cells in processes; output is identical to a serial run.
- ``resume`` keeps a cell whose metrics file already covers every draw and family.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from multiprocessing import get_context
from pathlib import Path
from typing import TYPE_CHECKING

from model_compass.domain import SCORED_FAMILIES, MetricFamily
from model_compass.errors import CompassError, ConfigError
from model_compass.metrics.dgml_xml import UnparseableDocument, parse_dgml_bytes
from model_compass.metrics.families import FAMILIES, CellInputs, DocsetArtifacts
from model_compass.metrics.predictions import predictions_for_documents
from model_compass.records import MetricRecord
from model_compass.runs import (
    draw_dirs,
    load_cells,
    load_manifest,
    load_result,
    load_sidecar,
    locate_workspace,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from xml.etree import ElementTree

    from model_compass.corpus.models import Corpus, Docset
    from model_compass.domain import AxisValue
    from model_compass.runs import StoredDrawResult, StoredWorkspaceEntry, StoredWorkspacePlan


@dataclass(frozen=True)
class CellScore:
    cell_id: str
    scored: bool
    draws: int = 0
    draws_scored: int = 0
    records: int = 0
    reason: str | None = None
    warnings: tuple[str, ...] = ()
    kept: bool = False


@dataclass
class ScoreResult:
    run_id: str
    families: tuple[MetricFamily, ...]
    cells: list[CellScore] = field(default_factory=list)

    @property
    def scored(self) -> list[CellScore]:
        return [c for c in self.cells if c.scored]


def resolve_families(requested: Sequence[MetricFamily | str]) -> tuple[MetricFamily, ...]:
    chosen = []
    for item in requested:
        try:
            family = MetricFamily(item)
        except ValueError:
            family = None
        if family not in FAMILIES:
            known = ", ".join(f.value for f in SCORED_FAMILIES)
            raise ConfigError(
                f"cannot score family {item!r}; scorable: {known}", code="metric_family_unknown"
            )
        chosen.append(family)
    return tuple(chosen)


def _entries_of(plan: StoredWorkspacePlan, docset: Docset) -> list[StoredWorkspaceEntry]:
    return [e for e in plan.entries if e.org == docset.org and e.docset_id == docset.docset_id]


def _documents_of_draw(docset: Docset, plan: StoredWorkspacePlan) -> Docset:
    """The docset narrowed to the documents this draw generated. A sidecar naming none of the
    docset's documents leaves it whole."""
    entries = _entries_of(plan, docset)
    if not entries:
        return docset
    names = {e.name for e in entries}
    file_ids = {e.corpus_file_id for e in entries if e.corpus_file_id}
    kept = tuple(
        d for d in docset.documents if d.name in names or (d.file_id and d.file_id in file_ids)
    )
    if len(kept) == len(docset.documents):
        return docset
    return docset.model_copy(update={"documents": kept})


def _artifacts_for(
    draw_dir: Path,
    workspace: Path | None,
    result: StoredDrawResult,
    plan: StoredWorkspacePlan,
    docset: Docset,
) -> tuple[DocsetArtifacts, list[str]]:
    mine = _entries_of(plan, docset)
    corpus_id_for = {e.dgml_file_id: e.corpus_file_id for e in mine if e.joinable}
    roots: list[tuple[str, ElementTree.Element]] = []
    unjoinable = unreadable = 0
    for document in result.documents:
        if document.docset_id != docset.docset_id or document.org != docset.org:
            continue
        if not document.produced_xml or not document.xml_path:
            continue
        corpus_id = document.corpus_file_id or corpus_id_for.get(document.dgml_file_id)
        if not corpus_id:
            unjoinable += 1
            continue
        # the copy persisted in the run directory first (it survives a cleaned or re-run
        # scratch workspace), the workspace copy second; only result.json's documents, unlike
        # CellInputs.workspace_docset, which globs whatever DGML the workspace holds
        candidates = [draw_dir / "dgml" / document.xml_path]
        if workspace is not None:
            candidates.append(workspace / document.xml_path)
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            unreadable += 1
            continue
        try:
            roots.append((corpus_id, parse_dgml_bytes(path.read_bytes(), source=document.xml_path)))
        except UnparseableDocument:
            unreadable += 1
    warnings = []
    if unjoinable:
        warnings.append(f"unjoinable_documents:{unjoinable}")
    if unreadable:
        warnings.append(f"unreadable_dgml:{unreadable}")
    artifacts = DocsetArtifacts(
        predictions=predictions_for_documents(roots).by_file,
        documents_expected=len(mine),
        documents_with_dgml=len(roots),
        roots=dict(roots),
    )
    return artifacts, warnings


def score_draw(
    draw_dir: Path,
    *,
    run_id: str,
    cell_id: str,
    draw: int,
    corpus: Corpus,
    families: Sequence[MetricFamily],
    settings: dict[str, AxisValue] | None = None,
    work_dir: Path | None = None,
) -> tuple[list[MetricRecord], list[str], str | None]:
    """``(records, warnings, reason it was not scored or None)`` for one draw."""
    result = load_result(draw_dir)
    if result is None:
        return [], [], "no_result"
    if result.dry_run:
        return [], [], "dry_run"
    workspace = locate_workspace(result.workspace, work_dir, run_id)
    plan = load_sidecar(draw_dir, workspace)
    if plan is None:
        return [], [], "no_sidecar"
    by_ref = {d.ref: d for d in corpus.docsets}
    refs = sorted({f"{o.org}/{o.docset_id}" for o in result.docsets})
    docsets = [_documents_of_draw(by_ref[ref], plan) for ref in refs if ref in by_ref]
    warnings: list[str] = []
    if len(docsets) != len(refs):
        warnings.append(f"docsets_not_in_corpus:{','.join(sorted(set(refs) - set(by_ref)))}")
    if not docsets:
        return [], warnings, "no_docsets_in_corpus"
    artifacts = {}
    for docset in docsets:
        artifacts[docset.ref], notes = _artifacts_for(draw_dir, workspace, result, plan, docset)
        warnings.extend(f"{docset.ref}:{note}" for note in notes)
    inputs = CellInputs(
        run_id=run_id,
        cell_id=cell_id,
        docsets=docsets,
        draw=draw,
        workspace=workspace,
        artifacts=artifacts,
        corpus_root=Path(corpus.root),
        docset_ids=dict(plan.docset_ids),
        settings=settings or {},
    )
    if workspace is None:
        warnings.append("no_workspace")
    records: list[MetricRecord] = []
    for family in sorted(families, key=lambda f: f is not MetricFamily.EXTRACTION):
        produced = FAMILIES[family](inputs)
        records.extend(produced)
        if family is MetricFamily.EXTRACTION:
            inputs.f1_by_docset = {
                r.ref: v for r in produced if (v := r.get("individual_overlap_f1")) is not None
            }
    return records, warnings, None


def score_cell(
    run_dir: Path,
    cell_id: str,
    *,
    corpus: Corpus,
    families: Sequence[MetricFamily],
    settings: dict[str, AxisValue] | None = None,
    work_dir: Path | None = None,
) -> tuple[CellScore, list[MetricRecord]]:
    """Draw by draw; a cell is scored when at least one draw is, and skipped draws are named."""
    draws = draw_dirs(run_dir / "cells" / cell_id)
    if not draws:
        return CellScore(cell_id=cell_id, scored=False, reason="no_result"), []
    run_id = run_dir.name
    records: list[MetricRecord] = []
    warnings: list[str] = []
    reasons: list[str] = []
    for index, draw_dir in draws:
        produced, notes, reason = score_draw(
            draw_dir,
            run_id=run_id,
            cell_id=cell_id,
            draw=index,
            corpus=corpus,
            families=families,
            settings=settings,
            work_dir=work_dir,
        )
        tag = f"draw{index:02d}:" if len(draws) > 1 else ""
        warnings.extend(f"{tag}{note}" for note in notes)
        if reason is not None:
            reasons.append(reason)
            if len(draws) > 1:
                warnings.append(f"{tag}{reason}")
            continue
        records.extend(produced)
    scored = len(draws) - len(reasons)
    summary = CellScore(
        cell_id=cell_id,
        scored=scored > 0,
        draws=len(draws),
        draws_scored=scored,
        records=len(records),
        reason=None if scored else (reasons[0] if len(set(reasons)) == 1 else "no_scorable_draws"),
        warnings=tuple(warnings),
    )
    return summary, records


def _metrics_path(run_dir: Path, cell_id: str) -> Path:
    return run_dir / "metrics" / f"{cell_id}.jsonl"


def _already_scored(
    run_dir: Path, cell_id: str, families: Sequence[MetricFamily]
) -> CellScore | None:
    """Kept only when the file covers every (draw, family) wanted, for this run and cell."""
    path = _metrics_path(run_dir, cell_id)
    draws = draw_dirs(run_dir / "cells" / cell_id)
    if not path.is_file() or not draws:
        return None
    covered = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = MetricRecord.model_validate_json(line)
                if record.run_id != run_dir.name or record.cell_id != cell_id:
                    return None
                covered.add((record.draw, record.family))
    except ValueError:
        return None
    if not {(i, f) for i, _ in draws for f in families} <= covered:
        return None
    return CellScore(
        cell_id=cell_id,
        scored=True,
        kept=True,
        draws=len(draws),
        draws_scored=len(draws),
        reason="resumed",
    )


@dataclass(frozen=True)
class _ScoreJob:
    """One cell's work; module-level and frozen so it pickles into a spawned worker."""

    run_dir: Path
    cell_id: str
    corpus: Corpus
    families: tuple[MetricFamily, ...]
    settings: dict[str, AxisValue] | None
    work_dir: Path | None
    resume: bool
    dry_run: bool = False


def _score_and_write(job: _ScoreJob) -> CellScore:
    if job.resume and (kept := _already_scored(job.run_dir, job.cell_id, job.families)) is not None:
        return kept
    summary, records = score_cell(
        job.run_dir,
        job.cell_id,
        corpus=job.corpus,
        families=job.families,
        settings=job.settings,
        work_dir=job.work_dir,
    )
    if summary.scored and not job.dry_run:
        path = _metrics_path(job.run_dir, job.cell_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(r.model_dump_json() + "\n" for r in records), encoding="utf-8")
    return summary


def score_run(
    run_dir: Path,
    *,
    corpus: Corpus,
    families: Sequence[MetricFamily | str] | None = None,
    work_dir: Path | None = None,
    workers: int = 1,
    resume: bool = False,
    dry_run: bool = False,
) -> ScoreResult:
    """Score every cell of the run in ``run_dir``; ``families`` default to the spec's.
    ``dry_run`` scores and reports but writes no metrics file."""
    if workers < 1:
        raise ConfigError(f"workers must be at least 1, got {workers}", code="workers_invalid")
    manifest = load_manifest(run_dir)
    if manifest.run_id != run_dir.name:
        raise CompassError(f"{run_dir} holds run {manifest.run_id!r}", code="run_id_mismatch")
    chosen = resolve_families(families or manifest.spec.metrics)
    planned = load_cells(run_dir)
    cell_ids = sorted(manifest.cells)
    jobs = [
        _ScoreJob(
            run_dir=run_dir,
            cell_id=cid,
            corpus=corpus,
            families=chosen,
            settings=planned[cid].settings_dict if cid in planned else None,
            work_dir=work_dir,
            resume=resume,
            dry_run=dry_run,
        )
        for cid in cell_ids
    ]
    result = ScoreResult(run_id=manifest.run_id, families=chosen)
    if min(workers, len(jobs)) <= 1:
        result.cells = [_score_and_write(job) for job in jobs]
        return result
    # spawn, not fork: safe on macOS; cells are returned in submission order
    with ProcessPoolExecutor(
        max_workers=min(workers, len(jobs)), mp_context=get_context("spawn")
    ) as pool:
        result.cells = list(pool.map(_score_and_write, jobs))
    return result
