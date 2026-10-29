#!/usr/bin/env python3
"""Full read: ask every question against the whole filing in one rendering.

    dgr run dev_dgml_compact_program --yes     # the recorded way (configs/experiments.json)
    dgr answer --format dgml_compact --split dev --limit 3
    dgr answer --format dgml --check                 # endpoint and what is present, one tiny call

One call per question. Each answer is its own file, results/reference/<model>/<condition>/<id>.json,
written atomically; an existing successful answer is skipped, so an interrupted run resumes
(--force redoes). <condition> is the format, plus "@<suffix>" when BENCH_CONDITION_SUFFIX is set
(the program prompt runs use "program"). The prompt is the same for every rendering except for
the document itself; the rendering is never named in it.

A filing longer than the prompt budget (LLM_MAX_PROMPT_TOKENS, counted with the model's own
tokenizer) keeps its beginning, cut at a line, with a note saying so. Questions run grouped by
filing, so the system message plus the document is a shared prefix the provider can cache.
"""
import argparse
import json
import os
import sys
import tempfile
import time

from dgml_reasoning import answermode
from dgml_reasoning import config as C
from dgml_reasoning import llm

# The system prompt every condition shares. Changing a word here changes the benchmark; the
# reference answers used exactly this text.
SYSTEM = (
    "You are a careful financial-document analyst. You are given one document "
    "and one question about it. Find the relevant figures in the document and "
    "compute the answer.\n"
    "Reason briefly - at most 150 words - then answer. Do not restate the "
    "document or enumerate every table you looked at.\n"
    "Give your final answer inside <answer></answer> tags, containing only the "
    "value itself with no explanation or units unless the question asks for them. "
    "If the document does not contain enough information, put NOT_FOUND inside "
    "the tags."
)
TRUNC_NOTE = ("\n\n[Note: this document was truncated to fit the context window; "
              "the excerpt above may not contain the answer.]")


def build_prompt(content, question):
    return (f'<document>\n{content}\n</document>\n\n'
            f'Question: {question}\n\n'
            f'Give the final answer inside <answer></answer> tags.')


def atomic_write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(obj, f, indent=1, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def chat_retrying(msgs, **kw):
    """The call, retried when it spent the whole completion budget without an <answer>.

    A reasoning model can loop and spend the whole budget (finish_reason=length). Greedy decoding
    cannot escape it: retry with a little temperature, then with a brevity cap.
    -> (last response, answer, reasoning, raw, finish_reason, usage, attempts_log)."""
    system = msgs[0]['content']
    attempts = []

    def ask(temp):
        resp = llm.chat(msgs, temperature=temp, **kw)
        answer, reasoning, raw = llm.split_output(resp)
        fin = (resp.get('choices') or [{}])[0].get('finish_reason')
        usage = resp.get('usage') or {}
        attempts.append(dict(temperature=temp, finish_reason=fin, prompt_tokens=usage.get('prompt_tokens'),
                             completion_tokens=usage.get('completion_tokens'), got_answer=answer is not None))
        return resp, answer, reasoning, raw, fin, usage

    resp, answer, reasoning, raw, fin, usage = ask(C.TEMPERATURE)
    for temp, extra in ((0.3, ''), (0.7, '\nAnswer now. Give at most two sentences '
                                         'of reasoning, then the <answer> tag.')):
        if answer is not None or fin != 'length':
            break
        msgs[0]['content'] = system + extra
        resp, answer, reasoning, raw, fin, usage = ask(temp)
    return resp, answer, reasoning, raw, fin, usage, attempts


def fit_to_budget(content, budget_tokens):
    """The document, or its beginning cut at a line boundary to fit budget_tokens (with a safety
    margin), measured line by line with the model's tokenizer (config.tokens_from_text)."""
    est = C.tokens_from_text(content)
    if est <= budget_tokens:
        return content, dict(truncated=False, kept_chars=len(content), original_chars=len(content),
                             kept_fraction=1.0, est_doc_tokens=est)
    target = int(budget_tokens * C.SAFETY)
    lines = content.split('\n')
    i = used = 0
    while i < len(lines):
        cost = C.tokens_from_text(lines[i]) + 1      # +1: the newline
        if used + cost > target:
            break
        used += cost
        i += 1
    kept = '\n'.join(lines[:i])
    return kept + TRUNC_NOTE, dict(truncated=True, truncation='head', kept_chars=len(kept),
                                   original_chars=len(content), kept_fraction=round(len(kept) / len(content), 4),
                                   est_doc_tokens=est, est_kept_tokens=C.tokens_from_text(kept),
                                   budget_tokens=budget_tokens)


def one(fmt, q, budget):
    out = C.answer_path(fmt, q['id'])
    src = C.doc_path(fmt, q['key'])
    with open(src, encoding='utf-8', errors='replace') as f:
        content = f.read()
    content, trunc = fit_to_budget(content, budget)
    prompt = build_prompt(content, q['question'])
    rec = dict(id=q['id'], format=fmt, key=q['key'], docfinqa_row=q['docfinqa_row'],
               question=q['question'], gold=q['gold'], finqa_id=q.get('finqa_id'),
               source_page=q.get('source_page'), ticker=q.get('ticker'), fiscal_year=q.get('fiscal_year'),
               source_file=os.path.relpath(src, C.ROOT), doc_chars=len(content), prompt_chars=len(prompt),
               model=C.MODEL, api_base=llm.endpoint_label(), client=llm.CLIENT, provider=C.PROVIDER,
               reasoning_effort=C.REASONING_EFFORT, temperature=C.TEMPERATURE, top_p=C.TOP_P,
               tokenizer=C.TOKENIZER, **trunc)
    t0 = time.time()
    try:
        system = SYSTEM + answermode.system_suffix()
        msgs = [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}]
        resp, answer, reasoning, raw, fin, usage, rec['attempts_log'] = chat_retrying(msgs)
        rec['retried_degenerate'] = len(rec['attempts_log']) - 1
        rec.update(ok=True, answer=answer, reasoning=reasoning, raw_content=raw, usage=usage,
                   finish_reason=fin, elapsed_s=resp.get('_elapsed_s'), answer_tag_found=answer is not None)
        if answermode.MODE:
            answermode.apply(rec, raw, content, is_xml=fmt.startswith('dgml') and '_compact' not in fmt)
    except Exception as e:
        rec.update(ok=False, error=f'{type(e).__name__}: {e}', elapsed_s=round(time.time() - t0, 2))
    atomic_write(out, rec)
    return rec


def done_ok(fmt, qid):
    p = C.answer_path(fmt, qid)
    try:
        return bool(json.load(open(p)).get('ok'))
    except Exception:
        return False                                  # missing, unreadable, or a recorded failure: redo


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--format', default='', help=f'the rendering to read: {", ".join(C.FORMATS)}')
    ap.add_argument('--split', default='dev', choices=['dev', 'test', 'all'])
    ap.add_argument('--docs', default='', help='comma list of filing key prefixes, e.g. IPG_2008')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--force', action='store_true', help='redo questions that already have an answer')
    ap.add_argument('--max-prompt-tokens', type=int, default=C.MAX_PROMPT_TOKENS)
    ap.add_argument('--check', action='store_true', help='smoke-test the endpoint and report what is present')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    if not C.MODEL:
        sys.exit('no model: launch through `dgr run <experiment> --yes` (see configs/experiments.json)')
    if C._TOKENIZER_SPEC.startswith('hf:') and C.TOKENIZER != C._TOKENIZER_SPEC[3:]:
        sys.exit(f'tokenizer {C._TOKENIZER_SPEC} could not be loaded: a run would cut long filings differently '
                 'from the recorded answers (needs tokenizers + huggingface_hub and network the first time)')
    if not a.format or a.format not in C.FORMATS:
        sys.exit(f'unknown format: {a.format} (known: {", ".join(C.FORMATS)}; scripts/build_renderings.sh builds them)')
    qs = sorted(C.load_questions(a.split, a.docs), key=lambda x: (x['key'], int(x['docfinqa_row'])))
    if a.check:
        keys = {q['key'] for q in qs}
        print(f'{a.format}: documents {sum(os.path.exists(C.doc_path(a.format, k)) for k in keys)}/{len(keys)}, '
              f'answers {sum(done_ok(a.format, q["id"]) for q in qs)}/{len(qs)}')
        llm.smoke_test()
        return
    todo = [q for q in qs if a.force or not done_ok(a.format, q['id'])][:a.limit or None]
    sizes = {}
    for q in todo:
        if q['key'] not in sizes:
            sizes[q['key']] = C.tokens_from_text(open(C.doc_path(a.format, q['key']), encoding='utf-8', errors='replace').read())
    n_cut = sum(1 for q in todo if sizes[q['key']] > a.max_prompt_tokens)
    print(f'{len(todo)} calls to make ({a.format}, model {C.MODEL}); {n_cut} on a filing cut to {a.max_prompt_tokens:,} tokens')
    if a.dry_run:
        return
    t0, fail = time.time(), 0
    for i, q in enumerate(todo, 1):
        r = one(a.format, q, a.max_prompt_tokens)
        fail += not r.get('ok')
        print(f"[{i}/{len(todo)}] {r['id']:<44} {'OK ' if r.get('ok') else 'ERR'} "
              f"gold={str(r.get('gold'))[:14]!r} got={str(r.get('answer'))[:20]!r} {r.get('elapsed_s')}s", flush=True)
    print(f'\ndone {len(todo)}, errors {fail}, {time.time() - t0:.0f}s total; score with: dgr report')


if __name__ == '__main__':
    main()
