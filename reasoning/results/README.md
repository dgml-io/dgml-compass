# Reference answers

`reference/<model>/<condition>/<question-id>.json`, one file per answer, with the parameters of the run
recorded in it (model, client, reasoning effort, temperature, tokenizer, prompt budget, cut, usage).
One model: `azure-deepseek-v4-flash-0731` (DeepSeek-V4-Flash-0731, temperature 0). A condition directory
holds both splits; the question ids tell them apart (`data/questions.json`, field `split`).

| condition | what it is |
|---|---|
| `<rendering>` | full read, plain prompt |
| `<rendering>@program` | full read, program prompt: every figure cited as `value \| element`, the computation as a program the benchmark executes |
| `dgml_nav@program` | DGML navigation: call 1 picks elements from the element outline, call 2 reads them as DGML |
| `dgml_nav_compact@program` | the same, the picked elements given in DGML compact |
| `…@r2`, `…@program.r2` | a second run of the same parameters |

`<rendering>`: `dgml`, `dgml_compact`, `markdown_pdf`, `markdown_pdf_rules`, `markdown_pdf_plumber`,
`markdown_pdf_poppler`. `conditions.py` names the rows built from these; `dgr report` and
`dgr provenance` read them, `dgr reproduce` runs both.
