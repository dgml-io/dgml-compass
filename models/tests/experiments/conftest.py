from __future__ import annotations

import pytest

from model_compass.config import load_settings
from model_compass.corpus.loader import load_corpus
from model_compass.corpus.shapes import load_shape_map
from model_compass.experiments.spec import ExperimentSpec
from model_compass.pricing import ModelPrice

from ..helpers import MINI
from .doubles import FakeDgml

PRICES = {"a/cheap": ModelPrice(id="a/cheap", input_per_mtok=1.0, output_per_mtok=5.0)}


def make_spec(**overrides) -> ExperimentSpec:
    payload = {
        "name": "draws-test",
        "corpus": {
            "docsets": {"all_with_refs": True},
            "max_files_per_docset": 2,
            "sampling": "random",
        },
        "axes": {"generation.model": ["a/cheap"]},
        "metrics": ["extraction", "reference_free", "economics", "tree"],
        "draws": 3,
        "seed": 20260917,
    }
    payload.update(overrides)
    return ExperimentSpec.model_validate(payload)


def mini_corpus(spec: ExperimentSpec):
    corpus, _ = load_corpus(MINI, spec.corpus, shapes=load_shape_map(MINI / "shapes.yaml"))
    return corpus


@pytest.fixture
def settings(tmp_path):
    return load_settings(
        environ={},
        corpus_root=MINI,
        runs_dir=tmp_path / "runs",
        work_dir=tmp_path / "work",
        dgml_repo=tmp_path / "no-dgml",
        prices_file=tmp_path / "no-prices.yaml",
        budget_usd=100.0,
        max_parallel_cells=2,
    )


class Doubles:
    """A dgml factory that remembers every double it handed out."""

    def __init__(self, outcome: str = "converted") -> None:
        self.outcome = outcome
        self.made: list[FakeDgml] = []

    def __call__(self, cell, workspace):
        double = FakeDgml(workspace, outcome=self.outcome)
        self.made.append(double)
        return double

    @property
    def generated(self) -> int:
        return sum(1 for d in self.made for name, _ in d.calls if name == "docset_generate")
