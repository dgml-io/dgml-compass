"""The rows of the results tables, shared by report.py and provenance.py.

A row is (name, condition, fallback): the answers in results/reference/<model>/<condition>/, and
optionally a fallback condition whose answer replaces a NOT_FOUND (the full read the system falls
back to; it pays for both). Condition directories:

  <rendering>              full read, plain prompt (reason, then answer)
  <rendering>@program      full read, program prompt (cite every figure as `value | element`, give
                           the computation as a program the benchmark executes)
  dgml_nav@program         DGML navigation: the model reads the element outline of the filing
                           (data/docs/dgml_outline), names up to 5 elements, then reads those elements
                           (+3 siblings each) as DGML and answers -- two calls
  dgml_nav_compact@program the same, the picked elements given in DGML compact
  dgml_nav@program.path    dgml_nav@program with every figure cited by its element path
                           (`value | /chunk/Debt/DebtTable/LongTermDebtNet`), call 2 retried when it spends
                           its whole budget without an answer
  ...@r2, @program.r2      second runs of the same parameters (run-to-run spread)
"""
RENDERINGS = [
    ('DGML', 'dgml'),
    ('DGML compact', 'dgml_compact'),
    ('PDF markdown, pymupdf4llm 2.0', 'markdown_pdf'),
    ('PDF markdown, pymupdf4llm 0.0.27', 'markdown_pdf_rules'),
    ('PDF markdown, pdfplumber', 'markdown_pdf_plumber'),
    ('PDF text, poppler', 'markdown_pdf_poppler'),
]
FULL_READS = ([(f'{name}, full read', cond, None) for name, cond in RENDERINGS]
              + [(f'{name}, full read, program prompt', cond + '@program', None) for name, cond in RENDERINGS])
NAVIGATION = [
    ('DGML navigation', 'dgml_nav@program', None),
    ('DGML navigation + compact fallback', 'dgml_nav@program', 'dgml_compact@program'),
    ('DGML navigation, compact excerpts', 'dgml_nav_compact@program', None),
    ('DGML navigation, compact excerpts + compact fallback', 'dgml_nav_compact@program', 'dgml_compact@program'),
    ('DGML navigation, path citations', 'dgml_nav@program.path', None),
    ('DGML navigation, path citations + compact fallback', 'dgml_nav@program.path', 'dgml_compact@program'),
]
REPEATS = [
    ('DGML compact, full read, run 2', 'dgml_compact@r2', None),
    ('DGML compact, full read, program prompt, run 2', 'dgml_compact@program.r2', None),
]
ROWS = FULL_READS + NAVIGATION + REPEATS
KNOWN = {c for _, c, _ in ROWS}


def document_of(condition, resolve_in_dgml=True):
    """The rendering a condition's citations are checked against. Every DGML condition resolves in
    the DGML by default: DGML compact carries the same element names, and the DGML is the document
    an auditor traces a figure in. resolve_in_dgml=False checks DGML compact as plain text."""
    base = condition.split('@')[0]
    if base.startswith('dgml_nav'):
        return 'dgml'
    if base == 'dgml_compact':
        return 'dgml' if resolve_in_dgml else 'dgml_compact'
    return base
