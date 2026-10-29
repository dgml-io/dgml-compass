# Run 20261014-022456-37998681

## What ran

- Outcome: **succeeded**
- 48 cells, 0 failed
- Measured spend: **$345.0765**
- Grid: 18 rows, 6 comparable

## Best model per shape

Only comparable rows are eligible. **Contested** means the runner-up's 2SE band overlaps the winner's, so the ranking is not resolved by this evidence.

| shape | model | quality | cost/doc | docsets | contested |
| --- | --- | ---: | ---: | ---: | :---: |
| prose_narrative | `openai/gpt-5.5` | 79.91 ±12.74 | $1.5537 | 5 | yes — vs `anthropic/claude-opus-5` |

## The grid

Quality carries its two-standard-error band, computed between docsets. A row marked `n=1` rests on a single docset and has no band — that is not a precise number, it is an unmeasured one.

| shape | schema | model | quality (F1, 0-100) | tag-blind | gap | docsets | draws | cost/doc (USD) | comparable |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| form | none | `gemini/gemini-3.6-flash` | 79.78 ±17.28 | 93.67 | 13.88 | 2 | 3 | $0.0966 | no |
| form | none | `gemini/gemini-3.1-flash-lite` | 47.75 ±23.14 | 89.17 | 41.42 | 2 | 3 | $0.0161 | no |
| form | none | `openai/gpt-5.5` | 94.43 ±5.48 | 96.20 | 1.77 | 2 | 3 | $0.5699 | no |
| form | none | `anthropic/claude-haiku-5-5` | 88.11 ±8.53 | 95.73 | 7.63 | 2 | 3 | $0.0147 | no |
| form | none | `anthropic/claude-opus-5` | 95.32 ±4.34 | 96.72 | 1.40 | 2 | 3 | $0.5870 | no |
| form | none | `anthropic/claude-sonnet-5` | 91.58 ±7.32 | 96.13 | 4.55 | 2 | 3 | $0.2243 | no |
| hybrid_composite | none | `gemini/gemini-3.6-flash` | 42.60 (n=1) | 95.49 | 52.89 | 1 | 3 | $0.2563 | no |
| hybrid_composite | none | `gemini/gemini-3.1-flash-lite` | 64.57 (n=1) | 93.03 | 28.46 | 1 | 3 | $0.0514 | no |
| hybrid_composite | none | `openai/gpt-5.5` | 85.79 (n=1) | 95.21 | 9.42 | 1 | 3 | $3.3066 | no |
| hybrid_composite | none | `anthropic/claude-haiku-5-5` | 93.11 (n=1) | 95.84 | 2.72 | 1 | 3 | $0.0456 | no |
| hybrid_composite | none | `anthropic/claude-opus-5` | 93.50 (n=1) | 96.15 | 2.65 | 1 | 3 | $1.2285 | no |
| hybrid_composite | none | `anthropic/claude-sonnet-5` | 90.16 (n=1) | 95.43 | 5.26 | 1 | 3 | $0.4988 | no |
| prose_narrative | none | `gemini/gemini-3.6-flash` | 72.30 ±8.98 | 86.27 | 13.97 | 5 | 3 | $0.1349 | yes |
| prose_narrative | none | `gemini/gemini-3.1-flash-lite` | 58.29 ±3.80 | 83.38 | 25.10 | 5 | 3 | $0.0251 | yes |
| prose_narrative | none | `openai/gpt-5.5` | 79.91 ±12.74 | 89.65 | 9.75 | 5 | 3 | $1.5537 | yes |
| prose_narrative | none | `anthropic/claude-haiku-5-5` | 72.28 ±13.44 | 85.13 | 12.85 | 5 | 3 | $0.0226 | yes |
| prose_narrative | none | `anthropic/claude-opus-5` | 77.11 ±11.79 | 87.47 | 10.37 | 5 | 3 | $0.8404 | yes |
| prose_narrative | none | `anthropic/claude-sonnet-5` | 76.24 ±9.02 | 86.93 | 10.69 | 5 | 3 | $0.2694 | yes |

## Comparability gates

12 of 18 rows are not comparable. A non-comparable row may not be ranked against another without saying so.

| code | rows | meaning |
| --- | ---: | --- |
| `single_docset` | 6 | one docset, so there is no between-docset band |
| `too_few_docsets` | 12 | fewer docsets than the comparability floor |

## Cost

Attributed spend totals **$1,222.2846** across 6 models.

| model | attributed cost | share |
| --- | ---: | ---: |
| `openai/gpt-5.5` | $659.6046 | 54.0% |
| `anthropic/claude-opus-5` | $356.6430 | 29.2% |
| `anthropic/claude-sonnet-5` | $123.8976 | 10.1% |
| `gemini/gemini-3.6-flash` | $60.6960 | 5.0% |
| `gemini/gemini-3.1-flash-lite` | $11.2914 | 0.9% |
| `anthropic/claude-haiku-5-5` | $10.1520 | 0.8% |

> 18 row(s) carry `cost_partial`: some spend could not be attributed to a document, so those figures are a workspace total spread over documents, not a measurement. They may not be compared with unflagged rows.

## Failures

No cell failed.

## What was asked for

**compass-label-haiku55** — compass-label-haiku55 over the public docsets.

Swept axes:

- `generation.label_model`: anthropic/claude-haiku-5-5, anthropic/claude-opus-5, anthropic/claude-sonnet-5, gemini/gemini-3.6-flash, gemini/gemini-3.1-flash-lite, openai/gpt-5.5

Held fixed:

- `generation.model` = anthropic/claude-haiku-5-5
- `schema_tier` = none
- `text_mode` = digital
- `window_size` = 10

Draws per cell: 3. Metric families: extraction, reference_free, economics, tree.

## Provenance

Everything below is what the run recorded about itself. An artifact that cannot be traced to this block is a bug.

| field | value |
| --- | --- |
| corpus hash | `2a590b16a0b17202` |
| dgml version | `dgml 0.1.1` |
| python | `3.12.13` |
| dgml-compass | `0.1.0` |
| repo `corpus` | `71386f50bb39b2948a20b798f1fbe1fadcae223d` *(uncommitted changes)* |
| repo `dgml` | `d6e55f66ad2fbde9ff1816fde6a60bde8dc7478a` |

> One or more repositories had uncommitted changes when this run started, so the recorded SHAs do not fully describe the code that produced these numbers.

## Summary line

One line for CI, machine-parseable:

```
run=20261014-022456-37998681 outcome=succeeded cells=48 failed=0 cost_usd=345.0765 rows=18 comparable=6 partial=no best_by_shape=prose_narrative=openai/gpt-5.5
```
