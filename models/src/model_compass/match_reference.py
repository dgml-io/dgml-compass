"""How closely does a scored run match the reference results? Pairs each cell of the run with
the cells of ``results/reference/<spec>/cells.csv`` and reports the quality, token and cost
differences. No model is called and nothing is re-scored.

    dgc score -r <run>                    # the run must be scored first
    dgc reference match <run>
    dgc reference match <run> --spec compass-baseline-haiku55 -o out.md

A run cell is paired with a reference cell in one of two ways:

    same cell     equal ``cell_id``: same settings, docset and seed -- a re-run of that cell
    same models   equal docset, transcriber, labeler and thinking, but a different cell id
                  (another seed, document sample or fixed setting): indicative only

A pair *matches* when the quality difference is within ``--tolerance`` points (default 5;
re-runs land within a few points) or within 2 sd of the reference's draws, whichever is wider,
and tokens per document are within a factor of ``--token-ratio`` (default 2) of the reference.

Exit codes follow ``dgc``: 0 every pair matches, 1 error, 2 findings (a pair outside tolerance,
nothing paired, or the run not scored).
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from model_compass.config import MODELS_DIR
from model_compass.errors import CompassError
from model_compass.reference import cell_rows
from model_compass.runs import load_cells, load_manifest

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_REFERENCE = MODELS_DIR / "results" / "reference"
CONFIG_KEYS = ("docset", "transcriber", "labeler", "thinking")
COLUMN_SETTINGS = {"generation.model", "generation.label_model", "generation.thinking"}


def _float(value: Any) -> float | None:
    return None if value in ("", None) else float(value)


@dataclass
class Pair:
    run: dict[str, Any]
    ref: dict[str, str]
    spec: str
    kind: str  # "same cell" | "same models"
    tolerance: float = 0.0
    quality_delta: float | None = None
    blind_delta: float | None = None
    token_ratio: float | None = None
    cost_ratio: float | None = None
    verdict: str = ""
    notes: list[str] = field(default_factory=list)


def load_references(
    root: Path, spec: str | None
) -> list[tuple[dict[str, Any], list[dict[str, str]]]]:
    paths = sorted(root.glob("*/summary.json"))
    if spec:
        paths = [p for p in paths if p.parent.name == spec]
        if not paths:
            raise SystemExit(f"error: no reference set {spec!r} under {root}")
    if not paths:
        raise SystemExit(f"error: no <spec>/summary.json under {root}")
    sets = []
    for path in paths:
        info = json.loads(path.read_text(encoding="utf-8"))
        with (path.parent / "cells.csv").open(encoding="utf-8") as fh:
            sets.append((info, list(csv.DictReader(fh))))
    return sets


def pair_cells(run_rows, sets) -> tuple[list[Pair], list[dict[str, Any]]]:
    """Same-cell pairs when there are any for a run cell, else same-models pairs."""
    pairs: list[Pair] = []
    unpaired = []
    for row in run_rows:
        exact, loose = [], []
        for info, cells in sets:
            for ref in cells:
                if ref["cell_id"] == row["cell_id"]:
                    exact.append(Pair(row, ref, info["spec"], "same cell"))
                elif all(str(row[k]) == ref[k] for k in CONFIG_KEYS):
                    loose.append(Pair(row, ref, info["spec"], "same models"))
        found = _dedupe(exact or loose)
        pairs += found
        if not found:
            unpaired.append(row)
    return pairs, unpaired


def _dedupe(found: list[Pair]) -> list[Pair]:
    """One pair per reference cell: sweeps imported from one run share cells and numbers."""
    kept: dict[tuple[str, str, str], Pair] = {}
    for pair in found:
        key = (pair.ref["cell_id"], pair.ref["quality"], pair.ref["total_tokens"])
        if key in kept:
            kept[key].spec += f", {pair.spec}"
        else:
            kept[key] = pair
    return list(kept.values())


def judge(pair: Pair, tolerance: float, token_ratio: float) -> Pair:
    run, ref = pair.run, pair.ref
    sd = _float(ref["quality_sd_draws"]) or 0.0
    pair.tolerance = max(tolerance, 2 * sd)
    rq, fq = _float(run["quality"]), _float(ref["quality"])
    if rq is not None and fq is not None:
        pair.quality_delta = rq - fq
    rb, fb = _float(run["tag_blind_recall"]), _float(ref["tag_blind_recall"])
    if rb is not None and fb is not None:
        pair.blind_delta = rb - fb
    rt, ft = _float(run["tokens_per_doc"]), _float(ref["tokens_per_doc"])
    if rt and ft:
        pair.token_ratio = rt / ft
    rc, fc = _float(run["cost_per_doc_usd"]), _float(ref["cost_per_doc_usd"])
    if rc and fc:
        pair.cost_ratio = rc / fc

    if run["status"] and run["status"] != "succeeded":
        pair.notes.append(f"run cell {run['status']}")
    if int(run["documents"] or 0) and int(ref["documents"] or 0):
        run_docs = int(run["documents"]) / max(int(run["draws"]), 1)
        ref_docs = int(ref["documents"]) / max(int(ref["draws"]), 1)
        if round(run_docs) != round(ref_docs):
            pair.notes.append(f"{run_docs:g} vs {ref_docs:g} docs/draw")
    if run["draws"] != int(ref["draws"] or 0):
        pair.notes.append(f"{run['draws']} vs {ref['draws']} draws")

    if pair.quality_delta is None:
        pair.verdict = "no quality"
    elif abs(pair.quality_delta) > pair.tolerance:
        pair.verdict = "off"
    elif pair.token_ratio is not None and not (1 / token_ratio <= pair.token_ratio <= token_ratio):
        pair.verdict = "off"
        pair.notes.append("tokens/doc outside range")
    else:
        pair.verdict = "match"
    return pair


def provenance_notes(run_dir: Path, run_rows, sets, specs_used: set[str]) -> list[str]:
    """Why a same-cell pair may still not be a strict re-run: corpus, dgml, fixed settings."""
    manifest = load_manifest(run_dir)
    prov = manifest.provenance
    dgml = prov.repos.get("dgml")
    run_settings = {}
    if run_rows:
        run_settings = next(iter(load_cells(run_dir).values())).settings_dict
    notes = []
    for info, _ in sets:
        if info["spec"] not in specs_used:
            continue
        ref = info.get("provenance", {})
        diffs = []
        if ref.get("corpus_hash") and ref["corpus_hash"] != prov.corpus_hash:
            diffs.append(f"corpus hash {prov.corpus_hash} vs {ref['corpus_hash']}")
        commit = dgml.commit if dgml else None
        if ref.get("dgml_commit") and ref["dgml_commit"] != commit:
            diffs.append(f"dgml commit {str(commit)[:10]} vs {ref['dgml_commit'][:10]}")
        if dgml and dgml.dirty:
            diffs.append("run's dgml checkout was dirty")
        for key, value in sorted(info.get("fixed", {}).items()):
            if key in COLUMN_SETTINGS or key not in run_settings:
                continue
            if str(run_settings[key]) != str(value):
                diffs.append(f"{key}={run_settings[key]} vs {value}")
        if diffs:
            notes.append(f"`{info['spec']}`: " + "; ".join(diffs))
    return notes


def _fmt(value: float | None, pattern: str) -> str:
    return "—" if value is None else pattern.format(value)


def render(run_dir: Path, manifest, pairs, unpaired, notes, args) -> str:
    matched = sum(p.verdict == "match" for p in pairs)
    exact = [p for p in pairs if p.kind == "same cell"]
    lines = [
        f"# Run `{manifest.run_id}` (`{manifest.spec.name}`) against `{args.reference.name}`",
        "",
        f"**{matched}/{len(pairs)} pairs match** "
        f"({len(exact)} same-cell, {len(pairs) - len(exact)} same-models); "
        f"{len(unpaired)} run cell(s) have no reference. "
        f"Tolerance: quality within max({args.tolerance:g}, 2·sd of the reference draws) points, "
        f"tokens/doc within {args.token_ratio:g}×.",
        "",
    ]
    if pairs and not exact:
        lines += [
            "No cell of this run is a re-run of a reference cell (different seed, document "
            "sample or settings), so these are same-models comparisons: indicative, not a "
            "reproduction check. Runs of one or two documents score low on extraction.",
            "",
        ]
    if pairs:
        lines += [
            "| verdict | pairing | reference spec | shape | docset | transcriber → labeler "
            "| quality run / ref | Δ quality | tol | Δ tag-blind | tokens/doc × | cost/doc × "
            "| notes |",
            "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
        for p in sorted(pairs, key=lambda p: (p.verdict != "off", p.run["docset"], p.spec)):
            models = f"`{p.ref['transcriber']}` → `{p.ref['labeler']}`"
            if p.ref["thinking"]:
                models += f" (thinking {p.ref['thinking']})"
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"**{p.verdict}**" if p.verdict == "off" else p.verdict,
                        p.kind,
                        ", ".join(f"`{s}`" for s in p.spec.split(", ")),
                        p.ref["shape"],
                        p.ref["docset"],
                        models,
                        f"{p.run['quality'] or '—'} / {p.ref['quality'] or '—'}",
                        _fmt(p.quality_delta, "{:+.1f}"),
                        f"{p.tolerance:.1f}",
                        _fmt(p.blind_delta, "{:+.1f}"),
                        _fmt(p.token_ratio, "{:.2f}"),
                        _fmt(p.cost_ratio, "{:.2f}"),
                        "; ".join(p.notes),
                    ]
                )
                + " |"
            )
        lines.append("")
    if unpaired:
        lines += ["## Run cells with no reference", ""]
        for row in unpaired:
            thinking = f" (thinking {row['thinking']})" if row["thinking"] else ""
            lines.append(
                f"- `{row['cell_id']}` {row['docset']}: `{row['transcriber']}` → "
                f"`{row['labeler']}`{thinking}"
            )
        lines.append("")
    if notes:
        lines += ["## Provenance differences", ""]
        lines += [f"- {n}" for n in notes]
        lines += [
            "",
            "`dgc compare` would mark these rows not comparable; deltas above still show how "
            "far apart the numbers are.",
            "",
        ]
    return "\n".join(lines)


def match(args) -> int:
    """``dgc reference match``: ``args`` carries run_dir, reference, spec, tolerance, token_ratio,
    out, json and dry_run."""

    run_dir = args.run_dir.resolve()
    if not (run_dir / "manifest.json").is_file():
        print(f"error: {run_dir} is not a run directory (no manifest.json)", file=sys.stderr)
        return 1
    manifest = load_manifest(run_dir)
    try:
        run_rows = cell_rows(run_dir)
    except CompassError:
        run_rows = []
    if not any(r["quality"] for r in run_rows):
        print(
            f"error: run {manifest.run_id} has no extraction scores; "
            f"run `dgc score -r {manifest.run_id}` first",
            file=sys.stderr,
        )
        return 2
    sets = load_references(args.reference, args.spec)
    pairs, unpaired = pair_cells(run_rows, sets)
    pairs = [judge(p, args.tolerance, args.token_ratio) for p in pairs]
    specs_used = {s for p in pairs for s in p.spec.split(", ")}
    notes = provenance_notes(run_dir, run_rows, sets, specs_used)
    text = render(run_dir, manifest, pairs, unpaired, notes, args)
    print(text)
    if args.out and not args.dry_run:
        args.out.write_text(text, encoding="utf-8")
    if args.json and not args.dry_run:
        payload = [
            {
                "verdict": p.verdict,
                "pairing": p.kind,
                "reference_specs": p.spec.split(", "),
                "run_cell_id": p.run["cell_id"],
                "reference_cell_id": p.ref["cell_id"],
                "docset": p.ref["docset"],
                "quality_run": _float(p.run["quality"]),
                "quality_reference": _float(p.ref["quality"]),
                "quality_delta": p.quality_delta,
                "tolerance": p.tolerance,
                "tag_blind_delta": p.blind_delta,
                "tokens_per_doc_ratio": p.token_ratio,
                "cost_per_doc_ratio": p.cost_ratio,
                "notes": p.notes,
            }
            for p in pairs
        ]
        args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0 if pairs and all(p.verdict == "match" for p in pairs) else 2
