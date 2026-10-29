#!/usr/bin/env python3
"""Evaluate a FinQA gold program, to see what it actually yields.

The gold answer and the gold program are separate annotations and do not always
agree: `multiply(375, 3%)` evaluates to 11.25 while the stated answer is 11.3. Most
of those gaps are rounding, but some are real inconsistencies — PM row0046's
program averages one table row while its answer comes from another — and a
question whose own annotation disagrees with itself cannot be answered correctly
by any system.

Handles the FinQA operator set, nesting, percentages and `const_*` literals.
Aggregates (`table_min(column, none)`) name a column rather than figures and evaluate to None.
"""
import re

CONST = re.compile(r'^const_(m?)(\d+(?:\.\d+)?)$')
OPS = {'add': lambda a, b: a + b, 'subtract': lambda a, b: a - b,
       'multiply': lambda a, b: a * b, 'divide': lambda a, b: a / b if b else None,
       'exp': lambda a, b: a ** b, 'greater': lambda a, b: 1.0 if a > b else 0.0}


def _atom(t):
    t = t.strip()
    m = CONST.match(t)
    if m:
        v = float(m.group(2))
        return -v if m.group(1) else v
    if t.endswith('%'):
        try: return float(t[:-1].replace(',', '')) / 100.0
        except ValueError: return None
    try: return float(t.replace(',', '').replace('$', ''))
    except ValueError: return None


def _split(args):
    """Split on top-level commas only, so nested calls survive."""
    out, depth, cur = [], 0, ''
    for ch in args:
        if ch == '(': depth += 1
        elif ch == ')': depth -= 1
        if ch == ',' and depth == 0:
            out.append(cur); cur = ''
        else:
            cur += ch
    if cur.strip(): out.append(cur)
    return out


def ev(expr):
    """-> float, or None if the program is an aggregate or cannot be evaluated."""
    if not expr: return None
    expr = expr.strip()
    m = re.match(r'^(\w+)\((.*)\)$', expr, re.S)
    if not m: return _atom(expr)
    op, args = m.group(1), _split(m.group(2))
    if op not in OPS: return None              # table_min / table_average etc.
    if len(args) != 2: return None
    a, b = ev(args[0]), ev(args[1])
    if a is None or b is None: return None
    # FinQA reads a percentage in add/subtract as RELATIVE to the first argument:
    # add(22560, 5%) is 22560 + 5% of 22560 = 23688, not 22560.05.
    if op in ('add', 'subtract') and args[1].strip().endswith('%'):
        b = a * b
    try: return OPS[op](a, b)
    except (ZeroDivisionError, OverflowError, ValueError): return None


