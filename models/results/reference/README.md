# Reference results: `reference`

Rebuilt by `dgc reference report` from the `summary.json` and `cells.csv` of each sweep; no model is called. Quality is `individual_overlap_f1` (0–100), the per-cell mean over draws, then the unweighted mean over the docsets of a shape; tokens and cost are summed over every draw of every cell. These are descriptive totals. The bands, comparability gates and best-by-shape rankings are in each sweep's `compass_grid.csv` and report tables -- a shape resting on one or two docsets has no trustworthy band, whatever the mean says.

## Sweeps

| spec | run | outcome | cells | draws | documents | tokens | cells' cost | run spend | grid rows comparable |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `compass-baseline-haiku55` | `20261008-154627-56e22032` | succeeded | 9 | 3 | 162 | 22.8 M | $3.60 | $6.09 | 1/4 |
| `compass-baseline-haiku55-think` | `20261013-203701-d87d278e` | succeeded | 9 | 3 | 162 | 26.8 M | $5.54 | $9.49 | 1/4 |
| `compass-corpus-3x6-haiku55` | `20261008-140547-4fe5464b` | succeeded | 9 | 3 | 162 | 21.6 M | $3.53 | $5.94 | 1/4 |
| `compass-label-gemini` | `20260925-200002-labelgm3` | succeeded | 54 | 3 | 972 | 111.9 M | $495.80 | $745.47 | 6/24 |
| `compass-label-haiku55` | `20261014-022456-37998681` | succeeded | 54 | 3 | 972 | 137.9 M | $432.23 | $583.31 | 6/24 |
| `compass-transcribe-gpt55` | `20260930-200000-trgpt55` | succeeded | 45 | 3 | 809 | 85.0 M | $778.92 | $1,220.28 | 1/4 |
| `compass-transcribe-haiku55` | `20261008-175618-25ef2d78` | succeeded | 45 | 3 | 767 | 95.3 M | $185.22 | $337.06 | 1/4 |

*cells' cost* is the spend attributed to these cells' draws (`cells.csv`); *run spend* is what the whole run measured, which for a run imported from a larger sweep includes cells outside the bundled corpus.

## `compass-baseline-haiku55`

compass-baseline-haiku55: conf/experiments/compass-transcribe.yaml with transcriber AND labeler at anthropic/claude-haiku-5-5 (was Haiku 4.5). Docsets, sampling, seed and draws unchanged, so cells pair with the Haiku 4.5 ones.

| transcriber → labeler | docsets | complex_layout | form | hybrid_composite | prose_narrative | tokens/doc | cost/doc | spend |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `anthropic/claude-haiku-5-5` → `anthropic/claude-haiku-5-5` | 9 | 79.9 (n=1) | 88.1 (n=2) | 93.1 (n=1) | 72.3 (n=5) | 141 k | $0.0222 | $3.60 |

## `compass-baseline-haiku55-think`

compass-baseline-haiku55 (Haiku 5.5 transcriber and labeler) with generation.thinking adaptive. Docsets, sampling, seed and draws unchanged, so cells pair with the thinking-disabled run.

| transcriber → labeler | docsets | complex_layout | form | hybrid_composite | prose_narrative | tokens/doc | cost/doc | spend |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `anthropic/claude-haiku-5-5` → `anthropic/claude-haiku-5-5` (thinking adaptive) | 9 | 94.3 (n=1) | 84.8 (n=2) | 92.2 (n=1) | 69.6 (n=5) | 166 k | $0.0342 | $5.54 |

## `compass-corpus-3x6-haiku55`

compass-corpus-3x6-haiku55: conf/experiments/compass-corpus-3x6.yaml with transcriber AND labeler at anthropic/claude-haiku-5-5 (was Haiku 4.5). Docsets, sampling, seed and draws unchanged, so cells pair with the Haiku 4.5 ones.

| transcriber → labeler | docsets | complex_layout | form | hybrid_composite | prose_narrative | tokens/doc | cost/doc | spend |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `anthropic/claude-haiku-5-5` → `anthropic/claude-haiku-5-5` | 9 | 75.2 (n=1) | 87.7 (n=2) | 89.7 (n=1) | 67.7 (n=5) | 133 k | $0.0218 | $3.53 |

## `compass-label-gemini`

Labeler sweep with the transcriber held at Gemini 3.6 Flash (earlier implementation, September 2026), imported scoped to the bundled corpus. Its Haiku labeler is Haiku 4.5, not 5.5; includes Gemini 3.6 Flash in both roles.

| transcriber → labeler | docsets | complex_layout | form | hybrid_composite | prose_narrative | tokens/doc | cost/doc | spend |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `gemini/gemini-3.6-flash` → `anthropic/claude-haiku-4-5` | 9 | 92.7 (n=1) | 93.0 (n=2) | 93.3 (n=1) | 74.8 (n=5) | 107 k | $0.2214 | $35.87 |
| `gemini/gemini-3.6-flash` → `anthropic/claude-opus-5` | 9 | 85.0 (n=1) | 92.7 (n=2) | 95.7 (n=1) | 66.0 (n=5) | 136 k | $0.7689 | $124.57 |
| `gemini/gemini-3.6-flash` → `anthropic/claude-sonnet-5` | 9 | 74.6 (n=1) | 89.2 (n=2) | 92.4 (n=1) | 70.0 (n=5) | 114 k | $0.3267 | $52.92 |
| `gemini/gemini-3.6-flash` → `gemini/gemini-3.1-flash-lite` | 9 | 68.7 (n=1) | 55.4 (n=2) | 59.0 (n=1) | 59.5 (n=5) | 78 k | $0.1203 | $19.49 |
| `gemini/gemini-3.6-flash` → `gemini/gemini-3.6-flash` | 9 | 82.6 (n=1) | 65.4 (n=2) | 61.6 (n=1) | 65.6 (n=5) | 102 k | $0.2332 | $37.77 |
| `gemini/gemini-3.6-flash` → `openai/gpt-5.5` | 9 | 94.8 (n=1) | 96.0 (n=2) | 96.0 (n=1) | 73.6 (n=5) | 153 k | $1.3901 | $225.19 |

## `compass-label-haiku55`

conf/experiments/compass-label.yaml with Haiku 4.5 replaced by anthropic/claude-haiku-5-5 (generation.model held at anthropic/claude-haiku-5-5). Docsets, sampling, seed and draws unchanged, so cells pair with the Haiku 4.5 ones.

| transcriber → labeler | docsets | complex_layout | form | hybrid_composite | prose_narrative | tokens/doc | cost/doc | spend |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `anthropic/claude-haiku-5-5` → `anthropic/claude-haiku-5-5` | 9 | 79.9 (n=1) | 88.1 (n=2) | 93.1 (n=1) | 72.3 (n=5) | 141 k | $0.0222 | $3.60 |
| `anthropic/claude-haiku-5-5` → `anthropic/claude-opus-5` | 9 | 91.9 (n=1) | 95.3 (n=2) | 93.5 (n=1) | 77.1 (n=5) | 159 k | $0.7905 | $128.06 |
| `anthropic/claude-haiku-5-5` → `anthropic/claude-sonnet-5` | 9 | 93.2 (n=1) | 91.6 (n=2) | 90.2 (n=1) | 76.2 (n=5) | 143 k | $0.2750 | $44.55 |
| `anthropic/claude-haiku-5-5` → `gemini/gemini-3.1-flash-lite` | 9 | 58.9 (n=1) | 47.8 (n=2) | 64.6 (n=1) | 58.3 (n=5) | 100 k | $0.0246 | $3.99 |
| `anthropic/claude-haiku-5-5` → `gemini/gemini-3.6-flash` | 9 | 76.8 (n=1) | 79.8 (n=2) | 42.6 (n=1) | 72.3 (n=5) | 122 k | $0.1335 | $21.62 |
| `anthropic/claude-haiku-5-5` → `openai/gpt-5.5` | 9 | 95.9 (n=1) | 94.4 (n=2) | 85.8 (n=1) | 79.9 (n=5) | 186 k | $1.4223 | $230.42 |

## `compass-transcribe-gpt55`

Transcriber sweep with the labeler held at GPT-5.5 (earlier implementation, September-October 2026), imported scoped to the bundled corpus. Its Haiku transcriber is Haiku 4.5, not 5.5; includes GPT-5.5 in both roles. The Opus 5 and Sonnet 5 cells are broken (GPT-5.5 labeling calls failed, trees left unlabelled).

| transcriber → labeler | docsets | complex_layout | form | hybrid_composite | prose_narrative | tokens/doc | cost/doc | spend |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `anthropic/claude-haiku-4-5` → `openai/gpt-5.5` | 9 | 96.4 (n=1) | 93.4 (n=2) | 95.0 (n=1) | 76.2 (n=5) | 161 k | $1.3779 | $223.23 |
| `anthropic/claude-opus-5` → `openai/gpt-5.5` | 9 | 11.8 (n=1) | 4.0 (n=2) | 8.3 (n=1) | 14.3 (n=5) | 47 k | $0.4411 | $71.46 |
| `anthropic/claude-sonnet-5` → `openai/gpt-5.5` | 9 | 64.0 (n=1) | 4.4 (n=2) | 8.2 (n=1) | 14.1 (n=5) | 57 k | $0.2447 | $39.64 |
| `gemini/gemini-3.6-flash` → `openai/gpt-5.5` | 9 | 94.8 (n=1) | 96.0 (n=2) | 96.0 (n=1) | 73.6 (n=5) | 153 k | $1.3901 | $225.19 |
| `openai/gpt-5.5` → `openai/gpt-5.5` | 9 | 89.4 (n=1) | 94.7 (n=2) | 96.3 (n=1) | 77.2 (n=5) | 107 k | $1.3628 | $219.41 |

## `compass-transcribe-haiku55`

conf/experiments/compass-transcribe.yaml with Haiku 4.5 replaced by anthropic/claude-haiku-5-5 (generation.label_model held at anthropic/claude-haiku-5-5). Docsets, sampling, seed and draws unchanged, so cells pair with the Haiku 4.5 ones.

| transcriber → labeler | docsets | complex_layout | form | hybrid_composite | prose_narrative | tokens/doc | cost/doc | spend |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `anthropic/claude-haiku-5-5` → `anthropic/claude-haiku-5-5` | 9 | 73.8 (n=1) | 91.4 (n=2) | 93.4 (n=1) | 71.5 (n=5) | 142 k | $0.0218 | $3.54 |
| `anthropic/claude-opus-5` → `anthropic/claude-haiku-5-5` | 9 | 77.0 (n=1) | 88.0 (n=2) | 94.3 (n=1) | 71.9 (n=5) | 129 k | $0.4549 | $73.70 |
| `anthropic/claude-sonnet-5` → `anthropic/claude-haiku-5-5` | 9 | 73.4 (n=1) | 90.7 (n=2) | 90.7 (n=1) | 71.8 (n=5) | 133 k | $0.1990 | $32.24 |
| `gemini/gemini-3.6-flash` → `anthropic/claude-haiku-5-5` | 9 | 75.6 (n=1) | 91.0 (n=2) | 48.2 (n=1) | 54.9 (n=5) | 107 k | $0.1077 | $13.57 |
| `openai/gpt-5.5` → `anthropic/claude-haiku-5-5` | 9 | 77.6 (n=1) | 86.4 (n=2) | 92.8 (n=1) | 73.2 (n=5) | 106 k | $0.4011 | $62.17 |

## Files

Each `<spec>/` holds `summary.json`, `cells.csv` (shape × docset × models, with tokens and cost per cell), `compass_grid.csv` and `validity.json` from `dgc aggregate`, and the `dgc report` tables `by_shape.csv`, `best_by_shape.csv`, `gates.csv`, `cost_by_model.csv`, `failures.csv`. Compare a new run against one with `dgc compare <reference_run> <new_run>` when both run directories are at hand, or against these files with `cells.csv` joined on `cell_id` (ids depend only on the cell's settings, docset and seed).
