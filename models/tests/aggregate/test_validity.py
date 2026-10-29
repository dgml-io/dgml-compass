"""The comparability gates."""

from __future__ import annotations

from dataclasses import replace

import pytest

from model_compass.aggregate.grid import GridRow, GroupKey
from model_compass.aggregate.validity import (
    CellEvidence,
    ValidityCode,
    check_comparison,
    check_group,
    describe_code,
    evidence_from_manifest,
    validity_payload,
)
from model_compass.runs import Manifest

ROW = GridRow(key=GroupKey(model="m"), mean_quality=60.0, n_docsets=4, single_docset=False)
ev = CellEvidence


def codes(result):
    return set(result.codes)


@pytest.mark.parametrize(
    ("row", "evidence", "expected"),
    [
        (ROW, [ev(corpus_hash="a"), ev(corpus_hash="b")], {ValidityCode.CORPUS_HASH_MISMATCH}),
        (ROW, [ev(dgml_version="1"), ev(dgml_version="2")], {ValidityCode.DGML_VERSION_MISMATCH}),
        (ROW, [ev(repo_shas=("x@1",)), ev(repo_shas=("x@2",))], {ValidityCode.REPO_SHA_MISMATCH}),
        (ROW, [ev(cost_partial=True), ev()], {ValidityCode.MIXED_COST_PARTIAL}),
        (ROW, [ev(cost_partial=True), ev(cost_partial=True)], set()),
        (ROW, [ev(draws_expected=3, draws_present=2)], {ValidityCode.MISSING_DRAWS}),
        (ROW, [ev(outcome="partial")], {ValidityCode.PARTIAL_OUTCOME}),
        (replace(ROW, n_docsets=2), [], {ValidityCode.TOO_FEW_DOCSETS}),
        (
            replace(ROW, n_docsets=1, single_docset=True),
            [],
            {ValidityCode.SINGLE_DOCSET, ValidityCode.TOO_FEW_DOCSETS},
        ),
        (replace(ROW, mean_quality=None), [], {ValidityCode.NO_QUALITY}),
        (ROW, [ev(corpus_hash=""), ev(corpus_hash="a")], set()),  # unrecorded is not a mismatch
        (ROW, [], set()),
    ],
)
def test_each_gate(row, evidence, expected):
    result = check_group(row, evidence)
    assert codes(result) == expected
    assert result.comparable is (not expected)


def test_codes_have_sentences():
    assert all(describe_code(code) != code.value for code in ValidityCode)
    assert describe_code("made_up") == "made_up"


def test_two_sound_rows_can_still_be_incomparable():
    a, b = ROW, replace(ROW, key=GroupKey(model="n"))
    evidence = {a.key.row_id: [ev(corpus_hash="x")], b.key.row_id: [ev(corpus_hash="y")]}
    assert check_group(a, evidence[a.key.row_id]).comparable
    result = check_comparison([a, b], evidence)
    assert result.codes == (ValidityCode.CORPUS_HASH_MISMATCH,)
    assert check_comparison([a, replace(b, cost_partial=True)]).codes == (
        ValidityCode.MIXED_COST_PARTIAL,
    )
    assert check_comparison([a, replace(b, mean_quality=None)]).codes == (ValidityCode.NO_QUALITY,)
    assert check_comparison([]).codes == (ValidityCode.NO_QUALITY,)
    assert check_comparison([a, b]).comparable


def test_evidence_comes_from_the_manifest():
    manifest = Manifest.model_validate(
        {
            "run_id": "r",
            "outcome": "succeeded",
            "provenance": {"corpus_hash": "h", "repos": {"b": {"commit": "2"}, "a": {}}},
            "cells": {
                "c1": {"status": "failed", "draws_total": 3, "draws_completed": 1},
                "c2": {"status": "succeeded", "draws_total": 3, "draws_completed": 3},
            },
        }
    )
    evidence = evidence_from_manifest(manifest)
    assert evidence["c1"] == ev("c1", "h", "", ("b@2",), "partial", False, 3, 1)
    assert evidence["c2"].outcome == "ok"
    partial = evidence_from_manifest(manifest.model_copy(update={"outcome": "partial"}))
    assert all(item.partial for item in partial.values())


def test_validity_payload_counts_by_code():
    gates = [check_group(ROW), check_group(replace(ROW, n_docsets=1, single_docset=True))]
    payload = validity_payload("r", 3, gates)
    assert payload["n_comparable"] == 1 and payload["n_incomparable"] == 1
    assert payload["counts"] == {"single_docset": 1, "too_few_docsets": 1}
    assert payload["results"][0]["key"]["model"] == "m"
