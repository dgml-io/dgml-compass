"""Cost model, prices, the manifest's event folding, and resume."""

from __future__ import annotations

import json

import pytest

from model_compass.config import load_settings
from model_compass.errors import ConfigError
from model_compass.experiments.manifest import CellStatus, EventKind, RunEvent, RunOutcome
from model_compass.experiments.plan import DropReason, is_complete, plan
from model_compass.experiments.spec import load_spec
from model_compass.pricing import (
    ModelPrice,
    estimate_generation,
    load_prices,
    load_run_prices,
    write_run_prices,
)

from ..helpers import SPECS
from .conftest import PRICES, make_spec, mini_corpus

CHEAP = ModelPrice(id="a/cheap", input_per_mtok=1.0, output_per_mtok=5.0)
DEAR = ModelPrice(id="a/dear", input_per_mtok=10.0, output_per_mtok=50.0)


def test_the_shipped_prices_cover_every_model_a_spec_uses():
    prices = load_prices(load_settings().prices_file)
    used = set()
    for path in SPECS.rglob("*.yaml"):
        spec = load_spec(path)
        for values in (*spec.axes.values(), *([v] for v in spec.fixed.values())):
            used |= {v for v in values if isinstance(v, str) and "/" in v}
    assert used and used <= {name for name, price in prices.items() if price.priced}


def test_the_estimate_is_the_cost_formula():
    one = estimate_generation(
        n_documents=6,
        generation_model="a/cheap",
        label_model="a/dear",
        prices={"a/cheap": CHEAP, "a/dear": DEAR},
    )
    pages = 6 * 10.0
    transcribe = (pages * (1200 + 1500) * 1.0 + pages * max(1200 * 1.5, 600) * 5.0) / 1e6
    label = (20_000 * 10.0 + 3_000 * 50.0) / 1e6  # one batch of up to ten documents
    assert one.by_slot == {
        "generation.model": round(transcribe, 6),
        "generation.label_model": label,
    }
    eleven = estimate_generation(
        n_documents=11, generation_model=None, label_model="a/dear", prices={"a/dear": DEAR}
    )
    assert eleven.usd == pytest.approx(2 * label)
    assert (
        estimate_generation(
            n_documents=0, generation_model="a/cheap", label_model=None, prices={}
        ).usd
        == 0
    )


def test_an_unpriced_model_is_named_not_free():
    listed = ModelPrice(id="a/listed")
    estimate = estimate_generation(
        n_documents=2,
        generation_model="a/listed",
        label_model="a/absent",
        prices={"a/listed": listed},
    )
    assert estimate.usd == 0 and estimate.unpriced_models == ("a/absent", "a/listed")


def test_prices_load_from_a_file_and_travel_with_the_run(tmp_path):
    registry = tmp_path / "prices.yaml"
    registry.write_text(
        "version: '7'\nmodels:\n  - {id: a/cheap, input_per_mtok: 1, output_per_mtok: 5}\n"
    )
    assert load_prices(registry) == {"a/cheap": CHEAP}
    with pytest.raises(ConfigError, match="not found"):
        load_prices(tmp_path / "missing.yaml")
    registry.write_text("models: []\n")
    with pytest.raises(ConfigError, match="no models"):
        load_prices(registry)
    write_run_prices(tmp_path, {"a/cheap": CHEAP}, source="prices.yaml", version="7")
    assert load_run_prices(tmp_path) == {"a/cheap": CHEAP}
    assert json.loads((tmp_path / "prices.json").read_text())["version"] == "7"


def test_plan_totals_budget_precedence_and_drops(settings):
    spec = make_spec(metrics=["extraction"], budget_usd=7.0)
    corpus = mini_corpus(spec)
    built = plan(spec, settings, corpus, prices=PRICES)
    assert built.estimated_usd == pytest.approx(sum(c.estimate.usd for c in built.cells) * 3)
    assert built.budget_usd == 7.0
    assert plan(spec, settings, corpus, prices=PRICES, budget_usd=3.0).budget_usd == 3.0
    assert plan(make_spec(), settings, corpus, prices=PRICES).budget_usd == settings.budget_usd
    assert "a/cheap" in built.render() and built.to_json().startswith("{")
    loose = make_spec(
        corpus={
            "docsets": ["redorg000001/dsred0000001", "grnorg000001/dsgrn0000001"],
            "max_files_per_docset": 2,
            "sampling": "random",
        }
    )
    assert all(
        d.reason is not DropReason.NO_GOLD
        for d in plan(loose, settings, mini_corpus(loose), prices=PRICES).dropped
    )


def test_planning_refuses_a_family_it_cannot_score(settings):
    with pytest.raises(ConfigError, match="shape"):
        plan(make_spec(metrics=["shape"]), settings, mini_corpus(make_spec()), prices={})


def _status(directory, status="succeeded", **extra):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "status.json").write_text(json.dumps({"status": status, **extra}))


def test_a_status_file_alone_or_a_failed_one_is_not_complete(tmp_path):
    _status(tmp_path)
    assert not is_complete(tmp_path)
    (tmp_path / "result.json").write_text("{}")
    assert is_complete(tmp_path)
    _status(tmp_path, "dry_run")
    assert is_complete(tmp_path) and not is_complete(tmp_path, accept_dry_run=False)
    _status(tmp_path, "failed")
    assert not is_complete(tmp_path)
    (tmp_path / "status.json").write_text("{corrupt")
    assert not is_complete(tmp_path)


def test_flat_artifacts_under_a_multi_draw_cell_count_as_complete(settings):
    spec = make_spec()
    built = plan(spec, settings, mini_corpus(spec), prices=PRICES)
    cell_dir = settings.runs_dir / "r1" / "cells" / built.cells[0].cell_id
    _status(cell_dir, cost_usd=1.5)
    (cell_dir / "result.json").write_text("{}")
    resumed = plan(spec, settings, mini_corpus(spec), prices=PRICES, resume_run_id="r1")
    assert len(resumed.cells) == len(built.cells) - 1
    (done,) = resumed.already_complete
    manifest = resumed.to_manifest()
    assert manifest.cells[done.cell_id].status is CellStatus.SUCCEEDED
    assert manifest.costs.actual_usd == 1.5 and manifest.run_id == "r1"


def test_a_failed_draw_keeps_its_cell_failed_and_outcomes_derive(settings):
    spec = make_spec()
    manifest = plan(spec, settings, mini_corpus(spec), prices=PRICES).to_manifest()
    first, second = sorted(manifest.cells)
    for event in [
        RunEvent(kind=EventKind.RUN_STARTED, payload={"estimated_usd": 1.0}),
        RunEvent(
            kind=EventKind.CELL_FAILED,
            cell_id=first,
            payload={"draw_index": 0, "code": "x", "cost_usd": 0.5},
        ),
        *[
            RunEvent(
                kind=EventKind.CELL_SUCCEEDED,
                cell_id=first,
                payload={"draw_index": i, "cost_usd": 1.0},
            )
            for i in (1, 2)
        ],
        *[
            RunEvent(
                kind=EventKind.CELL_SUCCEEDED,
                cell_id=second,
                payload={"draw_index": i, "cost_usd": 1.0},
            )
            for i in (0, 1, 2)
        ],
    ]:
        manifest.apply(event)
    assert manifest.cells[first].status is CellStatus.FAILED
    assert manifest.cells[first].cost_usd == 2.5 and manifest.costs.actual_usd == 5.5
    assert manifest.cells[second].status is CellStatus.SUCCEEDED
    assert manifest.derive_outcome() is RunOutcome.PARTIAL
    manifest.apply(RunEvent(kind=EventKind.RUN_ABORTED, payload={"reason": "budget_aborted"}))
    assert manifest.outcome is RunOutcome.BUDGET_ABORTED
    with pytest.raises(Exception, match="unknown cell"):
        manifest.apply(RunEvent(kind=EventKind.CELL_STARTED, cell_id="nope"))
