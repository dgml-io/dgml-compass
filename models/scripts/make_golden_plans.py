"""Regenerate tests/golden/plans/<spec>.json from this repo's planner.

For every spec under ``specs/``, plan it against the bundled corpus (``rehearsal.yaml``: the
mini corpus) with the shipped prices, and record each cell (id, org, docset, shape, settings,
draws, seed), its priced one-draw estimate, the per-draw document samples and the prices used.
Run it after a deliberate change to the planner, the corpus or the prices, and say why in
docs/DECISIONS.md:

    uv run python scripts/make_golden_plans.py
"""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from model_compass.config import load_settings
from model_compass.corpus.loader import load_corpus
from model_compass.corpus.sampling import draw_corpus
from model_compass.corpus.shapes import load_shape_map
from model_compass.experiments.plan import plan
from model_compass.experiments.spec import load_spec
from model_compass.pricing import load_prices

HERE = Path(__file__).resolve().parents[1]
SPECS = HERE / "specs"
MINI = HERE / "tests" / "fixtures" / "mini_corpus"
OUT = HERE / "tests" / "golden" / "plans"
NOW = datetime(2026, 10, 14, tzinfo=UTC)


def golden(path: Path) -> dict:
    spec = load_spec(path)
    mini = path.name == "rehearsal.yaml"
    defaults = load_settings(environ={})
    root = MINI if mini else defaults.corpus_root
    shapes = load_shape_map(MINI / "shapes.yaml") if mini else None
    corpus, _ = load_corpus(root, spec.corpus, shapes=shapes)
    prices = load_prices(defaults.prices_file)
    with tempfile.TemporaryDirectory() as scratch:
        settings = load_settings(
            environ={}, corpus_root=root, runs_dir=Path(scratch), work_dir=Path(scratch)
        )
        built = plan(spec, settings, corpus, prices=prices, now=NOW)
    used = sorted({v for item in built.cells for k, v in item.cell.settings if k.endswith("model")})
    cells = []
    samples: dict[str, list[list[str]]] = {}
    for item in built.cells:
        cell = item.cell
        draws = []
        for index in range(cell.draws):
            sampled = draw_corpus(corpus, cell, spec, index)
            draws.append([f"{d.ref}/{doc.name}" for d in sampled.docsets for doc in d.documents])
        # a draw's sample depends on the docset, the selector and the seed, never the settings
        assert samples.setdefault(cell.ref, draws) == draws, cell.cell_id
        cells.append(
            {
                "cell_id": cell.cell_id,
                "org": cell.org,
                "docset": cell.docset,
                "shape": cell.shape,
                "settings": [list(pair) for pair in cell.settings],
                "draws": cell.draws,
                "seed": cell.seed,
                "n_documents": item.n_documents,
                "estimate_usd": item.estimate.usd,
                "by_slot": item.estimate.by_slot,
                "unpriced_models": list(item.estimate.unpriced_models),
            }
        )
    return {
        "spec": path.relative_to(SPECS).as_posix(),
        "corpus": "mini" if mini else "bundled",
        "prices": {m: prices[m].model_dump(mode="json") for m in used if m in prices},
        "estimated_usd": built.estimated_usd,
        "dropped": [{"ref": d.ref, "reason": d.reason.value} for d in built.dropped],
        "cells": cells,
        "draw_documents": samples,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*.json"):
        stale.unlink()
    for path in sorted(SPECS.rglob("*.yaml")):
        data = golden(path)
        name = data["spec"].replace("/", "__").removesuffix(".yaml")
        (OUT / f"{name}.json").write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
        print(f"{name}: {len(data['cells'])} cells, ${data['estimated_usd']:.2f}")


if __name__ == "__main__":
    main()
