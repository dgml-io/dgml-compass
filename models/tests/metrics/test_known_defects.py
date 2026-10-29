"""Known defects, kept so numbers stay comparable with earlier results. Each test states the
intended behaviour and is a strict xfail until the defect is fixed; a fix moves numbers, so it
regenerates the goldens and is recorded in docs/DECISIONS.md.
"""

from __future__ import annotations

import pytest

from model_compass.metrics.economics import Economics
from model_compass.metrics.families import DocsetArtifacts

STRICT = {"strict": True}


@pytest.mark.xfail(
    reason="known defect 1 (docs/DECISIONS.md): "
    "complex_* scores are emitted as 0.0 although nothing produces complex predictions: "
    "a silent zero the no-silent-zero rule forbids",
    **STRICT,
)
def test_complex_scores_are_absent_without_complex_predictions(scored):
    _, actual = scored["msa_tree"]
    extraction = next(r for r in actual if r["family"] == "extraction")
    assert "complex_instance_f1" not in extraction["values"]


@pytest.mark.xfail(
    reason="known defect 2 (docs/DECISIONS.md): "
    "orphan-gold count compares gold with the SAMPLED documents, not the docset on disk: "
    "documents that were simply not sampled are reported as 'with no document on disk'",
    **STRICT,
)
def test_orphan_gold_counts_only_documents_missing_from_disk(scored):
    _, actual = scored["msa_tree"]
    extraction = next(r for r in actual if r["family"] == "extraction")
    assert extraction["counts"]["n_orphan_gold"] == 0


@pytest.mark.xfail(
    reason="known defect 4 (docs/DECISIONS.md): "
    "missing_dgml_rate is a fraction (0-1) in extraction records and a percentage "
    "(0-100) in economics records, under the same name",
    **STRICT,
)
def test_missing_dgml_rate_has_one_scale():
    half_missing = DocsetArtifacts(predictions={}, documents_expected=2, documents_with_dgml=1)
    economics = Economics(documents=1, files_expected=2)
    assert half_missing.missing_dgml_rate == economics.values["missing_dgml_rate"]
