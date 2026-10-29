"""plan -> dry run -> score -> aggregate -> report -> compare, through ``dgc``.

1. ``dgc plan`` and ``dgc run --dry-run`` on the rehearsal spec over the mini corpus: a full
   run directory, nothing spent, and its draws are refused by ``dgc score`` (dry runs are
   never scored).
2. ``dgc score`` on one real transcr3 draw (the ``msa_tree`` scoring fixture).
3. Those records are spliced into the transcr3 metrics (``fixtures/runs.tar.gz``) and the two
   real runs go through ``dgc aggregate``, ``report`` and ``compare``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from model_compass.cli import main
from model_compass.config import MODELS_DIR
from model_compass.errors import ExitCode

from .helpers import FIXTURES, MINI, TESTS, extract

if TYPE_CHECKING:
    from pathlib import Path

TRANSCR3 = "20260925-200000-transcr3"
LABELHK3 = "20260925-200001-labelhk3"
FAMILIES = ["extraction", "reference_free", "economics", "tree"]


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setenv("DGC_DGML_REPO", str(tmp_path / "no-dgml"))  # no `dgml --version` probe

    def run(*args: str, runs: Path, corpus: Path = MINI, work: Path | None = None) -> int:
        common = ["--runs-dir", str(runs), "--corpus-root", str(corpus)]
        return main([*common, "--work-dir", str(work or tmp_path / "work"), *args])

    return run


def test_plan_and_dry_run_spend_nothing_and_are_not_scored(cli, tmp_path):
    runs = tmp_path / "runs"
    spec = str(MODELS_DIR / "specs" / "rehearsal.yaml")
    assert cli("plan", "-e", spec, runs=runs) == ExitCode.OK
    assert not runs.exists()
    assert cli("run", "-e", spec, "--dry-run", "--allow-dirty-corpus", runs=runs) == ExitCode.OK
    (run_dir,) = runs.iterdir()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["outcome"] == "dry_run" and manifest["costs"]["actual_usd"] == 0
    for name in ("cells.json", "events.jsonl", "prices.json", "spec.resolved.yaml"):
        assert (run_dir / name).is_file(), name
    assert cli("score", "-r", run_dir.name, runs=runs) == ExitCode.FINDINGS
    assert not (run_dir / "metrics").exists()


def test_score_aggregate_report_compare(cli, tmp_path):
    # -- score one real draw -------------------------------------------------------------------
    scored = extract(TESTS / "metrics" / "fixtures" / "msa_tree.tar.gz", tmp_path) / "msa_tree"
    runs, corpus, work = scored / "runs", scored / "corpus", scored / "work"
    families = [arg for family in FAMILIES for arg in ("--metric", family)]
    assert (
        cli("score", "-r", TRANSCR3, *families, "--dry-run", runs=runs, corpus=corpus, work=work)
        == 0
    )
    assert not (runs / TRANSCR3 / "metrics").exists()
    assert cli("score", "-r", TRANSCR3, *families, runs=runs, corpus=corpus, work=work) == 0
    fresh = {
        path.name: [json.loads(line) for line in path.read_text().splitlines()]
        for path in (runs / TRANSCR3 / "metrics").glob("*.jsonl")
    }
    assert sorted(fresh) == ["2ec47c681483.jsonl"]

    # -- splice them into the full runs ------------------------------------------------------
    # transcr3 = the aggregate/fixtures copy plus cells/*/status.json; labelhk3 is only here
    full = extract(FIXTURES / "runs.tar.gz", tmp_path / "full") / "runs"
    for name, records in fresh.items():
        path = full / TRANSCR3 / "metrics" / name
        kept = [line for line in path.read_text().splitlines() if json.loads(line)["draw"] != 0]
        path.write_text("".join(json.dumps(r) + "\n" for r in records) + "\n".join(kept) + "\n")

    # -- aggregate, report, compare --------------------------------------------------------------
    # both runs have incomparable rows (too few docsets per shape), so these report findings
    findings = ExitCode.FINDINGS
    assert cli("aggregate", "-r", TRANSCR3, "--dry-run", runs=full) == findings
    assert not (full / TRANSCR3 / "grid").exists()
    for run in (TRANSCR3, LABELHK3):
        assert cli("aggregate", "-r", run, runs=full) == findings
        assert (full / run / "grid" / "compass_grid.csv").is_file()
    assert cli("report", "-r", TRANSCR3, runs=full) == ExitCode.OK
    assert (full / TRANSCR3 / "report" / "report.md").is_file()
    out = tmp_path / "compare"
    assert cli("compare", LABELHK3, TRANSCR3, "-o", str(out), runs=full) == findings
    assert {p.suffix for p in out.iterdir()} == {".md", ".csv"}
