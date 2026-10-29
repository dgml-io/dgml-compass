# Metrics

The metric definitions Model Compass scores with. One record is
written per (cell, docset, draw, family) to `metrics/<cell_id>.jsonl`. **Absent is not
zero:** a metric that cannot be computed is named in `absent` and has no value. Scales
differ by family: extraction and reference-free are 0–100; tree scores are 0–1 (ARI and tau
reach −1) while its counts, ratios and entropies are raw; economics is in units.

## 1. Extraction (`metrics/extraction.py`): agreement with `*.ref.json`

**Normalisation.** Values are compared after `normalize_text`, which is the same
normalisation everywhere in this family:
- NFKC, then lower-case;
- tokens of `\w+(?:[.,]\w+)*`, so `1,250.00` stays one token;
- punctuation and `•` deleted, tokens joined by single spaces;
- the sentinel `empty` passes through unchanged.

A gold value's `#N` suffix is provenance only and is never compared.

**Keying.** The key is `file_id__label`.
- **positional**: `value#index`, order-sensitive. This is the headline scheme.
- **occurrence**: a multiset; repeated values get `#2`, `#3`. This gives the `*_relaxed_f1`
  scores.

A missing pair is the sentinel on both sides. Predictions are padded with the sentinel over
the docset-wide union of predicted tags (DECISIONS 0014).

**Predictions** come from the generated DGML:
- every text-bearing element becomes a value under every path suffix (`C`, `B+C`, `A+B+C`);
- a list item is also offered without its `lim` marker (`+nolim`);
- inline-only composites count as one value;
- `dg:extraction` content is split off first.

**Overlap** for one value pair is the longest common contiguous token run, divided by the
predicted length (precision) or the gold length (recall). For a set, it is **greedy**: the sum
of each prediction's best (precision mass) and each gold value's best (recall mass) (DECISIONS 0006).

**Micro scores.**
- `P = mass_or_correct / Σ max(|pred|, 1)` and `R = … / Σ max(|gold|, 1)`; F1 is harmonic.
- An empty gold matched by an empty prediction counts as correct.
- `em` counts exact key matches; `*_aligned_f1` uses an order-preserving LCS (EM) or a
  non-crossing alignment (overlap). The aligned scores are report-only.

**Tag choice.** Each gold label picks the predicted tag with the best `em_f1`. If none is
positive it picks the best `overlap_f1`. Ties go to the first candidate.
- `individual_*` chooses per document, in extractor order.
- `global_*` chooses once per docset, in sorted order. It is usually, not always, lower.

**Emitted names** (27 in `ALL_EXTRACTION_METRICS`), plus extras:
- `{individual,global}_{em,overlap}_{precision,recall,f1}`, `…_aligned_f1`, `…_relaxed_f1`.
- `value_only_*` pools values per document, ignoring tag names. Read the recall: precision is
  dominated by fields gold never annotates.
- `naming_penalty = value_only_overlap_recall − individual_overlap_recall`. It is not clamped.
- `per_type.<ref type>.<score>` averages the per-label global scores by gold type.
- `complex_*`: instance scores against `complex_ref.json`, one-to-one (Hungarian) matching.
  `[]` means verified absent, `null` means skipped. Known defect 1 in DECISIONS applies.
- `missing_dgml_rate` is a fraction 0–1 here (known defect 4).

Gold covers only the documents a draw generated. Under random sampling the docset is narrowed
to the draw's sidecar. A docset without gold gets a record with `no_gold` and no values.

## 2. Reference-free (`metrics/reference_free.py`): no gold needed

The `dg:` frame is transparent here: it is not counted and not an ancestor (DECISIONS 0009).

**Consistency** is computed over the documents' sets of semantic tags.
- `vocabulary_reuse_rate`: % of tags used in at least 2 documents. `singleton_rate = 100 − reuse`.
- `mean_pairwise_jaccard` and `tag_inflation`: % of the vocabulary first seen in the last
  document. Both are absent for a single-document docset (DECISIONS 0008).
- `synonym_rate`: redundant names in complete-link clusters. A pair is a candidate when it
  shares a token and has token Jaccard ≥ 0.6 (or character ratio ≥ 0.92). It is vetoed by
  document co-occurrence > 0.5, or by TF-IDF content cosine < 0.6.
- `consistency_score = clamp(0.4·reuse + 0.3·jaccard + 0.15·(100−inflation) + 0.15·(100−synonym))`.

**Grounding** checks each text leaf's `dg:origin` boxes against the OCR words whose centre
falls inside them.
- `grounded_leaf_rate`, `origin_text_match` (mean % of leaf words found);
- `out_of_bounds_rate` (2% tolerance), `degenerate_box_rate`.

**Structure.**
- `dual_role_tags`: tags used both as container and as leaf. `…_attr` is the same by the
  `structure` attribute.
- `empty_containers`: has `structure`, no children (frame children count) and no text.
- `self_nesting`, `self_nesting_direct`.
- `defects_per_1k_elements = 1000·(dual + empty + nesting)/elements`.
- `structural_score = max(0, 100·(1 − rate/400))`.

## 3. Economics (`metrics/economics.py`): from `usage.jsonl` and the output

Billed tokens and estimated tokens (chars/4, prefixed `est_`) never mix.

- **Cost:** `cost_usd`, `cost_per_doc`, `cost_per_page`, `f1_per_dollar` (uses
  `individual_overlap_f1`), `f1_per_1k_tokens`, `tokens_per_doc`, `tokens_per_page`.
- **Size:**
  - `expansion_x = dgml_chars / source_chars`, where source chars are Σ(word length + 1) over
    the OCR pages;
  - `origin_overhead_pct`, `chars_per_element`, `est_dgml_tokens`.
- **Reliability and latency:** `llm_failure_rate`, `missing_dgml_rate` (0–100 here),
  `seconds_per_doc`, `seconds_per_page`, `call_p50_s`, `call_p95_s` (nearest rank).
- **`cost_partial`** is set when some spend can't be tied to a document, or a call is
  unpriced. It is a warning on the record and gates comparisons.
- **Role prices** (additive):
  - `cost_per_page_transcribe` and `cost_per_page_label` are `cost_usd ×
    (role's share of usage cost) / pages`. Transcribe calls go to the transcriber; label and
    links calls go to the labeler.
  - `cost_per_page_pipeline = cost_per_page`, emitted only when one model fills both slots.

## 4. Tree (`metrics/tree/`): prediction against the gold DGML

Both trees are flattened to reading-order token streams. Each token carries its chunk: the
text-bearing element, its depth, its ancestors, and its boxes. One `SequenceMatcher`
alignment feeds every metric.

- **`alignable_fraction = 2·matched/(n_gold + n_pred)`.** A document pair below 0.5 is
  counted (`n_unalignable`) and left out of every other mean.
- **Segmentation:** `seg_ari`, `coseg_agreement`, `boundary_f1`, `chunk_jaccard_bag`.
- **Labelling:** a token's tag is its nearest semantic element.
  - `label_ari`, `bcubed_{precision,recall,f1}`, with gold as the reference. Low precision
    means merged; low recall means split.
  - `tag_exact_agreement`, `tag_vocab_jaccard`, `direct_label_rate_{gold,pred}`.
- **Shape:** `depth_match`, `group_agreement`, `lca_depth_{match,mae}`, `path_suffix_cosine`,
  `struct_path_cosine`, `leaf_order_tau`. Pairwise measures use at most 400 chunks, tau at
  most 600.
- **Grounding:** `origin_iou_{mean,gt50}`, `origin_page_match`, `grounded_rate_{gold,pred}`.
- **Guards:** count, element and token ratios, and tag entropies.
- **Edits, prediction → gold:**
  - Zhang-Shasha over elements, with frames named `dg:*`. `teds` charges names plus own-text
    distance, `teds_struct` names only, `teds_shape` neither; each is `1 − TED/max(size)`.
  - `tree_{ins,del,ren}` are the minimal-rename script of `teds_struct`.
    `tree_edit_rate = TED/|gold|`.
  - The TED metrics are skipped above 2,500 elements per side.
  - `text_{ins,del,sub,wer}` are word operations over the alignment.
- **Level text,** for depth d ∈ {1, 2, 3}:
  - segments are the text under each element at depth d, matched one-to-one greedily by token
    Dice;
  - `level_{precision,recall,f1}_dN` count matches with Dice ≥ 0.5;
  - also `level_text_dice_dN`, `level_exact_dN` and `level_count_ratio_dN`.

Docset values are means over the alignable document pairs. `alignable_fraction` and
`token_len_ratio` are averaged over every compared pair.

## 5. Aggregation (`aggregate/`) and statistics (`aggregate/stats.py`)

- **Grouping key:** (unit, shape, doc type, schema tier, config tier, model). The model is part
  of the key (DECISIONS 0010); other swept settings (e.g. `window_size`) are not, so their
  rows pool. The model is the label model when set, else the generation model;
  known defect 7 in DECISIONS applies to transcriber sweeps.
- **Averaging:** draws are averaged within a docset, then docsets are averaged unweighted.
  `sd_between_docsets` uses ddof=1, and the band is ±2·SE. `mean_quality` (default
  `individual_overlap_f1`) is blank when nothing was scored.
- **Comparability gates** (in `validity.json`): `corpus_hash_mismatch`,
  `dgml_version_mismatch`, `repo_sha_mismatch`, `too_few_docsets` (default 3),
  `single_docset`, `mixed_cost_partial`, `missing_draws`, `partial_outcome`, `no_quality`.
- **`compass_grid.csv`:** one row per grouping key, columns in this fixed order:
  - key: `unit` (`docset`), `shape`, `doc_type` (equal to `shape`), `schema_tier`,
    `config_tier` (model family slug from the model id, e.g. `haiku`, `flash-lite`), `model`;
  - `mean_quality`, `tag_blind_recall` (`value_only_overlap_recall`, averaged the same way),
    `naming_gap = tag_blind_recall − mean_quality`, `sd_between_docsets`, `band_2se`;
  - `n_docsets`, `n_draws` (most draws any docset has), `single_docset`;
  - `cost_per_doc_usd` (mean over economics records), `cost_partial` (any record flagged),
    `usage_present` (every economics record had `usage.jsonl`);
  - `comparable`, `validity_warnings` (gate codes), `pooled_mean_quality` (mean over every
    record, not docset means; shown only so the difference is visible), `n_documents` (known
    defect 8), `n_cells`, `run_id`, `axes_json` (the first cell's settings);
  - `cost_per_page_{transcribe,label,pipeline}_usd`.
- **Compare:** gates first, then a paired docset bootstrap (10,000 resamples, seed 0) of the
  mean delta (candidate − baseline) with a 95% interval, and a Wilcoxon (zsplit) p-value. The
  verdict comes from the interval: `improved` if it is above 0, `regressed` if below,
  `no_change` otherwise; a gated row is `not_comparable` and has no effect size.
