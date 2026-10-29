import io
import time
from datetime import datetime,timezone,timedelta
from pathlib import Path
import pymupdf as fitz
from v2_fixture import v2app,user_client
from test_analysis_api import essay,analyze
from app.extensions import db
from app.models import Writing,Analysis,AppSetting
from app.v2 import operations_api


def completed(app,c,h,body='나는 몇일 동안 생각했다. 😀 漢字\n\n작품의 인물은 달렸다.'):
    w=essay(c,h,body);response=analyze(app,c,h,w);assert response.status_code==202
    return w,response.json['data']['analysisId']


def test_pdf_actual_version_korean_and_import_new_owner(v2app):
    c,h,uid=user_client(v2app);w,r=completed(v2app,c,h)
    c.patch('/api/writings/'+w['id'],headers=h,json={'content':'changed draft','revisionNumber':1})
    pdf=c.get('/api/analyses/'+r+'/pdf');assert pdf.status_code==200 and pdf.data.startswith(b'%PDF-')
    with fitz.open(stream=pdf.data,filetype='pdf') as doc:
        rendered=''.join(p.get_text() for p in doc);assert '몇일' in rendered and 'changed draft' not in rendered and '漢字' in rendered
    p=c.post('/api/pdf-import/preview',headers=h,data={'file':(io.BytesIO(pdf.data),'report.pdf')})
    assert p.status_code==200;preview=p.json['data'];assert preview['text']==w['content'] and preview['restoreAnalysis'] is False
    other,oh,_=user_client(v2app,'other')
    assert other.post('/api/pdf-import/confirm',headers=oh,json={'previewId':preview['previewId'],'confirmed':True}).status_code==409
    assert c.post('/api/pdf-import/confirm',headers=h,json={'previewId':preview['previewId'],'confirmed':False}).status_code==400
    created=c.post('/api/pdf-import/confirm',headers=h,json={'previewId':preview['previewId'],'confirmed':True,'title':'imported'})
    assert created.status_code==201 and created.json['data']['id']!=w['id'] and created.json['data']['analysisRuns']==[]
    with v2app.app_context():assert db.session.get(Writing,created.json['data']['id']).owner_id==uid
    assert c.post('/api/pdf-import/confirm',headers=h,json={'previewId':preview['previewId'],'confirmed':True}).status_code==409


def test_expired_read_save_pdf_and_list_blocked(v2app):
    c,h,_=user_client(v2app);w,r=completed(v2app,c,h)
    with v2app.app_context():db.session.get(Writing,w['id']).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.session.commit()
    assert c.get('/api/writings/'+w['id']).status_code==404
    assert c.patch('/api/writings/'+w['id'],headers=h,json={'content':'new','revisionNumber':1}).status_code==404
    assert c.get('/api/analyses/'+r+'/pdf').status_code==404
    assert c.get('/api/writings').json['data']==[]


def test_expiry_during_pdf_no_output(v2app,monkeypatch):
    c,h,_=user_client(v2app);w,r=completed(v2app,c,h);real=operations_api.create_report
    def expire(*args,**kwargs):
        data=real(*args,**kwargs)
        with v2app.app_context():db.session.get(Writing,w['id']).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.session.commit()
        return data
    monkeypatch.setattr(operations_api,'create_report',expire)
    assert c.get('/api/analyses/'+r+'/pdf').status_code==404


def test_pdf_idor_and_admin_no_private_override(v2app):
    c,h,_=user_client(v2app);w,r=completed(v2app,c,h)
    for role in ['USER','ADMIN']:
        other,_,_=user_client(v2app,role,role)
        assert other.get('/api/analyses/'+r+'/pdf').status_code==404


def test_pdf_malformed_active_and_scan_rejected(v2app):
    c,h,_=user_client(v2app)
    assert c.post('/api/pdf-import/preview',headers=h,data={'file':(io.BytesIO(b'%PDF-broken'),'x.pdf')}).status_code==422
    doc=fitz.open();doc.new_page();scan=doc.tobytes();doc.close()
    response=c.post('/api/pdf-import/preview',headers=h,data={'file':(io.BytesIO(scan),'scan.pdf')})
    assert response.status_code==422 and response.json['error']['code']=='OCR_REQUIRED_NOT_SUPPORTED'
    doc=fitz.open();doc.new_page().insert_text((70,70),'synthetic');xref=doc.get_new_xref();doc.update_object(xref,r'<< /S /JavaScript /JS (alert\(1\)) >>');active=doc.tobytes();doc.close()
    assert c.post('/api/pdf-import/preview',headers=h,data={'file':(io.BytesIO(active),'active.pdf')}).status_code==422


def test_admin_operations_and_no_unapproved_deletion(v2app):
    user,h,_=user_client(v2app);w=essay(user,h)
    assert user.get('/api/admin/operations').status_code==403
    admin,ah,_=user_client(v2app,'admin','ADMIN')
    status=admin.get('/api/admin/operations').json['data'];assert status['database']=='READY' and status['retention']=='BLOCKED_POLICY_UNCONFIRMED'
    assert admin.post('/api/admin/retention/cleanup',headers=ah).status_code==409
    assert user.get('/api/writings/'+w['id']).status_code==200
    assert admin.post('/api/backups',headers=ah).status_code==403


def test_admin_rules_audit_switch_no_student_body(v2app):
    admin,h,_=user_client(v2app,'admin','ADMIN')
    from app.analysis.ruleset import catalogue
    rid=catalogue()[0]['rule_id']
    assert admin.patch('/api/admin/rules',headers=h,json={'disabledRules':[rid]}).status_code==200
    assert admin.patch('/api/admin/rules',headers=h,json={'disabledRules':['invented']}).status_code==400
    assert admin.patch('/api/admin/ai',headers=h,json={'enabled':False}).status_code==200
    entries=admin.get('/api/admin/audit').json['data'];assert len(entries)==2 and all('details' not in x for x in entries)


def test_long_pdf_complete_body_and_no_temporary_files(v2app):
    c,h,_=user_client(v2app);body=('가상의 학생은 작품을 읽고 몇일 동안 생각했다. 😀 漢字\n\n'*1000)[:30000]
    w,r=completed(v2app,c,h,body);pdf=c.get('/api/analyses/'+r+'/pdf');assert pdf.status_code==200
    with fitz.open(stream=pdf.data,filetype='pdf') as doc:assert doc.page_count>1
    p=c.post('/api/pdf-import/preview',headers=h,data={'file':(io.BytesIO(pdf.data),'long.pdf')});assert p.json['data']['text']==body
    assert not list(Path(v2app.config['TEMP_FOLDER']).glob('*.pdf'))


def test_explicit_owner_removal_fk_integrity_and_pending_job(v2app):
    c,h,_=user_client(v2app);w,r=completed(v2app,c,h)
    assert c.delete('/api/records/'+w['id'],headers=h,json={'confirmation':'wrong'}).status_code==400
    other,oh,_=user_client(v2app,'other','ADMIN')
    assert other.delete('/api/records/'+w['id'],headers=oh,json={'confirmation':w['title']}).status_code==404
    assert c.delete('/api/records/'+w['id'],headers=h,json={'confirmation':w['title']}).status_code==200
    assert c.get('/api/analyses/'+r).status_code==404
    with v2app.app_context():assert db.session.execute(db.text('PRAGMA foreign_key_check')).all()==[] and db.session.get(Writing,w['id']) is None


def test_private_criteria_and_document_delete_guard(v2app):
    c,h,_=user_client(v2app);other,oh,_=user_client(v2app,'other','ADMIN')
    r=c.post('/api/rubrics',headers=h,data={'file':(io.BytesIO('가상 평가 기준'.encode()),'criteria.txt'),'name':'synthetic criteria'})
    assert r.status_code==201;rid=r.json['data']['id']
    assert other.get('/api/rubrics/'+rid).status_code==404
    assert c.patch('/api/rubrics/'+rid,headers=h,json={'correctedText':'수정한 가상 기준','confirm':True}).status_code==200
    assert c.post('/api/rubrics/'+rid+'/ocr',headers=h).status_code==409
    assert c.delete('/api/rubrics/'+rid,headers=h).status_code==200
    doc=c.post('/api/source-documents',headers=h,data={'file':(io.BytesIO('가상 자료 본문'.encode()),'source.txt')}).json['data']
    assert other.delete('/api/source-documents/'+doc['id'],headers=oh).status_code==404
    assert c.delete('/api/source-documents/'+doc['id'],headers=h).status_code==200


def test_preview_cache_actually_evicts_without_another_request():
    store=operations_api.PreviewStore(ttl=.03);key=store.save('synthetic-owner',{'text':'synthetic temporary text'})
    assert key in store.items;time.sleep(.08);assert key not in store.items and not store.timers


def test_admin_limits_explicit_configuration(v2app):
    c,h,_=user_client(v2app,'admin','ADMIN')
    assert c.patch('/api/admin/ai/limits',headers=h,json={}).status_code==400
    limits={'dailyRequests':2,'monthlyBudgetUnits':10,'callCostUnits':1,'cooldownSeconds':5,'concurrency':1}
    assert c.patch('/api/admin/ai/limits',headers=h,json=limits).status_code==200
    assert c.patch('/api/admin/ai',headers=h,json={'enabled':True}).status_code==200
    assert c.patch('/api/admin/ai/limits',headers=h,json=limits).status_code==409
    assert c.get('/api/ai/status').json['data']['externalApproved'] is False


def test_expiry_during_analysis_never_recreates_result(v2app,monkeypatch):
    from app.v2 import analysis_api
    c,h,_=user_client(v2app);w=essay(c,h);real=analysis_api.analyze_input
    def expire(*args):
        value=real(*args)
        with v2app.app_context():db.session.get(Writing,w['id']).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.session.commit()
        return value
    monkeypatch.setattr(analysis_api,'analyze_input',expire)
    ids=analyze(v2app,c,h,w).json['data']
    with v2app.app_context():assert db.session.get(Analysis,ids['analysisId']).result_snapshot is None
    assert c.get('/api/analyses/'+ids['analysisId']).status_code==404


def test_waitress_loopback_readiness_start_stop(v2app):
    import threading
    import urllib.request
    from waitress import create_server
    server=create_server(v2app,listen='127.0.0.1:0',threads=2)
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    try:
        with urllib.request.urlopen('http://127.0.0.1:'+str(server.effective_port)+'/api/health',timeout=5) as response:
            import json
            from app.storage import SCHEMA_HEAD
            assert response.status==200 and json.load(response)['data']['schema']==SCHEMA_HEAD
    finally:
        server.close();server.task_dispatcher.shutdown();thread.join(2)


def test_isolated_certified_expiry_graph_cleanup_retry_and_fk(v2app):
    c,h,_=user_client(v2app);w,r=completed(v2app,c,h)
    with v2app.app_context():
        db.session.get(Writing,w['id']).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.session.commit()
        import pytest
        with pytest.raises(ValueError):operations_api.purge_due_essays(v2app)
        assert db.session.get(Analysis,r) is not None
        # Synthetic test policy, never a product policy or an operational setting.
        v2app.config.update(RETENTION_APPROVED=True,RETENTION_DATES_VERIFIED=True,RETENTION_BACKUPS_VERIFIED=True,RETENTION_POLICY={'basis':'synthetic certified dates','targetScope':'PRIVATE_ESSAY_GRAPH','backupRetention':'synthetic no user-content backup','accountPolicy':'synthetic independent','publicDocumentPolicy':'synthetic independent','privateDocuments':'SEPARATE_APPROVED_LIFECYCLE'})
        assert operations_api.purge_due_essays(v2app)==1
        assert operations_api.purge_due_essays(v2app)==0
        assert db.session.execute(db.text('PRAGMA foreign_key_check')).all()==[]
        assert db.session.get(Analysis,r) is None


def test_cleanup_failure_rolls_back_graph_then_safe_retry(v2app,monkeypatch):
    import pytest
    c,h,_=user_client(v2app);w,r=completed(v2app,c,h)
    v2app.config.update(RETENTION_APPROVED=True,RETENTION_DATES_VERIFIED=True,RETENTION_BACKUPS_VERIFIED=True,RETENTION_POLICY={'basis':'synthetic certified dates','targetScope':'PRIVATE_ESSAY_GRAPH','backupRetention':'synthetic no user-content backup','accountPolicy':'synthetic independent','publicDocumentPolicy':'synthetic independent','privateDocuments':'SEPARATE_APPROVED_LIFECYCLE'})
    real=operations_api.remove_essay_graph
    def broken(identifier):real(identifier);raise RuntimeError('synthetic cleanup failure')
    with v2app.app_context():
        db.session.get(Writing,w['id']).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.session.commit()
        monkeypatch.setattr(operations_api,'remove_essay_graph',broken)
        with pytest.raises(RuntimeError):operations_api.purge_due_essays(v2app)
        assert db.session.get(Writing,w['id']) is not None and db.session.get(Analysis,r).result_snapshot is not None
        from app.models import ActivityRecord
        assert ActivityRecord.query.filter_by(action='RETENTION_CLEANUP_FAILED').one().details=={'errorType':'RuntimeError'}
        monkeypatch.setattr(operations_api,'remove_essay_graph',real)
        assert operations_api.purge_due_essays(v2app)==1


def test_revoked_account_during_pdf_preview_no_cached_text(v2app,monkeypatch):
    c,h,uid=user_client(v2app);w,r=completed(v2app,c,h);pdf=c.get('/api/analyses/'+r+'/pdf');real=operations_api.extract_preview
    def revoke(*args,**kwargs):
        preview=real(*args,**kwargs)
        from app.models import User
        with v2app.app_context():db.session.get(User,uid).session_version+=1;db.session.commit()
        return preview
    monkeypatch.setattr(operations_api,'extract_preview',revoke)
    assert c.post('/api/pdf-import/preview',headers=h,data={'file':(io.BytesIO(pdf.data),'report.pdf')}).status_code==403
    assert 'v2_pdf_previews' not in v2app.extensions


def test_real_list_pagination_does_not_repeat_books(v2app):
    c,h,_=user_client(v2app)
    created=[essay(c,h,'synthetic '+str(i)) for i in range(13)]
    first=c.get('/api/writings?page=1&pageSize=12').json['data'];second=c.get('/api/writings?page=2&pageSize=12').json['data']
    assert len(first)==12 and len(second)==1
    assert {r['id'] for r in first}.isdisjoint({r['id'] for r in second})
    assert {r['id'] for r in first+second}=={r['id'] for r in created}
    assert first[0]['createdAt'].endswith('+00:00')
    assert c.get('/api/writings?page=0').status_code==400


import pytest
@pytest.mark.parametrize('endpoint,hex_name',[('/api/source-documents',True),('/api/rubrics',False)])
def test_exclusive_upload_collision_preserves_existing_file(v2app,monkeypatch,endpoint,hex_name):
    from app.v2 import library_api
    c,h,_=user_client(v2app)
    fixed=library_api.uuid.UUID('00000000-0000-0000-0000-000000000001')
    monkeypatch.setattr(library_api.uuid,'uuid4',lambda:fixed)
    directory=Path(v2app.config['UPLOAD_FOLDER']);directory.mkdir(parents=True,exist_ok=True)
    target=directory/((fixed.hex if hex_name else str(fixed))+'.txt');target.write_bytes(b'protected-existing-synthetic-file')
    response=c.post(endpoint,headers=h,data={'file':(io.BytesIO('새 가상 자료'.encode()),'new.txt')})
    assert response.status_code==500
    assert target.read_bytes()==b'protected-existing-synthetic-file'


def test_current_selected_revision_replaces_link_without_rewriting_past_run(v2app):
    c,h,_=user_client(v2app);d=c.post('/api/source-documents',headers=h,data={'file':(io.BytesIO('달빛은 숲을 비춘다.'.encode()),'edition.txt')}).json['data']
    w=essay(c,h,'나는 “달빛은 숲을 비춘다.”라는 구절을 골랐다.')
    c.post('/api/writings/'+w['id']+'/documents',headers=h,json={'revisionId':d['latestRevisionId']})
    a=analyze(v2app,c,h,w).json['data'];before=c.get('/api/analyses/'+a['analysisId']).json['data']
    newer=c.post('/api/source-documents/'+d['id']+'/revisions',headers=h,json={'expectedRevisionId':d['latestRevisionId'],'content':'별빛은 강을 비춘다.'}).json['data']['id']
    assert c.post('/api/writings/'+w['id']+'/documents',headers=h,json={'revisionId':newer}).status_code==200
    b=analyze(v2app,c,h,w).json['data'];after=c.get('/api/analyses/'+b['analysisId']).json['data']
    assert [x['revisionId'] for x in after['contextSnapshot']['documents']]==[newer]
    assert after['result']['quoteChecks'][0]['status']=='NOT_FOUND_IN_SELECTED_REVISION'
    assert c.get('/api/analyses/'+a['analysisId']).json['data']['contextSnapshot']==before['contextSnapshot']


def test_admin_ai_status_uses_same_approved_terms_flag(v2app):
    admin,headers,_=user_client(v2app,'synthetic-ai-status-admin','ADMIN')
    for approved in [False,True]:
        v2app.config['EXTERNAL_AI_TERMS_APPROVED']=approved
        response=admin.patch('/api/admin/ai',headers=headers,json={'enabled':False})
        assert response.status_code==200 and response.json['data']['externalApproved'] is approved
        assert response.json['data']['enabled'] is False
