"""Metric records -> the decision-grade grid (docs/METRICS.md §5).

One row per ``(unit, shape, doc_type, schema_tier, config_tier, model)`` (DECISIONS 0010). Within a
row, draws are averaged inside each docset first, then docset means are averaged with equal
weight: documents are never pooled and docsets never weighted by size (design effect 2.7-5.1).
``band_2se`` is ``2 * stdev(docset means) / sqrt(n)``; a single docset has no band, an empty
group has no ``mean_quality`` (blank, never 0.0). The pooled mean is emitted beside it only so
the disagreement with a document-pooled mean stays visible.

``compass_grid.csv`` and the pivot are rendered in ``aggregate/render.py``.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import asdict, astuple, dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from model_compass.aggregate.render import grid_csv
from model_compass.aggregate.validity import (
    DEFAULT_MIN_DOCSETS,
    CellEvidence,
    GateResult,
    check_group,
    evidence_from_manifest,
    validity_payload,
)
from model_compass.domain import ModelSlot
from model_compass.errors import CompassError
from model_compass.metrics.economics import ROLE_PRICE_METRICS
from model_compass.records import MetricRecord
from model_compass.runs import PlannedCell, load_cells, load_manifest

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

GRID_DIR: Final[str] = "grid"
GRID_FILENAME: Final[str] = "compass_grid.csv"
VALIDITY_FILENAME: Final[str] = "validity.json"

DEFAULT_QUALITY_METRIC: Final[str] = "individual_overlap_f1"
TAG_BLIND_METRIC: Final[str] = "value_only_overlap_recall"
"""Travels with the tagged number: a model can find every value and name it differently."""

MODEL_SLOT_PRECEDENCE: Final[tuple[ModelSlot, ...]] = (
    ModelSlot.LABEL,
    ModelSlot.GENERATION,
    ModelSlot.VALUES,
    ModelSlot.SCHEMA,
    ModelSlot.CLASSIFICATION,
)
"""Which slot a row's ``model`` names. Known defect 7 (docs/DECISIONS.md): a sweep over
``generation.model`` with the labeler fixed (a transcriber sweep) pools every transcriber into
one row; pinned by a strict xfail in ``tests/aggregate``."""

_FAMILY_HINTS: Final[tuple[str, ...]] = (
    "haiku",
    "sonnet",
    "opus",
    "flash-lite",  # before "flash": gemini-3.1-flash-lite contains both
    "flash",
    "pro",
    "mini",
    "nano",
    "turbo",
)


# --- run artifacts this package reads ------------------------------------------------------


def load_metric_records(run_dir: Path) -> list[MetricRecord]:
    """Every record under ``metrics/``. A malformed line is an error, not a skipped row:
    dropping one shrinks ``n_docsets`` and can flip a gate."""
    metrics = run_dir / "metrics"
    records: list[MetricRecord] = []
    paths = sorted(metrics.rglob("*.jsonl"), key=lambda p: p.relative_to(metrics).as_posix())
    for path in paths if metrics.is_dir() else ():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                records.append(MetricRecord.model_validate_json(line))
            except ValueError as exc:
                raise CompassError(
                    f"{path} line {number} is not a metric record: {exc}", code="bad_metric_record"
                ) from exc
    if not records:
        raise CompassError(
            f"no metric records under {metrics}; run `dgc score` first", code="no_metrics"
        )
    return records


# --- the grid ------------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupKey:
    unit: str = "docset"
    shape: str = ""
    doc_type: str = ""
    schema_tier: str = "none"
    config_tier: str = ""
    model: str = ""

    def as_tuple(self) -> tuple[str, ...]:
        return astuple(self)

    def as_dict(self) -> dict[str, str]:
        return asdict(self)

    @property
    def row_id(self) -> str:
        """What a row's evidence is filed under in ``compare``."""
        return "|".join(self.as_tuple())


@dataclass(frozen=True)
class GridRow:
    """One group. ``None`` is absent and written blank; ``0.0`` is always a measured zero."""

    key: GroupKey
    mean_quality: float | None = None
    tag_blind_recall: float | None = None
    naming_gap: float | None = None
    sd_between_docsets: float | None = None
    band_2se: float | None = None
    n_docsets: int = 0
    n_docsets_tag_blind: int = 0
    n_draws: int = 0
    n_documents: int = 0
    n_cells: int = 0
    single_docset: bool = True
    cost_per_doc_usd: float | None = None
    cost_partial: bool = False
    usage_present: bool = False
    comparable: bool = False
    validity_warnings: tuple[str, ...] = ()
    pooled_mean_quality: float | None = None
    run_id: str = ""
    axes: dict[str, str] = field(default_factory=dict)
    docset_means: dict[str, float] = field(default_factory=dict)
    role_prices: dict[str, float | None] = field(default_factory=dict)


@dataclass(frozen=True)
class Grid:
    run_id: str = ""
    quality_metric: str = DEFAULT_QUALITY_METRIC
    rows: tuple[GridRow, ...] = ()
    min_docsets: int = DEFAULT_MIN_DOCSETS
    n_records: int = 0
    warnings: tuple[str, ...] = ()

    def by_key(self) -> dict[GroupKey, GridRow]:
        return {row.key: row for row in self.rows}


def primary_model(settings: Mapping[str, object]) -> str:
    for slot in MODEL_SLOT_PRECEDENCE:
        if value := settings.get(slot.value):
            return str(value)
    return ""


def config_tier_for(model: str) -> str:
    """Short model-family slug, derived so it can never disagree with ``model``:
    ``anthropic/claude-haiku-4-5`` -> ``haiku``; an unknown family keeps its bare id."""
    if not model:
        return ""
    tail = model.rsplit("/", 1)[-1].lower()
    return next((hint for hint in _FAMILY_HINTS if hint in tail), tail)


def group_key_for(cell: PlannedCell | None, *, unit: str = "docset") -> GroupKey:
    settings = cell.settings_dict if cell is not None else {}
    shape = (cell.shape if cell is not None else None) or ""
    model = primary_model(settings)
    return GroupKey(
        unit=unit,
        shape=shape,
        doc_type=shape,  # the CSV carries both names for one value
        schema_tier=str(settings.get("schema_tier") or "none"),
        config_tier=config_tier_for(model),
        model=model,
    )


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _mean_of_means(
    per_docset: Mapping[str, list[float]],
) -> tuple[float | None, float | None, float | None, int]:
    """Mean of docset means, between-docset sample SD (ddof=1), 2SE half-width, n."""
    means = [statistics.fmean(values) for values in per_docset.values() if values]
    if not means:
        return None, None, None, 0
    mean = statistics.fmean(means)
    if len(means) < 2:
        return mean, None, None, len(means)
    sd = statistics.stdev(means)
    return mean, sd, 2 * sd / (len(means) ** 0.5), len(means)


def aggregate(
    records: Sequence[MetricRecord],
    *,
    cells: Mapping[str, PlannedCell] | None = None,
    evidence: Mapping[str, CellEvidence] | None = None,
    run_id: str = "",
    unit: str = "docset",
    quality_metric: str = DEFAULT_QUALITY_METRIC,
    min_docsets: int = DEFAULT_MIN_DOCSETS,
) -> tuple[Grid, tuple[GateResult, ...]]:
    """Group records into rows and gate each row. Without ``cells`` every row has an empty
    model; without ``evidence`` the provenance gates cannot fire -- both are said in
    ``Grid.warnings`` rather than passing silently."""
    cells = cells or {}

    def nested() -> defaultdict[GroupKey, defaultdict[str, list[float]]]:
        return defaultdict(lambda: defaultdict(list))

    quality, tag_blind = nested(), nested()
    draws: defaultdict[GroupKey, defaultdict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    documents: defaultdict[GroupKey, int] = defaultdict(int)
    cost: defaultdict[GroupKey, list[float]] = defaultdict(list)
    role: defaultdict[GroupKey, defaultdict[str, list[float]]] = nested()
    partial: defaultdict[GroupKey, set[bool]] = defaultdict(set)
    present: defaultdict[GroupKey, set[bool]] = defaultdict(set)
    cell_ids: defaultdict[GroupKey, set[str]] = defaultdict(set)
    axes: dict[GroupKey, dict[str, str]] = {}

    for record in records:
        cell = cells.get(record.cell_id)
        key = group_key_for(cell, unit=unit)
        cell_ids[key].add(record.cell_id)
        # The first cell's settings name the row.
        axes.setdefault(key, {k: str(v) for k, v in (cell.settings if cell else ())})
        draws[key][record.docset].add(record.draw)
        # Known defect 8: summed over every family's record, so a document counts once per
        # family that reports n_documents (pinned by a strict xfail).
        documents[key] += record.counts.get("n_documents", 0)
        if (value := record.get(quality_metric)) is not None:
            quality[key][record.docset].append(value)
        if (blind := record.get(TAG_BLIND_METRIC)) is not None:
            tag_blind[key][record.docset].append(blind)
        if (per_doc := record.get("cost_per_doc")) is not None:
            cost[key].append(per_doc)
        for name in ROLE_PRICE_METRICS:
            if (price := record.get(name)) is not None:
                role[key][name].append(price)
        if record.family == "economics":
            partial[key].add("cost_partial" in record.warnings)
            present[key].add("no_usage_telemetry" not in record.warnings)

    rows: list[GridRow] = []
    gates: list[GateResult] = []
    for key in sorted(set(quality) | set(cell_ids), key=GroupKey.as_tuple):
        mean, sd, band, n_docsets = _mean_of_means(quality[key])
        blind_mean, _, _, n_blind = _mean_of_means(tag_blind[key])
        row = GridRow(
            key=key,
            mean_quality=mean,
            tag_blind_recall=blind_mean,
            naming_gap=None if blind_mean is None or mean is None else blind_mean - mean,
            sd_between_docsets=sd,
            band_2se=band,
            n_docsets=n_docsets,
            n_docsets_tag_blind=n_blind,
            # The weakest docset governs whether a band can be trusted.
            n_draws=max((len(seen) for seen in draws[key].values()), default=0),
            n_documents=documents[key],
            n_cells=len(cell_ids[key]),
            single_docset=n_docsets < 2,
            cost_per_doc_usd=_mean(cost[key]),
            cost_partial=any(partial[key]),
            usage_present=bool(present[key]) and all(present[key]),
            pooled_mean_quality=_mean([v for vs in quality[key].values() for v in vs]),
            run_id=run_id,
            axes=axes.get(key, {}),
            docset_means={d: statistics.fmean(v) for d, v in sorted(quality[key].items()) if v},
            role_prices={name: _mean(role[key][name]) for name in ROLE_PRICE_METRICS},
        )
        contributing = [
            item for cid in sorted(cell_ids[key]) if (item := (evidence or {}).get(cid)) is not None
        ]
        gate = check_group(row, contributing, min_docsets=min_docsets)
        rows.append(replace(row, comparable=gate.comparable, validity_warnings=gate.warnings))
        gates.append(gate)

    warnings = []
    if not cells:
        warnings.append("no cell map supplied: model and schema_tier could not be resolved")
    if evidence is None:
        warnings.append("no provenance supplied: the corpus, version and SHA gates did not run")
    grid = Grid(run_id, quality_metric, tuple(rows), min_docsets, len(records), tuple(warnings))
    return grid, tuple(gates)


# --- the run-level entry point -------------------------------------------------------------


@dataclass
class AggregateResult:
    grid: Grid
    gates: tuple[GateResult, ...]
    validity: dict[str, Any]
    csv_text: str
    written: tuple[Path, ...] = ()

    @property
    def n_incomparable(self) -> int:
        return int(self.validity["n_incomparable"])

    def summary(self) -> list[str]:
        """What ``dgc aggregate`` prints."""
        lines = [f"{len(self.grid.rows)} grid rows from {self.grid.n_records} metric records"]
        lines.append(
            f"{self.validity['n_comparable']} comparable, {self.n_incomparable} not comparable"
        )
        lines += [f"  {code}: {count}" for code, count in self.validity["counts"].items()]
        lines += list(self.grid.warnings)
        lines += [f"wrote {path}" for path in self.written]
        return lines


def aggregate_run(
    run_dir: Path,
    *,
    min_docsets: int = DEFAULT_MIN_DOCSETS,
    quality_metric: str = DEFAULT_QUALITY_METRIC,
    dry_run: bool = False,
) -> AggregateResult:
    """Aggregate a scored run and write ``grid/compass_grid.csv`` and ``grid/validity.json``
    (nothing when ``dry_run``). Provenance comes from the manifest, never from records."""
    run_dir = Path(run_dir)
    manifest = load_manifest(run_dir)
    grid, gates = aggregate(
        load_metric_records(run_dir),
        cells=load_cells(run_dir),
        evidence=evidence_from_manifest(manifest),
        run_id=manifest.run_id,
        quality_metric=quality_metric,
        min_docsets=min_docsets,
    )
    result = AggregateResult(
        grid=grid,
        gates=gates,
        validity=validity_payload(manifest.run_id, min_docsets, gates),
        csv_text=grid_csv(grid),
    )
    if not dry_run:
        out = run_dir / GRID_DIR
        out.mkdir(parents=True, exist_ok=True)
        (out / GRID_FILENAME).write_text(result.csv_text, encoding="utf-8")
        payload = json.dumps(result.validity, indent=2, sort_keys=True) + "\n"
        (out / VALIDITY_FILENAME).write_text(payload, encoding="utf-8")
        result.written = (out / GRID_FILENAME, out / VALIDITY_FILENAME)
    return result
