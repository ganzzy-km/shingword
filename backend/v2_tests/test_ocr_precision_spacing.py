"""Frozen development contracts: exact fragment + visible gap, never guessing letters."""
import copy
from PIL import Image,ImageDraw
import pytest
from app.services.ocr_pipeline import restore_fragment_spacing,supported_spacing

def fixture(*,space=True,intrusion=False):
    im=Image.new('RGB',(340,80),'white');d=ImageDraw.Draw(im)
    # Model boxes are slightly inaccurate at the second token's edge.
    d.rectangle((10,10,60,45),fill='black');d.rectangle((88 if space else 63,10,145,45),fill='black')
    if intrusion:d.rectangle((82,10,87,45),fill='black')
    line={'id':'a','text':'도현:오래 기다렸어.','box':[8,8,300,48],'engine':'paddle','includedInDraft':True}
    frag={'text':'도현: 오래','box':[10,10,145,46],'words':[{'text':'도현:','box':[10,10,61,46]},{'text':'오래','box':[94 if intrusion else 88,10,145,46]}]}
    return im,line,frag

def test_exact_prefix_and_visible_gap_adds_one_space_without_changing_characters():
    im,line,frag=fixture();before=copy.deepcopy((line,frag))
    result=restore_fragment_spacing(im,line,[frag])
    assert result['text']=='도현: 오래 기다렸어.'
    assert result['insertedAtLiteralOffsets']==[3]
    assert (line,frag)==before

def test_tsv_edge_inaccuracy_requires_a_sufficient_contiguous_white_cut():
    im,line,frag=fixture(intrusion=True)
    assert supported_spacing(im,frag['text'],frag['words'],frag['box'])
    assert restore_fragment_spacing(im,line,[frag])['text']=='도현: 오래 기다렸어.'

@pytest.mark.parametrize('kind',['ink','different_literal','different_row','other_column','repeat_anchor','native','nfd','multi_space','no_words','single_token','bad_geometry'])
def test_ambiguous_fragments_never_change_the_primary_text(kind):
    im,line,frag=fixture()
    if kind=='ink':ImageDraw.Draw(im).rectangle((61,10,87,45),fill='black')
    if kind=='different_literal':frag['text']='도현: 어제'
    if kind=='different_row':frag['box']=[10,60,145,78]
    if kind=='other_column':frag['box']=[320,10,450,46]
    if kind=='repeat_anchor':line['text']='도현:오래 도현:오래'
    if kind=='native':line['engine']='native'
    if kind=='nfd':line['text']='도현:오래 기다렸어.'
    if kind=='multi_space':frag['text']='도현:  오래'
    if kind=='no_words':frag.pop('words')
    if kind=='single_token':frag['text']='도현:'
    if kind=='bad_geometry':frag['words'][1]['box']=[54,10,145,46]
    result=restore_fragment_spacing(im,line,[frag])
    assert result['text']==line['text'] and not result['insertedAtLiteralOffsets']

def test_existing_tabs_multiple_spaces_and_punctuation_are_preserved():
    im,line,frag=fixture();line['text']='도현:오래\t기다렸어.  정말.'
    result=restore_fragment_spacing(im,line,[frag])
    assert result['text']=='도현: 오래\t기다렸어.  정말.'

def test_no_visual_word_gap_is_not_proved_by_tsv_spacing_alone():
    im,line,frag=fixture(space=False)
    assert restore_fragment_spacing(im,line,[frag])['text']==line['text']

def test_duplicate_evidence_is_idempotent():
    im,line,frag=fixture();result=restore_fragment_spacing(im,line,[frag,frag])
    assert result['text']=='도현: 오래 기다렸어.' and result['insertedAtLiteralOffsets']==[3]
    line['text']=result['text'];assert not restore_fragment_spacing(im,line,[frag])['insertedAtLiteralOffsets']


@pytest.mark.parametrize('size',[40,42])
@pytest.mark.parametrize('printed,tsv,positive',[
    ('동네기차역','동네 기차역',False),
    ('열두번째기록','열두번 째기록',False),
    ('지수:오늘','지수: 오늘',False),
    ('지수: 오늘','지수: 오늘',True),
    ('시각12:30','시각12: 30',False),
    ('URL:https://abc','URL: https://abc',False),
    ('빛：오늘','빛： 오늘',False),
    ('가상 작가:민아','가상 작가: 민아',False),
    ('가상 작가: 민아','가상 작가: 민아',True),
    ('지수:（오늘）','지수: （오늘）',False),
    ('기호:［실내］','기호: ［실내］',False),
    ('지수:「오늘」','지수: 「오늘」',False),
    ('인용:“오늘”','인용: “오늘”',False),
])
def test_actual_printed_font_distinguishes_a_space_from_glyph_sidebearing(size,printed,tsv,positive):
    from pathlib import Path
    from PIL import ImageFont,ImageOps
    import math
    font=ImageFont.truetype(str(Path(__file__).parents[2]/'public/fonts/noto-sans-kr-regular.ttf'),size)
    im=Image.new('RGB',(1200,200),'white');d=ImageDraw.Draw(im);d.text((40,40),printed,font=font,fill='black')
    positions=[i for i,c in enumerate(printed) if not c.isspace()];words=[];at=0
    for token in tsv.split(' '):
        lo=math.floor(40+d.textlength(printed[:positions[at]],font=font));end=positions[at+len(token)-1]+1
        hi=math.ceil(40+d.textlength(printed[:end],font=font));b=ImageOps.invert(im.crop((lo,0,hi,im.height)).convert('L')).getbbox()
        assert b;words.append({'text':token,'box':[lo+b[0],b[1],lo+b[2],b[3]]});at+=len(token)
    tight=list(ImageOps.invert(im.convert('L')).getbbox())
    primary=printed.replace(': ',':') if positive else printed
    target={'text':primary,'engine':'paddle','box':tight};fragment={'text':tsv,'words':words,'box':tight}
    result=restore_fragment_spacing(im,target,[fragment])
    assert result['text']==printed
    assert bool(result['insertedAtLiteralOffsets'])==positive
