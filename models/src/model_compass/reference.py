"""Reference results: run the configured sweeps, export a scored run into
``results/<set>/<spec>/``, and rebuild the summary table over such a set. ``sweep`` runs,
scores, aggregates, reports and exports each sweep, then calls ``report``; ``report`` alone
needs no key, corpus or run directory.

    dgc sweep                          # plan every configured sweep, $0
    dgc sweep --dry-run                # a run directory per sweep, $0
    dgc sweep --yes                    # paid: into results/latest/ (run it from models/)
    dgc reference export <run> --out results/reference
    dgc reference report               # rebuild results/reference/README.md

What ``export`` writes for one run, under ``<out>/<spec name>/``:

    summary.json        run id, outcome, cells, draws, documents, tokens, measured spend,
                        provenance (corpus hash, dgml version and commit, package version)
    cells.csv           one row per cell: shape, docset, transcriber, labeler, thinking,
                        quality (mean over draws), tokens, cost, seconds -- the shapes x models
                        table before any pooling
    compass_grid.csv    the aggregate grid (dgc aggregate), with its bands and gates
    validity.json
    by_shape.csv, best_by_shape.csv, gates.csv, cost_by_model.csv, failures.csv
                        the report tables (dgc report)

Nothing is re-scored: ``cells.csv`` is read off ``metrics/*.jsonl`` with the grid's quality
metric (``individual_overlap_f1``) and the economics family's counts. ``report.md`` is not
copied: its provenance block names every repository on the machine that ran the sweep.
"""

from __future__ import annotations

import csv
import json
import shutil
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from model_compass.aggregate.grid import (
    DEFAULT_QUALITY_METRIC,
    TAG_BLIND_METRIC,
    load_metric_records,
)
from model_compass.config import MODELS_DIR
from model_compass.errors import ConfigError, EngineError
from model_compass.runs import load_cells, load_manifest

GRID_FILES = ("compass_grid.csv", "validity.json")
REPORT_FILES = (
    "by_shape.csv",
    "best_by_shape.csv",
    "gates.csv",
    "cost_by_model.csv",
    "failures.csv",
)
CELL_COLUMNS = (
    "cell_id",
    "shape",
    "docset",
    "transcriber",
    "labeler",
    "thinking",
    "status",
    "draws",
    "documents",
    "pages",
    "quality",
    "quality_sd_draws",
    "tag_blind_recall",
    "total_tokens",
    "tokens_per_doc",
    "cost_usd",
    "cost_per_doc_usd",
    "cost_partial",
    "seconds_per_doc",
)
REFERENCE = MODELS_DIR / "results" / "reference"
REFERENCE_INDEX = "README.md"
SWEEPS = (
    "compass-transcribe-haiku55",
    "compass-label-haiku55",
    "compass-label-gemini-haiku55",
    "compass-transcribe-gpt55-haiku55",
    "compass-corpus-3x6-haiku55",
    "compass-baseline-haiku55",
    "compass-baseline-haiku55-think",
)
"""The configured sweeps: what ``sweep`` runs without ``--spec``."""


def _fmt(value: float | None, digits: int = 2) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


# --- export ----------------------------------------------------------------------------------


def cell_rows(run_dir: Path) -> list[dict[str, Any]]:
    """One row per planned cell, from ``cells.json``, the manifest and the metric records."""
    manifest = load_manifest(run_dir)
    cells = load_cells(run_dir)
    records = load_metric_records(run_dir)

    quality: defaultdict[str, list[float]] = defaultdict(list)
    blind: defaultdict[str, list[float]] = defaultdict(list)
    seconds: defaultdict[str, list[float]] = defaultdict(list)
    tokens: defaultdict[str, int] = defaultdict(int)
    documents: defaultdict[str, int] = defaultdict(int)
    pages: defaultdict[str, int] = defaultdict(int)
    cost: defaultdict[str, float] = defaultdict(float)
    partial: defaultdict[str, bool] = defaultdict(bool)
    draws: defaultdict[str, set[int]] = defaultdict(set)

    for record in records:
        cid = record.cell_id
        draws[cid].add(record.draw)
        if record.family == "extraction":
            if (q := record.values.get(DEFAULT_QUALITY_METRIC)) is not None:
                quality[cid].append(q)
            if (b := record.values.get(TAG_BLIND_METRIC)) is not None:
                blind[cid].append(b)
        elif record.family == "economics":
            tokens[cid] += record.counts.get("total_tokens", 0)
            documents[cid] += record.counts.get("documents", 0)
            pages[cid] += record.counts.get("pages", 0)
            cost[cid] += record.values.get("cost_usd", 0.0)
            partial[cid] |= "cost_partial" in record.warnings
            if (s := record.values.get("seconds_per_doc")) is not None:
                seconds[cid].append(s)

    rows: list[dict[str, Any]] = []
    for cid, cell in cells.items():
        settings = cell.settings_dict
        state = manifest.cells.get(cid)
        docs = documents[cid]
        rows.append(
            {
                "cell_id": cid,
                "shape": cell.shape or "",
                "docset": cell.docset,
                "transcriber": settings.get("generation.model", ""),
                "labeler": settings.get("generation.label_model", ""),
                "thinking": settings.get("generation.thinking", ""),
                "status": state.status if state else "",
                "draws": len(draws[cid]),
                "documents": docs,
                "pages": pages[cid],
                "quality": _fmt(_mean(quality[cid])),
                "quality_sd_draws": _fmt(
                    statistics.stdev(quality[cid]) if len(quality[cid]) > 1 else None
                ),
                "tag_blind_recall": _fmt(_mean(blind[cid])),
                "total_tokens": tokens[cid],
                "tokens_per_doc": _fmt(tokens[cid] / docs if docs else None, 0),
                "cost_usd": _fmt(cost[cid], 4),
                "cost_per_doc_usd": _fmt(cost[cid] / docs if docs else None, 4),
                "cost_partial": partial[cid],
                "seconds_per_doc": _fmt(_mean(seconds[cid]), 1),
            }
        )
    rows.sort(
        key=lambda r: (r["shape"], r["docset"], r["transcriber"], r["labeler"], r["thinking"])
    )
    return rows


def summary(run_dir: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    manifest = load_manifest(run_dir)
    prov = manifest.provenance
    dgml = prov.repos.get("dgml")
    grid_path = run_dir / "grid" / "compass_grid.csv"
    grid_rows = (
        list(csv.DictReader(grid_path.open(encoding="utf-8"))) if grid_path.is_file() else []
    )
    out: dict[str, Any] = {
        "schema_version": 1,
        "spec": manifest.spec.name,
        "description": manifest.spec.description,
        "run_id": manifest.run_id,
        "outcome": manifest.cells and _outcome(manifest.cells.values()),
        "cells": len(rows),
        "cells_failed": sum(1 for r in rows if r["status"] == "failed"),
        "draws_per_cell": manifest.spec.draws,
        "documents": sum(r["documents"] for r in rows),
        "total_tokens": sum(r["total_tokens"] for r in rows),
        # The manifest's spend covers the whole run as executed; an imported run also paid for
        # the cells the import dropped, so the kept cells' attributed cost is given alongside.
        "measured_usd": round(manifest.costs.actual_usd, 4),
        "cells_usd": round(sum(float(r["cost_usd"] or 0) for r in rows), 4),
        "quality_metric": DEFAULT_QUALITY_METRIC,
        "grid_rows": len(grid_rows),
        "grid_rows_comparable": sum(1 for r in grid_rows if r.get("comparable") == "True"),
        "axes": manifest.spec.axes,
        "fixed": manifest.spec.fixed,
        "provenance": {
            "corpus_hash": prov.corpus_hash,
            "dgml_version": prov.dgml_version,
            "dgml_commit": dgml.commit if dgml else None,
            "dgml_dirty": dgml.dirty if dgml else None,
            "package_version": prov.package_version,
        },
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    imported = run_dir / "import.json"
    if imported.is_file():
        info = json.loads(imported.read_text(encoding="utf-8"))
        out["imported"] = {
            "source_run": info.get("source_run"),
            "cells_kept": info.get("cells_kept"),
            "cells_dropped": len(info.get("cells_dropped", {})),
        }
    return out


def _outcome(states) -> str:
    statuses = {s.status for s in states}
    if statuses == {"succeeded"}:
        return "succeeded"
    return "partial" if "succeeded" in statuses else ",".join(sorted(statuses))


def export(run_dir: Path, out_root: Path, spec: str | None) -> Path:
    run_dir = run_dir.resolve()
    rows = cell_rows(run_dir)
    info = summary(run_dir, rows)
    target = out_root / (spec or info["spec"])
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    (target / "summary.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    with (target / "cells.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CELL_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    for sub, names in (("grid", GRID_FILES), ("report", REPORT_FILES)):
        for name in names:
            src = run_dir / sub / name
            if src.is_file():
                shutil.copyfile(src, target / name)
            else:
                print(f"note: {src} missing (run dgc {'aggregate' if sub == 'grid' else 'report'})")
    return target


# --- report ----------------------------------------------------------------------------------


def _load_set(root: Path) -> list[tuple[dict[str, Any], list[dict[str, str]]]]:
    sets = []
    for summary_path in sorted(root.glob("*/summary.json")):
        info = json.loads(summary_path.read_text(encoding="utf-8"))
        with (summary_path.parent / "cells.csv").open(encoding="utf-8") as fh:
            cells = list(csv.DictReader(fh))
        sets.append((info, cells))
    return sets


def _config(row: dict[str, str]) -> str:
    label = f"`{row['transcriber']}` → `{row['labeler']}`"
    return f"{label} (thinking {row['thinking']})" if row["thinking"] else label


def _table(header: list[str], align: list[str], rows: list[list[str]]) -> list[str]:
    return [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(align) + " |",
        *("| " + " | ".join(r) + " |" for r in rows),
        "",
    ]


def render(root: Path, sets) -> str:
    lines = [
        f"# Reference results: `{root.name}`",
        "",
        "Rebuilt by `dgc reference report` from the `summary.json` and `cells.csv` of each"
        " sweep; no model is called. Quality is `individual_overlap_f1` (0–100), the per-cell "
        "mean over draws, then the unweighted mean over the docsets of a shape; tokens and cost "
        "are summed over every draw of every cell. These are descriptive totals. The bands, "
        "comparability gates and best-by-shape rankings are in each sweep's `compass_grid.csv` "
        "and report tables -- a shape resting on one or two docsets has no trustworthy band, "
        "whatever the mean says.",
        "",
        "## Sweeps",
        "",
    ]
    rows = []
    for info, _cells in sets:
        rows.append(
            [
                f"`{info['spec']}`",
                f"`{info['run_id']}`",
                info.get("outcome", ""),
                str(info["cells"]),
                str(info["draws_per_cell"]),
                str(info["documents"]),
                f"{info['total_tokens'] / 1e6:.1f} M",
                f"${info['cells_usd']:,.2f}",
                f"${info['measured_usd']:,.2f}",
                f"{info['grid_rows_comparable']}/{info['grid_rows']}",
            ]
        )
    lines += _table(
        [
            "spec",
            "run",
            "outcome",
            "cells",
            "draws",
            "documents",
            "tokens",
            "cells' cost",
            "run spend",
            "grid rows comparable",
        ],
        ["---", "---", "---", "---:", "---:", "---:", "---:", "---:", "---:", "---:"],
        rows,
    )
    lines += [
        "*cells' cost* is the spend attributed to these cells' draws (`cells.csv`); *run spend* "
        "is what the whole run measured, which for a run imported from a larger sweep includes "
        "cells outside the bundled corpus.",
        "",
    ]

    for info, cells in sets:
        lines += [f"## `{info['spec']}`", ""]
        if info.get("description"):
            lines += [info["description"], ""]
        shapes = sorted({c["shape"] for c in cells})
        groups: dict[str, list[dict[str, str]]] = defaultdict(list)
        for c in cells:
            groups[_config(c)].append(c)
        body = []
        for config, group in groups.items():
            by_shape: dict[str, list[float]] = defaultdict(list)
            for c in group:
                if c["quality"]:
                    by_shape[c["shape"]].append(float(c["quality"]))
            docs = sum(int(c["documents"]) for c in group)
            tokens = sum(int(c["total_tokens"]) for c in group)
            cost = sum(float(c["cost_usd"] or 0) for c in group)
            n_docsets = len({c["docset"] for c in group})
            cells_q = [
                (f"{_mean(by_shape[s]):.1f} (n={len(by_shape[s])})" if by_shape.get(s) else "—")
                for s in shapes
            ]
            body.append(
                [
                    config,
                    str(n_docsets),
                    *cells_q,
                    f"{tokens / docs / 1e3:.0f} k" if docs else "—",
                    f"${cost / docs:.4f}" if docs else "—",
                    f"${cost:,.2f}",
                ]
            )
        lines += _table(
            ["transcriber → labeler", "docsets", *shapes, "tokens/doc", "cost/doc", "spend"],
            ["---", "---:", *(["---:"] * len(shapes)), "---:", "---:", "---:"],
            body,
        )
    lines += [
        "## Files",
        "",
        "Each `<spec>/` holds `summary.json`, `cells.csv` (shape × docset × models, with tokens "
        "and cost per cell), `compass_grid.csv` and `validity.json` from `dgc aggregate`, and the "
        "`dgc report` tables `by_shape.csv`, `best_by_shape.csv`, `gates.csv`, "
        "`cost_by_model.csv`, `failures.csv`. Compare a new run against one with "
        "`dgc compare <reference_run> <new_run>` when both run directories are at hand, or "
        "against these files with `cells.csv` joined on `cell_id` (ids depend only on the cell's "
        "settings, docset and seed).",
        "",
    ]
    return "\n".join(lines)


def report(root: Path, write: bool) -> str:
    sets = _load_set(root)
    if not sets:
        sys.exit(f"no <spec>/summary.json under {root} -- run `dgc sweep` or export a run first")
    text = render(root, sets)
    if write:
        (root / REFERENCE_INDEX).write_text(text, encoding="utf-8")
    return text


def _call(cmd: list[str]) -> int:
    return subprocess.call(cmd)


def _capture(cmd: list[str]) -> tuple[int, str]:
    """Run ``cmd`` and return its stdout, also printed. ``dgc run`` logs its progress on stderr,
    which is left to the terminal."""
    done = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=False)
    sys.stdout.write(done.stdout)
    return done.returncode, done.stdout


def sweep(
    specs: list[str],
    out: Path,
    dgc_flags: list[str],
    yes: bool,
    dry_run: bool,
    run_flags: list[str],
) -> int:
    """Each sweep through ``dgc`` itself, in a child process; ``dgc_flags`` are the global
    options (profile, paths) this ``dgc`` was given."""
    dgc = [sys.executable, "-m", "model_compass.cli", *dgc_flags]
    files = [f"specs/{name}.yaml" for name in specs]  # relative: the manifest records it
    if missing := [f for f in files if not Path(f).is_file()]:
        raise ConfigError(
            f"{', '.join(missing)} not found: run `dgc sweep` from models/", code="spec_missing"
        )
    if dry_run:
        for f in files:
            if code := _call([*dgc, "run", "-e", f, "--dry-run", *run_flags]):
                return code
        return 0
    if code := _call([*dgc, "plan", *(a for f in files for a in ("-e", f))]):
        return code
    if not yes:
        print(
            f"paid run of {len(specs)} sweep(s) above, capped by each spec's budget_usd: "
            "rerun with --yes to spend",
            file=sys.stderr,
        )
        return 1
    for name, f in zip(specs, files, strict=True):
        print(f"== {name}: dgc run -e {f} --yes {' '.join(run_flags)}", flush=True)
        code, output = _capture([*dgc, "run", "-e", f, "--yes", *run_flags])
        if code:
            return code
        wrote = [ln.removeprefix("wrote ") for ln in output.splitlines() if ln.startswith("wrote ")]
        if not wrote:
            raise EngineError(f"dgc run -e {f} named no run directory", code="run_dir_missing")
        run_dir = Path(wrote[-1])
        print(f"== {name}: score, aggregate, report {run_dir.name}", flush=True)
        if code := _call([*dgc, "score", "-r", run_dir.name]):
            return code
        for step in ("aggregate", "report"):
            if (code := _call([*dgc, step, "-r", run_dir.name])) not in (0, 2):
                return code  # 2 = rows not comparable: reported, not an error
        export(run_dir, out, name)
    report(out, write=True)
    print(f"wrote {out / REFERENCE_INDEX}")
    return 0
