"""The scoring rules, pinned. None of this needs a model or the documents."""
import os

import pytest

from dgml_reasoning import score as S


def test_exact_within_half_a_percent():
    assert S.compare('72.83%', '72.8%') == 'exact'
    assert S.compare('4575515', '4,575,515') == 'exact'
    assert S.compare('72.83%', '71%') == 'wrong'


def test_scaled_is_a_formatting_slip_not_a_wrong_figure():
    assert S.compare('3.4%', '0.034') == 'scaled'
    assert S.compare('0.034', '3.4') == 'scaled'


def test_not_found_and_missing():
    assert S.compare('5', 'NOT_FOUND') == 'not_found'
    assert S.compare('5', None) == 'missing'
    assert S.compare('5', '   ') == 'missing'


def test_accounting_negatives_and_separators():
    assert S.parse_num('(1,234)') == -1234
    assert S.parse_num('-19') == -19
    assert S.compare('-19', '(19)') == 'exact'


def test_an_answer_left_as_arithmetic_is_worth_its_value():
    assert S.eval_expr('16/3') == pytest.approx(16 / 3)
    assert S.eval_expr('(19-33)/33') == pytest.approx(-14 / 33)
    assert S.eval_expr('import os') is None          # nothing but arithmetic runs
    assert S.eval_expr('2**100000') is None           # ** is not whitelisted
    assert S.rounds_to_gold('5.3', '16/3')


def test_rounds_to_gold_at_golds_own_precision():
    assert S.rounds_to_gold('14%', '14.16%')
    assert S.rounds_to_gold('1.7%', '1.74%')
    assert not S.rounds_to_gold('14%', '15.2%')
    assert not S.rounds_to_gold('1.7%', '1.76%')


def test_three_readings_are_nested():
    rec = dict(id='x', gold='14%', answer='14.16%')
    assert not S.correct(rec, 'strict')
    assert S.correct(rec, 'prec')
    assert S.correct(rec, 'prec+computed')
    rec = dict(id='x', gold='14%', answer='14.0%')
    assert all(S.correct(rec, m) for m in S.MODES)


@pytest.mark.skipif(not os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'gold_computations.json')),
                    reason='data/ not in this checkout')
def test_computed_gold_comes_from_the_finqa_program():
    # ZBH row0021: gold '72.83%', program divide(384.3, 527.7) = 0.72825... -> '72.825...%'
    qid = 'ZBH_2003_0000950137-04-001881__row0021'
    g2 = S.computed_gold(qid, '72.83%')
    assert g2 is not None and g2.endswith('%')
    assert S.compare('72.83%', g2) == 'exact'
    assert S.computed_gold('no-such-question', '1') is None


def test_a_long_filing_keeps_its_beginning(monkeypatch):
    monkeypatch.setenv('LLM_MODEL', 'test/model')
    from dgml_reasoning import run as R
    C = R.C
    doc = '\n'.join(f'line {i} word word word' for i in range(1, 401))
    budget = C.tokens_from_text(doc) // 4                                 # about a quarter fits
    kept, st = R.fit_to_budget(doc, budget)
    lines = [ln for ln in kept.replace(R.TRUNC_NOTE, '').splitlines() if ln.startswith('line ')]
    assert st['truncated'] and st['truncation'] == 'head' and kept.endswith(R.TRUNC_NOTE)
    assert int(lines[0].split()[1]) == 1 and 80 <= int(lines[-1].split()[1]) <= 100
    assert C.tokens_from_text('\n'.join(lines)) <= budget
    assert R.fit_to_budget(doc, 10 * budget) == (doc, dict(truncated=False, kept_chars=len(doc), original_chars=len(doc),
                                                         kept_fraction=1.0, est_doc_tokens=C.tokens_from_text(doc)))
