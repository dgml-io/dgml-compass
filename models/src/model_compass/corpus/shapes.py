"""Docset → shape, from ``data/shapes.yaml``.

A docset with no entry has no shape: :meth:`ShapeMap.get` raises rather than guessing,
:meth:`ShapeMap.try_get` returns ``None``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from model_compass.config import MODELS_DIR
from model_compass.corpus.models import ShapeBasis
from model_compass.domain import Shape
from model_compass.errors import ConfigError, to_config_error

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_SHAPES_PATH: Final[Path] = MODELS_DIR / "data" / "shapes.yaml"


class UnmappedDocset(KeyError):
    """A docset has no shape. Never fall back to a guess."""


class DocsetShape(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    docset_id: str
    display_name: str = ""
    org: str = ""
    shape: Shape
    basis: ShapeBasis
    note: str = ""


class ShapeMap(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    docsets: dict[str, DocsetShape] = Field(default_factory=dict)
    not_a_docset: frozenset[str] = frozenset()
    unsourced_shapes: frozenset[Shape] = frozenset()

    def get(self, docset_id: str) -> DocsetShape:
        try:
            return self.docsets[docset_id]
        except KeyError as exc:
            raise UnmappedDocset(f"{docset_id!r} has no shape; add it to shapes.yaml") from exc

    def try_get(self, docset_id: str) -> DocsetShape | None:
        return self.docsets.get(docset_id)

    def is_docset(self, name: str) -> bool:
        return name not in self.not_a_docset


def load_shape_map(path: Path | None = None) -> ShapeMap:
    target = path or DEFAULT_SHAPES_PATH
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"shape map not found at {target}", code="shapes_missing") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{target} is not valid YAML: {exc}", code="shapes_invalid") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{target}: expected a mapping", code="shapes_invalid")
    entries: dict[str, DocsetShape] = {}
    try:
        for item in raw.get("docsets") or []:
            entry = DocsetShape.model_validate(item)
            if entry.docset_id in entries:
                raise ConfigError(
                    f"{target}: {entry.docset_id} listed twice", code="shapes_invalid"
                )
            entries[entry.docset_id] = entry
        return ShapeMap(
            docsets=entries,
            not_a_docset=frozenset(raw.get("not_a_docset") or ()),
            unsourced_shapes=frozenset(raw.get("unsourced_shapes") or ()),
        )
    except ValidationError as exc:
        raise to_config_error(exc, source=str(target), code="shapes_invalid") from exc
