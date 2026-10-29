# Where the data comes from

Everything under `data/` was taken or derived from the public sources below. No file is a full copy of
a dataset: only the 30 filings and 233 questions the benchmark uses, and only the fields it needs.

## Sources

| source | what | URL | revision used | licence |
|---|---|---|---|---|
| **DocFinQA** (Reddy et al., ACL 2024) | the questions and their gold answers, and which filing each one is asked on | dataset: https://huggingface.co/datasets/kensho/DocFinQA, files `dev.json` (dev split) and `test.json` (test split); paper: https://arxiv.org/abs/2401.06915 | commit `64ebaff62f692495bcc182f45cf9a9606251b19b` (2024-11-19) | MIT, as declared in the dataset card |
| **FinQA** (Chen et al., EMNLP 2021) | the gold program behind each answer (the computation and its operands) | https://github.com/czyssrs/FinQA, files `dataset/dev.json` and `dataset/test.json`; paper: https://arxiv.org/abs/2109.00122 | commit `0f16e2867befa6840783e58be38c9efb9229d742` | MIT, copyright (c) 2021 Zhiyu Chen; the full text is in [LICENSE-FinQA](LICENSE-FinQA) |
| **SEC EDGAR** | the filings themselves: each 10-K's primary document | https://www.sec.gov/edgar, one index page per filing in `manifest.json` (`edgar_index`) | as filed | US government filings, public domain |

## File by file

| file | contents | taken from |
|---|---|---|
| `questions.json` | per question: `question` and `gold` verbatim from DocFinQA's `Question` and `Answer` (checked for all 233); `docfinqa_row` = the record's index in DocFinQA's `dev.json` (dev split) or `test.json` (test split), whichever its `split` names; `finqa_id` = the id of the FinQA record with the same question text in FinQA's `dev.json` or `test.json` (DocFinQA does not carry it; checked for all 233), `source_page` the page that id names; `key`, `ticker`, `fiscal_year`, `company`, `edgar_index` identify the filing | DocFinQA and FinQA, plus the filing's EDGAR metadata |
| `gold_computations.json` | per question: the FinQA `program` found by `finqa_id` (what the computed reading of the score evaluates) and the table rows it reads (`evidence_rows`, `n_evidence_rows`) | FinQA |
| `manifest.json` | per filing: ticker, fiscal year, company, CIK, accession number, EDGAR index URL, number of questions, split | SEC EDGAR, matched to DocFinQA by filing |
| `pdf/<split>/<key>.pdf` | the filing's primary 10-K HTML from EDGAR, rendered to PDF with headless Chrome, one page of the filing's own pagination per sheet | SEC EDGAR |
| `docs/dgml/<key>.dgml.xml` | DGML produced from that PDF by the Docugami DGML converter (see [DATA.md](../DATA.md) and `scripts/regenerate_dgml.sh`) | derived from the PDF |

Not taken: DocFinQA's `Context` field (its own text of each filing, up to several hundred thousand words)
and its `Program` field (the gold program comes from FinQA instead), and every other question, record
and field of either dataset.

## How the filings were chosen

- **Dev split (`dev`)**: 15 filings of DocFinQA's dev split with their 122 questions.
- **Test split (`test`)**: 15 filings of DocFinQA's test split chosen to match the dev split in length, with their
  111 questions. They were answered only after every choice (renderings, prompts, settings) was made on the
  dev split.

The key of a filing is `<TICKER>_<FISCAL YEAR>_<ACCESSION NUMBER>`.

## Citing

- Reddy, V., Koncel-Kedziorski, R., Lai, V. D., Krumdick, M., Lovering, C., Tanner, C. *DocFinQA: A
  Long-Context Financial Reasoning Dataset.* ACL 2024. https://arxiv.org/abs/2401.06915
- Chen, Z., Chen, W., Smiley, C., Shah, S., Borova, I., Langdon, D., Moussa, R., Beane, M., Huang, T.-H.,
  Routledge, B., Wang, W. Y. *FinQA: A Dataset of Numerical Reasoning over Financial Data.* EMNLP 2021.
  https://arxiv.org/abs/2109.00122
