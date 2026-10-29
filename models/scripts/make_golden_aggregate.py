"""Regenerate tests/aggregate/expected/ from the run fixtures with this repo's code.

For each ``tests/aggregate/fixtures/<run>.tar.gz`` (manifest, cells, resolved spec and
metrics of a real run, cut to the public docsets), write:

    <run>/compass_grid.csv  <run>/validity.json     aggregate_run
    <run>/pivots.json                               pivot(grid, shape | doc_type)
    <run>/report.md                                 write_report
    compare/<a>__<b>.json                           compare_runs (gated) and compare_grids
                                                    without provenance

Run it after a deliberate change to aggregation, validity, compare or the report, and say why
in docs/DECISIONS.md:

    uv run python scripts/make_golden_aggregate.py
"""

import dataclasses
import json
import shutil
import tarfile
import tempfile
from pathlib import Path

from model_compass.aggregate.compare import compare_grids, compare_runs, render_comparison
from model_compass.aggregate.grid import aggregate_run
from model_compass.aggregate.render import pivot
from model_compass.report import write_report

HERE = Path(__file__).resolve().parents[1] / "tests" / "aggregate"
FIXTURES = HERE / "fixtures"
OUT = HERE / "expected"
RUNS = sorted(p.name.removesuffix(".tar.gz") for p in FIXTURES.glob("*.tar.gz"))
PAIRS = [
    ("20260925-200000-transcr3", "20261014-022456-37998681"),
    ("20261008-140547-4fe5464b", "20261014-022456-37998681"),
]


def _plain(value):
    return list(value) if isinstance(value, tuple) else value


def _table(table) -> dict:
    return {
        "baseline_run_id": table.baseline_run_id,
        "candidate_run_id": table.candidate_run_id,
        "deltas": [
            {"key": d.key.as_dict()}
            | {f.name: _plain(getattr(d, f.name)) for f in dataclasses.fields(d) if f.name != "key"}
            for d in table.deltas
        ],
        "baseline_only": [k.as_dict() for k in table.baseline_only],
        "candidate_only": [k.as_dict() for k in table.candidate_only],
        "warnings": list(table.warnings),
    }


def main() -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for run in RUNS:
            with tarfile.open(FIXTURES / f"{run}.tar.gz") as tar:
                tar.extractall(root, filter="data")
        (OUT / "compare").mkdir(parents=True)
        for baseline, candidate in PAIRS:  # before aggregate_run writes grid/ into the copies
            gated = compare_runs(root / baseline, root / candidate, out_dir=root / "cmp")
            grids = [aggregate_run(root / r, dry_run=True).grid for r in (baseline, candidate)]
            ungated = compare_grids(*grids, evidence=None)
            payload = {
                name: {"table": _table(table), "rendered": render_comparison(table)}
                for name, table in (("gated", gated), ("no_provenance", ungated))
            }
            path = OUT / "compare" / f"{baseline}__{candidate}.json"
            path.write_text(json.dumps(payload, indent=1) + "\n")
        for run in RUNS:
            out = OUT / run
            out.mkdir()
            result = aggregate_run(root / run)
            for name in ("compass_grid.csv", "validity.json"):
                shutil.copy2(root / run / "grid" / name, out / name)
            pivots = {axis: pivot(result.grid, axis) for axis in ("shape", "doc_type")}
            (out / "pivots.json").write_text(json.dumps(pivots, indent=1) + "\n")
            (out / "report.md").write_text(write_report(root / run, dry_run=True).markdown)
            print(f"{run}: {len(result.grid.rows)} grid rows")


if __name__ == "__main__":
    main()
