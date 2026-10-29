"""Draw figures/quality_cost.svg: quality against cost per document, one point per pipeline
(transcriber -> labeler) of docs/RESULTS.md §6. Every value is recomputed from the committed
``results/reference/<spec>/cells.csv`` the way RESULTS.md computes it: quality is the
unweighted mean over the 9 docsets of the per-cell mean over draws, its bar is +/- 2 standard
errors between docsets, and cost per document is the cells' cost over the documents produced.
No model is called.

    dgc figure
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING

from model_compass.aggregate.grid import _mean_of_means
from model_compass.config import MODELS_DIR
from model_compass.errors import ConfigError

if TYPE_CHECKING:
    from pathlib import Path

REFERENCE = MODELS_DIR / "results" / "reference"
OUT = MODELS_DIR / "figures" / "quality_cost.svg"

NAMES = {
    "anthropic/claude-haiku-5-5": "Haiku 5.5",
    "anthropic/claude-sonnet-5": "Sonnet 5",
    "anthropic/claude-opus-5": "Opus 5",
    "openai/gpt-5.5": "GPT-5.5",
    "gemini/gemini-3.6-flash": "Gemini 3.6 Flash",
    "gemini/gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite",
}
HAIKU, SONNET, OPUS = (
    "anthropic/claude-haiku-5-5",
    "anthropic/claude-sonnet-5",
    "anthropic/claude-opus-5",
)
GPT, GEMINI, LITE = "openai/gpt-5.5", "gemini/gemini-3.6-flash", "gemini/gemini-3.1-flash-lite"

# group: "base" Haiku 5.5 in both roles; "labeler" the labeler varies under a Haiku 5.5
# transcriber (§1); "transcriber" the transcriber varies under a Haiku 5.5 labeler (§2);
# "older" the §4 / §5 sweeps, on an earlier dgml build. The label offset (dx, dy, anchor)
# is placed by hand so that no two labels collide.
PIPELINES = (
    ("compass-label-haiku55", HAIKU, HAIKU, "base", (12, 5, "start")),
    ("compass-label-haiku55", HAIKU, SONNET, "labeler", (-12, 4, "end")),
    ("compass-label-haiku55", HAIKU, OPUS, "labeler", (-12, -10, "end")),
    ("compass-label-haiku55", HAIKU, GPT, "labeler", (12, -10, "start")),
    ("compass-label-haiku55", HAIKU, GEMINI, "labeler", (12, 4, "start")),
    ("compass-label-haiku55", HAIKU, LITE, "labeler", (12, 4, "start")),
    ("compass-transcribe-haiku55", SONNET, HAIKU, "transcriber", (-12, 16, "end")),
    ("compass-transcribe-haiku55", OPUS, HAIKU, "transcriber", (12, 18, "start")),
    ("compass-transcribe-haiku55", GPT, HAIKU, "transcriber", (0, -14, "middle")),
    ("compass-transcribe-haiku55", GEMINI, HAIKU, "transcriber", (-12, 4, "end")),
    ("compass-label-gemini", GEMINI, GEMINI, "older", (12, 4, "start")),
    ("compass-label-gemini", GEMINI, LITE, "older", (12, 4, "start")),
    ("compass-label-gemini", GEMINI, GPT, "older", (12, 22, "start")),
    ("compass-transcribe-gpt55", GPT, GPT, "older", (12, 5, "start")),
)

LEGEND = (
    ("base", "Haiku 5.5 in both roles"),
    ("labeler", "labeler varies, transcriber Haiku 5.5"),
    ("transcriber", "transcriber varies, labeler Haiku 5.5"),
    ("older", "earlier dgml build (RESULTS §4, §5)"),
)


@dataclass(frozen=True)
class Point:
    transcriber: str
    labeler: str
    group: str
    quality: float
    band_2se: float
    cost_per_doc: float
    label_offset: tuple[int, int, str]

    @property
    def label(self) -> str:
        return f"{NAMES[self.transcriber]} → {NAMES[self.labeler]}"


def points(reference: Path = REFERENCE) -> list[Point]:
    cells: dict[str, list[dict[str, str]]] = {}
    out = []
    for spec, transcriber, labeler, group, offset in PIPELINES:
        if spec not in cells:
            with (reference / spec / "cells.csv").open(encoding="utf-8") as f:
                cells[spec] = list(csv.DictReader(f))
        rows = [
            r
            for r in cells[spec]
            if r["transcriber"] == transcriber and r["labeler"] == labeler and not r["thinking"]
        ]
        per_docset = {r["docset"]: [float(r["quality"])] for r in rows if r["quality"]}
        quality, _, band, _ = _mean_of_means(per_docset)
        documents = sum(int(r["documents"]) for r in rows)
        if quality is None or band is None or not documents:
            raise ConfigError(
                f"{spec}/cells.csv has no band for {transcriber} -> {labeler}: it needs two "
                "scored docsets and some documents",
                code="figure_pipeline_missing",
            )
        cost = sum(float(r["cost_usd"]) for r in rows)  # every cell's cost, as RESULTS.md counts it
        out.append(Point(transcriber, labeler, group, quality, band, cost / documents, offset))
    return out


# geometry: log-scale cost on x, quality on y
W, H = 900, 540
X0, X1, Y0, Y1 = 76, 870, 64, 464
COST_MIN, COST_MAX = 0.015, 5.0
Q_MIN, Q_MAX = 50.0, 95.0
COST_TICKS = (0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0)

STYLE = (
    ".bg{fill:#ffffff}.ring{stroke:#ffffff}.fg{fill:#1f2328}.mu{fill:#59636e}"
    ".grid{stroke:#e4e6ea}"
    ".base{fill:#1f2328}.labeler{fill:#2563c9}.transcriber{fill:#d9661f}"
    ".older{fill:#ffffff;stroke:#8c959f}"
    ".bar-base{stroke:#1f2328}.bar-labeler{stroke:#2563c9}.bar-transcriber{stroke:#d9661f}"
    ".bar-older{stroke:#8c959f}"
    "@media (prefers-color-scheme: dark){.bg{fill:#0d1117}.ring{stroke:#0d1117}.fg{fill:#e6edf3}"
    ".mu{fill:#9198a1}.grid{stroke:#262c36}.base{fill:#e6edf3}"
    ".labeler{fill:#3987e5}.transcriber{fill:#d95926}.older{fill:#0d1117;stroke:#8c959f}"
    ".bar-base{stroke:#e6edf3}.bar-labeler{stroke:#3987e5}.bar-transcriber{stroke:#d95926}}"
)


def _x(cost: float) -> float:
    span = math.log10(COST_MAX) - math.log10(COST_MIN)
    return X0 + (math.log10(cost) - math.log10(COST_MIN)) / span * (X1 - X0)


def _y(quality: float) -> float:
    return Y1 - (quality - Q_MIN) / (Q_MAX - Q_MIN) * (Y1 - Y0)


def _marker(group: str, x: float, y: float) -> str:
    if group == "transcriber":
        return (
            f'<rect class="{group} ring" x="{x - 6:.1f}" y="{y - 6:.1f}" width="12" height="12" '
            f'rx="2" stroke-width="2"/>'
        )
    if group == "older":
        return f'<circle class="older" cx="{x:.1f}" cy="{y:.1f}" r="5.5" stroke-width="2"/>'
    return f'<circle class="{group} ring" cx="{x:.1f}" cy="{y:.1f}" r="6.5" stroke-width="2"/>'


def _cost(value: float) -> str:
    return f"${value:.2f}"


def render(pts: list[Point]) -> str:
    aria = (
        "Quality against cost per document for each transcriber-labeler pipeline: the labeler "
        "buys quality as cost rises, the transcriber does not"
    )
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" '
        f'height="{H}" font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif" '
        f'role="img" aria-label="{escape(aria)}">',
        f"<style>{STYLE}</style>",
        f'<rect class="bg" width="{W}" height="{H}"/>',
        f'<text class="fg" x="{X0}" y="30" font-size="16" font-weight="600">Quality against '
        "cost per document, one point per pipeline (transcriber → labeler)</text>",
        f'<text class="mu" x="{X0}" y="50" font-size="12">Bars: ± 2 SE between the 9 docsets. '
        "Cost: provider list prices, transcription and labeling together.</text>",
    ]
    for q in range(int(Q_MIN), int(Q_MAX) + 1, 5):
        y = _y(q)
        out.append(f'<line class="grid" x1="{X0}" x2="{X1}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(
            f'<text class="mu" x="{X0 - 10}" y="{y + 4:.1f}" font-size="12" '
            f'text-anchor="end">{q}</text>'
        )
    for c in COST_TICKS:
        x = _x(c)
        out.append(f'<line class="grid" x1="{x:.1f}" x2="{x:.1f}" y1="{Y0}" y2="{Y1}"/>')
        out.append(
            f'<text class="mu" x="{x:.1f}" y="{Y1 + 20}" font-size="12" '
            f'text-anchor="middle">{_cost(c)}</text>'
        )
    out.append(
        f'<text class="fg" x="{(X0 + X1) / 2:.0f}" y="{Y1 + 46}" font-size="13" '
        'text-anchor="middle">cost per document (USD, log scale)</text>'
    )
    out.append(
        f'<text class="fg" x="20" y="{(Y0 + Y1) / 2:.0f}" font-size="13" text-anchor="middle" '
        f'transform="rotate(-90 20 {(Y0 + Y1) / 2:.0f})">quality (F1, 0–100)</text>'
    )
    for p in pts:  # bars under every marker
        x = _x(p.cost_per_doc)
        out.append(
            f'<line class="bar-{p.group}" x1="{x:.1f}" x2="{x:.1f}" '
            f'y1="{_y(p.quality - p.band_2se):.1f}" y2="{_y(p.quality + p.band_2se):.1f}" '
            'stroke-width="2" stroke-opacity=".3" stroke-linecap="round"/>'
        )
    for p in pts:
        x, y = _x(p.cost_per_doc), _y(p.quality)
        dx, dy, anchor = p.label_offset
        out.append(_marker(p.group, x, y))
        out.append(
            f'<text class="fg" x="{x + dx:.1f}" y="{y + dy:.1f}" font-size="12" '
            f'text-anchor="{anchor}">{escape(p.label)}</text>'
        )
    lx, ly = X1 - 250, Y1 - 76
    for i, (group, text) in enumerate(LEGEND):
        y = ly + i * 22
        out.append(_marker(group, lx + 8, y))
        out.append(f'<text class="fg" x="{lx + 24}" y="{y + 4}" font-size="12">{text}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def write(out: Path = OUT) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(points()), encoding="utf-8")
    return out
