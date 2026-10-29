"""API invariants on synthetic drafts. Inference is verified separately, not mocked as PASS."""
import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest
from PIL import Image
from v2_fixture import v2app,user_client
from app.extensions import db
from app.models import AppSetting,OcrRun,SourceDocument,DocumentRevision
from app.services import ocr_jobs as jobs


@pytest.fixture
def setup(v2app,tmp_path,monkeypatch):
    v2app.config.update(OCR_AUTOSTART=False)
    cfg={'python':sys.executable,'models':str(tmp_path),'tesseract':sys.executable,'tessdata':str(tmp_path),'fingerprint':'synthetic-test-fingerprint'}
    # Existing authorization tests assume a runnable worker. Supply explicit
    # unit-only resource evidence; real host admission is tested separately.
    resource=tmp_path/'resource-evidence.json';resource.write_text(json.dumps({'status':'PASS','vlPeakJobCommitBytes':8409210880,'s4PeakPrivateCommitBytes':1024**3,'classification':'UNIT_CONTROL_FLOW_NOT_REAL_MEASUREMENT'}),encoding='utf-8')
    cfg['resourceEvidence']={'path':str(resource),'sha256':hashlib.sha256(resource.read_bytes()).hexdigest()}
    monkeypatch.setattr(jobs,'host_memory',lambda:{'available':True,'physicalAvailableBytes':64*1024**3,'commitAvailableBytes':64*1024**3})
    monkeypatch.setattr(jobs,'config',lambda:cfg)
    monkeypatch.setattr(jobs,'inspect_upload',lambda *_:{'mime':'image/png','pages':1,'needsOcr':True,'nativeText':''})
    client,headers,owner=user_client(v2app)
    data=io.BytesIO();Image.new('RGB',(400,200),'white').save(data,format='PNG')
    def upload(**fields):return client.post('/api/source-documents',headers=headers,data={'file':(io.BytesIO(data.getvalue()),'synthetic.png'),'title':'OCR synthetic','accessMode':'DOWNLOAD',**fields})
    response=upload();assert response.status_code==201
    document=response.json['data'];did=document['id'];jid=document['ocr']['jobId']
    return v2app,client,headers,owner,did,jid,document,upload


def ready(app,jid,text='시의 첫 줄\n  두 번째 행😀'):
    with app.app_context():
        run,record=jobs.row(jid);prefix=record.value['prefix']
        image=jobs.local_file(prefix+'-p0001.png');Image.new('RGB',(400,200),'white').save(image)
        lines=[{'id':'line-1','text':text,'box':[0,0,300,40],'engine':'synthetic','difference':'TEXT_DIFFERENCE','secondary':{'text':'대안'}}]
        page={'page':1,'width':400,'height':200,'imageFile':image.name,'lines':lines,'geometry':{'coordinateUnit':'RENDER_PIXEL_TOP_LEFT'},'structure':{'blocks':[],'tables':[]},'draft':{'text':text,'lineMap':[{'lineId':'line-1','rawStart':0,'rawEnd':len(text)}]},'calls':[],'seconds':0,'unavailable':[]}
        jobs.local_file(prefix+'-p0001.json').write_text(json.dumps(page,ensure_ascii=False),encoding='utf-8')
        record.value={**record.value,'pages':[page],'completedPages':1};run.status='REVIEW_READY';db.session.commit()


def test_pending_draft_not_analysis_or_public(setup):
    app,c,h,owner,did,jid,doc,_=setup
    r=c.post('/api/writings',headers=h,json={'title':'synthetic essay','content':'원문 분석 글입니다.','inquiryQuestion':'인물의 선택은 어떤 의미인가?'})
    wid=r.json['data']['id']
    assert c.post('/api/writings/'+wid+'/documents',headers=h,json={'revisionId':doc['latestRevisionId']}).status_code==409
    assert c.post('/api/source-documents/'+did+'/revisions',headers=h,json={'content':'bypass','expectedRevisionId':doc['latestRevisionId']}).status_code==409
    assert doc['scope']=='PRIVATE' and doc['canManageScope'] is False


@pytest.mark.parametrize('kind',['other','ADMIN'])
def test_no_foreign_review_any_endpoint(setup,kind):
    app,c,h,owner,did,jid,doc,_=setup;ready(app,jid)
    other,oh,_=user_client(app,'synthetic-ocr-'+kind,'ADMIN' if kind=='ADMIN' else 'USER')
    for url in ['/ocr-jobs/'+jid,'/source-documents/'+did+'/ocr','/ocr-jobs/'+jid+'/pages/1/image','/ocr-jobs/'+jid+'/export/txt']:
        assert other.get('/api'+url).status_code==404
    for suffix in ['confirm','cancel','retry','region']:
        assert other.post('/api/ocr-jobs/'+jid+'/'+suffix,headers=oh,json={}).status_code==404
    assert other.patch('/api/ocr-jobs/'+jid+'/draft',headers=oh,json={}).status_code==404


def test_csrf_denial_preserved(setup):
    app,c,h,owner,did,jid,doc,_=setup;ready(app,jid)
    assert c.post('/api/ocr-jobs/'+jid+'/confirm',json={}).status_code==401
    assert c.patch('/api/ocr-jobs/'+jid+'/draft',json={}).status_code==401


def test_save_conflict_reopen_and_unicode(setup):
    app,c,h,owner,did,jid,doc,_=setup;ready(app,jid)
    body={'expectedDraftVersion':1,'pages':{'1':'가😀\r\n  시구'}}
    r=c.patch('/api/ocr-jobs/'+jid+'/draft',headers=h,json=body);assert r.status_code==200 and r.json['data']['draftVersion']==2
    assert c.patch('/api/ocr-jobs/'+jid+'/draft',headers=h,json=body).status_code==409
    assert c.get('/api/source-documents/'+did+'/ocr').json['data']['pages'][0]['draft']=='가😀\r\n  시구'
    result=c.post('/api/ocr-jobs/'+jid+'/confirm',headers=h,json={'expectedDraftVersion':2,'expectedRevisionId':doc['latestRevisionId']})
    assert result.status_code==201
    rid=result.json['data']['revisionId']
    assert c.get('/api/source-documents/'+did+'/revisions/'+rid).json['data']['content']=='가😀\n  시구'
    assert c.get('/api/ocr-jobs/'+jid+'/export/json').json['mapping'][0]['mappingStatus']=='USER_EDITED_NO_GUESSED_MAPPING'


def test_confirmation_immutable_idempotent_and_export(setup):
    app,c,h,owner,did,jid,doc,_=setup;ready(app,jid)
    body={'expectedDraftVersion':1,'expectedRevisionId':doc['latestRevisionId']}
    r=c.post('/api/ocr-jobs/'+jid+'/confirm',headers=h,json=body);assert r.status_code==201;rid=r.json['data']['revisionId']
    assert c.post('/api/ocr-jobs/'+jid+'/confirm',headers=h,json=body).json['data']['revisionId']==rid
    with app.app_context():
        assert DocumentRevision.query.filter_by(document_id=did).count()==2
        assert db.session.get(DocumentRevision,doc['latestRevisionId']).content==''
        revision=db.session.get(DocumentRevision,rid);assert hashlib.sha256(revision.content.encode()).hexdigest()==revision.content_hash
    assert c.patch('/api/ocr-jobs/'+jid+'/draft',headers=h,json={'expectedDraftVersion':1,'pages':{'1':'overwrite'}}).status_code==409
    assert c.get('/api/ocr-jobs/'+jid+'/export/txt').data.decode()=='시의 첫 줄\n  두 번째 행😀'
    assert c.get('/api/ocr-jobs/'+jid+'/export/json').json['revisionId']==rid


@pytest.mark.parametrize('change',['revision','input','empty'])
def test_confirmation_rechecks_input_and_revision(setup,change):
    app,c,h,owner,did,jid,doc,_=setup;ready(app,jid,'' if change=='empty' else '원문')
    if change=='revision':
        with app.app_context():db.session.add(DocumentRevision(document_id=did,revision_number=2,content='changed',content_hash=hashlib.sha256(b'changed').hexdigest()));db.session.commit()
    if change=='input':
        with app.app_context():jobs.local_file(db.session.get(SourceDocument,did).stored_name).write_bytes(b'changed')
    r=c.post('/api/ocr-jobs/'+jid+'/confirm',headers=h,json={'expectedDraftVersion':1,'expectedRevisionId':doc['latestRevisionId']})
    assert r.status_code in {400,409}


@pytest.mark.parametrize('box',[[0,0,400,200],[-1,0,10,10],[0,0,401,10],[2,2,1,1],[0,0,float('inf'),2]])
def test_region_bounds_and_deduplication(setup,box):
    app,c,h,owner,did,jid,doc,_=setup;ready(app,jid)
    r=c.post('/api/ocr-jobs/'+jid+'/region',headers=h,json={'page':1,'box':box,'engine':'vl'})
    assert r.status_code==(202 if box==[0,0,400,200] else 400)
    if r.status_code==202:
        r2=c.post('/api/ocr-jobs/'+jid+'/region',headers=h,json={'page':1,'box':box,'engine':'vl'});assert r2.json['data']['id']==r.json['data']['id']
        assert c.get('/api/source-documents/'+did+'/ocr').json['data']['id']==jid


def test_cancel_retry_completed_pages_and_limit(setup):
    app,c,h,owner,did,jid,doc,_=setup
    assert c.post('/api/ocr-jobs/'+jid+'/cancel',headers=h).status_code==200
    assert c.post('/api/ocr-jobs/'+jid+'/confirm',headers=h,json={'expectedDraftVersion':1,'expectedRevisionId':doc['latestRevisionId']}).status_code==409
    for _ in range(2):
        assert c.post('/api/ocr-jobs/'+jid+'/retry',headers=h).status_code==202
        assert c.post('/api/ocr-jobs/'+jid+'/cancel',headers=h).status_code==200
    assert c.post('/api/ocr-jobs/'+jid+'/retry',headers=h).status_code==409


def test_match_only_does_not_expose_review_image_candidate_or_download(setup):
    app,c,h,owner,did,jid,doc,_=setup;ready(app,jid)
    with app.app_context():db.session.get(SourceDocument,did).access_mode='MATCH_ONLY';db.session.commit()
    for suffix in ['', '/pages/1/image','/export/txt','/export/json']:
        assert c.get('/api/ocr-jobs/'+jid+suffix).status_code==404
    assert c.get('/api/source-documents/'+did).json['data']['ocr']['jobId'] is None
    assert c.post('/api/ocr-jobs/'+jid+'/confirm',headers=h,json={}).status_code==404


def test_view_does_not_gain_download_permission(setup):
    app,c,h,owner,did,jid,doc,_=setup;ready(app,jid)
    c.post('/api/ocr-jobs/'+jid+'/confirm',headers=h,json={'expectedDraftVersion':1,'expectedRevisionId':doc['latestRevisionId']})
    with app.app_context():db.session.get(SourceDocument,did).access_mode='VIEW';db.session.commit()
    assert c.get('/api/ocr-jobs/'+jid).status_code==200
    assert c.get('/api/ocr-jobs/'+jid+'/export/txt').status_code==404


def test_delete_derived_files_and_job_while_queued(setup):
    app,c,h,owner,did,jid,doc,_=setup;ready(app,jid)
    assert c.delete('/api/source-documents/'+did,headers=h).status_code==200
    assert c.get('/api/ocr-jobs/'+jid).status_code==404
    with app.app_context():
        assert db.session.get(OcrRun,jid) is None and db.session.get(AppSetting,'ocr_job:'+jid) is None
        assert not list(jobs.root().glob('ocr-'+jid+'-*'))


def test_public_and_match_only_scan_requires_private_review(setup):
    app,c,h,owner,did,jid,doc,upload=setup
    assert upload(accessMode='MATCH_ONLY').status_code==409


def test_path_traversal_never_resolves(setup):
    app,*_=setup
    with app.app_context():
        for name in ['../secret','C:\\secret','a/b','a\\b','']:
            with pytest.raises(ValueError):jobs.local_file(name)


def test_ocr_review_does_not_extend_document_retention(setup):
    app,c,h,owner,did,jid,doc,_=setup;ready(app,jid)
    from app.v2.privacy_lifecycle import document_deadline,DOCUMENT_POLICY
    app.config['PRIVATE_DOCUMENT_RETENTION_POLICY']=DOCUMENT_POLICY
    with app.app_context():
        expected=document_deadline(db.session.get(SourceDocument,did));_,record=jobs.row(jid)
        record.value={**record.value,'retentionDeadline':expected.isoformat()};db.session.commit()
    assert c.post('/api/ocr-jobs/'+jid+'/confirm',headers=h,json={'expectedDraftVersion':1,'expectedRevisionId':doc['latestRevisionId']}).status_code==201
    with app.app_context():assert document_deadline(db.session.get(SourceDocument,did))==expected


def test_other_region_does_not_reuse_wrong_active_result(setup):
    app,c,h,owner,did,jid,doc,_=setup;ready(app,jid)
    assert c.post('/api/ocr-jobs/'+jid+'/region',headers=h,json={'page':1,'box':[0,0,100,100],'engine':'vl'}).status_code==202
    assert c.post('/api/ocr-jobs/'+jid+'/region',headers=h,json={'page':1,'box':[100,0,200,100],'engine':'tesseract'}).status_code==409


def test_queue_capacity_rolls_back_only_new_upload(setup):
    app,c,h,owner,did,jid,doc,upload=setup
    assert upload().status_code==201
    assert upload().status_code==429
    with app.app_context():assert SourceDocument.query.count()==2 and OcrRun.query.count()==2


def test_placeholder_stays_unselectable_after_confirmation(setup):
    app,c,h,owner,did,jid,doc,_=setup;ready(app,jid)
    confirmed=c.post('/api/ocr-jobs/'+jid+'/confirm',headers=h,json={'expectedDraftVersion':1,'expectedRevisionId':doc['latestRevisionId']}).json['data']['revisionId']
    wid=c.post('/api/writings',headers=h,json={'title':'synthetic','content':'원문에 대한 생각이다.'}).json['data']['id']
    assert c.post('/api/writings/'+wid+'/documents',headers=h,json={'revisionId':doc['latestRevisionId']}).status_code==409
    assert c.post('/api/writings/'+wid+'/documents',headers=h,json={'revisionId':confirmed}).status_code==200


def test_restart_state_not_overwritten_by_new_draft(setup):
    app,c,h,owner,did,jid,doc,_=setup;ready(app,jid)
    assert c.patch('/api/ocr-jobs/'+jid+'/draft',headers=h,json={'expectedDraftVersion':1,'pages':{'1':'수정한 원문'}}).status_code==200
    # Simulate a request boundary/new SQLAlchemy session, not fake inference.
    with app.app_context():db.session.remove()
    new_client,_,_=user_client(app)
    r=new_client.get('/api/ocr-jobs/'+jid).json['data']
    assert r['draftVersion']==2 and r['pages'][0]['draft']=='수정한 원문'


def test_new_comparison_does_not_disable_an_existing_confirmed_source(setup):
    app,c,h,owner,did,jid,doc,_=setup
    old=c.post('/api/source-documents',headers=h,data={'file':(io.BytesIO('기존에 확정된 원문이다.'.encode()),'native.txt'),'title':'기존 원문'}).json['data']
    r=c.post('/api/source-documents/'+old['id']+'/ocr',headers=h,json={'expectedRevisionId':old['latestRevisionId']})
    assert r.status_code==202
    detail=c.get('/api/source-documents/'+old['id']).json['data'];assert detail['content']=='기존에 확정된 원문이다.' and detail['status']=='등록 완료'
    wid=c.post('/api/writings',headers=h,json={'title':'기존 자료 재사용','content':'선택에 관한 생각이다.'}).json['data']['id']
    assert c.post('/api/writings/'+wid+'/documents',headers=h,json={'revisionId':old['latestRevisionId']}).status_code==200


def test_atomic_failure_files_are_registered_for_deletion(setup):
    app,c,h,owner,did,jid,doc,_=setup
    with app.app_context():
        _,record=jobs.row(jid);name=record.value['prefix']+'-p0001.json.tmp'
        assert name in record.value['files'];jobs.local_file(name).write_text('private partial OCR text')
    assert c.delete('/api/source-documents/'+did,headers=h).status_code==200
    with app.app_context():assert not jobs.local_file(name).exists()


@pytest.mark.skipif(os.name!='nt',reason='Windows JobObject contract')
def test_worker_job_suspended_assignment_and_memory_accounting():
    child=subprocess.Popen([sys.executable,'-c','x=bytearray(10000000);import time;time.sleep(.1)'],creationflags=subprocess.CREATE_NO_WINDOW|4)
    job=jobs.process_job(child,128*1024**2)
    try:child.wait(timeout=10);assert child.returncode==0 and job.memory()>=10000000
    finally:job()


@pytest.mark.skipif(os.name!='nt',reason='Windows JobObject contract')
def test_worker_job_close_terminates_its_own_child(tmp_path):
    import time,ctypes
    from ctypes import wintypes
    marker=tmp_path/'leaf-pid';finished=tmp_path/'must-not-finish'
    leaf=f"from pathlib import Path;import os,time;Path({str(marker)!r}).write_text(str(os.getpid()));time.sleep(60);Path({str(finished)!r}).write_text('finished')"
    parent=f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{leaf!r}]);time.sleep(60)"
    child=subprocess.Popen([sys.executable,'-c',parent],creationflags=subprocess.CREATE_NO_WINDOW|4)
    job=jobs.process_job(child,128*1024**2)
    deadline=__import__('time').monotonic()+10
    while not marker.exists() and time.monotonic()<deadline:time.sleep(.02)
    assert marker.exists()
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x100000,False,int(marker.read_text()));assert handle
    try:
        start=time.monotonic();job();child.wait(timeout=5)
        assert kernel.WaitForSingleObject(handle,5000)==0 and time.monotonic()-start<5
        assert not finished.exists() # No normal completion, irrespective of JobObject exit code.
    finally:kernel.CloseHandle(handle)


def test_confirmed_same_revision_reuses_job_without_new_ocr(setup):
    app,c,h,owner,did,jid,doc,_=setup;ready(app,jid)
    rid=c.post('/api/ocr-jobs/'+jid+'/confirm',headers=h,json={'expectedDraftVersion':1,'expectedRevisionId':doc['latestRevisionId']}).json['data']['revisionId']
    r=c.post('/api/source-documents/'+did+'/ocr',headers=h,json={'expectedRevisionId':rid})
    assert r.status_code==200 and r.json['data']['id']==jid and r.json['data']['status']=='CONFIRMED'
    with app.app_context():assert OcrRun.query.count()==1 and DocumentRevision.query.filter_by(document_id=did).count()==2


@pytest.mark.parametrize('mode',['precise'])
def test_upload_mode_is_recorded_and_returned(setup,mode):
    app,c,h,owner,did,jid,doc,upload=setup
    result=upload(ocrMode=mode);assert result.status_code==201
    identifier=result.json['data']['ocr']['jobId']
    assert c.get('/api/ocr-jobs/'+identifier).json['data']['ocrMode']==mode
    with app.app_context():assert jobs.row(identifier)[1].value['ocrMode']==mode


@pytest.mark.parametrize('mode',['unknown',[],True,None])
def test_invalid_mode_creates_no_job(setup,mode):
    app,c,h,owner,did,jid,doc,_=setup
    response=c.post('/api/source-documents/'+did+'/ocr',headers=h,json={'expectedRevisionId':doc['latestRevisionId'],'ocrMode':mode})
    assert response.status_code==400
    with app.app_context():assert OcrRun.query.count()==1


def test_profile_change_does_not_reuse_active_job_or_overwrite_confirmed_revision(setup):
    app,c,h,owner,did,jid,doc,_=setup
    body={'expectedRevisionId':doc['latestRevisionId'],'ocrMode':'precise','ocrProfile':'drama'}
    assert c.post('/api/source-documents/'+did+'/ocr',headers=h,json=body).status_code==409
    ready(app,jid,'기존 검수 원문')
    old=c.post('/api/ocr-jobs/'+jid+'/confirm',headers=h,json={'expectedDraftVersion':1,'expectedRevisionId':doc['latestRevisionId']}).json['data']['revisionId']
    body['expectedRevisionId']=old
    new=c.post('/api/source-documents/'+did+'/ocr',headers=h,json=body)
    assert new.status_code==202 and new.json['data']['id']!=jid
    current=c.get('/api/source-documents/'+did).json['data'];assert current['content']=='기존 검수 원문' and current['status']=='등록 완료'
    with app.app_context():
        assert db.session.get(DocumentRevision,old).content=='기존 검수 원문'
        assert DocumentRevision.query.filter_by(document_id=did).count()==2
        assert jobs.row(new.json['data']['id'])[1].value['ocrMode']=='precise'
        assert jobs.row(new.json['data']['id'])[1].value['ocrProfile']=='drama'
    assert c.get('/api/ocr-jobs/'+jid).json['data']['status']=='CONFIRMED'


def test_standard_region_cannot_activate_heavy_engines_and_inherits_mode(setup):
    app,c,h,owner,did,jid,doc,_=setup;ready(app,jid)
    with app.app_context():
        _,record=jobs.row(jid);record.value={**record.value,'ocrMode':'standard'};db.session.commit()
    payload={'page':1,'box':[0,0,100,50],'engine':'vl'}
    assert c.post('/api/ocr-jobs/'+jid+'/region',headers=h,json=payload).status_code==400
    payload['engine']='tesseract';assert c.post('/api/ocr-jobs/'+jid+'/region',headers=h,json=payload).status_code==400
    payload['engine']='paddle';result=c.post('/api/ocr-jobs/'+jid+'/region',headers=h,json=payload)
    assert result.status_code==202
    assert c.get('/api/ocr-jobs/'+result.json['data']['id']).json['data']['ocrMode']=='standard'


def test_invalid_upload_mode_is_rejected_before_new_source(setup):
    app,c,h,owner,did,jid,doc,upload=setup
    assert upload(ocrMode='unknown').status_code==400
    with app.app_context():assert SourceDocument.query.count()==1 and OcrRun.query.count()==1
