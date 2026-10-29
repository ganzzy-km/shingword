"""Private, revision-bound writing tools. S4/OCR snapshots remain read-only."""
from functools import wraps
from difflib import SequenceMatcher
from datetime import datetime, timezone
import hashlib
from werkzeug.exceptions import NotFound
from flask import Blueprint, g, request, abort
from sqlalchemy import update, func
from sqlalchemy.exc import IntegrityError
from ..extensions import db
from ..models import (UserAnnotation, WritingVersion, Writing, QuoteCard, WorkspaceSetting,
    SourceDocument, DocumentRevision, EssayDocument, Work, WorkDocument, PublicationRequest, ActivityRecord, User, utcnow)
from ..utils import success, api_error, json_body
from ..analysis.snapshot import normalize_text
from .common import owned_writing, admin_required, iso
from .library_api import workspace, document, revision_for, allowed_metadata, document_data, ocr_pending
from .annotations_api import data as annotation_data

bp=Blueprint('v2_writing_tools',__name__,url_prefix='/api/writing-tools')
KINDS={'USER_CLAIM','USER_EVIDENCE','USER_LINK'}
GROUPS={'SUPPORT','ALTERNATIVE','COUNTER','UNSORTED'}
CARD_KINDS={'DIRECT_QUOTE','SCENE','NOTE','CHARACTER','IMAGE','CONFLICT','QUESTION'}
SOURCE_TYPES={'ORIGINAL','REFERENCE','MY_INTERPRETATION'}
DEFAULTS={'fontSize':18,'lineHeight':1.9,'bodyWidth':820,'focus':False,'tutorial':'UNSEEN','tutorialStep':0,'mobileTab':'body'}


def guarded(fn):
    @wraps(fn)
    def call(*args,**kwargs):
        try:return fn(*args,**kwargs)
        except IntegrityError:
            db.session.rollback();return api_error('WRITING_TOOLS_CONFLICT','다른 창의 저장 결과를 다시 확인해 주세요.',409)
        except (ValueError,TypeError,KeyError,AttributeError):
            db.session.rollback();return api_error('WRITING_TOOLS_INVALID','선택한 판본·구간·입력 항목을 확인해 주세요.',400)
    return call


def body():
    value,error=json_body()
    if error or not isinstance(value,dict):raise ValueError()
    return value


def text(value,limit=5000):
    if not isinstance(value,str) or len(value)>limit:raise ValueError()
    return normalize_text(value)


def only(value,keys):
    if set(value)-set(keys):raise ValueError()


def version_anchor(writing_id,value):
    if not isinstance(value,dict):raise ValueError()
    only(value,{'essayVersionId','span','quote'})
    v=db.session.get(WritingVersion,value.get('essayVersionId'))
    if not v or v.writing_id!=writing_id or not v.snapshot_hash:raise ValueError()
    start,end=span(value.get('span'),v.content)
    if value.get('quote')!=v.content[start:end]:raise ValueError()
    return v,start,end


def span(value,content,empty=False):
    if not isinstance(value,dict):raise ValueError()
    a,b=value.get('start'),value.get('end')
    if type(a) is not int or type(b) is not int or not 0<=a<=b<=len(content) or (not empty and a==b):raise ValueError()
    return a,b


def setting(key):return WorkspaceSetting.query.filter_by(workspace_id=workspace().id,key=key).first()


def read_setting(key):
    row=setting(key);v=row.value if row and isinstance(row.value,dict) else {}
    return {'revisionNumber':v.get('revisionNumber',0),'data':v.get('data',{})}


def store_setting(key,value,expected):
    w=workspace()
    db.session.execute(update(type(w)).where(type(w).id==w.id).values(updated_at=type(w).updated_at))
    row=setting(key)
    if row:db.session.refresh(row)
    old=row.value if row and isinstance(row.value,dict) else {}
    if type(expected) is not int or expected!=old.get('revisionNumber',0):abort(409,description='SETTING_CONFLICT')
    result={'revisionNumber':expected+1,'data':value}
    if row:row.value=result
    else:db.session.add(WorkspaceSetting(workspace_id=w.id,key=key,value=result))
    db.session.commit();return result


@bp.get('/preferences')
def preferences():
    v=read_setting('writing_tools');values={**DEFAULTS,**v['data']}
    existing=Writing.query.filter_by(owner_id=g.principal.id).first() or SourceDocument.query.filter_by(owner_id=g.principal.id).first()
    return success({**v,'data':values,'offerTutorial':v['revisionNumber']==0 and not bool(existing)})


@bp.patch('/preferences')
@guarded
def save_preferences():
    b=body();only(b,{'revisionNumber','data'});patch=b['data']
    if not isinstance(patch,dict):raise ValueError()
    only(patch,DEFAULTS)
    for k,v in patch.items():
        if k=='fontSize' and (type(v) is not int or not 14<=v<=28):raise ValueError()
        if k=='lineHeight' and (type(v) not in (int,float) or not 1.4<=v<=2.4):raise ValueError()
        if k=='bodyWidth' and (type(v) is not int or not 520<=v<=1100):raise ValueError()
        if k=='focus' and type(v) is not bool:raise ValueError()
        if k=='tutorial' and v not in {'UNSEEN','ACTIVE','SKIPPED','COMPLETED'}:raise ValueError()
        if k=='tutorialStep' and (type(v) is not int or not 0<=v<=3):raise ValueError()
        if k=='mobileTab' and v not in {'body','source','notes'}:raise ValueError()
    old=read_setting('writing_tools')
    return success(store_setting('writing_tools',{**old['data'],**patch},b.get('revisionNumber')))


@bp.get('/sources')
@guarded
def sources():
    q=request.args.get('q','').casefold().strip()
    if len(q)>100:raise ValueError()
    # Keep the existing access/retention decisions; batch only request-local
    # metadata used by every visible row. No reference text is loaded here.
    items=[item for item in SourceDocument.query.order_by(SourceDocument.created_at.desc()) if allowed_metadata(item)]
    if not items:return success([])
    current=workspace();states={};genres={};latest_ids={}
    for offset in range(0,len(items),500):
        ids=[item.id for item in items[offset:offset+500]]
        for row in WorkspaceSetting.query.filter(WorkspaceSetting.workspace_id==current.id,WorkspaceSetting.key.in_(['document:'+identifier for identifier in ids])):
            value=row.value if isinstance(row.value,dict) else {}
            states[row.key[9:]]=value.get('data',{})
        for work,did in db.session.query(Work,WorkDocument.document_id).join(WorkDocument,Work.id==WorkDocument.work_id).filter(WorkDocument.document_id.in_(ids)):
            if work.genre and did not in genres:genres[did]=work.genre
        latest=db.session.query(DocumentRevision.document_id,func.max(DocumentRevision.revision_number).label('number')).filter(DocumentRevision.document_id.in_(ids)).group_by(DocumentRevision.document_id).subquery()
        latest_ids.update(db.session.query(DocumentRevision.document_id,DocumentRevision.id).join(latest,(DocumentRevision.document_id==latest.c.document_id) & (DocumentRevision.revision_number==latest.c.number)).all())
    values=[]
    for item in items:
        state=states.get(item.id,{})
        genre=genres.get(item.id,(item.edition_metadata or {}).get('genre','기타'))
        if q and q not in (item.title+' '+(item.author or '')+' '+genre).casefold():continue
        if any(request.args.get(k) and request.args[k]!=v for k,v in [('scope',item.scope),('access',item.access_mode),('genre',genre)]):continue
        if request.args.get('favorite')=='1' and not state.get('favorite'):continue
        values.append({**document_data(item,latest_ids=latest_ids),'genre':genre,'favorite':bool(state.get('favorite')),'lastUsed':state.get('lastUsed'),'isOwner':item.owner_id==g.principal.id,
            'sourceType':'REFERENCE' if item.document_type in {'REFERENCE','CRITERIA'} else 'ORIGINAL'})
        if len(values)>=1000:break
    if request.args.get('recent')=='1':values=sorted([x for x in values if x['lastUsed']],key=lambda x:x['lastUsed'],reverse=True)
    return success(values)


@bp.route('/sources/<identifier>/state',methods=['GET','PATCH'])
@guarded
def source_state(identifier):
    item=document(identifier);key='document:'+item.id;old=read_setting(key)
    if request.method=='GET':
        value=dict(old['data'])
        if value.get('revisionId'):
            try:document(identifier,'VIEW');revision_for(item,value['revisionId'])
            except Exception:value={k:v for k,v in value.items() if k in {'favorite','lastUsed'}}
        if value.get('writingId'):
            try:
                w=owned_writing(value['writingId'])
                if hashlib.sha256(w.content.encode()).hexdigest()!=value.get('essayBodySha256'):value={k:v for k,v in value.items() if k not in {'essayOffset','writingId','essayBodySha256'}}
            except Exception:value={k:v for k,v in value.items() if k not in {'essayOffset','writingId','essayBodySha256'}}
        if value.get('openCardId'):
            row=db.session.get(QuoteCard,value['openCardId'])
            if not row or row.owner_id!=g.principal.id or row.document_id!=item.id or not card_visible(row):value.pop('openCardId',None)
        return success({**old,'data':value})
    b=body();only(b,{'revisionNumber','data'});v=b['data'];only(v,{'favorite','revisionId','offset','scrollFraction','openCardId','essayOffset','writingId','lastUsed'})
    if 'favorite' in v and type(v['favorite']) is not bool:raise ValueError()
    if any(k in v for k in ['revisionId','offset','scrollFraction','openCardId','essayOffset']):
        document(identifier,'VIEW');r=revision_for(item,v.get('revisionId',old['data'].get('revisionId')))
        if 'offset' in v and (type(v['offset']) is not int or not 0<=v['offset']<=len(r.content)):raise ValueError()
        if 'scrollFraction' in v and (type(v['scrollFraction']) not in {int,float} or not 0<=v['scrollFraction']<=1):raise ValueError()
        if 'essayOffset' in v and (type(v['essayOffset']) is not int or not 0<=v['essayOffset']<=30000):raise ValueError()
        if v.get('openCardId') and own_card(v['openCardId']).document_id!=item.id:raise ValueError()
    if v.get('writingId'):
        w=owned_writing(v['writingId'])
        if type(v.get('essayOffset')) is not int or not 0<=v['essayOffset']<=len(w.content):raise ValueError()
        v={**v,'essayBodySha256':hashlib.sha256(w.content.encode()).hexdigest()}
    # Client timestamps cannot fabricate recent usage.
    return success(store_setting(key,{**old['data'],**v,'lastUsed':datetime.now(timezone.utc).isoformat()},b.get('revisionNumber')))


@bp.post('/sources/<identifier>/search')
@guarded
def context_search(identifier):
    item=document(identifier,'VIEW');b=body();only(b,{'revisionId','query'})
    revision=revision_for(item,b.get('revisionId'));query=text(b['query'],100)
    if not query:raise ValueError()
    hits=[];at=0
    while len(hits)<20:
        pos=revision.content.find(query,at)
        if pos<0:break
        a=max(0,pos-35);z=min(len(revision.content),pos+len(query)+35)
        hits.append({'span':{'start':pos,'end':pos+len(query)},'quote':revision.content[pos:pos+len(query)],'context':revision.content[a:z],'contextStart':a})
        at=pos+len(query)
    return success({'documentId':item.id,'revisionId':revision.id,'contentHash':revision.content_hash,'hits':hits,'truncated':len(hits)==20,'locationUnit':'UNICODE_CODE_POINT_HALF_OPEN'})


@bp.get('/writings/<identifier>/sources')
def writing_sources(identifier):
    owned_writing(identifier);out=[]
    for link in EssayDocument.query.filter_by(writing_id=identifier):
        r=db.session.get(DocumentRevision,link.revision_id);item=db.session.get(SourceDocument,r.document_id) if r else None
        visible=bool(allowed_metadata(item))
        if visible:
            try:revision_for(item,r.id)
            except Exception:visible=False
        out.append({'revisionId':link.revision_id,'documentId':item.id if visible else None,'title':item.title if visible else '접근할 수 없는 선택 자료','available':visible})
    return success(out)


@bp.delete('/writings/<identifier>/sources/<rid>')
def detach_source(identifier,rid):
    owned_writing(identifier)
    EssayDocument.query.filter_by(writing_id=identifier,revision_id=rid).delete()
    db.session.commit();return success({'removed':True})


def mark(identifier):
    row=db.session.get(UserAnnotation,identifier)
    if not row or row.user_id!=g.principal.id or row.annotation_kind not in KINDS:abort(404)
    owned_writing(row.writing_id);return row


def resolved(row,writing):
    v=db.session.get(WritingVersion,row.essay_version_id)
    if not v:return {'status':'NEEDS_REVIEW','span':None}
    if row.essay_version_id==writing.current_version_id and writing.content==v.content and writing.content[row.span_start:row.span_end]==row.quote:
        return {'status':'ANCHORED','span':{'start':row.span_start,'end':row.span_end}}
    before=v.content[max(0,row.span_start-24):row.span_start];after=v.content[row.span_end:row.span_end+24]
    at=writing.content.find(row.quote)
    if at>=0 and writing.content.find(row.quote,at+1)<0 and (before or after):
        if writing.content[max(0,at-len(before)):at]==before and writing.content[at+len(row.quote):at+len(row.quote)+len(after)]==after:
            return {'status':'RESOLVED_DRAFT','span':{'start':at,'end':at+len(row.quote)},'requiresVersionConfirmation':True}
    return {'status':'NEEDS_REVIEW','span':None}


def mark_data(row,writing):
    r={**annotation_data(row),'kind':row.annotation_kind,'source':'USER_DEFINED','metadata':row.metadata_json or {},'resolution':resolved(row,writing)}
    if row.annotation_kind=='USER_LINK':
        a=db.session.get(UserAnnotation,r['metadata'].get('claimId'));b=db.session.get(UserAnnotation,r['metadata'].get('evidenceId'))
        if not a or not b or a.annotation_kind!='USER_CLAIM' or b.annotation_kind!='USER_EVIDENCE' or a.writing_id!=writing.id or b.writing_id!=writing.id or any(resolved(x,writing)['status']=='NEEDS_REVIEW' for x in [a,b]):r['resolution']={'status':'NEEDS_REVIEW','span':None}
    return r


@bp.route('/writings/<identifier>/marks',methods=['GET','POST'])
@guarded
def marks(identifier):
    w=owned_writing(identifier)
    if request.method=='GET':return success([mark_data(x,w) for x in UserAnnotation.query.filter_by(writing_id=w.id,user_id=g.principal.id).filter(UserAnnotation.annotation_kind.in_(KINDS)).order_by(UserAnnotation.created_at,UserAnnotation.id)])
    b=body();only(b,{'kind','anchor'})
    if b.get('kind') not in {'USER_CLAIM','USER_EVIDENCE'}:raise ValueError()
    v,a,z=version_anchor(w.id,b['anchor'])
    db.session.execute(update(Writing).where(Writing.id==w.id).values(updated_at=Writing.updated_at))
    existing=UserAnnotation.query.filter_by(user_id=g.principal.id,writing_id=w.id,essay_version_id=v.id,span_start=a,span_end=z,annotation_kind=b['kind']).first()
    if existing:db.session.commit();return success(mark_data(existing,w))
    if UserAnnotation.query.filter_by(writing_id=w.id).count()>=2000:abort(429)
    row=UserAnnotation(user_id=g.principal.id,writing_id=w.id,essay_version_id=v.id,span_start=a,span_end=z,quote=v.content[a:z],content='직접 지정한 '+('주장' if b['kind']=='USER_CLAIM' else '근거'),original_anchor=b['anchor'],annotation_kind=b['kind'],metadata_json={'source':'USER_DEFINED'})
    db.session.add(row);db.session.commit();return success(mark_data(row,w),status=201)


@bp.post('/writings/<identifier>/links')
@guarded
def create_link(identifier):
    w=owned_writing(identifier);b=body();only(b,{'claimId','evidenceId','classification'})
    claim,evidence=mark(b['claimId']),mark(b['evidenceId'])
    if claim.writing_id!=w.id or evidence.writing_id!=w.id or claim.annotation_kind!='USER_CLAIM' or evidence.annotation_kind!='USER_EVIDENCE':raise ValueError()
    if claim.essay_version_id!=evidence.essay_version_id or max(claim.span_start,evidence.span_start)<min(claim.span_end,evidence.span_end):raise ValueError()
    group=b.get('classification','UNSORTED')
    if group not in GROUPS:raise ValueError()
    if any(resolved(x,w)['status']=='NEEDS_REVIEW' for x in [claim,evidence]):abort(409,description='ANCHOR_REVIEW_REQUIRED')
    db.session.execute(update(Writing).where(Writing.id==w.id).values(updated_at=Writing.updated_at))
    for x in UserAnnotation.query.filter_by(writing_id=w.id,annotation_kind='USER_LINK'):
        if (x.metadata_json or {}).get('claimId')==claim.id and (x.metadata_json or {}).get('evidenceId')==evidence.id:db.session.commit();return success(mark_data(x,w))
    if UserAnnotation.query.filter_by(writing_id=w.id).count()>=2000:abort(429)
    row=UserAnnotation(user_id=g.principal.id,writing_id=w.id,essay_version_id=evidence.essay_version_id,span_start=evidence.span_start,span_end=evidence.span_end,quote=evidence.quote,content='사용자 지정 관계',original_anchor={'essayVersionId':evidence.essay_version_id,'span':{'start':evidence.span_start,'end':evidence.span_end},'quote':evidence.quote},annotation_kind='USER_LINK',metadata_json={'source':'USER_DEFINED','claimId':claim.id,'evidenceId':evidence.id,'classification':group})
    db.session.add(row);db.session.commit();return success(mark_data(row,w),status=201)


@bp.route('/marks/<identifier>',methods=['PATCH','DELETE'])
@guarded
def change_mark(identifier):
    row=mark(identifier);b=body();only(b,{'revisionNumber','anchor','classification','kind'})
    if type(b.get('revisionNumber')) is not int or b['revisionNumber']!=row.revision_number:abort(409,description='MARK_CONFLICT')
    q=UserAnnotation.query.filter_by(id=row.id,user_id=g.principal.id,revision_number=b['revisionNumber'])
    if request.method=='DELETE':
        if q.delete()!=1:abort(409)
        db.session.commit();return success({'deleted':True})
    values={'revision_number':row.revision_number+1,'updated_at':utcnow()}
    if 'anchor' in b:
        if row.annotation_kind=='USER_LINK':raise ValueError()
        v,a,z=version_anchor(row.writing_id,b['anchor']);values.update(essay_version_id=v.id,span_start=a,span_end=z,quote=v.content[a:z])
    if 'kind' in b:
        if row.annotation_kind=='USER_LINK' or b['kind'] not in {'USER_CLAIM','USER_EVIDENCE'}:raise ValueError()
        values['annotation_kind']=b['kind']
    if 'classification' in b:
        if row.annotation_kind!='USER_LINK' or b['classification'] not in GROUPS:raise ValueError()
        values['metadata_json']={**(row.metadata_json or {}),'classification':b['classification']}
    if len(values)==2:raise ValueError()
    if q.update(values,synchronize_session=False)!=1:abort(409)
    db.session.commit();db.session.refresh(row);return success(mark_data(row,owned_writing(row.writing_id)))


def card_visible(row):
    wid=(row.metadata_json or {}).get('writingId')
    if not wid:return True
    try:owned_writing(wid)
    except NotFound:return False
    return True


def own_card(identifier):
    row=db.session.get(QuoteCard,identifier)
    if not row or row.owner_id!=g.principal.id or not card_visible(row):abort(404)
    return row


def card_data(row):
    m=row.metadata_json or {};source=m.get('sourceAnchor');available=True
    if row.document_id:
        item=db.session.get(SourceDocument,row.document_id)
        available=bool(allowed_metadata(item) and item.access_mode in {'VIEW','DOWNLOAD'})
        if available and source:
            try:revision_for(item,source['revisionId'])
            except Exception:available=False
    result={'id':row.id,'kind':m.get('kind','NOTE'),'sourceType':m.get('sourceType','ORIGINAL'),
        'quote':row.quote_text if available else '', 'work':row.work if available else '접근할 수 없는 자료',
        'author':row.author if available else '', 'page':row.page if available else '',
        'documentId':row.document_id,
        'sourceAnchor':source if available else None,'sourceUnavailable':not available,
        'interpretation':m.get('interpretation',row.scene or ''),'claimText':m.get('claimText',''),
        'writingAnchor':m.get('writingAnchor'),'claimId':m.get('claimId'),'classification':m.get('classification','UNSORTED'),
        'revisionNumber':row.revision_number,'clientKey':row.client_key,'origin':'USER_DEFINED','updatedAt':iso(row.updated_at)}
    anchor=m.get('writingAnchor')
    if anchor:
        try:
            w=owned_writing(m['writingId']);v=db.session.get(WritingVersion,anchor['essayVersionId']);a,z=span(anchor['span'],v.content)
            class Holder:pass
            h=Holder();h.essay_version_id=v.id;h.span_start=a;h.span_end=z;h.quote=anchor['quote']
            result['writingResolution']=resolved(h,w)
        except Exception:result['writingResolution']={'status':'NEEDS_REVIEW','span':None}
    return result


def validate_card(b,old=None):
    only(b,{'kind','sourceType','quote','interpretation','claimText','documentId','sourceAnchor','writingAnchor','writingId','claimId','classification','clientKey','revisionNumber','page'})
    kind=b.get('kind','NOTE');typ=b.get('sourceType','MY_INTERPRETATION');group=b.get('classification','UNSORTED')
    if kind not in CARD_KINDS or typ not in SOURCE_TYPES or group not in GROUPS:raise ValueError()
    quote=text(b.get('quote',''),2000);interp=text(b.get('interpretation',''));claim_text=text(b.get('claimText',''))
    if not any(x.strip() for x in [quote,interp,claim_text]):raise ValueError()
    m={'kind':kind,'sourceType':typ,'interpretation':interp,'claimText':claim_text,'classification':group}
    did=None;selected='';work='';author=''
    if b.get('documentId'):
        item=document(b['documentId']);did=item.id;work=item.title;author=item.author or ''
    if b.get('sourceAnchor'):
        a=b['sourceAnchor'];only(a,{'documentId','revisionId','span','quote'})
        item=document(a['documentId'],'VIEW');v=revision_for(item,a['revisionId']);start,end=span(a['span'],v.content)
        if end-start>2000 or a.get('quote')!=v.content[start:end]:raise ValueError()
        did=item.id;selected=v.content[start:end];work=item.title;author=item.author or '';m['sourceAnchor']=a
        m['originalSourceAnchor']=(old or {}).get('originalSourceAnchor',a)
    if kind=='DIRECT_QUOTE' and (not m.get('sourceAnchor') or typ=='MY_INTERPRETATION'):raise ValueError()
    if b.get('writingId'):
        w=owned_writing(b['writingId']);m['writingId']=w.id
        if b.get('writingAnchor'):
            version_anchor(w.id,b['writingAnchor']);m['writingAnchor']=b['writingAnchor']
            m['originalWritingAnchor']=(old or {}).get('originalWritingAnchor',b['writingAnchor'])
    elif b.get('writingAnchor'):raise ValueError()
    if b.get('claimId'):
        c=mark(b['claimId'])
        if c.annotation_kind!='USER_CLAIM' or c.writing_id!=m.get('writingId'):raise ValueError()
        m['claimId']=c.id
    return {'document_id':did,'selected_text':selected,'quote_text':quote,'work':work,'author':author,'page':text(b.get('page',''),60),'metadata_json':m}


@bp.route('/cards',methods=['GET','POST'])
@guarded
def cards():
    if request.method=='GET':
        did=request.args.get('documentId');wid=request.args.get('writingId')
        if did:document(did)
        if wid:owned_writing(wid)
        rows=QuoteCard.query.filter_by(owner_id=g.principal.id).order_by(QuoteCard.updated_at.desc()).limit(1000)
        return success([card_data(x) for x in rows if card_visible(x) and (not did or x.document_id==did) and (not wid or (x.metadata_json or {}).get('writingId')==wid)])
    b=body();key=b.get('clientKey')
    if not isinstance(key,str) or not 8<=len(key)<=64:raise ValueError()
    old=QuoteCard.query.filter_by(owner_id=g.principal.id,client_key=key).first()
    if old:
        if not card_visible(old):abort(404)
        return success(card_data(old))
    values=validate_card(b)
    row=QuoteCard(workspace_id=workspace().id,owner_id=g.principal.id,client_key=key,**values)
    db.session.add(row);db.session.commit();return success(card_data(row),status=201)


@bp.route('/cards/<identifier>',methods=['GET','PATCH','DELETE'])
@guarded
def change_card(identifier):
    row=own_card(identifier)
    if request.method=='GET':return success(card_data(row))
    b=body()
    if type(b.get('revisionNumber')) is not int or b['revisionNumber']!=row.revision_number:abort(409,description='CARD_CONFLICT')
    q=QuoteCard.query.filter_by(id=row.id,owner_id=g.principal.id,revision_number=b['revisionNumber'])
    if request.method=='DELETE':
        only(b,{'revisionNumber'})
        if q.delete()!=1:abort(409)
        db.session.commit();return success({'deleted':True})
    prior=card_data(row);m=row.metadata_json or {}
    values=validate_card({**{k:prior[k] for k in ['kind','sourceType','quote','interpretation','claimText','documentId','sourceAnchor','writingAnchor','claimId','classification','page']},'writingId':m.get('writingId'),**b},m)
    if not values['metadata_json'].get('sourceAnchor') and values['document_id']==row.document_id:
        values.update(selected_text=row.selected_text,work=row.work,author=row.author)
    values.update(revision_number=row.revision_number+1,updated_at=utcnow())
    if q.update(values,synchronize_session=False)!=1:abort(409)
    db.session.commit();db.session.refresh(row);return success(card_data(row))


@bp.post('/cards/<identifier>/quotation-diff')
@guarded
def quotation_diff(identifier):
    row=own_card(identifier);m=row.metadata_json or {}
    if m.get('kind')!='DIRECT_QUOTE':return success({'applicable':False,'reason':'직접 인용으로 지정한 카드만 대조합니다.'})
    a=m['sourceAnchor'];item=document(a['documentId'],'VIEW');revision=revision_for(item,a['revisionId']);start,end=span(a['span'],revision.content)
    expected=revision.content[start:end];typed=row.quote_text
    if len(expected)>2000 or len(typed)>2000:raise ValueError()
    changes=[{'kind':tag,'sourceSpan':{'start':start+i,'end':start+j},'typedSpan':{'start':a,'end':b},'source':expected[i:j],'typed':typed[a:b]} for tag,i,j,a,b in SequenceMatcher(None,expected,typed,autojunk=False).get_opcodes() if tag!='equal']
    return success({'applicable':True,'exact':not changes,'documentId':item.id,'revisionId':revision.id,'changes':changes,'normalization':'NFC_LF','locationUnit':'UNICODE_CODE_POINT_HALF_OPEN','automaticCorrection':False})


def publication_row(identifier):
    row=db.session.get(PublicationRequest,identifier)
    if not row or (row.owner_id!=g.principal.id and g.principal.role!='ADMIN'):abort(404)
    return row


def publication_data(row):
    item=db.session.get(SourceDocument,row.document_id)
    delegated=row.owner_id==g.principal.id or row.state in {'PENDING','APPROVED'}
    return {'id':row.id,'documentId':row.document_id,'revisionId':row.revision_id,'revisionHash':row.revision_hash,
        'title':item.title if item and delegated else '검토 접근이 철회된 자료','state':row.state,'rightsBasis':row.rights_basis,
        'revisionNumber':row.revision_number,'history':row.history,'canReview':g.principal.role=='ADMIN' and row.state=='PENDING',
        'isOwner':row.owner_id==g.principal.id,'accessMode':item.access_mode if item and delegated else None}


@bp.get('/publication-requests')
def publications():
    query=PublicationRequest.query
    if g.principal.role!='ADMIN':query=query.filter_by(owner_id=g.principal.id)
    return success([publication_data(x) for x in query.order_by(PublicationRequest.created_at.desc()).limit(1000)])


@bp.post('/publication-requests')
@guarded
def request_publication():
    b=body();only(b,{'documentId','revisionId','rightsConfirmed','rightsBasis','delegateReview'})
    item=document(b['documentId'])
    if item.owner_id!=g.principal.id:abort(404)
    revision=revision_for(item,b['revisionId'])
    if b.get('rightsConfirmed') is not True or b.get('delegateReview') is not True or len(text(b.get('rightsBasis',''),2000).strip())<10:raise ValueError()
    if item.scope!='PRIVATE' or ocr_pending(item) or not revision.content.strip():abort(409,description='PUBLICATION_REVIEW_REQUIRED')
    if hashlib.sha256(revision.content.encode()).hexdigest()!=revision.content_hash:abort(409)
    existing=PublicationRequest.query.filter_by(owner_id=g.principal.id,document_id=item.id,revision_id=revision.id).first()
    if existing:return success(publication_data(existing))
    row=PublicationRequest(owner_id=g.principal.id,document_id=item.id,revision_id=revision.id,revision_hash=revision.content_hash,
        state='PENDING',rights_basis=b['rightsBasis'],history=[{'state':'PENDING','at':iso(utcnow())}])
    db.session.add(row);db.session.commit();return success(publication_data(row),status=201)


@bp.get('/publication-requests/<identifier>/revision')
@guarded
def delegated_revision(identifier):
    row=publication_row(identifier)
    if row.owner_id!=g.principal.id and row.state not in {'PENDING','APPROVED'}:abort(404)
    item=db.session.get(SourceDocument,row.document_id);r=db.session.get(DocumentRevision,row.revision_id)
    if not item or not r or r.content_hash!=row.revision_hash or hashlib.sha256(r.content.encode()).hexdigest()!=row.revision_hash:abort(409)
    from .privacy_lifecycle import document_expired
    if document_expired(item):abort(404)
    result={'requestId':row.id,'revisionId':r.id,'hash':r.content_hash,'accessMode':item.access_mode}
    if item.access_mode in {'VIEW','DOWNLOAD'}:result['content']=r.content
    return success(result)


@bp.patch('/publication-requests/<identifier>')
@guarded
def decide_publication(identifier):
    row=publication_row(identifier);b=body();only(b,{'state','revisionNumber','reviewConfirmed','reason'})
    action=b.get('state');expected=b.get('revisionNumber')
    if action not in {'APPROVED','REJECTED','WITHDRAWN'} or type(expected) is not int:raise ValueError()
    if action=='WITHDRAWN':
        if row.owner_id!=g.principal.id and g.principal.role!='ADMIN':abort(403)
    else:
        admin_required()
        if row.state!='PENDING':abort(409,description='PUBLICATION_STATE_CONFLICT')
        if action=='APPROVED' and b.get('reviewConfirmed') is not True:raise ValueError()
        if action=='REJECTED' and not text(b.get('reason',''),1000).strip():raise ValueError()
    if row.revision_number!=expected:abort(409,description='PUBLICATION_STATE_CONFLICT')
    if row.state=='WITHDRAWN':return success(publication_data(row))
    history=[*(row.history or []),{'state':action,'at':iso(utcnow()),'reason':text(b.get('reason',''),1000)}]
    count=PublicationRequest.query.filter_by(id=row.id,revision_number=expected,state=row.state).update({'state':action,'revision_number':expected+1,'history':history},synchronize_session=False)
    if count!=1:abort(409)
    item=db.session.get(SourceDocument,row.document_id);r=db.session.get(DocumentRevision,row.revision_id)
    if not item or item.owner_id!=row.owner_id or not r or r.content_hash!=row.revision_hash or hashlib.sha256(r.content.encode()).hexdigest()!=row.revision_hash:abort(409)
    metadata=dict(item.edition_metadata or {})
    if action=='APPROVED':
        from .privacy_lifecycle import document_expired
        owner=db.session.get(User,row.owner_id)
        if not owner or owner.status!='ACTIVE' or document_expired(item) or ocr_pending(item) or not item.title.strip() or item.scope!='PRIVATE':abort(409,description='PUBLICATION_TARGET_CHANGED')
        item.rights_confirmed=True;item.rights_info=row.rights_basis;item.scope='PUBLIC'
        metadata['publication']={'requestId':row.id,'revisionId':r.id,'ownerId':row.owner_id,'revisionHash':r.content_hash}
    elif action=='WITHDRAWN' and metadata.get('publication',{}).get('requestId')==row.id:
        item.scope='PRIVATE';metadata.pop('publication',None)
    item.edition_metadata=metadata
    db.session.add(ActivityRecord(action='PUBLICATION_'+action,actor_id=g.principal.id,target_type='source_document',target_id=item.id,details={'requestId':row.id,'revisionId':r.id}))
    db.session.commit();db.session.refresh(row);return success(publication_data(row))
