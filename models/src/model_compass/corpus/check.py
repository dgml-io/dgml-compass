"""Integrity findings for ``dgc corpus check``. Nothing here raises: a flawed corpus is the
corpus we have. ERROR fails the command; WARN and INFO are reported. Codes are stable."""

from __future__ import annotations

import base64
import binascii
import contextlib
import re
import zlib
from typing import TYPE_CHECKING, Any, Final

from model_compass.corpus.models import Finding, IntegrityReport, Severity
from model_compass.corpus.refs import REF_TYPES

if TYPE_CHECKING:
    from pathlib import Path

    from model_compass.corpus.models import Corpus, Docset

CODES: Final[dict[str, str]] = {
    "unreadable_json": "a gold or mapping file could not be parsed",
    "mapping_missing": "an org's files_mapping.json is not a list of records",
    "incomplete_ref_triple": "a docset has some but not all of the three gold artifacts",
    "orphan_gold": "gold names a file id with no document on disk",
    "unresolved_document": "a document's (docset, name) is not in the org mapping",
    "document_without_gold": "a resolved document has no gold entries",
    "docset_without_refs": "a docset has no gold at all",
    "empty_docset": "a docset directory contains no source documents",
    "typed_ref_key_mismatch": "the typed ref's keys differ from the flat ref's",
    "unknown_ref_type": "a typed ref uses a type outside the eight measured",
    "dangling_complex_member": "a complex type names a label absent from the flat ref",
    "duplicate_filename": "a filename appears under more than one docset",
    "no_text_layer": "a PDF appears to be a scan with no extractable text",
    "unmapped_shape": "a docset has no entry in the shape map",
    "provisional_shape": "a docset's shape was guessed from its name, not inspected",
    "auto_complex_ref": "a complex ref was generated rather than hand-curated",
}


class Collector:
    def __init__(self) -> None:
        self.findings: list[Finding] = []

    def add(self, severity: Severity, code: str, message: str, **where: Any) -> None:
        if code not in CODES:
            raise AssertionError(f"unknown integrity code {code!r}; add it to CODES")
        self.findings.append(Finding(code=code, severity=severity, message=message, **where))

    def error(self, code: str, message: str, **where: Any) -> None:
        self.add(Severity.ERROR, code, message, **where)

    def warn(self, code: str, message: str, **where: Any) -> None:
        self.add(Severity.WARN, code, message, **where)

    def info(self, code: str, message: str, **where: Any) -> None:
        self.add(Severity.INFO, code, message, **where)

    def report(self, root: Path | str) -> IntegrityReport:
        return IntegrityReport(root=str(root), findings=tuple(self.findings))


def _gold(docset: Docset, out: Collector) -> None:
    where = {"org": docset.org, "docset_id": docset.docset_id}
    flat, typed, cplx = docset.flat_ref, docset.typed_ref, docset.complex_ref
    if not any((flat, typed, cplx)):
        out.info("docset_without_refs", f"{docset.ref} has no ground truth", **where)
        return
    missing = [n for n, v in (("flat", flat), ("typed", typed), ("complex", cplx)) if v is None]
    if missing:
        out.warn(
            "incomplete_ref_triple",
            f"{docset.ref} is missing the {', '.join(missing)} ref",
            **where,
        )
    present = {doc.file_id for doc in docset.documents if doc.file_id}
    if flat is not None:
        orphans = sorted(flat.file_ids - present)
        if orphans:
            shown = ", ".join(orphans[:3]) + ("..." if len(orphans) > 3 else "")
            out.warn(
                "orphan_gold",
                f"{docset.ref}: gold names {len(orphans)} file id(s) with no document on disk "
                f"({shown})",
                count=len(orphans),
                **where,
            )
        without = [d for d in docset.documents if d.file_id and d.file_id not in flat.file_ids]
        if without:
            out.info(
                "document_without_gold",
                f"{docset.ref}: {len(without)} document(s) have no gold entries",
                count=len(without),
                **where,
            )
        if typed is not None and set(flat.entries) != set(typed.entries):
            only_flat = len(set(flat.entries) - set(typed.entries))
            only_typed = len(set(typed.entries) - set(flat.entries))
            out.warn(
                "typed_ref_key_mismatch",
                f"{docset.ref}: {only_flat} key(s) only in the flat ref, "
                f"{only_typed} only in typed",
                **where,
            )
    if typed is not None and (unknown := sorted(typed.types - REF_TYPES)):
        out.warn(
            "unknown_ref_type",
            f"{docset.ref}: unfamiliar ref type(s) {', '.join(unknown)}",
            count=len(unknown),
            **where,
        )
    if cplx is not None:
        if not cplx.curated:
            out.info("auto_complex_ref", f"{docset.ref}: complex ref is auto-generated", **where)
        labels = flat.labels if flat else frozenset()
        dangling = sorted(
            {m for spec in cplx.types.values() for m in spec.members if labels and m not in labels}
        )
        if dangling:
            out.warn(
                "dangling_complex_member",
                f"{docset.ref}: complex types name {len(dangling)} label(s) absent from the flat "
                f"ref ({', '.join(dangling[:3])})",
                count=len(dangling),
                **where,
            )


def _documents_and_shape(docset: Docset, out: Collector) -> None:
    where = {"org": docset.org, "docset_id": docset.docset_id}
    if not docset.documents:
        out.info("empty_docset", f"{docset.ref} contains no source documents", **where)
    elif unresolved := [d for d in docset.documents if not d.resolved]:
        out.warn(
            "unresolved_document",
            f"{docset.ref}: {len(unresolved)} document(s) are not in the org mapping "
            f"({unresolved[0].name})",
            count=len(unresolved),
            **where,
        )
    if docset.shape is None:
        out.info("unmapped_shape", f"{docset.ref} has no entry in the shape map", **where)
    elif not docset.fitted_on:
        out.info(
            "provisional_shape",
            f"{docset.ref}: shape {docset.shape} guessed from the name",
            **where,
        )


def audit(corpus: Corpus, out: Collector) -> None:
    for docset in corpus.docsets:
        _documents_and_shape(docset, out)
        _gold(docset, out)
    seen: dict[str, set[str]] = {}
    for org in corpus.orgs:
        for record in org.mapping:
            seen.setdefault(record.name, set()).add(record.docset_id)
    if colliding := [name for name, ids in seen.items() if len(ids) > 1]:
        out.info(
            "duplicate_filename",
            f"{len(colliding)} filename(s) appear under more than one docset; "
            "resolve documents by (docset_id, name), never by name alone",
            count=len(colliding),
        )


# --- opt-in: does a PDF have a text layer? (a heuristic; None means "cannot tell") -------------

_MAX_STREAMS: Final[int] = 400
"""Streams inspected per PDF; none of them showing text means no text layer."""
_STREAM = re.compile(rb"stream\r?\n(.*?)endstream", re.DOTALL)
_TEXT_OPERATOR = re.compile(rb"(?:^|[\s\)\]>])(?:Tj|TJ|'|\")(?:[\s\(\[<]|$)", re.DOTALL)


def _decode(payload: bytes) -> bytes:
    stripped = payload.strip()
    if stripped.endswith(b"~>"):
        with contextlib.suppress(ValueError, binascii.Error):
            payload = base64.a85decode(stripped, adobe=True)
    with contextlib.suppress(zlib.error):
        payload = zlib.decompress(payload)
    return payload


def has_text_layer(path: Path, *, max_bytes: int = 8 << 20) -> bool | None:
    try:
        data = path.read_bytes()[:max_bytes]
    except OSError:
        return None
    if not data.startswith(b"%PDF"):
        return None
    inspected = 0
    for index, match in enumerate(_STREAM.finditer(data)):
        if index >= _MAX_STREAMS:
            break
        inspected += 1
        if _TEXT_OPERATOR.search(_decode(match.group(1))):
            return True
    return False if inspected else None


def audit_text_layers(corpus: Corpus, root: Path, out: Collector) -> None:
    for docset in corpus.docsets:
        scans = [
            d
            for d in docset.documents
            if d.suffix == ".pdf" and has_text_layer(root / d.path) is False
        ]
        if scans:
            out.warn(
                "no_text_layer",
                f"{docset.ref}: {len(scans)} PDF(s) look like scans with no text layer "
                f"({scans[0].name})",
                org=docset.org,
                docset_id=docset.docset_id,
                count=len(scans),
            )
