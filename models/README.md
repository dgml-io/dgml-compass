# Model Compass: picking the models for your pipeline

dgml uses one model to transcribe a document and one to label it. Model Compass runs dgml over
9 public docsets (forms, contracts, clinical protocols, leases and more) with different models
in each role, scores the DGML against gold annotations, and reports quality, consistency and
cost, to find the most cost-efficient models for the pipeline, for each need.

## Results

Seven sweeps; F1 is field values against gold, mean of the 9 docsets
([docs/RESULTS.md](docs/RESULTS.md) §6-7):

| Need | Transcriber → labeler | F1 | $/doc |
|---|---|---:|---:|
| Volume | Haiku 5.5 → Haiku 5.5 | 79 | 0.02 |
| Balanced | Haiku 5.5 → Sonnet 5 | 83 | 0.28 |
| Best | Haiku 5.5 → GPT-5.5 | 86 | 1.42 |

- **Spend on the labeler.** Haiku 5.5 transcribes as well as Sonnet 5, Opus 5 and GPT-5.5
  (78.3-78.8) at 1/9 to 1/20 of their cost.
- **Up to 30× cheaper.** On commercial leases, Haiku 5.5 in both roles scores 93.4 F1 at $0.045
  per document, against 94.3 at $1.33 for the best-scoring pipeline.

![Quality against cost per document for each transcriber-labeler pipeline: the labeler buys quality as cost rises, the transcriber does not](figures/quality_cost.svg)

`dgc figure` redraws it from `results/reference/`. This folder is a self-contained uv project:
the package `model_compass` with the command `dgc`, the corpus in `data/`, the sweeps in
`specs/`, their results in `results/reference/`; experiments in
[docs/EXPERIMENTS.md](docs/EXPERIMENTS.md), metrics in [docs/METRICS.md](docs/METRICS.md).
Every command below runs from this folder.

## Install

```bash
git clone https://github.com/dgml-io/dgml-compass.git && cd dgml-compass/models
uv sync                      # Python 3.12; installs model_compass and the `dgc` command
uv run dgc --help
```

`dgc run` calls dgml as a command line from a checkout of
[dgml](https://github.com/dgml-io/dgml), by default a sibling of this repo (`../../dgml` from
here). Everything except `dgc run` works without it. Each run records the commits of dgml, the
corpus and this repo in `manifest.json`. `compare` marks rows not comparable when two runs
differ in any of them, so run both sides from the same checkouts.

Run `dgc` from this checkout: it finds the bundled corpus, prices and specs relative to its
source tree, so an installed wheel on its own would not find them.

## Configure

| What | Where | Committed? |
|---|---|---|
| Provider API keys | `.env` in this folder (template: `.env.example`) | no (gitignored) |
| Paths, parallelism, budget | `local.yaml`, passed with `--profile local.yaml` (template: `conf/profiles/local.example.yaml`) | no (gitignored) |
| One-off overrides | command-line flags, or `DGC_*` variables in the shell or in `.env` | — |

```bash
cp .env.example .env                              # then fill in the keys you need
cp conf/profiles/local.example.yaml local.yaml    # then edit the paths
uv run dgc -v --profile local.yaml plan -e specs/compass-label-haiku55.yaml
```

Precedence, highest first: command-line flags (`--runs-dir`, `--corpus-root`, `--work-dir`
before the command, `--budget-usd` after `plan` or `run`), `DGC_<SETTING>` variables (the
shell beats `.env`), the `--profile` file, defaults. `dgc` reads `./.env`, then `models/.env`,
or only `--env-file`; empty values in `.env` are ignored. Unknown keys in `local.yaml` are an
error.

| Setting (`local.yaml`) | Environment | Default | Purpose |
|---|---|---|---|
| `dgml_repo` | `DGC_DGML_REPO` | `../../dgml` | dgml checkout; `dgc run` calls `uv run dgml` inside it |
| `corpus_root` | `DGC_CORPUS_ROOT` | `data/corpus` | the corpus; it must have no uncommitted changes before a paid run, or pass `--allow-dirty-corpus` |
| `prices_file` | `DGC_PRICES_FILE` | `conf/prices.yaml` | per-model token prices for estimates and the budget cap |
| `runs_dir` | `DGC_RUNS_DIR` | `./runs` | one directory per run (`runs/` is gitignored; point it outside the repo to keep runs across clones) |
| `work_dir` | `DGC_WORK_DIR` | `./.dgc/work` | dgml workspaces (OCR, usage logs), needed to re-score |
| `max_parallel_cells` | `DGC_MAX_PARALLEL_CELLS` | `4` | draws in flight (and `score --workers` default) |
| `max_parallel_calls` | `DGC_MAX_PARALLEL_CALLS` | `8` | documents dgml transcribes at once within a draw (`docset generate --max-parallel-calls`; windows of a document stay serial) |
| `budget_usd` | `DGC_BUDGET_USD` | `25` | hard cap per `dgc run` call (each `--resume` starts again at $0); a spec's `budget_usd` beats it (every shipped spec sets one), `--budget-usd` beats both |

dgml reads the provider keys itself; `dgc` only loads `.env` so dgml inherits it. Keys never
appear in settings, logs or run artifacts. Only the providers a spec uses need a key:
`ANTHROPIC_API_KEY` (`anthropic/claude-*`), `GEMINI_API_KEY` (`gemini/gemini-*`),
`OPENAI_API_KEY` (`openai/gpt-*`). A missing key makes those draws come back with no DGML; fix
it and run `dgc run --resume <run_id> --retry-empty --yes`.

## Quickstart: start small

The commands below are written as bare `dgc`; prefix them with `uv run`, or activate `.venv`.

```bash
dgc corpus check                                  # error findings stop paid runs
dgc plan -e SPEC                                  # cells x draws, priced; writes nothing
dgc run  -e SPEC --dry-run                        # full run dir, $0
dgc run  -e SPEC --yes                            # paid, under the cap
dgc score     -r <run_id>                         # metrics/<cell_id>.jsonl, all families
dgc aggregate -r <run_id>                         # grid/compass_grid.csv + validity.json
dgc report    -r <run_id>                         # report/report.md + CSV tables
dgc compare <baseline_run> <candidate_run> -o compare/
dgc reference match <run_id>                      # a scored run against results/reference/
```

`dgc sweep` chains these over the configured sweeps: without `--yes` it plans them and stops
($0), `--dry-run` writes their run directories ($0), and `--yes` (paid) runs, scores,
aggregates, reports and exports each sweep's tables to `results/latest/`. `dgc reference
report` rebuilds the index of the committed reference results in `results/reference/` without a
key (see [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md)).

Start with one document of one docset for one draw (a few cents with Haiku 5.5:
`specs/tiny.yaml`), then one docset, then a sweep. Plan estimates are a floor: Haiku
5.5 has spent about 2× its plan, GPT-5.5 and Opus 5 labelers 20–25×. Re-runs land within a
few points of earlier results rather than on the same numbers, and compare runs only against
the same corpus.

- **`--dry-run`** works on every command and spends nothing; `run --dry-run` writes the run
  directory with estimates.
- **Interrupted runs:** `run --resume <run_id>` executes only missing or failed draws, and
  `--retry-empty` re-runs draws that produced no DGML.
- **Reusing paid draws:** `dgc adopt -e SPEC --from <old_run>` seeds draw 00 of a new run from
  earlier single-draw runs whose documents match.

Exit codes: 0 ok, 1 error, 2 findings (non-comparable rows, a regression, corpus errors),
3 budget exceeded; on the bundled corpus `aggregate` and `compare` usually exit 2, because
some shapes have too few docsets. Reading the results:
[docs/EXPERIMENTS.md](docs/EXPERIMENTS.md#reading-the-results).

## Layout

```
src/model_compass/   cli, experiments/, engine/ (the dgml CLI adapter), corpus/, metrics/,
                     scoring, aggregate/, report, runs, reference (dgc sweep, dgc reference), figure
data/                the bundled corpus and its shape map (data/README.md)
specs/               the sweeps (docs/EXPERIMENTS.md)
conf/                prices.yaml, the settings profile template
results/reference/   the reference results of the sweeps, one directory per spec
figures/             quality_cost.svg, drawn from them by `dgc figure`
tests/               unit, golden and end-to-end tests, mirroring src/
scripts/             regenerate goldens; re-record dgml CLI fixtures; import an earlier run
docs/                RESULTS, METRICS, EXPERIMENTS, DECISIONS; model-compass-guide.html
pyproject.toml       the package, its dev tools and their settings (pytest, ruff); uv.lock
```

## Develop

```bash
uv run ruff check . && uv run pytest
```

Golden tests pin plans, draw samples, scores, grids and reports. A change that moves a number
must say why in `docs/DECISIONS.md` and regenerate the goldens with
`scripts/make_golden_*.py`.
