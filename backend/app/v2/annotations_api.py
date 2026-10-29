"""Personal notes never mutate drafts, retention deadlines or analysis snapshots."""
from flask import Blueprint, g, abort
from sqlalchemy import update, delete
from ..extensions import db
from ..models import UserAnnotation, WritingVersion, Analysis, utcnow
from ..utils import success, api_error, json_body
from .common import owned_writing, iso

bp = Blueprint('v2_annotations', __name__, url_prefix='/api')

def data(row):
    return {'id':row.id,'writingId':row.writing_id,'essayVersionId':row.essay_version_id,
            'span':{'start':row.span_start,'end':row.span_end},'quote':row.quote,
            'content':row.content,'revisionNumber':row.revision_number,
            'originalAnchor':row.original_anchor,'createdAt':iso(row.created_at),'updatedAt':iso(row.updated_at)}

def owned(identifier):
    row=db.session.get(UserAnnotation,identifier)
    if not row or row.user_id!=g.principal.id or row.annotation_kind!='NOTE':abort(404)
    owned_writing(row.writing_id)
    return row

def anchor(writing_id, body):
    identifier=body.get('essayVersionId')
    if not isinstance(identifier,str) or not identifier or len(identifier)>36:raise ValueError('INVALID_VERSION')
    version=db.session.get(WritingVersion,identifier)
    span=body.get('span',{})
    start,end=(span.get('start'),span.get('end')) if isinstance(span,dict) else (None,None)
    if (not version or version.writing_id!=writing_id or not version.snapshot_hash
        or type(start) is not int or type(end) is not int or not 0<=start<end<=len(version.content)
        or body.get('quote')!=version.content[start:end]
        or not Analysis.query.filter_by(writing_id=writing_id,essay_version_id=version.id,status='completed').filter(Analysis.result_snapshot.is_not(None)).first()):
        raise ValueError('INVALID_ANCHOR')
    return version,start,end

def content(body):
    value=body.get('content')
    if not isinstance(value,str) or not value.strip() or len(value)>5000:raise ValueError('INVALID_CONTENT')
    return value.strip()

@bp.get('/writings/<identifier>/annotations')
def listing(identifier):
    owned_writing(identifier)
    return success([data(x) for x in UserAnnotation.query.filter_by(writing_id=identifier,user_id=g.principal.id,annotation_kind='NOTE').order_by(UserAnnotation.created_at,UserAnnotation.id)])

@bp.post('/writings/<identifier>/annotations')
def create(identifier):
    owned_writing(identifier);body,error=json_body()
    if error:return error
    try:
        if set(body)-{'essayVersionId','span','quote','content'}:raise ValueError()
        version,start,end=anchor(identifier,body)
        row=UserAnnotation(user_id=g.principal.id,writing_id=identifier,essay_version_id=version.id,
            span_start=start,span_end=end,quote=body['quote'],content=content(body),
            original_anchor={'essayVersionId':version.id,'span':{'start':start,'end':end},'quote':body['quote']})
        db.session.add(row);db.session.commit()
    except (ValueError,TypeError,AttributeError):
        db.session.rollback();return api_error('ANNOTATION_INVALID','분석된 원문 구간과 주석 내용을 확인해 주세요.',400)
    return success(data(row),status=201)

@bp.patch('/annotations/<identifier>')
def edit(identifier):
    row=owned(identifier);body,error=json_body()
    if error:return error
    try:
        if set(body)-{'revisionNumber','content','essayVersionId','span','quote'}:raise ValueError()
        expected=body.get('revisionNumber')
        if type(expected) is not int:raise ValueError()
        values={}
        if 'content' in body:values['content']=content(body)
        if any(k in body for k in ('essayVersionId','span','quote')):
            version,start,end=anchor(row.writing_id,body)
            values.update(essay_version_id=version.id,span_start=start,span_end=end,quote=body['quote'])
        if not values:raise ValueError()
        values.update(revision_number=UserAnnotation.revision_number+1,updated_at=utcnow())
        result=db.session.execute(update(UserAnnotation).where(UserAnnotation.id==identifier,UserAnnotation.user_id==g.principal.id,UserAnnotation.revision_number==expected).values(**values))
        if result.rowcount!=1:
            db.session.rollback();return api_error('ANNOTATION_CONFLICT','주석이 다른 창에서 변경되었습니다. 입력을 보존하고 다시 확인하세요.',409)
        db.session.commit();db.session.refresh(row)
    except (ValueError,TypeError,AttributeError):
        db.session.rollback();return api_error('ANNOTATION_INVALID','원문 구간과 주석 내용을 확인해 주세요.',400)
    return success(data(row))

@bp.get('/annotations/<identifier>')
def get(identifier):
    return success(data(owned(identifier)))

@bp.delete('/annotations/<identifier>')
def remove(identifier):
    owned(identifier);body,error=json_body()
    if error:return error
    if body.get('confirmation')!='삭제' or type(body.get('revisionNumber')) is not int:
        return api_error('CONFIRMATION_REQUIRED','주석 삭제를 확인해 주세요.',400)
    result=db.session.execute(delete(UserAnnotation).where(UserAnnotation.id==identifier,UserAnnotation.user_id==g.principal.id,UserAnnotation.revision_number==body['revisionNumber']))
    if result.rowcount!=1:
        db.session.rollback();return api_error('ANNOTATION_CONFLICT','주석 변경 내용을 다시 확인해 주세요.',409)
    db.session.commit();return success({'deleted':True})
