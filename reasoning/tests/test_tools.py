"""dgml_outline.py: the converter-output import keeps every word, the outline is one line per
distinct element path; provenance.py counts the places a citation leads to."""
import os
import xml.etree.ElementTree as ET

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
from dgml_reasoning import dgml_outline as A

SRC = '''<dg:chunk xmlns:dg="http://dgml.io/ns/dg#" xmlns:docset="http://x/ds"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <docset:Revenue dg:structure="table" dg:origin="1 2 3 4 5" dg:style="b">
    <dg:chunk dg:structure="tr">
      <docset:LineItem dg:structure="td">Total revenue</docset:LineItem>
      <docset:Amount dg:structure="td" xsi:type="xsd:decimal" dg:value="10180">10,180</docset:Amount>
    </dg:chunk>
  </docset:Revenue>
  <docset:Note dg:structure="p">We are a leading provider.</docset:Note>
</dg:chunk>'''


def test_import_keeps_words_and_drops_grounding_markup():
    root = ET.fromstring(SRC)
    lite = A.to_lite(root)
    assert A.words_of(root) == A.words_of(lite)
    text = ET.tostring(lite, encoding='unicode')
    assert 'dg:origin' not in text and 'xsi:type' not in text and 'dg:value' not in text
    assert '<Revenue r="table">' in text and '<tr>' in text and '<LineItem r="td">' in text
    assert '<Note r="p">We are a leading provider.</Note>' in text


def test_outline_is_one_line_per_distinct_path():
    lite = A.to_lite(ET.fromstring(SRC))
    text, index = A.render_outline(lite.tag, A.build_trie(lite))
    assert text.splitlines()[0] == 'L0  chunk'
    assert index['L1'] == '/chunk/Revenue' and index['L2'] == '/chunk/Revenue/tr'
    assert set(index.values()) == {'/chunk', '/chunk/Revenue', '/chunk/Revenue/tr',
                                   '/chunk/Revenue/tr/LineItem', '/chunk/Revenue/tr/Amount', '/chunk/Note'}


def test_provenance_counts_places(tmp_path):
    from dgml_reasoning import provenance as P
    xml = ('<chunk><Debt><Principal r="td">375</Principal><Rate r="td">3.0%</Rate></Debt>'
           '<Other><Principal r="td">375</Principal></Other><p>Total 375 and 1,234</p></chunk>')
    p = tmp_path / 'd.dgml.xml'; p.write_text(xml)
    d = P.Doc(str(p), is_xml=True)
    assert d.n_name('Principal', '375') == 2 and d.n_name('Rate', '3.0') == 1
    assert d.n_value('375') == 3 and d.n_value('1234') == 1
    md = tmp_path / 'd.md'; md.write_text('| Principal amount | 375 |\n\nNote 16 Debt\n\nlong text ' + 'x ' * 300 + '375')
    t = P.Doc(str(md), is_xml=False)
    assert t.n_label('Principal amount', '375') == 1 and t.n_label('Note 16 Debt', '375') == 0
    assert P.num_of('$375 million') == '375' and P.num_of('(62,259)') == '62259' and P.num_of('3.0%') == '3'


def test_a_cited_path_pins_what_the_name_alone_does_not(tmp_path):
    from dgml_reasoning import provenance as P
    xml = ('<chunk><Debt><Principal r="td">375</Principal></Debt>'
           '<Other><Principal r="td">375</Principal></Other></chunk>')
    p = tmp_path / 'd.dgml.xml'; p.write_text(xml)
    d = P.Doc(str(p), is_xml=True)
    assert d.n_name('Principal', '375') == 2
    assert d.n_name('Principal', '375', 'chunk/Debt/Principal') == 1
    assert d.n_name('Principal', '375', 'Debt/Principal') == 1          # a tail of the path
    assert d.n_name('Principal', '375', 'Notes/Principal') == 0
    assert P.cited_path('/chunk/Debt[2]/Principal (2015)') == 'chunk/Debt/Principal'
    assert P.cited_path('Principal') == 'Principal'
    rec = dict(id='q', key='d', answer_mode='cite+path+program',
               citations=[dict(value='375', element='/chunk/Debt/Debt/Principal')])
    assert [x['route'] for x in P.analyse_doc(d, [rec], {})] == ['path']   # the repeated Debt collapsed
