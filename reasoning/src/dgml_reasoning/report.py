#!/usr/bin/env python3
"""The results table: every shipped condition, recomputed from results/reference/. No model is called.

    dgr report                      # the dev split
    dgr report --split test
    dgr report --markdown           # as a markdown table

Rows are defined in conditions.py. Any further condition directory (your own runs) gets a row
named after it. Tokens are the provider's usage figures, gross: all input + output tokens of every
call a row made, retries included (navigation makes two calls; a fallback pays for the navigation and
the full read).
correct / 1M = prec+computed correct answers per million gross tokens.
"""
import argparse
import os
import sys

from dgml_reasoning import conditions as K
from dgml_reasoning import config as C
from dgml_reasoning import score as S


def answers(model, condition, universe):
    t = S.load_condition(model, condition)
    return {q: t[q] for q in universe if q in t and t[q].get('ok')}


def resolve(model, condition, fallback, universe):
    """-> ({question: final record}, [every record that was paid for], number of fallbacks)."""
    main = answers(model, condition, universe)
    if not fallback:
        return main, list(main.values()), 0
    full = answers(model, fallback, universe)
    out, paid, n = {}, list(main.values()), 0
    for q, r in main.items():
        if S.compare(r.get('gold'), r.get('answer')) == 'not_found' and q in full:
            out[q] = full[q]; paid.append(full[q]); n += 1
        else:
            out[q] = r
    return out, paid, n


# A navigation answer whose first call returned no picks retried it with reasoning off; answers
# recorded before run-time accounting (r1_first_usage) lost that first call's usage. It is estimated
# as the retry's prompt plus a completion at the call-1 cap (an empty selection is a trace that ran
# to the cap): 31 of the shipped 466 navigation answers.
R1_CAP = 16000


def gross(recs):
    """All input + output tokens of every call the records made, retries included."""
    t = 0
    for j in recs:
        for k in ('usage', 'r1_first_usage', 'r1_usage', 'r2_usage'):
            u = j.get(k) or {}
            t += (u.get('prompt_tokens') or 0) + (u.get('completion_tokens') or 0)
        # full read: an answer that ran out of tokens was asked again (run.py); `usage` is the last
        # attempt, attempts_log holds every attempt (same prompt, its own completion)
        log = j.get('attempts_log') or []
        for a in log[:-1]:
            t += (a.get('prompt_tokens') or (j.get('usage') or {}).get('prompt_tokens') or 0) + (a.get('completion_tokens') or 0)
        if j.get('r1_retried') and not j.get('r1_first_usage'):
            t += ((j.get('r1_usage') or {}).get('prompt_tokens') or 0) + R1_CAP
    return t


def rows_for(model, universe):
    mdir = os.path.join(C.RESULTS, model)
    extra = sorted(d for d in os.listdir(mdir) if os.path.isdir(os.path.join(mdir, d)) and d not in K.KNOWN)
    for name, cond, fb in K.ROWS + [(d, d, None) for d in extra]:
        recs, paid, n_fb = resolve(model, cond, fb, universe)
        if recs:
            yield (f'{name} ({n_fb} q)' if fb else name), cond, recs, paid


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model', default='', help='results/reference/<model>/ (default: the one with most answers)')
    ap.add_argument('--split', default='dev', choices=['dev', 'test', 'all'])
    ap.add_argument('--markdown', action='store_true')
    a = ap.parse_args()
    if not C.result_models():
        sys.exit(f'no answer files under {C.RESULTS}/ -- run an experiment first: dgr run <experiment> --yes')
    model = a.model or C.result_models()[0]
    universe = sorted(q['id'] for q in C.load_questions(a.split))
    out = []
    for label, cond, recs, paid in rows_for(model, universe):
        hits = {m: sum(S.correct(r, m) for r in recs.values()) for m in S.MODES}
        g = gross(paid)
        out.append((label, len(recs), hits, g, 1e6 * hits['prec+computed'] / g if g else 0))
    n = len(universe)
    print(f'results/reference/{model}  --  split {a.split}, {n} questions\n')
    if a.markdown:
        print('| condition | answered | strict | prec | prec+computed | gross tokens | correct / 1M |')
        print('|---|---:|---:|---:|---:|---:|---:|')
        for label, k, h, g, pm in out:
            print(f"| {label} | {k} | {h['strict']} | {h['prec']} | {h['prec+computed']} | {g:,} | {pm:.1f} |")
        return
    w = max(len(r[0]) for r in out) + 2
    print(f"{'condition':<{w}}{'answered':>9}{'strict':>8}{'prec':>6}{'prec+comp':>11}{'gross tokens':>15}{'correct/1M':>12}")
    for label, k, h, g, pm in out:
        print(f"{label:<{w}}{k:>9}{h['strict']:>8}{h['prec']:>6}{h['prec+computed']:>11}{g:>15,}{pm:>12.1f}")
    print('\nstrict < prec < prec+computed: see score.py. Tokens: gross input + output over every call of the row.')


if __name__ == '__main__':
    main()
