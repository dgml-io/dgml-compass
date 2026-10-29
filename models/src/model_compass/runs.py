"""The run directory::

    <runs_dir>/<run_id>/
      manifest.json  cells.json  spec.resolved.yaml  events.jsonl
      cells/<cell_id>/[draws/<NN>/]result.json          what a draw produced
                                   workspace/mca-workspace.json   the join sidecar
                                   dgml/<xml_path>      generated DGML, persisted per document
      metrics/<cell_id>.jsonl                           written by scoring

The generated dgml workspace itself (usage, OCR page text) lives under ``work_dir``.
These models read those files; fields this repo does not use are ignored.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from model_compass.domain import AxisValue
from model_compass.errors import CompassError

RESULT_FILENAME: Final[str] = "result.json"
SIDECAR_FILENAME: Final[str] = "mca-workspace.json"
MANIFEST_FILENAME: Final[str] = "manifest.json"
MAX_DRAWS: Final[int] = 50
"""Draw indexes run ``00`` to ``49``."""


def artifact_prefix(cell_id: str) -> str:
    """A cell's directory relative to the run directory."""
    return f"cells/{cell_id}"


def draw_subdir(cell_dir: Path, index: int) -> Path:
    """``<cell_dir>/draws/<NN>``: where a multi-draw cell keeps draw ``index``."""
    return cell_dir / "draws" / f"{index:02d}"


class _Read(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class StoredDocumentOutcome(_Read):
    org: str
    docset_id: str
    name: str
    corpus_file_id: str | None = None
    dgml_file_id: str = ""
    status: str = "unknown"
    xml_path: str | None = None

    @property
    def produced_xml(self) -> bool:
        return bool(self.xml_path) and self.status in ("converted", "skipped")


class StoredDocsetOutcome(_Read):
    org: str
    docset_id: str


class StoredDrawResult(_Read):
    """``result.json``: one draw's generation outcome."""

    cell_id: str
    draw_index: int = 0
    dry_run: bool = False
    workspace: str = ""
    docsets: tuple[StoredDocsetOutcome, ...] = ()
    documents: tuple[StoredDocumentOutcome, ...] = ()


class StoredWorkspaceEntry(_Read):
    org: str
    docset_id: str
    name: str
    corpus_file_id: str | None = None
    dgml_file_id: str = ""

    @property
    def joinable(self) -> bool:
        return bool(self.corpus_file_id) and bool(self.dgml_file_id)


class StoredWorkspacePlan(_Read):
    """The join sidecar: the only record of which dgml file id is which corpus document."""

    cell_id: str
    entries: tuple[StoredWorkspaceEntry, ...] = ()
    docset_ids: dict[str, str] = Field(default_factory=dict)
    """Corpus ``org/docset`` -> the id dgml gave that docset in the workspace."""


class RepoState(_Read):
    commit: str | None = None
    dirty: bool = False


class Provenance(_Read):
    repos: dict[str, RepoState] = Field(default_factory=dict)
    dgml_version: str | None = None
    python_version: str = ""
    package_version: str = ""
    corpus_hash: str | None = None

    @property
    def any_dirty(self) -> bool:
        return any(repo.dirty for repo in self.repos.values())


class CellState(_Read):
    status: str = "pending"
    draws_total: int = 1
    draws_completed: int = 0
    error_code: str | None = None
    error_message: str | None = None


class SpecView(_Read):
    name: str = ""
    description: str | None = None
    axes: dict[str, list[Any]] = Field(default_factory=dict)
    fixed: dict[str, Any] = Field(default_factory=dict)
    draws: int = 1
    metrics: list[str] = Field(default_factory=list)
    corpus: dict[str, Any] = Field(default_factory=dict)


class Costs(_Read):
    actual_usd: float = 0.0


class Manifest(_Read):
    """``manifest.json`` as scoring, aggregation and the report read it.

    Kept apart from the strict, event-sourced writer (``experiments/manifest.py``): every field
    defaults, so older run directories still read."""

    run_id: str
    spec: SpecView = Field(default_factory=SpecView)
    provenance: Provenance = Field(default_factory=Provenance)
    cells: dict[str, CellState] = Field(default_factory=dict)
    costs: Costs = Field(default_factory=Costs)
    outcome: str = "pending"


class PlannedCell(_Read):
    """One entry of ``cells.json``; ``shape`` is the docset's shape, which grouping needs."""

    cell_id: str
    org: str
    docset: str
    settings: tuple[tuple[str, AxisValue], ...]
    shape: str | None = None

    @property
    def settings_dict(self) -> dict[str, AxisValue]:
        return dict(self.settings)


def _read(path: Path, model: type[_Read], what: str) -> Any:
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CompassError(
            f"{path} is not a readable {what}: {exc}", code="bad_run_artifact"
        ) from exc


def load_manifest(run_dir: Path) -> Manifest:
    path = run_dir / MANIFEST_FILENAME
    if not path.is_file():
        raise CompassError(
            f"no manifest at {path}; is this a run directory?", code="manifest_missing"
        )
    try:
        return Manifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CompassError(f"{path} is not a run manifest: {exc}", code="bad_manifest") from exc


def load_cells(run_dir: Path) -> dict[str, PlannedCell]:
    """``cells.json`` by id, sorted; empty for runs without it (every run ``dgc run`` writes
    has it)."""
    path = run_dir / "cells.json"
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {cell_id: PlannedCell.model_validate(cell) for cell_id, cell in sorted(raw.items())}


def load_result(draw_dir: Path) -> StoredDrawResult | None:
    path = draw_dir / RESULT_FILENAME
    return _read(path, StoredDrawResult, "cell result") if path.is_file() else None


def load_sidecar(draw_dir: Path, workspace: Path | None) -> StoredWorkspacePlan | None:
    """From the run directory first, the local workspace second."""
    for path in (
        draw_dir / "workspace" / SIDECAR_FILENAME,
        workspace and workspace / SIDECAR_FILENAME,
    ):
        if path and path.is_file():
            return _read(path, StoredWorkspacePlan, "workspace sidecar")
    return None


def draw_dirs(cell_dir: Path) -> tuple[tuple[int, Path], ...]:
    """Each draw's directory with its index. A flat cell (``result.json`` directly under it)
    is one draw; otherwise ``draws/00``, ``01``, ... up to the first one without a result."""
    if (cell_dir / RESULT_FILENAME).is_file():
        return ((0, cell_dir),)
    found = []
    for index in range(MAX_DRAWS):
        candidate = draw_subdir(cell_dir, index)
        if not (candidate / RESULT_FILENAME).is_file():
            break
        found.append((index, candidate))
    return tuple(found)


def locate_workspace(recorded: str, work_dir: Path | None, run_id: str) -> Path | None:
    """Where a draw's workspace is now: as recorded, or re-rooted under ``work_dir`` when the
    run was made on another mount or the scratch directory moved (adopted draws record the
    run they were generated in, so the path is also matched after the work_dir's name)."""
    if not recorded:
        return None
    original = Path(recorded)
    if original.is_dir():
        return original
    if work_dir is None:
        return None
    root = Path(work_dir) / run_id
    posix = original.as_posix()
    candidates: list[Path] = []
    scratch = f"/{Path(work_dir).name}/"
    if scratch in posix:
        candidates.append(Path(work_dir) / posix.split(scratch, 1)[1])
    marker = f"/{run_id}/"
    if marker in posix:
        candidates.append(root / posix.split(marker, 1)[1])
    parts = original.parts
    for depth in (2, 4):  # <cell>/workspace, <cell>/draws/NN/workspace
        if len(parts) >= depth:
            candidates.append(root.joinpath(*parts[-depth:]))
    return next((c for c in candidates if c.is_dir()), None)
