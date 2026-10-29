# Data provenance and terms

The data under `data/` and `results/reference/` comes from the
sources below, each with its own terms. [data/README.md](data/README.md) gives the provenance file by
file, with the URLs and the exact revisions used.

> **Status: rows marked TO CONFIRM must be verified before dgml-compass is made public.**
> Nothing here is a licence grant until that column says so.

| what | where it comes from | terms |
|---|---|---|
| `data/pdf/<split>/<key>.pdf` | the filing's primary 10-K document on SEC EDGAR (`edgar_index` in `data/manifest.json`), the HTML rendered to PDF with headless Chrome, one page of the filing's own pagination per sheet | US government filings: public domain |
| `data/docs/dgml/` | DGML produced from those PDFs by the Docugami DGML converter (Pass A, Claude Haiku 5.5; dgml-io/dgml PR #267: the test split at the commit `scripts/regenerate_dgml.sh` pins, the dev split at an earlier commit of the same PR with the same Pass A code) | Docugami output — **TO CONFIRM** |
| `data/questions.json` (question, gold answer) | DocFinQA (Reddy et al., 2024), https://huggingface.co/datasets/kensho/DocFinQA: dev split for `dev`, test split for `test` | MIT (dataset card) |
| `data/gold_computations.json` | FinQA annotations (Chen et al., 2021), https://github.com/czyssrs/FinQA, looked up by each question's `finqa_id` | MIT, notice in `data/LICENSE-FinQA` |
| `results/reference/` | answers produced by DeepSeek-V4-Flash-0731 on Azure AI Foundry, October 2026 | model output; provider terms apply — **TO CONFIRM** |

Built locally, not shipped (`scripts/build_renderings.sh`, converter versions pinned there): the DGML
element outline, DGML compact, and the four markdown renderings of the PDFs.

Not included: the full DocFinQA and FinQA files (only the 233 questions used, and only the fields
needed); the raw converter DGML with grounding coordinates and namespaces (the shipped form has the
same words, `python -m dgml_reasoning.dgml_outline --import` is the conversion); the DGML converter itself
(`scripts/regenerate_dgml.sh` clones it at the pinned commit).

## Citations

- Reddy, V. et al. *DocFinQA: A Long-Context Financial Reasoning Dataset.* ACL 2024. https://arxiv.org/abs/2401.06915
- Chen, Z. et al. *FinQA: A Dataset of Numerical Reasoning over Financial Data.* EMNLP 2021. https://arxiv.org/abs/2109.00122
