#!/usr/bin/env bash
# Build every rendering the benchmark compares, from what ships: data/docs/dgml/ and data/pdf/.
# No model, no network beyond the package index. Run once after cloning.
#
#   scripts/build_renderings.sh            # everything (the ONNX markdown takes a few minutes per filing)
#   scripts/build_renderings.sh dgml       # only the element outline and DGML compact (seconds)
#   scripts/build_renderings.sh markdown   # only the four PDF markdowns
#
# Every file is then checked against data/renderings.sha256 (scripts/check_renderings.py); a stale or stray
# file is removed and rebuilt, and the script fails if a file still differs.
#
# Outputs (gitignored), with the converter versions the reference answers were produced on:
#   data/docs/dgml_outline/          element outline per filing (DGML navigation reads it)
#   data/docs/dgml_compact/         DGML compact: `Name: text` lines, table rows `label | v | v`, no end tags
#   data/docs/markdown_pdf/         pymupdf4llm 2.0 / PyMuPDF 2.0 (bundled ONNX layout + table models), OCR off
#   data/docs/markdown_pdf_rules/   pymupdf4llm 0.0.27 / PyMuPDF 1.26.7 (rule-based, before the layout model)
#   data/docs/markdown_pdf_plumber/ pdfplumber 0.11.10, extract_text() + extract_tables()
#   data/docs/markdown_pdf_poppler/ poppler pdftotext -layout (system binary; reference: 26.10.0)
set -euo pipefail
cd "$(dirname "$0")/.."
WHAT="${1:-all}"
PY=(uv run --quiet --python 3.12)

build_dgml() {
  "${PY[@]}" python -m dgml_reasoning.dgml_outline
  "${PY[@]}" python -m dgml_reasoning.make_compact --from dgml
}
build_markdown() {
  for split in dev test; do
    "${PY[@]}" --with pymupdf4llm==2.0 --with pymupdf==2.0 python scripts/make_markdown_pdf.py --split "$split"
    "${PY[@]}" --with pymupdf4llm==0.0.27 --with pymupdf==1.26.7 python scripts/make_markdown_pdf_modelfree.py --engine rules --split "$split"
    "${PY[@]}" --with pdfplumber==0.11.10 python scripts/make_markdown_pdf_modelfree.py --engine plumber --split "$split"
    if command -v pdftotext >/dev/null; then
      "${PY[@]}" python scripts/make_markdown_pdf_modelfree.py --engine poppler --split "$split"
    else
      echo "pdftotext not found (poppler): markdown_pdf_poppler skipped (brew install poppler / apt install poppler-utils)" >&2
    fi
  done
}
# build what is missing, check every file against data/renderings.sha256, rebuild what was stale, check again
for group in dgml markdown; do
  [[ "$WHAT" == all || "$WHAT" == "$group" ]] || continue
  "build_$group"
  if ! "${PY[@]}" python scripts/check_renderings.py --only "$group" --fix; then
    "build_$group"
    "${PY[@]}" python scripts/check_renderings.py --only "$group" || { echo "renderings differ from the reference (see above)" >&2; exit 1; }
  fi
done
