# Model Compass: results on the bundled corpus

Which models should fill dgml's two roles, **transcriber** (`generation.model`) and **labeler**
(`generation.label_model`)? These are the reference results of the Model Compass sweeps over the
9 public docsets bundled in [`data/corpus`](../data/corpus), as committed under
[`results/reference/`](../results/reference).
Seven sweeps, 225 cells, 501 M tokens, about $1,905 of attributed spend.

## How to read the numbers

- **Quality** is `individual_overlap_f1` on a 0–100 scale: per document, each predicted field
  value is matched against the gold value by relaxed overlap, and the F1 is taken over the
  docset's fields; a cell's figure is the mean over its 3 draws, and an arm's figure the
  unweighted mean over its 9 docsets. **± 2 SE** is two standard errors of that mean *between
  docsets*: it says how much the arm's mean would move with other documents of the same kinds,
  and it is wide because the docsets differ far more than the models do.
- **Tag-blind recall** (`value_only_overlap_recall`) is the share of gold values found under
  *any* tag. The gap between it and quality is naming: values found but filed under another
  field name.
- **Draw SD** is the mean within-cell standard deviation across the 3 draws of the same
  documents — generation noise alone. Differences smaller than it are not differences.
- **Tokens, cost and seconds per document** come from dgml's usage log for every call of the
  pipeline (transcription and labeling together), summed over all 3 draws and divided by the
  documents produced. Cost uses provider list prices at run time; a few `cost_partial` draws
  spread an unattributed remainder over their documents.
- Every arm ran the same 6 documents per docset (`sampling: fixed`, seed 20260917), 3 draws,
  `schema_tier: none`, `window_size: 10`, `text_mode: digital`, thinking off unless stated. The
  Haiku 5.5 → Haiku 5.5 cells are shared by the two sweeps and the baseline (same cell ids), so
  their numbers are identical by construction.
- Shape columns rest on 1, 2, 1 and 5 docsets respectively. Only `prose_narrative` clears the
  comparability floor of 3 docsets in the aggregate grid; the other shapes are single-docset
  observations and should be read as such.

## The corpus

| docset | shape | documents in corpus | sampled per draw | pages per draw |
|---|---|---:|---:|---:|
| Cruise Itineraries | complex_layout | 13 | 6 | 36 |
| NTSB Aviation Incident Reports | form | 65 | 6 | 24 |
| Safety Data Sheets | form | 34 | 6 | 54 |
| Commercial Leases | hybrid_composite | 15 | 6 | 132 |
| Master Services Agreements | prose_narrative | 21 | 6 | 49 |
| Medical Notes (UNC) | prose_narrative | 9 | 6 | 35 |
| Clinical Trial Protocols | prose_narrative | 14 | 6 | 178 |
| Transport Agreements | prose_narrative | 20 | 6 | 80 |
| Supplier Agreements | prose_narrative | 14 | 6 | 105 |

## 1. Which labeler? (`compass-label-haiku55`)

Transcriber held at Haiku 5.5; six labelers. 54 cells, 972 documents, 138 M tokens.

| labeler (transcriber Haiku 5.5) | quality (F1) | tag-blind recall | draw SD | documents | tokens/doc | cost/doc | s/doc | spend |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GPT-5.5 | **85.6** ± 8.3 | 92.7 | 3.3 | 162 | 186 k | $1.422 | 465 | $230.42 |
| Opus 5 | **84.6** ± 8.7 | 91.6 | 3.0 | 162 | 159 k | $0.790 | 235 | $128.06 |
| Sonnet 5 | **83.1** ± 7.3 | 91.2 | 4.0 | 162 | 143 k | $0.275 | 179 | $44.55 |
| Haiku 5.5 | **79.0** ± 9.2 | 89.5 | 4.8 | 162 | 141 k | $0.022 | 89 | $3.60 |
| Gemini 3.6 Flash | **71.2** ± 9.3 | 89.9 | 7.3 | 162 | 122 k | $0.133 | 151 | $21.62 |
| Gemini 3.1 Flash Lite | **56.7** ± 5.7 | 86.2 | 4.1 | 162 | 100 k | $0.025 | 55 | $3.99 |

The three frontier labelers sit within 2.5 points of each other and well inside each other's
bands; the aggregate grid's best-by-shape call for `prose_narrative` is GPT-5.5 (79.9 ± 12.7)
and marks it *contested* with Opus 5. Below them the ordering is clear: Haiku 5.5 gives up 4–7
points, Gemini 3.6 Flash 12–14, Flash Lite 29. Tag-blind recall is 86–93 for every labeler, so
the spread is almost entirely a *naming* spread: the weaker labelers find the values but file
them under other field names. Gemini 3.6 Flash also has the largest draw-to-draw noise (7.3) and
one near-collapse on Safety Data Sheets (71.1 ± 30.1).

Cost separates them far more than quality does. Per document, Sonnet 5 costs 12× Haiku 5.5 for
+4.1 points; Opus 5 costs 36× for +5.6; GPT-5.5 costs 64× for +6.6, and takes 5× longer per
document.

### By shape

| labeler | complex_layout (1) | form (2) | hybrid_composite (1) | prose_narrative (5) |
|---|---:|---:|---:|---:|
| GPT-5.5 | 95.9 | 94.4 | 85.8 | 79.9 |
| Opus 5 | 91.9 | 95.3 | 93.5 | 77.1 |
| Sonnet 5 | 93.2 | 91.6 | 90.2 | 76.2 |
| Gemini 3.6 Flash | 76.8 | 79.8 | 42.6 | 72.3 |
| Haiku 5.5 | 79.9 | 88.1 | 93.1 | 72.3 |
| Gemini 3.1 Flash Lite | 58.9 | 47.8 | 64.6 | 58.3 |

### By docset (mean over 3 draws ± SD across draws)

| docset | shape | GPT-5.5 | Opus 5 | Sonnet 5 | Haiku 5.5 | Gemini 3.6 Flash | Gemini 3.1 Flash Lite |
|---|---|---:|---:|---:|---:|---:|---:|
| Cruise Itineraries | complex_layout | 95.9 ± 4.3 | 91.9 ± 3.1 | 93.2 ± 8.3 | 79.9 ± 8.9 | 76.8 ± 1.8 | 58.9 ± 0.6 |
| NTSB Aviation Reports | form | 97.2 ± 1.9 | 97.5 ± 2.0 | 95.2 ± 1.4 | 92.4 ± 1.7 | 88.4 ± 9.4 | 59.3 ± 1.1 |
| Safety Data Sheets | form | 91.7 ± 1.0 | 93.2 ± 2.6 | 87.9 ± 8.8 | 83.8 ± 9.7 | 71.1 ± 30.1 | 36.2 ± 1.9 |
| Commercial Leases | hybrid_composite | 85.8 ± 6.3 | 93.5 ± 1.0 | 90.2 ± 5.5 | 93.1 ± 2.4 | 42.6 ± 11.5 | 64.6 ± 6.7 |
| Master Services Agreements | prose_narrative | 88.9 ± 1.9 | 82.4 ± 1.0 | 78.0 ± 2.4 | 81.7 ± 2.0 | 77.6 ± 1.5 | 55.7 ± 12.9 |
| Medical Notes (UNC) | prose_narrative | 77.3 ± 6.7 | 75.9 ± 6.7 | 71.7 ± 0.4 | 63.2 ± 5.7 | 67.0 ± 6.2 | 63.5 ± 1.6 |
| Clinical Trial Protocols | prose_narrative | 56.6 ± 1.6 | 59.2 ± 5.5 | 74.4 ± 2.2 | 59.1 ± 5.4 | 75.9 ± 2.8 | 62.3 ± 1.9 |
| Transport Agreements | prose_narrative | 92.5 ± 2.1 | 95.2 ± 0.6 | 92.1 ± 2.2 | 94.1 ± 3.2 | 83.3 ± 1.2 | 54.7 ± 4.7 |
| Supplier Agreements | prose_narrative | 84.2 ± 3.9 | 72.8 ± 4.3 | 65.0 ± 4.5 | 63.3 ± 3.9 | 57.7 ± 1.2 | 55.2 ± 5.8 |

Two docsets drive most of the disagreement. On **Clinical Trial Protocols** the big labelers do
no better than Haiku (GPT-5.5 is worst at 56.6), while Sonnet 5 and Gemini 3.6 Flash reach
74–76. On **Supplier Agreements** GPT-5.5 is 11–20 points ahead of everyone else. The
`form` docsets are near ceiling for every Anthropic and OpenAI labeler.

## 2. Which transcriber? (`compass-transcribe-haiku55`)

Labeler held at Haiku 5.5; five transcribers. 45 cells, 767 documents, 95 M tokens.

| transcriber (labeler Haiku 5.5) | quality (F1) | tag-blind recall | draw SD | documents | tokens/doc | cost/doc | s/doc | spend |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GPT-5.5 | **78.8** ± 10.9 | 87.2 | 5.8 | 155 † | 106 k | $0.401 | 209 | $62.17 |
| Haiku 5.5 | **78.6** ± 10.1 | 89.4 | 4.2 | 162 | 142 k | $0.022 | 87 | $3.54 |
| Opus 5 | **78.5** ± 8.7 | 90.9 | 5.1 | 162 | 129 k | $0.455 | 165 | $73.70 |
| Sonnet 5 | **78.3** ± 10.1 | 89.5 | 4.0 | 162 | 133 k | $0.199 | 148 | $32.24 |
| Gemini 3.6 Flash | **64.5** ± 16.4 | 70.6 | 3.3 | 126 † | 107 k | $0.108 | 227 | $13.57 |

† Fewer than 162 documents: some draws returned no DGML for some documents. Gemini 3.6 Flash
lost 36 of 162 (Clinical Trial Protocols kept 1 of 6 documents, Commercial Leases 3 of 6); the
missing documents are not scored, so its quality is over the documents it did produce. GPT-5.5
lost 7, in the two cells regenerated after the provider ran out of credit.

With the labeler fixed, the four frontier-and-Haiku transcribers are indistinguishable: 78.3 to
78.8, against a draw SD of 4–6. Haiku 5.5 transcribes as well as Opus 5, Sonnet 5 and GPT-5.5
at 1/9 to 1/20 of their cost per document. Gemini 3.6 Flash is the exception: 14 points lower
on quality and 19 lower on tag-blind recall, on top of the missing documents — its
transcriptions lose values, not only names.

The aggregate grid pools these five arms into one row per shape (the model in the grid key is
the labeler, DECISIONS 0010 / known defect 7), which is why `compass_grid.csv` for this sweep
has 4 rows; the per-transcriber figures above come from `cells.csv`.

### By shape

| transcriber | complex_layout (1) | form (2) | hybrid_composite (1) | prose_narrative (5) |
|---|---:|---:|---:|---:|
| GPT-5.5 | 77.6 | 86.4 | 92.8 | 73.2 |
| Opus 5 | 77.0 | 88.0 | 94.3 | 71.9 |
| Sonnet 5 | 73.4 | 90.7 | 90.7 | 71.8 |
| Haiku 5.5 | 73.8 | 91.4 | 93.4 | 71.5 |
| Gemini 3.6 Flash | 75.6 | 91.0 | 48.2 | 54.9 |

### By docset

| docset | shape | GPT-5.5 | Haiku 5.5 | Opus 5 | Sonnet 5 | Gemini 3.6 Flash |
|---|---|---:|---:|---:|---:|---:|
| Cruise Itineraries | complex_layout | 77.6 ± 6.7 | 73.8 ± 4.2 | 77.0 ± 6.8 | 73.4 ± 4.6 | 75.6 ± 10.8 |
| NTSB Aviation Reports | form | 89.1 ± 6.7 | 94.3 ± 2.3 | 92.6 ± 6.6 | 93.0 ± 0.7 | 93.3 ± 2.1 |
| Safety Data Sheets | form | 83.7 ± 3.7 | 88.6 ± 8.4 | 83.3 ± 4.6 | 88.5 ± 10.8 | 88.8 ± 4.0 |
| Commercial Leases | hybrid_composite | 92.8 ± 5.5 | 93.4 ± 1.5 | 94.3 ± 3.0 | 90.7 ± 2.6 | 48.2 ± 0.6 (3/6 docs) |
| Master Services Agreements | prose_narrative | 87.5 ± 5.2 | 84.4 ± 5.7 | 80.1 ± 6.8 | 81.3 ± 1.9 | 63.4 ± 0.5 (4/6 docs) |
| Medical Notes (UNC) | prose_narrative | 67.4 ± 0.4 | 61.0 ± 6.0 | 73.2 ± 6.5 | 73.0 ± 3.4 | 63.5 ± 5.0 |
| Clinical Trial Protocols | prose_narrative | 42.8 ± 14.1 (4/6 docs) | 54.6 ± 0.8 | 54.1 ± 2.7 | 49.3 ± 1.9 | 11.6 ± 0.7 (1/6 docs) |
| Transport Agreements | prose_narrative | 95.6 ± 0.5 | 91.7 ± 6.4 | 87.2 ± 7.6 | 93.2 ± 5.7 | 78.3 ± 5.4 (5/6 docs) |
| Supplier Agreements | prose_narrative | 72.8 ± 9.8 (5/6 docs) | 66.1 ± 2.5 | 64.8 ± 1.6 | 62.3 ± 4.3 | 57.9 ± 0.4 (5/6 docs) |

## 3. Haiku 5.5 in both roles: thinking and document sampling

Three single-arm sweeps over the same 9 docsets, all Haiku 5.5 → Haiku 5.5.

| variant | quality (F1) | tag-blind recall | draw SD | tokens/doc | cost/doc | s/doc | spend |
|---|---:|---:|---:|---:|---:|---:|---:|
| Haiku 5.5 → Haiku 5.5, thinking off (fixed sampling) | **79.0** ± 9.2 | 89.5 | 4.8 | 141 k | $0.0222 | 89 | $3.60 |
| same, `generation.thinking: adaptive` | **78.2** ± 10.4 | 91.2 | 4.1 | 166 k | $0.0342 | 178 | $5.54 |
| same, thinking off, random `.pdf` sampling per draw | **75.4** ± 8.3 | 89.6 | 5.0 | 133 k | $0.0218 | 84 | $3.53 |

Adaptive extended thinking does not help Haiku 5.5: −0.8 points overall for 1.5× the cost and
2× the time per document, with large swings both ways per docset (+14 on Cruise Itineraries,
−9 on Clinical Trial Protocols, −8 on Safety Data Sheets). Tag-blind recall rises slightly
(89.5 → 91.2), so thinking finds a few more values and names them no better.

Random `.pdf` sampling per draw (`compass-corpus-3x6-haiku55`, seed 20260925) lands 3.6 points
below the fixed sample: the fixed sample takes gold-annotated documents first, and the random
one carries document variation as well as generation noise — visible as the 61.7 ± 14.9 on
Transport Agreements, where the fixed sample scores 94.1.

### By docset

| docset | shape | baseline | thinking adaptive | random sampling | pages/draw |
|---|---|---:|---:|---:|---:|
| Cruise Itineraries | complex_layout | 79.9 ± 8.9 | 94.3 ± 8.0 | 75.2 ± 3.8 | 36 |
| NTSB Aviation Reports | form | 92.4 ± 1.7 | 93.6 ± 3.7 | 93.3 ± 1.0 | 24 |
| Safety Data Sheets | form | 83.8 ± 9.7 | 76.1 ± 7.9 | 82.2 ± 3.2 | 54 |
| Commercial Leases | hybrid_composite | 93.1 ± 2.4 | 92.2 ± 0.3 | 89.7 ± 1.1 | 132 |
| Master Services Agreements | prose_narrative | 81.7 ± 2.0 | 79.8 ± 3.7 | 82.5 ± 5.7 | 49 |
| Medical Notes (UNC) | prose_narrative | 63.2 ± 5.7 | 68.1 ± 0.4 | 65.7 ± 4.9 | 35 |
| Clinical Trial Protocols | prose_narrative | 59.1 ± 5.4 | 49.9 ± 1.8 | 57.9 ± 5.2 | 178 |
| Transport Agreements | prose_narrative | 94.1 ± 3.2 | 87.7 ± 5.6 | 61.7 ± 14.9 | 80 |
| Supplier Agreements | prose_narrative | 63.3 ± 3.9 | 62.6 ± 5.6 | 70.6 ± 5.3 | 105 |

## 4. Gemini in both roles: labelers under a Gemini transcriber (`compass-label-gemini`)

Transcriber held at Gemini 3.6 Flash; six labelers, Gemini 3.6 Flash among them, so this is the
one sweep with a Google model in both roles. 54 cells, 972 documents, 112 M tokens. It is an
earlier run (September 2026, dgml @ `a4547da`) imported scoped to the bundled corpus, from
before Haiku 5.5: its Haiku labeler is **Haiku 4.5**, not 5.5.

| labeler (transcriber Gemini 3.6 Flash) | quality (F1) | tag-blind recall | draw SD | documents | tokens/doc | cost/doc | s/doc | spend |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GPT-5.5 | **83.4** ± 9.0 | 89.2 | 3.3 | 162 | 153 k | $1.390 | 453 | $225.19 |
| Haiku 4.5 | **82.9** ± 8.4 | 90.7 | 4.5 | 162 | 107 k | $0.221 | 226 | $35.87 |
| Opus 5 | **77.4** ± 11.0 | 86.1 | 6.2 | 162 | 136 k | $0.769 | 264 | $124.57 |
| Sonnet 5 | **77.2** ± 8.2 | 87.5 | 6.4 | 162 | 114 k | $0.327 | 216 | $52.92 |
| Gemini 3.6 Flash | **67.0** ± 7.9 | 87.1 | 6.4 | 162 | 102 k | $0.233 | 231 | $37.77 |
| Gemini 3.1 Flash Lite | **59.6** ± 8.1 | 84.7 | 8.0 | 162 | 78 k | $0.120 | 134 | $19.49 |

**Gemini end to end** (Gemini 3.6 Flash → Gemini 3.6 Flash) scores 67.0: 12 points below
Haiku 5.5 → Haiku 5.5 (79.0, §3) at 10× its cost per document. The bottom of the labeler
ladder is the same as in §1 — Gemini 3.6 Flash 16 points under the leader, Flash Lite 24 —
and tag-blind recall stays at 85–91 for every labeler, so the Gemini labelers lose on naming
again, not on finding values. Their weak spots are the `form` and `hybrid_composite` docsets
(Safety Data Sheets 46.2, Commercial Leases 61.6). At the top, GPT-5.5 and Haiku 4.5 lead and
Opus 5 and Sonnet 5 fall 5–6 points behind them, inside each other's bands.

In this run the Gemini 3.6 Flash transcriber produced DGML for all 162 documents; the 36
missing documents of §2 are specific to that October run, not to the model.

Against §1, the same labeler over Gemini rather than Haiku 5.5 transcriptions scores lower for
four of the five shared labelers (GPT-5.5 −2.1, Gemini 3.6 Flash −4.2, Sonnet 5 −5.8, Opus 5
−7.3; Flash Lite +2.9), winning on 2–5 of 9 docsets. The two runs are a month and a dgml
build apart, so read that as a direction, not a measured transcriber effect;
`compass-label-gemini-haiku55` measures it for the Haiku 5.5 labeler on the current build.

### By shape

| labeler | complex_layout (1) | form (2) | hybrid_composite (1) | prose_narrative (5) |
|---|---:|---:|---:|---:|
| GPT-5.5 | 94.8 | 96.0 | 96.0 | 73.6 |
| Haiku 4.5 | 92.7 | 93.0 | 93.3 | 74.8 |
| Opus 5 | 85.0 | 92.7 | 95.7 | 66.0 |
| Sonnet 5 | 74.6 | 89.2 | 92.4 | 70.0 |
| Gemini 3.6 Flash | 82.6 | 65.4 | 61.6 | 65.6 |
| Gemini 3.1 Flash Lite | 68.7 | 55.4 | 59.0 | 59.5 |

### By docset

| docset | shape | GPT-5.5 | Haiku 4.5 | Opus 5 | Sonnet 5 | Gemini 3.6 Flash | Gemini 3.1 Flash Lite |
|---|---|---:|---:|---:|---:|---:|---:|
| Cruise Itineraries | complex_layout | 94.8 ± 4.1 | 92.7 ± 7.3 | 85.0 ± 13.3 | 74.6 ± 14.6 | 82.6 ± 5.5 | 68.7 ± 10.1 |
| NTSB Aviation Reports | form | 96.9 ± 1.0 | 95.5 ± 0.7 | 92.1 ± 5.4 | 95.9 ± 2.7 | 84.6 ± 5.3 | 75.2 ± 21.0 |
| Safety Data Sheets | form | 95.2 ± 0.8 | 90.6 ± 2.9 | 93.3 ± 1.6 | 82.5 ± 15.2 | 46.2 ± 5.7 | 35.6 ± 0.4 |
| Commercial Leases | hybrid_composite | 96.0 ± 0.4 | 93.3 ± 3.0 | 95.7 ± 2.7 | 92.4 ± 1.3 | 61.6 ± 14.0 | 59.0 ± 7.7 |
| Master Services Agreements | prose_narrative | 84.1 ± 7.3 | 85.3 ± 6.2 | 75.2 ± 4.1 | 75.5 ± 5.4 | 72.0 ± 6.5 | 53.9 ± 4.6 |
| Medical Notes (UNC) | prose_narrative | 63.9 ± 4.2 | 73.8 ± 6.3 | 72.0 ± 6.2 | 71.8 ± 3.9 | 63.6 ± 5.5 | 69.6 ± 5.9 |
| Clinical Trial Protocols | prose_narrative | 64.5 ± 8.2 | 55.7 ± 3.9 | 43.8 ± 3.7 | 67.3 ± 8.7 | 65.2 ± 8.2 | 67.2 ± 1.1 |
| Transport Agreements | prose_narrative | 82.3 ± 2.8 | 80.9 ± 1.9 | 74.2 ± 5.7 | 79.6 ± 1.7 | 68.1 ± 6.7 | 56.9 ± 10.1 |
| Supplier Agreements | prose_narrative | 73.3 ± 1.3 | 78.3 ± 8.1 | 64.9 ± 12.9 | 55.6 ± 4.2 | 59.1 ± 0.2 | 50.1 ± 11.0 |

## 5. GPT-5.5 in both roles: transcribers under a GPT-5.5 labeler (`compass-transcribe-gpt55`)

Labeler held at GPT-5.5; five transcribers, GPT-5.5 among them, so this is the one sweep with
an OpenAI model in both roles. 45 cells, 809 documents, 85 M tokens. Like §4 it is an earlier
run (September–October 2026, dgml @ `ffdb38b`) imported scoped to the bundled corpus: its Haiku
transcriber is **Haiku 4.5**, not 5.5, and its Gemini 3.6 Flash cells are the Gemini → GPT-5.5
cells of §4 (adopted draws, identical numbers).

| transcriber (labeler GPT-5.5) | quality (F1) | tag-blind recall | draw SD | documents | tokens/doc | cost/doc | s/doc | spend | failed calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GPT-5.5 | **84.6** ± 9.6 | 91.9 | 1.8 | 161 † | 107 k | $1.363 | 331 | $219.41 | 29% |
| Haiku 4.5 | **84.3** ± 11.0 | 91.8 | 2.4 | 162 | 161 k | $1.378 | 427 | $223.23 | 0% |
| Gemini 3.6 Flash | **83.4** ± 9.0 | 89.2 | 3.3 | 162 | 153 k | $1.390 | 453 | $225.19 | 0% |
| Sonnet 5 ✗ | 16.8 ± 12.5 | 75.9 | 4.0 | 162 | 57 k | $0.245 | 165 | $39.64 | 44% |
| Opus 5 ✗ | 11.0 ± 4.0 | 74.5 | 0.4 | 162 | 47 k | $0.441 | 169 | $71.46 | 46% |

† One document missing in one draw of Clinical Trial Protocols. *Failed calls* is the
economics family's `llm_failure_rate`, the mean over the arm's cells.

✗ **Broken cells, not a measurement.** With Opus 5 or Sonnet 5 transcriptions, 44–46% of the
GPT-5.5 calls failed and the trees came back essentially unlabelled: quality 4–23 on every
docset but one, tag-blind recall still 75, a third to a half of the tokens of the working arms.
These cells measure the failure, not the models; they stay in `cells.csv` and are left out of
the readings below. A re-run on the current build is the way to fill them.

**OpenAI end to end** (GPT-5.5 → GPT-5.5) scores 84.6, with the lowest draw-to-draw noise of
any arm here (1.8). That is within a point of Haiku 5.5 → GPT-5.5 (85.6, §1; −1.0 paired,
ahead on 3 of 9 docsets) at about the same cost per document ($1.36 against $1.42), so
GPT-5.5 as transcriber buys nothing over Haiku 5.5 — the same reading as §2, now under a
GPT-5.5 labeler. Against Haiku 5.5 in both roles (79.0, §3) it is +5.6 points for 61× the cost
per document. Its GPT-5.5 transcriber also logged 29% failed calls without losing documents
or quality.

### By shape

| transcriber | complex_layout (1) | form (2) | hybrid_composite (1) | prose_narrative (5) |
|---|---:|---:|---:|---:|
| GPT-5.5 | 89.4 | 94.7 | 96.3 | 77.2 |
| Haiku 4.5 | 96.4 | 93.4 | 95.0 | 76.2 |
| Gemini 3.6 Flash | 94.8 | 96.0 | 96.0 | 73.6 |
| Sonnet 5 ✗ | 64.0 | 4.4 | 8.2 | 14.1 |
| Opus 5 ✗ | 11.8 | 4.0 | 8.3 | 14.3 |

### By docset

| docset | shape | GPT-5.5 | Haiku 4.5 | Gemini 3.6 Flash | Sonnet 5 ✗ | Opus 5 ✗ |
|---|---|---:|---:|---:|---:|---:|
| Cruise Itineraries | complex_layout | 89.4 ± 1.6 | 96.4 ± 1.3 | 94.8 ± 4.1 | 64.0 ± 32.1 | 11.8 ± 0.2 |
| NTSB Aviation Reports | form | 94.8 ± 0.9 | 97.3 ± 0.6 | 96.9 ± 1.0 | 4.7 ± 0.2 | 4.2 ± 0.1 |
| Safety Data Sheets | form | 94.7 ± 1.7 | 89.6 ± 6.2 | 95.2 ± 0.8 | 4.2 ± 0.1 | 3.7 ± 0.3 |
| Commercial Leases | hybrid_composite | 96.3 ± 0.2 | 95.0 ± 0.4 | 96.0 ± 0.4 | 8.2 ± 0.2 | 8.3 ± 0.1 |
| Master Services Agreements | prose_narrative | 84.0 ± 0.5 | 90.4 ± 1.3 | 84.1 ± 7.3 | 11.5 ± 0.6 | 11.5 ± 0.3 |
| Medical Notes (UNC) | prose_narrative | 74.2 ± 2.6 | 65.8 ± 5.8 | 63.9 ± 4.2 | 23.0 ± 1.3 | 23.3 ± 0.7 |
| Clinical Trial Protocols | prose_narrative | 52.5 ± 1.9 † | 49.5 ± 0.4 | 64.5 ± 8.2 | 17.3 ± 0.3 | 14.1 ± 1.2 |
| Transport Agreements | prose_narrative | 95.3 ± 0.1 | 95.5 ± 0.4 | 82.3 ± 2.8 | 14.2 ± 0.3 | 14.2 ± 0.1 |
| Supplier Agreements | prose_narrative | 79.7 ± 6.6 | 79.7 ± 5.1 | 73.3 ± 1.3 | 4.4 ± 0.5 | 8.3 ± 0.3 |

## 6. Cost and tokens

| pipeline | quality | tokens/doc | cost/doc | relative cost |
|---|---:|---:|---:|---:|
| Haiku 5.5 → Haiku 5.5 | 79.0 | 141 k | $0.022 | 1× |
| Haiku 5.5 → Sonnet 5 | 83.1 | 143 k | $0.275 | 12× |
| Haiku 5.5 → Opus 5 | 84.6 | 159 k | $0.790 | 36× |
| Haiku 5.5 → GPT-5.5 | 85.6 | 186 k | $1.422 | 64× |
| Sonnet 5 → Haiku 5.5 | 78.3 | 133 k | $0.199 | 9× |
| Opus 5 → Haiku 5.5 | 78.5 | 129 k | $0.455 | 20× |
| GPT-5.5 → Haiku 5.5 | 78.8 | 106 k | $0.401 | 18× |
| Gemini 3.6 Flash → Haiku 5.5 | 64.5 | 107 k | $0.108 | 5× |
| Haiku 5.5 → Gemini 3.6 Flash | 71.2 | 122 k | $0.133 | 6× |
| Haiku 5.5 → Gemini 3.1 Flash Lite | 56.7 | 100 k | $0.025 | 1.1× |
| Gemini 3.6 Flash → Gemini 3.6 Flash ‡ | 67.0 | 102 k | $0.233 | 10× |
| Gemini 3.6 Flash → Gemini 3.1 Flash Lite ‡ | 59.6 | 78 k | $0.120 | 5× |
| Gemini 3.6 Flash → GPT-5.5 ‡ | 83.4 | 153 k | $1.390 | 63× |
| GPT-5.5 → GPT-5.5 ‡ | 84.6 | 107 k | $1.363 | 61× |

‡ From `compass-label-gemini` (§4) or `compass-transcribe-gpt55` (§5), earlier runs on an
older dgml build.

Token volume varies by less than 2× across pipelines (100–186 k per document); the 64× cost
range is price per token. Putting a frontier model in the labeler slot costs about twice what
putting it in the transcriber slot does (Opus 5: +$0.77 per document as labeler, +$0.43 as
transcriber), and only the labeler slot buys quality.

Per docset the cost range is wider. On Commercial Leases (22 pages per document), the
transcriber sweep (`compass-transcribe-haiku55`, `cells.csv`) gives:

| pipeline | quality | draw SD | cost/doc | relative cost |
|---|---:|---:|---:|---:|
| Haiku 5.5 → Haiku 5.5 | 93.4 | 1.5 | $0.045 | 1× |
| Opus 5 → Haiku 5.5 | 94.3 | 3.0 | $1.330 | 30× |

The best-scoring pipeline of the sweep on this docset costs 30× the cheapest for 0.9 points,
less than either draw SD.

![Quality against cost per document for each pipeline above: the labeler buys quality as cost rises, the transcriber does not](../figures/quality_cost.svg)

The table above as a figure, with ± 2 SE bars between docsets (`dgc figure` redraws it from
`results/reference/`).

## 7. What the bundled corpus says

1. **Spend on the labeler, not the transcriber.** Transcriber choice among Haiku 5.5, Sonnet 5,
   Opus 5 and GPT-5.5 changes quality by half a point; labeler choice changes it by 6.6 points
   between Haiku 5.5 and GPT-5.5, and by 29 down to Flash Lite.
2. **Haiku 5.5 as transcriber is free quality.** Same quality as the frontier transcribers at
   $0.02–0.03 per document of transcription. On Commercial Leases, Haiku 5.5 in both roles
   scores 93.4 at $0.045 per document against 94.3 at $1.33 for the sweep's best (§6): 30×
   cheaper.
3. **The labeler ladder is Haiku 5.5 (79) → Sonnet 5 (83) → Opus 5 (85) → GPT-5.5 (86)**, at
   $0.02 → $0.28 → $0.79 → $1.42 per document. Sonnet 5 buys most of the gain for a tenth of the
   top price. The three frontier labelers are statistically contested on this corpus.
4. **Names, not values, are what separates models.** Tag-blind recall is 86–93 for every
   Anthropic/OpenAI pipeline and for Gemini as labeler; the quality spread is field naming.
   Gemini 3.6 Flash as *transcriber* is the one case where values themselves are lost.
5. **Thinking does not pay for Haiku 5.5** in either slot measured here.
6. **The hard docsets are hard for everyone.** Clinical Trial Protocols (50–76), Medical Notes
   (61–77) and Supplier Agreements (55–84) hold every pipeline below 85 (leaving aside the
   Gemini transcriber's one-document cell); NTSB Reports and Commercial Leases are above 90
   for any Anthropic/OpenAI pair, Safety Data Sheets 83–93.
7. **Gemini end to end is not competitive here.** Gemini 3.6 Flash in both roles scores 67,
   12 points under Haiku 5.5 in both roles at 10× the cost per document; under either
   transcriber the two Gemini labelers are the two lowest.
8. **OpenAI end to end matches, it does not beat, a cheap transcriber.** GPT-5.5 in both roles
   scores 84.6, a point under Haiku 5.5 → GPT-5.5 at the same cost; the GPT-5.5 labeler is
   what earns the score.

Caveats: nine docsets, six documents each; four shapes of which only `prose_narrative` has
enough docsets for a between-docset band; one run per sweep, so re-runs will land within a few
points rather than on these numbers; and Gemini 3.6 Flash's transcriber figure excludes the 22%
of documents it did not produce; §4 and §5 come from an earlier dgml build than the other
sweeps; and §5's Opus 5 and Sonnet 5 cells are broken runs, not results.

## Provenance

| sweep | run | cells | documents | tokens | cells' cost | run spend | corpus hash | dgml |
|---|---|---:|---:|---:|---:|---:|---|---|
| `compass-transcribe-haiku55` | `20261008-175618-25ef2d78` | 45 | 767 | 95.3 M | $185.22 | $337.06 | `2a590b16a0b17202` | dgml 0.1.1 @ `d6e55f6` |
| `compass-label-haiku55` | `20261014-022456-37998681` | 54 | 972 | 137.9 M | $432.23 | $583.31 | `2a590b16a0b17202` | dgml 0.1.1 @ `d6e55f6` |
| `compass-corpus-3x6-haiku55` | `20261008-140547-4fe5464b` | 9 | 162 | 21.6 M | $3.53 | $5.94 | `d9607f9b518b706a` | dgml 0.1.1 @ `ffdb38b` |
| `compass-baseline-haiku55` | `20261008-154627-56e22032` | 9 | 162 | 22.8 M | $3.60 | $6.09 | `b75b023d338b84b9` | dgml 0.1.1 @ `d6e55f6` |
| `compass-baseline-haiku55-think` | `20261013-203701-d87d278e` | 9 | 162 | 26.8 M | $5.54 | $9.49 | `2a590b16a0b17202` | dgml 0.1.1 @ `d6e55f6` |
| `compass-label-gemini` | `20260925-200002-labelgm3` | 54 | 972 | 111.9 M | $495.80 | $745.47 | `c63488a3458a1141` | dgml 0.1.1 @ `a4547da` |
| `compass-transcribe-gpt55` | `20260930-200000-trgpt55` | 45 | 809 | 85.0 M | $778.92 | $1,220.28 | `c63488a3458a1141` | dgml 0.1.1 @ `ffdb38b` |

The runs were executed on a larger corpus and imported scoped to the bundled docsets, so *run
spend* includes cells outside this corpus; *cells' cost* is what these cells' draws cost. All
runs: dgml 0.1.1, dgml-compass 0.1.0, Python 3.12. Two sweeps in `specs/` have no
reference yet — `compass-label-gemini-haiku55` and `compass-transcribe-gpt55-haiku55` — since no
run with Haiku 5.5 in those pairings exists (plan ≈ $14 and $7).

Files per sweep in `results/reference/<spec>/`: `cells.csv` (every number above is
derived from it), `summary.json`, `compass_grid.csv`, `validity.json`, and the `dgc report`
tables `by_shape.csv`, `best_by_shape.csv`, `gates.csv`, `cost_by_model.csv`, `failures.csv`.
`dgc reference report` rebuilds the index over them.
