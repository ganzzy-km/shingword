import hashlib
from datetime import datetime,timezone
from flask import Blueprint,g,request,abort
from sqlalchemy import update,func,or_
from sqlalchemy.orm import load_only
from ..extensions import db
from ..models import Writing,WritingVersion,Analysis
from ..utils import success,api_error,json_body,validate_length
from ..analysis.snapshot import normalize_text as normalize_input
from .common import owned_writing,iso

bp=Blueprint('v2_essays',__name__,url_prefix='/api')
FIELDS={'title':'title','work':'work','author':'author','inquiryQuestion':'inquiry_question','subject':'subject','conditions':'conditions'}


class SaveConflict(ValueError):pass


def analysis_summaries(identifiers):
    grouped={identifier:[] for identifier in identifiers}
    if not grouped:return grouped
    runs=Analysis.query.options(load_only(Analysis.id,Analysis.writing_id,Analysis.status,Analysis.metrics,Analysis.created_at,Analysis.essay_version_id)).filter(Analysis.writing_id.in_(grouped)).order_by(Analysis.created_at.desc(),Analysis.id)
    for run in runs:grouped[run.writing_id].append(run)
    return grouped


def writing_data(item,content=True,runs=None):
    if runs is None:runs=analysis_summaries([item.id])[item.id]
    successful=next((r for r in runs if r.status=='completed'),None)
    result={'id':item.id,'title':item.title or '', 'work':item.work or '', 'author':item.author or '', 'inquiryQuestion':item.inquiry_question or '', 'subject':item.subject or '', 'conditions':item.conditions or '', 'status':item.status,'revisionNumber':item.revision_number,'currentVersionId':item.current_version_id,'createdAt':iso(item.created_at),'updatedAt':iso(item.updated_at),'expiresAt':iso(item.expires_at),'characterCount':len(item.content or ''),'latestAnalysisId':successful.id if successful else None,'analysisRuns':[{'id':r.id,'status':r.status,'metrics':r.metrics or {},'createdAt':iso(r.created_at),'essayVersionId':r.essay_version_id} for r in runs]}
    if content:result.update(content=item.content or '',resources=[])
    return result


def validate(data):
    if not isinstance(data,dict) or set(data)&{'ownerId','owner_id','workspaceId','expiresAt','currentVersionId'}:raise ValueError('INVALID_FIELDS')
    if any(k in data and not isinstance(data[k],str) for k in [*FIELDS,'content']):raise ValueError('STRING_REQUIRED')
    if validate_length(data,{'title':240,'work':240,'author':160,'inquiryQuestion':5000,'subject':120,'conditions':10000}):raise ValueError('FIELD_TOO_LONG')


def save_draft(item,data):
    validate(data);expected=data.get('revisionNumber')
    if type(expected) is not int or expected!=item.revision_number:raise SaveConflict()
    values={attr:data[key] for key,attr in FIELDS.items() if key in data}
    if 'content' in data:values['content']=normalize_input(data['content'])
    from .privacy_lifecycle import enabled, deadline
    if 'content' in values and values['content']!=(item.content or '') and enabled():values['expires_at']=deadline()
    changed=any(getattr(item,k)!=v for k,v in values.items())
    if changed:values.update(revision_number=Writing.revision_number+1,updated_at=datetime.now(timezone.utc))
    else:values={'revision_number':Writing.revision_number} # write lock for atomic version capture too
    result=db.session.execute(update(Writing).where(Writing.id==item.id,Writing.owner_id==g.principal.id,Writing.revision_number==expected,or_(Writing.expires_at.is_(None),Writing.expires_at>datetime.now(timezone.utc))).values(**values).execution_options(synchronize_session=False))
    if result.rowcount!=1:raise SaveConflict()
    db.session.refresh(item)
    return changed


def freeze_version(item,data):
    save_draft(item,data)
    latest=WritingVersion.query.filter_by(writing_id=item.id).filter(WritingVersion.snapshot_hash.is_not(None)).order_by(WritingVersion.version_number.desc()).first()
    body=normalize_input(item.content or '')
    digest=hashlib.sha256(body.encode()).hexdigest()
    if latest and latest.snapshot_hash==digest and latest.content==body:
        version=latest
    else:
        number=(db.session.query(func.max(WritingVersion.version_number)).filter_by(writing_id=item.id).scalar() or 0)+1
        version=WritingVersion(writing_id=item.id,parent_id=latest.id if latest else None,name='분석 원문',content=body,version_number=number,snapshot_hash=digest,normalization_version='nfc-lf/1')
        db.session.add(version);db.session.flush()
    item.current_version_id=version.id
    if not item.original_version_id:item.original_version_id=version.id
    db.session.flush();return version


@bp.get('/writings')
@bp.get('/records')
def list_writings():
    q=Writing.query.filter_by(owner_id=g.principal.id).filter(or_(Writing.expires_at.is_(None),Writing.expires_at>datetime.now(timezone.utc)))
    if request.args.get('search'):q=q.filter(Writing.title.contains(request.args['search']))
    try:
        page=int(request.args.get('page','1'));size=int(request.args.get('pageSize','12'))
        if page<1 or not 1<=size<=100:raise ValueError()
    except ValueError:return api_error('VALIDATION_ERROR','목록 페이지와 크기를 확인해 주세요.')
    ascending=request.args.get('sort')=='updated-asc'
    order=Writing.updated_at.asc() if ascending else Writing.updated_at.desc()
    items=q.order_by(order,Writing.id).offset((page-1)*size).limit(size).all()
    runs=analysis_summaries([item.id for item in items])
    return success([writing_data(x,False,runs[x.id]) for x in items])


@bp.post('/writings')
def create():
    data,error=json_body()
    if error:return error
    try:validate(data);body=normalize_input(data.get('content',''))
    except (ValueError,TypeError):return api_error('VALIDATION_ERROR','입력값을 확인해 주세요.')
    item=Writing(workspace_id='local-workspace',owner_id=g.principal.id,content=body,**{attr:data[key] for key,attr in FIELDS.items() if key in data})
    from .privacy_lifecycle import enabled, deadline
    if enabled():item.expires_at=deadline()
    db.session.add(item);db.session.commit();return success(writing_data(item),status=201)


@bp.get('/writings/<identifier>')
def get(identifier):return success(writing_data(owned_writing(identifier)))


@bp.patch('/writings/<identifier>')
@bp.post('/writings/<identifier>/autosave')
def save(identifier):
    item=owned_writing(identifier);data,error=json_body()
    if error:return error
    try:save_draft(item,data);db.session.commit()
    except SaveConflict:
        db.session.rollback();return api_error('SAVE_CONFLICT','최신 저장 내용과 충돌했습니다. 편집 중인 초안을 보존하세요.',409,{'revisionNumber':item.revision_number})
    except (ValueError,TypeError):
        db.session.rollback();return api_error('VALIDATION_ERROR','입력값을 확인해 주세요.')
    return success(writing_data(item))


@bp.post('/writings/<identifier>/versions')
def snapshot(identifier):
    item=owned_writing(identifier);data,error=json_body()
    if error:return error
    try:version=freeze_version(item,data);db.session.commit()
    except SaveConflict:
        db.session.rollback();return api_error('SAVE_CONFLICT','현재 초안 revision을 확인해 주세요.',409)
    except (ValueError,TypeError):
        db.session.rollback();return api_error('VALIDATION_ERROR','입력값을 확인해 주세요.')
    return success(version_data(version),status=201)


def version_data(v):return {'id':v.id,'writingId':v.writing_id,'content':v.content,'name':v.name,'versionNumber':v.version_number,'parentId':v.parent_id,'hash':v.snapshot_hash,'normalizationVersion':v.normalization_version,'createdAt':iso(v.created_at)}


@bp.get('/writings/<identifier>/versions')
def versions(identifier):
    owned_writing(identifier)
    return success([version_data(v) for v in WritingVersion.query.filter_by(writing_id=identifier).filter(WritingVersion.snapshot_hash.is_not(None)).order_by(WritingVersion.version_number).all()])


@bp.get('/writing-versions/<left>/compare/<right>')
def compare(left,right):
    import difflib
    a=db.session.get(WritingVersion,left);b=db.session.get(WritingVersion,right)
    if not a or not b or a.writing_id!=b.writing_id or not a.snapshot_hash or not b.snapshot_hash:abort(404,description='API resource unavailable')
    owned_writing(a.writing_id)
    return success({'leftVersionId':left,'rightVersionId':right,'changes':[{'tag':tag,'before':a.content[i:j],'after':b.content[k:l],'startOffset':i,'endOffset':j} for tag,i,j,k,l in difflib.SequenceMatcher(None,a.content,b.content,autojunk=False).get_opcodes() if tag!='equal']})
