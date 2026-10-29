"""Aggregation, validity, pivots, compare and the report over three real runs, against the
outputs in ``expected/`` (``scripts/make_golden_aggregate.py``).
"""

from __future__ import annotations

import json

import pytest

from model_compass.aggregate.compare import compare_grids, compare_runs, render_comparison
from model_compass.aggregate.grid import aggregate_run
from model_compass.aggregate.render import GRID_HEADER, pivot
from model_compass.aggregate.validity import evidence_from_manifest
from model_compass.report import write_report
from model_compass.runs import load_manifest

from .conftest import EXPECTED, RUNS


@pytest.fixture(scope="module")
def produced(real_runs):
    return {run: aggregate_run(real_runs[run]) for run in RUNS}


@pytest.mark.parametrize("run", RUNS)
def test_grid_csv_matches(produced, real_runs, run):
    ours = (real_runs[run] / "grid" / "compass_grid.csv").read_text()
    assert ours == produced[run].csv_text
    assert ours == (EXPECTED / run / "compass_grid.csv").read_text()
    assert ours.splitlines()[0].split(",") == list(GRID_HEADER)


@pytest.mark.parametrize("run", RUNS)
def test_validity_json_matches(produced, real_runs, run):
    ours = (real_runs[run] / "grid" / "validity.json").read_text()
    theirs = (EXPECTED / run / "validity.json").read_text()
    assert json.loads(ours) == json.loads(theirs)
    assert ours == theirs  # same serialisation too


@pytest.mark.parametrize("run", RUNS)
def test_pivots_match(produced, run):
    expected = json.loads((EXPECTED / run / "pivots.json").read_text())
    for axis, table in expected.items():
        assert pivot(produced[run].grid, axis) == table


def _pairs():
    return sorted(p.stem.split("__") for p in (EXPECTED / "compare").glob("*.json"))


@pytest.mark.parametrize(("baseline", "candidate"), _pairs())
def test_compare_matches(real_runs, tmp_path, baseline, candidate):
    expected = json.loads((EXPECTED / "compare" / f"{baseline}__{candidate}.json").read_text())
    gated = compare_runs(real_runs[baseline], real_runs[candidate], out_dir=tmp_path)
    grids = [aggregate_run(real_runs[r], dry_run=True).grid for r in (baseline, candidate)]
    ungated = compare_grids(*grids, evidence=None)
    for name, table in (("gated", gated), ("no_provenance", ungated)):
        want = expected[name]
        assert render_comparison(table) == want["rendered"]
        assert list(table.warnings) == want["table"]["warnings"]
        assert [k.as_dict() for k in table.baseline_only] == want["table"]["baseline_only"]
        assert [k.as_dict() for k in table.candidate_only] == want["table"]["candidate_only"]
        assert len(table.deltas) == len(want["table"]["deltas"])
        for ours, theirs in zip(table.deltas, want["table"]["deltas"], strict=True):
            assert ours.key.as_dict() == theirs["key"]
            for name_, value in theirs.items():
                if name_ == "key":
                    continue
                mine = getattr(ours, name_)
                mine = list(mine) if isinstance(mine, tuple) else mine
                if isinstance(value, float):
                    assert mine == pytest.approx(value, abs=1e-9, rel=0)
                else:
                    assert mine == value, name_
    stem = f"{baseline}__vs__{candidate}"
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{stem}.csv", f"{stem}.md"]


def test_compare_evidence_is_every_cell_of_both_runs(real_runs):
    """Compare files all cells of both runs under every row key."""
    a, b = (real_runs[r] for r in RUNS[1:])
    cells = len(evidence_from_manifest(load_manifest(a))) + len(
        evidence_from_manifest(load_manifest(b))
    )
    assert cells == 48 + 8


@pytest.mark.parametrize("run", RUNS)
def test_report_matches(produced, real_runs, run):
    ours = write_report(real_runs[run], dry_run=True).markdown
    assert ours == (EXPECTED / run / "report.md").read_text()
    assert "This run is incomplete" not in ours
