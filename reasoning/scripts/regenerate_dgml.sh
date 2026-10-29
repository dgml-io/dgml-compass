#!/usr/bin/env bash
# OPTIONAL. Regenerate the DGML from the shipped PDFs with the Docugami DGML converter, at the commit
# that produced data/docs/dgml/. The benchmark does not need this: the DGML ships. The converter is
# not part of dgml-compass; this script clones it next to the dgml-compass checkout (or uses --converter DIR).
#
#   export ANTHROPIC_API_KEY=...          # the converter's models (Claude Haiku 5.5)
#   scripts/regenerate_dgml.sh --split dev [--keys ADI_2011,AMT_2005] [--jobs 5] [--dry-run]
#
# Output: data/docs/dgml_regenerated/ (+ _outline/), a format of its own -- the shipped data/docs/dgml/
# is never overwritten. Answer with it like any other format, under a recorded experiment's parameters:
#   uv run dgr run dev_dgml_program --yes --format dgml_regenerated        # full read -> dgml_regenerated@program/
#   uv run dgr run dev_dgml_nav_program --yes --format dgml_regenerated    # navigation -> dgml_regenerated_nav@program/
# (its element outline is written by this script; DGML compact: python -m dgml_reasoning.make_compact --from dgml_regenerated)
#
# Converter: https://github.com/dgml-io/dgml, commit DGML_COMMIT from PR #267 (merged). The commit is not on a
# branch of the repository, so it is fetched by its sha after the clone.
# Pass A = text transcription in 5-page windows with the completeness check and per-page retry, then
# labeling; every model Claude Haiku 5.5; PDFs ingested with their text layer (digital, 150 dpi).
# The test split was generated at exactly DGML_COMMIT; the dev split at an earlier commit of the same pull request
# whose Pass A code differs only by typing and logging changes. Model output is not
# deterministic: a regenerated file reads the same filing but is not byte-identical.
# Measured cost: about $0.37 per 100 pages (generation + labeling + links); the 30 filings are 3,522 pages (about $13).
# Requires: git, uv, jq, ghostscript (gs).
set -euo pipefail
DGML_REPO="${DGML_REPO:-https://github.com/dgml-io/dgml.git}"
DGML_COMMIT="${DGML_COMMIT:-4751bc0e7ef38deeb2f4ceabcca1fd324ec6206e}"
BENCH="$(cd "$(dirname "$0")/.." && pwd)"
# the converter and its workspace go next to the git repository holding this folder, never inside it
TOP="$(git -C "$BENCH" rev-parse --show-toplevel 2>/dev/null || echo "$BENCH")"
CONVERTER="$TOP/../dgml-converter"
SPLIT=dev; KEYS=""; JOBS=5; DRY=0
MODEL="anthropic/claude-haiku-5-5"; WINDOW=5
while [[ $# -gt 0 ]]; do
  case "$1" in
    --split) SPLIT="$2"; shift 2 ;;
    --keys) KEYS="$2"; shift 2 ;;
    --jobs) JOBS="$2"; shift 2 ;;
    --converter) CONVERTER="$2"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n 2,24p "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
for bin in git uv jq gs; do command -v "$bin" >/dev/null || { echo "\`$bin\` not on PATH" >&2; exit 1; }; done
WS="$(cd "$TOP/.." && pwd)/dgml-workspace-$SPLIT"

# the filings of the split, from the manifest
ALL=()
while IFS= read -r k; do ALL+=("$k"); done < <(uv run --quiet --python 3.12 python -c "import json; [print(m['key']) for m in json.load(open('$BENCH/data/manifest.json')) if m.get('split','dev')=='$SPLIT']")
SEL=()
for k in "${ALL[@]}"; do
  if [[ -z "$KEYS" ]]; then SEL+=("$k"); continue; fi
  IFS=, read -ra P <<< "$KEYS"; for p in "${P[@]}"; do [[ "$k" == "$p"* ]] && { SEL+=("$k"); break; }; done
done
(( ${#SEL[@]} )) || { echo "no filing of split $SPLIT matches '$KEYS'" >&2; exit 1; }
echo "converter $DGML_REPO @ ${DGML_COMMIT:0:7} -> $CONVERTER" >&2
echo "workspace $WS, ${#SEL[@]} filing(s), $JOBS at a time, model $MODEL, window $WINDOW pages" >&2
if (( DRY )); then printf '  %s\n' "${SEL[@]}"; exit 0; fi
[[ -n "${ANTHROPIC_API_KEY:-}" ]] || { echo "ANTHROPIC_API_KEY is not set" >&2; exit 1; }

# 1. the converter at the pinned commit, outside dgml-compass
if [[ ! -d "$CONVERTER/.git" ]]; then git clone --quiet "$DGML_REPO" "$CONVERTER"; fi
git -C "$CONVERTER" fetch --quiet origin "$DGML_COMMIT" 2>/dev/null || true
git -C "$CONVERTER" checkout --quiet "$DGML_COMMIT"
( cd "$CONVERTER" && uv sync --quiet )
dgml() { ( cd "$CONVERTER" && env -u VIRTUAL_ENV uv run --quiet dgml --workspace "$WS" "$@" ); }

# 2. a fresh workspace with the models of the reference run
if [[ ! -d "$WS" ]]; then
  dgml workspace create "$WS" --organization Docugami --name "$(basename "$WS")" >/dev/null
  printf '\n[models]\nlight    = "%s"\nstandard = "%s"\nadvanced = "%s"\nexpert   = "%s"\n\n[generation]\nretry_model = "%s"\n' \
    "$MODEL" "$MODEL" "$MODEL" "$MODEL" "$MODEL" >> "$WS/config.toml"
fi
mkdir -p "$WS/_run_logs"; echo "$DGML_COMMIT" > "$WS/_run_logs/commit.txt"

# 3. one DocSet per filing (a failure stays contained to its filing), generated in parallel
DS=()
for k in "${SEL[@]}"; do
  fid="$(dgml file add "$BENCH/data/pdf/$SPLIT/$k.pdf" --on-conflict skip --text-mode digital --dpi 150 | jq -r '.file.id')"
  dsid="$(dgml docset create --name "$k" --description "dgml-compass reasoning $SPLIT: $k" | jq -r .id)"
  dgml docset add-file "$fid" --docset "$dsid" >/dev/null
  DS+=("$k:$dsid"); echo "  $k -> docset $dsid" >&2
done
running=0
for pair in "${DS[@]}"; do
  k="${pair%%:*}"; dsid="${pair#*:}"
  ( dgml --verbose docset generate --window-size "$WINDOW" --max-parallel-calls 1 "$dsid" > "$WS/_run_logs/generate-$k.log" 2>&1 \
      && echo "  done $k" >&2 || echo "  FAILED $k (see $WS/_run_logs/generate-$k.log)" >&2 ) &
  running=$((running + 1))
  if (( running >= JOBS )); then wait; running=0; fi   # batches of --jobs (bash 3.2 has no wait -n)
done
wait

# 4. into the benchmark, as its own format
uv run --quiet --python 3.12 --project "$BENCH" python -m dgml_reasoning.dgml_outline --import "$WS/docsets/*/files/*" --to dgml_regenerated --keys "$(IFS=,; echo "${SEL[*]}")"
