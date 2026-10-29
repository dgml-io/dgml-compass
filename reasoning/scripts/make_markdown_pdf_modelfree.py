#!/usr/bin/env python3
"""PDF markdown with model-free converters, from the same PDFs the DGML is produced from; one
directory per engine. No layout model, no OCR, no LLM.

    --engine rules    pymupdf4llm 0.0.27 on PyMuPDF 1.26.7, the last versions before the layout model:
                      font-size headings, geometric table finder                 -> markdown_pdf_rules
    --engine plumber  pdfplumber 0.11.10: extract_text() + extract_tables(), tables as pipe tables
                                                                                 -> markdown_pdf_plumber
    --engine poppler  poppler pdftotext -layout (a system binary): text with its horizontal
                      alignment kept                                             -> markdown_pdf_poppler

    python3 scripts/make_markdown_pdf_modelfree.py --engine poppler --split dev [--force]

scripts/build_renderings.sh runs all three with the pinned versions. Each directory gets a README
naming the engine and version.
"""
import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from dgml_reasoning import config as C

OUT = {'rules': 'markdown_pdf_rules', 'plumber': 'markdown_pdf_plumber', 'poppler': 'markdown_pdf_poppler'}


def convert_rules(pdf):
    import pymupdf4llm
    import pymupdf
    return pymupdf4llm.to_markdown(pdf, show_progress=False), f'pymupdf4llm {pymupdf4llm.__version__} / PyMuPDF {pymupdf.__version__}, to_markdown defaults'


def convert_plumber(pdf):
    import pdfplumber
    parts = []
    with pdfplumber.open(pdf) as doc:
        for page in doc.pages:
            text = page.extract_text() or ''
            parts.append(text)
            for tb in page.extract_tables():
                rows = [[(c or '').replace('\n', ' ').strip() for c in r] for r in tb if r]
                if not rows:
                    continue
                parts.append('')
                parts.append('| ' + ' | '.join(rows[0]) + ' |')
                parts.append('|' + '---|' * len(rows[0]))
                for r in rows[1:]:
                    parts.append('| ' + ' | '.join(r) + ' |')
                parts.append('')
    return '\n'.join(parts), f'pdfplumber {pdfplumber.__version__}, extract_text() + extract_tables() defaults'


def convert_poppler(pdf):
    out = subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True, timeout=600)
    ver = subprocess.run(['pdftotext', '-v'], capture_output=True, text=True).stderr.strip().splitlines()[0]
    return out.stdout, f'{ver}, pdftotext -layout'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--engine', choices=list(OUT), required=True)
    ap.add_argument('--split', default='dev', choices=['dev', 'test'])
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    keys = sorted({q['key'] for q in C.load_questions(a.split)})
    out_dir = os.path.join(C.DOCS, OUT[a.engine]); os.makedirs(out_dir, exist_ok=True)
    pdf_root = os.path.join(os.path.dirname(C.DOCS), 'pdf', a.split)
    if not os.path.isdir(pdf_root):
        sys.exit(f'no PDFs at {pdf_root}')
    conv = {'rules': convert_rules, 'plumber': convert_plumber, 'poppler': convert_poppler}[a.engine]
    label = None; n = 0
    for k in keys:
        out = os.path.join(out_dir, k + '.md')
        if os.path.exists(out) and not a.force:
            continue
        t0 = time.time(); md, label = conv(os.path.join(pdf_root, k + '.pdf'))
        open(out, 'w', encoding='utf-8').write(md); n += 1
        print(f'{k}: {len(md):,} chars, {time.time() - t0:.0f}s', flush=True)
    if label:
        open(os.path.join(out_dir, 'README.md'), 'w').write(f'# {OUT[a.engine]}\n\nModel-free conversion of data/pdf/<split>/<key>.pdf: {label}. No layout model, no OCR, no LLM. Checked against data/renderings.sha256 by scripts/check_renderings.py.\n')
    print(f'{n} file(s) -> {out_dir}')


if __name__ == '__main__':
    main()
