"""``report.md`` and its CSV tables."""

from __future__ import annotations

import json

import pytest

from model_compass.aggregate.grid import aggregate_run
from model_compass.errors import CompassError
from model_compass.report import (
    ReportModel,
    ReportRow,
    load_report_model,
    parse_grid_csv,
    render_markdown,
    write_report,
)
from model_compass.runs import load_manifest

HEADER = "shape,model,mean_quality,band_2se,n_docsets,comparable,validity_warnings,mystery\n"


class TestGridParsing:
    def test_blank_stays_absent_and_malformed_is_absent_not_zero(self):
        (row,) = parse_grid_csv(HEADER + "form,m,,x,3,True,a;b,?\n")
        assert row.mean_quality is None and row.band_2se is None
        assert row.comparable is True and row.validity_warnings == ("a", "b")
        assert row.band_label == "—"

    def test_band_label(self):
        assert ReportRow(mean_quality=62.4, band_2se=3.1).band_label == "62.40 ±3.10"
        assert ReportRow(mean_quality=62.4, n_docsets=1).band_label == "62.40 (n=1)"


def rows(*specs):
    return [
        ReportRow(shape=s, model=m, mean_quality=q, band_2se=b, n_docsets=3, comparable=c)
        for s, m, q, b, c in specs
    ]


class TestModel:
    def test_only_comparable_rows_win_and_overlap_is_contested(self):
        model = ReportModel(
            run_id="r",
            grid=rows(
                ("form", "a", 80, 5, True),
                ("form", "b", 78, 5, True),
                ("form", "z", 99, 1, False),
                ("prose", "a", 70, 1, True),
                ("prose", "b", 50, 1, True),
                ("table", "a", 90, 1, False),
            ),
        )
        winners = {w.shape: w for w in model.shape_winners()}
        assert set(winners) == {"form", "prose"}
        assert winners["form"].model == "a" and winners["form"].contested
        assert not winners["prose"].contested and winners["prose"].runner_up == "b"
        assert "best_by_shape=form=a;prose=a" in model.summary_line()

    def test_gate_counts_fall_back_to_the_grid(self):
        model = ReportModel(run_id="r", grid=[ReportRow(validity_warnings=("x", "y"))])
        assert model.gate_counts() == {"x": 1, "y": 1}

    def test_an_empty_directory_names_everything_missing(self, tmp_path):
        model = load_report_model(tmp_path)
        assert [cmd for *_, cmd in model.missing] == ["dgc run", "dgc aggregate", "dgc aggregate"]
        text = render_markdown(model)
        assert "This run is incomplete" in text and "Run `dgc aggregate`" in text
        assert "partial=yes" in text

    def test_a_corrupt_manifest_is_a_bad_manifest_error(self, tmp_path):
        with pytest.raises(CompassError, match="no manifest") as caught:
            load_manifest(tmp_path)
        assert caught.value.code == "manifest_missing"
        (tmp_path / "manifest.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(CompassError) as caught:
            load_report_model(tmp_path)
        assert caught.value.code == "bad_manifest"


class TestWriteReport:
    def test_failures_cost_caveat_and_dirty_repos(self, fresh_runs):
        run = fresh_runs["20261008-140547-4fe5464b"]
        manifest = json.loads((run / "manifest.json").read_text())
        cell_id = next(iter(manifest["cells"]))
        manifest["cells"][cell_id].update(
            status="failed", error_code="refused", error_message="out of credits\ntrace"
        )
        manifest["provenance"]["repos"]["dgml"]["dirty"] = True
        (run / "manifest.json").write_text(json.dumps(manifest))
        aggregate_run(run)
        report = write_report(run)
        assert f"| `{cell_id}` | `refused` | out of credits |" in report.markdown
        assert "row(s) carry `cost_partial`" in report.markdown
        assert "*(uncommitted changes)*" in report.markdown
        assert not report.partial
        names = sorted(p.name for p in report.written)
        assert names == [
            "best_by_shape.csv",
            "by_shape.csv",
            "cost_by_model.csv",
            "failures.csv",
            "gates.csv",
            "report.md",
        ]
        failures = (run / "report" / "failures.csv").read_text().splitlines()
        assert failures == ["cell_id,error_code,message", f"{cell_id},refused,out of credits"]
        assert report.tables["by_shape.csv"][0] == ["shape", "anthropic/claude-haiku-5-5"]

    def test_dry_run_writes_nothing_and_is_reproducible(self, real_runs):
        run = real_runs["20261014-022456-37998681"]
        aggregate_run(run, dry_run=True)
        first, second = write_report(run, dry_run=True), write_report(run, dry_run=True)
        assert first.markdown == second.markdown and first.written == ()
        assert not (run / "report").exists()
