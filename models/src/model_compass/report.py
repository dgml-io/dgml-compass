"""``report/report.md`` plus CSV tables beside it, rendered from what a run already wrote.

A report recomputes nothing: it reads ``manifest.json``, ``grid/compass_grid.csv`` and
``grid/validity.json``, so the same run directory always renders the same report. Every absent
artifact is named with the command that produces it rather than leaving a section out.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Final

from model_compass.aggregate.grid import GRID_DIR, GRID_FILENAME, VALIDITY_FILENAME
from model_compass.aggregate.render import PivotEntry, render_pivot
from model_compass.aggregate.tables import csv_text, format_band, format_number, markdown_table
from model_compass.aggregate.validity import describe_code
from model_compass.runs import MANIFEST_FILENAME, Manifest, load_manifest

REPORT_DIR: Final[str] = "report"
MD_FILENAME: Final[str] = "report.md"

_NUMERIC: Final = frozenset(
    {
        "mean_quality",
        "tag_blind_recall",
        "naming_gap",
        "sd_between_docsets",
        "band_2se",
        "cost_per_doc_usd",
        "pooled_mean_quality",
    }
)
_INTEGER: Final = frozenset({"n_docsets", "n_draws", "n_documents", "n_cells"})
_BOOLEAN: Final = frozenset({"single_docset", "cost_partial", "usage_present", "comparable"})


@dataclass(frozen=True)
class ReportRow:
    """A grid row as the CSV on disk holds it (older grids included); blank stays ``None``."""

    shape: str = ""
    schema_tier: str = "none"
    model: str = ""
    mean_quality: float | None = None
    tag_blind_recall: float | None = None
    naming_gap: float | None = None
    band_2se: float | None = None
    n_docsets: int = 0
    n_draws: int = 0
    n_documents: int = 0
    cost_per_doc_usd: float | None = None
    cost_partial: bool = False
    comparable: bool = False
    validity_warnings: tuple[str, ...] = ()

    @property
    def interval(self) -> tuple[float, float] | None:
        if self.mean_quality is None or self.band_2se is None:
            return None
        return (self.mean_quality - self.band_2se, self.mean_quality + self.band_2se)

    @property
    def band_label(self) -> str:
        return format_band(self.mean_quality, self.band_2se, self.n_docsets, missing="—")


def _coerce(name: str, raw: str) -> Any:
    text = raw.strip()
    if name in _BOOLEAN:
        return text.lower() == "true"
    if name == "validity_warnings":
        return tuple(part for part in text.split(";") if part)
    if not text:
        return None if name in _NUMERIC else (0 if name in _INTEGER else "")
    try:
        if name in _NUMERIC:
            return float(text)
        if name in _INTEGER:
            return int(float(text))
    except ValueError:
        return None if name in _NUMERIC else 0  # malformed is absent, never zero quality
    return text


def parse_grid_csv(text: str) -> list[ReportRow]:
    known = {f.name for f in fields(ReportRow)}
    return [
        ReportRow(**{k: _coerce(k, v or "") for k, v in raw.items() if k in known})
        for raw in csv.DictReader(io.StringIO(text))
    ]


@dataclass(frozen=True)
class ShapeWinner:
    shape: str
    model: str
    mean_quality: float
    band_2se: float | None
    cost_per_doc_usd: float | None
    n_docsets: int
    contested: bool  # the runner-up's 2SE band overlaps the winner's
    runner_up: str | None


@dataclass
class ReportModel:
    run_id: str
    manifest: Manifest | None = None
    grid: list[ReportRow] = field(default_factory=list)
    validity: dict[str, Any] = field(default_factory=dict)
    missing: list[tuple[str, str, str]] = field(default_factory=list)
    """``(what, path, producing command)`` for every absent artifact."""

    def missing_messages(self) -> list[str]:
        return [
            f"{what} is missing ({key}) — produced by `{cmd}`" for what, key, cmd in self.missing
        ]

    @property
    def comparable_rows(self) -> list[ReportRow]:
        return [row for row in self.grid if row.comparable]

    @property
    def n_cells(self) -> int:
        return len(self.manifest.cells) if self.manifest else 0

    @property
    def n_failed(self) -> int:
        cells = self.manifest.cells.values() if self.manifest else ()
        return sum(1 for cell in cells if cell.status == "failed")

    @property
    def outcome(self) -> str:
        return self.manifest.outcome if self.manifest else "unknown"

    def failures(self) -> list[tuple[str, str, str]]:
        cells = self.manifest.cells if self.manifest else {}
        return [
            (
                cell_id,
                cell.error_code or "unknown",
                cell.error_message.strip().splitlines()[0] if cell.error_message else "",
            )
            for cell_id, cell in sorted(cells.items())
            if cell.status in {"failed", "cancelled"}
        ]

    def gate_counts(self) -> dict[str, int]:
        counts = self.validity.get("counts")
        if isinstance(counts, dict):
            return {str(k): int(v) for k, v in sorted(counts.items())}
        tally: dict[str, int] = {}
        for row in self.grid:
            for code in row.validity_warnings:
                tally[code] = tally.get(code, 0) + 1
        return dict(sorted(tally.items()))

    def shape_winners(self) -> list[ShapeWinner]:
        """Best comparable row per shape; a shape whose rows all failed has no winner."""
        winners = []
        for shape in sorted({row.shape for row in self.grid if row.shape}):
            eligible = sorted(
                (
                    r
                    for r in self.comparable_rows
                    if r.shape == shape and r.mean_quality is not None
                ),
                key=lambda r: (-(r.mean_quality or 0.0), r.model),
            )
            if not eligible:
                continue
            best, second = eligible[0], (eligible[1] if len(eligible) > 1 else None)
            mine, theirs = best.interval, second.interval if second else None
            contested = bool(mine and theirs and mine[0] <= theirs[1] and theirs[0] <= mine[1])
            winners.append(
                ShapeWinner(
                    shape,
                    best.model,
                    best.mean_quality or 0.0,
                    best.band_2se,
                    best.cost_per_doc_usd,
                    best.n_docsets,
                    contested,
                    second.model if second else None,
                )
            )
        return winners

    def cost_by_model(self) -> list[tuple[str, float]]:
        """``cost_per_doc_usd * n_documents`` summed per model, largest first. Inherits the
        grid's ``n_documents`` (one count per family; see tests/aggregate xfails)."""
        totals: dict[str, float] = {}
        for row in self.grid:
            if row.cost_per_doc_usd is None or not row.model:
                continue
            documents = row.n_documents or row.n_docsets
            totals[row.model] = totals.get(row.model, 0.0) + row.cost_per_doc_usd * documents
        return sorted(totals.items(), key=lambda item: (-item[1], item[0]))

    def summary_line(self) -> str:
        winners = ";".join(f"{w.shape}={w.model}" for w in self.shape_winners())
        cost = self.manifest.costs.actual_usd if self.manifest else 0.0
        return (
            f"run={self.run_id} outcome={self.outcome} cells={self.n_cells} "
            f"failed={self.n_failed} cost_usd={cost:.4f} "
            f"rows={len(self.grid)} comparable={len(self.comparable_rows)} "
            f"partial={'yes' if self.missing else 'no'} "
            f"best_by_shape={winners or 'none'}"
        )

    def pivot_by_shape(self) -> list[list[str]]:
        entries = [
            PivotEntry(r.shape, r.model, r.mean_quality, r.band_2se, r.n_docsets, r.comparable)
            for r in self.grid
        ]
        return render_pivot(entries, "shape") if entries else []


def load_report_model(run_dir: Path) -> ReportModel:
    run_dir = Path(run_dir)
    model = ReportModel(run_id=run_dir.name)
    if (run_dir / MANIFEST_FILENAME).is_file():
        model.manifest = load_manifest(run_dir)
        model.run_id = model.manifest.run_id
    else:
        model.missing.append(("The run manifest", "manifest.json", "dgc run"))
    path = run_dir / GRID_DIR / GRID_FILENAME
    if path.is_file():
        model.grid = parse_grid_csv(path.read_text(encoding="utf-8"))
    else:
        model.missing.append(("The grid", f"{GRID_DIR}/{GRID_FILENAME}", "dgc aggregate"))
    path = run_dir / GRID_DIR / VALIDITY_FILENAME
    if path.is_file():
        parsed = json.loads(path.read_text(encoding="utf-8"))
        model.validity = parsed if isinstance(parsed, dict) else {}
    else:
        model.missing.append(
            ("The comparability report", f"{GRID_DIR}/{VALIDITY_FILENAME}", "dgc aggregate")
        )
    return model


# --- Markdown ------------------------------------------------------------------------------


def _money(value: float | None) -> str:
    return "—" if value is None else f"${value:,.4f}"


def render_markdown(model: ReportModel) -> str:
    """Findings first, evidence second, provenance last."""
    lines = [f"# Run {model.run_id}", ""]
    if model.missing:
        lines += [
            "> **This run is incomplete.** The report renders what exists and names what does",
            "> not, rather than leaving a section out:",
            "",
        ]
        lines += [f"> - {message}" for message in model.missing_messages()]
        lines.append("")
    for section in (_headline, _winners, _grid, _gates, _cost, _failures, _spec, _provenance):
        lines += section(model)
    lines += [
        "## Summary line",
        "",
        "One line for CI, machine-parseable:",
        "",
        "```",
        model.summary_line(),
        "```",
        "",
    ]
    return "\n".join(lines)


def _headline(model: ReportModel) -> list[str]:
    if model.manifest is None:
        return ["## What ran", "", "_No manifest: this run's outcome is unknown._", ""]
    return [
        "## What ran",
        "",
        f"- Outcome: **{model.outcome}**",
        f"- {model.n_cells} cells, {model.n_failed} failed",
        f"- Measured spend: **{_money(model.manifest.costs.actual_usd)}**",
        f"- Grid: {len(model.grid)} rows, {len(model.comparable_rows)} comparable",
        "",
    ]


def _winners(model: ReportModel) -> list[str]:
    if not model.grid:
        return []
    winners = model.shape_winners()
    lines = ["## Best model per shape", ""]
    if not winners:
        return [
            *lines,
            "_No shape has a comparable row. Every candidate failed its comparability gates, "
            "so there is no winner to name — see the gate failures below._",
            "",
        ]
    lines += [
        "Only comparable rows are eligible. **Contested** means the runner-up's 2SE band "
        "overlaps the winner's, so the ranking is not resolved by this evidence.",
        "",
    ]
    rows = [
        [
            w.shape,
            f"`{w.model}`",
            format_band(w.mean_quality, w.band_2se, missing="—"),
            _money(w.cost_per_doc_usd),
            str(w.n_docsets),
            f"yes — vs `{w.runner_up}`" if w.contested else "",
        ]
        for w in winners
    ]
    header = ["shape", "model", "quality", "cost/doc", "docsets", "contested"]
    return (
        lines + markdown_table(header, ["---", "---", "---:", "---:", "---:", ":---:"], rows) + [""]
    )


def _grid(model: ReportModel) -> list[str]:
    if not model.grid:
        return [
            "## The grid",
            "",
            "_Not available. Run `dgc aggregate` to produce `grid/compass_grid.csv`._",
            "",
        ]
    lines = [
        "## The grid",
        "",
        "Quality carries its two-standard-error band, computed between docsets. A row marked "
        "`n=1` rests on a single docset and has no band — that is not a precise number, it is "
        "an unmeasured one.",
        "",
    ]
    header = [
        "shape",
        "schema",
        "model",
        "quality (F1, 0-100)",
        "tag-blind",
        "gap",
        "docsets",
        "draws",
        "cost/doc (USD)",
        "comparable",
    ]
    rows = [
        [
            row.shape or "—",
            row.schema_tier,
            f"`{row.model or '—'}`",
            row.band_label,
            format_number(row.tag_blind_recall, missing="—"),
            format_number(row.naming_gap, missing="—"),
            str(row.n_docsets),
            str(row.n_draws),
            _money(row.cost_per_doc_usd),
            "yes" if row.comparable else "no",
        ]
        for row in model.grid
    ]
    return lines + markdown_table(header, ["---"] * 3 + ["---:"] * 6 + [":---:"], rows) + [""]


def _gates(model: ReportModel) -> list[str]:
    lines = ["## Comparability gates", ""]
    if not model.grid:
        return [*lines, "_Not available: there is no grid to check._", ""]
    counts = model.gate_counts()
    if not counts:
        return [*lines, "Every grid row passed every gate.", ""]
    lines += [
        f"{len(model.grid) - len(model.comparable_rows)} of {len(model.grid)} rows are not "
        "comparable. A non-comparable row may not be ranked against another without saying so.",
        "",
    ]
    rows = [[f"`{code}`", str(count), describe_code(code)] for code, count in counts.items()]
    return lines + markdown_table(["code", "rows", "meaning"], ["---", "---:", "---"], rows) + [""]


def _cost(model: ReportModel) -> list[str]:
    lines = ["## Cost", ""]
    by_model = model.cost_by_model()
    if not by_model:
        return [
            *lines,
            "_No measured per-document cost in the grid. `dgml` writes `usage.jsonl` only "
            "under `--debug`; without it there is no spend to attribute._",
            "",
        ]
    total = sum(value for _, value in by_model)
    lines += [f"Attributed spend totals **{_money(total)}** across {len(by_model)} models.", ""]
    rows = [[f"`{name}`", _money(v), f"{v / total * 100:.1f}%"] for name, v in by_model]
    lines += markdown_table(["model", "attributed cost", "share"], ["---", "---:", "---:"], rows)
    partial = [row for row in model.grid if row.cost_partial]
    if partial:
        lines += [
            "",
            f"> {len(partial)} row(s) carry `cost_partial`: some spend could not be attributed "
            "to a document, so those figures are a workspace total spread over documents, not a "
            "measurement. They may not be compared with unflagged rows.",
        ]
    return [*lines, ""]


def _failures(model: ReportModel) -> list[str]:
    if model.manifest is None:
        return []
    failures = model.failures()
    if not failures:
        return ["## Failures", "", "No cell failed.", ""]
    rows = [[f"`{cell}`", f"`{code}`", message or "—"] for cell, code, message in failures]
    return [
        "## Failures",
        "",
        *markdown_table(["cell", "error code", "message"], ["---"] * 3, rows),
        "",
    ]


def _spec(model: ReportModel) -> list[str]:
    if model.manifest is None:
        return []
    spec = model.manifest.spec
    lines = [
        "## What was asked for",
        "",
        f"**{spec.name}** — {spec.description or 'no description'}",
        "",
    ]
    if spec.axes:
        lines += ["Swept axes:", ""]
        lines += [
            f"- `{key}`: {', '.join(str(v) for v in values)}"
            for key, values in sorted(spec.axes.items())
        ]
        lines.append("")
    if spec.fixed:
        lines += ["Held fixed:", ""]
        lines += [f"- `{key}` = {value}" for key, value in sorted(spec.fixed.items())]
        lines.append("")
    return [
        *lines,
        f"Draws per cell: {spec.draws}. Metric families: {', '.join(spec.metrics)}.",
        "",
    ]


def _provenance(model: ReportModel) -> list[str]:
    if model.manifest is None:
        return ["## Provenance", "", "_No manifest: this run cannot be traced._", ""]
    prov = model.manifest.provenance
    lines = [
        "## Provenance",
        "",
        "Everything below is what the run recorded about itself. An artifact that cannot be "
        "traced to this block is a bug.",
        "",
    ]
    rows = [
        ["corpus hash", f"`{prov.corpus_hash or '—'}`"],
        ["dgml version", f"`{prov.dgml_version or '—'}`"],
        ["python", f"`{prov.python_version}`"],
        ["dgml-compass", f"`{prov.package_version}`"],
    ]
    rows += [
        [
            f"repo `{name}`",
            f"`{repo.commit or 'unknown'}`" + (" *(uncommitted changes)*" if repo.dirty else ""),
        ]
        for name, repo in sorted(prov.repos.items())
    ]
    lines += [*markdown_table(["field", "value"], ["---", "---"], rows), ""]
    if prov.any_dirty:
        lines += [
            "> One or more repositories had uncommitted changes when this run started, so the "
            "recorded SHAs do not fully describe the code that produced these numbers.",
            "",
        ]
    return lines


# --- CSV tables and the entry point ----------------------------------------------------------


def report_tables(model: ReportModel) -> dict[str, list[list[str]]]:
    """The report's tables as CSV rows (header first), unrounded where the source data is."""

    def opt(value: float | None) -> str:
        return "" if value is None else repr(value)

    return {
        "best_by_shape.csv": [
            [
                "shape",
                "model",
                "mean_quality",
                "band_2se",
                "cost_per_doc_usd",
                "n_docsets",
                "contested",
                "runner_up",
            ],
            *(
                [
                    w.shape,
                    w.model,
                    repr(w.mean_quality),
                    opt(w.band_2se),
                    opt(w.cost_per_doc_usd),
                    str(w.n_docsets),
                    str(w.contested),
                    w.runner_up or "",
                ]
                for w in model.shape_winners()
            ),
        ],
        "by_shape.csv": model.pivot_by_shape(),
        "gates.csv": [
            ["code", "rows", "meaning"],
            *([code, str(n), describe_code(code)] for code, n in model.gate_counts().items()),
        ],
        "cost_by_model.csv": [
            ["model", "attributed_cost_usd"],
            *([name, repr(value)] for name, value in model.cost_by_model()),
        ],
        "failures.csv": [["cell_id", "error_code", "message"], *map(list, model.failures())],
    }


@dataclass
class RenderedReport:
    run_id: str
    markdown: str
    summary: str
    tables: dict[str, list[list[str]]]
    missing: list[str]
    written: tuple[Path, ...] = ()

    @property
    def partial(self) -> bool:
        return bool(self.missing)


def write_report(run_dir: Path, *, dry_run: bool = False) -> RenderedReport:
    """Render ``<run>/report/report.md`` and its CSV tables (nothing written when
    ``dry_run``)."""
    model = load_report_model(run_dir)
    rendered = RenderedReport(
        run_id=model.run_id,
        markdown=render_markdown(model),
        summary=model.summary_line(),
        tables=report_tables(model),
        missing=model.missing_messages(),
    )
    if not dry_run:
        out = Path(run_dir) / REPORT_DIR
        out.mkdir(parents=True, exist_ok=True)
        written = [out / MD_FILENAME]
        written[0].write_text(rendered.markdown, encoding="utf-8")
        for name, rows in rendered.tables.items():
            (out / name).write_text(csv_text(rows), encoding="utf-8")
            written.append(out / name)
        rendered.written = tuple(written)
    return rendered
