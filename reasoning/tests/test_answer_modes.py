"""Answer modes (cite, program), the DGML compact serialization, sampling and token counting. Offline."""
import importlib
import os
import xml.etree.ElementTree as ET

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')

DOC = ('<chunk><Debt r="section"><header>Debt</header><DebtTable r="table">'
       '<tr><td>Item</td><td>2015</td><td>2014</td></tr>'
       '<LongTermDebtNet r="tr"><td>Long-term debt, net</td><td>15,261</td><td>6,142</td></LongTermDebtNet>'
       '<InterestExpense r="tr"><td>Interest expense</td><td>443</td><td>340</td></InterestExpense>'
       '</DebtTable></Debt><Notes><p>Rent expense was 1,234 in 2015.</p></Notes></chunk>')



@pytest.fixture(autouse=True)
def _restore_environment():
    """Each test sets the variables it needs; afterwards the environment and the modules that read
    it at import are restored, so no test depends on another's leftovers."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)
    from dgml_reasoning import answermode
    from dgml_reasoning import config
    from dgml_reasoning import llm
    for m in (config, llm, answermode):
        importlib.reload(m)


def _mode(mode):
    os.environ['BENCH_ANSWER_MODE'] = mode
    from dgml_reasoning import answermode
    return importlib.reload(answermode)

def test_evidence_and_program_are_parsed_and_verified():
    am = _mode('cite+program')
    raw = ('<evidence>\n15,261 | LongTermDebtNet\n6,142 | LongTermDebtNet\n9,999 | InterestExpense\n</evidence>\n'
           '<program>subtract(15261, 6142)</program>\n<answer>9,119</answer>')
    cites = am.parse_evidence(raw)
    assert [c['value'] for c in cites] == ['15,261', '6,142', '9,999']
    cites, share = am.verify_citations(cites, DOC, is_xml=True)
    assert [c['verified'] for c in cites] == [True, True, False]
    assert abs(share - 2 / 3) < 1e-9
    assert am.parse_program(raw) == 'subtract(15261, 6142)'
    rec = am.apply(dict(answer='9,119'), raw, DOC, is_xml=True)
    assert rec['answer'] == '9119' and rec['answer_model'] == '9,119' and rec['program_value'] == 9119
    os.environ.pop('BENCH_ANSWER_MODE'); importlib.reload(am)


def test_path_mode_asks_for_paths_and_leaves_the_name_prompt_unchanged():
    am = _mode('cite+program')
    assert am.system_suffix() == am.CITE_TEXT + am.PROGRAM_TEXT
    am = _mode('cite+path+program')
    assert am.system_suffix() == am.CITE_PATH_TEXT + am.PROGRAM_TEXT and 'value | path' in am.CITE_PATH_TEXT
    cites, _ = am.verify_citations(am.parse_evidence('<evidence>15,261 | /chunk/Debt/DebtTable/LongTermDebtNet'
                                                     '</evidence>'), DOC, is_xml=True)
    assert cites[0]['verified_by'] == 'element'
    os.environ.pop('BENCH_ANSWER_MODE'); importlib.reload(am)


def test_program_keeps_the_percentage_unit_of_the_model():
    am = _mode('program')
    answer, value = am.execute('divide(subtract(15261, 6142), 6142)', '148.5%')
    assert answer.endswith('%') and abs(float(answer[:-1]) - 148.5) < 0.1
    answer, value = am.execute('not a program', '12')
    assert answer == '12' and value is None
    os.environ.pop('BENCH_ANSWER_MODE'); importlib.reload(am)


def test_citation_against_markdown_uses_the_label_line():
    am = _mode('cite')
    md = '| Long-term debt, net | 15,261 | 6,142 |\n| Interest expense | 443 | 340 |'
    cites, share = am.verify_citations([dict(value='15,261', element='Long-term debt, net'),
                                        dict(value='443', element='Rent')], md, is_xml=False)
    assert cites[0]['verified'] and cites[0]['verified_by'] == 'label'
    assert not cites[1]['verified'] and cites[1].get('value_in_text')
    # DGML: a qualified element name verifies by element; a cited row label (generic row
    # tags) verifies by label even when the cells sit on separate lines
    cites, share = am.verify_citations([dict(value='15,261', element='LongTermDebtNet (2015)'),
                                        dict(value='443', element='Interest expense')],
                                       DOC.replace('</td>', '</td>\n'), is_xml=True)
    assert [c['verified_by'] for c in cites] == ['element', 'label'] and share == 1
    # a qualified label still finds its row; a bare short word does not verify anything
    cites, _ = am.verify_citations([dict(value='443', element='Interest expense - 2015'),
                                    dict(value='443', element='Item')], DOC, is_xml=True)
    assert cites[0]['verified_by'] == 'label' and not cites[1]['verified']
    os.environ.pop('BENCH_ANSWER_MODE'); importlib.reload(am)


def test_compact_serialization_keeps_figures():
    from dgml_reasoning.make_compact import compact
    plain = compact(ET.fromstring(DOC))
    assert 'LongTermDebtNet: Long-term debt, net | 15,261 | 6,142' in plain and '</' not in plain
    assert 'Rent expense was 1,234 in 2015.' in plain

def test_top_p_is_sent_only_when_set():
    os.environ.update(LLM_MODEL='x', LLM_TOP_P='0.95')
    from dgml_reasoning import config
    from dgml_reasoning import llm
    importlib.reload(config)
    L = importlib.reload(llm)
    assert L._payload([{'role': 'user', 'content': 'hi'}], {})['top_p'] == 0.95
    os.environ.pop('LLM_TOP_P')
    importlib.reload(config)
    L = importlib.reload(llm)
    assert 'top_p' not in L._payload([{'role': 'user', 'content': 'hi'}], {})


def test_token_count_selection():
    os.environ.update(LLM_MODEL='azure/DeepSeek-V4-Flash-0731', LLM_TOKENIZER='words')
    from dgml_reasoning import config
    Cw = importlib.reload(config)
    assert Cw.TOKENIZER.startswith('words/') and Cw.tokens_from_text('one two three four') == int(4 / Cw.WORDS_PER_TOKEN)
    os.environ.pop('LLM_TOKENIZER')
    Ch = importlib.reload(config)
    n = Ch.tokens_from_text('Long-term debt, net 15,261 6,142')
    if Ch.TOKENIZER.startswith('words/'):
        pytest.skip('model tokenizer not loadable here (no tokenizers package or offline)')
    assert Ch.TOKENIZER == 'deepseek-ai/DeepSeek-V4-Flash-0731' and 5 < n < 20
    os.environ['LLM_MODEL'] = 'x'
    importlib.reload(config)
