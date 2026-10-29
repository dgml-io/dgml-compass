"""Known aggregation defects (docs/DECISIONS.md). Each test states the intended behaviour and is
a strict xfail until the defect is fixed."""

from __future__ import annotations

import json

import pytest

from model_compass.aggregate.grid import aggregate, aggregate_run
from model_compass.report import write_report

from .conftest import cell, rec

STRICT = {"strict": True}


@pytest.mark.xfail(
    reason="known defect 7 (docs/DECISIONS.md): "
    "the row's model is the first of label > generation > ...; in a transcriber sweep "
    "(labeler fixed, generation.model swept) every transcriber lands in ONE row, so "
    "mean_quality averages five models and axes_json names only the first (DECISIONS 0010 says a "
    "group never spans two models)",
    **STRICT,
)
def test_a_transcriber_sweep_keeps_one_row_per_transcriber(fresh_runs):
    result = aggregate_run(fresh_runs["20260925-200000-transcr3"], dry_run=True)
    # One configuration contributes one cell per docset.
    assert all(row.n_cells == row.n_docsets for row in result.grid.rows)


@pytest.mark.xfail(
    reason="known defect 8 (docs/DECISIONS.md): "
    "n_documents sums counts['n_documents'] over every family's record, so a document "
    "is counted once per family that reports it (3x in current runs)",
    **STRICT,
)
def test_n_documents_counts_each_scored_document_once():
    records = [
        rec("a", 50, family="extraction", n_documents=6),
        rec("a", family="reference_free", n_documents=6),
        rec("a", family="tree", n_documents=6),
    ]
    grid, _ = aggregate(records, cells={"c1": cell()}, evidence={})
    assert grid.rows[0].n_documents == 6


@pytest.mark.xfail(
    reason="known defect 8 (docs/DECISIONS.md): "
    "the report attributes cost as cost_per_doc_usd * n_documents, inheriting the "
    "per-family n_documents overcount: attributed spend is ~3x the measured spend",
    **STRICT,
)
def test_attributed_cost_does_not_exceed_measured_spend(fresh_runs):
    run = fresh_runs["20261014-022456-37998681"]
    aggregate_run(run)
    attributed = sum(float(v) for _, v in write_report(run).tables["cost_by_model.csv"][1:])
    measured = json.loads((run / "manifest.json").read_text())["costs"]["actual_usd"]
    assert attributed <= measured * 1.05
