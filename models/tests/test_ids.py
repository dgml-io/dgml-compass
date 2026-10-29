import subprocess
import sys
from datetime import UTC, datetime
from enum import Enum

import pytest

from model_compass.ids import canonical_json, cell_id, corpus_hash, digest, normalize, run_id

# Cells of recorded runs; their ids must not change.
REAL_CELLS = [
    (
        "2ec47c681483",  # runs/20260925-200000-transcr3
        {
            "org": "z4ervk9ic0oo",
            "docset": "hcqfkilviuq3",
            "settings": {
                "generation.label_model": "anthropic/claude-haiku-4-5",
                "generation.model": "anthropic/claude-sonnet-5",
                "schema_tier": "none",
                "text_mode": "digital",
                "window_size": 10,
            },
            "seed": 20260917,
        },
    ),
    (
        "baf9b31bb56c",  # runs/20261008-140547-4fe5464b
        {
            "org": "z4ervk9ic0oo",
            "docset": "hcqfkilviuq3",
            "settings": {
                "generation.label_model": "anthropic/claude-haiku-5-5",
                "generation.model": "anthropic/claude-haiku-5-5",
                "schema_tier": "none",
                "text_mode": "digital",
                "window_size": 10,
            },
            "seed": 20260925,
        },
    ),
]


@pytest.mark.parametrize(("expected", "identity"), REAL_CELLS)
def test_cell_ids_match_the_real_runs(expected, identity):
    assert cell_id(identity) == expected


def test_cell_id_ignores_key_order_and_moves_with_any_input():
    identity = REAL_CELLS[0][1]
    reordered = dict(reversed(list(identity.items())))
    assert cell_id(reordered) == cell_id(identity)
    assert cell_id({**identity, "seed": 1}) != cell_id(identity)


def test_cell_id_is_stable_across_processes():
    code = (
        "from model_compass.ids import cell_id;"
        "print(cell_id({'org':'o','docset':'d','settings':{'a':1},'seed':3}))"
    )
    out = {
        subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        ).stdout
        for _ in range(2)
    }
    assert len(out) == 1


def test_normalisation_rules():
    class Colour(Enum):
        RED = "red"

    assert normalize(-0.0) == 0.0
    assert normalize(Colour.RED) == "red"
    assert canonical_json({"b": 1, "a": [1, 2]}) == b'{"a":[1,2],"b":1}'
    with pytest.raises(ValueError):
        normalize(float("nan"))
    with pytest.raises(TypeError):
        normalize(object())
    with pytest.raises(ValueError):
        cell_id({})


def test_hash_spaces_are_separated():
    assert digest({"x": 1}, prefix=b"a") != digest({"x": 1}, prefix=b"b")


def test_run_id_format():
    rid = run_id({"name": "x"}, {}, now=datetime(2026, 10, 14, 12, 0, 1, tzinfo=UTC))
    assert rid.startswith("20261014-120001-") and len(rid) == 24


def test_corpus_hash_is_order_independent_and_content_sensitive(tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("1")
    b.write_text("2")
    first = corpus_hash([a, b], root=tmp_path)
    assert first == corpus_hash([b, a], root=tmp_path)
    b.write_text("3")
    assert corpus_hash([a, b], root=tmp_path) != first
    with pytest.raises(ValueError):
        corpus_hash([], root=tmp_path)
