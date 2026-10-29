#!/usr/bin/env python3
"""The DGML element outline that DGML navigation reads, and the import of a converter run.

    python -m dgml_reasoning.dgml_outline                         # data/docs/dgml -> data/docs/dgml_outline/
    python -m dgml_reasoning.dgml_outline --format dgml_regenerated
    python -m dgml_reasoning.dgml_outline --import '<workspace>/docsets/*/files/*' --to dgml_regenerated

Outline: one line per distinct element path (tag names and nesting, no text), `L12    BalanceSheet x3`,
written as <key>.outline.txt (what the model reads) and <key>.lines.json (line id -> path).

--import: the DGML the converter writes (namespaced, with grounding coordinates and typing
attributes) becomes the form the benchmark reads: semantic element names and nesting kept, the
structural role as r="...", grounding / typing attributes and namespaces dropped. The words are
checked to be unchanged. This is how data/docs/dgml/ was produced from the converter output.
"""
import argparse
import collections
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS = os.path.join(ROOT, 'data', 'docs')

DG = '{http://dgml.io/ns/dg#}'
DROP_ATTRS = ('type', 'value', 'id', 'itemprop', 'href', 'origin', 'style')
ROLE_TAGS = {'td', 'tr', 'table', 'p', 'li', 'ul', 'ol', 'span', 'header', 'section', 'lim'}
WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:,\d{3})*(?:\.\d+)?%?")


def _local(tag):
    return tag.split('}')[-1] if '}' in tag else tag.split(':')[-1]


def to_lite(el):
    """The same tree without reader-useless markup: no namespace prefixes, no xsi:type / dg:value /
    xml:id / dg:origin / dg:style; a generic chunk carrying a structure role becomes that tag
    (<td>, <tr>); a semantic element keeps its name and carries the role as r="..."."""
    role = el.get(DG + 'structure')
    name = _local(el.tag)
    promote = name == 'chunk' and role in ROLE_TAGS
    out = ET.Element(role if promote else name)
    if not promote and role:
        out.set('r', role)
    for k, v in el.attrib.items():
        if _local(k) in DROP_ATTRS or _local(k) == 'structure' or k.startswith('xmlns'):
            continue
        out.set(_local(k), v)
    out.text = el.text
    out.tail = el.tail
    for kid in el:
        out.append(to_lite(kid))
    return out


def words_of(el):
    return WORD.findall(' '.join(el.itertext()))


def build_trie(root, max_depth=8):
    trie = {'kids': collections.OrderedDict(), 'n': 1}

    def walk(el, node, depth):
        if depth > max_depth:
            return
        for kid in el:
            k = node['kids'].get(kid.tag)
            if k is None:
                k = node['kids'][kid.tag] = {'kids': collections.OrderedDict(), 'n': 0}
            k['n'] += 1
            walk(kid, k, depth + 1)

    walk(root, trie, 1)
    return trie


def render_outline(root_tag, trie):
    """-> (text, {line_id: path}); one line per distinct element path."""
    lines, index = [f'L0  {root_tag}'], {'L0': '/' + root_tag}
    counter = [0]

    def emit(node, path, depth):
        for tag, kid in node['kids'].items():
            counter[0] += 1
            lid = f'L{counter[0]}'
            p = path + '/' + tag
            index[lid] = p
            lines.append(f'{lid}  ' + '  ' * depth + tag + (f' x{kid["n"]}' if kid['n'] > 1 else ''))
            emit(kid, p, depth + 1)

    emit(trie, '/' + root_tag, 1)
    return '\n'.join(lines), index


def write_outline(root, outline_dir, key):
    os.makedirs(outline_dir, exist_ok=True)
    text, index = render_outline(root.tag, build_trie(root))
    open(os.path.join(outline_dir, key + '.outline.txt'), 'w', encoding='utf-8').write(text)
    json.dump(index, open(os.path.join(outline_dir, key + '.lines.json'), 'w'), indent=0)
    return len(index)


def keys_of_manifest():
    return [m['key'] for m in json.load(open(os.path.join(ROOT, 'data', 'manifest.json')))]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--format', default='dgml', help='the DGML directory under data/docs/ to build the outline of')
    ap.add_argument('--import', dest='imp', default='', help="glob(s), ':'-separated, of converter output dirs holding <key>*.dgml.xml")
    ap.add_argument('--to', default='dgml_regenerated', help='--import: the format directory to write (never the shipped dgml)')
    ap.add_argument('--keys', default='', help='comma list of key prefixes (default: every filing in the manifest)')
    a = ap.parse_args()
    keys = keys_of_manifest()
    if a.keys:
        pre = tuple(x.strip() for x in a.keys.split(',') if x.strip())
        keys = [k for k in keys if k.startswith(pre)]
    if a.imp:
        if a.to == 'dgml':
            sys.exit('--to dgml would overwrite the shipped DGML; import into another format (default dgml_regenerated)')
        dst = os.path.join(DOCS, a.to); os.makedirs(dst, exist_ok=True)
        dirs = [d for g in a.imp.split(':') for d in sorted(glob.glob(g))]
        n = 0
        for k in keys:
            src = next((f for d in dirs for f in sorted(glob.glob(os.path.join(d, k + '*.dgml.xml')))), None)
            if not src:
                continue
            root = ET.parse(src).getroot()
            lite = to_lite(root)
            if words_of(root) != words_of(lite):
                print(f'{k}: the conversion changed the words; skipped'); continue
            open(os.path.join(dst, k + '.dgml.xml'), 'w', encoding='utf-8').write(
                "<?xml version='1.0' encoding='utf-8'?>\n" + ET.tostring(lite, encoding='unicode'))
            lines = write_outline(lite, os.path.join(DOCS, a.to + '_outline'), k)
            print(f'{k}: imported, {lines:,} outline lines'); n += 1
        print(f'{n} file(s) -> {dst}')
        return
    src = os.path.join(DOCS, a.format)
    n = 0
    for k in keys:
        p = os.path.join(src, k + '.dgml.xml')
        if os.path.exists(p):
            write_outline(ET.parse(p).getroot(), os.path.join(DOCS, a.format + '_outline'), k); n += 1
    print(f'{n} outline(s) -> {os.path.join(DOCS, a.format + "_outline")}')


if __name__ == '__main__':
    main()
