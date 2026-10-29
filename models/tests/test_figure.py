"""``dgc figure``: the points of ``figures/quality_cost.svg`` are the pipelines of
docs/RESULTS.md §6, recomputed from the committed ``results/reference``, and the
committed figure is what the script draws from them."""

from __future__ import annotations

from pathlib import Path

import pytest

MODELS = Path(__file__).resolve().parents[1]

# docs/RESULTS.md §6 (quality, cost per document) and the ± 2 SE of §1, §2, §4, §5
RESULTS = {
    "Haiku 5.5 → Haiku 5.5": (79.0, 0.022, 9.2),
    "Haiku 5.5 → Sonnet 5": (83.1, 0.275, 7.3),
    "Haiku 5.5 → Opus 5": (84.6, 0.790, 8.7),
    "Haiku 5.5 → GPT-5.5": (85.6, 1.422, 8.3),
    "Haiku 5.5 → Gemini 3.6 Flash": (71.2, 0.133, 9.3),
    "Haiku 5.5 → Gemini 3.1 Flash Lite": (56.7, 0.025, 5.7),
    "Sonnet 5 → Haiku 5.5": (78.3, 0.199, 10.1),
    "Opus 5 → Haiku 5.5": (78.5, 0.455, 8.7),
    "GPT-5.5 → Haiku 5.5": (78.8, 0.401, 10.9),
    "Gemini 3.6 Flash → Haiku 5.5": (64.5, 0.108, 16.4),
    "Gemini 3.6 Flash → Gemini 3.6 Flash": (67.0, 0.233, 7.9),
    "Gemini 3.6 Flash → Gemini 3.1 Flash Lite": (59.6, 0.120, 8.1),
    "Gemini 3.6 Flash → GPT-5.5": (83.4, 1.390, 9.0),
    "GPT-5.5 → GPT-5.5": (84.6, 1.363, 9.6),
}


@pytest.fixture(scope="module")
def figure():
    from model_compass import figure

    return figure


def test_points_are_the_pipelines_of_results(figure):
    got = {
        p.label: (round(p.quality, 1), round(p.cost_per_doc, 3), round(p.band_2se, 1))
        for p in figure.points()
    }
    assert got == RESULTS


def test_the_committed_figure_is_up_to_date(figure):
    committed = (MODELS / "figures" / "quality_cost.svg").read_text(encoding="utf-8")
    assert committed == figure.render(figure.points()), "run `dgc figure`"


def test_a_missing_pipeline_is_a_clear_error(figure, tmp_path):
    from model_compass.errors import ConfigError

    for spec in {p[0] for p in figure.PIPELINES}:
        lines = (figure.REFERENCE / spec / "cells.csv").read_text(encoding="utf-8").splitlines()
        if spec == "compass-transcribe-gpt55":  # drop GPT-5.5 -> GPT-5.5
            lines = [ln for ln in lines if "openai/gpt-5.5,openai/gpt-5.5," not in ln]
        (tmp_path / spec).mkdir()
        (tmp_path / spec / "cells.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"openai/gpt-5\.5 -> openai/gpt-5\.5"):
        figure.points(tmp_path)
