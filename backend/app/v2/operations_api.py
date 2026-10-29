"""Authenticated operations. No retention basis or external provider is inferred."""
import io
import re
import time
import uuid
import threading
from datetime import datetime, timezone
from pathlib import Path
import pymupdf as fitz
from flask import Blueprint, current_app, g, request, send_file, abort
from sqlalchemy import text
from ..extensions import db
from ..models import Writing, WritingVersion, Analysis, AnalysisJob, FeedbackReaction, AIInteraction, EssayDocument, User, AppSetting, ActivityRecord
from ..utils import success, api_error, json_body, iso
from ..analysis.snapshot import normalize_text
from components.pdf import create_report, extract_preview, PdfRejected
from .analysis_api import owned_run
from .common import owned_writing,iso

bp=Blueprint('v2_operations',__name__,url_prefix='/api')



def presentable_snapshot(run):
    value=dict(run.result_snapshot)
    value['limitations']=[*value.get('limitations',[]), f"실행 시각: {iso(run.completed_at)} · 엔진: {run.engine_version}", f"구조 후보: {len(value.get('roleCandidates',[]))}개 문장 · 관계 단서: {len(value.get('relations',[]))}개. 확정 점수가 아닙니다."]
    groups={}
    for f in value.get('findings',[]):
        key=(f.get('ruleId'),f.get('tier'),f.get('reason'))
        row=groups.setdefault(key,{'tier':f.get('tier'),'reason':f.get('reason',''),'source':f.get('source',{}).get('url') or f.get('source',{}).get('legacyCaption',''),'locations':[]})
        row['locations'].append(f"[{f['start']},{f['end']})")
    value['limitations'].extend(f"인용 대조: {q['status']} · 선택한 revision: {q['revisionId']} · 원문 위치: {q['essaySpan']} · {q['limitation']}" for q in value.get('quoteChecks',[]))
    value['findings']=[{**f,'reason':f['reason']+' · '+str(len(f['locations']))+'곳 · 원문 코드포인트 위치: '+', '.join(f['locations'])} for f in groups.values()]
    return value

def live_account():
    from .auth_api import boundary,COOKIE
    from .common import principal
    db.session.remove()
    fresh=boundary().verify(request.cookies.get(COOKIE,''),load_user=lambda uid:principal(db.session.get(User,uid)),csrf=request.headers.get('X-CSRF-Token'),mutating=request.method not in {'GET','HEAD','OPTIONS'})
    if fresh.id!=g.principal.id:abort(403)


def live_owner(wid):
    live_account()
    return owned_writing(wid)


@bp.get('/analyses/<identifier>/pdf')
def report(identifier):
    run=owned_run(identifier);item=owned_writing(run.writing_id)
    if run.status!='completed' or not run.result_snapshot:return api_error('ANALYSIS_NOT_COMPLETE','완료된 분석을 선택해 주세요.',409)
    if set(request.args)-{'includeAi'} or request.args.get('includeAi','false') not in {'true','false'}:return api_error('INVALID_OPTIONS','PDF 옵션을 확인해 주세요.')
    wid=item.id;version=db.session.get(WritingVersion,run.essay_version_id)
    include=request.args.get('includeAi')=='true'
    interactions=AIInteraction.query.filter_by(user_id=g.principal.id,analysis_id=run.id).all() if include else []
    questions=[q['question'] for a in interactions for q in (a.questions or []) if isinstance(q,dict) and isinstance(q.get('question'),str)]
    notes=[a.note for a in interactions if a.note] if include else []
    args=dict(owner_id=item.owner_id,title=item.title or '제목 없는 글',text=version.content,version_id=version.id,run_id=run.id,analysis=presentable_snapshot(run),font_path=current_app.config.get('PDF_FONT_PATH',Path(__file__).resolve().parents[3]/'public/fonts/noto-sans-kr-regular.ttf'),max_pages=current_app.config.get('PDF_MAX_PAGES',100),max_bytes=current_app.config.get('PDF_MAX_BYTES',50*1024*1024),expires_at=item.expires_at.replace(tzinfo=timezone.utc).timestamp() if item.expires_at else None,now=time.time,include_ai=include,ai_questions=questions,thought_notes=notes)
    db.session.remove() # no database transaction during PDF layout
    try:data=create_report(g.principal,**args)
    except PdfRejected as e:return api_error(str(e),'PDF를 만들 수 없습니다.',422)
    live_owner(wid)
    owned_run(identifier)  # document expiry can occur during PDF generation
    return send_file(io.BytesIO(data),mimetype='application/pdf',as_attachment=True,download_name='geulbit-report.pdf',max_age=0)


class PreviewStore:
    """Bounded, owner-bound processing cache. Restart requires a fresh preview."""
    def __init__(self,ttl=600):self.lock=threading.Lock();self.items={};self.timers={};self.ttl=ttl
    def expire(self,key):
        with self.lock:
            self.items.pop(key,None);self.timers.pop(key,None)
    def save(self,owner,preview):
        with self.lock:
            now=time.monotonic()
            for k,v in list(self.items.items()):
                if v[2]<=now or v[0]==owner:
                    self.items.pop(k);timer=self.timers.pop(k,None)
                    if timer:timer.cancel()
            if len(self.items)>=16:raise PdfRejected('PREVIEW_CAPACITY')
            key=str(uuid.uuid4());self.items[key]=(owner,preview,now+self.ttl)
            timer=threading.Timer(self.ttl,self.expire,args=(key,));timer.daemon=True;self.timers[key]=timer;timer.start();return key
    def take(self,key,owner):
        with self.lock:
            value=self.items.get(key)
            if not value or value[0]!=owner:return None
            self.items.pop(key);timer=self.timers.pop(key,None)
            if timer:timer.cancel()
            return value[1] if value[2]>time.monotonic() else None


@bp.post('/pdf-import/preview')
def import_preview():
    file=request.files.get('file')
    if not file:return api_error('FILE_REQUIRED','PDF를 선택해 주세요.')
    limit=current_app.config.get('PDF_MAX_BYTES',50*1024*1024);data=file.read(limit+1)
    db.session.remove()
    try:
        # A Geulbit report may contain its specific untrusted source manifest;
        # executable actions and arbitrary attachment exposure remain forbidden.
        with fitz.open(stream=data,filetype='pdf') as doc:
            if doc.xref_length()>100000:raise PdfRejected('PDF_OBJECT_LIMIT')
            for i in range(1,doc.xref_length()):
                if re.search(r'/(JavaScript|JS|Launch|OpenAction|AA)\b',doc.xref_object(i)):raise PdfRejected('PDF_ACTIVE_CONTENT')
        preview=extract_preview(g.principal,data,max_bytes=limit,max_pages=current_app.config.get('PDF_MAX_PAGES',100))
        if len(preview['text'].encode())>limit:raise PdfRejected('PDF_EXTRACTED_SIZE_LIMIT')
        live_account()
        store=current_app.extensions.setdefault('v2_pdf_previews',PreviewStore())
        identifier=store.save(g.principal.id,preview)
    except Exception as e:
        from components.auth import AuthDenied
        if isinstance(e,AuthDenied):raise
        code=str(e) if isinstance(e,PdfRejected) else 'PDF_INVALID'
        return api_error(code,'PDF를 읽을 수 없습니다. 스캔 PDF의 OCR은 지원하지 않습니다.',422)
    return success({**preview,'previewId':identifier})


@bp.post('/pdf-import/confirm')
def import_confirm():
    data,error=json_body()
    if error:return error
    if data.get('confirmed') is not True:return api_error('CONFIRMATION_REQUIRED','추출한 본문을 확인해 주세요.')
    store=current_app.extensions.get('v2_pdf_previews')
    preview=store.take(data.get('previewId'),g.principal.id) if store else None
    if not preview:return api_error('PREVIEW_UNAVAILABLE','PDF를 다시 확인해 주세요.',409)
    body=data.get('content',preview['text']);title=data.get('title',preview['title']) or 'PDF에서 가져온 새 글'
    if not isinstance(body,str) or not isinstance(title,str) or len(title)>240 or len(body.encode())>current_app.config.get('PDF_MAX_BYTES',50*1024*1024):return api_error('VALIDATION_ERROR','제목과 본문을 확인해 주세요.')
    item=Writing(workspace_id='local-workspace',owner_id=g.principal.id,title=title,content=normalize_text(body))
    from .privacy_lifecycle import enabled, deadline
    if enabled():item.expires_at=deadline()
    db.session.add(item);db.session.commit()
    from .essays import writing_data
    return success(writing_data(item),status=201)


@bp.get('/admin/operations')
def operations():
    from .common import admin_required
    admin_required()
    revision=db.session.execute(text('SELECT version_num FROM alembic_version')).scalar()
    from ..storage import SCHEMA_HEAD
    return success({'database':'READY' if revision==SCHEMA_HEAD else 'MIGRATION_REQUIRED','revision':revision,'retention':'BLOCKED_POLICY_UNCONFIRMED','externalAi':'DISABLED_UNLESS_APPROVED','backup':'LOCAL_OPERATOR_CLI_ONLY','independentReview':'DEFERRED_FINAL_REVIEW'})


@bp.get('/admin/audit')
def audit():
    from .common import admin_required
    admin_required()
    return success([{'id':a.id,'action':a.action,'targetType':a.target_type,'targetId':a.target_id,'actorId':a.actor_id,'createdAt':iso(a.created_at)} for a in ActivityRecord.query.filter(ActivityRecord.action.in_(['ACCOUNT_STATUS_CHANGED','BOOTSTRAP_ADMIN','RULE_CONFIGURATION_CHANGED','AI_SWITCH_CHANGED','AI_LIMITS_CHANGED','OWNER_ESSAY_REMOVED','CERTIFIED_EXPIRED_ESSAY_GRAPH_REMOVED','RETENTION_CLEANUP_FAILED'])).order_by(ActivityRecord.created_at.desc()).limit(100)])


@bp.patch('/admin/rules')
def rules():
    from .common import admin_required
    from ..analysis.ruleset import catalogue
    admin_required();data,error=json_body()
    if error:return error
    disabled=data.get('disabledRules');known={r['rule_id'] for r in catalogue()}
    if not isinstance(disabled,list) or any(x not in known for x in disabled):return api_error('VALIDATION_ERROR','검증된 규칙 ID를 지정해 주세요.')
    setting=db.session.get(AppSetting,'disabled_rules') or AppSetting(key='disabled_rules')
    setting.value=sorted(set(disabled));db.session.add(setting)
    db.session.add(ActivityRecord(actor_id=g.principal.id,action='RULE_CONFIGURATION_CHANGED',target_type='setting',target_id=setting.key,details={}));db.session.commit()
    return success({'disabledRules':setting.value})


@bp.patch('/admin/ai')
def ai_switch():
    from .common import admin_required
    admin_required();data,error=json_body()
    if error:return error
    if type(data.get('enabled')) is not bool:return api_error('VALIDATION_ERROR','활성 여부를 확인해 주세요.')
    value=db.session.get(AppSetting,'ai_enabled') or AppSetting(key='ai_enabled');value.value=data['enabled'];db.session.add(value)
    db.session.add(ActivityRecord(actor_id=g.principal.id,action='AI_SWITCH_CHANGED',target_type='setting',target_id=value.key,details={'enabled':value.value}));db.session.commit();return success({'enabled':value.value,'externalApproved':current_app.config.get('EXTERNAL_AI_TERMS_APPROVED') is True})


@bp.post('/admin/retention/cleanup')
def blocked_retention():
    from .common import admin_required
    admin_required()
    try:count=purge_due_essays(current_app)
    except ValueError:return api_error('RETENTION_POLICY_UNCONFIRMED','기산점·적용 대상·백업 보존 정책 승인 전에는 삭제를 실행하지 않습니다.',409)
    from .privacy_lifecycle import retry_files
    pending=retry_files()
    accounts=current_app.extensions.get('account_retention_result',{'removed':0,'blocked':0})
    return success({'removed':count,'accounts':accounts,'filesPending':pending,'complete':pending==0 and accounts['blocked']==0},status=202 if pending or accounts['blocked'] else 200)


@bp.post('/backups')
def blocked_backup():return api_error('LOCAL_OPERATOR_REQUIRED','전체 DB 백업은 로컬 운영자 CLI에서만 수행할 수 있습니다.',403)


def remove_essay_graph(identifier, executor=None):
    execute=executor or db.session.execute
    for table in ['ai_interactions','feedback_reactions']:
        execute(text(f'DELETE FROM {table} WHERE analysis_id IN (SELECT id FROM analysis WHERE writing_id=:id)'),{'id':identifier})
    execute(text('DELETE FROM revision WHERE writing_id=:id'),{'id':identifier})
    execute(text('DELETE FROM analysis WHERE writing_id=:id'),{'id':identifier})
    execute(text('DELETE FROM essay_documents WHERE writing_id=:id'),{'id':identifier})
    execute(text('UPDATE writing SET current_version_id=NULL WHERE id=:id'),{'id':identifier})
    execute(text('DELETE FROM writing_version WHERE writing_id=:id'),{'id':identifier})
    execute(text('DELETE FROM writing WHERE id=:id'),{'id':identifier})

@bp.delete('/records/<identifier>')
@bp.delete('/writings/<identifier>')
def delete_essay(identifier):
    item=owned_writing(identifier);data,error=json_body()
    if error:return error
    if data.get('confirmation')!=(item.title or '삭제'):return api_error('CONFIRMATION_REQUIRED','글 제목을 확인해 주세요.')
    from .privacy_lifecycle import queue_essay, retry_files
    queue_essay(identifier)
    db.session.add(ActivityRecord(actor_id=g.principal.id,action='OWNER_ESSAY_REMOVED',target_type='essay',target_id=identifier,details={}))
    db.session.commit();pending=retry_files()
    return success({'deleted':pending==0,'databaseDeleted':True,'filesPending':pending},status=202 if pending else 200)

@bp.post('/account/withdraw')
def account_withdraw():
    data,error=json_body()
    if error:return error
    if data.get('confirmation')!='WITHDRAW':return api_error('CONFIRMATION_REQUIRED','탈퇴 의사를 확인해 주세요.')
    from .privacy_lifecycle import withdraw
    pending=withdraw(db.session.get(User,g.principal.id))
    from .privacy_lifecycle import ACCOUNT_POLICY
    response,status=success({'accountDisabled':True,'filesPending':pending,'accountRetention':ACCOUNT_POLICY},status=202 if pending else 200)
    from .auth_api import COOKIE,SessionBoundary
    response.delete_cookie(COOKIE,**SessionBoundary.cookie_attributes)
    return response,status

@bp.patch('/admin/ai/limits')
def ai_limits():
    from .common import admin_required
    admin_required();data,error=json_body()
    if error:return error
    keys={'dailyRequests','monthlyBudgetUnits','callCostUnits','cooldownSeconds','concurrency'}
    if set(data)!=keys or any(type(data[k]) is not int or data[k]<0 for k in keys) or any(data[k]==0 for k in ['dailyRequests','monthlyBudgetUnits','concurrency']):return api_error('VALIDATION_ERROR','승인된 정수 한도와 비용 단위를 입력해 주세요.')
    enabled=db.session.get(AppSetting,'ai_enabled')
    if enabled and enabled.value:return api_error('AI_CONFIGURATION_ACTIVE','AI를 끈 뒤 한도를 변경해 주세요.',409)
    value=db.session.get(AppSetting,'ai_limits') or AppSetting(key='ai_limits');value.value=data;db.session.add(value)
    db.session.add(ActivityRecord(actor_id=g.principal.id,action='AI_LIMITS_CHANGED',target_type='setting',target_id=value.key,details={}));db.session.commit()
    current_app.extensions.pop('v2_ai_semaphore',None)
    return success({'limits':data})


def purge_due_essays(app):
    """Use already certified expiry dates only. Never infer a seven-day basis.

    The trusted operator must separately approve scope, private-document lifecycle,
    backup handling and the process which assigns expiry dates. HTTP clients cannot
    supply these approvals. Production has no such configuration by default.
    """
    from components.lifecycle import require_retention_policy
    policy=app.config.get('RETENTION_POLICY')
    from .privacy_lifecycle import POLICY, NO_BACKUP_POLICY, enabled, queue_essay, retry_files, purge_due_accounts
    local_backup=isinstance(policy,dict) and policy.get('backupRetention')=='7d-encrypted-local-c-v1' and app.config.get('RETENTION_LOCAL_BACKUP_APPROVED') is True
    no_backup=isinstance(policy,dict) and policy.get('backupRetention')==NO_BACKUP_POLICY and app.config.get('RETENTION_NO_BACKUP_APPROVED') is True
    from .privacy_lifecycle import ACCOUNT_POLICY
    if app.config.get('ACCOUNT_RETENTION_APPROVED') is True and app.config.get('ACCOUNT_RETENTION_POLICY')!=ACCOUNT_POLICY:
        raise ValueError('ACCOUNT_RETENTION_POLICY_UNCONFIRMED')
    if enabled():
        if not isinstance(policy,dict) or policy.get('basis')!=POLICY or (policy.get('backupRetention')!='7d-encrypted-separate-device' and not no_backup and not local_backup):raise ValueError('RETENTION_POLICY_UNCONFIRMED')
    else:require_retention_policy(policy)
    if (app.config.get('RETENTION_APPROVED') is not True or app.config.get('RETENTION_DATES_VERIFIED') is not True
            or (not no_backup and app.config.get('RETENTION_BACKUPS_VERIFIED') is not True) or policy['targetScope']!='PRIVATE_ESSAY_GRAPH'
            or policy.get('privateDocuments')!='SEPARATE_APPROVED_LIFECYCLE'):
        raise ValueError('RETENTION_POLICY_UNCONFIRMED')
    now=datetime.now(timezone.utc)
    try:
        # Serialize the short cleanup transaction; ongoing producers recheck live rows.
        db.session.execute(text('UPDATE writing SET revision_number=revision_number WHERE expires_at<=:now'),{'now':now})
        ids=[w.id for w in Writing.query.filter(Writing.owner_id.is_not(None),Writing.expires_at<=now)]
        for identifier in ids:queue_essay(identifier)
        if ids:db.session.add(ActivityRecord(action='CERTIFIED_EXPIRED_ESSAY_GRAPH_REMOVED',target_type='retention',target_id=str(uuid.uuid4()),details={'count':len(ids)}))
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        db.session.add(ActivityRecord(action='RETENTION_CLEANUP_FAILED',target_type='retention',target_id=str(uuid.uuid4()),details={'errorType':type(error).__name__}))
        db.session.commit();raise
    retry_files()
    if app.config.get('ACCOUNT_RETENTION_APPROVED') is True:
        app.extensions['account_retention_result']=purge_due_accounts()
    else:app.extensions['account_retention_result']={'removed':0,'blocked':0}
    return len(ids)
