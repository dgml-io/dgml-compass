"""One draw's generation: config.toml, ``docset generate`` per docset, and what came out.

``docset generate`` does not fail when a document does: a per-file failure is one ``failed``
entry in ``results`` and the batch exits 0. :class:`DrawResult` (``result.json``) therefore
keeps every per-document outcome, soft errors included, and accounts for documents the payload
never mentioned. Under ``dry_run`` nothing is executed: the result carries the cost model's
estimate. :mod:`model_compass.runs` reads these files back.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, ConfigDict, Field

from model_compass.domain import ModelSlot
from model_compass.engine.dgml_cli import CONFIG_FILENAME, render_config_toml
from model_compass.engine.usage import USAGE_FILENAME, UsageSummary, read_usage
from model_compass.errors import EngineError
from model_compass.pricing import CostEstimate, estimate_generation

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from model_compass.engine.dgml_cli import DgmlCli
    from model_compass.engine.workspace import WorkspacePlan
    from model_compass.experiments.cells import Cell
    from model_compass.pricing import ModelPrice

log = logging.getLogger(__name__)

ENGINE_SCHEMA_VERSION: Final[int] = 1


class DocumentOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    org: str
    docset_id: str
    name: str
    corpus_file_id: str | None = None
    dgml_file_id: str = ""
    status: str = "unknown"
    xml_path: str | None = None
    grounded: bool | None = None
    matched_token_pct: float | None = None
    elements_annotated: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    soft_errors: tuple[str, ...] = ()

    @property
    def produced_xml(self) -> bool:
        return bool(self.xml_path) and self.status in ("converted", "skipped")


class DocsetOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    org: str
    docset_id: str
    dgml_docset_id: str
    total: int = 0
    converted: int = 0
    skipped: int = 0
    failed: int = 0
    models: dict[str, str] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


class DrawResult(BaseModel):
    """``result.json``: everything one draw produced."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = ENGINE_SCHEMA_VERSION
    cell_id: str
    draw_index: int = 0
    dry_run: bool = False
    workspace: str = ""
    docsets: tuple[DocsetOutcome, ...] = ()
    documents: tuple[DocumentOutcome, ...] = ()
    usage_path: str | None = None
    usage: UsageSummary = UsageSummary()
    cost_estimate: CostEstimate | None = None
    warnings: tuple[str, ...] = ()

    @property
    def n_with_xml(self) -> int:
        return sum(1 for document in self.documents if document.produced_xml)

    @property
    def missing_dgml_rate(self) -> float:
        if not self.documents:
            return 0.0
        return 1.0 - self.n_with_xml / len(self.documents)

    @property
    def cost_usd(self) -> float:
        """Observed spend; the estimate under a dry run."""
        if self.dry_run and self.cost_estimate is not None:
            return self.cost_estimate.usd
        return self.usage.total_cost_usd


def _as_int(value: object) -> int | None:
    """Integral settings only; a bool is a flag, not a count, so it maps to None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _as_float(value: object) -> float | None:
    try:
        return float(value) if isinstance(value, int | float | str) else None
    except ValueError:
        return None


def _document_outcomes(
    plan: WorkspacePlan, docset_id: str, results: Sequence[Any]
) -> list[DocumentOutcome]:
    by_file = {
        entry.dgml_file_id: entry
        for entry in plan.entries
        if entry.docset_id == docset_id and entry.dgml_file_id
    }
    outcomes: list[DocumentOutcome] = []
    for raw in results:
        if not isinstance(raw, dict):
            continue
        file_id = str(raw.get("file_id") or "")
        entry = by_file.pop(file_id, None)
        error: dict[str, Any] = raw["error"] if isinstance(raw.get("error"), dict) else {}
        outcomes.append(
            DocumentOutcome(
                org=entry.org if entry else "",
                docset_id=docset_id,
                name=entry.name if entry else str(raw.get("source") or ""),
                corpus_file_id=entry.corpus_file_id if entry else None,
                dgml_file_id=file_id,
                status=str(raw.get("status") or "unknown"),
                xml_path=str(raw["output"]) if raw.get("output") else None,
                grounded=raw.get("grounded"),
                matched_token_pct=raw.get("matched_token_pct"),
                elements_annotated=raw.get("elements_annotated"),
                error_code=str(error["code"]) if error.get("code") else None,
                error_message=str(error["message"]) if error.get("message") else None,
                soft_errors=tuple(
                    key
                    for key in ("label_error", "grounding_error", "link_error")
                    if isinstance(raw.get(key), dict)
                ),
            )
        )
    for entry in by_file.values():  # documents the payload never mentioned
        outcomes.append(
            DocumentOutcome(
                org=entry.org,
                docset_id=docset_id,
                name=entry.name,
                corpus_file_id=entry.corpus_file_id,
                dgml_file_id=entry.dgml_file_id,
                status="absent",
                error_code="not_reported",
                error_message="dgml's results array did not mention this file",
            )
        )
    return outcomes


def _generate_one(
    cli: DgmlCli, cell: Cell, plan: WorkspacePlan, reference: str, max_parallel_calls: int | None
) -> tuple[DocsetOutcome, list[DocumentOutcome]]:
    org, _, docset_id = reference.partition("/")
    dgml_docset_id = plan.docset_ids[reference]
    settings = cell.settings_dict
    try:
        payload = cli.docset_generate(
            dgml_docset_id,
            model=cell.model_for(ModelSlot.GENERATION),
            label_model=cell.model_for(ModelSlot.LABEL),
            window_size=_as_int(settings.get("window_size")),
            temperature=_as_float(settings.get("temperature")),
            max_tokens=_as_int(settings.get("max_tokens")),
            max_parallel_calls=max_parallel_calls,
        )
    except EngineError as exc:
        log.warning("docset generate failed for %s in %s: %s", reference, cell.cell_id, exc.code)
        failed = DocsetOutcome(
            org=org,
            docset_id=docset_id,
            dgml_docset_id=dgml_docset_id,
            error_code=exc.code,
            error_message=exc.message,
        )
        return failed, []
    summary = payload.get("summary") or {}
    outcome = DocsetOutcome(
        org=org,
        docset_id=docset_id,
        dgml_docset_id=dgml_docset_id,
        total=int(summary.get("total", 0)),
        converted=int(summary.get("converted", 0)),
        skipped=int(summary.get("skipped", 0)),
        failed=int(summary.get("failed", 0)),
        models={str(k): str(v) for k, v in (payload.get("models") or {}).items()},
    )
    return outcome, _document_outcomes(plan, docset_id, payload.get("results") or [])


def generate(
    cell: Cell,
    plan: WorkspacePlan,
    cli: DgmlCli | None,
    *,
    dry_run: bool = False,
    prices: Mapping[str, ModelPrice] | None = None,
    max_parallel_calls: int | None = None,
    draw_index: int = 0,
) -> DrawResult:
    """Run one draw over every docset in its workspace (one, per DECISIONS 0015).

    ``max_parallel_calls`` goes to dgml as ``--max-parallel-calls``: documents transcribed
    concurrently within the docset (None leaves dgml's default)."""
    workspace = Path(plan.workspace)
    if dry_run:
        return DrawResult(
            cell_id=cell.cell_id,
            draw_index=draw_index,
            dry_run=True,
            workspace=str(workspace),
            cost_estimate=estimate_generation(
                n_documents=len(plan.entries),
                generation_model=cell.model_for(ModelSlot.GENERATION),
                label_model=cell.model_for(ModelSlot.LABEL),
                prices=prices or {},
            ),
            warnings=("dry run: no dgml subprocess was started",),
        )
    if cli is None:
        raise EngineError("a real draw needs a dgml client", code="no_dgml_client")

    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / CONFIG_FILENAME).write_text(
        render_config_toml(cell.settings_dict, header=f"cell {cell.cell_id}"), encoding="utf-8"
    )
    outcomes: list[DocsetOutcome] = []
    documents: list[DocumentOutcome] = []
    for reference in sorted(plan.docset_ids):
        outcome, docs = _generate_one(cli, cell, plan, reference, max_parallel_calls)
        outcomes.append(outcome)
        documents.extend(docs)

    usage_path = workspace / USAGE_FILENAME
    usage = read_usage(usage_path)
    warnings: list[str] = []
    if not usage.present:
        warnings.append(
            "no usage.jsonl: dgml records cost only under --debug, so economics metrics "
            "will be unavailable for this cell"
        )
    if usage.n_unpriced:
        warnings.append(
            f"{usage.n_unpriced} model call(s) have no cost in usage.jsonl (dgml could not "
            f"price {', '.join(usage.unpriced_models) or 'the model'}); the cell's cost is a "
            "floor and is flagged partial"
        )
    if usage.cost_partial and usage.present and usage.unattributed_cost_usd > 0:
        warnings.append(
            f"${usage.unattributed_cost_usd:.4f} of spend is not attributable to a document; "
            "per-document cost is flagged partial"
        )
    soft = sum(1 for document in documents if document.soft_errors)
    if soft:
        warnings.append(f"{soft} document(s) carry a soft error reported inside a success payload")
    return DrawResult(
        cell_id=cell.cell_id,
        draw_index=draw_index,
        workspace=str(workspace),
        docsets=tuple(outcomes),
        documents=tuple(documents),
        usage_path=str(usage_path) if usage.present else None,
        usage=usage,
        warnings=tuple(warnings),
    )
