# Contributing to DGML Compass

DGML is an open initiative founded by Docugami and Inveniam. This repository holds DGML Compass,
the open benchmarks for DGML: `models/` (Model Compass, which models to create DGML with) and
`reasoning/` (DGML against PDF markdown for an agent's reasoning). The DGML reference
implementation lives in [dgml-io/dgml](https://github.com/dgml-io/dgml), the format specification
in [dgml-io/dgml-spec](https://github.com/dgml-io/dgml-spec).

## How to contribute

### Ask a question or start a discussion
Open a [GitHub Discussion](../../discussions) for questions about the benchmarks, ideas for new
sweeps, models or conditions, or anything else. For questions about the format itself, head to
[dgml-io/dgml-spec](https://github.com/dgml-io/dgml-spec/discussions); for the converter, to
[dgml-io/dgml](https://github.com/dgml-io/dgml/discussions).

### Report a bug
Open a [GitHub Issue](../../issues) with a clear description of the problem, the project
(`models/` or `reasoning/`), the exact command you ran and what it printed.

### Propose a change
1. Open an Issue first to describe what you want to change and why
2. Once there is consensus, submit a Pull Request
3. Small fixes (typos, bugs with obvious solutions) can go straight to a PR

A change that moves a published number (a metric, a scoring rule, a prompt, a rendering) says why,
and regenerates what pins it: `models/docs/DECISIONS.md` and the goldens in `models/`, the
README numbers and their tests in `reasoning/`. Every document added to a corpus must be public.

### Development setup
The two projects are independent, each with its own `pyproject.toml`; run commands from the
project's folder:

```bash
cd models && uv sync && uv run ruff check . && uv run pytest && cd ..
cd reasoning && uv sync && uv run ruff check . && uv run pytest && cd ..
```

The tests need no API key and make no model call; CI runs the same checks.

## Contributor License Agreement (CLA)

Before your Pull Request can be merged, you must sign the Apache Individual
Contributor License Agreement. The CLA bot will prompt you automatically
when you open your first PR. This is a one-time requirement.

## Governance

DGML is governed as an open standard. A steering committee will be established
over time to guide the evolution of the format, with representation from
contributors and adopters.
