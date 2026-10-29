"""Scoring a run directory: skips, resume and workers, on the ``msa_tree`` fixture."""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING

import pytest

from model_compass.corpus.loader import load_corpus
from model_compass.corpus.selector import CorpusSelector
from model_compass.errors import ConfigError
from model_compass.scoring import score_run

from .helpers import TESTS, extract

if TYPE_CHECKING:
    from pathlib import Path

FIXTURE = TESTS / "metrics" / "fixtures" / "msa_tree.tar.gz"


@pytest.fixture
def run(tmp_path):
    base = extract(FIXTURE, tmp_path) / "msa_tree"
    (run_dir,) = (base / "runs").iterdir()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    corpus, _ = load_corpus(
        base / "corpus", CorpusSelector.model_validate(manifest["spec"]["corpus"])
    )
    _move_recorded_workspaces(run_dir, tmp_path / "elsewhere")
    return run_dir, corpus, base / "work"


def _move_recorded_workspaces(run_dir: Path, root: Path) -> None:
    """Point each draw's recorded workspace at a path that does not exist, keeping its tail,
    so the tests only find what is re-rooted under ``work_dir``."""
    for path in run_dir.glob("cells/*/draws/*/result.json"):
        result = json.loads(path.read_text())
        recorded = result.get("workspace")
        if recorded and "/work/" in recorded:
            result["workspace"] = str(root / "work" / recorded.split("/work/", 1)[1])
            path.write_text(json.dumps(result))


def _draw(run_dir: Path) -> Path:
    (cell,) = (run_dir / "cells").iterdir()
    return cell / "draws" / "00"


def test_families_default_to_the_spec_and_unknown_ones_are_refused(run):
    run_dir, corpus, work = run
    result = score_run(run_dir, corpus=corpus, work_dir=work)
    assert [f.value for f in result.families] == ["extraction", "reference_free", "economics"]
    with pytest.raises(ConfigError, match="shape"):
        score_run(run_dir, corpus=corpus, families=["shape"], work_dir=work)


def test_without_the_workspace_families_say_so(run):
    run_dir, corpus, _ = run
    score_run(run_dir, corpus=corpus, families=["extraction", "economics"], work_dir=None)
    records = [
        json.loads(x) for x in next((run_dir / "metrics").glob("*.jsonl")).read_text().splitlines()
    ]
    economics = next(r for r in records if r["family"] == "economics")
    assert economics["values"] == {} and economics["warnings"] == ["no_workspace"]
    extraction = next(r for r in records if r["family"] == "extraction")
    assert extraction["values"]  # scored from the DGML persisted in the run directory


def test_a_draw_without_its_sidecar_or_a_dry_run_is_not_scored(run):
    run_dir, corpus, work = run
    shutil.rmtree(_draw(run_dir) / "workspace")
    assert not list(work.rglob("mca-workspace.json"))  # the fixture keeps it in the run only
    result = score_run(run_dir, corpus=corpus, families=["extraction"], work_dir=work)
    assert (result.cells[0].scored, result.cells[0].reason) == (False, "no_sidecar")
    path = _draw(run_dir) / "result.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "dry_run": True}))
    assert score_run(run_dir, corpus=corpus, families=["extraction"]).cells[0].reason == "dry_run"


def test_resume_keeps_a_complete_file_and_workers_change_nothing(run):
    run_dir, corpus, work = run
    families = ["extraction", "reference_free"]
    score_run(run_dir, corpus=corpus, families=families, work_dir=work)
    (metrics,) = (run_dir / "metrics").glob("*.jsonl")
    first = metrics.read_text()
    assert score_run(run_dir, corpus=corpus, families=families, resume=True).cells[0].kept
    assert metrics.read_text() == first
    assert (
        not score_run(
            run_dir, corpus=corpus, families=[*families, "tree"], resume=True, work_dir=work
        )
        .cells[0]
        .kept
    )
    score_run(run_dir, corpus=corpus, families=families, work_dir=work, workers=2)
    strip = [
        {k: v for k, v in json.loads(x).items() if k != "computed_at"}
        for x in metrics.read_text().splitlines()
    ]
    assert strip == [
        {k: v for k, v in json.loads(x).items() if k != "computed_at"} for x in first.splitlines()
    ]
