# dgml-compass

Experiments on [dgml](https://github.com/dgml-io/dgml), which transcribes documents (PDF, DOCX)
into DGML, an XML whose elements are labeled with what each part of the document holds. Each
experiment answers one question about DGML with public documents, committed reference results
and tests that pin the published numbers.

The two folders follow DGML through its life: first produce it well, then put it to work. They
are separate projects, each with its own `pyproject.toml`, data, results, tests and README, and
each runs on its own. But they answer two questions in sequence: which models should make the
DGML, and whether a model reading DGML rather than markdown keeps the quality of its answers
while every figure in them can be traced back to the source. Run each project's commands from
its own folder.

| Folder | Question | Runs over | Needs |
|---|---|---|---|
| [`models/`](models/README.md): **Model Compass** | Which models should fill dgml's *transcribe* and *label* roles, by quality, consistency and cost? | 9 public docsets (205 documents with gold DGML and field values) | a dgml checkout and provider keys for new runs; scoring and reports need neither |
| [`reasoning/`](reasoning/README.md): **DGML vs markdown, provenance** | A model reads a filing as DGML or as markdown converted from the same PDF and answers a question: can each figure it used be traced back to its source? | 30 SEC 10-K filings, 233 DocFinQA questions | nothing to reproduce the scores: offline, from the shipped answers |

## 1. Produce the DGML: Model Compass (`models/`)

dgml calls one model to transcribe a document and another to label it, and the right choice
can differ from one kind of document to another. Model Compass compares them per document
shape (forms, contracts and other long prose, complex layouts, hybrid documents). It sweeps
models from OpenAI, Google and Anthropic through both roles over the corpus, scores the DGML
against gold annotations, and reports quality, draw-to-draw noise, tokens and cost per model.
The aim is the model that is good enough for each shape, without paying for more than it needs.

![Quality against cost per document for each transcriber-labeler pipeline: the labeler buys quality as cost rises, the transcriber does not](models/figures/quality_cost.svg)

Each point is a pipeline averaged over all 9 docsets.\* Blue points climb with cost: the labeler
buys quality, from Haiku 5.5 (79, $0.02 per document) to GPT-5.5 (86, $1.42). Orange points stay
flat: four of the five transcribers give about 78.5, so the cheapest, Haiku 5.5, is enough. The
bars are wide because the 9 docsets differ far more than the models do; points inside each
other's bars are not distinguishable on this corpus. Gray points come from an earlier dgml
build. Every number is in [models/docs/RESULTS.md](models/docs/RESULTS.md) §6.

\* The best model can change with the kind of document. RESULTS.md breaks every sweep down
[by document shape](models/docs/RESULTS.md#by-shape) (forms, contracts and other long prose,
complex layouts, hybrid documents) and by docset. Only long prose has enough docsets for a firm
ranking; each other shape rests on one or two docsets.

It is a Python package, `model_compass`, with the CLI `dgc` (plan, run, score, aggregate,
report, compare; `sweep` for the configured sweeps end to end, `reference` and `figure` for the
committed results). Paid runs are planned and priced first and stop at a budget cap.

- Results on the bundled corpus: [models/docs/RESULTS.md](models/docs/RESULTS.md)
- Sweeps and how to run them: [models/docs/EXPERIMENTS.md](models/docs/EXPERIMENTS.md)
- Metric definitions: [models/docs/METRICS.md](models/docs/METRICS.md); design decisions and
  known defects: [models/docs/DECISIONS.md](models/docs/DECISIONS.md)

## 2. Read the DGML: provenance against markdown (`reasoning/`)

Once a document is in DGML, can a model answer from it with provenance, each figure traced back
to its source, while keeping the quality of its answers? This benchmark gives a model the same
SEC filings as DGML and as markdown, the format most often fed to LLMs, converted from the
same PDFs by four converters. The model answers questions and cites every figure it uses, and
a script follows each citation back into the filing.

Provenance is what makes an answer usable wherever it has to be checked, as in finance, legal,
audit or compliance work: a figure that cannot be traced to one place in the source cannot be
verified, and a wrong one goes unnoticed. With DGML, citations are traceable about twice as
often as with markdown, and the answers stay as accurate.

![Correct answers against traceable citations for each system, dev and test splits: the four DGML systems sit at 56-85% traceable, the four PDF-markdown converters at 16-33%, across the same accuracy range](reasoning/figures/accuracy_traceable.svg)

Each segment is one system, from its dev point (blue) to its test point (orange); filled points
are DGML, hollow points markdown from the same PDF. Details and every number in
[reasoning/README.md](reasoning/README.md).

It is a Python package, `dgml_reasoning`, with the CLI `dgr` (reproduce, renderings, report,
provenance, figure, run); `uv run dgr reproduce` rebuilds every score in its README without a
key.

## Quick start

Both projects need [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
git clone https://github.com/dgml-io/dgml-compass.git && cd dgml-compass

cd models && uv sync && uv run dgc --help && cd ..          # Model Compass: the `dgc` command
cd reasoning && uv sync && uv run dgr reproduce && cd ..    # the reasoning benchmark: `dgr`, offline
```

Each project runs its own tests, with no key and no model call:

```bash
cd models && uv run ruff check . && uv run pytest && cd ..
cd reasoning && uv run ruff check . && uv run pytest && cd ..
```

Everything else, paid runs included, goes through each project's own command: `dgc` in
`models/` (`dgc sweep --yes` runs the configured sweeps) and `dgr` in `reasoning/`
(`dgr run <experiment> --yes` re-runs a recorded experiment).

## Layout

```
models/       Model Compass: package, corpus, sweeps, reference results, docs, tests
reasoning/    Reasoning and provenance: benchmark code, filings, answers, figures, tests
LICENSE       applies to the whole repository; reasoning/data/ also carries the FinQA licence
```

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md) (pull requests need the one-time
DGML CLA).
