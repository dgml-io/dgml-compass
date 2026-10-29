"""Grouping, averaging and the CSV contract."""

from __future__ import annotations

import csv
import io
import json
import statistics

import pytest

from model_compass.aggregate.grid import (
    aggregate,
    aggregate_run,
    config_tier_for,
    load_metric_records,
    primary_model,
)
from model_compass.aggregate.render import (
    GRID_BASE_COLUMNS,
    GRID_EXTRA_COLUMNS,
    GRID_HEADER,
    GRID_ROLE_PRICE_COLUMNS,
    grid_csv,
    pivot,
)
from model_compass.errors import CompassError

from .conftest import cell, rec

BASE_HEADER = (
    "unit,shape,doc_type,schema_tier,config_tier,model,mean_quality,tag_blind_recall,"
    "naming_gap,sd_between_docsets,band_2se,n_docsets,n_draws,single_docset,"
    "cost_per_doc_usd,cost_partial,usage_present"
)


def one_row(records, cells=None, **kwargs):
    grid, _ = aggregate(records, cells=cells or {"c1": cell()}, evidence={}, **kwargs)
    (row,) = grid.rows
    return row


def parsed(grid):
    return list(csv.DictReader(io.StringIO(grid_csv(grid))))


class TestModelResolution:
    def test_the_labeler_wins_then_the_precedence_falls_through(self):
        both = {"generation.model": "a/sonnet-5", "generation.label_model": "a/haiku-4-5"}
        assert primary_model(both) == "a/haiku-4-5"
        assert primary_model({"grounded.values_model": "g/x"}) == "g/x"
        assert primary_model({"schema_tier": "none"}) == ""

    @pytest.mark.parametrize(
        ("model", "tier"),
        [
            ("anthropic/claude-haiku-4-5", "haiku"),
            ("anthropic/claude-sonnet-5", "sonnet"),
            ("gemini/gemini-3.1-flash-lite", "flash-lite"),
            ("gemini/gemini-3.6-flash", "flash"),
            ("openai/gpt-5.5", "gpt-5.5"),
            ("", ""),
        ],
    )
    def test_the_tier_slug_reproduces_the_published_labels(self, model, tier):
        assert config_tier_for(model) == tier


class TestMeanOfMeans:
    def test_draws_are_averaged_within_a_docset_first(self):
        row = one_row([rec("a", 10, draw=0), rec("a", 30, draw=1), rec("b", 80)])
        assert row.mean_quality == pytest.approx((20 + 80) / 2)
        assert row.n_draws == 2  # the maximum over docsets, not the mean

    def test_docsets_are_not_weighted_by_size_but_the_pooled_mean_is_emitted(self):
        records = [rec("big", 10) for _ in range(9)] + [rec("small", 90)]
        row = one_row(records)
        assert row.mean_quality == pytest.approx(50)
        assert row.pooled_mean_quality == pytest.approx(18)

    def test_the_band_is_two_se_of_the_between_docset_sample_sd(self):
        row = one_row([rec("a", 10, draw=0), rec("a", 50, draw=1), rec("b", 40), rec("c", 60)])
        means = [30, 40, 60]
        assert row.sd_between_docsets == pytest.approx(statistics.stdev(means))
        assert row.band_2se == pytest.approx(2 * statistics.stdev(means) / 3**0.5)

    def test_a_single_docset_has_no_band_and_nothing_scored_has_no_quality(self):
        row = one_row([rec("a", 70), rec("a", 72, draw=1)])
        assert (row.sd_between_docsets, row.band_2se, row.single_docset) == (None, None, True)
        empty = one_row([rec("a", family="economics", extra={"cost_per_doc": 0.1})])
        assert empty.mean_quality is None and empty.n_docsets == 0

    def test_absent_is_not_zero(self):
        row = one_row([rec("a", 0.0), rec("b", 50, absent=("individual_overlap_f1",))])
        assert row.mean_quality == 0.0 and row.n_docsets == 1


class TestDerivedColumns:
    def test_the_naming_gap_is_a_difference_of_aggregates(self):
        row = one_row([rec("a", 20, blind=90), rec("b", 40, blind=70), rec("c", 60)])
        assert row.tag_blind_recall == pytest.approx(80)
        assert row.naming_gap == pytest.approx(80 - 40)
        assert (row.n_docsets, row.n_docsets_tag_blind) == (3, 2)
        assert one_row([rec("a", 20)]).naming_gap is None

    def test_cost_flags_aggregate_rather_than_assign(self):
        econ = dict(family="economics")
        row = one_row(
            [
                rec("a", **econ, extra={"cost_per_doc": 0.1}, warnings=("cost_partial",)),
                rec("b", **econ, extra={"cost_per_doc": 0.3}, warnings=("no_usage_telemetry",)),
            ]
        )
        assert row.cost_per_doc_usd == pytest.approx(0.2)
        assert row.cost_partial is True  # any
        assert row.usage_present is False  # all

    def test_role_prices_are_appended_and_blank_when_absent(self):
        econ = {"cost_per_page_transcribe": 0.0012345, "cost_per_page_pipeline": 0.002}
        grid, _ = aggregate(
            [rec("a", 50, family="economics", extra=econ), rec("b", 60)],
            cells={"c1": cell()},
            evidence={},
        )
        (row,) = parsed(grid)
        assert row["cost_per_page_transcribe_usd"] == "0.001234"
        assert row["cost_per_page_label_usd"] == ""
        assert row["cost_per_page_pipeline_usd"] == "0.002"


class TestGrouping:
    def test_model_and_schema_tier_are_part_of_the_key(self):
        cells = {
            "c1": cell("c1"),
            "c2": cell("c2", **{"generation.label_model": "anthropic/claude-sonnet-5"}),
            "c3": cell("c3", schema_tier="rich"),
        }
        grid, _ = aggregate(
            [rec("a", 10, cell="c1"), rec("a", 90, cell="c2"), rec("a", 50, cell="c3")],
            cells=cells,
            evidence={},
        )
        keys = [(r.key.schema_tier, r.key.config_tier, r.mean_quality) for r in grid.rows]
        assert keys == [("none", "haiku", 10), ("none", "sonnet", 90), ("rich", "haiku", 50)]
        assert all(r.key.shape == r.key.doc_type == "form" for r in grid.rows)

    def test_the_axes_survive_as_json(self):
        grid, _ = aggregate([rec("a", 10)], cells={"c1": cell(window_size=10)}, evidence={})
        (row,) = parsed(grid)
        assert json.loads(row["axes_json"])["window_size"] == "10"

    def test_missing_maps_are_said_not_silently_passed(self):
        grid, _ = aggregate([rec("a", 10)])
        assert grid.rows[0].key.model == ""
        assert len(grid.warnings) == 2


class TestCsvContract:
    def test_column_order(self):
        assert ",".join(GRID_BASE_COLUMNS) == BASE_HEADER
        assert GRID_HEADER == GRID_BASE_COLUMNS + GRID_EXTRA_COLUMNS + GRID_ROLE_PRICE_COLUMNS
        assert GRID_EXTRA_COLUMNS[0] == "comparable" and GRID_EXTRA_COLUMNS[-1] == "axes_json"

    def test_formatting(self):
        records = [
            rec("a", 61.23456, extra={"cost_per_doc": 0.123456}, family="extraction"),
            rec("b", 70),
        ]
        grid, _ = aggregate(records, cells={"c1": cell()}, evidence={})
        (row,) = parsed(grid)
        assert row["mean_quality"] == str(round((61.23456 + 70) / 2, 2))
        assert row["cost_per_doc_usd"] == "0.1235"
        assert row["single_docset"] == "False" and row["comparable"] == "False"
        assert row["validity_warnings"] == "too_few_docsets"
        assert grid_csv(grid) == grid_csv(grid)

    def test_an_unscored_row_writes_blank_quality_and_a_measured_zero_survives(self):
        grid, _ = aggregate(
            [rec("a", family="economics"), rec("a", 0.0, cell="c2")],
            cells={"c1": cell("c1"), "c2": cell("c2", shape="prose_narrative")},
            evidence={},
        )
        rows = {r["shape"]: r for r in parsed(grid)}
        assert rows["form"]["mean_quality"] == "" and rows["form"]["band_2se"] == ""
        assert rows["prose_narrative"]["mean_quality"] == "0.0"


class TestPivot:
    def test_band_n_and_gate_marks(self):
        cells = {
            "c1": cell("c1"),
            "c2": cell("c2", shape="prose_narrative"),
            "c3": cell("c3", schema_tier="rich"),
        }
        records = [rec(d, 60 + i, cell="c1") for i, d in enumerate("abc")]
        records += [rec("a", 50, cell="c2"), rec("a", 99, cell="c3")]
        grid, _ = aggregate(records, cells=cells, evidence={})
        table = pivot(grid)
        assert table[0] == ["shape", "anthropic/claude-haiku-4-5"]
        assert table[1][1].startswith("61.00 ±")  # three docsets beat one at schema rich
        assert table[2] == ["prose_narrative", "50.00 (n=1) !"]
        with pytest.raises(ValueError, match="cannot pivot"):
            pivot(grid, "model")


class TestRunLoading:
    def test_malformed_and_missing_records_are_errors(self, tmp_path):
        with pytest.raises(CompassError, match="dgc score"):
            load_metric_records(tmp_path)
        (tmp_path / "metrics").mkdir()
        (tmp_path / "metrics" / "x.jsonl").write_text("\n{not json}\n")
        with pytest.raises(CompassError, match="line 2"):
            load_metric_records(tmp_path)

    def test_a_missing_manifest_names_itself(self, tmp_path):
        with pytest.raises(CompassError, match="no manifest"):
            aggregate_run(tmp_path)

    def test_dry_run_writes_nothing(self, fresh_runs):
        run = fresh_runs["20261008-140547-4fe5464b"]
        result = aggregate_run(run, dry_run=True)
        assert not (run / "grid").exists() and result.written == ()
        assert result.summary()[0] == "3 grid rows from 96 metric records"

    def test_the_floor_reaches_the_gates_and_validity(self, fresh_runs):
        run = fresh_runs["20261008-140547-4fe5464b"]
        result = aggregate_run(run, min_docsets=2)
        assert result.validity["min_docsets"] == 2
        assert result.validity["counts"] == {"single_docset": 1, "too_few_docsets": 1}
        assert {p.name for p in result.written} == {"compass_grid.csv", "validity.json"}
