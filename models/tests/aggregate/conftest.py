"""Shared builders, and the real-run fixtures extracted once per session.

The fixture runs (``fixtures/<run_id>.tar.gz``; manifests, cells.json and metrics, no DGML),
all over the 8 public z4ervk9ic0oo docsets, 6 documents, 3 draws:

- ``20260925-200000-transcr3``: transcriber sweep (5 generation models, labeler Haiku 4.5)
- ``20261008-140547-4fe5464b``: ``compass-corpus-3x6-haiku55`` (Haiku 5.5 both slots, random
  sampling, .pdf only)
- ``20261014-022456-37998681``: ``compass-label-haiku55`` (6 label models, transcriber Haiku 5.5)

``20260925-200001-labelhk3`` (labeler sweep, transcriber Haiku 4.5) is only in
``tests/fixtures/runs.tar.gz``, used by ``test_end_to_end.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from model_compass.records import MetricRecord
from model_compass.runs import PlannedCell

from .. import helpers

HERE = Path(__file__).parent
EXPECTED = HERE / "expected"
RUNS = sorted(p.name.removesuffix(".tar.gz") for p in (HERE / "fixtures").glob("*.tar.gz"))


def extract(into: Path) -> dict[str, Path]:
    for run in RUNS:
        helpers.extract(HERE / "fixtures" / f"{run}.tar.gz", into)
    return {run: into / run for run in RUNS}


@pytest.fixture(scope="session")
def real_runs(tmp_path_factory) -> dict[str, Path]:
    """Read-only use: tests that write into a run take ``fresh_runs``."""
    return extract(tmp_path_factory.mktemp("runs"))


@pytest.fixture
def fresh_runs(tmp_path) -> dict[str, Path]:
    return extract(tmp_path)


def rec(
    docset: str,
    value: float | None = None,
    *,
    cell: str = "c1",
    draw: int = 0,
    family: str = "extraction",
    blind: float | None = None,
    extra: dict[str, float] | None = None,
    warnings: tuple[str, ...] = (),
    absent: tuple[str, ...] = (),
    n_documents: int | None = None,
) -> MetricRecord:
    values = dict(extra or {})
    if value is not None:
        values["individual_overlap_f1"] = value
    if blind is not None:
        values["value_only_overlap_recall"] = blind
    return MetricRecord(
        run_id="r",
        cell_id=cell,
        org="org",
        docset=docset,
        draw=draw,
        family=family,
        values=values,
        counts={} if n_documents is None else {"n_documents": n_documents},
        absent=absent,
        warnings=warnings,
    )


def cell(cell_id: str = "c1", shape: str | None = "form", **settings) -> PlannedCell:
    settings = {"generation.label_model": "anthropic/claude-haiku-4-5", **settings}
    return PlannedCell(
        cell_id=cell_id,
        org="org",
        docset="d",
        shape=shape,
        settings=tuple(sorted(settings.items())),
    )
