# Run 20261008-140547-4fe5464b

## What ran

- Outcome: **succeeded**
- 8 cells, 0 failed
- Measured spend: **$3.2987**
- Grid: 3 rows, 1 comparable

## Best model per shape

Only comparable rows are eligible. **Contested** means the runner-up's 2SE band overlaps the winner's, so the ranking is not resolved by this evidence.

| shape | model | quality | cost/doc | docsets | contested |
| --- | --- | ---: | ---: | ---: | :---: |
| prose_narrative | `anthropic/claude-haiku-5-5` | 67.70 ±8.53 | $0.0224 | 5 |  |

## The grid

Quality carries its two-standard-error band, computed between docsets. A row marked `n=1` rests on a single docset and has no band — that is not a precise number, it is an unmeasured one.

| shape | schema | model | quality (F1, 0-100) | tag-blind | gap | docsets | draws | cost/doc (USD) | comparable |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| form | none | `anthropic/claude-haiku-5-5` | 87.75 ±11.03 | 96.16 | 8.42 | 2 | 3 | $0.0137 | no |
| hybrid_composite | none | `anthropic/claude-haiku-5-5` | 89.73 (n=1) | 94.40 | 4.67 | 1 | 3 | $0.0441 | no |
| prose_narrative | none | `anthropic/claude-haiku-5-5` | 67.70 ±8.53 | 86.24 | 18.54 | 5 | 3 | $0.0224 | yes |

## Comparability gates

2 of 3 rows are not comparable. A non-comparable row may not be ranked against another without saying so.

| code | rows | meaning |
| --- | ---: | --- |
| `single_docset` | 1 | one docset, so there is no between-docset band |
| `too_few_docsets` | 2 | fewer docsets than the comparability floor |

## Cost

Attributed spend totals **$9.9090** across 1 models.

| model | attributed cost | share |
| --- | ---: | ---: |
| `anthropic/claude-haiku-5-5` | $9.9090 | 100.0% |

> 3 row(s) carry `cost_partial`: some spend could not be attributed to a document, so those figures are a workspace total spread over documents, not a measurement. They may not be compared with unflagged rows.

## Failures

No cell failed.

## What was asked for

**compass-corpus-3x6-haiku55** — compass-corpus-3x6-haiku55 over the public docsets.

Held fixed:

- `generation.label_model` = anthropic/claude-haiku-5-5
- `generation.model` = anthropic/claude-haiku-5-5
- `schema_tier` = none
- `text_mode` = digital
- `window_size` = 10

Draws per cell: 3. Metric families: extraction, reference_free, economics, tree.

## Provenance

Everything below is what the run recorded about itself. An artifact that cannot be traced to this block is a bug.

| field | value |
| --- | --- |
| corpus hash | `d9607f9b518b706a` |
| dgml version | `dgml 0.1.1` |
| python | `3.12.13` |
| dgml-compass | `0.1.0` |
| repo `corpus` | `71386f50bb39b2948a20b798f1fbe1fadcae223d` *(uncommitted changes)* |
| repo `dgml` | `ffdb38b51ad2f6ac0d859d54e16be2c87aa5da97` |

> One or more repositories had uncommitted changes when this run started, so the recorded SHAs do not fully describe the code that produced these numbers.

## Summary line

One line for CI, machine-parseable:

```
run=20261008-140547-4fe5464b outcome=succeeded cells=8 failed=0 cost_usd=3.2987 rows=3 comparable=1 partial=no best_by_shape=prose_narrative=anthropic/claude-haiku-5-5
```
