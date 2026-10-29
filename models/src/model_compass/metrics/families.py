"""The four metric families as functions of one cell's inputs -> MetricRecords.

Every family speaks for every docset of the cell; one that cannot compute says why in
``warnings`` and lists its names in ``absent`` -- never a record of zeros.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from model_compass.corpus.refs import REF_KEY_SEP
from model_compass.domain import MetricFamily
from model_compass.engine.usage import read_usage
from model_compass.metrics.complex_ref import score_complex
from model_compass.metrics.dgml_xml import UnparseableDocument, parse_dgml
from model_compass.metrics.economics import (
    ALL_ECONOMICS_METRICS,
    ROLE_PRICE_METRICS,
    compute_economics,
    representation_cost,
    role_prices,
)
from model_compass.metrics.extraction import ALL_EXTRACTION_METRICS, score_docset
from model_compass.metrics.outputs import DocsetWorkspace, read_config_label_model, read_docset
from model_compass.metrics.reference_free import (
    ALL_REFERENCE_FREE_METRICS,
    GROUNDING_METRICS,
    document_tags,
    grounding_quality,
    pooled_content,
    structural_health,
    tag_consistency,
)
from model_compass.metrics.tree.compare import ALL_TREE_METRICS, compare_docset
from model_compass.records import MetricRecord

if TYPE_CHECKING:
    from collections import Counter
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path
    from xml.etree import ElementTree

    from model_compass.corpus.models import Docset
    from model_compass.domain import AxisValue


@dataclass
class DocsetArtifacts:
    """One docset's generated DGML, joined to corpus file ids."""

    predictions: Mapping[str, Mapping[str, Sequence[str]]]
    documents_expected: int
    documents_with_dgml: int
    roots: Mapping[str, ElementTree.Element] = field(default_factory=dict)

    @property
    def missing_dgml_rate(self) -> float:
        if not self.documents_expected:
            return 0.0
        return 1.0 - self.documents_with_dgml / self.documents_expected


@dataclass
class CellInputs:
    """Everything the families may need for one draw of one cell."""

    run_id: str
    cell_id: str
    docsets: Sequence[Docset]
    draw: int = 0
    workspace: Path | None = None
    artifacts: Mapping[str, DocsetArtifacts] = field(default_factory=dict)
    corpus_root: Path | None = None
    docset_ids: Mapping[str, str] = field(default_factory=dict)
    """Corpus ``org/docset`` -> the docset id dgml used inside the workspace."""
    settings: Mapping[str, AxisValue] = field(default_factory=dict)
    f1_by_docset: Mapping[str, float] = field(default_factory=dict)
    """Filled from the extraction records; economics reads it for ``f1_per_dollar``."""
    _workspace_docsets: dict[str, DocsetWorkspace] = field(default_factory=dict, repr=False)

    def workspace_docset(self, docset: Docset) -> DocsetWorkspace:
        """The workspace copy of a docset's DGML, read once and shared by reference_free and
        economics (neither mutates it). Requires ``workspace``."""
        if docset.ref not in self._workspace_docsets:
            assert self.workspace is not None
            dgml_id = self.docset_ids.get(docset.ref, docset.docset_id)
            self._workspace_docsets[docset.ref] = read_docset(self.workspace, dgml_id)
        return self._workspace_docsets[docset.ref]

    def record(
        self,
        docset: Docset,
        family: MetricFamily,
        *,
        values: Mapping[str, float] | None = None,
        counts: Mapping[str, int] | None = None,
        absent: Sequence[str] = (),
        warnings: Sequence[str] = (),
    ) -> MetricRecord:
        return MetricRecord(
            run_id=self.run_id,
            cell_id=self.cell_id,
            org=docset.org,
            docset=docset.docset_id,
            draw=self.draw,
            family=family,
            values=dict(values or {}),
            counts=dict(counts or {}),
            absent=tuple(absent),
            warnings=tuple(warnings),
        )


def score_extraction(inputs: CellInputs) -> list[MetricRecord]:
    """docs/METRICS.md §1. A docset without gold gets a record with no values and ``no_gold``."""
    records = []
    for docset in inputs.docsets:
        artifact = inputs.artifacts.get(docset.ref)
        values: dict[str, float] = {}
        counts: dict[str, int] = {}
        warnings: list[str] = []
        unusable: list[str] = []
        if artifact is None:
            unusable.append("no_artifacts")
        elif docset.flat_ref is None:
            unusable.append("no_gold")
        else:
            gold_file_ids = sorted({d.file_id for d in docset.documents if d.file_id})
            orphans = sorted(docset.flat_ref.file_ids - set(gold_file_ids))
            labels = sorted(docset.flat_ref.labels)
            types_by_label: dict[str, str] = {}
            for raw_key, entry in (docset.typed_ref.entries if docset.typed_ref else {}).items():
                types_by_label.setdefault(raw_key.partition(REF_KEY_SEP)[2], entry.type)
            values.update(
                score_docset(
                    {k: [v.raw for v in vals] for k, vals in docset.flat_ref.entries.items()},
                    artifact.predictions,
                    gold_file_ids,
                    labels,
                    types_by_label=types_by_label,
                )
            )
            if docset.complex_ref is not None:
                values.update(score_complex(docset.complex_ref, {}))
            counts.update(
                {
                    "n_documents": len(docset.documents),
                    "n_scored_documents": len(gold_file_ids),
                    "n_labels": len(labels),
                    "n_orphan_gold": len(orphans),
                    "n_gold_values": docset.flat_ref.n_values,
                }
            )
            if orphans:
                warnings.append(f"{len(orphans)} gold file id(s) have no document on disk")
        if artifact is not None:
            values["missing_dgml_rate"] = artifact.missing_dgml_rate
            counts["n_documents_with_dgml"] = artifact.documents_with_dgml
            if artifact.missing_dgml_rate > 0:
                unusable.append("missing_dgml")
        records.append(
            inputs.record(
                docset,
                MetricFamily.EXTRACTION,
                values=values,
                counts=counts,
                absent=[n for n in ALL_EXTRACTION_METRICS if n not in values],
                warnings=[*warnings, *(f"unusable: {r}" for r in unusable)],
            )
        )
    return records


def score_reference_free(inputs: CellInputs) -> list[MetricRecord]:
    """docs/METRICS.md §2; the only family that needs no gold at all."""
    family, names = MetricFamily.REFERENCE_FREE, ALL_REFERENCE_FREE_METRICS
    if inputs.workspace is None:
        return [
            inputs.record(d, family, absent=names, warnings=["no_workspace"])
            for d in inputs.docsets
        ]
    records = []
    for docset in inputs.docsets:
        ws = inputs.workspace_docset(docset)
        counts = {
            "n_documents": ws.documents,
            "n_files_expected": ws.documents_expected,
            "n_unparseable": len(ws.unparseable),
        }
        warnings = list(ws.warnings)
        if not ws.roots:
            records.append(
                inputs.record(
                    docset, family, counts=counts, absent=names, warnings=[*warnings, "no_dgml"]
                )
            )
            continue
        values: dict[str, float] = {}
        content: dict[str, Counter[str]] = {}
        per_doc_tags = []
        for root in ws.roots:
            per_doc_tags.append(document_tags(root))
            pooled_content(root, content)
        consistency = tag_consistency(per_doc_tags, content)
        values.update(consistency.values)
        counts["n_vocabulary"] = consistency.vocabulary
        if consistency.documents < 2:
            warnings.append("single_document_docset")
        if consistency.synonym_examples:
            warnings.append("synonyms: " + "; ".join(consistency.synonym_examples))
        structural = structural_health(ws.roots)
        values.update(structural.values)
        counts["n_elements"] = structural.elements
        counts["n_dual_role_names"] = len(structural.dual_role_names)
        if ws.has_page_text:
            grounded = [
                grounding_quality(root, ws.page_words.get(file_id, {}))
                for root, file_id in zip(ws.roots, ws.file_ids, strict=True)
            ]
            for name in GROUNDING_METRICS:
                vals = [v for g in grounded if (v := getattr(g, name)) is not None]
                if vals:
                    values[name] = sum(vals) / len(vals)
            counts["n_text_leaves"] = sum(g.text_leaves for g in grounded)
            counts["n_origin_boxes"] = sum(g.boxes for g in grounded)
            if any(name not in values for name in GROUNDING_METRICS):
                warnings.append("no_grounded_leaves")
        records.append(
            inputs.record(
                docset,
                family,
                values=values,
                counts=counts,
                absent=[n for n in names if n not in values],
                warnings=warnings,
            )
        )
    return records


def score_economics(inputs: CellInputs) -> list[MetricRecord]:
    """docs/METRICS.md §3. ``usage.jsonl`` is per workspace: with several docsets in a cell the
    cost is the cell's, and the record says ``cost_shared_across_docsets``."""
    family = MetricFamily.ECONOMICS
    if inputs.workspace is None:
        return [
            inputs.record(d, family, absent=ALL_ECONOMICS_METRICS, warnings=["no_workspace"])
            for d in inputs.docsets
        ]
    usage = read_usage(inputs.workspace / "usage.jsonl")
    configured, config_warnings = read_config_label_model(inputs.workspace)
    transcriber = inputs.settings.get("generation.model")
    same_model = transcriber is not None and transcriber == inputs.settings.get(
        "generation.label_model"
    )
    records = []
    for docset in inputs.docsets:
        ws = inputs.workspace_docset(docset)
        economics = compute_economics(
            usage,
            representation_cost(ws.dgml_texts, ws.page_word_lengths()),
            files_expected=ws.documents_expected,
            f1=inputs.f1_by_docset.get(docset.ref),
        )
        values = economics.values
        values.update(role_prices(economics, usage.by_operation, same_model=same_model))
        warnings = [*ws.warnings, *config_warnings, *economics.warnings()]
        if len(inputs.docsets) > 1:
            warnings.append("cost_shared_across_docsets")
        if not usage.label_models and usage.present:
            warnings.append("no_label_telemetry")
        if configured and usage.label_models and configured not in usage.label_models:
            warnings.append(
                f"label_model_mismatch: configured {configured!r} but ran "
                f"{list(usage.label_models)} - NOT COMPARABLE"
            )
        role_absent = [n for n in ROLE_PRICE_METRICS if n not in values]
        if not same_model:
            role_absent.remove("cost_per_page_pipeline")  # not applicable, not missing
        records.append(
            inputs.record(
                docset,
                family,
                values=values,
                counts=economics.counts,
                absent=[*economics.absent, *role_absent],
                warnings=warnings,
            )
        )
    return records


def score_tree(inputs: CellInputs) -> list[MetricRecord]:
    """docs/METRICS.md §4: each document's prediction against the gold ``<stem>.dgml.xml`` beside it
    in the corpus, joined by corpus file id."""
    family, names = MetricFamily.TREE, ALL_TREE_METRICS
    records = []
    for docset in inputs.docsets:
        artifact = inputs.artifacts.get(docset.ref)
        gold_paths = {d.file_id: d.xml_path for d in docset.documents if d.file_id and d.xml_path}
        if not gold_paths:
            records.append(inputs.record(docset, family, absent=names, warnings=["no_gold_xml"]))
            continue
        if inputs.corpus_root is None:
            records.append(inputs.record(docset, family, absent=names, warnings=["no_corpus"]))
            continue
        if artifact is None or not artifact.roots:
            reason = "no_workspace" if inputs.workspace is None and artifact is None else "no_dgml"
            records.append(
                inputs.record(
                    docset,
                    family,
                    counts={"n_documents": artifact.documents_expected if artifact else 0},
                    absent=names,
                    warnings=[reason],
                )
            )
            continue
        unreadable_gold = 0
        pairs = []
        for file_id, pred_root in artifact.roots.items():
            gold_root = None
            if xml_path := gold_paths.get(file_id):
                try:
                    gold_root = parse_dgml(inputs.corpus_root / xml_path)
                except (UnparseableDocument, OSError):
                    unreadable_gold += 1
            pairs.append((gold_root, pred_root))
        result = compare_docset(pairs)
        warnings = list(result.warnings)
        if unreadable_gold:
            warnings.append(f"unreadable_gold_xml:{unreadable_gold}")
        records.append(
            inputs.record(
                docset,
                family,
                values=result.values,
                counts={
                    "n_documents": artifact.documents_expected,
                    "n_documents_with_dgml": artifact.documents_with_dgml,
                    "n_gold_xml": len(gold_paths),
                    "n_compared": result.n_compared,
                    "n_alignable": result.n_alignable,
                    "n_unalignable": result.n_unalignable,
                    "n_without_gold_xml": result.n_without_gold_xml,
                },
                absent=result.absent,
                warnings=warnings,
            )
        )
    return records


FAMILIES: Final[dict[MetricFamily, Callable[[CellInputs], list[MetricRecord]]]] = {
    MetricFamily.EXTRACTION: score_extraction,
    MetricFamily.REFERENCE_FREE: score_reference_free,
    MetricFamily.ECONOMICS: score_economics,
    MetricFamily.TREE: score_tree,
}
