"""The dgml adapter, config.toml, workspaces, generation, and the runner's rails."""

from __future__ import annotations

import json
import subprocess

import pytest

from model_compass.corpus.sampling import draw_corpus
from model_compass.engine.dgml_cli import PERMANENT_CODES, DgmlCli, classify, render_config_toml
from model_compass.engine.generate import _as_int, generate
from model_compass.engine.workspace import WorkspacePlan, build_workspace, plan_only
from model_compass.errors import BudgetExceeded, ConfigError, EngineError
from model_compass.experiments.cells import Cell
from model_compass.experiments.pool import BudgetGuard, ProviderLimit, RateLimiter, provider_of
from model_compass.experiments.run import draw_status

from .conftest import PRICES, make_spec, mini_corpus
from .doubles import FakeDgml, completed, load, raw, scripted_runner

SPEC = make_spec(corpus={"docsets": {"all_with_refs": True}, "max_files_per_docset": 2})
CELL = Cell.create(
    org="redorg000001",
    docset="dsred0000001",
    settings={
        "generation.model": "a/cheap",
        "generation.label_model": "b/label",
        "text_mode": "ocr",
        "window_size": 10,
    },
    draws=3,
)


def _cli(tmp_path, script, **kwargs):
    runner = scripted_runner(script)
    return DgmlCli(workspace=tmp_path / "ws", runner=runner, retry_initial_s=0.0, **kwargs), runner


# -- the adapter ------------------------------------------------------------------------------


def test_argv_is_uv_run_in_a_repo_and_generate_always_passes_debug(tmp_path):
    cli, runner = _cli(tmp_path, [completed(raw("docset_generate.json"))], repo_root=tmp_path)
    payload = cli.docset_generate("ds1", model="a/x", window_size=10)
    assert payload["summary"]["total"] == 3
    (argv,) = runner.calls
    assert argv[:3] == ["uv", "run", "dgml"]
    assert argv[3:7] == ["--workspace", str(tmp_path / "ws"), "--format", "json"]
    assert argv[7:] == [
        "docset",
        "generate",
        "ds1",
        "--debug",
        "--model",
        "a/x",
        "--window-size",
        "10",
    ]
    assert DgmlCli(workspace=tmp_path).base_argv == ("dgml",)


def test_max_parallel_calls_is_passed_to_docset_generate(tmp_path):
    cli, runner = _cli(tmp_path, [completed(raw("docset_generate.json"))])
    cli.docset_generate("ds1", max_parallel_calls=3)
    (argv,) = runner.calls
    assert argv[-5:] == ["generate", "ds1", "--debug", "--max-parallel-calls", "3"]


def test_a_failed_version_reports_the_argv_it_ran(tmp_path):
    cli, _ = _cli(tmp_path, [completed(stderr="boom", returncode=2)], repo_root=tmp_path)
    with pytest.raises(EngineError) as caught:
        cli.version()
    assert caught.value.context["argv"] == ["uv", "run", "dgml", "--version"]


def test_output_is_logged_whether_or_not_the_call_fails(tmp_path):
    error = completed(stderr=raw("error_schema_invalid.json"), returncode=1)
    cli, _ = _cli(
        tmp_path, [completed(raw("status.json"), "warn"), error], log_dir=tmp_path / "logs"
    )
    cli.docset_add_file("f1", docset_id="d1")
    with pytest.raises(EngineError) as caught:
        cli.file_add(tmp_path / "a.pdf")
    assert caught.value.code == "schema_invalid" and "not valid RNC" in caught.value.message
    assert sorted(p.name for p in (tmp_path / "logs").iterdir()) == [
        "0001-docset-add-file.stderr.log",
        "0001-docset-add-file.stdout.log",
        "0002-file-add.stderr.log",
    ]


def test_a_rate_limit_is_retried_and_a_schema_error_is_not(tmp_path):
    limited = completed(stderr=raw("error_rate_limited.json"), returncode=1)
    cli, runner = _cli(tmp_path, [limited, completed(raw("file_add.json"))])
    assert cli.file_add(tmp_path / "a.pdf")["file_id"] == "k7q3xb91pmrf"
    assert len(runner.calls) == 2
    schema = completed(stderr=raw("error_schema_invalid.json"), returncode=1)
    cli, runner = _cli(tmp_path, [schema, schema])
    with pytest.raises(EngineError):
        cli.file_add(tmp_path / "a.pdf")
    assert len(runner.calls) == 1
    cli, runner = _cli(tmp_path, [limited] * 3)
    with pytest.raises(EngineError) as caught:
        cli.file_add(tmp_path / "a.pdf")
    assert caught.value.code == "rate_limited" and len(runner.calls) == 3


def test_timeouts_missing_binaries_and_bad_payloads(tmp_path):
    cli, _ = _cli(tmp_path, [subprocess.TimeoutExpired("dgml", 1)], retries=0)
    with pytest.raises(EngineError, match="exceeded") as caught:
        cli.docset_create(name="x")
    assert caught.value.code == "timeout"
    cli, _ = _cli(tmp_path, [FileNotFoundError("dgml")])
    with pytest.raises(ConfigError, match="install dgml"):
        cli.docset_create(name="x")
    cli, _ = _cli(tmp_path, [completed("not json")])
    with pytest.raises(EngineError, match="not JSON"):
        cli.docset_create(name="x")
    cli, _ = _cli(tmp_path, [completed(raw("version.txt"))])
    assert cli.version() == raw("version.txt").strip()


def test_classify():
    assert classify("INTERNAL_ERROR", "RateLimitError: 429") == "rate_limited"
    assert classify("AUTH_ERROR", "429 from upstream") == "auth_error"
    assert classify("INTERNAL_ERROR", "Bad Gateway") == "server_error"
    assert classify(None, "something odd") == "dgml_error"
    assert {"AUTH_ERROR", "SCHEMA_INVALID", "MODEL_NOT_SUPPORTED"} <= PERMANENT_CODES


def test_config_toml_renders_the_slots_a_cell_sets_and_thinking():
    text = render_config_toml(
        {
            "generation.model": "a/x",
            "grounded.values_model": 'evil"\\id',
            "generation.thinking": "adaptive",
            "window_size": 10,
        },
        header="cell abc",
    )
    assert text.startswith("# cell abc\n")
    assert '[generation]\nmodel = "a/x"\nthinking = "adaptive"' in text
    assert 'values_model = "evil\\"\\\\id"' in text
    assert "[classification]" not in text and "window_size" not in text


# -- workspaces and generation ----------------------------------------------------------------


def test_a_workspace_records_both_ids_and_rebuilding_is_a_no_op(tmp_path):
    corpus = draw_corpus(mini_corpus(SPEC), CELL, SPEC, 0)
    double = FakeDgml(tmp_path / "ws")
    built = build_workspace(CELL, corpus, double, artifact_dir=tmp_path / "run")
    assert all(e.corpus_file_id and e.dgml_file_id for e in built.entries)
    assert {c["text_mode"] for name, c in double.calls if name == "file_add"} == {"ocr"}
    stored = (tmp_path / "run" / "workspace" / "mca-workspace.json").read_text()
    assert stored == built.to_json() and '"captured' not in stored
    again = FakeDgml(tmp_path / "ws")
    assert build_workspace(CELL, corpus, again) == built and again.calls == []
    other = Cell.create(org=CELL.org, docset=CELL.docset, settings={"generation.model": "z/z"})
    with pytest.raises(EngineError) as caught:
        build_workspace(other, corpus, again)
    assert caught.value.code == "workspace_mismatch"
    assert WorkspacePlan.from_json(stored) == built


def test_a_payload_without_an_id_is_an_error_and_the_nested_id_is_read(tmp_path):
    corpus = draw_corpus(mini_corpus(SPEC), CELL, SPEC, 0)

    class Nested(FakeDgml):
        def file_add(self, path, **kwargs):
            flat = super().file_add(path, **kwargs)
            return {"file": {"id": flat["file_id"]}}

    assert build_workspace(CELL, corpus, Nested(tmp_path / "a")).entries[0].dgml_file_id

    class Broken(FakeDgml):
        def docset_create(self, **kwargs):
            return {"created": True}

    with pytest.raises(EngineError, match="no docset_id"):
        build_workspace(CELL, corpus, Broken(tmp_path / "b"))


def test_generation_captures_outcomes_soft_errors_and_absent_documents(tmp_path):
    corpus = draw_corpus(mini_corpus(SPEC), CELL, SPEC, 0)
    double = FakeDgml(tmp_path / "ws")
    built = build_workspace(CELL, corpus, double)
    recorded = load("docset_generate.json")
    recorded["results"][0]["file_id"] = built.entries[0].dgml_file_id
    seen = {}
    double.docset_generate = lambda docset_id, **options: seen.update(options) or recorded
    result = generate(CELL, built, double, draw_index=1, max_parallel_calls=5)
    assert seen["max_parallel_calls"] == 5
    assert (tmp_path / "ws" / "config.toml").is_file() and result.draw_index == 1
    statuses = sorted(d.status for d in result.documents)
    assert statuses == ["absent", "converted", "converted", "skipped"]
    assert any(d.soft_errors == ("label_error", "grounding_error") for d in result.documents)
    assert any("soft error" in w for w in result.warnings)
    assert any("no usage.jsonl" in w for w in result.warnings)
    assert draw_status(result) == "succeeded"


def test_a_failing_docset_does_not_raise_and_a_dry_run_calls_nothing(tmp_path):
    corpus = draw_corpus(mini_corpus(SPEC), CELL, SPEC, 0)
    double = FakeDgml(tmp_path / "ws")
    built = build_workspace(CELL, corpus, double)

    def refuse(docset_id, **options):
        raise EngineError("dgml docset-generate: boom", code="auth_error")

    double.docset_generate = refuse
    result = generate(CELL, built, double)
    assert result.docsets[0].error_code == "auth_error" and result.documents == ()
    planned = plan_only(CELL, corpus, tmp_path / "dry")
    dry = generate(CELL, planned, None, dry_run=True, prices=PRICES)
    assert dry.dry_run and draw_status(dry) == "dry_run" and not (tmp_path / "dry").exists()
    assert dry.cost_usd == dry.cost_estimate.usd and dry.cost_estimate.unpriced_models == (
        "b/label",
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5, 5),
        (-3, -3),
        (10.0, 10),
        ("7", 7),
        (" -2 ", -2),
        (10.5, None),
        ("5-", None),
        ("ten", None),
        ("10.0", None),
        (True, None),
        (None, None),
        ([1], None),
    ],
)
def test_integer_settings_parse_only_integral_values(value, expected):
    assert _as_int(value) == expected


# -- rails ----------------------------------------------------------------------------------


def test_the_budget_guard_reserves_and_settles():
    guard = BudgetGuard(10.0)
    guard.reserve(6.0)
    with pytest.raises(BudgetExceeded) as caught:
        guard.reserve(5.0)
    assert caught.value.context["projected_usd"] == 11.0
    guard.settle(6.0, 1.0)
    guard.reserve(5.0)
    assert (guard.spent_usd, guard.committed_usd) == (1.0, 5.0)
    with pytest.raises(ConfigError):
        BudgetGuard(0)


def test_the_rate_limiter_buckets_per_provider():
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    limiter = RateLimiter({"a": ProviderLimit(60.0, 2)}, clock=lambda: now[0], sleep=sleep)
    assert [limiter.acquire("a") for _ in range(2)] == [0.0, 0.0]
    assert limiter.acquire("a") == pytest.approx(1.0)
    assert limiter.acquire("unknown") == 0.0
    assert (
        provider_of("anthropic/claude-haiku-4-5") == "anthropic" and provider_of(None) == "unknown"
    )


def test_a_draws_corpus_is_its_cells_docset_only():
    corpus = mini_corpus(SPEC)
    assert [d.ref for d in draw_corpus(corpus, CELL, SPEC, 0).docsets] == [CELL.ref]
    stranger = Cell.create(
        org="redorg000001", docset="elsewhere", settings={"generation.model": "a/x"}
    )
    with pytest.raises(EngineError) as caught:
        draw_corpus(corpus, stranger, SPEC, 0)
    assert caught.value.code == "cell_docset_absent"
    assert json.loads(json.dumps(CELL.model_dump(mode="json")))["draws"] == 3
