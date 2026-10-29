# Experiments

Each sweep is a spec under `specs/`. The commands below run from `models/`. Every
spec prices itself first, with `dgc plan` or `dgc run --dry-run`. Paid runs need `--yes` and
stop at the budget cap.

## Common shape

| Field | Value in the sweeps | Why |
|---|---|---|
| docsets | the 9 bundled docsets (`data/corpus`) | every shape the corpus covers |
| `max_files_per_docset` | 6 | documents per draw |
| `sampling` | `fixed` (gold first, then by name; same 6 every draw) | draws differ only by generation |
| `draws` | 3 | averaged within each docset; the ± band is between docsets, not draws (METRICS §5) |
| `seed` | 20260917 (`3x6`: 20260925) | part of every cell id: never change it on a running sweep |
| `fixed` | `schema_tier: none`, `window_size: 10`, `text_mode: digital` | baseline settings |
| `require_gold` | `false` | |
| `metrics` | `extraction, reference_free, economics, tree` | |

## Sweeps (`specs/`)

| Spec | Varies | Held | Question | Plan ($) | Cap ($) |
|---|---|---|---|---:|---:|
| `compass-transcribe-haiku55.yaml` | transcriber: Haiku 5.5, Sonnet 5, Opus 5, Gemini 3.6 Flash, GPT-5.5 | labeler Haiku 5.5 | which transcriber? | 258.61 | 800 |
| `compass-label-haiku55.yaml` | labeler: Haiku 5.5, Opus 5, Sonnet 5, Gemini 3.6 Flash, Gemini 3.1 Flash Lite, GPT-5.5 | transcriber Haiku 5.5 | which labeler? | 24.18 | 75 |
| `compass-label-gemini.yaml` | labeler: Haiku 4.5, Opus 5, Sonnet 5, Gemini 3.6 Flash, Gemini 3.1 Flash Lite, GPT-5.5 | transcriber Gemini 3.6 Flash | which labeler under a Gemini transcriber? Gemini in both roles | 98.95 | 150 |
| `compass-label-gemini-haiku55.yaml` | labeler: Haiku 5.5 | transcriber Gemini 3.6 Flash | does the labeler result depend on the transcriber? | 14.31 | 50 |
| `compass-transcribe-gpt55.yaml` | transcriber: Haiku 4.5, Sonnet 5, Opus 5, Gemini 3.6 Flash, GPT-5.5 | labeler GPT-5.5 | which transcriber under a GPT-5.5 labeler? GPT-5.5 in both roles | 300.85 | 1200 |
| `compass-transcribe-gpt55-haiku55.yaml` | transcriber: Haiku 5.5 | labeler GPT-5.5 | does the transcriber result depend on the labeler? | 7.03 | 25 |
| `compass-corpus-3x6-haiku55.yaml` | — (Haiku 5.5 both slots) | `sampling: random`, `.pdf` only, seed 20260925 | spread including document variation | 1.99 | 10 |
| `compass-baseline-haiku55.yaml` | — (Haiku 5.5 both slots, thinking off) | fixed sampling | same-model baseline | 1.99 | 10 |
| `compass-baseline-haiku55-think.yaml` | — (Haiku 5.5 both slots, `generation.thinking: adaptive`) | as baseline | does thinking help Haiku 5.5? | 1.99 | 10 |
| `rehearsal.yaml` | 2 models (Haiku 5.5, Sonnet 5), the mini corpus, 1 draw | reference_free only | pipeline smoke test | 0.98 (mini corpus) | 5 |
| `tiny.yaml` | — (Haiku 5.5 both slots, 1 document of 1 docset, 1 draw) | fixed sampling | first paid run before a sweep | 0.02 | 2 |

`rehearsal.yaml` is meant for the mini corpus:

```bash
DGC_CORPUS_ROOT=tests/fixtures/mini_corpus \
  uv run dgc run -e specs/rehearsal.yaml --dry-run
```

Without `DGC_CORPUS_ROOT` it runs over all 9 bundled docsets and plans $4.42 against its $5 cap.
It sets no label model, so its plan prices the transcriber only.

The two `compass-transcribe-*` sweeps hit known defect 7 (docs/DECISIONS.md): grid rows key
the model by label model first, so `dgc aggregate` pools every transcriber into one row named
after the labeler, and `dgc compare` matches that row with no warning. Until it is fixed,
compare transcribers per cell (`metrics/<cell_id>.jsonl`) and do not `compare` these runs.

Only `prose_narrative` can be ranked on the bundled corpus: a row needs 3 docsets to be
comparable, and only prose has that many (5; `form` has 2, the other shapes 1). Lowering
`--min-docsets` is for exploring, not for rankings.

"Plan" is `dgc plan` with `conf/prices.yaml`. It is a floor, and each cap is about 3×
its plan. That suits Haiku 5.5 (about 2× observed) but not expensive models: an earlier run of
the label sweep spent about 9× its plan ($345 against $40), with GPT-5.5 and Opus 5 at 20–25×,
so a $75 cap stops it early. Check the real rate on one docset first, then set `--budget-usd`.
The cap is per `dgc run` call, and each `--resume` starts again at $0.

## Start small

Before a sweep, run one document of one docset for one draw (a few cents with Haiku 5.5),
then one full docset, and only then the sweep. `specs/tiny.yaml` is that first run:

```bash
uv run dgc plan -e specs/tiny.yaml
uv run dgc run  -e specs/tiny.yaml --yes
```

For the one-docset step, copy a sweep spec and narrow `corpus.docsets.include` to one docset.

Judge models on full docsets, not on one document: dgml names tags across a docset's
documents at once, so one-document runs score much lower on extraction. Cell ids do not depend
on the number of documents or draws, so a small run with a sweep's settings shares its cell
ids. `tiny.yaml` leaves `schema_tier`, `window_size` and `text_mode` at dgml's defaults, so its
cells are its own. Do not `adopt` or `compare` across runs of different sizes.

## Commands

```bash
S=specs

# price, then dry-run (writes a run dir with estimates, spends $0)
dgc plan -e $S/compass-transcribe-haiku55.yaml -e $S/compass-label-haiku55.yaml
dgc run  -e $S/compass-label-haiku55.yaml --dry-run

# reuse earlier single-draw runs as draw 00, then run the rest (paid)
dgc adopt -e $S/compass-label-haiku55.yaml --from <earlier_run_id> --dry-run
dgc adopt -e $S/compass-label-haiku55.yaml --from <earlier_run_id>
dgc run   -e $S/compass-label-haiku55.yaml --resume <run_id> --yes

# after an interruption, or draws that produced no DGML (e.g. a provider out of credit)
dgc run -e $S/compass-label-haiku55.yaml --resume <run_id> --retry-empty --yes

# measure
dgc score     -r <run_id>                       # --workers N, --resume, --metric F
dgc aggregate -r <run_id> --pivot shape
dgc report    -r <run_id>
dgc compare <baseline_run> <candidate_run> -o compare/
```

The corpus must have no uncommitted changes before a paid run; `--allow-dirty-corpus`
overrides that check, and the run's provenance records it.

## Reading the results

`dgc report` writes `report/report.md`. Worked examples: the goldens in
`tests/aggregate/expected/*/report.md`, and the runs in
`tests/aggregate/fixtures/*.tar.gz` (extract one and pass `--runs-dir`).

- **What ran.** Measured spend is the real spend, except after a `--resume`, which drops
  earlier draws (defect 6).
- **Best model per shape.** Comparable rows only. *Contested* means the runner-up's band
  overlaps the winner's. It is a coarse check: the bands mostly reflect how hard each docset
  is, so close models are nearly always contested. There is no paired test between two models
  of one run.
- **The grid.** *Quality* is `individual_overlap_f1` (0–100) ± 2·SE of the docset means.
  `n=1` means one docset and no band: unmeasured, not precise. *Tag-blind* is
  `value_only_overlap_recall`: values found, whatever their tag. *Gap* is tag-blind minus
  quality; a large gap means values found under other tag names. Columns: METRICS §5.
- **Comparability gates.** Why a row is not comparable. Such a row is shown, never ranked.
- **Cost.** Attributed cost counts each document 3 times (defect 8): use it for shares, not
  totals. `cost_partial` rows do not compare with unflagged rows.

`dgc compare <baseline> <candidate> -o DIR` writes a `.md` and a `.csv`. It pairs the same row
across two runs over their shared docsets. *Delta* is candidate − baseline with a 95% bootstrap
CI: `improved` (CI above 0), `regressed` (below 0), `no_change` (spans 0), `not_comparable` (a
gate failed).

## Reference results

`results/reference/<spec>/` holds, for each sweep that has been run, the tables a run
leaves behind: `cells.csv` (one row per cell: shape, docset, transcriber, labeler, thinking,
quality as the mean over draws, tokens, cost, seconds), `compass_grid.csv` and `validity.json`
from `dgc aggregate`, the `dgc report` CSV tables, and `summary.json` (run id, outcome, totals,
corpus hash, dgml version and commit). `results/reference/README.md` is the summary over them;
`dgc reference report` rebuilds it from those files alone.

| Spec | Reference run | Cells | Note |
|---|---|---:|---|
| `compass-transcribe-haiku55.yaml` | `20261008-175618-25ef2d78` | 45 | |
| `compass-label-haiku55.yaml` | `20261014-022456-37998681` | 54 | |
| `compass-corpus-3x6-haiku55.yaml` | `20261008-140547-4fe5464b` | 9 | |
| `compass-baseline-haiku55.yaml` | `20261008-154627-56e22032` | 9 | |
| `compass-baseline-haiku55-think.yaml` | `20261013-203701-d87d278e` | 9 | |
| `compass-label-gemini.yaml` | `20260925-200002-labelgm3` | 54 | September run, earlier dgml build; Haiku labeler is Haiku 4.5 |
| `compass-label-gemini-haiku55.yaml` | — | | not yet run with Haiku 5.5 |
| `compass-transcribe-gpt55.yaml` | `20260930-200000-trgpt55` | 45 | earlier dgml build; Haiku transcriber is Haiku 4.5; Opus 5 and Sonnet 5 cells broken |
| `compass-transcribe-gpt55-haiku55.yaml` | — | | not yet run with Haiku 5.5 |

These runs were made on a larger corpus and imported scoped to the 9 bundled docsets
(`summary.json` → `imported`), so `measured_usd` is the whole run's spend and `cells_usd` the
part attributed to these cells; `cells.csv` and the grid cover only the bundled docsets. Cell
ids depend only on settings, docset and seed, so a new run of the same spec shares them: join
`cells.csv` on `cell_id`, or `dgc compare <reference_run> <new_run>` with both run directories.

To check your own run against these files without the reference run directories, score it and
run `dgc reference match <run_id>`. It pairs each of
your cells with the reference cell of the same `cell_id` (a re-run), or failing that with the
same docset, transcriber, labeler and thinking (indicative only: another seed or document
sample), and reports the quality difference, tokens and cost per document as ratios, and any
corpus, dgml or setting differences. A pair matches within 5 quality points or 2 sd of the
reference draws, whichever is wider, and 2× tokens per document (`--tolerance`,
`--token-ratio`); exit 2 when any pair does not. One-document runs such as `tiny.yaml` score low
on extraction, so expect them outside tolerance.

`dgc sweep --yes` (paid: `dgc run --yes`, `score`, `aggregate`, `report`, then the export)
writes a fresh set to `results/latest/` (gitignored); `--out results/reference` replaces the
reference, and `--spec compass-baseline-haiku55` (repeatable) restricts either to some sweeps.
Without `--yes` it plans the sweeps and stops.
