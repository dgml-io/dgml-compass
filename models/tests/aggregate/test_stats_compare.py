"""Paired statistics and run comparison."""

from __future__ import annotations

import math

import pytest

from model_compass.aggregate.compare import (
    Verdict,
    compare_grids,
    compare_runs,
    comparison_csv,
    comparison_markdown,
    render_comparison,
    verdict_for,
)
from model_compass.aggregate.grid import Grid, GridRow, GroupKey
from model_compass.aggregate.stats import bootstrap_ci, compare_arms


class TestBootstrap:
    def test_reproducible_bracketing_and_seeded(self):
        values = [1.3, 7.9, 2.2, 9.4, 5.5, 3.1]
        ci = bootstrap_ci(values)
        assert ci == bootstrap_ci(values)
        assert ci.point == pytest.approx(4.9)
        assert ci.low < ci.point < ci.high and ci.n == 6
        assert bootstrap_ci(values, resamples=50, seed=1) != bootstrap_ci(values, resamples=50)
        assert bootstrap_ci(values, statistic=lambda s: float(max(s))).point == 9.4

    def test_refusals(self):
        assert bootstrap_ci([1.0]) is None
        assert bootstrap_ci([1.0, math.nan]) is None
        assert bootstrap_ci([1.0, 2.0], statistic=lambda s: math.nan) is None
        with pytest.raises(ValueError):
            bootstrap_ci([1.0, 2.0], confidence=1.0)
        with pytest.raises(ValueError):
            bootstrap_ci([1.0, 2.0], resamples=0)
        degenerate = bootstrap_ci([5.0, 5.0, 5.0])
        assert degenerate.low == degenerate.high == 5.0


class TestCompareArms:
    def test_paired_on_shared_docsets_only(self):
        result = compare_arms({"a": 10, "b": 20, "c": 30, "x": 0}, {"a": 15, "b": 25, "c": 35})
        assert (result.n_pairs, result.n_a_only, result.n_b_only) == (3, 1, 0)
        assert result.mean_delta == 5.0 and result.wins == 3
        assert result.ci.low > 0.0

    def test_refusals_and_ties(self):
        with pytest.raises(ValueError, match="shared docsets"):
            compare_arms({"a": 1.0, "b": 2.0}, {"c": 1.0, "d": 2.0})
        with pytest.raises(ValueError, match="finite"):
            compare_arms({"a": 1.0, "b": math.nan}, {"a": 1.0, "b": 2.0})
        same = compare_arms({"a": 1.0, "b": 2.0}, {"a": 1.0, "b": 2.0})
        assert same.p_value == 1.0 and same.ties == 2


def grid(run_id, means_by_model, *, cost_partial=False):
    rows = []
    for model, means in means_by_model.items():
        mean = sum(means.values()) / len(means) if means else None
        rows.append(
            GridRow(
                key=GroupKey(shape="form", model=model),
                mean_quality=mean,
                n_docsets=len(means),
                single_docset=len(means) < 2,
                cost_partial=cost_partial,
                docset_means=means,
            )
        )
    return Grid(run_id=run_id, rows=tuple(rows))


BASE = {f"d{i}": 50.0 + i for i in range(6)}


@pytest.mark.parametrize(
    ("shift", "verdict"), [(10.0, "improved"), (-10.0, "regressed"), (0.0, "no_change")]
)
def test_verdicts(shift, verdict):
    candidate = {k: v + shift for k, v in BASE.items()}
    table = compare_grids(grid("a", {"m": BASE}), grid("b", {"m": candidate}), evidence={})
    (delta,) = table.deltas
    assert delta.verdict == verdict and delta.n_pairs == 6
    assert verdict in set(Verdict)


def test_noise_is_not_a_change_and_the_interval_decides():
    noisy = {k: v + (8 if i % 2 else -6) for i, (k, v) in enumerate(BASE.items())}
    (delta,) = compare_grids(grid("a", {"m": BASE}), grid("b", {"m": noisy}), evidence={}).deltas
    assert delta.mean_delta == pytest.approx(1.0) and delta.verdict == "no_change"
    assert verdict_for(None, None) == "no_change" and verdict_for(0.1, 2) == "improved"


def test_a_failed_gate_suppresses_the_effect_size():
    table = compare_grids(
        grid("a", {"m": BASE}), grid("b", {"m": BASE}, cost_partial=True), evidence={}
    )
    (delta,) = table.deltas
    assert delta.verdict == "not_comparable" and delta.mean_delta is None
    assert delta.validity_warnings == ("mixed_cost_partial",)
    assert render_comparison(table)[1][5:] == ["-", "mixed_cost_partial", "not_comparable"]
    assert ",not_comparable,50.0" not in comparison_csv(table)  # no number where none computed


def test_too_few_shared_docsets_and_one_sided_groups():
    a = grid("a", {"m": BASE, "only_a": BASE})
    b = grid("b", {"m": {"zz": 1.0, "yy": 2.0, "xx": 3.0, "d0": 50.0}, "only_b": BASE})
    table = compare_grids(a, b)
    (delta,) = table.deltas
    assert delta.validity_warnings == ("too_few_docsets",)
    assert [k.model for k in table.baseline_only] == ["only_a"]
    assert [k.model for k in table.candidate_only] == ["only_b"]
    assert table.warnings == (
        "no provenance supplied: the corpus, version and SHA gates did not run",
    )
    assert (
        compare_grids(grid("a", {"x": BASE}), grid("b", {"y": BASE}))
        .warnings[0]
        .startswith("the two runs share no group key")
    )


def test_markdown_and_csv(real_runs):
    a, b = real_runs["20261008-140547-4fe5464b"], real_runs["20261014-022456-37998681"]
    table = compare_runs(a, b, dry_run=True)
    assert table.written == () and not (b / "compare").exists()
    md = comparison_markdown(table)
    assert md.startswith("# Compare 20261008-140547-4fe5464b -> 20261014-022456-37998681")
    assert "3 of 3 group(s) are NOT comparable" in md
    lines = comparison_csv(table).splitlines()
    assert lines[0].startswith("unit,shape,doc_type") and len(lines) == 4
