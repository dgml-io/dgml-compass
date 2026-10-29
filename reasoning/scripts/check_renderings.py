#!/usr/bin/env python3
"""Check the built renderings against data/renderings.sha256: the files the reference answers were
produced on. A stale or stray file would otherwise be reused silently.

    python3 scripts/check_renderings.py [--only dgml|markdown] [--fix]

Exit 0 when every expected file is present and identical. --fix removes every file that differs, and
every stray file in those directories (another filing, an older build), so that
scripts/build_renderings.sh rebuilds them; it then exits 1 if anything was removed.
"""
import argparse
import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GROUPS = {'dgml': ('dgml_outline', 'dgml_compact'),
          'markdown': ('markdown_pdf', 'markdown_pdf_rules', 'markdown_pdf_plumber', 'markdown_pdf_poppler')}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--only', choices=sorted(GROUPS), default=None)
    ap.add_argument('--fix', action='store_true', help='remove differing and stray files so they get rebuilt')
    a = ap.parse_args()
    dirs = GROUPS[a.only] if a.only else GROUPS['dgml'] + GROUPS['markdown']
    expected = {}
    for line in open(os.path.join(ROOT, 'data', 'renderings.sha256')):
        h, path = line.split(None, 1)
        path = path.strip()
        if path.split('/')[2] in dirs:
            expected[path] = h
    bad, missing, stray = [], [], []
    for path, h in sorted(expected.items()):
        p = os.path.join(ROOT, path)
        if not os.path.exists(p):
            missing.append(path)
        elif hashlib.sha256(open(p, 'rb').read()).hexdigest() != h:
            bad.append(path)
    for d in dirs:
        full = os.path.join(ROOT, 'data', 'docs', d)
        for f in sorted(os.listdir(full)) if os.path.isdir(full) else []:
            path = f'data/docs/{d}/{f}'
            if f != 'README.md' and path not in expected:
                stray.append(path)
    for kind, paths in (('differs from the reference', bad), ('missing', missing), ('stray (not a rendering of this benchmark)', stray)):
        for p in paths:
            print(f'{kind}: {p}')
    if a.fix:
        for p in bad + stray:
            os.remove(os.path.join(ROOT, p))
    n = len(expected)
    if not (bad or missing or stray):
        print(f'renderings: all {n} files identical to the reference')
        return 0
    if any('markdown_pdf_poppler' in p for p in bad):
        print('note: markdown_pdf_poppler depends on the system pdftotext; the reference is poppler 26.10.0')
    print(f'renderings: {len(bad)} differ, {len(missing)} missing, {len(stray)} stray, of {n} expected'
          + (' -- removed for rebuilding' if a.fix and (bad or stray) else ''))
    return 1


if __name__ == '__main__':
    sys.exit(main())
