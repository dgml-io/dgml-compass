"""Edge-case definitions of the metric families, hermetic and small. End-to-end agreement with
recorded scores is in test_scoring_goldens.py."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

import pytest

from model_compass.engine.usage import UsageSummary, parse_usage, summarize
from model_compass.metrics.dgml_xml import UnparseableDocument, parse_dgml_bytes
from model_compass.metrics.economics import (
    ROLE_PRICE_METRICS,
    RepresentationCost,
    compute_economics,
    percentile_nearest_rank,
    role_prices,
)
from model_compass.metrics.extraction import (
    build_gold,
    build_predictions,
    compute_scores,
    count_overlap,
    score_docset,
)
from model_compass.metrics.predictions import predictions_for_documents
from model_compass.metrics.reference_free import structural_health, tag_consistency
from model_compass.metrics.text import EMPTY, normalize_text, occurrence_keys, positional_keys
from model_compass.metrics.tree.compare import compare_docset
from model_compass.metrics.tree.flatten import flatten
from model_compass.metrics.tree.ted import tree_edit_metrics

from .conftest import extract, score

if TYPE_CHECKING:
    from xml.etree import ElementTree

DG = "http://dgml.io/ns/dg#"


def xml(text: str) -> ElementTree.Element:
    return parse_dgml_bytes(text.encode())


# -- text and keys ----------------------------------------------------------------------------


def test_normalisation_keeps_numbers_whole_and_exempts_the_sentinel():
    assert normalize_text("ACME  Ltd.") == "acme ltd"
    assert normalize_text("$1,250.00 • due") == "125000 due"  # one token, then punctuation-free
    assert normalize_text(EMPTY) == EMPTY


def test_positional_vs_occurrence_keys():
    assert positional_keys(["A", "a"]) == {"a#0", "a#1"}
    assert occurrence_keys(["A", "a"]) == {"a", "a#2"}


# -- extraction ------------------------------------------------------------------------------


def test_empty_is_an_answer():
    assert count_overlap(set(), set()) == (1.0, 1.0)
    assert count_overlap({"a#0"}, set()) == (0.0, 0.0)
    assert compute_scores({"k": set()}, {"k": set()}) == (1.0, 1.0, 1.0)


def test_predictions_are_padded_with_the_sentinel_like_gold():
    """DECISIONS 0014: a document rightly silent about a field matches gold's sentinel."""
    preds = build_predictions({"f1": {"Total": ["5"]}, "f2": {}}, ["f1", "f2"])
    assert preds["f2__Total"] == {EMPTY}
    gold = build_gold({"f1::Total": ["5#3"]}, ["f1", "f2"], ["Total"])
    assert gold["f2__Total"] == {EMPTY}
    scores = score_docset(
        {"f1::Total": ["5#3"]}, {"f1": {"Total": ["5"]}, "f2": {}}, ["f1", "f2"], ["Total"]
    )
    assert scores["individual_em_f1"] == 100.0


def test_naming_penalty_is_tag_blind_minus_tagged_recall():
    scores = score_docset({"f1::Total": ["5#3"]}, {"f1": {"Amount": ["5"]}}, ["f1"], ["Total"])
    assert scores["naming_penalty"] == pytest.approx(
        scores["value_only_overlap_recall"] - scores["individual_overlap_recall"]
    )


def test_every_path_suffix_is_a_label_and_nolim_is_offered():
    root = xml(
        '<Doc><A><B structure="p"><Lim structure="lim">2.1</Lim> Onsite visits</B></A></Doc>'
    )
    table = predictions_for_documents([("f1", root)]).by_file["f1"]
    assert table["A+B"] == ["2.1 Onsite visits"]
    assert table["B+nolim"] == ["Onsite visits"]


def test_doctype_is_refused():
    with pytest.raises(UnparseableDocument):
        parse_dgml_bytes(b'<!DOCTYPE x [<!ENTITY a "b">]><x/>')


# -- reference-free --------------------------------------------------------------------------


def test_single_document_docset_has_no_consistency_score():
    """DECISIONS 0008: absent, not a coerced 0."""
    result = tag_consistency([frozenset({"A", "B"})])
    assert result.consistency_score is None and result.mean_pairwise_jaccard is None
    assert "consistency_score" not in result.values


def test_empty_containers_count_dg_children():
    """DECISIONS 0009: text wrapped in a dg:chunk is content."""
    root = xml(
        f'<Doc xmlns:dg="{DG}"><Clause structure="p"><dg:chunk>text</dg:chunk></Clause>'
        '<Empty structure="p"/></Doc>'
    )
    assert structural_health([root]).empty_containers == 1


# -- economics -------------------------------------------------------------------------------


def test_nothing_measured_is_absent_not_zero():
    economics = compute_economics(UsageSummary(present=False), RepresentationCost())
    assert economics.values == {}
    assert "cost_usd" in economics.absent
    assert "cost_partial" in economics.warnings()


def test_nearest_rank_p95_reports_the_tail():
    assert percentile_nearest_rank([1.0, 2.0, 10.0], 0.95) == 10.0
    assert percentile_nearest_rank([], 0.95) is None


def test_role_prices_split_cost_in_usage_shares():
    rows = [
        '{"operation": "transcribe", "model": "m", "cost_usd": 3.0, "outcome": "ok"}',
        '{"operation": "label", "model": "m", "cost_usd": 0.5, "outcome": "ok"}',
        '{"operation": "links", "model": "m", "cost_usd": 0.5, "outcome": "ok"}',
        '{"operation": "classify", "model": "m", "cost_usd": 1.0, "outcome": "ok"}',
    ]
    usage = summarize(parse_usage(rows))
    economics = compute_economics(usage, RepresentationCost(documents=1, pages=10))
    prices = role_prices(economics, usage.by_operation, same_model=True)
    # $5 total over 10 pages, split 3:1 between transcribe and label (+links); classify shared
    assert prices == {
        "cost_per_page_transcribe": pytest.approx(0.375),
        "cost_per_page_label": pytest.approx(0.125),
        "cost_per_page_pipeline": pytest.approx(0.5),
    }
    assert "cost_per_page_pipeline" not in role_prices(
        economics, usage.by_operation, same_model=False
    )
    assert set(prices) == set(ROLE_PRICE_METRICS)


# -- tree ------------------------------------------------------------------------------------


def test_identical_trees_agree_perfectly():
    gold = xml('<Doc><Party structure="p">Acme Limited</Party><Total>17 dollars</Total></Doc>')
    result = compare_docset([(gold, gold)])
    assert result.values["alignable_fraction"] == 1.0
    assert result.values["bcubed_f1"] == 1.0
    assert result.values["teds"] == 1.0 and result.values["text_wer"] == 0.0


def test_unalignable_pairs_are_counted_not_averaged():
    gold = xml("<Doc><A>one two three four</A></Doc>")
    pred = xml("<Doc><A>five six seven eight</A></Doc>")
    result = compare_docset([(gold, pred)])
    assert result.n_unalignable == 1 and "unalignable" in result.warnings
    assert "bcubed_f1" not in result.values


def test_ted_counts_an_added_wrapper_as_one_operation():
    gold = xml("<Doc><A>x</A></Doc>")
    pred = xml(f'<Doc xmlns:dg="{DG}"><dg:chunk><A>x</A></dg:chunk></Doc>')
    ted = tree_edit_metrics(gold, pred)
    assert ted is not None and (ted["tree_del"], ted["tree_ins"], ted["tree_ren"]) == (
        1.0,
        0.0,
        0.0,
    )


def test_chunk_folds_text_interrupted_by_a_child():
    doc = flatten(xml("<Doc><P>before <B>bold</B> after</P></Doc>"))
    assert [c.norm for c in doc.chunks] == ["before after", "bold"]
    assert Counter(doc.tok_chunk) == Counter({0: 2, 1: 1})


# -- the label-model check ----------------------------------------------------------------------

RAN = "anthropic/claude-haiku-4-5"  # the label model in the msa_tree fixture's usage.jsonl


@pytest.mark.parametrize(
    ("name", "config", "expected"),
    [
        ("config.toml", f'[generation]\nlabel_model = "{RAN}"\n', []),
        ("config.toml", '[generation]\nlabel_model = "anthropic/claude-opus-5"\n', ["mismatch"]),
        ("config.json", '// older dgml\n{"generation": {"label_model": "x/other"}}', ["mismatch"]),
        ("config.toml", "[generation\n", ["config_unreadable"]),
        (None, "", ["no_config"]),
    ],
)
def test_the_configured_label_model_is_checked_against_the_one_that_ran(
    tmp_path, name, config, expected
):
    run_dir, corpus_root, work_dir = extract("msa_tree", tmp_path)
    (usage,) = work_dir.rglob("usage.jsonl")
    if name:
        usage.with_name(name).write_text(config)
    economics = next(r for r in score(run_dir, corpus_root, work_dir) if r["family"] == "economics")
    found = [w for w in economics["warnings"] if w in ("no_config", "config_unreadable")]
    found += ["mismatch" for w in economics["warnings"] if w.startswith("label_model_mismatch")]
    assert found == expected
