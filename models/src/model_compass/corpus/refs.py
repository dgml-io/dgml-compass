"""Gold: the three ref artifacts of a docset, and their traps.

- A value's ``#N`` suffix indexes a token stream the corpus does not ship: provenance only,
  never matched on.
- In a complex ref, ``[]`` (verified absent) and ``null`` (unverified) are different answers.
- Under ``scope: list`` a member's value is a list of strings, not a string.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field

REF_KEY_SEP: Final[str] = "::"
"""Separator in the ``<file_id>::<label>`` gold ref key."""

_KEY = re.compile(rf"^(?P<file_id>[^:]+){REF_KEY_SEP}(?P<label>.+)$")
_VALUE = re.compile(r"^(?P<text>.*)#(?P<start_token>\d+)$", re.DOTALL)

REF_SUFFIXES: Final[tuple[str, str, str]] = ("ref.json", "ref.type.json", "complex_ref.json")
"""Flat, typed and complex gold, each at ``<docset_id>_<org>.<suffix>`` in the docset folder."""

REF_TYPES: Final[frozenset[str]] = frozenset(
    {"table", "key_value", "clause", "form", "inline_value", "heading", "list", "letterhead"}
)


def ref_filename(docset_id: str, org: str, suffix: str) -> str:
    return f"{docset_id}_{org}.{suffix}"


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ComplexScope(StrEnum):
    GROUP = "group"
    LIST = "list"
    ROW = "row"


class SpecSource(StrEnum):
    CURATED = "curated"
    AUTO = "auto"


class InstanceState(StrEnum):
    VERIFIED = "verified"
    ABSENT = "absent"
    UNVERIFIED = "unverified"


class RefKey(Frozen):
    """``<file_id>::<Label+With+Plus>`` (``+`` encodes a space)."""

    file_id: str
    label: str

    @classmethod
    def parse(cls, raw: str) -> Self:
        match = _KEY.match(raw)
        if not match:
            raise ValueError(f"{raw!r} is not a '<file_id>::<label>' ref key")
        return cls(file_id=match["file_id"], label=match["label"])

    @property
    def raw(self) -> str:
        return f"{self.file_id}{REF_KEY_SEP}{self.label}"

    @property
    def text_label(self) -> str:
        return self.label.replace("+", " ")

    def __str__(self) -> str:
        return self.raw


class RefValue(Frozen):
    """``<text>#<start token>``; the text may itself contain ``#``."""

    text: str
    start_token: int | None = None

    @classmethod
    def parse(cls, raw: str) -> Self:
        match = _VALUE.match(raw)
        if not match:
            return cls(text=raw)
        return cls(text=match["text"], start_token=int(match["start_token"]))

    @property
    def raw(self) -> str:
        return self.text if self.start_token is None else f"{self.text}#{self.start_token}"


class FlatRef(Frozen):
    """``*.ref.json``: values keyed by the raw ``file_id::label`` string."""

    docset_id: str
    org: str
    entries: dict[str, tuple[RefValue, ...]] = Field(default_factory=dict)

    @property
    def keys(self) -> tuple[RefKey, ...]:
        return tuple(RefKey.parse(raw) for raw in self.entries)

    @property
    def file_ids(self) -> frozenset[str]:
        return frozenset(raw.split(REF_KEY_SEP, 1)[0] for raw in self.entries)

    @property
    def labels(self) -> frozenset[str]:
        return frozenset(raw.split(REF_KEY_SEP, 1)[1] for raw in self.entries if REF_KEY_SEP in raw)

    @property
    def n_values(self) -> int:
        return sum(len(values) for values in self.entries.values())

    def values_for(self, key: RefKey | str) -> tuple[RefValue, ...]:
        return self.entries.get(key.raw if isinstance(key, RefKey) else key, ())


class TypedEntry(Frozen):
    type: str
    values: tuple[RefValue, ...] = ()

    @property
    def known_type(self) -> bool:
        return self.type in REF_TYPES


class TypedRef(Frozen):
    """``*.ref.type.json``: the flat ref's keys, each with a type."""

    docset_id: str
    org: str
    entries: dict[str, TypedEntry] = Field(default_factory=dict)

    @property
    def types(self) -> frozenset[str]:
        return frozenset(entry.type for entry in self.entries.values())

    def type_of(self, key: RefKey | str) -> str | None:
        entry = self.entries.get(key.raw if isinstance(key, RefKey) else key)
        return entry.type if entry else None


class ComplexTypeSpec(Frozen):
    name: str
    scope: ComplexScope
    members: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()


class ComplexInstance(Frozen):
    members: dict[str, str | tuple[str, ...] | None] = Field(default_factory=dict)


class ComplexEntry(Frozen):
    """What gold records for one (document, complex type) pair."""

    file_id: str
    type_name: str
    state: InstanceState
    instances: tuple[ComplexInstance, ...] = ()

    @property
    def counts_toward_metrics(self) -> bool:
        return self.state is not InstanceState.UNVERIFIED


class ComplexValidation(Frozen):
    files: int = 0
    instances: int = 0
    empty_files: int = 0
    dropped_files: int = 0
    xml_checked: int = 0
    xml_ok: int = 0
    accepted: bool = False


class ComplexRef(Frozen):
    """``*.complex_ref.json``: grouped gold, with verified absence preserved."""

    docset_id: str
    org: str
    derived_from: str = ""
    spec_source: SpecSource = SpecSource.CURATED
    note: str = ""
    reference_xml: str | None = None
    types: dict[str, ComplexTypeSpec] = Field(default_factory=dict)
    entries: tuple[ComplexEntry, ...] = ()
    validation: dict[str, ComplexValidation] = Field(default_factory=dict)

    @property
    def curated(self) -> bool:
        return self.spec_source is SpecSource.CURATED

    def state_for(self, file_id: str, type_name: str) -> InstanceState:
        for entry in self.entries:
            if entry.file_id == file_id and entry.type_name == type_name:
                return entry.state
        return InstanceState.UNVERIFIED

    def scored_entries(self) -> tuple[ComplexEntry, ...]:
        return tuple(entry for entry in self.entries if entry.counts_toward_metrics)
