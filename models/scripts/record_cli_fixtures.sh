#!/usr/bin/env bash
# Re-record tests/fixtures/cli_responses/ against a real `dgml`.
#
# Most of the committed fixtures were TRANSCRIBED from dgml's docs/cli-reference.md rather
# than captured, because capturing them needs a dgml checkout, a workspace and (for generate)
# a paid API key. This script captures the real thing. Run it when the CLI's payloads change,
# or to convert a transcribed fixture into a recorded one.
#
# Usage:
#   scripts/record_cli_fixtures.sh [--with-generate]
#
# Environment:
#   DGML_REPO   path to the dgml checkout          (default: $DGC_DGML_REPO, else ../../dgml,
#                                                   a sibling of the repo)
#   OUT         where to write                     (default: tests/fixtures/cli_responses)
#   CORPUS      documents to add                   (default: the mini corpus)
# Relative paths resolve against models/, where the script runs.
#
# --with-generate runs `docset generate`, which CALLS A PAID MODEL. Everything else is free.
# Review every recorded file before committing: payloads can contain absolute paths from your
# machine, and must never contain a credential.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

DGML_REPO="${DGML_REPO:-${DGC_DGML_REPO:-../../dgml}}"
OUT="${OUT:-tests/fixtures/cli_responses}"
CORPUS="${CORPUS:-tests/fixtures/mini_corpus/redorg000001/dsred0000001}"
WITH_GENERATE=0
[[ "${1:-}" == "--with-generate" ]] && WITH_GENERATE=1

# dgml() runs inside $DGML_REPO, so paths handed to it must be absolute.
CORPUS="$(cd "$CORPUS" && pwd)" || { echo "CORPUS not found: $CORPUS" >&2; exit 1; }

WS="$(mktemp -d)/ws"
dgml() { ( cd "$DGML_REPO" && uv run dgml --workspace "$WS" --format json "$@" ); }

mkdir -p "$OUT"
echo "workspace: $WS"

( cd "$DGML_REPO" && uv run dgml --version ) > "$OUT/version.txt"
dgml workspace create "$WS" --organization mca --name cell-record > "$OUT/workspace_create.json"

FILE_ID=$(dgml file add "$CORPUS/alpha.pdf" --on-conflict skip --text-mode digital \
  | tee "$OUT/file_add.json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["file_id"])')
# The same add again: --on-conflict skip must return the existing record, created=false.
dgml file add "$CORPUS/alpha.pdf" --on-conflict skip --text-mode digital > "$OUT/file_add_skipped.json"

DOCSET_ID=$(dgml docset create --name dsred0000001 --description "recorded fixture" \
  | tee "$OUT/docset_create.json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["docset_id"])')
dgml docset add-file "$FILE_ID" --docset "$DOCSET_ID" > "$OUT/docset_add_file.json"

dgml status > "$OUT/status.json"
dgml check > "$OUT/check_clean.json"   # exit 2 here would mean issues were found; keep both

# Error envelopes go to stderr, so capture that side instead.
dgml docset show nonexistent-docset 2> "$OUT/error_docset_not_found.json" >/dev/null || true

if (( WITH_GENERATE )); then
  echo "running docset generate -- THIS SPENDS MONEY" >&2
  dgml docset generate "$DOCSET_ID" --debug > "$OUT/docset_generate.json"
  cp "$WS/usage.jsonl" "$OUT/usage.jsonl" 2>/dev/null || echo "no usage.jsonl (was --debug passed?)" >&2
fi

echo "recorded into $OUT. Review for absolute paths and credentials before committing."
