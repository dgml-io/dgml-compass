"""The shipped numbers: report.py and provenance.py must keep reproducing the tables of docs/RESULTS.md from
results/reference/. If a scoring rule, the row logic or the citation check changes, this notices."""
import os
import subprocess
import sys

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
MODEL = 'azure-deepseek-v4-flash-0731'
N = {'dev': 122, 'test': 111}

# row -> correct answers (prec+computed), as in docs/RESULTS.md and report.py
ACCURACY = {
    'dev': {
        'DGML, full read': 72, 'DGML compact, full read': 75,
        'PDF markdown, pymupdf4llm 2.0, full read': 75, 'PDF markdown, pymupdf4llm 0.0.27, full read': 77,
        'PDF markdown, pdfplumber, full read': 75, 'PDF text, poppler, full read': 76,
        'DGML, full read, program prompt': 78, 'DGML compact, full read, program prompt': 83,
        'PDF markdown, pymupdf4llm 2.0, full read, program prompt': 80,
        'PDF markdown, pymupdf4llm 0.0.27, full read, program prompt': 81,
        'PDF markdown, pdfplumber, full read, program prompt': 79, 'PDF text, poppler, full read, program prompt': 81,
        'DGML navigation': 71, 'DGML navigation + compact fallback (12 q)': 79,
        'DGML navigation, compact excerpts': 70, 'DGML navigation, compact excerpts + compact fallback (9 q)': 75,
        'DGML navigation, path citations': 76, 'DGML navigation, path citations + compact fallback (10 q)': 79,
    },
    'test': {
        'DGML, full read': 74, 'DGML compact, full read': 76,
        'PDF markdown, pymupdf4llm 2.0, full read': 77, 'PDF markdown, pymupdf4llm 0.0.27, full read': 75,
        'PDF markdown, pdfplumber, full read': 77, 'PDF text, poppler, full read': 74,
        'DGML, full read, program prompt': 76, 'DGML compact, full read, program prompt': 78,
        'PDF markdown, pymupdf4llm 2.0, full read, program prompt': 77,
        'PDF markdown, pymupdf4llm 0.0.27, full read, program prompt': 78,
        'PDF markdown, pdfplumber, full read, program prompt': 79, 'PDF text, poppler, full read, program prompt': 79,
        'DGML navigation': 66, 'DGML navigation + compact fallback (18 q)': 75,
        'DGML navigation, compact excerpts': 63, 'DGML navigation, compact excerpts + compact fallback (17 q)': 73,
        'DGML navigation, path citations': 68, 'DGML navigation, path citations + compact fallback (17 q)': 76,
        'DGML compact, full read, run 2': 77, 'DGML compact, full read, program prompt, run 2': 78,
    },
}
# row -> (traceable %, gold-figure traceable %, traceable per 1M tokens), as in docs/RESULTS.md
TRACEABLE = {
    'dev': {'DGML navigation, path citations + compact fallback (10 q)': (82, 79, 31.2),
            'DGML navigation + compact fallback (12 q)': (64, 66, 26.9),
            'DGML compact, full read, program prompt': (56, 67, 10.3),
            'DGML, full read, program prompt': (61, 66, 6.8),
            'PDF markdown, pymupdf4llm 2.0, full read, program prompt': (31, 33, 6.8)},
    'test': {'DGML navigation, path citations + compact fallback (17 q)': (85, 84, 31.2),
             'DGML navigation + compact fallback (18 q)': (74, 73, 28.3),
             'DGML compact, full read, program prompt': (67, 73, 12.0),
             'DGML, full read, program prompt': (61, 65, 7.4),
             'PDF markdown, pymupdf4llm 2.0, full read, program prompt': (31, 32, 6.5)},
}


def _run(args):
    return subprocess.run([sys.executable] + args, capture_output=True, text=True, check=True, cwd=ROOT).stdout


@pytest.mark.parametrize('split', ['dev', 'test'])
def test_accuracy_reproduces(split):
    rows = {}
    for line in _run(['-m', 'dgml_reasoning.report', '--model', MODEL, '--split', split, '--markdown']).splitlines():
        if line.startswith('| ') and not line.startswith('| condition'):
            c = [x.strip() for x in line.strip('|').split('|')]
            rows[c[0]] = (int(c[1]), int(c[2]), int(c[3]), int(c[4]))
    for label, want in ACCURACY[split].items():
        assert label in rows, (split, label)
        n, s, p, pc = rows[label]
        assert n == N[split] and pc == want and s <= p <= pc, (split, label, rows[label], want)


@pytest.mark.parametrize('split', ['dev', 'test'])
def test_traceability_reproduces(split):
    docs = os.path.join(ROOT, 'data', 'docs')
    if not all(os.path.isdir(os.path.join(docs, d)) for d in ('dgml_compact', 'markdown_pdf')):
        pytest.skip('renderings not built (scripts/build_renderings.sh)')
    got = {}
    for line in _run(['-m', 'dgml_reasoning.provenance', '--split', split]).splitlines()[1:]:
        for label in TRACEABLE[split]:
            if line.startswith(label + ' '):
                f = line[len(label):].split()   # cites located by-name traceable gold value-only traceable/1M
                got[label] = (int(f[3].rstrip('%')), int(f[4].rstrip('%')), float(f[6]))
    assert got == TRACEABLE[split], (split, got)


def test_tokens_count_every_call_retries_included():
    """Gross tokens include the retried calls (full-read and navigation call-2 retries from attempts_log,
    the lost first navigation call estimated at its cap): pinned on three rows of docs/RESULTS.md."""
    rows = {}
    for line in _run(['-m', 'dgml_reasoning.report', '--model', MODEL, '--split', 'dev', '--markdown']).splitlines():
        if line.startswith('| ') and not line.startswith('| condition'):
            c = [x.strip() for x in line.strip('|').split('|')]
            rows[c[0]] = int(c[5].replace(',', ''))
    assert rows['DGML compact, full read, program prompt'] == 14_787_293
    assert rows['DGML navigation + compact fallback (12 q)'] == 6_330_999
    assert rows['DGML navigation, path citations + compact fallback (10 q)'] == 6_995_503
