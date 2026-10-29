"""navigate.py rebuilds, from each shipped DGML navigation answer's recorded picks, exactly the
excerpts that answer was given (same length, all 466 answers): the code that ships is the code the
reference answers came from."""
import glob
import importlib
import json
import os
import xml.etree.ElementTree as ET

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
REF = os.path.join(ROOT, 'results', 'reference', 'azure-deepseek-v4-flash-0731')
EXPERIMENT_ENV = {'dgml_nav@program': {}, 'dgml_nav_compact@program': {'BENCH_REGION_RENDER': 'compact'}}


@pytest.mark.parametrize('condition', sorted(EXPERIMENT_ENV))
def test_excerpts_rebuild_from_the_recorded_picks(condition, monkeypatch):
    monkeypatch.setenv('LLM_MODEL', 'x')
    for k, v in {'TR_XPATHS': '5', 'TR_SIBLINGS': '3', 'TR_WIDEN': '0', 'BENCH_REGION_RENDER': '',
                 **EXPERIMENT_ENV[condition]}.items():
        monkeypatch.setenv(k, v)
    from dgml_reasoning import navigate
    R = importlib.reload(navigate)
    docs, n = {}, 0
    for f in sorted(glob.glob(os.path.join(REF, condition, '*.json'))):
        r = json.load(open(f))
        if r['key'] not in docs:
            root = ET.parse(os.path.join(ROOT, 'data', 'docs', 'dgml', r['key'] + '.dgml.xml')).getroot()
            docs[r['key']] = (R.name_paths(root), {c: p for p in root.iter() for c in p})
        content, used = R.collect(r['predicted_xpaths'], *docs[r['key']])
        assert (len(content), used) == (r['content_chars'], r['matched_xpaths']), r['id']
        n += 1
    assert n == 233


def test_call_2_retries_when_it_runs_out_of_budget(tmp_path, monkeypatch):
    """BENCH_R2_RETRY: an answer cut at the budget is asked again as a full read is, every attempt logged
    and counted in the gross tokens."""
    monkeypatch.setenv('LLM_MODEL', 'x')
    for k, v in {'TR_XPATHS': '5', 'TR_SIBLINGS': '3', 'TR_WIDEN': '0', 'BENCH_REGION_RENDER': '',
                 'BENCH_CONDITION': 'retried', 'BENCH_R2_RETRY': '1'}.items():
        monkeypatch.setenv(k, v)
    from dgml_reasoning import navigate, report
    R = importlib.reload(navigate)
    src = json.load(open(sorted(glob.glob(os.path.join(REF, 'dgml_nav@program', '*.json')))[0]))
    # a one-line outline of the filing's first element: the test needs no built rendering
    root = ET.parse(os.path.join(ROOT, 'data', 'docs', 'dgml', src['key'] + '.dgml.xml')).getroot()
    (tmp_path / (src['key'] + '.outline.txt')).write_text(f'L0 {root[0].tag}\n')
    (tmp_path / (src['key'] + '.lines.json')).write_text(json.dumps({'L0': f'/{root.tag}/{root[0].tag}'}))
    monkeypatch.setattr(R, 'OUTLINE_DIR', str(tmp_path))
    monkeypatch.setattr(R.C, 'answer_path', lambda cond, qid: str(tmp_path / cond / (qid + '.json')))
    replies = iter([({'content': '<xpaths>\nL0\n</xpaths>'}, 'stop'),
                    ({'content': 'thinking...'}, 'length'), ({'content': '<answer>1</answer>'}, 'stop')])

    def chat(msgs, **kw):
        msg, fin = next(replies)
        return {'choices': [{'message': msg, 'finish_reason': fin}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
    monkeypatch.setattr(R.llm, 'chat', chat)
    rec = R.run_one(dict(id=src['id'], key=src['key'], question=src['question'], gold=src['gold']))
    assert rec['answer'] == '1' and rec['retried_degenerate'] == 1
    assert [a['finish_reason'] for a in rec['attempts_log']] == ['length', 'stop']
    assert report.gross([rec]) == 3 * 15                       # call 1, the cut call 2, its retry
    monkeypatch.delenv('BENCH_R2_RETRY')
    importlib.reload(navigate)
