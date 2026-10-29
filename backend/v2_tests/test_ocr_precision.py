"""Frozen development contracts; synthetic geometry is not OCR accuracy data."""
import copy,json,sys
from pathlib import Path
import pytest
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).parents[1]))
from v2_fixture import v2app,user_client
from test_ocr_api import setup,ready
from app.services.ocr_pipeline import (combine_page,select_precise_draft,ink_rows,
    supported_spacing,precision_reading_order,compose_precision_draft,precision_crop_view,_page_alternative)


def line(text,box,**extra):return {'text':text,'box':box,'engine':'fixture','confidence':.9,**extra}


def picture(boxes):
    im=Image.new('RGB',(400,250),'white');d=ImageDraw.Draw(im)
    for b in boxes:d.rectangle(b,fill='black')
    return im


def page(im,primary,secondary,alts,profile='poetry'):
    result=combine_page(im,{'route':'ocr'},primary,secondary,{'blocks':[],'tables':[]},profile=profile)
    result['localRefinement']={'candidates':[{'id':'crop-1','box':[0,0,400,200],
        'lineIds':[l['id'] for l in result['lines']],'alternatives':alts}], 'automaticallyChangedCharacters':0}
    return result


def alternatives(p,t):
    return [{'engine':'PaddleOCR_LOCAL_REDETECTION','scale':1,'lines':p},
            {'engine':'tesseract_best','lines':t}]


def test_missing_line_requires_image_and_independent_redetection():
    a=line('첫 문장',[10,10,180,30]);b=line('누락 문장',[10,80,180,100]);im=picture([a['box'],b['box']])
    r=page(im,[a],[a,b],alternatives([a,b],[a,b]));before=r['draft']['text']
    select_precise_draft(im,r)
    assert before=='첫 문장' and r['draft']['text']=='첫 문장\n\n누락 문장'
    assert r['precision']['decisions'][0]['status']=='APPLIED'
    assert r['precision']['before']['text']==before and len(r['enginesRaw']['paddle'])==1


@pytest.mark.parametrize('defect',['blank_image','disagreement','no_redetection','overlap'])
def test_missing_text_abstains_on_unproven_or_duplicate_region(defect):
    a=line('첫 문장',[10,10,180,30]);b=line('누락 문장',[10,80,180,100])
    if defect=='overlap':b['box']=[12,11,179,29]
    im=picture([] if defect=='blank_image' else [a['box'],b['box']]);p=[b];t=[b]
    if defect=='disagreement':p=[line('다른 문장',b['box'])]
    if defect=='no_redetection':p=[]
    r=page(im,[a],[a,b],alternatives(p,t));select_precise_draft(im,r)
    assert r['draft']['text']=='첫 문장'


def test_literal_substitution_needs_geometry_and_repeated_crop_recognition():
    box=[10,10,210,30];im=picture([box]);old=line('문장을 남것다.',box);new=line('문장을 남겼다.',box)
    r=page(im,[old],[new],alternatives([new],[new]));select_precise_draft(im,r)
    assert r['draft']['text']==new['text'] and r['lines'][0]['originalText']==old['text']
    assert not r['precision']['crossEngineConfidenceRanked']


@pytest.mark.parametrize('other',['문맥을 새로 만들어 낸다.','문장을 남겼다?','다른 문장이다.'])
def test_contextual_or_conflicting_text_is_not_voted_in(other):
    box=[10,10,210,30];im=picture([box]);old=line('문장을 남겼다.',box)
    r=page(im,[old],[line(other,box)],alternatives([old],[line(other,box)]));select_precise_draft(im,r)
    assert r['draft']['text']==old['text']


def test_spacing_uses_literal_tsv_words_and_visible_gaps():
    words=[{'text':'여울:','box':[10,10,50,30]},{'text':'남겨','box':[65,10,105,30]},{'text':'두자.','box':[120,10,170,30]}]
    im=picture([w['box'] for w in words]);box=[10,10,170,30]
    old=line('여울:남겨 두자.',box);t=line('여울: 남겨 두자.',box,words=words)
    assert supported_spacing(im,t['text'],words,box)
    r=page(im,[old],[t],alternatives([old],[t]),'drama');select_precise_draft(im,r)
    assert r['draft']['text']==t['text']


def test_same_row_fragments_align_without_cross_row_mixing():
    words=[{'text':'여울:','box':[10,10,50,30]}, {'text':'기다릴','box':[65,10,115,30]}, {'text':'수','box':[130,10,145,30]}, {'text':'있어.','box':[160,10,200,30]}]
    im=picture([w['box'] for w in words]);old=line('여울:기다릴수있어.',[10,10,200,30])
    fragments=[line(w['text'],w['box']) for w in words];fragments[2:]=fragments[2:][::-1]
    t=line('여울: 기다릴 수 있어.',old['box'],words=words)
    r=page(im,[old],[t],alternatives(fragments,[t]),'drama');select_precise_draft(im,r)
    assert r['draft']['text']==t['text']


def test_tsv_character_boxes_are_unioned_inside_literal_txt_word():
    words=[{'text':'책','box':[10,10,65,30]}, {'text':'은','box':[40,5,58,35]}, {'text':'남았다.','box':[80,10,155,30]}]
    im=picture([[10,10,65,30],[80,10,155,30]])
    assert supported_spacing(im,'책은 남았다.',words,[10,5,155,35])


def test_column_gutter_is_not_a_word_gap_in_local_fragment_adoption():
    words=[{'text':'왼쪽','box':[10,10,70,30]}, {'text':'오른쪽','box':[240,10,310,30]}]
    im=picture([w['box'] for w in words]);old=line('왼쪽오른쪽',[10,10,310,30]);t=line('왼쪽 오른쪽',old['box'],words=words)
    r=page(im,[old],[t],alternatives([line(w['text'],w['box']) for w in words],[t]));select_precise_draft(im,r)
    assert r['draft']['text']==old['text']


@pytest.mark.parametrize('space',['  ','\t','\u3000'])
def test_existing_literal_spacing_is_not_collapsed_by_engine_consensus(space):
    words=[{'text':'낯선','box':[10,10,65,30]}, {'text':'경험','box':[80,10,155,30]}]
    im=picture([w['box'] for w in words]);old=line('낯선'+space+'경험',[10,10,155,30]);t=line('낯선 경험',old['box'],words=words)
    r=page(im,[old],[t],alternatives([t],[t]));select_precise_draft(im,r)
    assert r['draft']['text']==old['text']


def test_printed_punctuation_is_not_modernized_by_two_agreeing_candidates():
    text='“서랍 속 작은 종이는 어제의 시간을 붙잡고 있었다.”';box=[10,10,350,30]
    im=picture([box]);old=line(text,box);new=line(text.replace('“','"').replace('”','"'),box)
    r=page(im,[old],[new],alternatives([new],[new]));select_precise_draft(im,r)
    assert r['draft']['text']==text
    assert r['precision']['decisions'][0]['reason']=='EXISTING_WHITESPACE_OR_PUNCTUATION_PRESERVED_REVIEW_ONLY'


@pytest.mark.parametrize('defect',['ink_in_gap','word_mismatch','no_boxes','different_row'])
def test_spacing_abstains_when_image_or_literal_alignment_is_missing(defect):
    words=[{'text':'낯선','box':[10,10,50,30]},{'text':'경험','box':[65,10,105,30]}]
    im=picture([w['box'] for w in words])
    if defect=='ink_in_gap':ImageDraw.Draw(im).rectangle([50,10,65,30],fill='black')
    if defect=='word_mismatch':words[0]['text']='새로운'
    if defect=='no_boxes':words=[]
    if defect=='different_row':words[1]['box']=[65,80,105,100]
    assert not supported_spacing(im,'낯선 경험',words,[10,10,105,30])


def test_vertical_merged_line_splits_only_on_same_literal_rows():
    a=line('첫째 둘째',[10,10,200,70]);p=[line('첫째',[10,10,150,30]),line('둘째',[10,50,150,70])]
    im=picture([l['box'] for l in p]);r=page(im,[a],p,alternatives(p,p));select_precise_draft(im,r)
    assert r['draft']['text']=='첫째\n둘째'
    assert r['precision']['decisions'][0]['reason']=='SAME_LITERAL_SEQUENCE_IN_DISTINCT_IMAGE_ROWS'


def test_horizontal_fragments_are_not_misread_as_two_rows():
    a=line('첫째 둘째',[10,10,200,30]);p=[line('첫째',[10,10,95,30]),line('둘째',[110,10,200,30])]
    im=picture([l['box'] for l in p]);r=page(im,[a],p,alternatives(p,p));select_precise_draft(im,r)
    assert r['draft']['text']=='첫째 둘째'


def test_merged_secondary_does_not_collapse_distinct_primary_rows():
    p=[line('첫째',[10,10,150,30]),line('둘째',[10,50,150,70])];t=[line('첫째 둘째',[10,10,200,70])]
    im=picture([l['box'] for l in p]);r=page(im,p,t,alternatives(p,t));select_precise_draft(im,r)
    assert r['draft']['text']=='첫째\n둘째'


def test_column_order_with_spanning_heading_and_footer():
    raw=[line('제목',[10,0,370,20]),line('왼쪽1',[10,50,150,70]),line('오른쪽1',[230,50,380,70]),
         line('왼쪽2',[10,90,150,110]),line('오른쪽2',[230,90,380,110]),line('각주',[10,150,380,170])]
    assert [l['text'] for l in precision_reading_order(raw,{},400)]==['제목','왼쪽1','왼쪽2','오른쪽1','오른쪽2','각주']


def test_short_left_aligned_footnote_follows_both_columns():
    raw=[line('제목',[10,0,90,20],block=0),line('왼쪽1',[10,70,100,90],block=1),line('오른쪽1',[230,70,350,90],block=1),
         line('왼쪽2',[10,110,100,130],block=1),line('오른쪽2',[230,110,350,130],block=1),line('짧은 각주',[10,220,170,240],block=2)]
    assert [l['text'] for l in precision_reading_order(raw,{},400)]==['제목','왼쪽1','왼쪽2','오른쪽1','오른쪽2','짧은 각주']


def test_internal_two_column_stanza_gap_is_not_a_page_region_boundary():
    raw=[line('왼쪽1',[10,10,100,30],block=1),line('오른쪽1',[230,10,350,30],block=1),
         line('왼쪽2',[10,130,100,150],block=1),line('오른쪽2',[230,130,350,150],block=1)]
    assert [l['text'] for l in precision_reading_order(raw,{},400)]==['왼쪽1','왼쪽2','오른쪽1','오른쪽2']


def test_table_order_is_row_major_not_column_major():
    raw=[line('A',[10,10,80,30]),line('C',[10,70,80,90]),line('B',[200,10,280,30]),line('D',[200,70,280,90])]
    st={'blocks':[{'type':'table','box':[0,0,300,100]}]}
    assert [l['text'] for l in precision_reading_order(raw,st,400)]==['A','B','C','D']


def test_heading_does_not_turn_a_table_into_text_columns():
    raw=[line('제목',[10,0,350,15]),line('A',[10,30,80,50]),line('C',[10,80,80,100]),line('B',[220,30,280,50]),line('D',[220,80,280,100])]
    st={'blocks':[{'type':'table','box':[0,20,300,110]}]}
    assert [l['text'] for l in precision_reading_order(raw,st,400)]==['제목','A','B','C','D']


def test_visible_ruled_grid_keeps_original_coordinates_and_raw_model_cells():
    from app.services.ocr_pipeline import bind_ruled_cells
    im=Image.new('RGB',(400,250),'white');d=ImageDraw.Draw(im)
    for x in [10,150,290]:d.line([x,20,x,180],fill='black',width=2)
    for y in [20,100,180]:d.line([10,y,290,y],fill='black',width=2)
    lines=[line('가',[20,30,80,50],id='1'),line('나',[160,30,220,50],id='2')]
    st={'blocks':[{'type':'table','box':[10,20,290,180]}],'tables':[{'cells':[{'text':'untrusted HTML cell'}]}]}
    out=bind_ruled_cells(im,st,lines);cells=out['tables'][0]['cells']
    assert len(cells)==4 and cells[0]['text']=='가' and cells[1]['text']=='나' and cells[2]['text']==''
    assert cells[0]['box'][0]==10.5 and out['tables'][0]['rawModelAlternatives']==st['tables']


def test_prose_large_gap_remains_unconfirmed_instead_of_invented_blank_line():
    a=line('산문의 한 줄',[10,10,200,30]);b=line('뒤의 한 줄',[10,100,200,120]);im=picture([a['box'],b['box']])
    r=page(im,[a,b],[a,b],alternatives([a,b],[a,b]),'prose');select_precise_draft(im,r)
    assert r['draft']['text']=='산문의 한 줄\n뒤의 한 줄'
    assert r['literary']['boundaries'] and not any(b['automaticallyApplied'] for b in r['literary']['boundaries'])


def test_native_regions_never_enter_automatic_replacement():
    a=line('직접 추출 보존',[10,10,180,30]);im=picture([a['box']])
    r=page(im,[a],[a],alternatives([line('직접 추출 수정',a['box'])],[line('직접 추출 수정',a['box'])]))
    r['lines'][0]['engine']='native';select_precise_draft(im,r)
    assert r['draft']['text']==a['text']


def test_nfc_unicode_span_with_blank_separator():
    lines=[line('가😀',[0,0,80,20],id='one',separatorBefore=''),line('“둘째”',[0,60,90,80],id='two',separatorBefore='\n\n')]
    r=compose_precision_draft(lines)
    assert r['text']=='가😀\n\n“둘째”' and r['lineMap'][1]['start']==4
    for entry,l in zip(r['lineMap'],lines):assert r['text'][entry['start']:entry['end']]==__import__('unicodedata').normalize('NFC',l['text'])


def test_crop_transform_maps_boxes_and_words_to_original_page():
    r={'box':[100,200,300,400]};a={'scale':2,'inverseAffine':[1,0,5,0,1,-3],
        'lines':[line('그대로',[20,40,100,80],words=[{'text':'그대로','box':[20,40,100,80]}])]}
    mapped=_page_alternative(r,a)[0]
    assert mapped['box']==[115,217,155,237] and mapped['words'][0]['box']==mapped['box']


def test_preprocessing_preserves_original_and_records_reversible_view():
    im=Image.new('RGB',(200,60),(190,190,190));ImageDraw.Draw(im).rectangle((10,20,160,40),fill=(140,140,140));original=im.tobytes()
    view,meta=precision_crop_view(im)
    assert im.tobytes()==original and view.size==im.size
    assert 'LOW_CONTRAST_AUTOCONTRAST' in meta['applied'] and len(meta['inverseAffine'])==6


@pytest.mark.parametrize('angle',[90,180,270])
def test_orthogonal_view_is_invertible_without_resampling_original(angle):
    from app.services.ocr_pipeline import orthogonal_view,restore_original_page_boxes
    im=Image.new('RGB',(400,250),'white');d=ImageDraw.Draw(im);d.rectangle([20,30,80,90],fill='black');source=im.tobytes()
    view,inverse=orthogonal_view(im,angle)
    # Map the complete transformed rectangle to the original extent; literal
    # spans are unrelated to rotation and must stay code-point identical.
    l=line('가😀',[0,0,view.width,view.height],id='1',includedInDraft=True)
    p={'lines':[l],'draft':{'text':'가😀','lineMap':[{'box':l['box'],'start':0,'end':2}]},'structure':{'blocks':[],'tables':[]}}
    restore_original_page_boxes(p,inverse,im.size)
    assert p['lines'][0]['box']==[0,0,400,250] and p['draft']['text']=='가😀'
    assert p['width']==400 and p['height']==250 and im.tobytes()==source


def test_explicit_formula_region_is_retained_separately_not_fabricated_as_text():
    a=line('원래 본문',[10,10,180,30]);b=line('x^2+y^2=r',[10,80,220,110]);im=picture([a['box'],b['box']])
    r=page(im,[a,b],[a,b],alternatives([a,b],[a,b]),'other')
    r['structure']['blocks']=[{'type':'text','box':a['box']},{'type':'formula','box':[10,80,170,110]}]
    r['lines'][0]['block']=0;r['lines'][1]['block']=1
    select_precise_draft(im,r)
    assert r['draft']['text']==a['text'] and r['lines'][1]['text']==b['text']
    assert r['lines'][1]['difference']=='FORMULA_REGION_SEPARATE' and r['precision']['before']['text'].endswith(b['text'])


@pytest.mark.parametrize('angle',[90,270])
def test_rotation_proposal_requires_image_rows_not_only_classifier_score(angle):
    from app.services.ocr_pipeline import orientation_verdict
    upright=picture([[10,10,300,30],[10,60,280,80],[10,110,310,130]])
    rotated=upright.transpose(Image.Transpose.ROTATE_90)
    old=[line('같은문자수',[0,0,100,20],confidence=.96)];new=[line('원문인식결과',[0,0,100,20],confidence=.98)]
    assert orientation_verdict({'angle':angle,'score':.88},old,new,rotated,upright)['allowed']
    assert not orientation_verdict({'angle':angle,'score':.99},old,new,upright,rotated)['allowed']


@pytest.mark.parametrize('defect',['uncertain_classifier','empty_result','no_gain'])
def test_half_turn_abstains_without_corroborated_recognition_gain(defect):
    from app.services.ocr_pipeline import orientation_verdict
    im=picture([[10,10,300,30],[10,60,280,80]])
    old=[line('기존문장',[0,0,100,20],confidence=.35)];new=[line('되찾은문장',[0,0,100,20],confidence=.98)]
    prediction={'angle':180,'score':.92}
    assert orientation_verdict(prediction,old,new,im,im)['allowed']
    if defect=='uncertain_classifier':prediction['score']=.4
    if defect=='empty_result':new=[]
    if defect=='no_gain':old=copy.deepcopy(new)
    assert not orientation_verdict(prediction,old,new,im,im)['allowed']


def test_precision_metadata_is_owner_only_and_survives_confirmation(setup):
    from app.services import ocr_jobs as jobs
    from app.extensions import db
    app,c,h,owner,did,jid,doc,_=setup;ready(app,jid)
    with app.app_context():
        _,record=jobs.row(jid);v=copy.deepcopy(record.value)
        v['pages'][0]['precision']={'before':{'text':'선택 전'},'changedCharacters':1,'decisions':[]}
        record.value=v;db.session.commit()
    result=c.get('/api/ocr-jobs/'+jid)
    assert result.status_code==200 and result.json['data']['pages'][0]['precision']['before']['text']=='선택 전'
    other,_,_=user_client(app,'precision-private-other')
    assert other.get('/api/ocr-jobs/'+jid).status_code==404
    assert c.post('/api/ocr-jobs/'+jid+'/confirm',headers=h,json={'expectedDraftVersion':1,'expectedRevisionId':doc['latestRevisionId']}).status_code==201
    assert c.get('/api/ocr-jobs/'+jid).json['data']['pages'][0]['precision']['before']['text']=='선택 전'
