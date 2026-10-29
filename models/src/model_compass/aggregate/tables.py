"""Text formatting shared by the grid, the report and the comparison.

Each caller passes its own ``missing`` placeholder: files already on disk use ``-`` in some
places and ``—`` in others, and their bytes must not change.
"""

from __future__ import annotations

import csv
import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


def format_number(value: float | None, *, missing: str) -> str:
    return missing if value is None else f"{value:.2f}"


def format_band(
    mean: float | None, band: float | None, n_docsets: int | None = None, *, missing: str
) -> str:
    """``62.40 ±3.10``; without a band ``62.40 (n=1)``, or bare ``62.40`` when ``n_docsets``
    is not given."""
    if mean is None:
        return missing
    if band is None:
        return f"{mean:.2f}" if n_docsets is None else f"{mean:.2f} (n={n_docsets})"
    return f"{mean:.2f} ±{band:.2f}"


def markdown_table(
    header: Sequence[str], align: Sequence[str], rows: Iterable[Sequence[str]]
) -> list[str]:
    return [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(align) + " |",
        *("| " + " | ".join(row) + " |" for row in rows),
    ]


def csv_text(rows: Iterable[Sequence[object]]) -> str:
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    return buffer.getvalue()
