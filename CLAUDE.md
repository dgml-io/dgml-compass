# dgml-compass

Two independent uv projects, each with its own `pyproject.toml`; run commands from the
project's folder. The root holds only the README and LICENSE.
`models/` holds the Model Compass package (`model_compass`, CLI `dgc`): transcribe/label sweeps
with draws over dgml, scoring (extraction, reference_free, economics, tree), aggregation,
reports and comparisons. `reasoning/` is a separate benchmark (DGML vs PDF markdown): package
`dgml_reasoning`, CLI `dgr`.

## Rules
- Never simplify scientific definitions: metric formulas, draw sampling, `cell_id` hashing,
  model-in-grid-key, sentinel padding, validity exclusions. A change that moves a number says
  why in `models/docs/DECISIONS.md` and regenerates the goldens.
- dgml runs from the configurable `dgml_repo` (default: a `dgml` checkout beside this repo).
- Never launch a paid run without the user's go-ahead; verify with plans, dry-runs, test
  doubles and recorded CLI fixtures. Paid runs start tiny (one document, one draw).
- The corpus and every fixture hold only public docsets. Never add non-public documents or
  their filenames, ids or values, and no machine-specific paths.
- Don't commit; end each task with a proposed commit message (no attribution lines).
- Every task ends green: `uv run ruff check . && uv run pytest` in each project touched.
- In `reasoning/`, the prompt texts, scoring rules, citation resolution and renderings are the
  benchmark: its tests pin its README's main numbers, and the renderings must match
  `data/renderings.sha256`. A paid run is `dgr run <experiment> --yes`, with only the
  parameters recorded in `configs/experiments.json`.
- Docs budget: `models/README.md` ≤150 lines, `models/docs/` METRICS, EXPERIMENTS, DECISIONS,
  RESULTS. The root README stays a short map of the two projects. Docstrings only where the
  "why" is not obvious.

## Layout (paths under `models/`)
- `src/model_compass/`: `cli.py` (`dgc`), `experiments/` (spec, cells, plan, manifest,
  provenance, pool, run, adopt), `engine/` (dgml_cli adapter, workspace, generate, usage),
  `corpus/`, `metrics/` (families, extraction, reference_free, economics, `tree/`),
  `aggregate/` (grid, render, validity, compare, stats, tables), `scoring.py`, `report.py`,
  `pricing.py`, `runs.py`, `ids.py`, `domain.py`, `records.py`, `config.py`, `errors.py`,
  `reference.py`, `match_reference.py`, `figure.py`
- `data/`: the bundled corpus (`corpus/`) and its shape map (`shapes.yaml`)
- `specs/`: the sweeps (start with `tiny.yaml`); `conf/`: `prices.yaml`, the settings profile
  template; `.env` and `local.yaml` (both gitignored) live in `models/`
- `results/reference/`: the sweeps' reference results; `dgc sweep` plans / dry-runs / runs
  (paid, `--yes`) the configured sweeps and exports them (`reference.py`), `dgc reference
  report|export|match` maintain and check them (`reference.py`, `match_reference.py`);
  `figures/quality_cost.svg` is drawn from them by `dgc figure` (`figure.py`)
- `tests/`: mirrors `src/` (`corpus/`, `metrics/`, `experiments/`, `aggregate/`), shared
  `helpers.py`, golden tests (`golden/`, `*/expected/`), `test_end_to_end.py`
- `scripts/`: `make_golden_plans.py`, `make_golden_aggregate.py`, `record_cli_fixtures.sh`,
  `import_mca_run.py`
- `docs/`: RESULTS, METRICS, EXPERIMENTS, DECISIONS, `model-compass-guide.html`

## Layout (paths under `reasoning/`)
- `src/dgml_reasoning/`: `cli.py` (`dgr`: reproduce, renderings, report, provenance, figure,
  run, answer, navigate), `run.py` (full read), `navigate.py`, `score.py`, `report.py`,
  `provenance.py`, `conditions.py` (the rows), `answermode.py`, `llm.py`, `config.py`,
  `dgml_outline.py` and `make_compact.py` (the DGML renderings), `make_figure.py`
- `data/`: the 30 filings (PDF, DGML), questions, gold programs, `renderings.sha256`
- `configs/experiments.json`: every recorded run; `results/reference/<model>/<condition>/`
  one JSON per answer
- `scripts/`: `build_renderings.sh` (the PDF converters, pinned, under `uv run --with`),
  `check_renderings.py`, `make_markdown_pdf*.py`, `regenerate_dgml.sh`
- `tests/`: pin the README's numbers (accuracy, traceability, tokens)
