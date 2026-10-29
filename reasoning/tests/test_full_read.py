"""run.py cuts a filing longer than the prompt budget exactly as the shipped answers record: same
kept length for every cut answer (the DGML full reads on the 2 long dev and 2 long test filings)."""
import glob
import importlib
import json
import os

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
REF = os.path.join(ROOT, 'results', 'reference', 'azure-deepseek-v4-flash-0731')


def test_cut_filings_keep_what_the_answers_record(monkeypatch):
    monkeypatch.setenv('LLM_MODEL', 'azure/DeepSeek-V4-Flash-0731')
    from dgml_reasoning import config
    importlib.reload(config)
    if not config.TOKENIZER.startswith('deepseek-ai/'):
        pytest.skip('the model tokenizer is not loadable here (tokenizers / huggingface_hub, network)')
    from dgml_reasoning import run
    R = importlib.reload(run)
    seen, n = {}, 0
    for cond in ('dgml', 'dgml@program'):
        for f in glob.glob(os.path.join(REF, cond, '*.json')):
            r = json.load(open(f))
            if not r.get('truncated'):
                continue
            if r['key'] not in seen:
                text = open(os.path.join(ROOT, 'data', 'docs', 'dgml', r['key'] + '.dgml.xml'), encoding='utf-8').read()
                seen[r['key']] = R.fit_to_budget(text, r['budget_tokens'])[1]['kept_chars']
            assert seen[r['key']] == r['kept_chars'], r['id']
            n += 1
    assert n == 2 * (7 + 13)
