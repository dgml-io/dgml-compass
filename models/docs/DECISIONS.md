# Decisions

Model Compass began as an earlier, unpublished implementation ("the earlier implementation"
in code and docs). Each binding decision is condensed to one paragraph. Numbers 0002–0018 come
from its decision records; P1–P8 were made when it was rebuilt as this package; R1–R6 were made
for the public release. A change that moves a number needs an entry here.

## Inherited

**0002 — The axis vocabulary is closed.** The keys `axes:` and `fixed:` may use are the five
model slots plus `schema_tier`, `text_mode`, `window_size`, `temperature`, `max_tokens`,
`max_files_per_docset` and `generation.thinking`. An unknown key is a validation error naming
the field. A typo such as `generation.labelmodel` would otherwise run a sweep in which nothing
varied.

**0003 — A run lives at `<runs_dir>/<run_id>/`.** There is no extra `runs/` prefix.

**0004 — Name-only shapes are provisional.** A shape assigned from a docset's name alone, with
no document inspected, is reported and flagged `provisional`, never treated as evidence.

**0005 — Distinct labels are counted once.** A label shared across docsets counts once; the sum
of per-docset counts double-counts it. `dgc corpus check` prints both (123 and 125 on the
bundled corpus).

**0006 — Overlap matching is greedy.** Each prediction's best gold value and each gold
value's best prediction are summed. An optimal one-to-one assignment would move every
historical number.

**0007 — Ambiguities in the scoring are settled once.**
- NFKC is applied before comparison.
- The relaxed scheme contributes only its F1s.
- These choices are what `docs/METRICS.md` describes.

**0008 — A single-document docset has no consistency score.** Pairwise Jaccard and tag
inflation are undefined with one document. They and `consistency_score` are absent, not a
coerced 0.

**0009 — Empty containers count `dg:` children.** An element whose text sits in a `dg:chunk`
has content. Counting semantic children only gave 64–94% false positives.

**0010 — The model is part of the grid key.** A group never pools two models. Which slot names
the model breaks this for transcriber sweeps; that is known defect 7, pinned and unfixed.

**0014 — Predictions are padded with the sentinel, like gold.** Every (file, tag) pair over
the docset-wide union of predicted tags is `empty` when not produced, so a correct absence
matches gold's sentinel. Without the padding, F1 was low by the sentinel share.

**0015 — A cell generates only its own docset.** The workspace is built from
`Corpus.for_ref(cell.ref)`, and the planner's estimate equals the dry-run estimate (a test
pins it).

**0016 — Budget is reserved per draw and settled on actual cost.** The cap trips on measured
spend.

**0017 — A draw is the unit of execution.**
- Each draw has its own workspace, artifacts, record index and document sample.
- `sampling: fixed` gives every draw the same documents (gold first, then by name).
- `sampling: random` seeds each draw from `dgml.sample.v1:<seed>:<org>/<docset>:<draw+1>`,
  and redraws a set that repeats an earlier draw's.
- A failed draw fails the cell.

**0018 — Earlier executions can be adopted as draw 00.** Adoption happens only when they
generated exactly the documents draw 00 would, produced DGML, and use no excluded model.

## Made for this package

**P1 — The package is a self-contained uv project in its own folder.** The folder is `models/`,
the package `model_compass` and the CLI `dgc`; its `pyproject.toml`, `uv.lock`, docs, `.env` and
`local.yaml` live there, and commands run from it. `reasoning/` beside it is a separate project.

**P2 — Outputs were checked against the earlier implementation.** Every stage was compared
with its output on real runs: draw membership, cell ids, metric records, grid,
validity, compare, report and plans. Its defects were reproduced, not fixed; each is pinned by
a strict xfail stating the intended behaviour (see Known defects).

**P3 — Dead families are dropped.** The `shape` family (no spec asks for it), coverage (it
never reached a record), tag normalisation (never used) and the `optimal` overlap assignment.

**P4 — Role prices are on the economics record.** `cost_per_page_{transcribe,label,pipeline}`
are additive, and the grid appends the matching `*_usd` columns.

**P5 — `metrics:` defaults to all four families.** Every shipped spec lists its families
explicitly.

**P6 — `--retry-empty` re-runs empty draws.** On resume it re-runs any draw that reported
success but produced no DGML.

**P7 — Only the local path is kept.** Paths live under `runs_dir`, and dgml reads provider keys
itself. There is no cloud execution, storage or secrets layer.

**P8 — The report is Markdown plus CSV.** Exit codes: 2 for findings, 3 for budget.

## Made for the public release

**R1 — The corpus is bundled.** `data/corpus` holds 9 public docsets (205 documents,
gold DGML and refs) and is the default `corpus_root`; `data/shapes.yaml` is the shape
map. Cruise Itineraries (`o9dmulfkp0ii`) moved under org `z4ervk9ic0oo`, so its cell ids differ
from earlier runs; every other docset keeps its cell ids and draw samples.

**R2 — Prices ship with the repo.** `conf/prices.yaml` (the `prices_file` setting) prices
plans and the budget cap. Without it every estimate would be $0 and the cap would trip only
after spend accumulates.

**R3 — The evidence-pack export and the import of earlier results are dropped.** The pipeline ends at
`score → aggregate → report → compare`.

**R4 — Goldens are regenerated by this repo.** Plan goldens (`scripts/make_golden_plans.py`)
and aggregation goldens (`scripts/make_golden_aggregate.py`) come from this repo's code over
the bundled corpus and fixtures. Before release they matched the earlier implementation on
the full data: identical cell ids and draw samples for every public cell, byte-identical grids,
validity and reports. The scoring golden (`tests/metrics/expected/msa_tree.jsonl`) is the
earlier implementation's output, kept frozen.

**R5 — Test fixtures carry only public docsets.** Run fixtures were cut to the public cells,
with neutral paths and no branch names; aggregate numbers in the goldens are over those cells.

**R6 — Corpus files carry no authoring metadata.** Every bundled PDF lost its Info
dictionaries and XMP streams; every DOCX its author, last-editor, internal custom properties
and local template paths. Page content, DOCX bodies, file names and gold are unchanged, so cell
ids and draw samples are too, but the corpus hash differs from runs made before the change.

**R7 — `max_parallel_calls` reaches dgml.** It used to size a per-draw pool over docsets, and a
draw holds one docset (0015), so it did nothing. It is now passed as `docset generate
--max-parallel-calls` (documents transcribed at once; a document's windows stay serial), a flag
like the other generation knobs, since dgml has no config.toml key for it. Draws now run at 8
concurrent documents by default instead of dgml's 4; no metric definition or number moves.

**R8 — The label-model check reads `config.toml` (was known defect 3).** It read `config.json`,
which dgml stopped writing when it moved to TOML, so every economics record said `no_config` and
`label_model_mismatch` could never fire. It now reads `[generation] label_model` from the
workspace's `config.toml` (the file compass writes per draw), falling back to `config.json` for
workspaces made before dgml's move. New runs' economics records lose `no_config` and carry
`label_model_mismatch` when the label calls in `usage.jsonl` used another model. Warnings only:
no metric value moves. The fixtures and goldens are unchanged, since their workspaces hold no
config file and still say `no_config`.

## Known defects

Reproduced on purpose so numbers stay comparable with earlier results. Most are pinned by a
strict xfail stating the intended behaviour; fixing one means regenerating the goldens and
recording it here.

1. `complex_*` scores are emitted as 0.0 although nothing produces complex predictions.
2. `n_orphan_gold` counts unsampled documents as "no document on disk".
3. Fixed by R8 (the number is kept so references to later defects stay valid).
4. `missing_dgml_rate` is 0–1 in extraction records and 0–100 in economics records.
5. Resume rewrites `events.jsonl` with only the latest invocation's events, and
   `run --resume --dry-run` rewrites the run's resolved spec.
6. Resume records cost 0 for draws finished before it.
7. Grid rows key the model by label model first, so transcriber sweeps pool all transcribers
   into one row (against 0010).
8. `n_documents` is counted once per family (about 3×), and the report's cost attribution
   inherits it: "attributed spend" overstates every model by the same factor, so shares hold
   and totals do not.
