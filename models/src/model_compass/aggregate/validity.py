"""Comparability gates (docs/METRICS.md §5): may these numbers be compared at all?

The codes are the API; the sentences are display only. ``check_group`` judges one grid row
against the cells behind it; ``check_comparison`` judges rows against each other (``compare``).
An unrecorded provenance field is "not recorded", never a mismatch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from model_compass.aggregate.grid import GridRow, GroupKey
    from model_compass.runs import Manifest

DEFAULT_MIN_DOCSETS: Final[int] = 3
"""Below three docsets a between-docset band rests on one or two numbers."""


class ValidityCode(StrEnum):
    CORPUS_HASH_MISMATCH = "corpus_hash_mismatch"
    DGML_VERSION_MISMATCH = "dgml_version_mismatch"
    REPO_SHA_MISMATCH = "repo_sha_mismatch"
    TOO_FEW_DOCSETS = "too_few_docsets"
    SINGLE_DOCSET = "single_docset"
    MIXED_COST_PARTIAL = "mixed_cost_partial"
    MISSING_DRAWS = "missing_draws"
    PARTIAL_OUTCOME = "partial_outcome"
    NO_QUALITY = "no_quality"


_SENTENCES: Final[dict[ValidityCode, str]] = {
    ValidityCode.CORPUS_HASH_MISMATCH: (
        "the contributing cells did not all run against the same corpus content"
    ),
    ValidityCode.DGML_VERSION_MISMATCH: "the contributing cells ran different dgml versions",
    ValidityCode.REPO_SHA_MISMATCH: "the contributing cells ran different repo revisions",
    ValidityCode.TOO_FEW_DOCSETS: "fewer docsets than the comparability floor",
    ValidityCode.SINGLE_DOCSET: "one docset, so there is no between-docset band",
    ValidityCode.MIXED_COST_PARTIAL: (
        "some cells measured cost per call and others spread a workspace total"
    ),
    ValidityCode.MISSING_DRAWS: "a docset has fewer draws than the spec asked for",
    ValidityCode.PARTIAL_OUTCOME: "a contributing cell finished with outcome: partial",
    ValidityCode.NO_QUALITY: "nothing in this group produced a quality score",
}


def describe_code(code: ValidityCode | str) -> str:
    try:
        return _SENTENCES[ValidityCode(code)]
    except ValueError:
        return str(code)


@dataclass(frozen=True)
class CellEvidence:
    """A contributing cell's provenance, taken from the run manifest (never from records)."""

    cell_id: str = ""
    corpus_hash: str = ""
    dgml_version: str = ""
    repo_shas: tuple[str, ...] = ()
    outcome: str = "ok"
    cost_partial: bool = False
    draws_expected: int = 1
    draws_present: int = 1

    @property
    def partial(self) -> bool:
        return self.outcome == "partial"


@dataclass(frozen=True)
class GateResult:
    key: GroupKey | None = None
    codes: tuple[ValidityCode, ...] = ()
    detail: dict[str, str] = field(default_factory=dict)

    @property
    def comparable(self) -> bool:
        return not self.codes

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(code.value for code in self.codes)


def evidence_from_manifest(manifest: Manifest) -> dict[str, CellEvidence]:
    """One :class:`CellEvidence` per cell. Corpus hash, dgml version and SHAs are run-level,
    so within one run those gates cannot fire; they matter across runs (``compare``).
    ``cost_partial`` is never set here, so ``mixed_cost_partial`` fires
    from rows, not from evidence."""
    prov = manifest.provenance
    shas = tuple(
        f"{name}@{repo.commit}" for name, repo in sorted(prov.repos.items()) if repo.commit
    )
    run_partial = manifest.outcome == "partial"
    return {
        cell_id: CellEvidence(
            cell_id=cell_id,
            corpus_hash=prov.corpus_hash or "",
            dgml_version=prov.dgml_version or "",
            repo_shas=shas,
            outcome="partial" if run_partial or cell.status == "failed" else "ok",
            draws_expected=cell.draws_total,
            draws_present=cell.draws_completed,
        )
        for cell_id, cell in sorted(manifest.cells.items())
    }


def _distinct(values: Iterable[str]) -> list[str]:
    return sorted({value for value in values if value})


def _provenance_codes(
    evidence: Sequence[CellEvidence], codes: list[ValidityCode], detail: dict[str, str]
) -> None:
    hashes = _distinct(item.corpus_hash for item in evidence)
    if len(hashes) > 1:
        codes.append(ValidityCode.CORPUS_HASH_MISMATCH)
        detail["corpus_hash"] = ", ".join(hashes)
    versions = _distinct(item.dgml_version for item in evidence)
    if len(versions) > 1:
        codes.append(ValidityCode.DGML_VERSION_MISMATCH)
        detail["dgml_version"] = ", ".join(versions)
    shas = _distinct("|".join(item.repo_shas) for item in evidence)
    if len(shas) > 1:
        codes.append(ValidityCode.REPO_SHA_MISMATCH)
        detail["repo_shas"] = f"{len(shas)} distinct revisions"


def check_group(
    row: GridRow, evidence: Sequence[CellEvidence] = (), *, min_docsets: int = DEFAULT_MIN_DOCSETS
) -> GateResult:
    codes: list[ValidityCode] = []
    detail: dict[str, str] = {}
    _provenance_codes(evidence, codes, detail)
    if row.mean_quality is None:
        codes.append(ValidityCode.NO_QUALITY)
    if row.single_docset or row.n_docsets < 2:
        codes.append(ValidityCode.SINGLE_DOCSET)
    if row.n_docsets < min_docsets:
        codes.append(ValidityCode.TOO_FEW_DOCSETS)
        detail["n_docsets"] = f"{row.n_docsets} < {min_docsets}"
    if len({item.cost_partial for item in evidence}) > 1:
        codes.append(ValidityCode.MIXED_COST_PARTIAL)
        detail["cost_partial"] = "mixed across contributing cells"
    short = [item for item in evidence if item.draws_present < item.draws_expected]
    if short:
        codes.append(ValidityCode.MISSING_DRAWS)
        detail["draws"] = ", ".join(
            f"{item.cell_id}: {item.draws_present}/{item.draws_expected}" for item in short[:3]
        )
    partial = [item for item in evidence if item.partial]
    if partial:
        codes.append(ValidityCode.PARTIAL_OUTCOME)
        detail["partial_cells"] = ", ".join(item.cell_id for item in partial[:3])
    return GateResult(key=row.key, codes=tuple(codes), detail=detail)


def check_comparison(
    rows: Sequence[GridRow],
    evidence: Mapping[str, Sequence[CellEvidence]] | None = None,
    *,
    min_docsets: int = DEFAULT_MIN_DOCSETS,
) -> GateResult:
    """Rows judged against each other. ``evidence`` is filed under ``row.key.row_id``."""
    if not rows:
        return GateResult(codes=(ValidityCode.NO_QUALITY,))
    codes: list[ValidityCode] = []
    detail: dict[str, str] = {}
    pooled = [item for row in rows for item in (evidence or {}).get(row.key.row_id, ())]
    _provenance_codes(pooled, codes, detail)
    detail.pop("repo_shas", None)  # the code is named here, not the detail
    # One arm measured per call, the other a workspace total spread over documents.
    if len({row.cost_partial for row in rows}) > 1:
        codes.append(ValidityCode.MIXED_COST_PARTIAL)
        detail["cost_partial"] = "the arms measured cost differently"
    if any(row.single_docset for row in rows):
        codes.append(ValidityCode.SINGLE_DOCSET)
    if any(row.n_docsets < min_docsets for row in rows):
        codes.append(ValidityCode.TOO_FEW_DOCSETS)
        detail["n_docsets"] = ", ".join(str(row.n_docsets) for row in rows)
    if any(row.mean_quality is None for row in rows):
        codes.append(ValidityCode.NO_QUALITY)
    if any(item.partial for item in pooled):
        codes.append(ValidityCode.PARTIAL_OUTCOME)
    if any(item.draws_present < item.draws_expected for item in pooled):
        codes.append(ValidityCode.MISSING_DRAWS)
    return GateResult(key=rows[0].key, codes=tuple(dict.fromkeys(codes)), detail=detail)


def validity_payload(run_id: str, min_docsets: int, gates: Sequence[GateResult]) -> dict[str, Any]:
    """``grid/validity.json``."""
    counts: dict[str, int] = {}
    for gate in gates:
        for code in gate.codes:
            counts[code.value] = counts.get(code.value, 0) + 1
    n_comparable = sum(1 for gate in gates if gate.comparable)
    return {
        "run_id": run_id,
        "min_docsets": min_docsets,
        "n_comparable": n_comparable,
        "n_incomparable": len(gates) - n_comparable,
        "counts": dict(sorted(counts.items())),
        "results": [
            {
                "key": gate.key.as_dict() if gate.key else None,
                "comparable": gate.comparable,
                "codes": list(gate.warnings),
                "detail": gate.detail,
            }
            for gate in gates
        ],
    }
