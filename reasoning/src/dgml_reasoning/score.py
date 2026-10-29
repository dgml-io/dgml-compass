#!/usr/bin/env python3
"""How an answer is judged.

    python -m dgml_reasoning.score                    # every condition of the default model
    python -m dgml_reasoning.score --model <slug>     # another results/reference/<slug>/ tree
    python -m dgml_reasoning.score --errors 5         # show mismatches per condition

Reads results/reference/<model>/<condition>/*.json only -- it never calls a model, so it
is safe on a partial set mid-run.

DocFinQA answers are numbers ("72.83%", "4575515", "-19"), so scoring is
numeric, and three progressively more forgiving readings are reported:

  strict         within 0.5% of the stated gold answer, plus a /100 pass
                 (0.034 for a gold of 3.4% is a formatting slip, not a wrong
                 figure)
  prec           also credits an answer that rounds to gold at gold's own
                 stated precision -- 14.16% for a gold of 14% -- and evaluates
                 an answer left as arithmetic ("16/3" for 5.3)
  prec+computed  also accepts the gold PROGRAM's own value as a reference. The
                 stated answer and the program are separate annotations and
                 disagree on ~15 questions: multiply(375, 3%) is 11.25 where the
                 answer says 11.3

The report shows all three. The README's accuracy figures use prec+computed (every
reading is in results/reference/ and in `dgr report`).
"""
import argparse
import ast
import glob
import json
import os
import re
import sys

from dgml_reasoning import config as C
from dgml_reasoning.eval_gold import ev

NUM = re.compile(r'-?\d[\d,]*\.?\d*')
EXPR_OK = re.compile(r'^[\d\s.,()+\-*/]+$')
MODES = ('strict', 'prec', 'prec+computed')


def eval_expr(s):
    """Evaluate an answer left as arithmetic, e.g. '16/3' or '(19-33)/33'.

    Parsed with ast and a whitelist of node types -- never eval() on the raw
    string -- so nothing but arithmetic runs.
    """
    t = (s or '').replace(',', '').replace('%', '').strip()
    if not t or not EXPR_OK.match(t) or not any(o in t for o in '+-*/'):
        return None
    try:
        tree = ast.parse(t, mode='eval')
    except SyntaxError:
        return None
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd)
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            return None
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            return None
    try:
        v = eval(compile(tree, '<expr>', 'eval'), {'__builtins__': {}}, {})
        return float(v) if isinstance(v, (int, float)) else None
    except (ZeroDivisionError, OverflowError, TypeError):
        return None


def parse_num(v):
    if v is None:
        return None
    s = str(v).strip().replace(',', '')
    neg = s.startswith('(') and s.endswith(')')
    m = NUM.search(s)
    if not m:
        return None
    try:
        x = float(m.group(0).replace(',', ''))
    except ValueError:
        return None
    return -x if neg else x


def gold_decimals(g):
    """Decimal places the annotator actually wrote."""
    m = re.search(r'-?[\d,]*\.?(\d*)', str(g).replace(',', ''))
    return len(m.group(1)) if m else 0


def rounds_to_gold(gold, ans):
    """Does the answer round to gold AT GOLD'S OWN STATED PRECISION?

    FinQA golds are often rounded to two significant figures ('1.7%', '4%')
    while a model answers in full ('1.74%', '4.49%'). A gold of '4%' carries
    zero decimals, so this accepts anything in [3.5, 4.5) -- a wide window,
    which is why it is a separate, reported reading and not the default.
    """
    g = parse_num(gold)
    a = eval_expr(ans)
    if a is None:
        a = parse_num(ans)
    if g is None or a is None:
        return False
    d = gold_decimals(gold)
    return any(round(c, d) == round(g, d) for c in (a, a * 100, a / 100))


_PROGRAMS = None


def gold_programs():
    """question id -> FinQA gold program."""
    global _PROGRAMS
    if _PROGRAMS is None:
        # the gold programs ship with data/; without them the computed reading is simply absent
        _PROGRAMS = ({r['id']: r.get('program') for r in json.load(open(C.GOLD_COMPUTATIONS))}
                     if os.path.exists(C.GOLD_COMPUTATIONS) else {})
    return _PROGRAMS


def computed_gold(qid, gold):
    """The gold program's own value, in the gold answer's units (a program yields
    a ratio where the stated answer is that ratio x100 on percentage questions)."""
    v = ev(gold_programs().get(qid))
    if v is None:
        return None
    return f'{v * 100}%' if '%' in str(gold) else f'{v}'


def compare(gold, ans, tol=0.005):
    """-> 'exact' | 'scaled' | 'wrong' | 'missing' | 'not_found'"""
    if ans is None or not str(ans).strip():
        return 'missing'
    if 'not_found' in str(ans).strip().lower():
        return 'not_found'
    g, a = parse_num(gold), parse_num(ans)
    e = eval_expr(ans)
    if e is not None and g is not None:
        if abs(e - g) <= tol * max(abs(e), abs(g), 1e-9):
            return 'exact'
        if abs(e * 100 - g) <= tol * max(abs(e * 100), abs(g), 1e-9):
            return 'scaled'
        a = e
    if g is None or a is None:
        return 'exact' if str(gold).strip().lower() == str(ans).strip().lower() else 'wrong'

    def close(x, y):
        if x == y:
            return True
        d = abs(x - y)
        return d <= tol * max(abs(x), abs(y), 1e-9) or d < 1e-6

    if close(g, a):
        return 'exact'
    if close(g, a * 100) or close(g, a / 100):
        return 'scaled'
    return 'wrong'


def correct(rec, mode='strict'):
    """Is this answer record right, under one of the three readings?"""
    gold, ans = rec.get('gold', ''), rec.get('answer', '')

    def ok(g):
        v = compare(g, ans)
        if v in ('exact', 'scaled'):
            return True
        return mode != 'strict' and v == 'wrong' and rounds_to_gold(g, ans)

    if ok(gold):
        return True
    if mode == 'prec+computed':
        g2 = computed_gold(rec.get('id', ''), gold)
        return bool(g2) and ok(g2)
    return False


def load_condition(model, condition):
    out = {}
    for p in sorted(glob.glob(os.path.join(C.RESULTS, model, condition, '*.json'))):
        try:
            j = json.load(open(p))
        except Exception as e:
            print(f'  unreadable {p}: {e}', file=sys.stderr)
            continue
        out[j.get('id', os.path.basename(p))] = j
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model', default='', help='results/reference/<model>/ to score (default: the one with most answers)')
    ap.add_argument('--errors', type=int, default=0, help='print up to N mismatches per condition')
    ap.add_argument('--split', default='dev', choices=['dev', 'test', 'all'], help='question split to score')
    ap.add_argument('--docs', default='', help='comma list of filing key prefixes')
    a = ap.parse_args()
    model = a.model or (C.result_models() or [C.MODEL_SLUG])[0]
    conds = sorted(d for d in os.listdir(os.path.join(C.RESULTS, model))
                   if os.path.isdir(os.path.join(C.RESULTS, model, d)))
    print(f'results/reference/{model}/\n')
    print(f"{'condition':<34}{'answered':>9}{'errors':>7}{'not_found':>10}"
          + ''.join(f'{m:>15}' for m in MODES))
    wanted = {q['id'] for q in C.load_questions(a.split, a.docs)}
    for c in conds:
        recs = {k: v for k, v in load_condition(model, c).items() if k in wanted}
        ok = [r for r in recs.values() if r.get('ok')]
        nf = sum(1 for r in ok if compare(r.get('gold'), r.get('answer')) == 'not_found')
        cols = ''.join(f'{sum(correct(r, m) for r in ok):>15}' for m in MODES)
        print(f'{c:<34}{len(ok):>9}{len(recs) - len(ok):>7}{nf:>10}{cols}')
        if a.errors:
            shown = 0
            for r in ok:
                if correct(r, 'prec+computed') or shown >= a.errors:
                    continue
                print(f"    {r['id'][-30:]:<32} gold={str(r.get('gold'))[:14]!r:<17} got={str(r.get('answer'))[:24]!r}")
                shown += 1
    print(f'\n{len(conds)} condition(s); modes: strict < prec < prec+computed (see --help)')


if __name__ == '__main__':
    main()
