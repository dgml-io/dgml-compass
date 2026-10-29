"""Scoring against frozen expected records, on a real draw.

``fixtures/<case>.tar.gz`` is one draw of one cell of a real run (run artifacts, the generated
workspace's usage/DGML/OCR, and the corpus slice with gold refs and gold DGML; source
documents are empty stubs). ``expected/<case>.jsonl`` holds the records expected
for it; the file is frozen, so a change that moves a number must say why in
docs/DECISIONS.md.

Every record must match: same families, docsets and draws, identical counts, warnings and
``absent``, and values equal to 1e-9. The role prices added to economics
(``cost_per_page_{transcribe,label,pipeline}``) are checked separately against the per-page
prices recorded for the same draw.
"""

from __future__ import annotations

import math

import pytest

from model_compass.metrics.economics import ROLE_PRICE_METRICS

from .conftest import CASES

# Recorded per-page prices of the draw-0 row of each cell. ``None``: not
# emitted (pipeline only when one model fills both slots).
ROLE_PRICES = {
    "msa_tree": (0.01225782857142857, 0.00885484081632653, None),
}


def _without_role_prices(record: dict) -> dict:
    record = dict(record)
    record["values"] = {k: v for k, v in record["values"].items() if k not in ROLE_PRICE_METRICS}
    record["absent"] = [n for n in record["absent"] if n not in ROLE_PRICE_METRICS]
    record.pop("computed_at")
    return record


@pytest.mark.parametrize("case", CASES)
def test_records_match_the_source(scored, case):
    expected, actual = scored[case]
    assert [(r["family"], r["docset"], r["draw"]) for r in actual] == [
        (r["family"], r["docset"], r["draw"]) for r in expected
    ]
    for exp, act in zip(expected, actual, strict=True):
        exp, act = _without_role_prices(exp), _without_role_prices(act)
        where = f"{case}/{exp['family']}"
        assert act["values"].keys() == exp["values"].keys(), where
        for name, value in exp["values"].items():
            assert math.isclose(act["values"][name], value, rel_tol=1e-12, abs_tol=1e-9), (
                f"{where}: {name} {act['values'][name]!r} != {value!r}"
            )
        for key in (
            "schema_version",
            "run_id",
            "cell_id",
            "org",
            "docset",
            "counts",
            "absent",
            "warnings",
        ):
            assert act[key] == exp[key], f"{where}: {key}"


def test_the_tree_case_is_scored(scored):
    assert "msa_tree" in CASES
    _, actual = scored["msa_tree"]
    tree = next(r for r in actual if r["family"] == "tree")
    assert tree["counts"]["n_alignable"] >= 1 and "teds" in tree["values"]


@pytest.mark.parametrize("case", CASES)
def test_role_prices_match_recorded_values(scored, case):
    _, actual = scored[case]
    economics = next(r for r in actual if r["family"] == "economics")
    for name, want in zip(ROLE_PRICE_METRICS, ROLE_PRICES[case], strict=True):
        got = economics["values"].get(name)
        if want is None:
            assert got is None and name not in economics["absent"], name
        else:
            assert got is not None and math.isclose(got, want, rel_tol=1e-9), (name, got, want)
