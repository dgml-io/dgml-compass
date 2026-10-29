"""Cells and draws.

A cell is one axis combination over one docset; its id hashes org, docset, settings and seed
and nothing else, so a reworded description or a rerun with more draws is the same cell. A draw
is one repeat of a cell, with its own workspace and document sample (DECISIONS 0017).
"""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING, Any, Final, Self

from pydantic import BaseModel, ConfigDict, Field

from model_compass.domain import AxisValue, ModelSlot
from model_compass.errors import ConfigError
from model_compass.ids import cell_id
from model_compass.runs import MAX_DRAWS

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from model_compass.corpus.models import Docset
    from model_compass.experiments.spec import ExperimentSpec

CELL_SCHEMA_VERSION: Final[int] = 1


class Cell(BaseModel):
    """One entry of ``cells.json``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = CELL_SCHEMA_VERSION
    cell_id: str
    org: str
    docset: str
    shape: str | None = None
    settings: tuple[tuple[str, AxisValue], ...]
    draws: int = Field(default=1, ge=1, le=MAX_DRAWS)
    seed: int | None = None

    @classmethod
    def create(
        cls,
        *,
        org: str,
        docset: str,
        settings: Mapping[str, AxisValue],
        shape: str | None = None,
        draws: int = 1,
        seed: int | None = None,
    ) -> Self:
        ordered = tuple(sorted(settings.items()))
        identity: dict[str, Any] = {
            "org": org,
            "docset": docset,
            "settings": dict(ordered),
            "seed": seed,
        }
        return cls(
            cell_id=cell_id(identity),
            org=org,
            docset=docset,
            shape=shape,
            settings=ordered,
            draws=draws,
            seed=seed,
        )

    @property
    def settings_dict(self) -> dict[str, AxisValue]:
        return dict(self.settings)

    @property
    def ref(self) -> str:
        return f"{self.org}/{self.docset}"

    def model_for(self, slot: ModelSlot) -> str | None:
        value = self.settings_dict.get(slot.value)
        return str(value) if value is not None else None

    @property
    def models(self) -> set[str]:
        return {model for slot in ModelSlot if (model := self.model_for(slot))}


class Draw(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = CELL_SCHEMA_VERSION
    draw_id: str
    cell_id: str
    index: int = Field(ge=0, lt=MAX_DRAWS)
    seed: int | None = None


def expand_cells(spec: ExperimentSpec, docsets: Sequence[Docset]) -> tuple[Cell, ...]:
    """Axis combinations vary slowest, in declaration order; docsets fastest."""
    if not docsets:
        raise ConfigError(f"experiment {spec.name!r} selects no docsets", code="empty_selection")
    keys = list(spec.axes)
    combinations = itertools.product(*(spec.axes[key] for key in keys)) if keys else [()]
    cells: list[Cell] = []
    seen: set[str] = set()
    for combination in combinations:
        settings: dict[str, AxisValue] = dict(spec.fixed)
        settings.update(dict(zip(keys, combination, strict=True)))
        for docset in docsets:
            cell = Cell.create(
                org=docset.org,
                docset=docset.docset_id,
                settings=settings,
                shape=docset.shape.value if docset.shape else None,
                draws=spec.draws,
                seed=spec.seed,
            )
            if cell.cell_id in seen:
                raise ConfigError(
                    f"duplicate cell {cell.cell_id} for {cell.ref}; the spec selects a "
                    "docset more than once",
                    code="duplicate_cell",
                )
            seen.add(cell.cell_id)
            cells.append(cell)
    return tuple(cells)


def expand_draws(cell: Cell) -> tuple[Draw, ...]:
    return tuple(
        Draw(
            draw_id=f"{cell.cell_id}-d{index:02d}",
            cell_id=cell.cell_id,
            index=index,
            seed=None if cell.seed is None else cell.seed + index,
        )
        for index in range(cell.draws)
    )
