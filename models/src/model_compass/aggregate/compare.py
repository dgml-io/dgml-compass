"""Paired A/B of two runs (docs/METRICS.md §5).

Grids are joined on the group key; each matched group is compared paired over the docsets both
arms scored (between-docset variance dwarfs between-arm variance here). The gates run first and
a failure suppresses the effect size entirely: a number beside a warning gets read as a number.
The interval decides the verdict, not the point estimate or the p-value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final

from model_compass.aggregate.grid import Grid, GridRow, GroupKey, aggregate_run
from model_compass.aggregate.stats import DEFAULT_RESAMPLES, MIN_DOCSETS, compare_arms
from model_compass.aggregate.tables import csv_text, format_number, markdown_table
from model_compass.aggregate.validity import (
    DEFAULT_MIN_DOCSETS,
    CellEvidence,
    ValidityCode,
    check_comparison,
    evidence_from_manifest,
)
from model_compass.runs import load_manifest

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class Verdict(StrEnum):
    IMPROVED = "improved"
    REGRESSED = "regressed"
    NO_CHANGE = "no_change"
    NOT_COMPARABLE = "not_comparable"


COMPARE_DIR: Final[str] = "compare"


@dataclass(frozen=True)
class ArmDelta:
    key: GroupKey
    verdict: Verdict = Verdict.NOT_COMPARABLE
    baseline_quality: float | None = None
    candidate_quality: float | None = None
    mean_delta: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    p_value: float | None = None
    n_pairs: int = 0
    wins: int = 0
    losses: int = 0
    ties: int = 0
    validity_warnings: tuple[str, ...] = ()


@dataclass
class ComparisonTable:
    baseline_run_id: str = ""
    candidate_run_id: str = ""
    deltas: tuple[ArmDelta, ...] = ()
    baseline_only: tuple[GroupKey, ...] = ()
    candidate_only: tuple[GroupKey, ...] = ()
    warnings: tuple[str, ...] = ()
    written: tuple[Path, ...] = field(default=())

    @property
    def n_incomparable(self) -> int:
        return sum(1 for d in self.deltas if d.verdict == Verdict.NOT_COMPARABLE)

    @property
    def n_regressed(self) -> int:
        return sum(1 for d in self.deltas if d.verdict == Verdict.REGRESSED)


def verdict_for(ci_low: float | None, ci_high: float | None) -> Verdict:
    if ci_low is None or ci_high is None:
        return Verdict.NO_CHANGE
    if ci_low > 0.0:
        return Verdict.IMPROVED
    if ci_high < 0.0:
        return Verdict.REGRESSED
    return Verdict.NO_CHANGE


def compare_grids(
    baseline: Grid,
    candidate: Grid,
    *,
    evidence: Mapping[str, Sequence[CellEvidence]] | None = None,
    min_docsets: int = DEFAULT_MIN_DOCSETS,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = 0,
) -> ComparisonTable:
    left, right = baseline.by_key(), candidate.by_key()
    shared = sorted(set(left) & set(right), key=GroupKey.as_tuple)
    deltas = tuple(
        _compare_one(left[key], right[key], evidence, min_docsets, resamples, seed)
        for key in shared
    )
    warnings = []
    if not shared:
        warnings.append(
            "the two runs share no group key; they swept different axes and cannot be compared"
        )
    if evidence is None:
        warnings.append("no provenance supplied: the corpus, version and SHA gates did not run")
    return ComparisonTable(
        baseline_run_id=baseline.run_id,
        candidate_run_id=candidate.run_id,
        deltas=deltas,
        baseline_only=tuple(sorted(set(left) - set(right), key=GroupKey.as_tuple)),
        candidate_only=tuple(sorted(set(right) - set(left), key=GroupKey.as_tuple)),
        warnings=tuple(warnings),
    )


def _compare_one(
    baseline: GridRow,
    candidate: GridRow,
    evidence: Mapping[str, Sequence[CellEvidence]] | None,
    min_docsets: int,
    resamples: int,
    seed: int,
) -> ArmDelta:
    gate = check_comparison([baseline, candidate], evidence, min_docsets=min_docsets)
    shared_docsets = set(baseline.docset_means) & set(candidate.docset_means)
    codes = list(gate.codes)
    # Two arms measured on different docsets is not a comparison, whatever the gates say.
    if len(shared_docsets) < MIN_DOCSETS and ValidityCode.TOO_FEW_DOCSETS not in codes:
        codes.append(ValidityCode.TOO_FEW_DOCSETS)
    if codes:
        return ArmDelta(
            key=baseline.key,
            baseline_quality=baseline.mean_quality,
            candidate_quality=candidate.mean_quality,
            n_pairs=len(shared_docsets),
            validity_warnings=tuple(code.value for code in dict.fromkeys(codes)),
        )
    result = compare_arms(
        baseline.docset_means, candidate.docset_means, resamples=resamples, seed=seed
    )
    return ArmDelta(
        key=baseline.key,
        verdict=verdict_for(result.ci.low, result.ci.high),
        baseline_quality=baseline.mean_quality,
        candidate_quality=candidate.mean_quality,
        mean_delta=result.mean_delta,
        ci_low=result.ci.low,
        ci_high=result.ci.high,
        p_value=result.p_value,
        n_pairs=result.n_pairs,
        wins=result.wins,
        losses=result.losses,
        ties=result.ties,
    )


def render_comparison(table: ComparisonTable) -> list[list[str]]:
    """The display table, header first."""
    rows = [
        ["shape", "schema_tier", "model", "baseline", "candidate", "delta", "95% CI", "verdict"]
    ]
    for d in table.deltas:
        if d.verdict == Verdict.NOT_COMPARABLE:
            interval, change = ";".join(d.validity_warnings) or "gates failed", "-"
        else:
            interval = (
                f"[{d.ci_low:+.2f}, {d.ci_high:+.2f}]"
                if d.ci_low is not None and d.ci_high is not None
                else "-"
            )
            change = f"{d.mean_delta:+.2f}" if d.mean_delta is not None else "-"
        rows.append(
            [
                d.key.shape,
                d.key.schema_tier,
                d.key.model,
                format_number(d.baseline_quality, missing="-"),
                format_number(d.candidate_quality, missing="-"),
                change,
                interval,
                d.verdict,
            ]
        )
    return rows


CSV_COLUMNS: Final[tuple[str, ...]] = (
    "unit",
    "shape",
    "doc_type",
    "schema_tier",
    "config_tier",
    "model",
    "verdict",
    "baseline_quality",
    "candidate_quality",
    "mean_delta",
    "ci_low",
    "ci_high",
    "p_value",
    "n_pairs",
    "wins",
    "losses",
    "ties",
    "validity_warnings",
)


def comparison_csv(table: ComparisonTable) -> str:
    """Every delta at full precision; blank where no effect size was computed."""
    rows: list[list[object]] = [list(CSV_COLUMNS)]
    for d in table.deltas:
        numbers = (d.baseline_quality, d.candidate_quality, d.mean_delta, d.ci_low, d.ci_high)
        rows.append(
            [
                *d.key.as_tuple(),
                d.verdict,
                *("" if v is None else repr(v) for v in numbers),
                "" if d.p_value is None else repr(d.p_value),
                d.n_pairs,
                d.wins,
                d.losses,
                d.ties,
                ";".join(d.validity_warnings),
            ]
        )
    return csv_text(rows)


def comparison_markdown(table: ComparisonTable) -> str:
    rendered = render_comparison(table)
    lines = [
        f"# Compare {table.baseline_run_id} -> {table.candidate_run_id}",
        "",
        "Paired over the docsets both runs scored; the 95% CI is a docset bootstrap of the "
        "mean delta (candidate - baseline). A `not_comparable` row failed a gate and carries "
        "no effect size.",
        "",
        *markdown_table(rendered[0], ["---"] * len(rendered[0]), rendered[1:]),
    ]
    lines.append("")
    lines += [f"> {warning}" for warning in table.warnings]
    if table.baseline_only or table.candidate_only:
        lines.append(
            f"{len(table.baseline_only)} group(s) only in the baseline, "
            f"{len(table.candidate_only)} only in the candidate."
        )
    if table.n_incomparable:
        lines.append(
            f"{table.n_incomparable} of {len(table.deltas)} group(s) are NOT comparable; "
            "no effect size is reported for those."
        )
    return "\n".join(lines).rstrip("\n") + "\n"


def compare_runs(
    run_a: Path,
    run_b: Path,
    *,
    min_docsets: int = DEFAULT_MIN_DOCSETS,
    out_dir: Path | None = None,
    dry_run: bool = False,
) -> ComparisonTable:
    """``run_a`` is the baseline, ``run_b`` the candidate. Writes
    ``<out_dir>/<a>__vs__<b>.{md,csv}`` (default ``out_dir``: ``<run_b>/compare``) unless
    ``dry_run``.

    Every matched row is gated against the provenance of *all* cells of
    both runs, so a partial cell anywhere marks every row ``partial_outcome``."""
    grids: list[Grid] = []
    evidence: dict[str, list[CellEvidence]] = {}
    for run in (Path(run_a), Path(run_b)):
        grid = aggregate_run(run, min_docsets=min_docsets, dry_run=True).grid
        cells = list(evidence_from_manifest(load_manifest(run)).values())
        for row in grid.rows:
            evidence.setdefault(row.key.row_id, []).extend(cells)
        grids.append(grid)
    table = compare_grids(grids[0], grids[1], evidence=evidence, min_docsets=min_docsets)
    if not dry_run:
        out = Path(out_dir) if out_dir is not None else Path(run_b) / COMPARE_DIR
        out.mkdir(parents=True, exist_ok=True)
        stem = f"{table.baseline_run_id}__vs__{table.candidate_run_id}"
        (out / f"{stem}.md").write_text(comparison_markdown(table), encoding="utf-8")
        (out / f"{stem}.csv").write_text(comparison_csv(table), encoding="utf-8")
        table.written = (out / f"{stem}.md", out / f"{stem}.csv")
    return table
