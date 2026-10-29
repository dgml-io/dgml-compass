#!/usr/bin/env python3
"""Draw figures/accuracy_traceable.svg: correct answers against traceable citations, one segment per
system from its dev point to its test point. Every value is recomputed from results/reference/ with the
same code as report.py and provenance.py (renderings must be built: dgr renderings).

    uv run dgr figure
"""
import json
import os
from html import escape

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dgml_reasoning import conditions as K
from dgml_reasoning import config as C
from dgml_reasoning import provenance as P
from dgml_reasoning import report as REP
from dgml_reasoning import score as S

SYSTEMS = [  # label, row name in conditions.py, DGML?
    ('DGML-Nav-Path', 'DGML navigation, path citations + compact fallback', True),
    ('DGML-Nav', 'DGML navigation + compact fallback', True),
    ('DGML-Compact', 'DGML compact, full read, program prompt', True),
    ('DGML', 'DGML, full read, program prompt', True),
    ('MD-PyMuPDF', 'PDF markdown, pymupdf4llm 2.0, full read, program prompt', False),
    ('MD-Rules', 'PDF markdown, pymupdf4llm 0.0.27, full read, program prompt', False),
    ('MD-Plumber', 'PDF markdown, pdfplumber, full read, program prompt', False),
    ('TXT-Poppler', 'PDF text, poppler, full read, program prompt', False),
]


def measure():
    gold = {g['id']: g for g in json.load(open(C.GOLD_COMPUTATIONS))}
    model = C.result_models()[0]
    out, search = {}, {}
    for split in ('dev', 'test'):
        universe = sorted(q['id'] for q in C.load_questions(split))
        rows = {label.split(' (')[0]: (cond, recs) for label, cond, recs, paid in REP.rows_for(model, universe)}
        for lab, name, _ in SYSTEMS:
            cond, recs = rows[name]
            cites = []
            for r in recs.values():
                cites += P.analyse(K.document_of(r.get('format') or cond), [r], gold)
            al, _ = P.summary(cites)
            out[(lab, split)] = (100 * sum(S.correct(r, 'prec+computed') for r in recs.values()) / len(universe),
                                 100 * al['pinned'])
            if lab == 'DGML':
                search[split] = 100 * al['value_unique']
    return out, search


def svg(points, search):
    W, H, ml, mr, mt, mb = 900, 500, 64, 150, 40, 56
    xs = [p[0] for p in points.values()]
    x0, x1 = 2 * int(min(xs) // 2) - 2, 2 * int(max(xs) // 2) + 4
    y0, y1 = 0, 90
    X = lambda v: ml + (v - x0) / (x1 - x0) * (W - ml - mr)  # noqa: E731
    Y = lambda v: H - mb - (v - y0) / (y1 - y0) * (H - mt - mb)  # noqa: E731
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         'font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif" role="img" '
         'aria-label="Correct answers against traceable citations: DGML systems 56-85% traceable, markdown 16-33%, same accuracy range">',
         '<style>.bg{fill:#ffffff}.fg{fill:#1f2328}.mu{fill:#59636e}.grid{stroke:#e4e6ea}.ax{stroke:#8c959f}'
         '.band{fill:#8c959f;fill-opacity:.12}.bandl{stroke:#8c959f}.dev{fill:#2563c9;stroke:#2563c9}.test{fill:#d9661f;stroke:#d9661f}'
         '.hole{fill:#ffffff}.link{stroke:#1f2328}.mdlink{stroke:#8c959f}'
         '@media (prefers-color-scheme: dark){.bg{fill:#0d1117}.fg{fill:#e6edf3}.mu{fill:#9198a1}.grid{stroke:#262c36}'
         '.ax{stroke:#656c76}.dev{fill:#6ea2ff;stroke:#6ea2ff}.test{fill:#ff9a55;stroke:#ff9a55}.hole{fill:#0d1117}'
         '.link{stroke:#e6edf3}}</style>',
         f'<rect class="bg" width="{W}" height="{H}"/>']
    for v in range(y0, y1 + 1, 10):
        o.append(f'<line class="grid" x1="{ml}" x2="{W - mr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                 f'<text class="mu" x="{ml - 10}" y="{Y(v) + 4:.1f}" font-size="12" text-anchor="end">{v}%</text>')
    for v in range(x0, x1 + 1, 2):
        o.append(f'<line class="ax" x1="{X(v):.1f}" x2="{X(v):.1f}" y1="{H - mb}" y2="{H - mb + 5}"/>'
                 f'<text class="mu" x="{X(v):.1f}" y="{H - mb + 20}" font-size="12" text-anchor="middle">{v}%</text>')
    o.append(f'<text class="mu" x="{(ml + W - mr) / 2}" y="{H - 14}" font-size="13" text-anchor="middle">correct answers</text>')
    cy = (mt + H - mb) / 2
    o.append(f'<text class="mu" x="18" y="{cy}" font-size="13" text-anchor="middle" transform="rotate(-90 18 {cy})">traceable citations</text>')
    lo, hi = min(search.values()), max(search.values())
    o.append(f'<rect class="band" x="{ml}" y="{Y(hi):.1f}" width="{W - ml - mr}" height="{Y(lo) - Y(hi):.1f}"/>')
    for v in (lo, hi):
        o.append(f'<line class="bandl" x1="{ml}" x2="{W - mr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke-dasharray="5 4"/>')
    o.append(f'<text class="mu" x="{ml + 8}" y="{Y((lo + hi) / 2) + 4:.1f}" font-size="12">searching the number alone</text>')
    anchors = []
    for lab, _, dgml in SYSTEMS:
        d, t = points[(lab, 'dev')], points[(lab, 'test')]
        (dx, dy), (tx, ty) = (X(d[0]), Y(d[1])), (X(t[0]), Y(t[1]))
        o.append(f'<line class="{"link" if dgml else "mdlink"}" x1="{dx:.1f}" y1="{dy:.1f}" x2="{tx:.1f}" y2="{ty:.1f}" '
                 f'stroke-width="{2.2 if dgml else 1.2}" stroke-opacity="{.45 if dgml else .8}"'
                 f'{"" if dgml else " stroke-dasharray=\"3 3\""}/>')
        anchors.append((max((dx, dy), (tx, ty)), lab, dgml))
    # labels in a column right of the plot, at least 18 px apart, each joined to its segment's end
    anchors.sort(key=lambda a: a[0][1])
    ys = []
    for (ax, ay), _, _ in anchors:
        ys.append(max(ay, ys[-1] + 18) if ys else ay)
    col = W - mr + 14
    for ((ax, ay), lab, dgml), yy in zip(anchors, ys):
        o.append(f'<polyline class="ax" fill="none" stroke-width="0.8" stroke-opacity=".6" '
                 f'points="{ax + 8:.1f},{ay:.1f} {col - 18:.1f},{yy:.1f} {col - 4:.1f},{yy:.1f}"/>')
        o.append(f'<text class="{"fg" if dgml else "mu"}" x="{col:.1f}" y="{yy + 4:.1f}" font-size="13" '
                 f'font-weight="{600 if dgml else 400}" font-family="ui-monospace,SFMono-Regular,Menlo,monospace">{escape(lab)}</text>')
    for lab, _, dgml in SYSTEMS:   # points on top of lines and leaders
        for split, cls in (('dev', 'dev'), ('test', 'test')):
            x, y = X(points[(lab, split)][0]), Y(points[(lab, split)][1])
            if dgml:
                o.append(f'<circle class="{cls}" cx="{x:.1f}" cy="{y:.1f}" r="7" stroke-width="0"/>')
            else:
                o.append(f'<circle class="{cls} hole" cx="{x:.1f}" cy="{y:.1f}" r="6" stroke-width="2.2" style="fill:none"/>')
    lx = ml + 12
    o.append(f'<circle class="dev" cx="{lx}" cy="16" r="6"/><text class="mu" x="{lx + 12}" y="20" font-size="12">dev split</text>')
    o.append(f'<circle class="test" cx="{lx + 90}" cy="16" r="6"/><text class="mu" x="{lx + 102}" y="20" font-size="12">test split</text>')
    o.append(f'<text class="mu" x="{lx + 180}" y="20" font-size="12">filled: DGML (cites element names or paths) · hollow: markdown from the same PDF</text>')
    o.append('</svg>')
    return '\n'.join(o) + '\n'


def main():
    points, search = measure()
    os.makedirs(os.path.join(ROOT, 'figures'), exist_ok=True)
    path = os.path.join(ROOT, 'figures', 'accuracy_traceable.svg')
    open(path, 'w').write(svg(points, search))
    for (lab, split), (acc, tr) in sorted(points.items()):
        print(f'{lab:<13} {split:<5} correct {acc:5.1f}%  traceable {tr:4.0f}%')
    print(f'search the number: {search}  -> {os.path.relpath(path, ROOT)}')


if __name__ == '__main__':
    main()
