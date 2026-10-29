from itertools import combinations

import pytest

from model_compass.corpus.models import Docset, Document
from model_compass.corpus.refs import FlatRef
from model_compass.corpus.sampling import (
    fixed_selection,
    random_selection,
    sample_seed,
    select_for_draw,
)
from model_compass.corpus.selector import CorpusSelector
from model_compass.errors import ConfigError


def docset(n: int, *, gold: int = 0, docset_id: str = "ds") -> Docset:
    docs = tuple(
        Document(
            name=f"doc{i:02d}.pdf",
            path=f"o/{docset_id}/doc{i:02d}.pdf",
            org="o",
            docset_id=docset_id,
            file_id=f"f{i:02d}",
        )
        for i in range(n)
    )
    # gold on the LAST `gold` documents, so "gold first" is visible
    flat = (
        FlatRef(
            docset_id=docset_id, org="o", entries={f"f{i:02d}::L": () for i in range(n - gold, n)}
        )
        if gold
        else None
    )
    return Docset(
        docset_id=docset_id, org="o", path=f"o/{docset_id}", documents=docs, flat_ref=flat
    )


def names(d: Docset) -> list[str]:
    return [doc.name for doc in d.documents]


def test_fixed_takes_gold_first_then_by_name():
    assert names(fixed_selection(docset(10, gold=2), 4)) == [
        "doc08.pdf",
        "doc09.pdf",
        "doc00.pdf",
        "doc01.pdf",
    ]
    small = docset(3)
    assert fixed_selection(small, 6) is small


def test_random_is_reproducible_sized_ordered_and_a_subset():
    d = docset(20)
    a = random_selection(d, 6, seed=7, draw_index=1)
    assert names(a) == names(random_selection(d, 6, seed=7, draw_index=1))
    assert len(a.documents) == 6 and names(a) == sorted(names(a))
    assert set(names(a)) <= set(names(d))


def test_random_varies_with_draw_seed_and_docset():
    d = docset(20)
    base = names(random_selection(d, 6, seed=7, draw_index=0))
    assert base != names(random_selection(d, 6, seed=7, draw_index=1))
    assert base != names(random_selection(d, 6, seed=8, draw_index=0))
    other = docset(20, docset_id="other")
    assert base != names(random_selection(other, 6, seed=7, draw_index=0))


def test_draws_never_repeat_and_later_draws_do_not_move_earlier_ones():
    d = docset(7)  # 7 choose 6 = 7 subsets: collisions are likely without the redraw rule
    sets = [tuple(names(random_selection(d, 6, seed=3, draw_index=i))) for i in range(7)]
    assert all(a != b for a, b in combinations(sets, 2))


def test_small_docset_is_returned_whole_and_zero_is_refused():
    assert len(random_selection(docset(4), 6, seed=1, draw_index=2).documents) == 4
    with pytest.raises(ConfigError):
        random_selection(docset(4), 0, seed=1, draw_index=0)


def test_seed_string_is_stable():
    assert sample_seed(20260917, "org", "ds", 0) == "dgml.sample.v1:20260917:org/ds:1"


def test_select_for_draw_dispatches_and_random_needs_a_seed():
    d = docset(10, gold=1)
    fixed = CorpusSelector.model_validate({"docsets": ["o/ds"], "max_files_per_docset": 3})
    rand = CorpusSelector.model_validate(
        {"docsets": ["o/ds"], "max_files_per_docset": 3, "sampling": "random"}
    )
    assert names(select_for_draw(d, fixed, draw_index=2, seed=None)) == [
        "doc09.pdf",
        "doc00.pdf",
        "doc01.pdf",
    ]
    assert len(select_for_draw(d, rand, draw_index=0, seed=1).documents) == 3
    with pytest.raises(ConfigError, match="seed"):
        select_for_draw(d, rand, draw_index=0, seed=None)
