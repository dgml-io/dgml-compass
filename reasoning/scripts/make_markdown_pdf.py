#!/usr/bin/env python3
"""PDF markdown with pymupdf4llm 2.0, which runs PyMuPDF's bundled ONNX layout and table models: the
markdown a PDF-conversion user gets today. OCR is off (the PDFs carry a text layer); no LLM.

    uv run --python 3.12 --with pymupdf4llm==2.0 --with pymupdf==2.0 \
        python scripts/make_markdown_pdf.py --split dev [--to markdown_pdf] [--force]

Reads data/pdf/<split>/<key>.pdf, the PDFs the DGML is produced from; writes data/docs/<to>/<key>.md
and records the tool and version in data/docs/<to>/README.md. scripts/build_renderings.sh runs it.
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from dgml_reasoning import config as C


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--split', default='dev', choices=['dev', 'test'])
    ap.add_argument('--to', default='markdown_pdf')
    ap.add_argument('--keys', default='')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--pdf-root', default='', help='directory holding <split>/<key>.pdf (default: data/pdf)')
    a = ap.parse_args()
    import pymupdf
    import pymupdf4llm
    keys = sorted({q['key'] for q in C.load_questions(a.split)})
    if a.keys:
        pre = tuple(x.strip() for x in a.keys.split(',') if x.strip())
        keys = [k for k in keys if k.startswith(pre)]
    out_dir = os.path.join(C.DOCS, a.to)
    os.makedirs(out_dir, exist_ok=True)
    candidates = [a.pdf_root] if a.pdf_root else [os.path.join(os.path.dirname(C.DOCS), 'pdf')]
    pdf_root = next((os.path.join(c, a.split) for c in candidates
                     if os.path.isdir(os.path.join(c, a.split))), None)
    if not pdf_root:
        sys.exit(f'no PDF directory found among {candidates}; pass --pdf-root')
    print(f'PDFs from {os.path.abspath(pdf_root)}')
    n = 0
    for k in keys:
        out = os.path.join(out_dir, k + '.md')
        if os.path.exists(out) and not a.force:
            continue
        pdf = os.path.join(pdf_root, k + '.pdf')
        t0 = time.time()
        doc = pymupdf.open(pdf)
        # the PDFs carry a text layer; OCR off (no Tesseract here, and OCR would change the baseline)
        try:
            from pymupdf4llm.helpers.document_layout import OCRMode
            off = next((m for n, m in OCRMode.__members__.items() if n.upper() in ('NONE', 'NEVER', 'OFF', 'DISABLED')), False)
        except Exception:
            off = False
        md = pymupdf4llm.to_markdown(doc, show_progress=False, use_ocr=off)
        n_pages = doc.page_count
        doc.close()
        open(out, 'w', encoding='utf-8').write(md)
        pipes = sum(1 for ln in md.splitlines() if ln.lstrip().startswith('|') and '---' in ln)
        n += 1
        print(f'{k}: {n_pages} pages, {len(md):,} chars, {pipes} pipe tables, {time.time() - t0:.0f}s', flush=True)
    readme = os.path.join(out_dir, 'README.md')
    open(readme, 'w').write(f"# {a.to}\n\nMarkdown produced from data/pdf/<split>/<key>.pdf (the same PDFs the DGML is produced from) "
                            f"with pymupdf4llm {pymupdf4llm.__version__} / PyMuPDF {pymupdf.__version__}, "
                            f"`pymupdf4llm.to_markdown(doc, use_ocr=off)` (table detection on, OCR off: the PDFs have a text layer). "
                            f"Checked against data/renderings.sha256 by scripts/check_renderings.py.\n")
    print(f'{n} file(s) -> {out_dir}')


if __name__ == '__main__':
    main()
