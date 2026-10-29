"""Answer modes that use what DGML can offer the reader: cited elements and an
executable program. Selected with BENCH_ANSWER_MODE, recorded in every answer file.

  ''         the plain prompt: reason, then <answer>value</answer>
  cite       before the answer, an <evidence> block: one line per figure used,
             `value | element`, the element being the DGML tag the figure sits in
             (markdown: the row label or heading). The bench verifies each line
             against the text the model read: does an element of that name (or
             a line with that label) contain that value? -> citation_verified
  program    the computation as a FinQA-style program, <program>subtract(a, b)</program>,
             which the bench executes (eval_gold.ev); the executed value is
             the answer scored, the model's own <answer> is kept as answer_model
  cite+program  both
  path       with cite: the element is cited by its path in the DGML tree
             (`value | /chunk/Debt/DebtTable/LongTermDebtNet`), not its name alone;
             provenance.py resolves the path before the name

Why: the error analysis on the DGML rows found most full-read and navigation
errors in reading (wrong row or column) and arithmetic, not in finding the
section. Citing the element makes the first checkable; executing the program
removes the second. Markdown has no element to cite.
"""
import os
import re

from dgml_reasoning.eval_gold import ev

MODE = os.environ.get('BENCH_ANSWER_MODE', '').strip().lower()
CITE = 'cite' in MODE
PROGRAM = 'program' in MODE
PATH = 'path' in MODE

EVIDENCE = re.compile(r'<evidence>(.*?)</evidence>', re.S | re.I)
PROG = re.compile(r'<program>(.*?)</program>', re.S | re.I)
LABEL_WINDOW = 400   # chars after a cited label in which its value must appear (one table row)

CITE_TEXT = (
    "\nBefore the answer, list every figure you use inside <evidence></evidence>, one per "
    "line as `value | element`, where value is the figure exactly as printed and element is "
    "the name of the DGML element it sits in (for a document without element names, the row "
    "label or heading next to it). Cite only figures you actually read."
)
CITE_PATH_TEXT = (
    "\nBefore the answer, list every figure you use inside <evidence></evidence>, one per "
    "line as `value | path`, where value is the figure exactly as printed and path is the "
    "path of the DGML element it sits in: the tag names from the root element down to that "
    "element, separated by /, for example /chunk/Debt/DebtTable/LongTermDebtNet. Cite only "
    "figures you actually read."
)
PROGRAM_TEXT = (
    "\nThen give the computation inside <program></program> as nested calls over the figures "
    "as printed, using add(a, b), subtract(a, b), multiply(a, b), divide(a, b), exp(a, b) -- "
    "for example divide(subtract(15261, 6142), 6142). A figure that is itself the answer is "
    "its own program. The program is executed by the benchmark, so it must be exact."
)


def system_suffix():
    cite = (CITE_PATH_TEXT if PATH else CITE_TEXT) if CITE else ''
    return cite + (PROGRAM_TEXT if PROGRAM else '')


def parse_evidence(raw):
    m = EVIDENCE.search(raw or '')
    out = []
    if not m:
        return out
    for line in m.group(1).splitlines():
        line = line.strip().strip('-*• ').strip()
        if '|' not in line:
            continue
        value, element = [x.strip() for x in line.split('|', 1)]
        if value:
            out.append(dict(value=value, element=element.strip('<>/ ')))
    return out


def parse_program(raw):
    m = PROG.search(raw or '')
    if not m:
        return None
    p = re.sub(r'\s+', ' ', m.group(1)).strip().strip('`')
    return p or None


def _norm_num(s):
    s = s.replace(',', '').replace('$', '').strip()
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    return s


def _present(value, text):
    v = _norm_num(value)
    t = text.replace(',', '')
    return bool(v) and (v in t or value in text or (v.startswith('-') and f'({v[1:]})' in t))


def label_variants(el):
    """The label texts to look for from a cited element: the whole, then without
    parentheses, then the part before a ' - ' / ':' / ',' qualifier, then without a
    trailing year or column word. `Operating income - Consulting 2009` ->
    ['operating income - consulting 2009', 'operating income - consulting', 'operating income'].
    Short fragments (one word under 8 chars) are not used: 'Total' matches anything."""
    out = []
    cur = el.strip().lower()
    for cand in (cur, re.sub(r'\s*\(.*?\)\s*', ' ', cur).strip(),
                 re.split(r'\s+[-\u2013\u2014:,]\s+|:\s+', cur)[0].strip(),
                 re.sub(r'(\s+(19|20)\d\d|\s+(total|change|net|amount))+$', '', cur).strip()):
        cand = re.sub(r'\s+', ' ', cand)
        if cand and cand not in out and (len(cand) >= 8 or ' ' in cand):
            out.append(cand)
    return out


def verify_citations(citations, content, is_xml):
    """Mark each citation verified when the named element (DGML) or a line
    carrying the label (text) contains the value. Returns (citations, share).

    The element is read as its leading identifier: models write
    `InvestmentAmount (Mutual funds, 2011)` or `Debt/LongTermDebtNet`. When no
    element of that name holds the value, a line of the text that carries the
    cited label and the value also verifies it (verified_by = label): on DGML
    with generic row tags the model can only cite the label, as on markdown.
    verified_by tells the two apart."""
    if not citations:
        return citations, None

    def element_texts(tag):
        # the texts of every <tag ...>...</tag> in the content, by regex: retrieved
        # content is a concatenation of fragments, possibly cut, not one XML document
        if not tag:
            return []
        pat = re.compile(rf'<{re.escape(tag)}(?:\s[^>]*)?>(.*?)</{re.escape(tag)}>', re.S)
        return [re.sub(r'<[^>]+>', ' ', m.group(1)) for m in pat.finditer(content)]

    plain = re.sub(r'<[^>]+>', ' ', content) if is_xml else content
    low = plain.lower()
    ok = 0
    for c in citations:
        el, val = c['element'], c['value']
        m = re.match(r'[A-Za-z_][\w.-]*', el.split('/')[-1].strip())
        tag = m.group(0) if m else ''
        labels = label_variants(el)
        hit = None
        if is_xml:
            cands = element_texts(tag)
            c['element_found'] = bool(cands)
            if any(_present(val, t) for t in cands):
                hit = 'element'
        for lab in labels if hit is None else []:
            # the value within a row's reach (LABEL_WINDOW chars) after the label: a table
            # row spans several lines once the tags (or the flattened HTML) are stripped
            start = 0
            while (i := low.find(lab, start)) >= 0:
                if _present(val, plain[i:i + len(lab) + LABEL_WINDOW]):
                    hit = 'label'; break
                start = i + 1
            if hit: break
        if hit is None and _present(val, content):
            c['value_in_text'] = True
        c['verified'] = hit is not None
        c['verified_by'] = hit
        ok += hit is not None
    return citations, ok / len(citations)


def execute(program, model_answer):
    """-> (answer to score, executed value or None). A percentage question keeps
    the model's unit: if its own answer carried a %, the ratio is reported x100."""
    v = ev(program) if program else None
    if v is None:
        return model_answer, None
    if model_answer and '%' in model_answer and abs(v) < 1.5:
        return f'{v * 100:.4f}%', v
    if abs(v) >= 1 and v == int(v):
        return f'{int(v)}', v
    return f'{v:.6f}'.rstrip('0').rstrip('.'), v


def apply(rec, raw, content, is_xml):
    """Fill the answer-mode fields of a record from the model's raw reply."""
    rec['answer_mode'] = MODE
    if CITE:
        cites, share = verify_citations(parse_evidence(raw), content, is_xml)
        rec['citations'] = cites
        rec['citation_verified'] = share
    if PROGRAM:
        prog = parse_program(raw)
        rec['program_model'] = prog
        rec['answer_model'] = rec.get('answer')
        answer, value = execute(prog, rec.get('answer'))
        rec['program_value'] = value
        rec['answer'] = answer
    return rec
