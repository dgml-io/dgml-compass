"""Presentation of the grid: ``compass_grid.csv`` and the axis x model pivot.

``compass_grid.csv`` keeps a fixed column order: the 17 base columns, then the validity and
provenance block, then the role-price block -- nothing inserted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from model_compass.aggregate.tables import csv_text, format_band
from model_compass.metrics.economics import ROLE_PRICE_METRICS

if TYPE_CHECKING:
    from collections.abc import Sequence

    from model_compass.aggregate.grid import Grid

GRID_BASE_COLUMNS: Final[tuple[str, ...]] = (
    "unit",
    "shape",
    "doc_type",
    "schema_tier",
    "config_tier",
    "model",
    "mean_quality",
    "tag_blind_recall",
    "naming_gap",
    "sd_between_docsets",
    "band_2se",
    "n_docsets",
    "n_draws",
    "single_docset",
    "cost_per_doc_usd",
    "cost_partial",
    "usage_present",
)
"""Load-bearing order: readers of the grid and of grids already on disk depend on it."""

GRID_EXTRA_COLUMNS: Final[tuple[str, ...]] = (
    "comparable",
    "validity_warnings",
    "pooled_mean_quality",
    "n_documents",
    "n_cells",
    "run_id",
    "axes_json",
)
"""Appended after ``usage_present``."""

GRID_ROLE_PRICE_COLUMNS: Final[tuple[str, ...]] = tuple(f"{m}_usd" for m in ROLE_PRICE_METRICS)
"""Appended last: the per-role prices. Same aggregation as
``cost_per_doc_usd`` (mean over the group's economics records), six decimals because a
per-page price is often below a cent; blank when no record carries the value."""

GRID_HEADER: Final[tuple[str, ...]] = (
    GRID_BASE_COLUMNS + GRID_EXTRA_COLUMNS + GRID_ROLE_PRICE_COLUMNS
)


def _round(value: float | None, digits: int) -> str | float:
    return "" if value is None else round(value, digits)


def grid_csv(grid: Grid) -> str:
    """Fixed formatting (grids already on disk use it): two decimals for quality, four
    for cost, blank for absent, Python ``True``/``False``."""
    rows: list[list[object]] = [list(GRID_HEADER)]
    for row in grid.rows:
        key = row.key
        rows.append(
            [
                *key.as_tuple(),
                _round(row.mean_quality, 2),
                _round(row.tag_blind_recall, 2),
                _round(row.naming_gap, 2),
                _round(row.sd_between_docsets, 2),
                _round(row.band_2se, 2),
                row.n_docsets,
                row.n_draws,
                row.single_docset,
                _round(row.cost_per_doc_usd, 4),
                row.cost_partial,
                row.usage_present,
                row.comparable,
                ";".join(row.validity_warnings),
                _round(row.pooled_mean_quality, 2),
                row.n_documents,
                row.n_cells,
                row.run_id,
                json.dumps(row.axes, sort_keys=True, separators=(",", ":")),
                *(_round(row.role_prices.get(name), 6) for name in ROLE_PRICE_METRICS),
            ]
        )
    return csv_text(rows)


PIVOT_AXES: Final[tuple[str, ...]] = ("shape", "doc_type", "schema_tier", "config_tier")


@dataclass(frozen=True)
class PivotEntry:
    axis_value: str
    model: str
    mean_quality: float | None
    band_2se: float | None
    n_docsets: int
    comparable: bool


def render_pivot(entries: Sequence[PivotEntry], axis: str) -> list[list[str]]:
    """Axis value x model, header first. A cell is ``62.40 ±3.10``, ``62.40 (n=1)`` without a
    band, ``-`` when never measured or unscored, suffixed `` !`` when it failed its gates.
    Colliding rows keep the one with the most docsets (quality breaks the tie): averaging
    across, say, schema tiers would describe no runnable configuration."""
    best: dict[tuple[str, str], PivotEntry] = {}
    for entry in entries:
        cell_key = (entry.axis_value, entry.model)
        current = best.get(cell_key)
        if current is None or _rank(entry) > _rank(current):
            best[cell_key] = entry
    columns = sorted({model for _, model in best})
    table = [[axis, *columns]]
    for axis_value in sorted({value for value, _ in best}):
        line = [axis_value]
        for column in columns:
            entry = best.get((axis_value, column))
            if entry is None:
                line.append("-")
                continue
            text = format_band(entry.mean_quality, entry.band_2se, entry.n_docsets, missing="-")
            line.append(text + ("" if entry.comparable else " !"))
        table.append(line)
    return table


def _rank(entry: PivotEntry) -> tuple[int, float]:
    quality = entry.mean_quality if entry.mean_quality is not None else float("-inf")
    return (entry.n_docsets, quality)


def pivot(grid: Grid, axis: str = "shape") -> list[list[str]]:
    if axis not in PIVOT_AXES:
        raise ValueError(f"cannot pivot on {axis!r}; choose one of {', '.join(PIVOT_AXES)}")
    entries = [
        PivotEntry(
            str(getattr(row.key, axis)),
            row.key.model,
            row.mean_quality,
            row.band_2se,
            row.n_docsets,
            row.comparable,
        )
        for row in grid.rows
    ]
    return render_pivot(entries, axis)
