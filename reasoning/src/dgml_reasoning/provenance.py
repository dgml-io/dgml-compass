#!/usr/bin/env python3
"""Provenance of cited figures: does a citation lead back to ONE place in the filing?

    dgr provenance [--split dev|test] [--compact-as-text]

Offline, over the answers recorded with the program prompt (every figure cited as `value | element`),
for the rows of conditions.py. For every citation, against the full document:

  by path    answers in a path answer mode (answermode.py): the innermost elements whose path, without
             indices, ends with the cited path and whose text holds the value; counted under "by name"
  by name    in the DGML: the innermost elements whose tag is the cited name and whose text holds the
             value (an element nested in a same-named element counts once)
  by label   the places where the cited label is followed within one row's reach (400 chars) by the
             value -- the only route in markdown text
  value only the places the number itself occurs in the filing: what searching the figure finds,
             with no citation

A citation is *traceable* (pinned) when its route, path first, then name, then label, leads to exactly
one place.
DGML compact and DGML navigation citations are resolved in the DGML, which carries the same element
names (--compact-as-text checks DGML compact as plain text instead). "gold" restricts to the figures
the gold FinQA program uses. traceable/1M = traceable citations per million gross tokens of the row.
"""
import argparse
import json
import os
import re
import xml.etree.ElementTree as ET

from dgml_reasoning import conditions as K
from dgml_reasoning import config as C
from dgml_reasoning import report as REP
from dgml_reasoning.answermode import label_variants

WINDOW = 400
NUM = re.compile(r'\d[\d,]*\.?\d*')


def num_of(value):
    m = NUM.search(value.replace('$', ''))
    if not m:
        return None
    n = m.group(0).replace(',', '').rstrip('.')
    if '.' in n:
        n = n.rstrip('0').rstrip('.') if re.search(r'\.\d*[1-9]', n) else n.split('.')[0]
    return n or None


def flat(text):
    return re.sub(r'(?<=\d),(?=\d{3})', '', text)


def count_num(n, text):
    """occurrences of number n as a whole number (1,234 == 1234; 15.3 != 115.3, != 15.35)."""
    pat = re.escape(n)
    rx = re.compile(r'(?<![\d.])' + pat + (r'(?:\.0+)?' if '.' not in n else r'0*') + r'(?![\d])')
    return len(rx.findall(text))


class Doc:
    def __init__(self, path, is_xml):
        raw = open(path, encoding='utf-8', errors='replace').read()
        self.is_xml, self.by_tag, self.path = is_xml, {}, {}
        if is_xml:
            root = ET.fromstring(raw)
            for e in root.iter():
                self.by_tag.setdefault(e.tag, []).append(e)

            def walk(e, p):
                self.path[id(e)] = p = p + '/' + e.tag
                for k in e:
                    walk(k, p)
            walk(root, '')
            self.plain = flat(re.sub(r'\s+', ' ', ' '.join(root.itertext())))
        else:
            self.plain = flat(raw)
        self.low = self.plain.lower()

    def n_name(self, tag, n, path=''):
        els = self.by_tag.get(tag)
        if not els:
            return 0
        hits = [e for e in els if count_num(n, flat(''.join(e.itertext())))
                and (not path or (self.path[id(e)] + '/').endswith('/' + path + '/'))]
        ids = {id(e) for e in hits}
        # drop an element when a same-named descendant already holds the value
        inner = [e for e in hits if not any(id(d) in ids for d in e.iter(tag) if d is not e)]
        return len(inner)

    def n_label(self, element, n):
        """places for the first label variant (the verifier's: whole, unqualified, without a
        trailing year) that resolves at all."""
        for lab in label_variants(element):
            k, start = 0, 0
            while (i := self.low.find(lab, start)) >= 0:
                if count_num(n, self.plain[i:i + len(lab) + WINDOW]):
                    k += 1
                start = i + len(lab)
            if k:
                return k
        return 0

    def n_value(self, n):
        return count_num(n, self.plain)


def cited_path(element):
    """`/chunk/Debt[2]/LongTermDebtNet (2015)` -> 'chunk/Debt/LongTermDebtNet': the leading path, indices
    dropped (the outline the model navigates has none)."""
    m = re.match(r'/?[A-Za-z_][\w.-]*(?:\[\d+\])?(?:/[A-Za-z_][\w.-]*(?:\[\d+\])?)*', element.strip())
    return re.sub(r'\[\d+\]', '', m.group(0)).strip('/') if m else ''


def operands(program):
    out = set()
    for x in re.findall(r'(?<![\w])-?\d[\d,]*\.?\d*', program or ''):
        n = num_of(x)
        if n:
            out.add(n)
    return out


_DOCS = {}   # parsed filings, shared by every answer and row of a run


def analyse(doc_fmt, recs, gold):
    docs = _DOCS
    rows = []
    for r in recs:
        fmt = doc_fmt
        if fmt not in C.FORMATS:
            raise LookupError(f'rendering {fmt} not built (scripts/build_renderings.sh)')
        is_xml = fmt.startswith('dgml') and '_compact' not in fmt
        p = C.doc_path(fmt, r['key'])
        if not os.path.exists(p):
            continue
        if p not in docs:
            docs[p] = Doc(p, is_xml)
        rows += analyse_doc(docs[p], [r], gold)
    return rows


def analyse_doc(d, recs, gold):
    """One row per cited figure of recs, all resolved in the document d."""
    rows = []
    for r in recs:
        ops = operands(gold.get(r['id'], {}).get('program'))
        for c in r.get('citations') or []:
            n = num_of(c['value'])
            if not n:
                continue
            el = c.get('element') or ''
            m = re.match(r'[A-Za-z_][\w.-]*', el.split('/')[-1].strip())
            tag = m.group(0) if m else ''
            path = cited_path(el) if 'path' in (r.get('answer_mode') or '') else ''
            npath = 0
            if d.is_xml and '/' in path:
                # as written, then with a repeated tag collapsed: an excerpt is labeled with its element's
                # own path and opens with that element, and the model often names it twice
                segs = path.split('/')
                once = '/'.join(s for i, s in enumerate(segs) if not i or s != segs[i - 1])
                for p_ in dict.fromkeys((path, once)):
                    if npath := d.n_name(segs[-1], n, p_):
                        break
            nn = d.n_name(tag, n) if d.is_xml and tag else 0
            nl = d.n_label(el, n) if el else 0
            route, k = next(((rt, x) for rt, x in (('path', npath), ('name', nn), ('label', nl)) if x), (None, 0))
            rows.append(dict(id=r['id'], route=route, k=k, nv=d.n_value(n), gold=n in ops))
    return rows


def summary(rows):
    def part(rs):
        n = len(rs)
        if not n:
            return None
        res = [x for x in rs if x['route']]
        return dict(n=n,
                    located=len(res) / n,
                    by_name=sum(x['route'] in ('name', 'path') for x in rs) / n,
                    pinned=sum(x['k'] == 1 for x in res) / n,
                    value_unique=sum(x['nv'] == 1 for x in rs) / n)
    return part(rows), part([x for x in rows if x['gold']])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--split', default='dev', choices=['dev', 'test', 'all'])
    ap.add_argument('--model', default='')
    ap.add_argument('--compact-as-text', action='store_true', help='check DGML compact citations as plain text')
    a = ap.parse_args()
    universe = sorted(q['id'] for q in C.load_questions(a.split))
    gold = {g['id']: g for g in json.load(open(C.GOLD_COMPUTATIONS))}
    model = a.model or (C.result_models() or [C.MODEL_SLUG])[0]
    print(f"{'row':<56}{'cites':>6}{'located':>9}{'by name':>9}{'traceable':>11}{'gold traceable':>16}{'value only 1':>14}{'traceable/1M':>14}")
    for label, cond, recs, paid in REP.rows_for(model, universe):
        recs = [r for r in recs.values() if r.get('citations') is not None]
        if not recs:
            continue
        rows = []
        try:
            for r in recs:   # a fallback row mixes conditions: each answer resolves in its own document
                rows += analyse(K.document_of(r.get('format') or cond, not a.compact_as_text), [r], gold)
        except LookupError as e:
            print(f'{label:<56}  skipped: {e}')
            continue
        al, go = summary(rows)
        if not al:
            continue
        pinned = sum(1 for x in rows if x['route'] and x['k'] == 1)
        g = REP.gross(paid)
        print(f"{label:<56}{al['n']:>6}{100*al['located']:>8.0f}%{100*al['by_name']:>8.0f}%{100*al['pinned']:>10.0f}%"
              f"{100*go['pinned'] if go else 0:>15.0f}%{100*al['value_unique']:>13.0f}%{1e6*pinned/g if g else 0:>14.1f}")


if __name__ == '__main__':
    main()
