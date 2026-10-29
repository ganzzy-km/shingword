"""Independent literal agreement can preserve the primary whitespace template."""
import copy
import pytest
from test_ocr_precision import line,picture,page,alternatives
from app.services.ocr_pipeline import select_precise_draft

def test_character_corroboration_retains_primary_spaces_and_codepoint_spans():
    box=[10,10,320,32];im=picture([box]);primary=line('잎의 무늬는 서로 다르다.',box)
    paddle=line('잎의 무늬는서로 다룬다.',box);tess=line('잎의 무늬는 서로 다룬다.',box)
    r=page(im,[primary],[primary],alternatives([paddle],[tess]),'prose');old=copy.deepcopy(r['draft'])
    select_precise_draft(im,r)
    assert r['draft']['text']=='잎의 무늬는 서로 다룬다.'
    assert r['precision']['before']==old
    unit=r['draft']['lineMap'][0];assert r['draft']['text'][unit['start']:unit['end']]=='잎의 무늬는 서로 다룬다.'
    assert any(x.get('reason')=='LOCAL_LITERAL_PRIMARY_WHITESPACE_PRESERVED' for d in r['precision']['decisions'] for x in d['changes'])

def test_primary_tabs_and_multiple_spaces_are_not_reformatted_by_corroboration():
    box=[10,10,320,32];im=picture([box]);before='잎의\t무늬는  서로 다르다.'
    r=page(im,[line(before,box)],[line(before,box)],alternatives([line('잎의 무늬는서로 다룬다.',box)],[line('잎의 무늬는 서로 다룬다.',box)]),'prose')
    select_precise_draft(im,r);assert r['draft']['text']=='잎의\t무늬는  서로 다룬다.'

@pytest.mark.parametrize('kind',['disagreement','different_length','punctuation','no_independent_engine','different_position','large_edit','native'])
def test_conflicting_or_incomplete_literal_evidence_still_abstains(kind):
    box=[10,10,320,32];im=picture([box]);before='잎의 무늬는 서로 다르다.'
    p=line('잎의 무늬는서로 다룬다.',box);t=line('잎의 무늬는 서로 다룬다.',box)
    if kind=='disagreement':t['text']='잎의 무늬는 서로 다린다.'
    if kind=='different_length':p['text']='잎의무늬는서로같다.';t['text']='잎의 무늬는 서로 같다.'
    if kind=='punctuation':p['text']='잎의 무늬는서로 다룬다!';t['text']='잎의 무늬는 서로 다룬다!'
    if kind=='different_position':t['box']=[10,130,320,150]
    if kind=='large_edit':p['text']='잎의모양이아주비슷하다.';t['text']='잎의 모양이 아주 비슷하다.'
    r=page(im,[line(before,box)],[line(before,box)],alternatives([p],[] if kind=='no_independent_engine' else [t]),'prose')
    if kind=='native':r['lines'][0]['engine']='native'
    select_precise_draft(im,r);assert r['draft']['text']==before

def test_balanced_insert_delete_is_not_treated_as_characterwise_replacement():
    box=[10,10,350,32];im=picture([box]);before='가나다라마바 사아자차카타파하.'
    p=line('나다라마바사아자차카타파거하.',box);t=line('나다라마바 사아자차카타파거하.',box)
    r=page(im,[line(before,box)],[line(before,box)],alternatives([p],[t]),'prose')
    select_precise_draft(im,r);assert r['draft']['text']==before
