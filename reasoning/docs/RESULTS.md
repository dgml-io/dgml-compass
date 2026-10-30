# DGML vs markdown: results

Every result of the benchmark on the dev (122 questions) and test (111 questions) splits, from the
answers shipped in [`results/reference/`](../results/reference). DeepSeek-V4-Flash, temperature 0,
program prompt unless stated (see [The prompts](../README.md#the-prompts)). A citation is
**traceable** when it leads to exactly one place in the filing that holds the figure; how that is
decided is in [How traceability is measured](../README.md#how-traceability-is-measured).
`uv run dgr reproduce` rebuilds every number below, offline, and `tests/test_report.py` pins them.

## 1. Traceable citations

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

![Correct answers against traceable citations for each system, dev and test splits: the four DGML systems sit at 56-85% traceable, the four PDF-markdown converters at 16-33%, across the same accuracy range](../figures/accuracy_traceable.svg)

Each segment is one system, from its dev point (blue) to its test point (orange); filled points are DGML,
hollow points markdown from the same PDF. `dgr figure` redraws it from the shipped answers.

- **Even a full DGML read is traceable about twice as often as markdown.** The model copies an
  element name that exists in the filing. Asked for the change in HII's unamortized debt issuance costs, it cites
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

## 2. Accuracy and cost

Correct answers (prec+computed, see [Scoring](../README.md#scoring)) and gross tokens (all input and output tokens
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

## 3. With and without the citing prompt

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
