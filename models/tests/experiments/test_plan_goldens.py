"""The planner against its goldens: same cells, same draw samples, same prices, for every spec.
Expected values come from ``scripts/make_golden_plans.py``."""

from __future__ import annotations

import json

import pytest

from model_compass.config import load_settings
from model_compass.corpus.loader import load_corpus
from model_compass.corpus.sampling import draw_corpus
from model_compass.corpus.shapes import load_shape_map
from model_compass.experiments.plan import plan
from model_compass.experiments.spec import load_spec
from model_compass.pricing import ModelPrice, load_prices

from ..helpers import GOLDEN, MINI, SPECS

PLANS = GOLDEN / "plans"
CASES = [pytest.param(path, id=path.stem) for path in sorted(PLANS.glob("*.json"))]


def test_every_carried_spec_has_a_golden_plan():
    specs = {p.relative_to(SPECS).as_posix() for p in SPECS.rglob("*.yaml")}
    assert specs == {json.loads(p.read_text())["spec"] for p in PLANS.glob("*.json")}


def _plan(golden, tmp_path, prices):
    spec = load_spec(SPECS / golden["spec"])
    if golden["corpus"] == "bundled":
        root, shapes = load_settings(environ={}).corpus_root, None
    else:
        root, shapes = MINI, load_shape_map(MINI / "shapes.yaml")
    corpus, _ = load_corpus(root, spec.corpus, shapes=shapes)
    settings = load_settings(environ={}, corpus_root=root, runs_dir=tmp_path, work_dir=tmp_path)
    return spec, corpus, plan(spec, settings, corpus, prices=prices)


@pytest.mark.parametrize("path", CASES)
def test_cells_draws_and_estimates_match_the_goldens(path, tmp_path):
    golden = json.loads(path.read_text())
    prices = {k: ModelPrice.model_validate(v) for k, v in golden["prices"].items()}
    spec, corpus, built = _plan(golden, tmp_path, prices)
    cells = [
        {
            "cell_id": item.cell.cell_id,
            "org": item.cell.org,
            "docset": item.cell.docset,
            "shape": item.cell.shape,
            "settings": [list(pair) for pair in item.cell.settings],
            "draws": item.cell.draws,
            "seed": item.cell.seed,
            "n_documents": item.n_documents,
            "estimate_usd": pytest.approx(item.estimate.usd, abs=1e-9),
            "by_slot": pytest.approx(item.estimate.by_slot, abs=1e-9),
            "unpriced_models": list(item.estimate.unpriced_models),
        }
        for item in built.cells
    ]
    assert cells == golden["cells"]  # same ids, order, settings and one-draw estimates
    assert built.estimated_usd == pytest.approx(golden["estimated_usd"], abs=1e-9)
    assert [{"ref": d.ref, "reason": d.reason.value} for d in built.dropped] == golden["dropped"]
    for item in built.cells:
        expected = golden["draw_documents"][item.cell.ref]
        for index in range(item.cell.draws):
            sampled = draw_corpus(corpus, item.cell, spec, index)
            names = [f"{d.ref}/{doc.name}" for d in sampled.docsets for doc in d.documents]
            assert names == expected[index], (item.cell.cell_id, index)


@pytest.mark.parametrize("path", CASES)
def test_estimates_match_the_goldens_with_the_shipped_prices(path, tmp_path):
    golden = json.loads(path.read_text())
    _, _, built = _plan(golden, tmp_path, load_prices(load_settings().prices_file))
    assert built.estimated_usd == pytest.approx(golden["estimated_usd"], abs=1e-9), (
        "conf/prices.yaml changed since the goldens were made: rerun scripts/make_golden_plans.py"
    )
