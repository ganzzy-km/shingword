import io
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
from v2_fixture import v2app,user_client
from test_analysis_api import essay,analyze
from app.extensions import db
from app.models import Writing,User,SourceDocument,AppSetting,ActivityRecord
from app.v2.privacy_lifecycle import POLICY,retry_files,prune_audit
from app.v2.operations_api import purge_due_essays


def expiry(app,identifier):
    with app.app_context():return db.session.get(Writing,identifier).expires_at


def test_last_successful_body_change_not_title_read_or_analysis(v2app):
    v2app.config['PERSONAL_DATA_POLICY']=POLICY
    c,h,_=user_client(v2app);w=essay(c,h);first=expiry(v2app,w['id'])
    assert first>datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(hours=1)+timedelta(days=7)
    assert c.get('/api/writings/'+w['id']).status_code==200
    same=c.patch('/api/writings/'+w['id'],headers=h,json={'content':w['content'],'revisionNumber':1});assert same.status_code==200
    title=c.patch('/api/writings/'+w['id'],headers=h,json={'title':'changed title','revisionNumber':1});assert title.status_code==200
    w=title.json['data'];assert analyze(v2app,c,h,w).status_code==202
    assert expiry(v2app,w['id'])==first
    assert c.patch('/api/writings/'+w['id'],headers=h,json={'content':'new body','revisionNumber':1}).status_code==409
    assert expiry(v2app,w['id'])==first
    assert c.patch('/api/writings/'+w['id'],headers=h,json={'content':'new body','revisionNumber':w['revisionNumber']}).status_code==200
    assert expiry(v2app,w['id'])>first


def test_file_retry_pending_and_safe_path(v2app,monkeypatch):
    with v2app.app_context():
        path=Path(v2app.config['UPLOAD_FOLDER'])/'synthetic.txt';path.write_text('synthetic')
        db.session.add(AppSetting(key='privacy_job:synthetic',value={'state':'FILES_PENDING','files':['synthetic.txt','../outside']}));db.session.commit()
        real=Path.unlink
        def failed(self,*args,**kwargs):
            if self==path:raise PermissionError('synthetic')
            return real(self,*args,**kwargs)
        monkeypatch.setattr(Path,'unlink',failed);assert retry_files()==1 and path.exists()
        monkeypatch.setattr(Path,'unlink',real);assert retry_files()==1 and not path.exists()
        assert db.session.get(AppSetting,'privacy_job:synthetic').value['files']==['../outside']


def test_withdraw_revokes_session_removes_private_files_keeps_identity(v2app):
    c,h,uid=user_client(v2app);w=essay(c,h)
    doc=c.post('/api/source-documents',headers=h,data={'file':(io.BytesIO(b'synthetic private file'),'private.txt')});assert doc.status_code==201
    with v2app.app_context():filename=db.session.get(SourceDocument,doc.json['data']['id']).stored_name
    response=c.post('/api/account/withdraw',headers=h,json={'confirmation':'WITHDRAW'})
    assert response.status_code==200 and response.json['data']['accountRetention']=='withdrawal/calendar-2months-v1'
    assert c.get('/api/auth/session').status_code==401
    with v2app.app_context():
        assert db.session.get(User,uid).status=='INACTIVE'
        assert db.session.get(Writing,w['id']) is None
        assert SourceDocument.query.filter_by(owner_id=uid).count()==0
        assert db.session.execute(db.text('PRAGMA foreign_key_check')).all()==[]
        assert not (Path(v2app.config['UPLOAD_FOLDER'])/filename).exists()


def test_expiry_policy_stays_blocked_without_backup_gate(v2app):
    v2app.config.update(PERSONAL_DATA_POLICY=POLICY,RETENTION_APPROVED=True,RETENTION_DATES_VERIFIED=True,RETENTION_BACKUPS_VERIFIED=False,RETENTION_POLICY={'basis':POLICY,'targetScope':'PRIVATE_ESSAY_GRAPH','backupRetention':'7d-encrypted-separate-device','privateDocuments':'SEPARATE_APPROVED_LIFECYCLE'})
    c,h,_=user_client(v2app);w=essay(c,h)
    with v2app.app_context():
        db.session.get(Writing,w['id']).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.session.commit()
        with pytest.raises(ValueError):purge_due_essays(v2app)
        v2app.config['RETENTION_BACKUPS_VERIFIED']=True
        assert purge_due_essays(v2app)==1
        assert purge_due_essays(v2app)==0
    assert c.get('/api/writings/'+w['id']).status_code==404


def test_known_log_retention_unknown_consent_preserved(v2app):
    now=datetime.now(timezone.utc)
    with v2app.app_context():
        for action,days in [('CSRF_REJECTED',31),('BOOTSTRAP_ADMIN',91),('BOOTSTRAP_ADMIN',31),('CONSENT_RECORD',100)]:
            db.session.add(ActivityRecord(action=action,target_type='synthetic',target_id='synthetic',details={},created_at=now-timedelta(days=days)))
        db.session.commit();assert prune_audit(now)==2
        assert ActivityRecord.query.count()==2


def test_withdraw_preserves_shared_public_document(v2app):
    from test_library_api import upload
    c,h,uid=user_client(v2app,email='ps00000@onedu.jje.go.kr',verified=True)
    result=upload(c,h,scope='PUBLIC',rightsConfirmed='true',rightsInfo='synthetic approved rights');assert result.status_code==201
    identifier=result.json['data']['id']
    with v2app.app_context():filename=db.session.get(SourceDocument,identifier).stored_name
    assert c.post('/api/account/withdraw',headers=h,json={'confirmation':'WITHDRAW'}).status_code==200
    with v2app.app_context():
        assert db.session.get(SourceDocument,identifier).scope=='PUBLIC'
        assert (Path(v2app.config['UPLOAD_FOLDER'])/filename).exists()


def test_expired_dependent_file_removed_after_multi_revision_graph(v2app):
    from test_library_api import upload
    from app.models import EssayDocument,DocumentRevision
    v2app.config.update(PERSONAL_DATA_POLICY=POLICY,RETENTION_APPROVED=True,RETENTION_DATES_VERIFIED=True,RETENTION_BACKUPS_VERIFIED=True,RETENTION_POLICY={'basis':POLICY,'targetScope':'PRIVATE_ESSAY_GRAPH','backupRetention':'7d-encrypted-separate-device','privateDocuments':'SEPARATE_APPROVED_LIFECYCLE'})
    c,h,_=user_client(v2app);w=essay(c,h);doc=upload(c,h).json['data']
    assert c.post('/api/source-documents/'+doc['id']+'/revisions',headers=h,json={'content':'synthetic second revision','expectedRevisionId':doc['latestRevisionId']}).status_code==201
    with v2app.app_context():
        revision=DocumentRevision.query.filter_by(document_id=doc['id']).order_by(DocumentRevision.revision_number.desc()).first()
        db.session.add(EssayDocument(writing_id=w['id'],revision_id=revision.id))
        filename=db.session.get(SourceDocument,doc['id']).stored_name
        db.session.get(Writing,w['id']).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.session.commit()
        assert purge_due_essays(v2app)==1
        assert db.session.get(SourceDocument,doc['id']) is None
        assert not (Path(v2app.config['UPLOAD_FOLDER'])/filename).exists()
        assert db.session.execute(db.text('PRAGMA foreign_key_check')).all()==[]


def test_independent_document_body_basis_access_and_cleanup(v2app,monkeypatch):
    from app.models import DocumentRevision
    from app.v2.privacy_lifecycle import DOCUMENT_POLICY,document_deadline,purge_due_documents
    v2app.config.update(PRIVATE_DOCUMENT_RETENTION_POLICY=DOCUMENT_POLICY,RETENTION_APPROVED=True,RETENTION_BACKUPS_VERIFIED=True)
    c,h,uid=user_client(v2app)
    upload=c.post('/api/source-documents',headers=h,data={'file':(io.BytesIO(b'synthetic private content'),'private.txt')})
    assert upload.status_code==201;did=upload.json['data']['id']
    with v2app.app_context():
        doc=db.session.get(SourceDocument,did);revision=DocumentRevision.query.filter_by(document_id=did).one();rid=revision.id;due=document_deadline(doc)
    same=c.post('/api/source-documents/'+did+'/revisions',headers=h,json={'content':'synthetic private content','expectedRevisionId':rid});assert same.status_code==200
    with v2app.app_context():assert document_deadline(db.session.get(SourceDocument,did))==due
    different=c.post('/api/source-documents/'+did+'/revisions',headers=h,json={'content':'synthetic changed content','expectedRevisionId':rid});assert different.status_code==201
    with v2app.app_context():
        doc=db.session.get(SourceDocument,did);assert document_deadline(doc)>=due
        future=document_deadline(doc)+timedelta(seconds=1)
    from app.v2 import privacy_lifecycle as lifecycle
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return future if tz else future.replace(tzinfo=None)
    monkeypatch.setattr(lifecycle,'datetime',Clock)
    assert c.get('/api/source-documents/'+did).status_code==404
    assert all(d['id']!=did for d in c.get('/api/source-documents').json['data'])
    assert c.get('/api/files/source/'+did).status_code==404
    with v2app.app_context():
        result=purge_due_documents();assert result=={'removed':1,'blocked':0,'filesPending':0}
        assert db.session.get(SourceDocument,did) is None

def test_independent_rubric_same_body_does_not_extend_and_expiry_denies_access(v2app,monkeypatch):
    from app.models import Rubric
    from app.v2.privacy_lifecycle import DOCUMENT_POLICY,purge_due_rubrics
    v2app.config.update(PRIVATE_DOCUMENT_RETENTION_POLICY=DOCUMENT_POLICY,RETENTION_APPROVED=True,RETENTION_BACKUPS_VERIFIED=True)
    c,h,_=user_client(v2app)
    r=c.post('/api/rubrics',headers=h,data={'file':(io.BytesIO(b'synthetic rubric'),'rubric.txt')});assert r.status_code==201
    rid=r.json['data']['id']
    with v2app.app_context():before=db.session.get(Rubric,rid).file.updated_at
    assert c.patch('/api/rubrics/'+rid,headers=h,json={'correctedText':'synthetic rubric','confirm':True}).status_code==200
    with v2app.app_context():assert db.session.get(Rubric,rid).file.updated_at==before
    future=datetime.now(timezone.utc)+timedelta(days=8)
    from app.v2 import privacy_lifecycle as lifecycle
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return future if tz else future.replace(tzinfo=None)
    monkeypatch.setattr(lifecycle,'datetime',Clock)
    assert c.get('/api/rubrics/'+rid).status_code==404
    assert c.get('/api/rubrics').json['data']==[]
    with v2app.app_context():
        assert purge_due_rubrics()=={'removed':1,'blocked':0,'filesPending':0}
        assert db.session.get(Rubric,rid) is None
