"""Approved lifecycle adapter using existing expiry, settings and deletion graph."""
import uuid
import calendar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from flask import current_app
from sqlalchemy import text
from ..extensions import db
from ..models import AppSetting, Writing, SourceDocument, DocumentRevision, EssayDocument, WorkDocument, Work, Rubric, RubricFile, Workspace, WorkspaceSetting, Consent, ActivityRecord, User, Analysis

POLICY='last-successful-body-change/7d-v1'
ACCOUNT_POLICY='withdrawal/calendar-2months-v1'
NO_BACKUP_POLICY='no-backups-approved-acquaintances-v1'


def account_deadline(at):
    """Two UTC calendar months; clamp month end, preserve time of day."""
    if at.tzinfo is None:raise ValueError('AWARE_WITHDRAWAL_TIME_REQUIRED')
    at=at.astimezone(timezone.utc)
    year,month=divmod(at.year*12+at.month-1+2,12)
    return at.replace(year=year,month=month+1,day=min(at.day,calendar.monthrange(year,month+1)[1]))


def withdrawn(identifier):
    user=db.session.get(User,identifier)
    return (user is not None and user.oidc_issuer=='urn:geulbit:erased-owner') or db.session.get(AppSetting,'privacy_account:'+identifier) is not None


def enabled():
    return current_app.config.get('PERSONAL_DATA_POLICY')==POLICY


def deadline(now=None):
    return (now or datetime.now(timezone.utc))+timedelta(days=7)


def ledger(kind,identifier,**extra):
    key='privacy_revoke:'+kind+':'+identifier
    value={'kind':kind,'id':identifier,'at':datetime.now(timezone.utc).isoformat(),**extra}
    row=db.session.get(AppSetting,key)
    if row:row.value=value
    else:db.session.add(AppSetting(key=key,value=value))


def queue_files(files):
    files=sorted(set(files))
    if any(not name or '/' in name or '\\' in name or ':' in name or name in {'.','..'} for name in files):raise ValueError('UNSAFE_FILE_REFERENCE')
    job=AppSetting(key='privacy_job:'+str(uuid.uuid4()),value={'state':'FILES_PENDING','files':files,'createdAt':datetime.now(timezone.utc).isoformat()})
    db.session.add(job)
    return job.key


def remove_private_document(doc):
    if doc.scope!='PRIVATE':raise ValueError('PUBLIC_DOCUMENT_PROTECTED')
    revisions=DocumentRevision.query.filter_by(document_id=doc.id).order_by(DocumentRevision.revision_number.desc()).all()
    if EssayDocument.query.filter(EssayDocument.revision_id.in_([r.id for r in revisions])).first():raise ValueError('DOCUMENT_STILL_LINKED')
    files={doc.stored_name,*[r.file_ref for r in revisions if r.file_ref]}
    from ..services.ocr_jobs import derived_files_for_delete
    files.update(derived_files_for_delete(doc))
    for filename in files:
        if Path(filename).name!=filename or filename in {'','.', '..'}:raise ValueError('UNSAFE_FILE_REFERENCE')
    # References are explicit; never delete a different owner's quote/card.
    foreign=db.session.execute(text('SELECT 1 FROM quote_card WHERE document_id=:d AND (owner_id IS NULL OR owner_id!=:u)'),{'d':doc.id,'u':doc.owner_id}).first()
    if foreign:raise ValueError('DOCUMENT_OWNERSHIP_CONFLICT')
    foreign_work=Work.query.join(WorkDocument,WorkDocument.work_id==Work.id).filter(WorkDocument.document_id==doc.id,Work.owner_id!=doc.owner_id).first()
    if foreign_work:raise ValueError('DOCUMENT_OWNERSHIP_CONFLICT')
    db.session.execute(text('DELETE FROM quote_card WHERE document_id=:d'),{'d':doc.id})
    db.session.execute(text('DELETE FROM work_documents WHERE document_id=:d'),{'d':doc.id})
    for revision in revisions:db.session.delete(revision);db.session.flush()
    db.session.delete(doc);db.session.flush()
    ledger('document',doc.id)
    return sorted(files)


def queue_essay(identifier):
    from .operations_api import remove_essay_graph
    item=db.session.get(Writing,identifier)
    if not item:return None
    owner=item.owner_id
    docs=SourceDocument.query.join(DocumentRevision,DocumentRevision.document_id==SourceDocument.id).join(EssayDocument,EssayDocument.revision_id==DocumentRevision.id).filter(EssayDocument.writing_id==identifier,SourceDocument.owner_id==owner,SourceDocument.scope=='PRIVATE').all()
    files=[]
    remove_essay_graph(identifier)
    for doc in docs:
        remaining=EssayDocument.query.join(DocumentRevision,EssayDocument.revision_id==DocumentRevision.id).filter(DocumentRevision.document_id==doc.id).first()
        if not remaining and not WorkDocument.query.filter_by(document_id=doc.id).first():files+=remove_private_document(doc)
    ledger('essay',identifier)
    return queue_files(files)


def retry_files():
    """Only post-commit physical deletion; errors retain a durable outbox."""
    root=Path(current_app.config['UPLOAD_FOLDER']).resolve();pending=0
    for job in AppSetting.query.filter(AppSetting.key.like('privacy_job:%')).all():
        if job.value.get('state')!='FILES_PENDING':continue
        left=[]
        for name in job.value['files']:
            try:
                target=root/name
                if Path(name).name!=name or target.is_symlink() or not target.resolve().is_relative_to(root):raise ValueError('UNSAFE_DELETE_PATH')
                # A file referenced by a live revision is never removed.
                if SourceDocument.query.filter_by(stored_name=name).first() or DocumentRevision.query.filter_by(file_ref=name).first() or RubricFile.query.filter_by(stored_name=name).first():raise ValueError('FILE_STILL_REFERENCED')
                target.unlink(missing_ok=True)
            except (OSError,ValueError):left.append(name)
        job.value={**job.value,'state':'FILES_PENDING' if left else 'COMPLETE','files':left}
        pending+=bool(left)
    db.session.commit()
    return pending


def withdraw(user,now=None):
    """Invalidate immediately; persist the first withdrawal deadline atomically."""
    now=now or datetime.now(timezone.utc)
    if withdrawn(user.id):raise ValueError('ACCOUNT_ALREADY_WITHDRAWN')
    due=account_deadline(now)
    user.status='INACTIVE';user.session_version+=1
    for essay in Writing.query.filter_by(owner_id=user.id).all():queue_essay(essay.id)
    files=[]
    for doc in SourceDocument.query.filter_by(owner_id=user.id,scope='PRIVATE').all():files+=remove_private_document(doc)
    for work in Work.query.filter_by(owner_id=user.id,scope='PRIVATE').all():
        WorkDocument.query.filter_by(work_id=work.id).delete(synchronize_session=False)
        db.session.delete(work)
    for rubric in Rubric.query.filter_by(owner_id=user.id).all():
        if db.session.execute(text('SELECT 1 FROM writing_resource WHERE resource_id=:r'),{'r':rubric.id}).first():raise ValueError('RUBRIC_STILL_LINKED')
        if rubric.file:files.append(rubric.file.stored_name)
        db.session.delete(rubric)
    for workspace in Workspace.query.filter_by(owner_id=user.id):workspace.user_name='';workspace.name='탈퇴 계정'
    for consent in Consent.query.filter_by(user_id=user.id,revoked_at=None):consent.revoked_at=now
    db.session.execute(text('DELETE FROM quote_card WHERE owner_id=:u'),{'u':user.id})
    # Public contributions and their ownership FK stay intact.
    ledger('user',user.id,sessionVersion=user.session_version)
    db.session.add(AppSetting(key='privacy_account:'+user.id,value={'policy':ACCOUNT_POLICY,'withdrawnAt':now.isoformat(),'purgeAt':due.isoformat(),'state':'RETAINED'}))
    queue_files(files)
    db.session.add(ActivityRecord(actor_id=user.id,action='ACCOUNT_WITHDRAWAL',target_type='user',target_id=user.id,details={}))
    db.session.commit()
    store=current_app.extensions.get('v2_pdf_previews')
    if store:
        with store.lock:keys=[k for k,v in store.items.items() if v[0]==user.id]
        for key in keys:store.expire(key)
    return retry_files()


def purge_due_accounts(now=None):
    """Explicit trusted activation only; protect all unresolved ownership FKs."""
    if current_app.config.get('ACCOUNT_RETENTION_POLICY')!=ACCOUNT_POLICY or current_app.config.get('ACCOUNT_RETENTION_APPROVED') is not True:
        raise ValueError('ACCOUNT_RETENTION_POLICY_UNCONFIRMED')
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError('AWARE_CLEANUP_TIME_REQUIRED')
    result={'removed':0,'anonymized':0,'blocked':0}
    keys=[row.key for row in AppSetting.query.filter(AppSetting.key.like('privacy_account:%')).all()]
    for key in keys:
        try:
            # Serialize against status/ownership writes before rechecking the job.
            db.session.execute(text('UPDATE app_settings SET value=value WHERE key=:key'),{'key':key})
            job=db.session.get(AppSetting,key);value=job.value
            at=datetime.fromisoformat(value['withdrawnAt']);due=account_deadline(at)
            if value.get('policy')!=ACCOUNT_POLICY or datetime.fromisoformat(value['purgeAt'])!=due:raise ValueError('ACCOUNT_RETENTION_MANIFEST_INVALID')
            if now<due:db.session.commit();continue
            identifier=key.split(':',1)[1];user=db.session.get(User,identifier)
            # These are only the known disposable account records. Every other
            # ownership reference must be resolved by its existing lifecycle.
            if user and user.status!='INACTIVE':raise ValueError('WITHDRAWN_ACCOUNT_STATE_CONFLICT')
            public_refs=False
            for model in [Writing,SourceDocument,Work,Rubric]:
                for row in model.query.filter_by(owner_id=identifier).all():
                    if model in [SourceDocument,Work] and row.scope=='PUBLIC':public_refs=True
                    else:raise ValueError('ACCOUNT_OWNERSHIP_REFERENCE_BLOCKED')
            if public_refs and current_app.config.get('ACCOUNT_PUBLIC_OWNER_ERASURE_APPROVED') is not True:raise ValueError('ACCOUNT_OWNERSHIP_REFERENCE_BLOCKED')
            from ..models import AIInteraction, FeedbackReaction
            if AIInteraction.query.filter_by(user_id=identifier).first() or FeedbackReaction.query.filter_by(user_id=identifier).first():raise ValueError('ACCOUNT_OWNERSHIP_REFERENCE_BLOCKED')
            if db.session.execute(text('SELECT 1 FROM quote_card WHERE owner_id=:u'),{'u':identifier}).first():raise ValueError('ACCOUNT_OWNERSHIP_REFERENCE_BLOCKED')
            Consent.query.filter_by(user_id=identifier).delete(synchronize_session=False)
            for workspace in Workspace.query.filter_by(owner_id=identifier).all():
                WorkspaceSetting.query.filter_by(workspace_id=workspace.id).delete(synchronize_session=False)
                if SourceDocument.query.filter_by(workspace_id=workspace.id,scope='PUBLIC').first():
                    workspace.user_name='';workspace.name='공용 자료 저장 공간'
                    workspace.created_at=datetime(1970,1,1,tzinfo=timezone.utc);workspace.updated_at=workspace.created_at
                else:db.session.delete(workspace)
            # Keep 90-day audit events without linking them to the removed user.
            for audit in ActivityRecord.query.filter(db.or_(ActivityRecord.actor_id==identifier,db.and_(ActivityRecord.target_type=='user',ActivityRecord.target_id==identifier))).all():
                if audit.actor_id==identifier:audit.actor_id=None
                if audit.target_type=='user' and audit.target_id==identifier:audit.target_id=None
                audit.details={}
            if user:
                if public_refs:
                    # Approved technical owner reference only; never invent an
                    # owner or break PUBLIC revision links. OIDC cannot match it.
                    user.oidc_issuer='urn:geulbit:erased-owner';user.oidc_subject=str(uuid.uuid4())
                    user.email=None;user.email_verified=False;user.role='USER';user.status='INACTIVE';user.session_version+=1
                    user.created_at=datetime(1970,1,1,tzinfo=timezone.utc);user.updated_at=user.created_at
                else:db.session.delete(user)
            db.session.delete(job)
            enrollment=db.session.get(AppSetting,'beta_enrollment:'+identifier)
            if enrollment:db.session.delete(enrollment)
            revocation=db.session.get(AppSetting,'privacy_revoke:user:'+identifier)
            if revocation:db.session.delete(revocation)
            db.session.commit();result['anonymized' if public_refs else 'removed']+=1
        except Exception as error:
            db.session.rollback()
            job=db.session.get(AppSetting,key)
            if job:
                # No account identifiers or exception strings in public results.
                codes={'ACCOUNT_RETENTION_MANIFEST_INVALID','WITHDRAWN_ACCOUNT_STATE_CONFLICT','ACCOUNT_OWNERSHIP_REFERENCE_BLOCKED'}
                job.value={**job.value,'state':'BLOCKED','errorCode':str(error) if str(error) in codes else 'ACCOUNT_PURGE_RETRY_REQUIRED'}
                db.session.commit()
            result['blocked']+=1
    return result


def prune_audit(now=None):
    now=now or datetime.now(timezone.utc)
    security=['LOGIN_REJECTED','SESSION_REJECTED','CSRF_REJECTED','IDOR_REJECTED']
    admin=['ACCOUNT_STATUS_CHANGED','BOOTSTRAP_ADMIN','RULE_CONFIGURATION_CHANGED','AI_SWITCH_CHANGED','AI_LIMITS_CHANGED','OWNER_ESSAY_REMOVED','CERTIFIED_EXPIRED_ESSAY_GRAPH_REMOVED','RETENTION_CLEANUP_FAILED','ACCOUNT_WITHDRAWAL']
    removed=0
    for actions,days in [(security,30),(admin,90)]:
        removed+=ActivityRecord.query.filter(ActivityRecord.action.in_(actions),ActivityRecord.created_at<now-timedelta(days=days)).delete(synchronize_session=False)
    # Unknown/consent records have no invented retention duration.
    db.session.commit();return removed


DOCUMENT_POLICY='last-document-body-change/7d-v1'

def rubric_expired(item,now=None):
    if current_app.config.get('PRIVATE_DOCUMENT_RETENTION_POLICY')!=DOCUMENT_POLICY:return False
    if not item.file:raise ValueError('RUBRIC_CONTENT_PROVENANCE_REQUIRED')
    at=item.file.updated_at
    if at.tzinfo is None:at=at.replace(tzinfo=timezone.utc)
    return at+timedelta(days=7)<=(now or datetime.now(timezone.utc))

def document_deadline(doc):
    if not doc or doc.scope!='PRIVATE' or current_app.config.get('PRIVATE_DOCUMENT_RETENTION_POLICY')!=DOCUMENT_POLICY:return None
    revisions=DocumentRevision.query.filter_by(document_id=doc.id).order_by(DocumentRevision.revision_number.desc()).all()
    if not revisions:raise ValueError('DOCUMENT_CONTENT_PROVENANCE_REQUIRED')
    ocr=(doc.edition_metadata or {}).get('ocr',{})
    if revisions[0].id==ocr.get('confirmedRevisionId') and ocr.get('retentionDeadline'):
        # Transcribing/reviewing the same uploaded source does not reset its TTL.
        at=datetime.fromisoformat(ocr['retentionDeadline'])
        if at.tzinfo is None:raise ValueError('OCR_RETENTION_PROVENANCE_REQUIRED')
        return at
    latest_hash=revisions[0].content_hash;at=revisions[0].created_at
    for revision in revisions[1:]:
        if revision.content_hash!=latest_hash:break
        at=revision.created_at
    if at.tzinfo is None:at=at.replace(tzinfo=timezone.utc)
    return at+timedelta(days=7)

def document_expired(doc,now=None):
    due=document_deadline(doc)
    return due is not None and due<=(now or datetime.now(timezone.utc))

def purge_due_documents(now=None):
    if current_app.config.get('PRIVATE_DOCUMENT_RETENTION_POLICY')!=DOCUMENT_POLICY:return {'removed':0,'blocked':0}
    if current_app.config.get('RETENTION_APPROVED') is not True or current_app.config.get('RETENTION_BACKUPS_VERIFIED') is not True:raise ValueError('DOCUMENT_RETENTION_SAFETY_REQUIRED')
    result={'removed':0,'blocked':0}
    for doc in SourceDocument.query.filter_by(scope='PRIVATE').all():
        try:
            if not document_expired(doc,now):continue
            # Existing graph deletion refuses unresolved linked/foreign resources.
            # Expired content is already denied independently of physical cleanup.
            revisions=DocumentRevision.query.filter_by(document_id=doc.id).all()
            links=EssayDocument.query.filter(EssayDocument.revision_id.in_([r.id for r in revisions])).all()
            if any(not db.session.get(Writing,l.writing_id) or db.session.get(Writing,l.writing_id).owner_id!=doc.owner_id for l in links):raise ValueError('DOCUMENT_OWNERSHIP_CONFLICT')
            for run in Analysis.query.all():
                if not any(ref.get('documentId')==doc.id for ref in (run.context_snapshot or {}).get('documents',[])):continue
                essay=db.session.get(Writing,run.writing_id)
                if not essay or essay.owner_id!=doc.owner_id:raise ValueError('DOCUMENT_OWNERSHIP_CONFLICT')
                for table in ['ai_interactions','feedback_reactions']:
                    db.session.execute(text(f'DELETE FROM {table} WHERE analysis_id=:id'),{'id':run.id})
                db.session.execute(text('DELETE FROM analysis WHERE id=:id'),{'id':run.id})
            for link in links:db.session.delete(link)
            db.session.flush()
            files=remove_private_document(doc);queue_files(files);db.session.commit();result['removed']+=1
        except Exception:
            db.session.rollback();result['blocked']+=1
    result['filesPending']=retry_files()
    return result

def purge_due_rubrics(now=None):
    if current_app.config.get('PRIVATE_DOCUMENT_RETENTION_POLICY')!=DOCUMENT_POLICY:return {'removed':0,'blocked':0}
    if current_app.config.get('RETENTION_APPROVED') is not True or current_app.config.get('RETENTION_BACKUPS_VERIFIED') is not True:raise ValueError('DOCUMENT_RETENTION_SAFETY_REQUIRED')
    result={'removed':0,'blocked':0}
    from ..models import RubricResult,RubricItem,WritingResource
    for item in Rubric.query.all():
        try:
            if not rubric_expired(item,now):continue
            links=WritingResource.query.filter_by(resource_id=item.id).all()
            if any(not db.session.get(Writing,l.writing_id) or db.session.get(Writing,l.writing_id).owner_id!=item.owner_id for l in links):raise ValueError('RUBRIC_OWNERSHIP_CONFLICT')
            # Legacy assessed rubric results require a separately verified graph;
            # fail closed rather than deleting another user's analysis.
            if RubricResult.query.join(RubricItem,RubricResult.rubric_item_id==RubricItem.id).filter(RubricItem.rubric_id==item.id).first():raise ValueError('RUBRIC_ANALYSIS_GRAPH_REVIEW_REQUIRED')
            filename=item.file.stored_name
            for link in links:db.session.delete(link)
            ledger('rubric',item.id);queue_files([filename]);db.session.delete(item);db.session.commit();result['removed']+=1
        except Exception:
            db.session.rollback();result['blocked']+=1
    result['filesPending']=retry_files()
    return result
