"""The loader against the synthetic mini corpus (never the real one)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from model_compass.config import load_settings
from model_compass.corpus.check import CODES, has_text_layer
from model_compass.corpus.loader import load_corpus
from model_compass.corpus.models import Severity, ShapeBasis
from model_compass.corpus.refs import InstanceState
from model_compass.corpus.selector import CorpusSelector
from model_compass.corpus.shapes import UnmappedDocset, load_shape_map
from model_compass.errors import ConfigError, CorpusError

from ..helpers import MINI

RED, GREEN = "redorg000001", "grnorg000001"
RED_DS, GREEN_DS = "dsred0000001", "dsgrn0000001"


def selector(**overrides):
    return CorpusSelector.model_validate(
        {"docsets": {"all_with_refs": True}, "max_files_per_docset": 100, **overrides}
    )


@pytest.fixture
def loaded(mini_shapes):
    return load_corpus(MINI, selector(), shapes=mini_shapes)


def snapshot(root: Path):
    seen = {}
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs.sort()
        for name in files:
            stat = (Path(base) / name).stat()
            seen[f"{base}/{name}"] = (stat.st_size, stat.st_mtime_ns)
    return seen


# -- loading -------------------------------------------------------------------------------


def test_loads_both_orgs_and_writes_nothing(mini_shapes):
    before = snapshot(MINI)
    corpus, _ = load_corpus(MINI, selector(), shapes=mini_shapes)
    assert snapshot(MINI) == before
    assert [org.org_id for org in corpus.orgs] == [GREEN, RED]
    assert {d.docset_id for d in corpus.docsets} == {RED_DS, GREEN_DS}


def test_symlinks_and_skip_directories_are_not_walked(loaded):
    # ``mini_corpus/mini_corpus -> .`` is deliberate: following it would load every docset twice
    # (and recurse), so the loader must never follow symlinks.
    assert (MINI / "mini_corpus").is_symlink(), "fixture must keep its self-symlink"
    corpus, _ = loaded
    paths = [d.path for d in corpus.docsets] + [doc.path for doc in corpus.documents]
    assert not any(p.count("mini_corpus") > 1 for p in paths)
    for skipped in ("NO_REF", "Schemas", "field_name_check", ".render_cache"):
        assert not any(skipped in p for p in paths)


def test_a_missing_root_is_a_corpus_error(tmp_path):
    with pytest.raises(CorpusError) as caught:
        load_corpus(tmp_path / "absent", selector())
    assert caught.value.code == "corpus_missing"


def test_documents_resolve_per_docset_not_by_name(loaded):
    corpus, _ = loaded
    red, green = corpus.docset(RED, RED_DS), corpus.docset(GREEN, GREEN_DS)
    assert {d.name for d in red.documents} == {"alpha.pdf", "shared.pdf", "scan.pdf"}
    red_shared = next(d for d in red.documents if d.name == "shared.pdf")
    green_shared = next(d for d in green.documents if d.name == "shared.pdf")
    assert red_shared.file_id == "red000000002" != green_shared.file_id


# -- gold ------------------------------------------------------------------------------------


def test_flat_ref_values_keep_text_offsets_and_whitespace(loaded):
    corpus, _ = loaded
    flat = corpus.docset(RED, RED_DS).flat_ref
    (party,) = flat.values_for("red000000001::Party+Name")
    assert (party.text, party.start_token) == ("ACME LIMITED", 4)
    (ref,) = flat.values_for("red000000001::Reference")
    assert (ref.text, ref.start_token, ref.raw) == ("Order # 40 - 12", 31, "Order # 40 - 12#31")
    (total,) = flat.values_for("red000000002::Total")
    assert total.text == '" 17 "'
    keys = {k.label: k for k in flat.keys}
    assert keys["Party+Name"].text_label == "Party Name"


def test_typed_ref_and_unfamiliar_types(loaded):
    corpus, report = loaded
    typed = corpus.docset(RED, RED_DS).typed_ref
    assert typed.type_of("red000000002::Total") == "table"
    assert typed.type_of("nope::Nope") is None
    entry = corpus.docset(GREEN, GREEN_DS).typed_ref.entries["grn000000003::Rate"]
    assert (entry.type, entry.known_type) == ("spreadsheet_cell", False)
    assert "unknown_ref_type" in report.by_code()


def test_complex_ref_keeps_verified_absent_and_unverified_apart(loaded):
    corpus, _ = loaded
    cref = corpus.docset(RED, RED_DS).complex_ref
    assert cref.state_for("red000000001", "PartyInfo") is InstanceState.VERIFIED
    assert cref.state_for("red000000002", "PartyInfo") is InstanceState.ABSENT
    assert cref.state_for("red000000003", "PartyInfo") is InstanceState.UNVERIFIED
    assert {e.state for e in cref.scored_entries()} == {
        InstanceState.VERIFIED,
        InstanceState.ABSENT,
    }
    absent = next(e for e in cref.entries if e.state is InstanceState.ABSENT)
    assert absent.instances == ()


def test_complex_members_list_vs_string_and_spec_source(loaded):
    corpus, _ = loaded
    cref = corpus.docset(RED, RED_DS).complex_ref
    totals = next(e for e in cref.entries if e.type_name == "TotalsList")
    assert totals.instances[0].members["Total"] == ("one", "two", "three")
    party = next(e for e in cref.entries if e.type_name == "PartyInfo" and e.instances)
    assert party.instances[0].members["Party+Name"] == "ACME LIMITED"
    assert cref.curated is True
    assert corpus.docset(GREEN, GREEN_DS).complex_ref.curated is False


# -- integrity ---------------------------------------------------------------------------------


def test_findings(loaded):
    _, report = loaded
    assert report.ok
    (orphan,) = [f for f in report.findings if f.code == "orphan_gold"]
    assert (orphan.severity, orphan.docset_id, orphan.count) == (Severity.WARN, RED_DS, 1)
    (dangling,) = [f for f in report.findings if f.code == "dangling_complex_member"]
    assert "Missing+Label" in dangling.message
    assert report.by_code()["duplicate_filename"] == 1
    assert set(report.by_code()) <= set(CODES)


def test_unreadable_json_is_an_error_not_an_exception(tmp_path, mini_shapes):
    copy = tmp_path / "corpus"
    shutil.copytree(MINI, copy, symlinks=True)
    (copy / RED / RED_DS / f"{RED_DS}_{RED}.ref.json").write_text("{not json")
    _, report = load_corpus(copy, selector(), shapes=mini_shapes)
    assert [f.code for f in report.errors] == ["unreadable_json"]


def test_text_layer_check_is_opt_in(mini_shapes, tmp_path):
    assert has_text_layer(MINI / RED / RED_DS / "alpha.pdf") is True
    assert has_text_layer(MINI / RED / RED_DS / "scan.pdf") is False
    (tmp_path / "x.txt").write_text("hello")
    assert has_text_layer(tmp_path / "x.txt") is None
    _, without = load_corpus(MINI, selector(), shapes=mini_shapes)
    _, with_check = load_corpus(MINI, selector(), shapes=mini_shapes, check_text_layer=True)
    assert "no_text_layer" not in without.by_code()
    assert with_check.by_code()["no_text_layer"] == 1


# -- shapes ------------------------------------------------------------------------------------


def test_shapes_attach_and_name_only_is_provisional(loaded, mini_shapes):
    corpus, report = loaded
    red, green = corpus.docset(RED, RED_DS), corpus.docset(GREEN, GREEN_DS)
    assert (red.shape, red.shape_basis) == ("hybrid_composite", ShapeBasis.INSPECTED_SAMPLE)
    assert (green.shape_basis, green.fitted_on) == (ShapeBasis.NAME_ONLY, False)
    assert "provisional_shape" in report.by_code()
    with pytest.raises(UnmappedDocset):
        mini_shapes.get("never-seen")


def test_the_shipped_shape_map_covers_exactly_the_bundled_docsets():
    shapes = load_shape_map()
    root = load_settings(environ={}).corpus_root
    bundled = {p.name for org in root.iterdir() if org.is_dir() for p in org.iterdir()}
    assert set(shapes.docsets) == bundled
    assert len(bundled) == 9
    assert all(s.basis is not ShapeBasis.NAME_ONLY for s in shapes.docsets.values())
    assert not shapes.is_docset("NO_REF")


def test_a_duplicate_shape_entry_is_rejected(tmp_path):
    path = tmp_path / "s.yaml"
    entry = "- {docset_id: a, shape: form, basis: name_only}\n"
    path.write_text("docsets:\n" + entry + entry)
    with pytest.raises(ConfigError, match="listed twice"):
        load_shape_map(path)


# -- selection ---------------------------------------------------------------------------------


def test_include_exclude_shape_and_org_filters(mini_shapes):
    def ids(**kw):
        corpus, _ = load_corpus(MINI, selector(**kw), shapes=mini_shapes)
        return [d.docset_id for d in corpus.docsets]

    assert ids(docsets={"include": [f"{RED}/{RED_DS}"]}) == [RED_DS]
    assert ids(
        docsets={"include": [f"{RED}/{RED_DS}", f"{GREEN}/{GREEN_DS}"], "exclude": [GREEN_DS]}
    ) == [RED_DS]
    assert ids(docsets=[f"{GREEN}/{GREEN_DS}"]) == [GREEN_DS]  # bare list = include
    assert ids(shapes=["hybrid_composite"]) == [RED_DS]
    assert ids(orgs=[RED]) == [RED_DS]


def test_orgs_are_derived_from_qualified_includes():
    sel = CorpusSelector.model_validate({"docsets": [f"{RED}/{RED_DS}", f"{RED}/x", f"{GREEN}/y"]})
    assert sel.org_ids == (RED, GREEN)


def test_fixed_selection_prefers_gold_and_random_keeps_everything(mini_shapes):
    corpus, _ = load_corpus(MINI, selector(max_files_per_docset=2), shapes=mini_shapes)
    assert {d.name for d in corpus.docset(RED, RED_DS).documents} == {"alpha.pdf", "shared.pdf"}
    corpus, _ = load_corpus(
        MINI, selector(max_files_per_docset=2, sampling="random"), shapes=mini_shapes
    )
    assert len(corpus.docset(RED, RED_DS).documents) == 3


def test_suffix_validation():
    assert CorpusSelector.model_validate({"docsets": ["a/b"], "suffixes": ["PDF"]}).suffixes == (
        ".pdf",
    )
    with pytest.raises(ValueError, match="unknown suffix"):
        CorpusSelector.model_validate({"docsets": ["a/b"], "suffixes": [".txt"]})


def test_consumed_paths_cover_documents_and_gold(loaded):
    corpus, _ = loaded
    paths = corpus.consumed_paths()
    assert f"{RED}/{RED_DS}/alpha.pdf" in paths
    assert f"{RED}/{RED_DS}/{RED_DS}_{RED}.complex_ref.json" in paths
    assert paths == tuple(sorted(paths))
    assert [d.docset_id for d in corpus.for_ref(f"{RED}/{RED_DS}").docsets] == [RED_DS]
