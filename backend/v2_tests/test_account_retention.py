"""Synthetic isolated DB only; no operating cleanup or provider calls."""
from datetime import datetime, timedelta, timezone
import pytest
from v2_fixture import v2app, user_client
from app.extensions import db
from app.models import User, Consent, AppSetting, ActivityRecord, Workspace, WorkspaceSetting
from app.v2.privacy_lifecycle import ACCOUNT_POLICY, POLICY, NO_BACKUP_POLICY, account_deadline, withdraw, purge_due_accounts
from app.v2.operations_api import purge_due_essays

def stamp(year,month,day):return datetime(year,month,day,12,30,tzinfo=timezone.utc)

@pytest.mark.parametrize('start,end',[(stamp(2026,12,31),stamp(2027,2,28)),(stamp(2023,12,31),stamp(2024,2,29)),(stamp(2026,7,31),stamp(2026,9,30)),(stamp(2026,10,11),stamp(2026,12,11))])
def test_calendar_month_boundaries(start,end):assert account_deadline(start)==end

def activate(app):app.config.update(ACCOUNT_RETENTION_APPROVED=True,ACCOUNT_RETENTION_POLICY=ACCOUNT_POLICY)

def scheduled(app,at):
    c,h,uid=user_client(app)
    with app.app_context():
        db.session.add(Consent(user_id=uid,kind='privacy',policy_version='synthetic',granted_at=at))
        db.session.add(Workspace(id='synthetic-space',owner_id=uid))
        db.session.flush();db.session.add(WorkspaceSetting(workspace_id='synthetic-space',key='theme',value='default'))
        db.session.commit();withdraw(db.session.get(User,uid),now=at)
    return c,h,uid

def test_exact_deadline_restarts_idempotence_and_no_other_account(v2app):
    activate(v2app);at=stamp(2026,10,11);c,h,uid=scheduled(v2app,at)
    _,_,other=user_client(v2app,subject='unrelated',email='unrelated@example.test')
    assert c.get('/api/auth/session').status_code==401
    with v2app.app_context():
        shared_settings=WorkspaceSetting.query.filter(WorkspaceSetting.workspace_id!='synthetic-space').count()
        assert purge_due_accounts(account_deadline(at)-timedelta(microseconds=1))=={'removed':0,'anonymized':0,'blocked':0}
        assert Consent.query.filter_by(user_id=uid).count()==1
        db.session.remove() # persisted checkpoint, independent ORM session
        assert purge_due_accounts(account_deadline(at))=={'removed':1,'anonymized':0,'blocked':0}
        assert db.session.get(User,uid) is None and db.session.get(User,other).email=='unrelated@example.test'
        assert Consent.query.filter_by(user_id=uid).count()==0
        assert db.session.get(Workspace,'synthetic-space') is None
        assert WorkspaceSetting.query.filter_by(workspace_id='synthetic-space').count()==0
        assert WorkspaceSetting.query.count()==shared_settings
        assert db.session.get(AppSetting,'privacy_account:'+uid) is None
        event=ActivityRecord.query.filter_by(action='ACCOUNT_WITHDRAWAL').one()
        assert event.actor_id is None and event.target_id is None and event.details=={}
        assert db.session.execute(db.text('PRAGMA foreign_key_check')).all()==[]
        assert purge_due_accounts(account_deadline(at))=={'removed':0,'anonymized':0,'blocked':0}
    assert c.get('/api/auth/session').status_code==401

def test_unconfigured_never_deletes_and_inactive_is_not_withdrawal(v2app):
    _,_,uid=scheduled(v2app,stamp(2026,1,1))
    _,_,other=user_client(v2app,subject='disabled-only')
    with v2app.app_context():
        db.session.get(User,other).status='INACTIVE';db.session.commit()
        with pytest.raises(ValueError):purge_due_accounts(stamp(2026,4,1))
        activate(v2app);assert purge_due_accounts(stamp(2026,4,1))['removed']==1
        assert db.session.get(User,other) is not None

def test_withdrawn_cannot_admin_reactivate_or_bootstrap(v2app):
    _,_,uid=scheduled(v2app,stamp(2026,1,1))
    with v2app.app_context():
        user=db.session.get(User,uid);user.email='synthetic@example.test';user.email_verified=True;db.session.commit()
    args=['bootstrap-admin','--issuer','https://accounts.google.com','--subject','synthetic-user','--confirm-account','synthetic@example.test']
    assert v2app.test_cli_runner().invoke(args=args).exit_code!=0
    admin,h,_=user_client(v2app,subject='admin',role='ADMIN')
    assert admin.patch('/api/admin/users/'+uid,headers=h,json={'status':'ACTIVE'}).status_code==409

def test_public_document_file_and_revision_survive_owner_erasure(v2app):
    from test_library_api import upload
    from app.models import SourceDocument,DocumentRevision
    from pathlib import Path
    activate(v2app);v2app.config['ACCOUNT_PUBLIC_OWNER_ERASURE_APPROVED']=True
    c,h,uid=user_client(v2app,email='ps00000@onedu.jje.go.kr',verified=True)
    r=upload(c,h,scope='PUBLIC',rightsConfirmed='true',rightsInfo='synthetic rights',accessMode='VIEW');assert r.status_code==201
    did=r.json['data']['id']
    with v2app.app_context():
        doc=db.session.get(SourceDocument,did);filename=doc.stored_name
        before=(Path(v2app.config['UPLOAD_FOLDER'])/filename).read_bytes()
        revision=DocumentRevision.query.filter_by(document_id=did).one();snapshot=revision.content
        withdraw(db.session.get(User,uid),now=stamp(2026,1,1))
        assert purge_due_accounts(stamp(2026,4,1))=={'removed':0,'anonymized':1,'blocked':0}
        assert db.session.get(SourceDocument,did).owner_id==uid
        assert DocumentRevision.query.filter_by(document_id=did).one().content==snapshot
        assert (Path(v2app.config['UPLOAD_FOLDER'])/filename).read_bytes()==before
        assert db.session.execute(db.text('PRAGMA foreign_key_check')).all()==[]

def test_oidc_does_not_refresh_withdrawn_account_metadata(v2app):
    from types import SimpleNamespace
    from app.v2.auth_api import CHALLENGE_COOKIE
    c,_,uid=scheduled(v2app,stamp(2026,1,1))
    v2app.config['OIDC_FLOW']=SimpleNamespace(testing=True,finish=lambda *_a,**_k:{'sub':'synthetic-user','email':'new@example.test','emailVerified':True})
    v2app.extensions['v2_challenges']['synthetic-ticket']=object()
    c.set_cookie(CHALLENGE_COOKIE,'synthetic-ticket')
    assert c.get('/api/auth/callback?state=synthetic&code=synthetic').status_code==401
    with v2app.app_context():
        assert db.session.get(User,uid).email!='new@example.test'
        assert db.session.get(AppSetting,'privacy_account:'+uid).value['purgeAt']==stamp(2026,3,1).isoformat()

def test_public_ownership_is_blocked_not_deleted(v2app):
    from app.models import Work
    activate(v2app);_,_,uid=scheduled(v2app,stamp(2026,1,1))
    with v2app.app_context():
        db.session.add(Work(owner_id=uid,title='public synthetic',scope='PUBLIC'));db.session.commit()
        assert purge_due_accounts(stamp(2026,4,1))=={'removed':0,'anonymized':0,'blocked':1}
        assert db.session.get(User,uid) is not None and Consent.query.filter_by(user_id=uid).count()==1
        assert Work.query.count()==1
        assert db.session.get(AppSetting,'privacy_account:'+uid).value['errorCode']=='ACCOUNT_OWNERSHIP_REFERENCE_BLOCKED'
        assert db.session.execute(db.text('PRAGMA foreign_key_check')).all()==[]

def test_failure_rolls_back_and_retry_succeeds(v2app,monkeypatch):
    activate(v2app);_,_,uid=scheduled(v2app,stamp(2026,1,1))
    with v2app.app_context():
        original=db.session.commit;calls=[]
        def fail_once():
            if not calls:calls.append(1);raise RuntimeError('synthetic sensitive exception must not persist')
            return original()
        monkeypatch.setattr(db.session,'commit',fail_once)
        assert purge_due_accounts(stamp(2026,4,1))=={'removed':0,'anonymized':0,'blocked':1}
        assert db.session.get(User,uid) is not None and Consent.query.filter_by(user_id=uid).count()==1
        job=db.session.get(AppSetting,'privacy_account:'+uid)
        assert job.value['errorCode']=='ACCOUNT_PURGE_RETRY_REQUIRED'
        assert 'sensitive' not in str(job.value)
        assert purge_due_accounts(stamp(2026,4,1))=={'removed':1,'anonymized':0,'blocked':0}

def test_deadline_tamper_and_repeated_withdraw_do_not_extend(v2app):
    activate(v2app);_,_,uid=scheduled(v2app,stamp(2026,1,1))
    with v2app.app_context():
        with pytest.raises(ValueError):withdraw(db.session.get(User,uid),now=stamp(2026,2,1))
        job=db.session.get(AppSetting,'privacy_account:'+uid)
        assert job.value['purgeAt']==stamp(2026,3,1).isoformat()
        job.value={**job.value,'purgeAt':stamp(2026,2,1).isoformat()};db.session.commit()
        assert purge_due_accounts(stamp(2026,4,1))['blocked']==1
        assert db.session.get(User,uid) is not None

def test_no_backup_policy_requires_explicit_trusted_approval(v2app):
    policy={'basis':POLICY,'backupRetention':NO_BACKUP_POLICY,'targetScope':'PRIVATE_ESSAY_GRAPH','privateDocuments':'SEPARATE_APPROVED_LIFECYCLE'}
    v2app.config.update(PERSONAL_DATA_POLICY=POLICY,RETENTION_APPROVED=True,RETENTION_DATES_VERIFIED=True,RETENTION_POLICY=policy,RETENTION_BACKUPS_VERIFIED=False)
    with v2app.app_context():
        with pytest.raises(ValueError):purge_due_essays(v2app)
        v2app.config['RETENTION_NO_BACKUP_APPROVED']=True
        assert purge_due_essays(v2app)==0

def test_cleanup_api_reports_pending_public_account(v2app):
    from app.models import Work
    activate(v2app);_,_,uid=scheduled(v2app,stamp(2020,1,1))
    with v2app.app_context():db.session.add(Work(owner_id=uid,title='protected',scope='PUBLIC'));db.session.commit()
    v2app.config.update(PERSONAL_DATA_POLICY=POLICY,RETENTION_APPROVED=True,RETENTION_DATES_VERIFIED=True,RETENTION_NO_BACKUP_APPROVED=True,RETENTION_POLICY={'basis':POLICY,'backupRetention':NO_BACKUP_POLICY,'targetScope':'PRIVATE_ESSAY_GRAPH','privateDocuments':'SEPARATE_APPROVED_LIFECYCLE'})
    admin,h,_=user_client(v2app,subject='admin',role='ADMIN')
    r=admin.post('/api/admin/retention/cleanup',headers=h)
    assert r.status_code==202 and r.json['data']['complete'] is False
    assert r.json['data']['accounts']=={'removed':0,'anonymized':0,'blocked':1}


def test_approved_public_owner_erasure_keeps_reference_without_google_identity(v2app):
    from app.models import Work
    from app.v2.privacy_lifecycle import withdrawn
    activate(v2app);v2app.config['ACCOUNT_PUBLIC_OWNER_ERASURE_APPROVED']=True
    _,_,uid=scheduled(v2app,stamp(2026,1,1))
    with v2app.app_context():
        user=db.session.get(User,uid);original_sub=user.oidc_subject;user.email='original@example.test';user.role='ADMIN'
        db.session.add(Work(owner_id=uid,title='public must survive',scope='PUBLIC'));db.session.commit()
        assert purge_due_accounts(stamp(2026,4,1))=={'removed':0,'anonymized':1,'blocked':0}
        user=db.session.get(User,uid)
        assert user.oidc_subject!=original_sub and user.oidc_issuer=='urn:geulbit:erased-owner'
        assert user.email is None and user.email_verified is False and user.role=='USER' and user.status=='INACTIVE'
        assert Consent.query.filter_by(user_id=uid).count()==0 and withdrawn(uid)
        assert Work.query.one().owner_id==uid
        assert db.session.execute(db.text('PRAGMA foreign_key_check')).all()==[]
        assert purge_due_accounts(stamp(2026,4,1))=={'removed':0,'anonymized':0,'blocked':0}
    admin,h,_=user_client(v2app,subject='admin',role='ADMIN')
    assert admin.patch('/api/admin/users/'+uid,headers=h,json={'status':'ACTIVE'}).status_code==409


def test_local_backup_retention_requires_approval_and_verified_backup(v2app):
    v2app.config.update(PERSONAL_DATA_POLICY=POLICY,RETENTION_APPROVED=True,RETENTION_DATES_VERIFIED=True,RETENTION_BACKUPS_VERIFIED=True,RETENTION_POLICY={'basis':POLICY,'backupRetention':'7d-encrypted-local-c-v1','targetScope':'PRIVATE_ESSAY_GRAPH','privateDocuments':'SEPARATE_APPROVED_LIFECYCLE'})
    with v2app.app_context():
        with pytest.raises(ValueError):purge_due_essays(v2app)
        v2app.config['RETENTION_LOCAL_BACKUP_APPROVED']=True
        assert purge_due_essays(v2app)==0
        v2app.config['RETENTION_BACKUPS_VERIFIED']=False
        with pytest.raises(ValueError):purge_due_essays(v2app)
