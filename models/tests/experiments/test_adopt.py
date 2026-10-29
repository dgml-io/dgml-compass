"""Adopting earlier flat executions as draw 00 (DECISIONS 0018)."""

from __future__ import annotations

import json

import pytest

from model_compass.errors import ConfigError
from model_compass.experiments.adopt import adopt
from model_compass.experiments.plan import draw_dir, is_complete, plan
from model_compass.experiments.run import run

from .conftest import PRICES, Doubles, make_spec, mini_corpus

FIXED = {"docsets": {"all_with_refs": True}, "max_files_per_docset": 2, "sampling": "fixed"}
FLAT = make_spec(corpus=FIXED, draws=1)
THREE = make_spec(corpus=FIXED, draws=3)


def _flat_run(settings, outcome="converted"):
    manifest = run(
        FLAT,
        settings,
        yes=True,
        dgml_client=Doubles(outcome),
        corpus=mini_corpus(FLAT),
        prices=PRICES,
        allow_dirty_corpus=True,
    )
    return manifest.run_id


def _adopt(settings, sources, **kwargs):
    return adopt(THREE, settings, sources, corpus=mini_corpus(THREE), **kwargs)


def test_adopt_seeds_draw_zero_and_resume_prices_the_rest(settings):
    source = _flat_run(settings)
    result = _adopt(settings, [source], into="target")
    assert len(result.adopted) == 2 and all(a.draws == 1 and a.files > 0 for a in result.adopted)
    target = settings.runs_dir / "target"
    for item in result.adopted:
        assert is_complete(draw_dir(target, item.cell_id, 0, draws=3), accept_dry_run=False)
    adoption = json.loads((target / "adoption.json").read_text())
    assert {a["source_run"] for a in adoption["adopted"]} == {source}
    assert (target / "cells.json").is_file()
    resumed = plan(THREE, settings, mini_corpus(THREE), prices=PRICES, resume_run_id="target")
    assert all(item.draws_done == 1 and len(item.draws) == 2 for item in resumed.cells)
    again = _adopt(settings, [source], into="target")
    assert {a.reason for a in again.cells} == {"target_has_draw_00"}


def test_adopt_refuses_other_documents_missing_dgml_and_excluded_models(settings):
    source = _flat_run(settings)
    cells = sorted((settings.runs_dir / source / "cells").iterdir())
    sidecar = cells[0] / "workspace" / "mca-workspace.json"
    data = json.loads(sidecar.read_text())
    data["entries"][0]["name"] = "someone-else.pdf"
    sidecar.write_text(json.dumps(data))
    result = _adopt(settings, [source], into="target")
    reasons = {a.cell_id: a.reason for a in result.cells}
    assert reasons[cells[0].name] == f"documents_differ:{source}"
    assert reasons[cells[1].name] == ""

    empty = _flat_run(
        settings.model_copy(update={"runs_dir": settings.runs_dir / "e"}), "unreported"
    )
    elsewhere = settings.runs_dir / "e" / empty
    assert {a.reason for a in _adopt(settings, [str(elsewhere)], dry_run=True).cells} == {
        f"no_dgml:{empty}"
    }
    excluded = _adopt(settings, [source], exclude_models=["a/cheap"], dry_run=True)
    assert {a.reason for a in excluded.cells} == {"excluded_model:a/cheap"}


def test_an_adopt_dry_run_writes_nothing(settings):
    source = _flat_run(settings)
    result = _adopt(settings, [source], into="target", dry_run=True)
    assert {a.action for a in result.cells} == {"would_adopt"}
    assert not (settings.runs_dir / "target").exists()


def test_adopt_refuses_a_single_draw_spec(settings):
    with pytest.raises(ConfigError, match="more than one draw"):
        adopt(FLAT, settings, ["x"], corpus=mini_corpus(FLAT))
