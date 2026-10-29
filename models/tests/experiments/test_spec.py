"""Spec validation and cell expansion."""

from __future__ import annotations

import pytest
import yaml

from model_compass.errors import ConfigError
from model_compass.experiments.cells import Cell, expand_cells, expand_draws
from model_compass.experiments.spec import dump_spec, load_spec

from .conftest import make_spec, mini_corpus


def _write(tmp_path, payload) -> object:
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(payload) if not isinstance(payload, str) else payload)
    return path


def _payload(**overrides):
    payload = {
        "name": "spec-test",
        "corpus": {"docsets": ["z4ervk9ic0oo/8frgx7rlbew3"]},
        "axes": {"generation.model": ["a/x", "a/y"]},
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"axes": {"generation.labelmodel": ["a/x"]}}, "axes"),
        ({"fixed": {"generation.thinking": "always"}}, "generation.thinking"),
        ({"axes": {"generation.model": []}}, "has no values"),
        ({"axes": {"generation.model": ["a/x", "a/x"]}}, "repeats a value"),
        ({"fixed": {"schema_tier": "gold"}}, "expected one of"),
        ({"fixed": {"generation.model": "a/x"}}, "both `axes` and `fixed`"),
        ({"axes": {}}, "at least one"),
        ({"name": "Bad Name"}, "name"),
        ({"surprise": 1}, "surprise"),
        ({"metrics": ["bogus"]}, "metrics"),
        ({"corpus": {"docsets": [], "sampling": "fixed"}}, "select docsets"),
        ({"corpus": {"docsets": ["a/b"], "sampling": "random"}}, "seed"),
    ],
)
def test_bad_specs_are_refused_by_field(tmp_path, overrides, fragment):
    with pytest.raises(ConfigError, match=fragment.replace("(", r"\(")) as caught:
        load_spec(_write(tmp_path, _payload(**overrides)))
    assert caught.value.code == "spec_invalid"


def test_missing_and_malformed_files(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_spec(tmp_path / "nope.yaml")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_spec(_write(tmp_path, "name: [unclosed"))
    with pytest.raises(ConfigError, match="mapping"):
        load_spec(_write(tmp_path, "- a\n- b\n"))


def test_a_source_resolved_spec_loads_and_round_trips(tmp_path):
    source = _payload(
        corpus={
            "orgs": ["z4ervk9ic0oo"],
            "docsets": {
                "include": ["z4ervk9ic0oo/8frgx7rlbew3"],
                "exclude": [],
                "all_with_refs": False,
            },
            "max_files_per_docset": 6,
            "shapes": None,
            "suffixes": [".pdf", ".docx"],
            "sampling": "fixed",
            "require_gold": False,
        },
        schema_version=1,
        description="",
        fixed={"generation.thinking": "adaptive", "window_size": 10},
        draws=3,
        metrics=["extraction", "reference_free", "economics", "tree"],
        budget_usd=900.0,
        seed=20260917,
    )
    spec = load_spec(_write(tmp_path, source))
    assert yaml.safe_load(dump_spec(spec)) == source  # a real run's spec.resolved.yaml
    assert load_spec(_write(tmp_path, dump_spec(spec))) == spec


def test_orgs_are_derived_and_metrics_default_to_all_four(tmp_path):
    spec = load_spec(_write(tmp_path, _payload()))
    assert spec.corpus.org_ids == ("z4ervk9ic0oo",)
    assert [m.value for m in spec.metrics] == ["extraction", "reference_free", "economics", "tree"]


def test_cell_identity_excludes_draws_shape_and_settings_order():
    one = Cell.create(org="o", docset="d", settings={"a": 1, "b": 2}, draws=1, shape="form")
    other = Cell.create(org="o", docset="d", settings={"b": 2, "a": 1}, draws=5, seed=None)
    assert one.cell_id == other.cell_id
    assert (
        Cell.create(org="o", docset="d", settings={"a": 1, "b": 2}, seed=1).cell_id != one.cell_id
    )


def test_expansion_order_fixed_values_and_draw_seeds():
    spec = make_spec(
        axes={"generation.model": ["a/x", "a/y"]}, fixed={"window_size": 10}, draws=2, seed=7
    )
    docsets = mini_corpus(spec).docsets
    cells = expand_cells(spec, docsets)
    assert [(c.settings_dict["generation.model"], c.docset) for c in cells] == [
        (model, d.docset_id) for model in ("a/x", "a/y") for d in docsets
    ]
    assert all(c.settings_dict["window_size"] == 10 for c in cells)
    draws = expand_draws(cells[0])
    assert [(d.draw_id[-3:], d.seed) for d in draws] == [("d00", 7), ("d01", 8)]
    with pytest.raises(ConfigError, match="more than once"):
        expand_cells(spec, [*docsets, docsets[0]])
    with pytest.raises(ConfigError, match="selects no docsets"):
        expand_cells(spec, [])
