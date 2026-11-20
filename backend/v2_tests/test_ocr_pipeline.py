"""Small synthetic contract tests; actual model smoke is a separate receipt."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]))
from app.services.ocr_pipeline import normalize,native_quality,align_lines,combine_page,compose_draft,OcrRejected


@pytest.mark.parametrize('text,good',[('정상 한국어 원문입니다.',True),('짧은 시구',True),('',False),('깨진 � 문자열',False),('가\x00나다라',False),('!@#$!',False)])
def test_native_quality(text,good):assert native_quality(text)==good


def test_nfc_lf_and_codepoints():
    line={'id':'line-1','text':'가😀\r\n  시의 행','box':[0,0,100,20]}
    d=compose_draft([line]);assert d['text']=='가😀\n  시의 행'
    assert d['rawText']==line['text'] and d['locationUnit']=='UNICODE_CODE_POINT_HALF_OPEN'
    assert d['lineMap'][0]['rawEnd']==len(line['text'])
    assert ''.join(line['text'][s['raw'][0]:s['raw'][1]] for s in d['normalizationMap'])==line['text']
    assert normalize('가\r\n나\r다')=='가\n나\n다'


def test_line_alignment_disagreement_and_independent_missing():
    a=[{'text':'원문 한 줄','box':[0,0,100,20],'confidence':.2}]
    b=[{'text':'다른 인식','box':[0,0,100,20],'confidence':99},{'text':'별도 누락 줄','box':[0,40,100,60]}]
    result=align_lines(a,b)
    assert result[0]['text']=='원문 한 줄' and result[0]['difference']=='TEXT_DIFFERENCE'
    assert result[1]['difference']=='PRIMARY_MISSING'
    assert result[0]['confidence']==.2 # Never rank incomparable engine scores.


def test_primary_and_secondary_missing_separate():
    assert align_lines([{'text':'가','box':[0,0,10,10]}],[])[0]['difference']=='SECONDARY_MISSING'


def test_mixed_native_layer_preserved_without_duplication():
    from PIL import Image
    n={'text':'직접 추출 원문','box':[0,0,150,20]}
    page={'route':'mixed','nativeLines':[n]}
    p=[{'text':'직접 추출 원문','box':[0,0,150,20]},{'text':'그림 속 인쇄 글','box':[0,40,150,60]}]
    result=combine_page(Image.new('RGB',(200,200)),page,p,p,{'blocks':[],'tables':[]})
    assert result['draft']['text'].count('직접 추출 원문')==1
    assert result['draft']['text'].count('그림 속 인쇄 글')==1


def test_poetry_indentation_line_order_and_punctuation():
    lines=[{'id':f'line-{i}','text':t,'box':[10,20*i,100,20*i+15]} for i,t in enumerate(['  창문은 닫혔다.','','“바람아, ~ 기다려!”','  창문은 닫혔다.'])]
    result=compose_draft(lines)
    assert result['text']=='  창문은 닫혔다.\n\n“바람아, ~ 기다려!”\n  창문은 닫혔다.'
    assert len(result['lineMap'])==4


def test_footnote_and_formula_raw_structure_retained():
    from PIL import Image
    structure={'blocks':[{'box':[0,0,200,20],'type':'text'},{'box':[0,100,200,120],'type':'footnote'},{'box':[0,50,50,70],'type':'formula'}],'tables':[],'raw':{'footnote':'original'}}
    result=combine_page(Image.new('RGB',(200,200)),{'route':'ocr'},[{'text':'각주 원문','box':[0,100,180,120]}],[],structure)
    assert result['structure']==structure and result['lines'][0]['block']==1


def test_alignment_search_bound():
    with pytest.raises(OcrRejected,match='LINE_LIMIT'):align_lines([{}]*1201,[])


def test_inert_table_cells_keep_rows_spans_text_and_no_html_execution():
    from app.services.ocr_pipeline import table_cells
    cells=table_cells({'pred_html':'<table><tr><td rowspan="2">장소</td><td>첫날</td></tr><tr><td>&lt;원문&gt;</td></tr></table>'})
    assert cells==[{'row':0,'column':0,'rowSpan':2,'columnSpan':1,'text':'장소'},{'row':0,'column':1,'rowSpan':1,'columnSpan':1,'text':'첫날'},{'row':1,'column':1,'rowSpan':1,'columnSpan':1,'text':'<원문>'}]
    assert table_cells({'pred_html':'<table><tr><td colspan="999999999">x</td></tr></table>'})==[]


def test_secondary_fragments_are_preserved_but_never_auto_added_to_draft():
    from PIL import Image
    primary=[{'text':'원문 한 줄','box':[0,0,300,30],'engine':'korean_PP-OCRv5_mobile_rec'}]
    secondary=[{'text':'원문','box':[0,0,100,30]},{'text':'한 줄','box':[110,0,300,30]}]
    result=combine_page(Image.new('RGB',(400,100)),{'route':'ocr'},primary,secondary,{'blocks':[],'tables':[]})
    assert result['draft']['text']=='원문 한 줄'
    assert len(result['lines'])==2 and len(result['enginesRaw']['tesseract'])==2
    missing=[l for l in result['lines'] if l.get('primaryMissing')]
    assert len(missing)==1 and missing[0]['includedInDraft'] is False and missing[0]['draftLineIndex'] is None


@pytest.mark.parametrize('mode',['standard','precise'])
@pytest.mark.parametrize('route',['native','ocr','mixed'])
def test_mode_routing_native_priority_and_cache_separation(tmp_path,monkeypatch,mode,route):
    """Control-flow safety fixture; actual CPU measurements are separate."""
    import importlib,json
    from PIL import Image
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'app/services'))
    worker=importlib.import_module('ocr_models');pipeline=importlib.import_module('ocr_pipeline')
    monkeypatch.setattr(pipeline,'validate_input',lambda *a,**k:{'pages':1})
    native={'text':'직접 추출 구절','box':[0,0,200,20]}
    page={'route':route,'nativeText':native['text'] if route!='ocr' else '','nativeLines':[native] if route!='ocr' else [],'geometry':{'coordinateUnit':'RENDER_PIXEL_TOP_LEFT'}}
    monkeypatch.setattr(pipeline,'render_page',lambda *a:(Image.new('RGB',(300,150),'white'),page))
    monkeypatch.setattr(pipeline,'ruled_table_candidate',lambda *a:True)
    class Fixture:
        timings=[]
        def __init__(self):self.calls=[]
        def lightweight(self,image):self.calls.append('lightweight');return [{'text':'이미지 구절','box':[0,40,200,60],'confidence':.9,'engine':'korean_PP-OCRv5_mobile_rec'}]
        def structure(self,image,table=False):self.calls.append('structure');return self.lightweight(image),{'blocks':[],'tables':[]}
        def tesseract(self,image):self.calls.append('tesseract');return []
        def versions(self,calls):return {'fixture':'NOT_REAL_MODEL_EVIDENCE'} if calls else {}
    fixture=Fixture();request={'operation':'document','ocrMode':mode,'config':{'models':str(tmp_path/'models')},'input':'fixture','inputSha':'fixture-sha','owner':'fixture-owner','inputRevisionId':'revision-fixture','fingerprint':'fixture-fingerprint','outputRoot':str(tmp_path),'prefix':'mode-cache','cancelFile':str(tmp_path/'cancel'),'progressFile':str(tmp_path/'progress.json')}
    result=worker.run(request,models=fixture);output=json.loads((tmp_path/result['pageFiles'][0]).read_text())
    assert output['ocrMode']==mode and output['cacheBinding']['ocrMode']==mode
    assert result['timing']['workerRunSeconds']>=result['timing']['validationSeconds']>=0
    assert output['timing']['renderAndImageSaveSeconds']>=0
    assert output['timing']['recognitionAndCompositionSeconds']>=0
    assert any('pageAndProgressSaveSeconds' in t for t in fixture.timings)
    if route=='native':assert fixture.calls==[] and output['calls']==[]
    elif mode=='standard':assert fixture.calls==['lightweight'] and 'tesseract_best' not in output['calls'] and 'PP-StructureV3' not in output['calls']
    else:assert fixture.calls==['structure','lightweight','tesseract']
    if route=='mixed':assert output['draft']['text'].count(native['text'])==1
    fixture.calls.clear();worker.run(request,models=fixture);assert fixture.calls==[]
    # Same prefix/hash/revision must still miss cache after a mode change.
    request['ocrMode']='precise' if mode=='standard' else 'standard'
    worker.run(request,models=fixture)
    if route!='native':assert fixture.calls
