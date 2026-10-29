"""The shipped data is internally consistent: 30 filings, 233 questions, one DGML and one PDF per filing."""
import json
import os
import xml.etree.ElementTree as ET

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
DATA = os.path.join(ROOT, 'data')
REF = os.path.join(ROOT, 'results', 'reference', 'azure-deepseek-v4-flash-0731')
SPLITS = {'dev': (15, 122), 'test': (15, 111)}


def _q():
    return json.load(open(os.path.join(DATA, 'questions.json')))['questions']


def _man():
    return json.load(open(os.path.join(DATA, 'manifest.json')))


def test_questions_match_manifest():
    q, man = _q(), _man()
    assert {x['key'] for x in q} == {d['key'] for d in man}
    for split, (n_files, n_q) in SPLITS.items():
        qs = [x for x in q if x.get('split', 'dev') == split]
        assert len(qs) == n_q and len({x['key'] for x in qs}) == n_files, split
    for d in man:
        assert sum(1 for x in q if x['key'] == d['key']) == d['n_questions'], d['key']
    gold = {r['id'] for r in json.load(open(os.path.join(DATA, 'gold_computations.json')))}
    assert gold == {x['id'] for x in q}


def test_one_dgml_and_one_pdf_per_filing():
    for d in _man():
        k, split = d['key'], d.get('split', 'dev')
        pdf = os.path.join(DATA, 'pdf', split, k + '.pdf')
        assert open(pdf, 'rb').read(5) == b'%PDF-', k
        root = ET.parse(os.path.join(DATA, 'docs', 'dgml', k + '.dgml.xml')).getroot()   # well-formed
        assert len(''.join(root.itertext()).split()) > 10_000, k
    assert len(os.listdir(os.path.join(DATA, 'docs', 'dgml'))) == len(_man())


def test_reference_answers_cover_both_splits():
    q = {x['id']: x.get('split', 'dev') for x in _q()}
    for cond in os.listdir(REF):
        ids = {f[:-5] for f in os.listdir(os.path.join(REF, cond)) if f.endswith('.json')}
        assert ids <= set(q), cond
        for split in {q[i] for i in ids}:
            want = {i for i, s in q.items() if s == split}
            assert ids & want == want, (cond, split, len(want - ids))
