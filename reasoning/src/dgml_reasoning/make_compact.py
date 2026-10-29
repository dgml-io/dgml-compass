#!/usr/bin/env python3
"""DGML compact: the same DGML written lighter -- indented `Name: text` lines, no closing tags, no
attributes, each table row on one line with its cells separated by ` | ` (the row element's name
first when it has one). About 40% fewer tokens than the DGML for the same elements and text.

    python -m dgml_reasoning.make_compact [--from dgml] [--to dgml_compact] [--keys ADI_2011,...] [--force]

Writes data/docs/<to>/<key>.dgml.txt and checks that every figure of the DGML survives, in order.

    Debt:
      header: Debt
      DebtTable:
        Item | 2015 | 2014
        LongTermDebtNet: Long-term debt, net | 15,261 | 6,142
"""
import argparse
import os
import re
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS = os.path.join(ROOT, 'data', 'docs')
STRUCT_ROWS = {'tr', 'row'}     # generic row tags: the row line carries no name


def _txt(el):
    return re.sub(r'\s+', ' ', ''.join(el.itertext())).strip()


def _is_table(el):
    return el.tag == 'table' or el.get('r') == 'table'


def compact(root):
    out = []

    def walk(el, d):
        ind = '  ' * d
        if _is_table(el):
            out.append(f'{ind}{el.tag}:')
            for r in el:
                cells = [_txt(c) for c in r]
                name = '' if r.tag in STRUCT_ROWS else r.tag + ': '
                body = ' | '.join(cells) if cells else _txt(r)
                if body or name:
                    out.append(f'{ind}  {name}{body}')
            return
        kids = list(el)
        head = re.sub(r'\s+', ' ', el.text or '').strip()
        if not kids:
            out.append(f'{ind}{el.tag}: {head}' if head else f'{ind}{el.tag}:')
            return
        out.append(f'{ind}{el.tag}:' + (f' {head}' if head else ''))
        for k in kids:
            walk(k, d + 1)
            tail = re.sub(r'\s+', ' ', k.tail or '').strip()
            if tail:
                out.append(f'{ind}  {tail}')

    walk(root, 0)
    return '\n'.join(out) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--from', dest='src', default='dgml')
    ap.add_argument('--to', dest='dst', default='')
    ap.add_argument('--keys', default='')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    src_dir, dst_dir = os.path.join(DOCS, a.src), os.path.join(DOCS, a.dst or a.src + '_compact')
    os.makedirs(dst_dir, exist_ok=True)
    keys = sorted(f[:-len('.dgml.xml')] for f in os.listdir(src_dir) if f.endswith('.dgml.xml'))
    if a.keys:
        keys = [k for k in keys if k.startswith(tuple(x.strip() for x in a.keys.split(',') if x.strip()))]
    n = 0
    for k in keys:
        out = os.path.join(dst_dir, k + '.dgml.txt')
        if os.path.exists(out) and not a.force:
            continue
        root = ET.parse(os.path.join(src_dir, k + '.dgml.xml')).getroot()
        text = compact(root)
        # the digit stream is identical once element names (which may carry digits) are stripped:
        # element boundaries and cell separators change the spacing, never a digit or its order
        body = '\n'.join(re.sub(r'^\s*[A-Za-z_][\w.-]*:', '', line) for line in text.splitlines())
        assert re.sub(r'\D', '', body) == re.sub(r'\D', '', ''.join(root.itertext())), f'{k}: figures changed'
        open(out, 'w', encoding='utf-8').write(text)
        n += 1
        print(f'{k}: {len(text):,} chars')
    print(f'{n} file(s) -> {dst_dir}')


if __name__ == '__main__':
    main()
