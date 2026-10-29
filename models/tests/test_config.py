from pathlib import Path

import pytest

from model_compass.config import MODELS_DIR, load_settings
from model_compass.errors import BudgetExceeded, CompassError, ConfigError, ExitCode


def test_precedence_default_profile_env_override(tmp_path):
    profile = tmp_path / "p.yaml"
    profile.write_text("budget_usd: 50\nmax_parallel_cells: 2\nruns_dir: /tmp/p\n")
    settings = load_settings(
        profile=profile,
        environ={"DGC_MAX_PARALLEL_CELLS": "3", "DGC_RUNS_DIR": "/tmp/e"},
        runs_dir="/tmp/o",
        budget_usd=None,
    )
    assert settings.budget_usd == 50  # profile beats default; None override falls through
    assert settings.max_parallel_cells == 3  # env beats profile
    assert settings.runs_dir == Path("/tmp/o").resolve()  # override beats env (macOS: /private/tmp)


def test_defaults_point_at_the_bundled_corpus_and_a_sibling_dgml():
    settings = load_settings(environ={})
    assert settings.dgml_repo.name == "dgml"
    assert settings.corpus_root == MODELS_DIR / "data" / "corpus"


def test_bad_input_is_a_config_error_naming_the_field(tmp_path):
    with pytest.raises(ConfigError, match="max_parallel_cells"):
        load_settings(environ={"DGC_MAX_PARALLEL_CELLS": "0"})
    profile = tmp_path / "p.yaml"
    profile.write_text("storage_uri: gs://x\n")
    with pytest.raises(ConfigError, match="unknown settings: storage_uri"):
        load_settings(profile=profile, environ={})
    with pytest.raises(ConfigError, match="profile not found"):
        load_settings(profile=tmp_path / "missing.yaml", environ={})


def test_paths_are_checked_only_when_required(tmp_path):
    settings = load_settings(environ={}, dgml_repo=tmp_path / "nope")
    with pytest.raises(ConfigError, match="DGC_DGML_REPO"):
        settings.require("dgml_repo")
    assert load_settings(environ={}, dgml_repo=tmp_path).require("dgml_repo") == tmp_path


def test_errors_carry_codes_and_exit_codes():
    err = ConfigError("bad", code="x", field="f")
    assert isinstance(err, CompassError)
    assert err.as_dict() == {"error": {"code": "x", "message": "bad", "context": {"field": "f"}}}
    assert BudgetExceeded("over").exit_code is ExitCode.BUDGET_EXCEEDED


def test_dotenv_fills_only_what_is_unset_and_skips_placeholders(tmp_path):
    from model_compass.config import load_dotenv

    path = tmp_path / ".env"
    path.write_text(
        "# keys\n"
        "ANTHROPIC_API_KEY=sk-test   # a comment\n"
        "export GEMINI_API_KEY='g-key'\n"
        "OPENAI_API_KEY=            # placeholder\n"
        'DGC_RUNS_DIR="/tmp/from env file"\n'
        "DGC_BUDGET_USD=7\n"
        "not a variable\n"
    )
    env = {"DGC_BUDGET_USD": "9"}
    loaded = load_dotenv(path, env)
    assert env["ANTHROPIC_API_KEY"] == "sk-test"
    assert env["GEMINI_API_KEY"] == "g-key"
    assert "OPENAI_API_KEY" not in env
    assert env["DGC_RUNS_DIR"] == "/tmp/from env file"
    assert env["DGC_BUDGET_USD"] == "9"  # the real environment wins
    assert sorted(loaded) == ["ANTHROPIC_API_KEY", "DGC_RUNS_DIR", "GEMINI_API_KEY"]
    assert load_settings(environ=env).budget_usd == 9
    assert load_dotenv(tmp_path / "missing", env) == []


def test_the_committed_templates_load(tmp_path):
    from model_compass.config import load_dotenv

    env: dict[str, str] = {}
    assert load_dotenv(MODELS_DIR / ".env.example", env) == []  # placeholders only
    profile = MODELS_DIR / "conf" / "profiles" / "local.example.yaml"
    assert load_settings(profile=profile, environ={}).budget_usd == 25


def test_a_leftover_root_env_is_pointed_out(tmp_path, monkeypatch, caplog):
    from model_compass import cli

    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=placeholder\n", encoding="utf-8")
    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    monkeypatch.chdir(MODELS_DIR)
    assert cli.main(["reference", "report", "--dry-run"]) == 0
    assert "is not read any more: move it to" in caplog.text
