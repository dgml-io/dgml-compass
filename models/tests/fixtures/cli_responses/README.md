# Recorded `dgml` responses

Payloads the unit tests replay, so the adapter is exercised without a `dgml`, a workspace, or
an API key.

| File | Provenance |
|---|---|
| `usage.jsonl` | **Real.** Rows from dgml workspaces' `usage.jsonl`, one per (operation, outcome) seen; only document names were replaced with names from the bundled corpus. |
| everything else | **Transcribed** from the documented contract in dgml's `docs/cli-reference.md`, not captured from a live run — see below. |

Re-record the transcribed ones against a real `dgml` with `scripts/record_cli_fixtures.sh`.
Until someone does, these fixtures prove the adapter matches the *documented* contract; only a
recording proves it matches the implementation; a tiny paid run (docs/EXPERIMENTS.md) does too.

The `usage.jsonl` rows are worth reading: `transcribe` rows carry `context.doc` and are
attributable to a document, while `label` rows carry `context.doc_count` and are not. That is
why per-document cost is flagged `cost_partial` rather than guessed.
