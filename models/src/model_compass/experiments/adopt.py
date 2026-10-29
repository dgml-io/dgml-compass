"""Seeding draw 00 of a new run with executions an earlier run already paid for (DECISIONS 0018).

A run made before draws were executed holds one flat execution per cell over the loader's
fixed document selection; for a ``draws: N`` spec over the same selection that execution *is*
draw zero. A cell is adopted only when it succeeded with DGML for every document (unless
``allow_partial``), uses no excluded model, and generated exactly the documents the target's
draw zero would -- checked against its sidecar, never assumed. A multi-draw source hands over
every completed draw that passes the same checks. ``adoption.json`` records where each adopted
draw came from; ``run(..., resume_run_id=<target>)`` then executes only the missing draws.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from model_compass.corpus.loader import load_checked_corpus
from model_compass.corpus.sampling import draw_corpus
from model_compass.engine.workspace import WorkspacePlan
from model_compass.errors import ConfigError
from model_compass.experiments.manifest import SCHEMA_VERSION
from model_compass.experiments.plan import (
    STATUS_FILENAME,
    cell_dir,
    draw_dir,
    is_complete,
    plan,
    read_status,
    write_cells,
)
from model_compass.experiments.run import write_cell_summary
from model_compass.runs import SIDECAR_FILENAME, draw_subdir

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from model_compass.config import Settings
    from model_compass.corpus.models import Corpus
    from model_compass.experiments.cells import Cell
    from model_compass.experiments.spec import ExperimentSpec

log = logging.getLogger(__name__)

ADOPTION_FILENAME: Final[str] = "adoption.json"


@dataclass(frozen=True)
class Adoption:
    """What happened to one cell of the target spec."""

    cell_id: str
    ref: str
    action: str
    """``adopted``, ``would_adopt`` (dry run) or ``skipped``."""
    reason: str = ""
    source_run: str | None = None
    source_dir: str | None = None
    target_dir: str | None = None
    files: int = 0
    cost_usd: float = 0.0
    draws: int = 0


@dataclass
class AdoptResult:
    run_id: str
    run_dir: Path
    cells: list[Adoption] = field(default_factory=list)

    @property
    def adopted(self) -> list[Adoption]:
        return [c for c in self.cells if c.action != "skipped"]


def _documents(directory: Path) -> set[tuple[str, str, str]] | None:
    path = directory / "workspace" / SIDECAR_FILENAME
    if not path.is_file():
        return None
    sidecar = WorkspacePlan.from_json(path.read_text(encoding="utf-8"))
    return {(e.org, e.docset_id, e.name) for e in sidecar.entries}


def _expected(corpus: Corpus, cell: Cell, spec: ExperimentSpec) -> set[tuple[str, str, str]]:
    sampled = draw_corpus(corpus, cell, spec, 0)
    return {(d.org, d.docset_id, doc.name) for d in sampled.docsets for doc in d.documents}


def _copy_tree(source: Path, target: Path) -> int:
    """Every file under ``source`` except a nested ``draws/`` tree; ``status.json`` last."""
    files = [
        p
        for p in sorted(source.rglob("*"))
        if p.is_file() and p.relative_to(source).parts[0] != "draws"
    ]
    files.sort(key=lambda p: p == source / STATUS_FILENAME)
    for path in files:
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    return len(files)


def _usable(status: dict[str, Any], allow_partial: bool) -> bool:
    n_documents = int(status.get("n_documents", 0))
    n_with_xml = int(status.get("n_with_xml", 0))
    return allow_partial or n_with_xml >= n_documents


@dataclass(frozen=True)
class _Source:
    run_name: str
    directory: Path
    status: dict[str, Any]

    @property
    def cost_usd(self) -> float:
        return float(self.status.get("cost_usd", 0.0))


def _find_source(
    cell: Cell,
    source_runs: Sequence[Path],
    expected: set[tuple[str, str, str]],
    allow_partial: bool,
) -> tuple[_Source | None, str]:
    """The first source run whose flat execution or draw 00 of ``cell`` is usable, or why none
    is (the last source's reason)."""
    reason = "no_source"
    for source_run in source_runs:
        base = cell_dir(source_run, cell.cell_id)
        candidate = next(
            (d for d in (base, draw_subdir(base, 0)) if is_complete(d, accept_dry_run=False)),
            None,
        )
        if candidate is None:
            continue
        status = read_status(candidate) or {}
        run_name = source_run.name
        if int(status.get("n_documents", 0)) == 0 or int(status.get("n_with_xml", 0)) == 0:
            reason = f"no_dgml:{run_name}"
            continue
        if not _usable(status, allow_partial):
            reason = f"partial:{run_name}:{status.get('n_with_xml')}/{status.get('n_documents')}"
            continue
        actual = _documents(candidate)
        if actual is None:
            reason = f"no_sidecar:{run_name}"
            continue
        if actual != expected:
            reason = f"documents_differ:{run_name}"
            continue
        return _Source(run_name, candidate, status), reason
    return None, reason


def _adopt_extra_draws(
    source_cell: Path,
    target_run: Path,
    cell_id: str,
    *,
    draws: int,
    expected: set[tuple[str, str, str]],
    allow_partial: bool,
) -> tuple[int, list[tuple[int, Path, float]]]:
    """Draws 01.. of a multi-draw source that pass the same checks and are missing from the
    target: (files copied, ``(index, source draw, cost)`` per draw)."""
    copied = 0
    taken: list[tuple[int, Path, float]] = []
    for index in range(1, draws):
        src = draw_subdir(source_cell, index)
        dst = draw_dir(target_run, cell_id, index, draws=draws)
        if not is_complete(src, accept_dry_run=False) or is_complete(dst, accept_dry_run=False):
            continue
        status = read_status(src) or {}
        if not _usable(status, allow_partial) or _documents(src) != expected:
            continue
        copied += _copy_tree(src, dst)
        taken.append((index, src, float(status.get("cost_usd", 0.0))))
    return copied, taken


def adopt(
    spec: ExperimentSpec,
    settings: Settings,
    sources: Sequence[str],
    *,
    exclude_models: Iterable[str] = (),
    into: str | None = None,
    allow_partial: bool = False,
    dry_run: bool = False,
    corpus: Corpus | None = None,
    now: datetime | None = None,
) -> AdoptResult:
    """Copy usable executions from ``sources`` (run ids under ``runs_dir``, or run
    directories), searched in order, into draw 00 of ``into`` (default: a fresh run id)."""
    if spec.draws <= 1:
        raise ConfigError(
            f"experiment {spec.name!r} has draws: {spec.draws}; adopting is for specs with "
            "more than one draw. Resume that run instead.",
            code="adopt_single_draw",
        )
    corpus = corpus if corpus is not None else load_checked_corpus(spec, settings)
    built = plan(spec, settings, corpus, prices={}, dry_run=dry_run, now=now)
    target_id = into or built.run_id
    target_run = settings.runs_dir / target_id
    source_runs = [(Path(s) if Path(s).is_dir() else settings.runs_dir / s) for s in sources]
    excluded = {model for model in exclude_models if model}
    stamp = (now or datetime.now(UTC)).isoformat(timespec="seconds").replace("+00:00", "Z")
    result = AdoptResult(run_id=target_id, run_dir=target_run)
    provenance: list[dict[str, Any]] = []
    cells = [item.cell for item in built.cells]

    for cell in cells:
        expected = _expected(corpus, cell, spec)

        def skip(reason: str, cell: Cell = cell, **extra: Any) -> None:
            result.cells.append(
                Adoption(
                    cell_id=cell.cell_id, ref=cell.ref, action="skipped", reason=reason, **extra
                )
            )

        if banned := cell.models & excluded:
            skip(f"excluded_model:{','.join(sorted(banned))}")
            continue
        target = draw_dir(target_run, cell.cell_id, 0, draws=spec.draws)
        if is_complete(target, accept_dry_run=False):
            skip("target_has_draw_00", target_dir=str(target))
            continue
        found, reason = _find_source(cell, source_runs, expected, allow_partial)
        if found is None:
            skip(reason)
            continue
        if dry_run:
            result.cells.append(
                Adoption(
                    cell_id=cell.cell_id,
                    ref=cell.ref,
                    action="would_adopt",
                    source_run=found.run_name,
                    source_dir=str(found.directory),
                    target_dir=str(target),
                    cost_usd=found.cost_usd,
                )
            )
            continue
        copied = _copy_tree(found.directory, target)
        taken = [(0, found.directory, found.cost_usd)]
        # a multi-draw source hands over its other good draws too
        if found.directory.parent.name == "draws":
            extra_files, extra_draws = _adopt_extra_draws(
                found.directory.parent.parent,
                target_run,
                cell.cell_id,
                draws=spec.draws,
                expected=expected,
                allow_partial=allow_partial,
            )
            copied += extra_files
            taken += extra_draws
            if len(taken) == spec.draws:
                write_cell_summary(target_run, cell.cell_id, draws=spec.draws)
        provenance += [
            {
                "cell_id": cell.cell_id,
                "ref": cell.ref,
                "draw_index": index,
                "source_run": found.run_name,
                "source_prefix": str(src),
                "adopted_at": stamp,
                "cost_usd": cost,
            }
            for index, src, cost in taken
        ]
        result.cells.append(
            Adoption(
                cell_id=cell.cell_id,
                ref=cell.ref,
                action="adopted",
                source_run=found.run_name,
                source_dir=str(found.directory),
                target_dir=str(target),
                files=copied,
                cost_usd=sum(cost for _, _, cost in taken),
                draws=len(taken),
            )
        )
        log.info("adopted %s from %s (%d files)", cell.cell_id, found.run_name, copied)

    if not dry_run:
        write_cells(target_run, cells)
        _write_adoption(target_run, target_id, spec, provenance, stamp)
    return result


def _write_adoption(
    run_dir: Path, run_id: str, spec: ExperimentSpec, adopted: list[dict[str, Any]], stamp: str
) -> None:
    path = run_dir / ADOPTION_FILENAME
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "spec_name": spec.name,
        "draws": spec.draws,
        "sampling": spec.corpus.sampling.value,
        "adopted": [],
    }
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and isinstance(loaded.get("adopted"), list):
            record["adopted"] = loaded["adopted"]
    known = {(item.get("cell_id"), item.get("draw_index", 0)) for item in record["adopted"]}
    record["adopted"].extend(
        item for item in adopted if (item["cell_id"], item["draw_index"]) not in known
    )
    record["adopted"].sort(
        key=lambda item: (str(item.get("cell_id")), int(item.get("draw_index", 0)))
    )
    record["updated_at"] = stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
