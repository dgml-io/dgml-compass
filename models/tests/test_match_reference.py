"""``dgc reference match``: a run against ``results/reference``, over the real-run
fixtures of ``tests/aggregate`` (``compass-corpus-3x6-haiku55`` cut to 8 cells)."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from model_compass.cli import main

from .aggregate.conftest import extract

MODELS = Path(__file__).resolve().parents[1]
REFERENCE = MODELS / "results" / "reference"
RUN = "20261008-140547-4fe5464b"
SPEC = "compass-corpus-3x6-haiku55"


def _match(argv: list[str]) -> int:
    return main(["reference", "match", *argv])


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory) -> Path:
    return extract(tmp_path_factory.mktemp("runs"))[RUN]


def _reference_copy(tmp_path: Path, edit) -> Path:
    """``results/reference/<SPEC>`` copied, with ``edit(rows)`` applied to its cells.csv."""
    root = tmp_path / "reference"
    shutil.copytree(REFERENCE / SPEC, root / SPEC)
    path = root / SPEC / "cells.csv"
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields, rows = reader.fieldnames, list(reader)
    edit(rows)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return root


def test_the_reference_run_matches_itself(run_dir, tmp_path, capsys):
    out = tmp_path / "pairs.json"
    code = _match([str(run_dir), "--spec", SPEC, "--json", str(out)])
    text = capsys.readouterr().out
    pairs = json.loads(out.read_text(encoding="utf-8"))
    assert code == 0
    assert "**8/8 pairs match** (8 same-cell, 0 same-models)" in text
    assert {p["pairing"] for p in pairs} == {"same cell"}
    assert all(p["quality_delta"] == pytest.approx(0, abs=0.01) for p in pairs)
    assert all(p["tokens_per_doc_ratio"] == pytest.approx(1, abs=0.01) for p in pairs)


def test_a_quality_drift_is_a_finding(run_dir, tmp_path, capsys):
    def drift(rows):
        row = next(r for r in rows if r["docset"] == "8frgx7rlbew3")
        row["quality"] = f"{float(row['quality']) - 30:.2f}"

    root = _reference_copy(tmp_path, drift)
    assert _match([str(run_dir), "--reference", str(root)]) == 2
    text = capsys.readouterr().out
    assert "**7/8 pairs match**" in text
    assert "| **off** | same cell |" in text


def test_other_cell_ids_pair_on_the_models(run_dir, tmp_path, capsys):
    def reseed(rows):
        for row in rows:
            row["cell_id"] = "x" + row["cell_id"][1:]

    root = _reference_copy(tmp_path, reseed)
    assert _match([str(run_dir), "--reference", str(root)]) == 0
    text = capsys.readouterr().out
    assert "(0 same-cell, 8 same-models)" in text
    assert "indicative, not a reproduction check" in text


def test_cells_without_a_reference_are_listed(run_dir, tmp_path, capsys):
    def other_models(rows):
        for row in rows:
            row["cell_id"] = "x" + row["cell_id"][1:]
            row["labeler"] = "openai/gpt-5.5"

    root = _reference_copy(tmp_path, other_models)
    assert _match([str(run_dir), "--reference", str(root)]) == 2
    text = capsys.readouterr().out
    assert "**0/0 pairs match**" in text and "8 run cell(s) have no reference" in text


def test_an_unscored_run_asks_for_dgc_score(run_dir, tmp_path, capsys):
    bare = tmp_path / RUN
    shutil.copytree(run_dir, bare, ignore=shutil.ignore_patterns("metrics"))
    assert _match([str(bare)]) == 2
    assert f"dgc score -r {RUN}" in capsys.readouterr().err


def test_not_a_run_directory(tmp_path):
    assert _match([str(tmp_path)]) == 1
