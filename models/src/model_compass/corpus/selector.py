"""The ``corpus:`` block of a spec: which docsets, how many documents, sampled how.

Field names are stable, so every earlier ``spec.resolved.yaml`` still loads.
``orgs`` may be left empty; it is then derived from the qualified docset references.
"""

from __future__ import annotations

from typing import Any, Final, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from model_compass.corpus.sampling import SamplingMode
from model_compass.domain import Shape

SOURCE_SUFFIXES: Final[frozenset[str]] = frozenset({".pdf", ".docx"})


class DocsetSelector(BaseModel):
    """``include``/``exclude`` references, a bare list (= include), or ``all_with_refs: true``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    all_with_refs: bool = False

    @model_validator(mode="before")
    @classmethod
    def _shorthands(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"include": [value]}
        if isinstance(value, list | tuple):
            merged: dict[str, Any] = {}
            for item in value:
                if isinstance(item, dict):
                    merged.update(item)
                else:
                    merged.setdefault("include", []).append(item)
            return merged
        return value

    @model_validator(mode="after")
    def _selects_something(self) -> Self:
        if not self.include and not self.all_with_refs:
            raise ValueError("select docsets with `include: [...]` or `all_with_refs: true`")
        if self.include and self.all_with_refs:
            raise ValueError("`include` and `all_with_refs` are mutually exclusive")
        return self


class CorpusSelector(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    orgs: tuple[str, ...] = ()
    docsets: DocsetSelector
    max_files_per_docset: int = Field(default=6, ge=1, le=1000)
    shapes: tuple[Shape, ...] | None = None
    suffixes: tuple[str, ...] = (".pdf", ".docx")
    """``[.pdf]`` counts documents rather than files when a docset keeps a .docx beside a PDF."""
    sampling: SamplingMode = SamplingMode.FIXED
    require_gold: bool = True
    """``false`` keeps docsets without gold; their extraction records come back absent."""

    @field_validator("suffixes")
    @classmethod
    def _suffixes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(
            dict.fromkeys(s.lower() if s.startswith(".") else f".{s.lower()}" for s in value)
        )
        unknown = sorted(set(cleaned) - SOURCE_SUFFIXES)
        if unknown:
            raise ValueError(f"unknown suffix(es): {', '.join(unknown)}")
        if not cleaned:
            raise ValueError("`suffixes` must name at least one document type")
        return cleaned

    @property
    def org_ids(self) -> tuple[str, ...]:
        """Orgs to load: as given, else derived from qualified includes, else all."""
        if self.orgs:
            return self.orgs
        qualified = [item.split("/", 1)[0] for item in self.docsets.include if "/" in item]
        return tuple(dict.fromkeys(qualified))
