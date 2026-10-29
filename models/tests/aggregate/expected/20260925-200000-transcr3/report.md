# Run 20260925-200000-transcr3

## What ran

- Outcome: **succeeded**
- 40 cells, 0 failed
- Measured spend: **$285.5692**
- Grid: 3 rows, 1 comparable

## Best model per shape

Only comparable rows are eligible. **Contested** means the runner-up's 2SE band overlaps the winner's, so the ranking is not resolved by this evidence.

| shape | model | quality | cost/doc | docsets | contested |
| --- | --- | ---: | ---: | ---: | :---: |
| prose_narrative | `anthropic/claude-haiku-4-5` | 77.35 ±7.81 | $0.3790 | 5 |  |

## The grid

Quality carries its two-standard-error band, computed between docsets. A row marked `n=1` rests on a single docset and has no band — that is not a precise number, it is an unmeasured one.

| shape | schema | model | quality (F1, 0-100) | tag-blind | gap | docsets | draws | cost/doc (USD) | comparable |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| form | none | `anthropic/claude-haiku-4-5` | 87.52 ±7.51 | 94.99 | 7.47 | 2 | 3 | $0.2197 | no |
| hybrid_composite | none | `anthropic/claude-haiku-4-5` | 91.71 (n=1) | 95.91 | 4.21 | 1 | 3 | $0.8385 | no |
| prose_narrative | none | `anthropic/claude-haiku-4-5` | 77.35 ±7.81 | 87.05 | 9.70 | 5 | 3 | $0.3790 | yes |

## Comparability gates

2 of 3 rows are not comparable. A non-comparable row may not be ranked against another without saying so.

| code | rows | meaning |
| --- | ---: | --- |
| `single_docset` | 1 | one docset, so there is no between-docset band |
| `too_few_docsets` | 2 | fewer docsets than the comparability floor |

## Cost

Attributed spend totals **$856.6830** across 1 models.

| model | attributed cost | share |
| --- | ---: | ---: |
| `anthropic/claude-haiku-4-5` | $856.6830 | 100.0% |

> 3 row(s) carry `cost_partial`: some spend could not be attributed to a document, so those figures are a workspace total spread over documents, not a measurement. They may not be compared with unflagged rows.

## Failures

No cell failed.

## What was asked for

**compass-transcribe** — compass-transcribe over the public docsets.

Swept axes:

- `generation.model`: anthropic/claude-haiku-4-5, anthropic/claude-sonnet-5, anthropic/claude-opus-5, gemini/gemini-3.6-flash, openai/gpt-5.5

Held fixed:

- `generation.label_model` = anthropic/claude-haiku-4-5
- `schema_tier` = none
- `text_mode` = digital
- `window_size` = 10

Draws per cell: 3. Metric families: extraction, reference_free, economics.

## Provenance

Everything below is what the run recorded about itself. An artifact that cannot be traced to this block is a bug.

| field | value |
| --- | --- |
| corpus hash | `c63488a3458a1141` |
| dgml version | `dgml 0.1.1` |
| python | `3.12.13` |
| dgml-compass | `0.1.0` |
| repo `corpus` | `71386f50bb39b2948a20b798f1fbe1fadcae223d` *(uncommitted changes)* |
| repo `dgml` | `a4547da81ede8c11eb05d513a63ea00f090e2dfc` |

> One or more repositories had uncommitted changes when this run started, so the recorded SHAs do not fully describe the code that produced these numbers.

## Summary line

One line for CI, machine-parseable:

```
run=20260925-200000-transcr3 outcome=succeeded cells=40 failed=0 cost_usd=285.5692 rows=3 comparable=1 partial=no best_by_shape=prose_narrative=anthropic/claude-haiku-4-5
```
