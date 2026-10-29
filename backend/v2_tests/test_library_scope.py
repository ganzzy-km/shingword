"""Synthetic isolated0004 data only; no operating DB, real sources or OIDC."""
import hashlib
import json
from pathlib import Path
from datetime import timedelta
import pytest
from v2_fixture import v2app,user_client
from test_library_api import upload
from test_analysis_api import essay,analyze
from app.extensions import db
from app.models import SourceDocument,DocumentRevision,Work,WorkDocument,ActivityRecord,Analysis,WritingVersion


def admin(app):return user_client(app,'scope-admin','ADMIN')
def source(c,h,**metadata):
    return upload(c,h,body='합성 작품에서 인물은 낯선 손님에게 물을 건넨다. 원문 전문 보호 표식 ONLY_SYNTHETIC_FULL_SOURCE.',rightsConfirmed='true',rightsInfo='합성 창작 원문 공개 이용 확인',**metadata).json['data']
def change(c,h,d,scope):return c.patch('/api/source-documents/'+d['id']+'/scope',headers=h,json={'scope':scope,'expectedRevisionId':d['latestRevisionId']})
def state(app,d):
    with app.app_context():
        doc=db.session.get(SourceDocument,d['id']);r=db.session.get(DocumentRevision,d['latestRevisionId'])
        return {'id':doc.id,'owner':doc.owner_id,'name':doc.stored_name,'scope':doc.scope,'mode':doc.access_mode,'rights':doc.rights_confirmed,'rightsInfo':doc.rights_info,'rid':r.id,'revision':r.revision_number,'hash':r.content_hash,'text':r.content,'file':r.file_ref,'revisionCreated':str(r.created_at),'fileHash':hashlib.sha256((Path(app.config['UPLOAD_FOLDER'])/doc.stored_name).read_bytes()).hexdigest()}


def test_admin_roundtrip_is_idempotent_preserves_files_history_and_audit(v2app):
    c,h,uid=admin(v2app);d=source(c,h,accessMode='DOWNLOAD');before=state(v2app,d)
    assert d['canManageScope'] is True and d['scope']=='PRIVATE'
    for scope in ['PUBLIC','PUBLIC','PRIVATE','PRIVATE']:
        r=change(c,h,d,scope);assert r.status_code==200 and r.json['data']['scope']==scope
        after=state(v2app,d);assert {k:v for k,v in after.items() if k!='scope'}=={k:v for k,v in before.items() if k!='scope'}
    with v2app.app_context():
        assert SourceDocument.query.count()==DocumentRevision.query.count()==1
        events=ActivityRecord.query.filter_by(action='DOCUMENT_SCOPE_CHANGED').order_by(ActivityRecord.created_at).all()
        assert [e.details['after'] for e in events]==['PUBLIC','PRIVATE']
        assert all(e.actor_id==uid and e.target_id==d['id'] and 'text' not in e.details for e in events)


@pytest.mark.parametrize('field,value',[('ownerId','other'),('accessMode','DOWNLOAD'),('rightsConfirmed',True),('content','injected'),('workId','other'),('role','ADMIN')])
def test_extra_fields_never_modify_owner_rights_or_content(v2app,field,value):
    c,h,_=admin(v2app);d=source(c,h);before=state(v2app,d)
    r=c.patch('/api/source-documents/'+d['id']+'/scope',headers=h,json={'scope':'PUBLIC','expectedRevisionId':d['latestRevisionId'],field:value})
    assert r.status_code==400 and state(v2app,d)==before


@pytest.mark.parametrize('value',[None,[],{},True,'ALL'])
def test_invalid_scope_payload_denied(v2app,value):
    c,h,_=admin(v2app);d=source(c,h)
    assert c.patch('/api/source-documents/'+d['id']+'/scope',headers=h,json={'scope':value,'expectedRevisionId':d['latestRevisionId']}).status_code==400
    assert state(v2app,d)['scope']=='PRIVATE'


def test_anonymous_csrf_and_user_scope_requests_are_denied(v2app):
    c,h,_=admin(v2app);d=source(c,h);payload={'scope':'PUBLIC','expectedRevisionId':d['latestRevisionId']};url='/api/source-documents/'+d['id']+'/scope'
    assert v2app.test_client().patch(url,json=payload).status_code==401
    assert c.patch(url,json=payload).status_code==401
    u,uh,_=user_client(v2app);own=source(u,uh)
    assert change(u,uh,own,'PUBLIC').status_code==403
    # Existing verified public uploader capability is not an ADMIN scope grant.
    publisher,ph,_=user_client(v2app,'public-uploader',email='ps00000@onedu.jje.go.kr',verified=True)
    assert change(publisher,ph,d,'PUBLIC').status_code==403
    assert change(c,h,d,'PUBLIC').status_code==200
    assert change(u,uh,d,'PRIVATE').status_code==403
    assert all(not x['canManageScope'] for x in u.get('/api/source-documents').json['data'])


def test_admin_has_no_foreign_private_lookup_or_conversion(v2app):
    c,h,_=admin(v2app);u,uh,_=user_client(v2app);d=source(u,uh)
    assert c.get('/api/source-documents/'+d['id']).status_code==404
    assert all(x['id']!=d['id'] for x in c.get('/api/source-documents').json['data'])
    assert change(c,h,d,'PUBLIC').status_code==404
    other,oh,_=user_client(v2app,'second-admin','ADMIN');own=source(c,h)
    assert change(c,h,own,'PUBLIC').status_code==200
    assert change(other,oh,own,'PRIVATE').status_code==404
    assert other.get('/api/source-documents/'+own['id']).json['data']['canManageScope'] is False


@pytest.mark.parametrize('field,value',[('rights_confirmed',False),('rights_info',' '),('title',' '),('document_type',None)])
def test_publication_requires_existing_rights_and_metadata(v2app,field,value):
    c,h,_=admin(v2app);d=source(c,h)
    with v2app.app_context():setattr(db.session.get(SourceDocument,d['id']),field,value);db.session.commit()
    r=change(c,h,d,'PUBLIC');assert r.status_code==409 and r.json['error']['code']=='PUBLIC_METADATA_REQUIRED'
    assert state(v2app,d)['scope']=='PRIVATE'


def test_revision_conflict_and_other_private_editions_are_not_exposed(v2app):
    c,h,_=admin(v2app);d=source(c,h)
    bad={**d,'latestRevisionId':'other-revision'}
    assert change(c,h,bad,'PUBLIC').status_code==409
    revised=c.post('/api/source-documents/'+d['id']+'/revisions',headers=h,json={'content':'별도 개인 판본','expectedRevisionId':d['latestRevisionId']}).json['data']['id']
    latest={**d,'latestRevisionId':revised}
    assert change(c,h,latest,'PUBLIC').status_code==409
    u,_,_=user_client(v2app);assert u.get('/api/source-documents').json['data']==[]
    with v2app.app_context():assert DocumentRevision.query.count()==2 and ActivityRecord.query.filter_by(action='DOCUMENT_SCOPE_CHANGED').count()==0


def test_work_scope_is_atomic_without_publishing_sibling_documents(v2app):
    c,h,_=admin(v2app);wid=c.post('/api/works',headers=h,json={'title':'합성 작품','author':'가상 작가','genre':'소설'}).json['data']['id']
    a=source(c,h,workId=wid);b=source(c,h,workId=wid);u,_,_=user_client(v2app)
    assert change(c,h,a,'PUBLIC').status_code==200
    assert [x['id'] for x in u.get('/api/source-documents').json['data']]==[a['id']]
    with v2app.app_context():assert db.session.get(Work,wid).scope=='PUBLIC' and db.session.get(SourceDocument,b['id']).scope=='PRIVATE'
    assert change(c,h,b,'PUBLIC').status_code==200
    assert change(c,h,a,'PRIVATE').status_code==200
    with v2app.app_context():assert db.session.get(Work,wid).scope=='PUBLIC'
    assert change(c,h,b,'PRIVATE').status_code==200
    assert u.get('/api/works').json['data']==[]


def test_foreign_or_ambiguous_linked_work_blocks_publication(v2app):
    c,h,_=admin(v2app);d=source(c,h);u,uh,_=user_client(v2app)
    wid=u.post('/api/works',headers=uh,json={'title':'다른 사용자 개인 작품'}).json['data']['id']
    with v2app.app_context():db.session.add(WorkDocument(work_id=wid,document_id=d['id']));db.session.commit()
    assert change(c,h,d,'PUBLIC').status_code==409
    with v2app.app_context():assert db.session.get(Work,wid).scope=='PRIVATE'


def test_failed_commit_rolls_back_document_work_and_audit(v2app,monkeypatch):
    c,h,_=admin(v2app);wid=c.post('/api/works',headers=h,json={'title':'원자적 시험 작품'}).json['data']['id'];d=source(c,h,workId=wid);before=state(v2app,d)
    original=db.session.commit
    def fail():raise RuntimeError('synthetic commit failure')
    monkeypatch.setattr(db.session,'commit',fail)
    r=change(c,h,d,'PUBLIC');assert r.status_code==500 and r.json['error']['code']=='SCOPE_CHANGE_FAILED'
    monkeypatch.setattr(db.session,'commit',original)
    assert state(v2app,d)==before
    with v2app.app_context():assert db.session.get(Work,wid).scope=='PRIVATE' and ActivityRecord.query.filter_by(action='DOCUMENT_SCOPE_CHANGED').count()==0


def test_publication_does_not_extend_private_retention_or_run_cleanup(v2app):
    from app.v2.privacy_lifecycle import document_deadline,DOCUMENT_POLICY,purge_due_documents
    v2app.config['PRIVATE_DOCUMENT_RETENTION_POLICY']=DOCUMENT_POLICY
    c,h,_=admin(v2app);d=source(c,h)
    with v2app.app_context():due=document_deadline(db.session.get(SourceDocument,d['id']))
    assert change(c,h,d,'PUBLIC').status_code==200
    with v2app.app_context():
        assert document_deadline(db.session.get(SourceDocument,d['id'])) is None
        v2app.config.update(RETENTION_APPROVED=True,RETENTION_BACKUPS_VERIFIED=True)
        assert purge_due_documents(due+timedelta(days=1))['removed']==0
    assert change(c,h,d,'PRIVATE').status_code==200
    with v2app.app_context():assert document_deadline(db.session.get(SourceDocument,d['id']))==due


@pytest.mark.parametrize('mode',['MATCH_ONLY','VIEW','DOWNLOAD'])
def test_public_source_access_modes_remain_independent(v2app,mode):
    c,h,_=admin(v2app);d=source(c,h,accessMode=mode);assert change(c,h,d,'PUBLIC').status_code==200
    u,uh,_=user_client(v2app);listed=u.get('/api/source-documents').json['data'];assert listed[0]['id']==d['id']
    assert 'content' not in listed[0] and 'pageData' not in listed[0]
    detail=u.get('/api/source-documents/'+d['id']).json['data'];assert detail['accessMode']==mode
    assert ('content' in detail)==(mode!='MATCH_ONLY')
    assert u.get('/api/source-documents/'+d['id']+'/revisions/'+d['latestRevisionId']).status_code==(404 if mode=='MATCH_ONLY' else 200)
    assert u.get('/api/files/source/'+d['id']).status_code==(200 if mode=='DOWNLOAD' else 404)
    match=u.post('/api/source-documents/'+d['id']+'/search',headers=uh,json={'revisionId':d['latestRevisionId'],'quote':'낯선 손님에게 물을 건넨다'})
    assert match.status_code==200 and 'excerpt' not in match.json['data'] if mode=='MATCH_ONLY' else match.status_code==200


def test_unpublication_preserves_saved_analysis_but_revokes_all_new_source_use(v2app):
    v2app.config['GEULBIT_S4_ENGINE']=True
    c,h,_=admin(v2app);d=source(c,h,accessMode='MATCH_ONLY');assert change(c,h,d,'PUBLIC').status_code==200
    u,uh,_=user_client(v2app);w=essay(u,uh,'낯선 이를 받아들이는 태도가 중요하다고 생각한다. 작품에서 인물은 “낯선 손님에게 물을 건넨다”.')
    assert u.post('/api/writings/'+w['id']+'/documents',headers=uh,json={'revisionId':d['latestRevisionId']}).status_code==200
    ids=analyze(v2app,u,uh,w).json['data'];saved=u.get('/api/analyses/'+ids['analysisId']);assert saved.status_code==200
    assert 'ONLY_SYNTHETIC_FULL_SOURCE' not in saved.get_data(as_text=True)
    before=json.dumps(saved.json['data'],sort_keys=True,ensure_ascii=False)
    assert change(c,h,d,'PRIVATE').status_code==200
    again=u.get('/api/analyses/'+ids['analysisId']);assert again.status_code==200 and json.dumps(again.json['data'],sort_keys=True,ensure_ascii=False)==before
    assert u.get('/api/source-documents').json['data']==[]
    assert u.get('/api/source-documents/'+d['id']).status_code==404
    assert u.get('/api/files/source/'+d['id']).status_code==404
    assert u.post('/api/source-documents/'+d['id']+'/search',headers=uh,json={'revisionId':d['latestRevisionId'],'quote':'낯선 손님'}).status_code==404
    w2=essay(u,uh,'공개 중지 후 새 선택 시험')
    assert u.post('/api/writings/'+w2['id']+'/documents',headers=uh,json={'revisionId':d['latestRevisionId']}).status_code==404
    assert analyze(v2app,u,uh,w).status_code==404
    assert u.get('/api/analyses/'+ids['analysisId']+'/pdf').status_code==404
    assert u.post('/api/analyses/'+ids['analysisId']+'/ai/preview',headers=uh,json={}).status_code==404
    other,_,_=user_client(v2app,'other-reader');assert other.get('/api/analyses/'+ids['analysisId']).status_code==404
    with v2app.app_context():assert Analysis.query.count()==1 and WritingVersion.query.count()==1
