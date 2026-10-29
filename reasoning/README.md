# Reasoning and provenance: DGML vs PDF markdown

`reasoning/` in dgml-compass: a project separate from `models/` (Model Compass), with its own
`pyproject.toml`, data, reference answers and tests. It installs the command `dgr`; run every command
below from this folder.

**When a model answers a question about a financial filing, can you trace each figure it used back to
the one place in the filing it came from?** With DGML, about twice as often as with markdown converted
from the same PDF, at the same accuracy.

The benchmark gives a model 30 SEC 10-K filings and 233 DocFinQA questions, once as DGML and once as
markdown produced from the same PDFs by four different converters. The model answers and cites every
figure it uses as `value | element`. A script then follows each citation back into the full filing.

## The result

A citation is **traceable** when it leads to exactly one place in the filing that holds the figure.
DeepSeek-V4-Flash, temperature 0, program prompt (see [The prompts](#the-prompts)).

| the model reads | traceable citations, dev | traceable citations, test | correct, dev / test |
|---|---:|---:|---:|
| **DGML navigation, path citations + compact fallback** | **82%** | **85%** | 79 / 76 |
| **DGML navigation + compact fallback** | **64%** | **74%** | 79 / 75 |
| **DGML compact, full read** | **56%** | **67%** | 83 / 78 |
| **DGML, full read** | **61%** | **61%** | 78 / 76 |
| PDF markdown, pymupdf4llm 2.0 (layout models) | 31% | 31% | 80 / 77 |
| PDF markdown, three model-free converters | 16-29% | 21-33% | 79-81 / 78-79 |
| no citation: searching the number in the filing | 33-34% | 39-40% | |

The last row is the share of cited figures that occur exactly once in the filing (full reads; 15% on
the pdfplumber text, which repeats figures).

![Correct answers against traceable citations for each system, dev and test splits: the four DGML systems sit at 56-85% traceable, the four PDF-markdown converters at 16-33%, across the same accuracy range](figures/accuracy_traceable.svg)

Each segment is one system, from its dev point (blue) to its test point (orange); filled points are DGML,
hollow points markdown from the same PDF. `dgr figure` redraws it from the shipped answers.

- **A DGML citation is traceable about twice as often.** The model copies an element name that exists
  in the filing. Asked for the change in HII's unamortized debt issuance costs, it cites
  `$8 million | DebtIssuanceCostAmount`: one element, in a filing where the number 8 appears 91 times
  ("$8 million" 10 times).
- **Citing the element's path makes it more traceable still.** A name can repeat in a filing; a path
  (`value | /chunk/.../DebtIssuanceCostAmount`) separates the elements that share it. DGML navigation
  with path citations reaches 82-85%, at the same accuracy.
- **A markdown citation is no more traceable than searching the number.** Most markdown citations that
  fail name a label that is not in the filing: a paraphrased row label, or a section heading far from
  the figure. For the same question the markdown answer cites `Note 14: Debt - unamortized debt
  issuance costs associated with...`, a heading that leads to no place for one figure and five for the
  other. Both answers are right (37.5%); only one can be checked.
- **The same holds for the figures the gold answer uses:** 65-84% for DGML against 32-33% for PDF
  markdown with pymupdf4llm 2.0 (19-37% across the four converters).
- **At the same accuracy.** Every full read scores within a few points, on both splits.

## Accuracy and cost

Correct answers (prec+computed, see [Scoring](#scoring)) and gross tokens (all input and output tokens
of every call, retries included). Program prompt.

| | dev (122 q): correct | tokens | correct / 1M | traceable / 1M | test (111 q): correct | tokens | correct / 1M | traceable / 1M |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| DGML navigation, path citations + compact fallback | 79 | 7.0 M | 11.3 | **31.2** | 76 | 6.6 M | 11.6 | **31.2** |
| DGML navigation + compact fallback | 79 | 6.3 M | **12.5** | 26.9 | 75 | 6.3 M | **11.9** | 28.3 |
| DGML compact, full read | **83** | 14.8 M | 5.6 | 10.3 | **78** | 13.6 M | 5.7 | 12.0 |
| DGML, full read | 78 | 22.8 M | 3.4 | 6.8 | 76 | 20.1 M | 3.8 | 7.4 |
| PDF markdown, pymupdf4llm 2.0, full read | 80 | 12.1 M | 6.6 | 6.8 | 77 | 11.0 M | 7.0 | 6.5 |
| PDF markdown, pymupdf4llm 0.0.27, full read | 81 | 11.6 M | 7.0 | 6.5 | 78 | 11.5 M | 6.8 | 6.5 |
| PDF markdown, pdfplumber, full read | 79 | 13.6 M | 5.8 | 3.2 | 79 | 13.4 M | 5.9 | 3.6 |
| PDF text, poppler, full read | 81 | 12.2 M | 6.6 | 6.2 | 79 | 10.8 M | 7.3 | 7.2 |

- **DGML navigation + compact fallback** is the most efficient: about half the tokens of PDF markdown,
  almost twice its correct answers per million tokens, about four times its traceable citations per
  million tokens, three to four points from the best accuracy. The model reads the filing's element outline,
  picks up to five elements, and answers from them (each pick with three sibling elements on each
  side); when it answers NOT_FOUND (12 and 18 questions), it reads the whole filing in DGML compact.
  Its tokens include an estimate for 31 of 466 navigation answers whose first call was retried and
  not recorded (the retry's prompt plus a first call at its 16,000-token cap).
- **DGML navigation, path citations** is the same system with every figure cited by its element path,
  and call 2 asked again, as a full read is, when it spends its whole budget without an answer: the most
  traceable citations per million tokens, at the same accuracy, for 4-11% more tokens (NOT_FOUND on 10
  and 17 questions).
- **DGML compact, full read** is the most accurate, for about 20% more tokens than PDF markdown.
- **DGML, full read** costs the most: it exceeds the model's 240k-token budget on 7 dev and 13 test
  questions, which it then answers from a cut filing. DGML compact carries the same filing in about
  40% fewer tokens and fits on every filing.
- Run-to-run spread is one to two points (two runs of DGML compact on the test split: 76 and 77 with
  the plain prompt, 78 and 78 with the program prompt).

### With and without the citing prompt

Correct answers, full read. The plain prompt asks only for the answer; the program prompt also asks for
the cited figures and the computation, which the benchmark executes.

| | dev, plain | dev, program | test, plain | test, program |
|---|---:|---:|---:|---:|
| DGML navigation + compact fallback | -- | 79 | -- | 75 |
| DGML compact, full read | 75 | **83** | 76 | **78** |
| DGML, full read | 72 | 78 | 74 | 76 |
| PDF markdown, pymupdf4llm 2.0 | 75 | 80 | 77 | 77 |
| PDF markdown, pymupdf4llm 0.0.27 | 77 | 81 | 75 | 78 |
| PDF markdown, pdfplumber | 75 | 79 | 77 | 79 |
| PDF text, poppler | 76 | 81 | 74 | 79 |

Every rendering scores within a few points under both prompts, so the equal accuracy is not an effect
of the citing prompt. Asking for the cited figures and the computation lifts every rendering by 4 to 8
points on the dev split and by 0 to 5 on the test split; executing the program changes little (the
model's own answer and the executed value score alike on nearly every question).

## How traceability is measured

`dgr provenance`, offline, over the answers in `results/reference/`. For every cited
`value | element`, against the full filing:

- **DGML, path cited:** the innermost elements whose path, without indices, ends with the cited path and
  whose text holds the value (a tag the model repeats, as the excerpt label and its first element, counts once).
- **DGML:** the innermost elements whose name is the cited name and whose text holds the value. DGML
  compact and DGML navigation carry the same element names, so their citations are resolved in the DGML
  too, the document an auditor traces a figure in (`--compact-as-text` checks DGML compact as plain
  text instead: 41% and 49%).
- **Markdown:** the places where the cited label is followed within 400 characters (one table row) by
  the value, trying the label as written, without parentheses, and without a trailing year.
- **Searching the number:** the places the figure occurs in the filing at all, with no citation.

A citation is traceable when its route, path first, then name, then label, leads to exactly one place. Numbers
are matched as whole numbers (`1,234` = `1234`; `15.3` does not match `115.3`).

What it does not show: that the one place is the gold evidence location (it is a single landing spot,
not a checked one); and a person reading the page may find more than the 400-character window does.
The DGML citations that remain ambiguous (about 28% on a full read) are one name holding the same value
in several tables; stable short ids on elements would resolve them.

## Reproduce

Requires [uv](https://docs.astral.sh/uv/) (every step runs under Python 3.12) and poppler's `pdftotext`
for one of the four markdowns (`brew install poppler`, `apt install poppler-utils`). Reproducing the
scores needs no key and no model; the network is used only for packages and, with `--tests`, once for
the model's tokenizer:

```bash
# from this folder (reasoning/)
uv sync                           # Python 3.12; installs dgml_reasoning and the `dgr` command
uv run dgr reproduce              # builds the renderings, prints both tables for the dev and test splits
uv run dgr reproduce --tests      # the same, then the tests (they pin the accuracy of every row, the traceable
                                  #   share and traceable/1M of the main rows, and three token totals)
```

It runs these steps, which can also be run one by one (`dgr <command> -h` for the options):

```bash
uv run dgr renderings             # element outline + DGML compact, the four PDF markdowns
uv run dgr report --split dev     # accuracy and tokens (--split test for the test split)
uv run dgr provenance --split dev # traceable citations
uv run pytest                     # the tests
```

`dgr renderings` runs `scripts/build_renderings.sh`, which pins every converter (pymupdf4llm 2.0 /
PyMuPDF 2.0; pymupdf4llm 0.0.27 / PyMuPDF 1.26.7; pdfplumber 0.11.10; poppler's `pdftotext` is a system
binary, reference 26.10.0), then checks every file against `data/renderings.sha256`, the files the
reference answers were produced on: a stale or stray file is removed and rebuilt, and the build fails if
a file still differs.

**pymupdf4llm is not deterministic.** pymupdf4llm 0.0.27 (`markdown_pdf_rules`) does not always write
the same file from the same PDF, even with the same versions on the same machine: on
`AMT_2016_0001053507-17-000009` the header cells of one table come out in one of two orders. The
results are the same either way: every number of this README is unchanged. When the check reports that
file, run `uv run dgr renderings` again until it matches.

**Re-run the model.** Put the endpoint and key in `.env` (template `.env.example`) and run any recorded
experiment from `configs/experiments.json`:

```bash
uv run dgr run                                    # the recorded experiments
uv run dgr run dev_dgml_compact_program           # prints what it would run; paid, so it stops there
uv run dgr run dev_dgml_compact_program --yes     # runs it
```

`dgr run <experiment>` clears every run parameter left in the shell, then sets exactly the ones recorded
for it (model, client, reasoning effort, temperature, max tokens, prompt budget, prompt); only the
endpoint and the key come from the environment or `.env`. Extra arguments, after the experiment name,
go to the run and override its recorded ones (e.g. `--limit 3`). A backend with `LLM_CLIENT=litellm` needs
`uv sync --extra litellm`. Answers land in
`results/reference/<model>/<condition>/<question-id>.json` with those parameters recorded in each
file. To try another model, add a backend there.

**Regenerate the DGML (optional).** The DGML ships in `data/docs/dgml/`. To produce it again from the
PDFs, `scripts/regenerate_dgml.sh` clones the DGML converter ([dgml-io/dgml](https://github.com/dgml-io/dgml))
next to the dgml-compass checkout at the commit that produced the test split (the dev split came from an earlier
commit of the same pull request whose Pass A code differs only by typing and logging), installs it, and writes
`data/docs/dgml_regenerated/` (the shipped DGML is never overwritten). It needs an Anthropic key (the
converter runs Claude Haiku 5.5) and costs about $13 for the 30 filings. Model output is not
deterministic, so a regenerated file reads the same filing but is not byte-identical.

## What is in this folder

```
data/
  pdf/<split>/<key>.pdf      the 30 filings as PDF: what the DGML and every markdown are produced from
  docs/dgml/<key>.dgml.xml   the DGML, the only rendering shipped (scripts/build_renderings.sh builds the others)
  renderings.sha256          checksums of the renderings the reference answers were produced on
  questions.json             233 questions: 122 on the dev split, 111 on the test split
  gold_computations.json     the FinQA program behind each gold answer
  manifest.json              the filings, with their EDGAR index pages
  README.md                  where each file comes from, with URLs and revisions
results/reference/azure-deepseek-v4-flash-0731/<condition>/   one JSON per answer
configs/experiments.json     the recorded parameters of every run (`dgr run <experiment>`)
src/dgml_reasoning/          the package behind `dgr` (cli.py): run.py (full read), navigate.py (DGML
                             navigation), score.py, report.py, provenance.py, conditions.py (the rows),
                             answermode.py (citations, programs), llm.py, config.py, dgml_outline.py and
                             make_compact.py (the DGML renderings), make_figure.py
scripts/                     build_renderings.sh (`dgr renderings`: the outline, DGML compact and the four
                             markdowns, then check_renderings.py), make_markdown_pdf.py,
                             make_markdown_pdf_modelfree.py, regenerate_dgml.sh (optional)
tests/                       pin the README's numbers listed under Reproduce (`uv run pytest`)
pyproject.toml, uv.lock      the package and its locked dependencies
figures/accuracy_traceable.svg   the README figure
```

**The two splits.** The dev split is 15 filings from the DocFinQA dev split with 122 questions. The test split
is 15 filings from the DocFinQA test split, chosen to match the dev split in size, with 111 questions; it was
answered blind, after every choice was made on the dev split.

**The renderings.** `dgml` is the converter's DGML without its grounding coordinates and namespaces
(same words; `python -m dgml_reasoning.dgml_outline --import` is the conversion). `dgml_compact` is the same DGML
written lighter: indented `Name: text` lines, table rows as `label | value | value`, no closing tags.
The element outline (`dgml_outline`) lists each distinct element path of a filing once, without text:
what DGML navigation reads to pick elements. The four markdowns come from the same PDFs:
`markdown_pdf` (pymupdf4llm 2.0, which runs PyMuPDF's bundled ONNX layout and table models),
`markdown_pdf_rules` (pymupdf4llm 0.0.27, rule-based), `markdown_pdf_plumber` (pdfplumber),
`markdown_pdf_poppler` (`pdftotext -layout`). No converter uses an LLM or OCR.

**The conditions.** `<rendering>` is a full read with the plain prompt, `<rendering>@program` with
the program prompt, `dgml_nav@program` DGML navigation, `dgml_nav_compact@program` DGML navigation with
the picked elements given in DGML compact (it scores 70 and 63 alone, 75 and 73 with the compact
fallback: no better), `dgml_nav@program.path` DGML navigation citing each figure by its element path.
`conditions.py` defines the rows of both tables.

## The prompts

*Plain*: reason, then give the answer. *Program*: also list every figure used as `value | element`
(the DGML element name, or the row label or heading next to it) and give the computation as a program
the benchmark executes. With path citations, `value | path`: the tag names from the root element down
to the element. The program prompt is the one that cites, so it is the one both tables use.

## Scoring

DocFinQA answers are numbers. `score.py` gives three nested readings: *strict* (within 0.5% of the
stated answer), *prec* (also an answer that rounds to the gold at the gold's own precision), and
*prec+computed* (also the value of the gold FinQA program, which disagrees with the stated answer on
about 30 of the 233 questions even after rounding). The tables here use prec+computed; `dgr report` prints all three.

## Data and terms

See [DATA.md](DATA.md) and [data/README.md](data/README.md).
