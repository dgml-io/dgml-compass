"""Typed corpus objects: orgs, docsets, documents, and integrity findings.

A filename does not identify a document (the same name can recur across docsets); the key is
``(docset_id, name)``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import Field, field_validator

from model_compass.corpus.refs import (
    REF_SUFFIXES,
    ComplexRef,
    FlatRef,
    Frozen,
    TypedRef,
    ref_filename,
)
from model_compass.domain import Shape


class ShapeBasis(StrEnum):
    """How a shape was decided. ``name_only`` is a guess: reported, never fitted on
    (DECISIONS 0004)."""

    DOCX_TABLE = "docx_table"
    INSPECTED_SAMPLE = "inspected_sample"
    NAME_ONLY = "name_only"


class Severity(StrEnum):
    ERROR = "error"
    WARN = "warn"
    INFO = "info"


class MappingRecord(Frozen):
    """One row of ``<org>.files_mapping.json``."""

    name: str
    file_id: str
    docset_id: str
    document_status: str = ""
    ingestion_status: str = ""
    ingestion_warnings: str = ""

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> Self:
        return cls(
            name=str(raw["name"]),
            file_id=str(raw["id"]),
            docset_id=str(raw["docsetId"]),
            document_status=str(raw.get("documentStatus", "")),
            ingestion_status=str(raw.get("ingestionStatus", "")),
            ingestion_warnings=str(raw.get("ingestionWarnings", "")),
        )


class Document(Frozen):
    name: str
    path: str
    org: str
    docset_id: str
    file_id: str | None = None
    size_bytes: int = 0
    xml_path: str | None = None
    """The gold ``<stem>.dgml.xml`` beside the document, when there is one."""

    @property
    def suffix(self) -> str:
        _, _, tail = self.name.rpartition(".")
        return f".{tail.lower()}" if tail else ""

    @property
    def stem(self) -> str:
        head, _, _ = self.name.rpartition(".")
        return head or self.name

    @property
    def resolved(self) -> bool:
        return self.file_id is not None


class Docset(Frozen):
    docset_id: str
    org: str
    display_name: str | None = None
    path: str
    shape: Shape | None = None
    shape_basis: ShapeBasis | None = None
    documents: tuple[Document, ...] = ()
    xml_files: tuple[str, ...] = ()
    flat_ref: FlatRef | None = None
    typed_ref: TypedRef | None = None
    complex_ref: ComplexRef | None = None

    @property
    def ref(self) -> str:
        return f"{self.org}/{self.docset_id}"

    @property
    def has_gold(self) -> bool:
        return self.flat_ref is not None and self.typed_ref is not None

    @property
    def labels(self) -> frozenset[str]:
        return self.flat_ref.labels if self.flat_ref else frozenset()

    @property
    def fitted_on(self) -> bool:
        return self.shape is not None and self.shape_basis is not ShapeBasis.NAME_ONLY


class Org(Frozen):
    org_id: str
    docsets: tuple[Docset, ...] = ()
    mapping: tuple[MappingRecord, ...] = ()


class Finding(Frozen):
    code: str
    severity: Severity
    message: str
    org: str | None = None
    docset_id: str | None = None
    file_id: str | None = None
    count: int = 1


class IntegrityReport(Frozen):
    schema_version: int = 1
    root: str
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    findings: tuple[Finding, ...] = ()

    @property
    def errors(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.WARN)

    @property
    def ok(self) -> bool:
        return not self.errors

    def by_code(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for finding in self.findings:
            totals[finding.code] = totals.get(finding.code, 0) + finding.count
        return totals


class Corpus(Frozen):
    schema_version: int = 1
    root: str
    loaded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    orgs: tuple[Org, ...] = ()

    @field_validator("orgs")
    @classmethod
    def _unique(cls, value: tuple[Org, ...]) -> tuple[Org, ...]:
        ids = [org.org_id for org in value]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate org ids")
        return value

    @property
    def docsets(self) -> tuple[Docset, ...]:
        return tuple(d for org in self.orgs for d in org.docsets)

    @property
    def documents(self) -> tuple[Document, ...]:
        return tuple(doc for d in self.docsets for doc in d.documents)

    @property
    def labels(self) -> frozenset[str]:
        return frozenset().union(*(d.labels for d in self.docsets))

    def docset(self, org: str, docset_id: str) -> Docset | None:
        return next((d for d in self.docsets if d.org == org and d.docset_id == docset_id), None)

    def for_ref(self, ref: str) -> Corpus:
        """Narrowed to one ``org/docset``: a cell generates only its own docset (DECISIONS 0015)."""
        org_id, _, docset_id = ref.partition("/")
        orgs = []
        for org in self.orgs:
            if org.org_id != org_id:
                continue
            kept = tuple(d for d in org.docsets if d.docset_id == docset_id)
            if kept:
                orgs.append(org.model_copy(update={"docsets": kept}))
        return self.model_copy(update={"orgs": tuple(orgs)})

    def consumed_paths(self) -> tuple[str, ...]:
        """Documents, gold XML and ref files this selection depends on (feeds corpus_hash)."""
        paths: set[str] = set()
        for docset in self.docsets:
            for doc in docset.documents:
                paths.add(doc.path)
                if doc.xml_path:
                    paths.add(doc.xml_path)
            if docset.flat_ref is not None:
                paths |= {
                    f"{docset.path}/{ref_filename(docset.docset_id, docset.org, suffix)}"
                    for suffix in REF_SUFFIXES
                }
        return tuple(sorted(paths))
