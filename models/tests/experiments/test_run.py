"""The runner with a dgml double: the run directory, budget cap, resume, retry_empty."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from model_compass.corpus.sampling import select_for_draw
from model_compass.errors import ConfigError
from model_compass.experiments.manifest import CellStatus, RunManifest, RunOutcome
from model_compass.experiments.plan import draw_dir, is_complete, plan
from model_compass.experiments.run import read_events, run
from model_compass.runs import draw_dirs, load_cells, load_manifest, load_result, load_sidecar
from model_compass.scoring import score_run

from .conftest import PRICES, Doubles, make_spec, mini_corpus

SPEC = make_spec()


def _run(settings, spec=SPEC, doubles=None, **kwargs):
    kwargs.setdefault("dry_run", False)
    kwargs.setdefault("yes", True)
    return run(
        spec,
        settings,
        dgml_client=doubles if doubles is not None else Doubles(),
        corpus=mini_corpus(spec),
        prices=PRICES,
        allow_dirty_corpus=True,
        **kwargs,
    )


def _refuse(cell, workspace):
    raise AssertionError("a dry run must not build a dgml client")


def test_a_dry_run_writes_the_run_directory_and_spends_nothing(settings):
    manifest = run(
        SPEC,
        settings,
        dry_run=True,
        dgml_client=_refuse,
        corpus=mini_corpus(SPEC),
        prices=PRICES,
        allow_dirty_corpus=True,
    )
    run_dir = settings.runs_dir / manifest.run_id
    for name in (
        "manifest.json",
        "events.jsonl",
        "cells.json",
        "prices.json",
        "spec.resolved.yaml",
    ):
        assert (run_dir / name).is_file(), name
    assert manifest.outcome is RunOutcome.DRY_RUN and manifest.costs.actual_usd == 0.0
    assert not settings.work_dir.exists(), "a dry run builds no workspace"
    assert json.loads((run_dir / "prices.json").read_text())["models"]["a/cheap"]["id"] == "a/cheap"
    # DECISIONS 0015: what the plan priced is what the dry run estimates, draw by draw
    built = plan(SPEC, settings, mini_corpus(SPEC), prices=PRICES)
    dry = sum(
        json.loads((d / "status.json").read_text())["cost_usd"]
        for cell in (run_dir / "cells").iterdir()
        for _, d in draw_dirs(cell)
    )
    assert built.estimated_usd > 0 and dry == pytest.approx(built.estimated_usd, abs=1e-9)


def test_a_paid_run_needs_confirmation(settings):
    with pytest.raises(ConfigError) as caught:
        _run(settings, yes=False)
    assert caught.value.code == "confirmation_required"
    assert not settings.runs_dir.exists()


def test_a_run_writes_the_source_layout_and_is_scorable(settings):
    doubles = Doubles()
    manifest = _run(settings, doubles=doubles)
    run_dir = settings.runs_dir / manifest.run_id
    assert manifest.outcome is RunOutcome.SUCCEEDED
    assert len(doubles.made) == len(manifest.cells) * SPEC.draws
    assert len({d.workspace for d in doubles.made}) == len(doubles.made), "a workspace per draw"
    for cell_id, record in manifest.cells.items():
        assert record.status is CellStatus.SUCCEEDED and record.draws_completed == SPEC.draws
        assert record.attempts == 1
        cell_dir = run_dir / "cells" / cell_id
        summary = json.loads((cell_dir / "status.json").read_text())
        assert summary["draws_completed"] == SPEC.draws and summary["missing_dgml_rate"] == 0.0
        for index, directory in draw_dirs(cell_dir):
            assert directory == draw_dir(run_dir, cell_id, index, draws=SPEC.draws)
            for name in ("result.json", "status.json", "usage.jsonl"):
                assert (directory / name).is_file()
            result = load_result(directory)
            sidecar = load_sidecar(directory, None)
            assert result is not None and sidecar is not None
            assert all((directory / "dgml" / doc.xml_path).is_file() for doc in result.documents)
            workspace = Path(result.workspace)
            assert (
                workspace
                == settings.work_dir
                / manifest.run_id
                / cell_id
                / "draws"
                / (f"{index:02d}")
                / "workspace"
            )
            assert (workspace / "config.toml").read_text().count('model = "a/cheap"') == 1
    assert set(load_cells(run_dir)) == set(manifest.cells)
    assert load_manifest(run_dir).run_id == manifest.run_id
    base = plan(SPEC, settings, mini_corpus(SPEC), prices=PRICES, resume_run_id=manifest.run_id)
    assert not base.cells, "everything is complete"

    scored = score_run(run_dir, corpus=mini_corpus(SPEC), work_dir=settings.work_dir)
    assert scored.cells and all(c.scored and c.draws_scored == SPEC.draws for c in scored.cells)
    assert all(c.records > 0 for c in scored.cells)


def test_the_event_log_replays_to_the_manifest(settings):
    manifest = _run(settings)
    run_dir = settings.runs_dir / manifest.run_id
    built = plan(SPEC, settings, mini_corpus(SPEC), prices=PRICES)
    base = built.model_copy(update={"run_id": manifest.run_id}).to_manifest()
    base = base.model_copy(update={"provenance": manifest.provenance})
    replayed = RunManifest.replay(base, read_events(run_dir))
    assert replayed == manifest
    assert json.loads((run_dir / "manifest.json").read_text())["outcome"] == "succeeded"


def test_a_cell_generates_only_its_own_docset_and_each_draw_its_sample(settings):
    doubles = Doubles()
    manifest = _run(settings, doubles=doubles)
    corpus = mini_corpus(SPEC)
    for double in doubles.made:
        cell_id = double.workspace.parts[-4]
        index = int(double.workspace.parts[-2])
        cell = load_cells(settings.runs_dir / manifest.run_id)[cell_id]
        assert [name for name, _ in double.calls].count("docset_create") == 1
        added = {Path(c["path"]).parent.name for name, c in double.calls if name == "file_add"}
        assert added == {cell.docset}
        docset = corpus.docset(cell.org, cell.docset)
        expected = select_for_draw(docset, SPEC.corpus, draw_index=index, seed=SPEC.seed)
        names = sorted(Path(c["path"]).name for name, c in double.calls if name == "file_add")
        assert names == sorted(d.name for d in expected.documents)


def test_max_parallel_calls_reaches_every_docset_generate(settings):
    doubles = Doubles()
    _run(settings.model_copy(update={"max_parallel_calls": 3}), doubles=doubles)
    calls = [c for d in doubles.made for name, c in d.calls if name == "docset_generate"]
    assert calls and {c["max_parallel_calls"] for c in calls} == {3}


def test_the_budget_cap_stops_submission(settings):
    built = plan(SPEC, settings, mini_corpus(SPEC), prices=PRICES)
    one_draw = built.cells[0].estimate.usd
    doubles = Doubles()
    tight = settings.model_copy(update={"max_parallel_cells": 1})
    manifest = _run(tight, doubles=doubles, budget_usd=one_draw * 1.5)
    assert manifest.outcome is RunOutcome.BUDGET_ABORTED
    assert doubles.generated < len(built.cells) * SPEC.draws
    statuses = {record.status for record in manifest.cells.values()}
    assert CellStatus.CANCELLED in statuses
    events = read_events(settings.runs_dir / manifest.run_id)
    assert [e.kind.value for e in events][-2:] == ["run_aborted", "run_finished"]


def test_resume_runs_only_the_missing_draws(settings):
    first = _run(settings)
    run_dir = settings.runs_dir / first.run_id
    cell_id = sorted(first.cells)[0]
    (draw_dir(run_dir, cell_id, 1, draws=3) / "status.json").unlink()
    doubles = Doubles()
    resumed = _run(settings, doubles=doubles, resume_run_id=first.run_id)
    assert resumed.run_id == first.run_id and resumed.outcome is RunOutcome.SUCCEEDED
    assert [d.workspace.parts[-2] for d in doubles.made] == ["01"]
    assert all(r.status is CellStatus.SUCCEEDED for r in resumed.cells.values())


def test_a_failed_draw_fails_its_cell_and_resume_redoes_it(settings):
    manifest = _run(settings, doubles=Doubles("failed"))
    assert manifest.outcome is RunOutcome.FAILED
    record = next(iter(manifest.cells.values()))
    assert record.status is CellStatus.FAILED and record.error_code == "generation_failed"
    run_dir = settings.runs_dir / manifest.run_id
    status = json.loads((draw_dir(run_dir, record.cell_id, 0, draws=3) / "status.json").read_text())
    assert status["status"] == "failed" and status["n_with_xml"] == 0
    doubles = Doubles()
    resumed = _run(settings, doubles=doubles, resume_run_id=manifest.run_id)
    assert resumed.outcome is RunOutcome.SUCCEEDED and len(doubles.made) == 3 * len(resumed.cells)


def test_retry_empty_reruns_succeeded_draws_without_dgml(settings):
    manifest = _run(settings, doubles=Doubles("unreported"))
    run_dir = settings.runs_dir / manifest.run_id
    assert manifest.outcome is RunOutcome.SUCCEEDED, "not_reported is not a generation failure"
    some_draw = draw_dir(run_dir, sorted(manifest.cells)[0], 0, draws=3)
    assert is_complete(some_draw) and not is_complete(some_draw, retry_empty=True)
    plain = Doubles()
    _run(settings, doubles=plain, resume_run_id=manifest.run_id)
    assert plain.made == []
    retried = Doubles()
    after = _run(settings, doubles=retried, resume_run_id=manifest.run_id, retry_empty=True)
    assert len(retried.made) == 3 * len(after.cells)
    assert is_complete(some_draw, retry_empty=True)


@pytest.mark.xfail(
    strict=True,
    reason="known defect 5 (docs/DECISIONS.md): a resumed run rewrites events.jsonl from empty",
)
def test_a_resumed_run_keeps_the_earlier_event_log(settings):
    first = _run(settings)
    run_dir = settings.runs_dir / first.run_id
    before = read_events(run_dir)
    (draw_dir(run_dir, sorted(first.cells)[0], 1, draws=3) / "status.json").unlink()
    _run(settings, resume_run_id=first.run_id)
    assert read_events(run_dir)[: len(before)] == before


@pytest.mark.xfail(
    strict=True,
    reason="known defect 6 (docs/DECISIONS.md): a resumed cell's manifest cost drops its "
    "earlier draws",
)
def test_a_resumed_cell_keeps_the_cost_of_its_earlier_draws(settings):
    first = _run(settings)
    run_dir = settings.runs_dir / first.run_id
    cell_id = sorted(first.cells)[0]
    (draw_dir(run_dir, cell_id, 1, draws=3) / "status.json").unlink()
    resumed = _run(settings, resume_run_id=first.run_id)
    assert resumed.cells[cell_id].cost_usd == pytest.approx(first.cells[cell_id].cost_usd)
