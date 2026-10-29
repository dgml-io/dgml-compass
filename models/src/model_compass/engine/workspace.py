"""Building one draw's dgml workspace, and the join sidecar that records what went in.

The sidecar (``mca-workspace.json``) maps each corpus file id (what gold is keyed on) to the
dgml file id (what the generated XML is filed under); nothing else can reconstruct that
afterwards. Docsets are created named by docset_id, which joins straight to gold.

A workspace whose sidecar matches the request is reused without a subprocess; a half-built one
(no sidecar) is rebuilt, with ``file add --on-conflict skip`` reusing what exists; a sidecar for
a different cell or document set is refused rather than attributing one arm's output to another.
:mod:`model_compass.runs` reads these files back.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, ConfigDict, Field

from model_compass.errors import EngineError
from model_compass.ids import digest
from model_compass.runs import SIDECAR_FILENAME

if TYPE_CHECKING:
    from model_compass.corpus.models import Corpus, Docset, Document
    from model_compass.engine.dgml_cli import DgmlCli
    from model_compass.experiments.cells import Cell

log = logging.getLogger(__name__)

WORKSPACE_SCHEMA_VERSION: Final[int] = 1


class WorkspaceEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    org: str
    docset_id: str
    name: str
    source_path: str
    corpus_file_id: str | None = None
    dgml_file_id: str = ""
    dgml_docset_id: str = ""


class WorkspacePlan(BaseModel):
    """No timestamp: two builds of the same draw serialise to identical bytes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = WORKSPACE_SCHEMA_VERSION
    cell_id: str
    draw_index: int = 0
    organization: str
    workspace: str
    fingerprint: str
    entries: tuple[WorkspaceEntry, ...] = ()
    docset_ids: dict[str, str] = Field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, text: str) -> WorkspacePlan:
        return cls.model_validate(json.loads(text))


def _fingerprint(cell: Cell, corpus: Corpus, draw_index: int = 0) -> str:
    return digest(
        {
            "cell_id": cell.cell_id,
            **({"draw_index": draw_index} if draw_index else {}),
            "documents": [
                [docset.org, docset.docset_id, document.name, document.file_id]
                for docset in corpus.docsets
                for document in docset.documents
            ],
        },
        length=16,
        prefix=b"mca.workspace.v1",
    )


def _entry(
    docset: Docset, document: Document, *, dgml_file_id: str = "", dgml_docset_id: str = ""
) -> WorkspaceEntry:
    return WorkspaceEntry(
        org=docset.org,
        docset_id=docset.docset_id,
        name=document.name,
        source_path=document.path,
        corpus_file_id=document.file_id,
        dgml_file_id=dgml_file_id,
        dgml_docset_id=dgml_docset_id,
    )


def _workspace_plan(
    cell: Cell,
    corpus: Corpus,
    workspace: Path,
    entries: list[WorkspaceEntry],
    docset_ids: dict[str, str],
    *,
    organization: str,
    draw_index: int,
) -> WorkspacePlan:
    return WorkspacePlan(
        cell_id=cell.cell_id,
        draw_index=draw_index,
        organization=organization,
        workspace=str(workspace),
        fingerprint=_fingerprint(cell, corpus, draw_index),
        entries=tuple(sorted(entries, key=lambda e: (e.org, e.docset_id, e.name))),
        docset_ids=docset_ids,
    )


def plan_only(
    cell: Cell, corpus: Corpus, workspace: Path, *, organization: str = "mca", draw_index: int = 0
) -> WorkspacePlan:
    """What a build would produce, creating nothing (dry runs): dgml ids empty, documents real."""
    entries = [_entry(docset, doc) for docset in corpus.docsets for doc in docset.documents]
    docset_ids = {docset.ref: "" for docset in corpus.docsets}
    return _workspace_plan(
        cell,
        corpus,
        workspace,
        entries,
        docset_ids,
        organization=organization,
        draw_index=draw_index,
    )


def build_workspace(
    cell: Cell,
    corpus: Corpus,
    cli: DgmlCli,
    *,
    artifact_dir: Path | None = None,
    organization: str = "mca",
    draw_index: int = 0,
) -> WorkspacePlan:
    """Create one draw's workspace; the sidecar goes beside it and under ``artifact_dir``."""
    workspace = Path(cli.workspace)
    sidecar = workspace / SIDECAR_FILENAME
    fingerprint = _fingerprint(cell, corpus, draw_index)
    if sidecar.is_file():
        try:
            existing = WorkspacePlan.from_json(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise EngineError(
                f"{sidecar} exists but could not be read: {exc}", code="workspace_sidecar_invalid"
            ) from exc
        if existing.fingerprint != fingerprint or existing.cell_id != cell.cell_id:
            raise EngineError(
                f"{workspace} was built for cell {existing.cell_id} with a different document "
                f"set; refusing to reuse it for {cell.cell_id}. Use a fresh workspace.",
                code="workspace_mismatch",
            )
        return existing

    if not (workspace / "workspace.json").is_file():
        cli.workspace_create(name=workspace.name, organization=organization)
    text_mode = str(cell.settings_dict.get("text_mode") or "digital")
    entries: list[WorkspaceEntry] = []
    docset_ids: dict[str, str] = {}
    for docset in corpus.docsets:
        created = cli.docset_create(
            name=docset.docset_id,
            description=f"{docset.display_name or docset.docset_id} ({docset.org})",
        )
        dgml_docset_id = _require_id(created, "docset", f"docset create {docset.docset_id}")
        docset_ids[docset.ref] = dgml_docset_id
        for document in docset.documents:
            added = cli.file_add(
                Path(corpus.root) / document.path, text_mode=text_mode, on_conflict="skip"
            )
            dgml_file_id = _require_id(added, "file", f"file add {document.name}")
            cli.docset_add_file(dgml_file_id, docset_id=dgml_docset_id)
            entries.append(
                _entry(
                    docset, document, dgml_file_id=dgml_file_id, dgml_docset_id=dgml_docset_id
                )
            )
    plan = _workspace_plan(
        cell,
        corpus,
        workspace,
        entries,
        docset_ids,
        organization=organization,
        draw_index=draw_index,
    )
    workspace.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(plan.to_json(), encoding="utf-8")
    if artifact_dir is not None:
        stored = artifact_dir / "workspace" / SIDECAR_FILENAME
        stored.parent.mkdir(parents=True, exist_ok=True)
        stored.write_text(plan.to_json(), encoding="utf-8")
    log.info("workspace built for %s: %d documents", cell.cell_id, len(entries))
    return plan


def _require_id(payload: dict[str, Any], noun: str, what: str) -> str:
    """``{"<noun>_id": ...}`` or, in newer dgml, ``{"<noun>": {"id": ...}}``; the flat
    key wins when both are present."""
    nested = payload.get(noun)
    value = (
        payload.get(f"{noun}_id")
        or (nested.get("id") if isinstance(nested, dict) else None)
        or payload.get("id")
    )
    if not value:
        raise EngineError(f"{what} returned no {noun}_id: {payload!r}", code="bad_payload")
    return str(value)
