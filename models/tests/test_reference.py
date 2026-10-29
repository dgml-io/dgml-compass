"""``model_compass.reference`` (``dgc sweep``, ``dgc reference``): the sweep, the export after
each sweep and the summary table, over the real-run fixtures of ``tests/aggregate`` and the
committed ``results/reference``."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from model_compass.aggregate.grid import aggregate_run
from model_compass.cli import main
from model_compass.report import write_report

from .aggregate.conftest import extract

MODELS = Path(__file__).resolve().parents[1]
REFERENCE = MODELS / "results" / "reference"
RUN = "20261008-140547-4fe5464b"  # compass-corpus-3x6-haiku55 cut to 8 cells, one model pair
PROFILE = "conf/profiles/local.example.yaml"


@pytest.fixture(scope="module")
def reference():
    from model_compass import reference

    return reference


@pytest.fixture(scope="module")
def exported(reference, tmp_path_factory):
    runs = extract(tmp_path_factory.mktemp("runs"))
    aggregate_run(runs[RUN])
    write_report(runs[RUN])
    out = tmp_path_factory.mktemp("results")
    target = reference.export(runs[RUN], out, None)
    return out, target


def test_export_writes_the_set_for_one_spec(exported):
    out, target = exported
    assert target == out / "compass-corpus-3x6-haiku55"
    names = sorted(p.name for p in target.iterdir())
    assert names == sorted(
        [
            "summary.json",
            "cells.csv",
            "compass_grid.csv",
            "validity.json",
            "by_shape.csv",
            "best_by_shape.csv",
            "gates.csv",
            "cost_by_model.csv",
            "failures.csv",
        ]
    )
    assert "report.md" not in names  # its provenance block names machine-local repositories


def test_cells_csv_is_the_shapes_by_models_table(reference, exported):
    _, target = exported
    with (target / "cells.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert [*rows[0]] == list(reference.CELL_COLUMNS)
    assert len(rows) == 8 and len({r["docset"] for r in rows}) == 8
    assert {r["transcriber"] for r in rows} == {"anthropic/claude-haiku-5-5"}
    assert {r["shape"] for r in rows} == {"form", "hybrid_composite", "prose_narrative"}
    for row in rows:
        assert row["draws"] == "3"
        assert 0 <= float(row["quality"]) <= 100
        assert int(row["total_tokens"]) > 0 and float(row["cost_usd"]) > 0
        assert float(row["tokens_per_doc"]) == pytest.approx(
            int(row["total_tokens"]) / int(row["documents"]), abs=0.5
        )


def test_summary_totals_agree_with_cells_and_manifest(exported):
    _, target = exported
    info = json.loads((target / "summary.json").read_text(encoding="utf-8"))
    with (target / "cells.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert info["spec"] == "compass-corpus-3x6-haiku55" and info["run_id"] == RUN
    assert info["cells"] == 8 and info["cells_failed"] == 0 and info["outcome"] == "succeeded"
    assert info["total_tokens"] == sum(int(r["total_tokens"]) for r in rows)
    assert info["cells_usd"] == pytest.approx(sum(float(r["cost_usd"]) for r in rows), abs=1e-3)
    assert info["measured_usd"] >= info["cells_usd"]
    assert info["quality_metric"] == "individual_overlap_f1"
    assert info["grid_rows"] == 3
    assert set(info["provenance"]) == {
        "corpus_hash",
        "dgml_version",
        "dgml_commit",
        "dgml_dirty",
        "package_version",
    }


def test_report_renders_without_calling_anything(reference, exported):
    out, _ = exported
    text = reference.report(out, write=True)
    assert (out / "README.md").read_text(encoding="utf-8") == text
    assert (
        "| `compass-corpus-3x6-haiku55` | `20261008-140547-4fe5464b` | succeeded | 8 | 3 |" in text
    )
    assert "`anthropic/claude-haiku-5-5` → `anthropic/claude-haiku-5-5`" in text
    assert "(n=5)" in text  # prose_narrative rests on five docsets


def test_report_refuses_an_empty_set(reference, tmp_path):
    with pytest.raises(SystemExit):
        reference.report(tmp_path, write=False)


# --- the committed reference ------------------------------------------------------------------

PUBLIC_DOCSETS = {
    "8frgx7rlbew3",
    "hcqfkilviuq3",
    "i0ycfsrfx0av",
    "nqkh1hkhhkaf",
    "qve3rqreikmn",
    "uzruqpzkyugz",
    "vg52pfjb0wbf",
    "yrrrq1d5kili",
    "o9dmulfkp0ii",
}


@pytest.mark.parametrize("spec_dir", sorted(p.parent for p in REFERENCE.glob("*/summary.json")))
def test_committed_reference_is_complete_and_public(spec_dir):
    info = json.loads((spec_dir / "summary.json").read_text(encoding="utf-8"))
    assert info["spec"] == spec_dir.name
    assert (MODELS / "specs" / f"{spec_dir.name}.yaml").is_file()
    with (spec_dir / "cells.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == info["cells"] > 0
    assert {r["docset"] for r in rows} <= PUBLIC_DOCSETS
    for name in ("compass_grid.csv", "validity.json", "by_shape.csv", "cost_by_model.csv"):
        assert (spec_dir / name).is_file()
    for path in spec_dir.iterdir():
        text = path.read_text(encoding="utf-8")
        assert "/Users/" not in text and "/home/" not in text, path


def test_committed_index_is_current(reference):
    """``report`` output is committed next to the data it summarises."""
    assert reference.report(REFERENCE, write=False) == (REFERENCE / "README.md").read_text(
        encoding="utf-8"
    )


def test_sweep_plans_and_stops_without_yes(reference, monkeypatch):
    monkeypatch.chdir(MODELS)
    calls = []
    monkeypatch.setattr(reference, "_call", lambda cmd: calls.append(cmd[3:]) or 0)
    monkeypatch.setattr(reference, "_capture", lambda cmd: pytest.fail("a paid run started"))
    assert main(["sweep", "--spec", "tiny"]) == 1
    assert calls == [["plan", "-e", "specs/tiny.yaml"]]


def test_sweep_runs_scores_and_exports_each_spec(reference, monkeypatch, tmp_path):
    monkeypatch.chdir(MODELS)
    calls, exported = [], []

    def call(cmd):
        calls.append(cmd[3:])
        return 2 if cmd[3] == "aggregate" else 0  # 2: rows not comparable, not an error

    def capture(cmd):
        calls.append(cmd[3:])
        return 0, "planned\nwrote runs/20261026-000000-abcdef12\n"

    monkeypatch.setattr(reference, "_call", call)
    monkeypatch.setattr(reference, "_capture", capture)
    monkeypatch.setattr(reference, "export", lambda *a: exported.append(a))
    monkeypatch.setattr(reference, "report", lambda root, write: "")
    out = tmp_path / "latest"
    argv = ["sweep", "--spec", "tiny", "--yes", "--out", str(out), "--allow-dirty-corpus"]
    assert main(argv) == 0
    run_id = "20261026-000000-abcdef12"
    assert calls == [
        ["plan", "-e", "specs/tiny.yaml"],
        ["run", "-e", "specs/tiny.yaml", "--yes", "--allow-dirty-corpus"],
        ["score", "-r", run_id],
        ["aggregate", "-r", run_id],
        ["report", "-r", run_id],
    ]
    assert exported == [(Path("runs") / run_id, out, "tiny")]


def test_sweep_passes_the_global_options_on(reference, monkeypatch):
    monkeypatch.chdir(MODELS)
    calls = []
    monkeypatch.setattr(reference, "_call", lambda cmd: calls.append(cmd[3:]) or 0)
    assert main(["--profile", PROFILE, "sweep", "--spec", "tiny"]) == 1
    assert calls == [["--profile", PROFILE, "plan", "-e", "specs/tiny.yaml"]]


def test_sweep_stops_when_a_run_names_no_directory(reference, monkeypatch, capsys):
    monkeypatch.chdir(MODELS)
    monkeypatch.setattr(reference, "_call", lambda cmd: 0)
    monkeypatch.setattr(reference, "_capture", lambda cmd: (0, "no run directory here\n"))
    monkeypatch.setattr(reference, "export", lambda *a: pytest.fail("exported"))
    assert main(["sweep", "--spec", "tiny", "--yes"]) == 1
    assert "run_dir_missing" in capsys.readouterr().err
