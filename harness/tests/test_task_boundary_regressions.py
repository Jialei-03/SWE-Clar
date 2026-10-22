"""Regression checks for task boundary behavior artifact replay."""
import ast
from copy import deepcopy
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]

def test_arabic_labels_use_spatial_order_not_extraction_run_order():
    import unicodedata
    check=isolated_function('SWECLAR-011','pdf_checks.py','spatial_arabic_label_matches')
    check.__globals__['unicodedata']=unicodedata
    expected='المعرّف'
    glyphs=[{'character':c,'box':(100-i*5,0,104-i*5,5)} for i,c in enumerate(expected)]
    # Arbitrary extraction run order is harmless when actual glyph positions agree.
    assert check(list(reversed(glyphs)),expected)
    assert not check([g for g in glyphs if g['character']!='ّ'],expected)
    wrong=[dict(g) for g in glyphs]
    wrong[0]['box'],wrong[2]['box']=wrong[2]['box'],wrong[0]['box']
    assert not check(wrong,expected)
    assert not check(glyphs+[{'character':'ا','box':(200,0,204,5)}],expected)

def test_arabic_mark_filter_does_not_hide_broken_letter_bodies():
    check=isolated_function('SWECLAR-011','pdf_checks.py','exclude_diacritic_components')
    bodies=[(10,30,20,60),(32,45,20,60),(14,20,4,15)]
    assert check(bodies,[(13,21,3,16)])==bodies[:2]
    assert check(bodies,[])==bodies
    assert check(bodies,[(10,30,4,15)])==bodies[:2]

def isolated_function(task, file, name):
    source=ROOT/'SWE-Clar/tasks'/task/'evaluation/tests'/file
    tree=ast.parse(source.read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    scope={}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(source),'exec'),scope)
    return scope[name]

def test_review_notice_uses_current_revision_amount_not_literal():
    check=isolated_function('SWECLAR-001','listing_contract.py','assert_review_notice')
    for revision in (1,2):
        offer={'external_id':'offer/one','revision':revision,'listing_id':'parcel-a','amount':190000+revision,'terms':'Synthetic terms'}
        notice={'sequence':revision,'kind':'arbitrary-review-kind','offer_id':offer['external_id'],'actor':'seller-a','revision':revision,'listing_id':'parcel-a','data':{'amount':offer['amount'],'terms':offer['terms']}}
        check({'notifications':[]},{'notifications':[notice]},offer)
        wrong=deepcopy(notice);wrong['data']['amount']=190003
        with pytest.raises(AssertionError):check({'notifications':[]},{'notifications':[wrong]},offer)
        with pytest.raises(AssertionError):check({'notifications':[]},{'notifications':[]},offer)
        with pytest.raises(AssertionError):check({'notifications':[]},{'notifications':[notice,notice]},offer)

def test_snapshot_fault_handlers_do_not_reenter_network_fetch():
    source=ROOT/'SWE-Clar/tasks/SWECLAR-100/evaluation/tests/browser_check.py'
    tree=ast.parse(source.read_text())
    assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='fetch' for n in ast.walk(tree))
    assert "['checksum','decode','http']" in source.read_text()

def test_pdf_labels_removed_per_page_without_eating_prose():
    import re
    spans=isolated_function('SWECLAR-090','test_solution.py','page_number_spans')
    spans.__globals__['re']=re
    text='Sentence 2 describes fictional\nPage 2 of 4\n'
    for start,end in reversed(spans(text,2,4)):
        text=text[:start]+text[end:]
    assert text.strip()=='Sentence 2 describes fictional'
    assert spans('Sentence 2 describes fictional plants',2,4)==[]

def test_photo_membership_still_rejects_wrong_or_missing_images():
    check=isolated_function('SWECLAR-099','test_solution.py','assert_photo_membership')
    rows=[{'url':'/photos/a','eligible':True},{'url':'/photos/late','eligible':False}]
    check(['/photos/a','/photos/late'],['/photos/a'],rows,rows[1])
    for timeline,grid in [(['/photos/a'],['/photos/a']),(['/photos/a','/photos/late'],['/photos/late']),(['/photos/a','/photos/a'],['/photos/a'])]:
        with pytest.raises(AssertionError):check(timeline,grid,rows,rows[1])
