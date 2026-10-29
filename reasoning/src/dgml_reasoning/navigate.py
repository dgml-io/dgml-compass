#!/usr/bin/env python3
"""DGML navigation: the model reads the filing's element outline, picks elements, then answers from them.

    dgr run dev_dgml_nav_program --yes          # the recorded way (configs/experiments.json)
    dgr navigate --split dev --limit 5

  Call 1  the element outline (data/docs/dgml_outline/<key>.outline.txt: one line per distinct
          element path, tag names and nesting, no text) + the question -> up to TR_XPATHS line ids
  Call 2  those elements, each with TR_SIBLINGS siblings on each side and widened TR_WIDEN
          ancestor levels, + the question -> the answer

Settings (environment, recorded per experiment):
  BENCH_DGML_FORMAT     the DGML rendering navigated and read (default dgml)
  BENCH_CONDITION       results/reference/<model>/<condition>/ (default dgml_nav)
  TR_XPATHS             ids call 1 may name (default 5)
  TR_SIBLINGS           sibling elements fetched on each side of a pick (default 0)
  TR_WIDEN              ancestor levels fetched around a pick (default 1)
  BENCH_REGION_RENDER   "compact": call 2 reads the elements in DGML compact instead of DGML
  BENCH_ANSWER_MODE     "cite+program": the program prompt (answermode.py); "cite+path+program": figures
                        cited by their element path
  BENCH_R2_RETRY        "1": call 2 is retried as a full read is (run.chat_retrying) when it spends
                        its whole budget without an answer

The question is asked before the outline or the excerpts and repeated after them. The prompt
texts below are the ones the reference answers were produced with: changing a word changes the
benchmark.
"""
import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

from dgml_reasoning import answermode
from dgml_reasoning import config as C
from dgml_reasoning import llm
from dgml_reasoning.run import SYSTEM, atomic_write, chat_retrying

DGML_FMT = os.environ.get('BENCH_DGML_FORMAT', 'dgml')
CONDITION = os.environ.get('BENCH_CONDITION', 'dgml_nav')
OUTLINE_DIR = C.outline_dir(DGML_FMT)
MAX_XPATHS = int(os.environ.get('TR_XPATHS', 5))
SIBLINGS = int(os.environ.get('TR_SIBLINGS', 0))
WIDEN = int(os.environ.get('TR_WIDEN', 1))
REGION_RENDER = os.environ.get('BENCH_REGION_RENDER', '').strip().lower()
R2_RETRY = os.environ.get('BENCH_R2_RETRY', '').strip() == '1'
# Excerpts are never cut below what a full read sends: a blind cut would make the result depend
# on the cap rather than on the picks.
MAX_CONTENT = 1_500_000
# Call 1 reasons over an outline of thousands of lines before it emits the <xpaths> block; a budget
# that runs out mid-trace would look like a navigation failure.
R1_MAX_TOKENS = 16000

R1_SYSTEM = (
    'You are given the ELEMENT STRUCTURE of an XML financial filing: tag names and '
    'nesting, with all text removed. Every line starts with an id (L0, L1, ...) '
    'followed by the indented tag name. "xN" means the element repeats N times.\n'
    'Given a question, pick the line id(s) whose content would answer it.\n'
    'Prefer the enclosing container -- a whole table or a whole section -- over a '
    'single row or a single value: a row without its headers cannot be read.\n'
    f'Decide quickly -- do not enumerate candidates at length. Reply with one id '
    f'per line inside <xpaths></xpaths>, best first, at most {MAX_XPATHS}. Reply '
    'with the ids only, for example:\n'
    '<xpaths>\nL2184\nL910\n</xpaths>')

# Call 2 answers under the system prompt of every full read, with one sentence changed.
R2_SYSTEM = SYSTEM.replace(
    'You are given one document and one question about it.',
    'You are given excerpts from one document, selected because they should '
    'contain the answer, and one question about it.')


def r1_user(question, outline, tail=''):
    return f'Question: {question}\n\n<schema>\n{outline}\n</schema>\n\nQuestion: {question}{tail}'


def name_paths(root):
    """path -> [elements], paths written without indices (/chunk/Debt/DebtTable)."""
    out = {}

    def walk(el, path):
        p = path + '/' + el.tag
        out.setdefault(p, []).append(el)
        for k in el:
            walk(k, p)
    walk(root, '')
    return out


def parse_selection(text, lines):
    """The picked paths: line ids first, raw paths as a fallback (some replies give a path)."""
    m = re.search(r'<xpaths>(.*?)</xpaths>', text or '', re.S | re.I)
    body = m.group(1) if m else (text or '')
    out = []
    for lid in re.findall(r'\bL(\d+)\b', body):
        p = lines.get('L' + lid)
        if p and p not in out:
            out.append(p)
    if not out:
        for line in body.splitlines():
            line = re.sub(r'^[-*\d.)\s]+', '', line.strip().strip('`')).split(' ')[0]
            if line.startswith('/'):
                p = re.sub(r'\[\d+\]', '', line).rstrip('/')
                if p not in out:
                    out.append(p)
    return out[:MAX_XPATHS]


def resolve(pred, index):
    """A picked path -> real paths. A path that does not exist verbatim is matched on its tail,
    longest tail first, shallowest (largest container) hits first."""
    if pred in index:
        return [pred]
    segs = pred.strip('/').split('/')
    for n in range(min(3, len(segs)), 0, -1):
        tail = '/' + '/'.join(segs[-n:])
        hits = [k for k in index if k.endswith(tail)]
        if hits:
            return sorted(hits, key=lambda k: k.count('/'))[:2]
    return []


def render_element(el):
    """The element as DGML, or in DGML compact (make_compact.py) when BENCH_REGION_RENDER=compact."""
    if REGION_RENDER == 'compact':
        from dgml_reasoning.make_compact import compact
        return compact(el)
    return ET.tostring(el, encoding='unicode')


def collect(paths, index, parents):
    """The excerpts: for each picked path, its first three elements, each widened WIDEN ancestor
    levels and with SIBLINGS siblings on each side; an element reached twice is emitted once."""
    chunks, used, emitted = [], [], set()
    for p in paths:
        for real in resolve(p, index):
            if real in used:
                continue
            used.append(real)
            picked = []
            for el in index[real][:3]:
                for _ in range(WIDEN):
                    par = parents.get(el)
                    if par is None:
                        break
                    el = par
                picked.append(el)
                if SIBLINGS:
                    par = parents.get(el)
                    if par is not None:
                        sibs = list(par)
                        i = sibs.index(el) if el in sibs else 0
                        picked.extend(sibs[max(0, i - SIBLINGS): i + SIBLINGS + 1])
            for el in picked:
                if id(el) in emitted:
                    continue
                emitted.add(id(el))
                chunks.append(f'<region path="{real}">\n' + render_element(el) + '\n</region>')
    return '\n'.join(chunks)[:MAX_CONTENT], used


def run_one(q, force=False):
    path = C.answer_path(CONDITION, q['id'])
    if not force and os.path.exists(path):
        try:
            if json.load(open(path)).get('ok'):
                return None
        except Exception:
            pass
    key = q['key']
    outline_p = os.path.join(OUTLINE_DIR, key + '.outline.txt')
    doc_p = C.doc_path(DGML_FMT, key)
    rec = dict(id=q['id'], key=key, question=q['question'], gold=q['gold'], format=CONDITION,
               model=C.MODEL, api_base=llm.endpoint_label(), client=llm.CLIENT, provider=C.PROVIDER,
               reasoning_effort=C.REASONING_EFFORT, temperature=C.TEMPERATURE, top_p=C.TOP_P,
               tokenizer=C.TOKENIZER, outline_source=os.path.basename(outline_p), doc_source=os.path.basename(doc_p))
    t0 = time.time()
    try:
        outline = open(outline_p, encoding='utf-8').read()
        lines = json.load(open(outline_p.replace('.outline.txt', '.lines.json')))
        rec['outline_chars'] = len(outline)
        r1 = llm.chat([{'role': 'system', 'content': R1_SYSTEM},
                       {'role': 'user', 'content': r1_user(q['question'], outline)}],
                      max_tokens=R1_MAX_TOKENS, temperature=C.TEMPERATURE)
        _, r1_reason, r1_raw = llm.split_output(r1)
        preds = parse_selection(r1_raw, lines)
        r1_retried = False
        if not preds:
            # an empty selection is the trace running to the cap: retry with reasoning off
            r1_retried = True
            rec['r1_first_usage'] = r1.get('usage', {})
            r1 = llm.chat([{'role': 'system', 'content': R1_SYSTEM},
                           {'role': 'user', 'content': r1_user(q['question'], outline,
                            '\n\nAnswer immediately with the <xpaths> block. Do not explain or work through candidates.')}],
                          max_tokens=R1_MAX_TOKENS, temperature=C.TEMPERATURE, reasoning_effort='')
            _, r1_reason, r1_raw = llm.split_output(r1)
            preds = parse_selection(r1_raw, lines)
        rec.update(predicted_xpaths=preds, r1_reasoning_chars=len(r1_reason), r1_retried=r1_retried,
                   r1_usage=r1.get('usage', {}))

        root = ET.parse(doc_p).getroot()
        content, used = collect(preds, name_paths(root), {c: p for p in root.iter() for c in p})
        rec.update(matched_xpaths=used, content_chars=len(content), widen=WIDEN, siblings=SIBLINGS)

        msgs = [{'role': 'system', 'content': R2_SYSTEM + answermode.system_suffix()},
                {'role': 'user', 'content': f'Question: {q["question"]}\n\n{content}\n\nQuestion: {q["question"]}'}]
        if R2_RETRY:
            # gross tokens count every attempt: attempts_log as in a full read, r2_usage the last one
            r2, answer, reasoning, raw, fin, _, attempts = chat_retrying(msgs, max_tokens=C.MAX_TOKENS)
            rec.update(attempts_log=attempts, retried_degenerate=len(attempts) - 1, finish_reason=fin)
        else:
            r2 = llm.chat(msgs, max_tokens=C.MAX_TOKENS, temperature=C.TEMPERATURE)
            answer, reasoning, raw = llm.split_output(r2)
        rec.update(ok=True, answer=answer, reasoning=reasoning, raw_content=raw, r2_usage=r2.get('usage', {}))
        if answermode.MODE:
            answermode.apply(rec, raw, content, is_xml=REGION_RENDER != 'compact')
    except Exception as e:
        rec.update(ok=False, answer=None, error=f'{type(e).__name__}: {e}')
    rec['elapsed_s'] = round(time.time() - t0, 2)
    atomic_write(path, rec)
    return rec


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--split', default='dev', choices=['dev', 'test', 'all'])
    ap.add_argument('--format', default='', help='another DGML rendering to navigate (e.g. dgml_regenerated); '
                    'answers then go to <format>_nav... instead of dgml_nav...')
    ap.add_argument('--docs', default='', help='comma list of filing key prefixes')
    ap.add_argument('--limit', type=int)
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--force', action='store_true', help='redo questions that already have an answer')
    a = ap.parse_args()
    global DGML_FMT, OUTLINE_DIR, CONDITION
    if a.format and a.format != DGML_FMT:
        if a.format not in C.FORMATS:
            sys.exit(f'unknown format: {a.format} (known: {", ".join(C.FORMATS)})')
        CONDITION = CONDITION.replace(DGML_FMT, a.format, 1)
        DGML_FMT, OUTLINE_DIR = a.format, C.outline_dir(a.format)
    if not C.MODEL:
        sys.exit('no model: launch through `dgr run <experiment> --yes` (see configs/experiments.json)')
    qs = C.load_questions(a.split, a.docs)[:a.limit or None]
    print(f'DGML navigation over "{DGML_FMT}", {len(qs)} questions -> results/reference/<model>/{CONDITION}/')
    n = err = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(run_one, q, a.force) for q in qs]
        for i, fu in enumerate(as_completed(futs), 1):
            r = fu.result()
            if r is None:
                continue
            n += 1
            err += not r['ok']
            if r['ok']:
                print(f'[{i}/{len(qs)}] {r["id"][-26:]:<28} {r["content_chars"]:>6}ch gold={r["gold"]!r} got={r["answer"]!r} {r["elapsed_s"]}s')
            else:
                print(f'[{i}/{len(qs)}] {r["id"][-26:]:<28} ERR {r["error"][:70]}')
    print(f'\ndone {n}, errors {err}')


if __name__ == '__main__':
    main()
