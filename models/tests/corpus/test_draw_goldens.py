"""Draw membership must not change: sampled documents are part of what a cell means.

``golden/draws.json`` is the frozen expected membership, and two of its cases were also
checked against the documents real runs generated. One test feeds the recorded
population to the sampler; the other re-loads the bundled corpus with the loader.
"""

import json

import pytest

from model_compass.config import load_settings
from model_compass.corpus.loader import load_corpus
from model_compass.corpus.models import Docset, Document
from model_compass.corpus.refs import FlatRef
from model_compass.corpus.sampling import select_for_draw
from model_compass.corpus.selector import CorpusSelector

from ..helpers import GOLDEN

CASES = json.loads((GOLDEN / "draws.json").read_text())["cases"]
IDS = [f"{c['ref']}@{c['seed']}-{c['sampling']}" for c in CASES]


def selector(case, sampling: str | None = None) -> CorpusSelector:
    return CorpusSelector.model_validate(
        {
            "docsets": [case["ref"]],
            "suffixes": case["suffixes"],
            "sampling": sampling or case["sampling"],
            "max_files_per_docset": case["max_files_per_docset"],
        }
    )


def test_cover_both_samplings_and_seeds_with_run_evidence():
    assert {(c["sampling"], c["seed"]) for c in CASES} >= {
        ("fixed", 20260917),
        ("random", 20260917),
        ("random", 20260925),
    }
    assert sum(c["verified_against_run"] is not None for c in CASES) >= 2


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_sampler_reproduces_the_draws(case):
    org, docset_id = case["ref"].split("/")
    docs = tuple(
        Document(name=name, path=f"{case['ref']}/{name}", org=org, docset_id=docset_id, file_id=fid)
        for name, fid in case["population"]
    )
    flat = FlatRef(
        docset_id=docset_id, org=org, entries={f"{fid}::L": () for fid in case["gold_file_ids"]}
    )
    docset = Docset(docset_id=docset_id, org=org, path=case["ref"], documents=docs, flat_ref=flat)
    for index, expected in enumerate(case["draws"]):
        chosen = select_for_draw(docset, selector(case), draw_index=index, seed=case["seed"])
        assert [d.name for d in chosen.documents] == expected, f"draw {index}"


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_loader_and_sampler_reproduce_the_draws_on_the_bundled_corpus(case):
    root = load_settings(environ={}).corpus_root
    sel = selector(case)
    corpus, _ = load_corpus(root, selector(case, "random"))  # random keeps every doc
    (full,) = corpus.docsets
    assert [[d.name, d.file_id] for d in full.documents] == case["population"], "corpus drifted"
    corpus, _ = load_corpus(root, sel)
    (loaded,) = corpus.docsets
    for index, expected in enumerate(case["draws"]):
        chosen = select_for_draw(loaded, sel, draw_index=index, seed=case["seed"])
        assert [d.name for d in chosen.documents] == expected, f"draw {index}"
