import math
import time
from datetime import datetime,timezone
from flask import Blueprint,g,current_app,abort
from ..extensions import db
from ..models import Consent,AIInteraction,AppSetting,WritingVersion,User,DocumentRevision
from ..utils import success,api_error,json_body
from components.ai import preview_context,questions
from components.auth import AuthDenied,require_active
from .analysis_api import owned_run
from .common import owned_writing,principal

bp=Blueprint('v2_ai',__name__,url_prefix='/api')


def enabled():
    value=db.session.get(AppSetting,'ai_enabled')
    return bool(value and value.value is True)


@bp.get('/ai/status')
def status():return success({'enabled':enabled(),'externalApproved':current_app.config.get('EXTERNAL_AI_TERMS_APPROVED') is True,'providerConfigured':bool(current_app.config.get('AI_PROVIDER')),'consentPolicyReady':bool(current_app.config.get('AI_POLICY_VERSION')),'policyVersion':current_app.config.get('AI_POLICY_VERSION')})


@bp.post('/ai/consent')
def consent():
    data,error=json_body()
    if error:return error
    policy=current_app.config.get('AI_POLICY_VERSION')
    if not policy:return api_error('POLICY_UNCONFIRMED','AI 동의 정책이 아직 확정되지 않았습니다.',503)
    if data.get('policyVersion')!=policy or type(data.get('granted')) is not bool:return api_error('VALIDATION_ERROR','동의 정책과 명시적 선택을 확인해 주세요.')
    now=datetime.now(timezone.utc)
    for row in Consent.query.filter_by(user_id=g.principal.id,kind='AI').filter(Consent.revoked_at.is_(None)):row.revoked_at=now
    if data['granted']:db.session.add(Consent(user_id=g.principal.id,kind='AI',policy_version=policy,granted_at=now))
    db.session.commit();return success({'granted':data['granted'],'policyVersion':policy})


def context(run,data):
    version=db.session.get(WritingVersion,run.essay_version_id);item=owned_writing(run.writing_id)
    if run.status!='completed':raise ValueError('ANALYSIS_REQUIRED')
    spans=data.get('spans');limit=current_app.config.get('AI_MAX_SELECTED_CODEPOINTS')
    if type(limit) is not int or limit<=0:raise ValueError('CONTEXT_LIMIT_CONFIGURATION_REQUIRED')
    if not isinstance(spans,list) or not 1<=len(spans)<=3:raise ValueError('SELECTION_REQUIRED')
    # Bound selected payload size and reject aggregate coverage of the full essay.
    positions=set()
    for span in spans:
        if not isinstance(span,dict) or type(span.get('start')) is not int or type(span.get('end')) is not int or not 0<=span['start']<span['end']<=len(version.content):raise ValueError('INVALID_SPAN')
        if span['end']-span['start']>limit:raise ValueError('CONTEXT_LIMIT')
        positions.update(range(span['start'],span['end']))
    if len(positions)>limit or len(positions)==len(version.content):raise ValueError('FULL_ESSAY_FORBIDDEN')
    selections=data.get('references',[])
    if not isinstance(selections,list) or len(selections)>1:raise ValueError('REFERENCE_LIMIT')
    references=[]
    linked={d['revisionId']:d for d in (run.context_snapshot or {}).get('documents',[])}
    from .library_api import document
    for selection in selections:
        if not isinstance(selection,dict) or set(selection)!={'revisionId','quote'}:raise ValueError('REFERENCE_SELECTION_REQUIRED')
        rid=selection['revisionId'];quote=selection['quote']
        if not isinstance(rid,str) or rid not in linked:raise ValueError('REFERENCE_NOT_LINKED')
        revision=db.session.get(DocumentRevision,rid)
        if not revision or revision.document_id!=linked[rid]['documentId'] or revision.content_hash!=linked[rid]['sha256']:raise ValueError('REFERENCE_CHANGED')
        source=document(revision.document_id,'VIEW')
        if source.document_type!='TEXT':raise ValueError('WORK_TEXT_REQUIRED')
        if not isinstance(quote,str) or not quote.strip() or len(quote)>500 or len(positions)+len(quote)>limit or len(quote)>=len(revision.content):raise ValueError('REFERENCE_LIMIT')
        start=revision.content.find(quote)
        if start<0 or revision.content.find(quote,start+1)>=0:raise ValueError('REFERENCE_QUOTE_AMBIGUOUS_OR_MISSING')
        references.append({'revisionId':rid,'start':start,'end':start+len(quote),'quote':quote})
    return preview_context(g.principal,owner_id=item.owner_id,version_id=version.id,canonical_text=version.content,spans=spans,question_type=data.get('questionType'),references=references)


@bp.get('/analyses/<identifier>/ai/references')
def reference_options(identifier):
    run=owned_run(identifier)
    from .library_api import allowed_metadata
    from ..models import SourceDocument
    options=[]
    for link in (run.context_snapshot or {}).get('documents',[]):
        source=db.session.get(SourceDocument,link['documentId'])
        if source and allowed_metadata(source) and source.document_type=='TEXT' and source.access_mode in {'VIEW','DOWNLOAD'}:
            options.append({'revisionId':link['revisionId'],'title':source.title})
    return success(options)


@bp.post('/analyses/<identifier>/ai/preview')
def preview(identifier):
    run=owned_run(identifier);data,error=json_body()
    if error:return error
    try:ctx,digest=context(run,data)
    except (ValueError,TypeError,KeyError):return api_error('AI_CONTEXT_INVALID','선택 구간과 운영 문맥 한도 설정을 확인해 주세요.')
    return success({'context':ctx.payload,'previewHash':digest,'externalEnabled':enabled() and current_app.config.get('EXTERNAL_AI_TERMS_APPROVED') is True})


def reserve_budget(uid):
    limits=(db.session.get(AppSetting,'ai_limits').value if db.session.get(AppSetting,'ai_limits') else current_app.config.get('AI_LIMITS'))
    required=['dailyRequests','monthlyBudgetUnits','callCostUnits','cooldownSeconds','concurrency']
    if not isinstance(limits,dict) or any(type(limits.get(k)) is not int or limits[k]<0 for k in required) or any(limits[k]==0 for k in ('dailyRequests','monthlyBudgetUnits','callCostUnits','concurrency')):return False
    # Serialize SQLite writes before reading/reserving budget. No transaction
    # survives the provider call. Accounting uses approved integer cost units.
    db.session.execute(db.update(AppSetting).where(AppSetting.key=='ai_enabled').values(value=AppSetting.value))
    key='ai_usage_'+uid;setting=db.session.get(AppSetting,key);value=dict(setting.value) if setting else {}
    now=datetime.now(timezone.utc);day=now.date().isoformat();month=day[:7];stamp=time.time()
    if value.get('day')!=day:value.update(day=day,daily=0)
    if value.get('month')!=month:value.update(month=month,spent=0)
    global_row=db.session.get(AppSetting,'ai_monthly_usage')
    global_value=dict(global_row.value) if global_row else {}
    if global_value.get('month')!=month:global_value={'month':month,'spent':0}
    if stamp-value.get('lastReservation',0)<limits['cooldownSeconds']:db.session.rollback();return False
    if value.get('daily',0)>=limits['dailyRequests'] or global_value.get('spent',0)+limits['callCostUnits']>limits['monthlyBudgetUnits']:db.session.rollback();return False
    value['daily']=value.get('daily',0)+1;value['spent']=value.get('spent',0)+limits['callCostUnits']
    value['lastReservation']=stamp
    if setting:setting.value=value
    else:db.session.add(AppSetting(key=key,value=value))
    global_value['spent']+=limits['callCostUnits']
    if global_row:global_row.value=global_value
    else:db.session.add(AppSetting(key='ai_monthly_usage',value=global_value))
    db.session.commit();return True


@bp.post('/analyses/<identifier>/ai/questions')
def generate(identifier):
    run=owned_run(identifier);data,error=json_body()
    if error:return error
    policy=current_app.config.get('AI_POLICY_VERSION')
    granted=Consent.query.filter_by(user_id=g.principal.id,kind='AI',policy_version=policy).filter(Consent.granted_at.is_not(None),Consent.revoked_at.is_(None)).first() if policy else None
    if not granted:return api_error('AI_CONSENT_REQUIRED','별도 AI 동의가 필요합니다.',403)
    try:ctx,digest=context(run,data)
    except (ValueError,TypeError,KeyError):return api_error('AI_CONTEXT_INVALID','선택 문맥을 확인해 주세요.')
    if data.get('previewHash')!=digest:return api_error('PREVIEW_MISMATCH','전송 미리보기를 다시 확인해 주세요.',409)
    run_id,writing_id,consent_id=run.id,run.writing_id,granted.id
    external=enabled() and current_app.config.get('EXTERNAL_AI_TERMS_APPROVED') is True
    provider=current_app.config.get('AI_PROVIDER')
    # A test provider cannot accidentally become a production external gateway.
    if current_app.config.get('AI_PROVIDER_TEST_ONLY') and not current_app.testing:provider=None
    profile=(getattr(provider,'cache_tag','configured-provider/v1') if external and provider else 'local-question-options/v1')
    cached=AIInteraction.query.filter_by(user_id=g.principal.id,analysis_id=run.id,preview_digest=digest).order_by(AIInteraction.created_at.desc()).first()
    if cached and cached.context.get('consentPolicy')==policy and cached.context.get('generationProfile')==profile and (not external or cached.status in ('PROVIDER_VALIDATED','INSUFFICIENT_CONTEXT')):return success({'id':cached.id,'status':cached.status,'questions':cached.questions,'cached':True})
    semaphore=None;acquired=False
    limits=(db.session.get(AppSetting,'ai_limits').value if db.session.get(AppSetting,'ai_limits') else current_app.config.get('AI_LIMITS'))
    if external and provider and isinstance(limits,dict) and type(limits.get('concurrency')) is int and limits['concurrency']>0:
        import threading
        semaphore=current_app.extensions.setdefault('v2_ai_semaphore',threading.BoundedSemaphore(limits['concurrency']))
        acquired=semaphore.acquire(blocking=False)
    try:
        db.session.rollback()  # no read/write transaction during slow network I/O
        result=questions(g.principal,context=ctx,preview_hash=digest,consent=True,enabled=external and acquired,external_terms_approved=external,reserve_budget=reserve_budget,provider=provider)
    finally:
        if acquired:semaphore.release()
    # Recheck expiry/account revocation after slow external work before storing.
    db.session.remove();fresh=db.session.get(User,g.principal.id);require_active(principal(fresh))
    if external and (not enabled() or current_app.config.get('EXTERNAL_AI_TERMS_APPROVED') is not True):return api_error('AI_DISABLED','AI 기능이 중지되어 결과를 저장하지 않았습니다.',409)
    if fresh.session_version!=g.principal.session_version:raise AuthDenied('ACCESS_DENIED')
    owned_writing(writing_id)
    fresh_consent=Consent.query.filter_by(user_id=g.principal.id,kind='AI',policy_version=policy).filter(Consent.granted_at.is_not(None),Consent.revoked_at.is_(None)).first()
    if not fresh_consent or fresh_consent.id!=consent_id:return api_error('AI_CONSENT_REQUIRED','동의가 철회되어 결과를 저장하지 않았습니다.',403)
    if ctx.payload.get('references'):
        # Recheck linked edition access/expiry after a slow provider call.
        context(owned_run(run_id),data)
    stored_payload=dict(ctx.payload)
    if 'references' in stored_payload:
        # A separate copy of a work excerpt must not outlive its source.
        stored_payload['references']=[{k:v for k,v in r.items() if k!='quote'} for r in stored_payload['references']]
    record=AIInteraction(user_id=g.principal.id,analysis_id=run_id,preview_digest=digest,context={'payload':stored_payload,'consentPolicy':policy,'consentId':consent_id,'generationProfile':profile},questions=result['questions'],status=result['status']);db.session.add(record);db.session.commit()
    return success({'id':record.id,**result})


@bp.patch('/ai/interactions/<identifier>/note')
def note(identifier):
    record=db.session.get(AIInteraction,identifier)
    if not record or record.user_id!=g.principal.id:abort(404,description='API resource unavailable')
    owned_run(record.analysis_id);data,error=json_body()
    if error:return error
    if set(data)!={'note'} or not isinstance(data['note'],str):return api_error('VALIDATION_ERROR','생각 메모 문자열이 필요합니다.')
    record.note=data['note'];db.session.commit();return success({'id':record.id,'note':record.note})

@bp.get('/analyses/<identifier>/ai/interactions')
def list_interactions(identifier):
    owned_run(identifier)
    return success([{'id':a.id,'questions':a.questions,'status':a.status,'note':a.note or ''} for a in AIInteraction.query.filter_by(user_id=g.principal.id,analysis_id=identifier).all()])
