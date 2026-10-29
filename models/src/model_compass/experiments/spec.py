"""The experiment spec: which corpus, which axes, how many draws, which metrics, what budget.

Field names are stable, so every earlier ``spec.resolved.yaml`` loads. A cell's id
covers org, docset, settings and seed, never the spec's name or description (DECISIONS 0002 keeps
the axis vocabulary closed).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from model_compass.corpus.sampling import SamplingMode
from model_compass.corpus.selector import CorpusSelector
from model_compass.domain import (
    AXIS_KEYS,
    SCORED_FAMILIES,
    THINKING_MODES,
    AxisValue,
    MetricFamily,
    ModelSlot,
    SchemaTier,
    TextMode,
)
from model_compass.errors import ConfigError, to_config_error
from model_compass.runs import MAX_DRAWS

SPEC_SCHEMA_VERSION: Final[int] = 1
_NAME: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_ENUM_AXES: Final[dict[str, type[SchemaTier] | type[TextMode]]] = {
    "schema_tier": SchemaTier,
    "text_mode": TextMode,
}
_MODEL_AXES: Final[frozenset[str]] = frozenset(slot.value for slot in ModelSlot)


def _coerce(key: str, value: Any) -> AxisValue:
    if key in _ENUM_AXES:
        try:
            return _ENUM_AXES[key](value).value
        except ValueError:
            allowed = ", ".join(item.value for item in _ENUM_AXES[key])
            raise ValueError(
                f"{value!r} is not a valid {key} (expected one of: {allowed})"
            ) from None
    if key == "generation.thinking":
        if value not in THINKING_MODES:
            raise ValueError(
                f"{value!r} is not a valid generation.thinking "
                f"(expected one of: {', '.join(THINKING_MODES)})"
            )
        return str(value)
    if key in _MODEL_AXES:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty model id string, got {value!r}")
        return value.strip()
    if not isinstance(value, bool | int | float | str):
        raise ValueError(f"{key} must be a scalar, got {type(value).__name__}")
    return value


def _check_keys(keys: list[str], *, where: str) -> None:
    unknown = sorted(key for key in keys if key not in AXIS_KEYS)
    if unknown:
        raise ValueError(
            f"unknown {where} key(s): {', '.join(unknown)}; "
            f"valid keys are: {', '.join(sorted(AXIS_KEYS))}"
        )


class ExperimentSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = SPEC_SCHEMA_VERSION
    name: str
    description: str = ""
    corpus: CorpusSelector
    axes: dict[str, tuple[AxisValue, ...]] = Field(default_factory=dict)
    fixed: dict[str, AxisValue] = Field(default_factory=dict)
    draws: int = Field(default=1, ge=1, le=MAX_DRAWS)
    metrics: tuple[MetricFamily, ...] = SCORED_FAMILIES
    budget_usd: float | None = Field(default=None, gt=0.0)
    seed: int | None = None

    @field_validator("name")
    @classmethod
    def _slug(cls, value: str) -> str:
        if not _NAME.match(value):
            raise ValueError(
                "must be 2-64 characters of lower-case letters, digits, '.', '_' or '-'"
            )
        return value

    @field_validator("axes")
    @classmethod
    def _valid_axes(
        cls, value: dict[str, tuple[AxisValue, ...]]
    ) -> dict[str, tuple[AxisValue, ...]]:
        _check_keys(list(value), where="axes")
        cleaned: dict[str, tuple[AxisValue, ...]] = {}
        for key, values in value.items():
            if not values:
                raise ValueError(f"axis {key!r} has no values; remove it or give it at least one")
            coerced = tuple(_coerce(key, item) for item in values)
            if len(set(coerced)) != len(coerced):
                raise ValueError(f"axis {key!r} repeats a value")
            cleaned[key] = coerced
        return cleaned

    @field_validator("fixed")
    @classmethod
    def _valid_fixed(cls, value: dict[str, AxisValue]) -> dict[str, AxisValue]:
        _check_keys(list(value), where="fixed")
        return {key: _coerce(key, item) for key, item in value.items()}

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        overlap = sorted(set(self.axes) & set(self.fixed))
        if overlap:
            raise ValueError(
                f"key(s) set in both `axes` and `fixed`: {', '.join(overlap)}; "
                "a swept key cannot also be pinned"
            )
        if not self.axes and not self.fixed:
            raise ValueError("an experiment needs at least one `axes` or `fixed` entry")
        if self.corpus.sampling is SamplingMode.RANDOM and self.seed is None:
            raise ValueError(
                "`corpus.sampling: random` needs a top-level `seed`, so that every draw's "
                "document sample can be reproduced"
            )
        return self


def load_spec(path: Path | str) -> ExperimentSpec:
    """Load and validate a spec, naming every bad field by its path."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"experiment spec not found: {path}", code="spec_missing") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}", code="spec_invalid") from exc
    if not isinstance(raw, dict):
        raise ConfigError(
            f"{path} must be a mapping at the top level, got {type(raw).__name__}",
            code="spec_invalid",
        )
    try:
        return ExperimentSpec.model_validate(raw)
    except ValidationError as exc:
        raise to_config_error(exc, source=str(path), code="spec_invalid") from exc


def dump_spec(spec: ExperimentSpec) -> str:
    """``spec.resolved.yaml``."""
    return yaml.safe_dump(
        spec.model_dump(mode="json"), sort_keys=False, allow_unicode=True, default_flow_style=False
    )
