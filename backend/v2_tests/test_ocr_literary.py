"""Predeclared functional examples, never independent literary accuracy labels."""
import hashlib,json,sys
from pathlib import Path
import pytest
from PIL import Image
sys.path.insert(0,str(Path(__file__).parents[1]))
from v2_fixture import v2app
from app.services import ocr_jobs as jobs
from app.services.ocr_pipeline import align_lines,combine_page,compose_draft,local_refinement_regions,LITERARY_POLICY
from app.models import OcrRun
from test_ocr_api import setup,ready

def line(text,box):return {'text':text,'box':box,'confidence':.5,'engine':'fixture'}

@pytest.mark.parametrize('profile',['poetry','prose','drama','auto'])
def test_geometry_is_not_invented_spaces_or_blank_lines(profile):
    raw=[line('가😀 시의 행',[10,10,200,30]),line('먼 곳의 말',[45,100,200,120]),line('여울:이 선택을 남긴다.',[10,130,250,150])]
    image=Image.new('RGB',(400,250),'white');r=combine_page(image,{'route':'ocr'},raw,raw,{'blocks':[],'tables':[]},profile=profile)
    assert r['draft']['text']=='가😀 시의 행\n먼 곳의 말\n여울:이 선택을 남긴다.'
    assert r['literary']['physicalLines'][1]['indentRatio']>0 and r['literary']['boundaries']
    assert not any(b['automaticallyApplied'] for b in r['literary']['boundaries'])
    for m in r['draft']['lineMap']:
        source=next(l for l in r['lines'] if l['id']==m['lineId'])
        assert r['draft']['text'][m['start']:m['end']]==source['text'].replace('가','가')
    assert r['draft']['rawText'].startswith('가😀')

def test_large_gap_across_blocks_or_ink_is_not_confirmed_stanza():
    from PIL import ImageDraw
    im=Image.new('RGB',(400,300),'white');ImageDraw.Draw(im).rectangle((10,40,200,90),fill='black')
    p=[line('첫 행입니다',[10,10,200,30]),line('다음 행입니다',[10,100,200,120])]
    result=combine_page(im,{'route':'ocr'},p,p,{'blocks':[],'tables':[]},profile='poetry')
    assert not result['literary']['boundaries']
    assert result['draft']['text']=='첫 행입니다\n다음 행입니다'

def test_per_line_model_blocks_keep_relative_indent_and_unconfirmed_gap():
    p=[line('첫 행입니다',[20,10,220,30]),line('들여쓴 다음 행',[50,50,220,70]),line('다음 연의 행',[20,140,220,160])]
    blocks=[{'box':x['box'],'type':'text'} for x in p]
    result=combine_page(Image.new('RGB',(300,250),'white'),{'route':'ocr'},p,p,{'blocks':blocks,'tables':[]},profile='poetry')
    assert result['literary']['physicalLines'][1]['indentRatio']>.1
    assert result['literary']['boundaries'][-1]['reasons']==['IMAGE_BLANK_GAP_ACROSS_MODEL_BLOCKS_REQUIRES_REVIEW']
    assert result['draft']['text']=='첫 행입니다\n들여쓴 다음 행\n다음 연의 행'
    assert not result['literary']['boundaries'][-1]['automaticallyApplied']

@pytest.mark.parametrize('kind', ['1:N','N:1','N:N'])
def test_split_merge_graph_preserves_all_raw_candidates_without_selection(kind):
    a=[line('첫째 둘째',[0,0,200,40])];b=[line('첫째',[0,0,95,40]),line('둘째',[100,0,200,40])]
    if kind=='N:1':a,b=b,a
    if kind=='N:N':a=[line('원래 A',[0,0,160,40]),line('원래 B',[40,0,200,40])]
    result=align_lines(a,b,groups=True)
    assert any(l['alignment']['kind']==kind for l in result if 'alignment' in l)
    assert [l['text'] for l in result if not l.get('primaryMissing')]==[l['text'] for l in a]
    assert all(not l.get('alignment',{}).get('automaticTextAdoption') for l in result)
    assert len({i for l in result for i in l.get('alignment',{}).get('secondaryIndexes',[])})==len(b)

def test_unmatched_secondary_preserved_and_never_silently_added():
    a=[line('첫 문학 구절',[0,0,200,25])];b=a+[line('다른 줄',[0,80,200,105])]
    r=combine_page(Image.new('RGB',(300,200),'white'),{'route':'ocr'},a,b,{'blocks':[],'tables':[]},profile='prose')
    assert r['draft']['text']=='첫 문학 구절' and r['lines'][1]['includedInDraft'] is False
    assert local_refinement_regions(r)[0]['triggers']==['PRIMARY_LINE_MISSING']

def test_local_regions_are_bounded_and_references_are_distinct():
    p=[line('정상 문학 구절',[0,i*40,180,i*40+20]) for i in range(20)]
    t=[{**x,'text':'다른 문자'} for x in p]
    page=combine_page(Image.new('RGB',(300,900),'white'),{'route':'ocr'},p,t,{'blocks':[],'tables':[]},profile='poetry')
    regions=local_refinement_regions(page);assert len(regions)==LITERARY_POLICY['maxLocalRegions']==4
    assert all(r['psm']==7 and r['status']=='REVIEW_ONLY' for r in regions)
    assert len({r['lineIds'][0] for r in regions})==4

def test_refinement_runs_real_interfaces_and_keeps_original_text(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'app/services'))
    from ocr_models import refine_local
    p=[line('문학 원래 글줄',[0,0,180,20])];t=[line('다른 인식',[0,0,180,20])]
    page=combine_page(Image.new('RGB',(300,100),'white'),{'route':'ocr'},p,t,{'blocks':[],'tables':[]},profile='drama')
    class ControlFixture:
        def tesseract(self,image,psm,timeout):assert psm==7 and 0<timeout<=45;return [line('교체하면 안 됨',[0,0,100,20])]
        def versions(self,calls):return {'fixture':'CONTROL_FLOW_ONLY'}
    result=refine_local(Image.new('RGB',(300,100),'white'),page,ControlFixture())
    assert result['automaticallyChangedCharacters']==0 and result['candidates'][0]['alternatives'][0]['text']=='교체하면 안 됨'
    assert page['draft']['text']=='문학 원래 글줄' and not result['VLautomatic']

def evidence(tmp_path):
    p=tmp_path/'evidence.json';p.write_text(json.dumps({'status':'PASS','vlPeakJobCommitBytes':8409210880,'s4PeakPrivateCommitBytes':4*1024**3}))
    return {'resourceEvidence':{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}}

@pytest.mark.parametrize('physical,commit,allowed',[(32,32,True),(8,32,False),(32,8,False)])
def test_vl_admission_separates_physical_ram_and_available_commit(tmp_path,physical,commit,allowed):
    r=jobs.vl_admission(evidence(tmp_path),{'available':True,'physicalAvailableBytes':physical*1024**3,'commitAvailableBytes':commit*1024**3})
    assert r['allowed'] is allowed and r['requiredAvailableBytes']>r['vlPeakJobCommitBytes']

def test_vl_unknown_or_tampered_resource_evidence_denied(tmp_path):
    assert not jobs.vl_admission({}, {'available':False})['allowed']
    cfg=evidence(tmp_path);Path(cfg['resourceEvidence']['path']).write_text('{}')
    assert not jobs.vl_admission(cfg,{'available':True})['allowed']

def test_prior_larger_rss_is_only_a_conservative_reserve_floor(tmp_path):
    cfg=evidence(tmp_path);p=Path(cfg['resourceEvidence']['path']);v=json.loads(p.read_text());v['s4ObservedPeakRssBytes']=5*1024**3;p.write_text(json.dumps(v));cfg['resourceEvidence']['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    r=jobs.vl_admission(cfg,{'available':True,'physicalAvailableBytes':64*1024**3,'commitAvailableBytes':64*1024**3})
    assert r['s4ReserveBytes']==5*1024**3 and r['s4PeakPrivateCommitBytes']==4*1024**3

def test_resource_denial_is_not_a_successful_job_and_does_not_mutate_source(setup,monkeypatch):
    app,c,h,owner,did,jid,doc,_=setup;ready(app,jid)
    monkeypatch.setattr(jobs,'vl_admission',lambda *a,**k:{'allowed':False,'reason':'INSUFFICIENT_HOST_RAM_OR_COMMIT'})
    with app.app_context():before=OcrRun.query.count()
    response=c.post('/api/ocr-jobs/'+jid+'/region',headers=h,json={'page':1,'box':[0,0,100,40],'engine':'vl'})
    assert response.status_code==503 and response.json['error']['code']=='OCR_RESOURCE_BUSY'
    with app.app_context():assert OcrRun.query.count()==before
    assert c.get('/api/ocr-jobs/'+jid).json['data']['status']=='REVIEW_READY'

def test_profile_is_recorded_validated_and_cannot_replace_active_job(setup):
    app,c,h,owner,did,jid,doc,upload=setup
    d=upload(ocrProfile='poetry').json['data'];job=c.get('/api/ocr-jobs/'+d['ocr']['jobId']).json['data'];assert job['ocrProfile']=='poetry'
    assert upload(ocrProfile='invalid').status_code==400
    assert c.post('/api/source-documents/'+d['id']+'/ocr',headers=h,json={'expectedRevisionId':d['latestRevisionId'],'ocrProfile':'drama'}).status_code==409

def test_psm7_manual_region_and_standard_denial(setup):
    app,c,h,owner,did,jid,doc,_=setup;ready(app,jid)
    response=c.post('/api/ocr-jobs/'+jid+'/region',headers=h,json={'page':1,'box':[0,0,100,40],'engine':'tesseract-line'})
    assert response.status_code==202
    assert c.get('/api/ocr-jobs/'+response.json['data']['id']).json['data']['ocrMode']=='precise'
