# DGML vs markdown: traceable reasoning

`reasoning/` in dgml-compass: a project separate from `models/` (Model Compass), with its own
`pyproject.toml`, data, reference answers and tests. It installs the command `dgr`; run every command
below from this folder.

**When an agent answers a question about a financial filing, does each figure it reasons from point
to one exact place in the document?** With DGML, 82-85% of them do, against 16-33% with markdown
converted from the same PDF: about 2.5 times as often, at the same accuracy and with about half the
tokens.

The benchmark gives a model 30 SEC 10-K filings and 233 DocFinQA questions, once as DGML and once as
markdown produced from the same PDFs by four different converters. The model answers and cites every
figure it uses as `value | element`. A script then follows each citation back into the full filing.

## The result

A citation is **traceable** when it leads to exactly one place in the filing that holds the figure.
DeepSeek-V4-Flash, temperature 0, program prompt (see [The prompts](#the-prompts)).

The headline compares the best DGML system, navigation with path citations, against every PDF
converter, on the dev and test splits:

| | DGML navigation, path citations | PDF markdown, four converters |
|---|---:|---:|
| traceable citations | **82-85%** | 16-33% |
| correct answers, dev / test | 79 / 76 | 79-81 / 77-79 |
| tokens, dev / test | **7.0 M / 6.6 M** | 11.6-13.6 M / 10.8-13.4 M |

![Correct answers against traceable citations for each system, dev and test splits: the four DGML systems sit at 56-85% traceable, the four PDF-markdown converters at 16-33%, across the same accuracy range](figures/accuracy_traceable.svg)

Each segment is one system, from its dev point (blue) to its test point (orange); filled points are DGML,
hollow points markdown from the same PDF. `dgr figure` redraws it from the shipped answers.

Every row, the accuracy and token tables and the effect of the citing prompt are in
[docs/RESULTS.md](docs/RESULTS.md).

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
results are the same either way: every number of docs/RESULTS.md is unchanged. When the check reports that
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
tests/                       pin the numbers of docs/RESULTS.md listed under Reproduce (`uv run pytest`)
docs/RESULTS.md              every result: traceable citations, accuracy and tokens, the citing prompt
pyproject.toml, uv.lock      the package and its locked dependencies
figures/accuracy_traceable.svg   the figure of the README and docs/RESULTS.md
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
