"""Extract each scoring fixture and score it once with this repo, for every test module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from model_compass.corpus.loader import load_corpus
from model_compass.corpus.selector import CorpusSelector
from model_compass.scoring import score_run

from .. import helpers

HERE = Path(__file__).parent
CASES = sorted(p.name.removesuffix(".tar.gz") for p in (HERE / "fixtures").glob("*.tar.gz"))
FAMILIES = ["extraction", "reference_free", "economics", "tree"]


def extract(case: str, into: Path) -> tuple[Path, Path, Path]:
    """``(run_dir, corpus_root, work_dir)`` of an extracted fixture."""
    base = helpers.extract(HERE / "fixtures" / f"{case}.tar.gz", into) / case
    (run_dir,) = (base / "runs").iterdir()
    return run_dir, base / "corpus", base / "work"


def score(run_dir: Path, corpus_root: Path, work_dir: Path) -> list[dict]:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    corpus, _ = load_corpus(corpus_root, CorpusSelector.model_validate(manifest["spec"]["corpus"]))
    result = score_run(run_dir, corpus=corpus, families=FAMILIES, work_dir=work_dir)
    assert [c.scored for c in result.cells] == [True]
    (metrics,) = (run_dir / "metrics").glob("*.jsonl")
    return [json.loads(line) for line in metrics.read_text().splitlines()]


@pytest.fixture(scope="session")
def scored(tmp_path_factory):
    """``{case: (expected source records, this repo's records)}``."""
    out = {}
    for case in CASES:
        actual = score(*extract(case, tmp_path_factory.mktemp(case)))
        lines = (HERE / "expected" / f"{case}.jsonl").read_text().splitlines()
        out[case] = ([json.loads(line) for line in lines], actual)
    return out
