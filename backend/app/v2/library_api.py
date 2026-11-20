import hashlib
import io
import uuid
from pathlib import Path
from flask import Blueprint,g,request,abort,current_app,send_file
from sqlalchemy import func,or_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from ..extensions import db
from ..models import Workspace,WorkspaceSetting,Work,WorkDocument,SourceDocument,DocumentRevision,EssayDocument,QuoteCard,Rubric,ActivityRecord
from ..seed import DEFAULT_SETTINGS
from ..routes.core import ALLOWED_SETTINGS
from ..utils import success,api_error,json_body
from ..analysis.snapshot import normalize_text
from ..analysis.norms_reference import PRIMARY_REFERENCE
from components.auth import AuthDenied,require_public_permission
from .common import owned_writing,iso,admin_required
from .files import extract_file

bp=Blueprint('v2_library',__name__,url_prefix='/api')


def workspace():
    value=Workspace.query.filter_by(owner_id=g.principal.id).first()
    if not value:
        # First home loads workspace and preferences in parallel. Serialize the
        # deterministic insert and accept only an existing row owned by this user.
        db.session.execute(sqlite_insert(Workspace).values(id='user-'+g.principal.id,owner_id=g.principal.id,user_name='',name='글빛 작업 공간').on_conflict_do_nothing(index_elements=['id']))
        value=Workspace.query.filter_by(owner_id=g.principal.id).first()
        if not value:raise AuthDenied('RESOURCE_UNAVAILABLE')
    return value


@bp.get('/workspace')
def get_workspace():
    value=workspace();db.session.commit();return success({'id':value.id,'userName':value.user_name,'workspaceName':value.name})


@bp.patch('/workspace')
def patch_workspace():
    data,error=json_body()
    if error:return error
    if set(data)-{'id','userName','workspaceName','updatedAt'} or any(k in data and (not isinstance(data[k],str) or len(data[k])>120) for k in ['userName','workspaceName']):return api_error('VALIDATION_ERROR','표시 이름을 확인해 주세요.')
    value=workspace()
    if 'userName' in data:value.user_name=data['userName']
    if 'workspaceName' in data:value.name=data['workspaceName']
    db.session.commit();return success({'id':value.id,'userName':value.user_name,'workspaceName':value.name})


@bp.get('/settings')
def settings():
    value=workspace();values=dict(DEFAULT_SETTINGS);values.update({s.key:s.value for s in WorkspaceSetting.query.filter_by(workspace_id=value.id)});db.session.commit();return success(values)


@bp.patch('/settings')
def patch_settings():
    data,error=json_body()
    if error:return error
    for key,value in data.items():
        if key not in ALLOWED_SETTINGS:return api_error('VALIDATION_ERROR','허용되지 않은 설정입니다.')
        typ,minimum,maximum=ALLOWED_SETTINGS[key]
        if not isinstance(value,typ) or (typ in (int,float) and isinstance(value,bool)) or (minimum is not None and not minimum<=value<=maximum):return api_error('VALIDATION_ERROR','설정 범위를 확인해 주세요.')
        if key=='theme' and value not in {'default','bookshelf'}:return api_error('VALIDATION_ERROR','테마를 확인해 주세요.')
    current=workspace()
    for key,value in data.items():
        setting=WorkspaceSetting.query.filter_by(workspace_id=current.id,key=key).first()
        if setting:setting.value=value
        else:db.session.add(WorkspaceSetting(workspace_id=current.id,key=key,value=value))
    db.session.commit();return settings()


def allowed_metadata(item):
    if isinstance(item,SourceDocument):
        from .privacy_lifecycle import document_expired
        try:
            if document_expired(item):return False
        except ValueError:return False
    return item and ((item.owner_id==g.principal.id and item.owner_id is not None) or (item.scope=='PUBLIC' and bool(getattr(item,'rights_confirmed',True))))


def document(identifier,mode=None):
    item=db.session.get(SourceDocument,identifier)
    if not allowed_metadata(item) or item.scope not in {'PUBLIC','PRIVATE'} or (mode=='VIEW' and item.access_mode not in {'VIEW','DOWNLOAD'}) or (mode=='DOWNLOAD' and item.access_mode!='DOWNLOAD'):abort(404,description='API resource unavailable')
    return item


def editable(item,action='ADD'):
    if item.scope=='PUBLIC':require_public_permission(g.principal,action)
    elif item.owner_id!=g.principal.id:abort(404,description='API resource unavailable')


def revision_for(item,identifier=None):
    delegated=(item.edition_metadata or {}).get('publication',{}) if item.owner_id!=g.principal.id else {}
    pinned=delegated.get('revisionId')
    if pinned:
        if identifier and identifier!=pinned:abort(404,description='API resource unavailable')
        identifier=pinned
    value=db.session.get(DocumentRevision,identifier) if identifier else DocumentRevision.query.filter_by(document_id=item.id).order_by(DocumentRevision.revision_number.desc()).first()
    if not value or value.document_id!=item.id:abort(404,description='API resource unavailable')
    return value


def can_manage_scope(item):
    # Existing public ADD grants do not imply ownership of another user's data.
    return g.principal.role=='ADMIN' and item.owner_id is not None and item.owner_id==g.principal.id and not ocr_pending(item)


def ocr_pending(item):
    value=(item.edition_metadata or {}).get('ocr',{})
    return bool(value.get('jobId') and not value.get('confirmedRevisionId'))


def public_scope_issues(item):
    issues=[]
    if ocr_pending(item):issues.append('OCR 검수와 원문 확정이 필요합니다.')
    if not item.title or not item.title.strip():issues.append('자료 제목이 필요합니다.')
    if item.document_type not in {'TEXT','CRITERIA','REFERENCE','INFO'}:issues.append('자료 유형을 확인해 주세요.')
    if item.rights_confirmed is not True or not (item.rights_info or '').strip():issues.append('공개 이용 권리 확인 정보가 필요합니다.')
    revisions=DocumentRevision.query.filter_by(document_id=item.id).all()
    if not revisions:issues.append('분석 가능한 판본이 필요합니다.')
    # 0004 scope belongs to a document, not to its immutable revision history.
    # Do not accidentally publish additional private revisions or work records.
    if item.scope=='PRIVATE' and len(revisions)>1:issues.append('여러 개인 판본이 있어 개별 공개 범위를 확인해야 합니다.')
    works=Work.query.join(WorkDocument,WorkDocument.work_id==Work.id).filter(WorkDocument.document_id==item.id).all()
    if len(works)>1 or any(w.owner_id!=item.owner_id for w in works):issues.append('연결된 작품의 관리 권한을 확인해 주세요.')
    directory=Path(current_app.config['UPLOAD_FOLDER']).resolve()
    for revision in revisions:
        if hashlib.sha256(revision.content.encode()).hexdigest()!=revision.content_hash:issues.append('판본 무결성을 확인해 주세요.');break
    for name in {item.stored_name,*[r.file_ref for r in revisions if r.file_ref]}:
        target=(directory/name).resolve()
        if not target.is_relative_to(directory) or not target.is_file():issues.append('등록 파일을 확인해 주세요.');break
    return issues


def document_data(item,view=False,latest_ids=None):
    # Listing must not load full reference bodies, or query once per document.
    revision=revision_for(item) if view else None
    if view:latest_id=revision.id if revision else None
    elif latest_ids is not None:latest_id=latest_ids.get(item.id)
    else:latest_id=db.session.query(DocumentRevision.id).filter_by(document_id=item.id).order_by(DocumentRevision.revision_number.desc()).limit(1).scalar()
    result={'id':item.id,'title':item.title,'author':item.author,'edition':item.edition,'originalName':item.original_name,'mimeType':item.mime_type,'size':item.size,'pages':item.page_count,'status':'등록 완료','cards':0,'date':iso(item.created_at),'scope':item.scope,'accessMode':item.access_mode,'documentType':item.document_type,'rightsInfo':item.rights_info,'sourceUrl':item.source_url,'latestRevisionId':latest_id,'ocr':{'status':'not_required','ocrMode':(item.edition_metadata or {}).get('ocrImportMode'),'notice':'텍스트 직접 추출 자료입니다.'}}
    pinned=(item.edition_metadata or {}).get('publication',{}).get('revisionId') if item.owner_id!=g.principal.id else None
    if pinned:
        result['latestRevisionId']=pinned
        result['originalName']='등록된 자료'
    result['canManageScope']=can_manage_scope(item)
    ocr=(item.edition_metadata or {}).get('ocr',{})
    if ocr.get('jobId'):
        result['status']='OCR 검수 필요' if ocr_pending(item) else '등록 완료'
        # Review content and crop endpoints remain owner-only, including PUBLIC.
        result['ocr']={'status':'needs_review' if ocr_pending(item) else 'confirmed','ocrMode':ocr.get('ocrMode','precise'),'jobId':ocr['jobId'] if item.owner_id==g.principal.id and item.access_mode in {'VIEW','DOWNLOAD'} else None,'reviewAvailable':item.owner_id==g.principal.id and item.access_mode in {'VIEW','DOWNLOAD'}}
    if view and item.access_mode in {'VIEW','DOWNLOAD'} and revision:
        result['content']=revision.content
        result['pageData']=[{'id':revision.id,'pageNumber':1,'originalText':revision.content,'correctedText':revision.content,'confidence':None,'extractionMethod':'native_text','status':'not_required'}]
        result['textLocationUnit']='DOCUMENT_REVISION_CODE_POINT_NOT_PDF_PAGE'
    return result


@bp.get('/works')
def works():return success([{'id':w.id,'title':w.title,'author':w.author,'genre':w.genre,'introduction':w.introduction,'vocabulary':w.vocabulary or [],'scope':w.scope} for w in Work.query.filter(or_(Work.owner_id==g.principal.id,Work.scope=='PUBLIC')).all()])


@bp.post('/works')
def create_work():
    data,error=json_body()
    if error:return error
    scope=data.get('scope','PRIVATE')
    if scope not in {'PRIVATE','PUBLIC'} or not isinstance(data.get('title'),str) or not data['title'].strip():return api_error('VALIDATION_ERROR','작품 정보를 확인해 주세요.')
    if scope=='PUBLIC':require_public_permission(g.principal,'ADD')
    vocabulary=data.get('vocabulary',[])
    if not isinstance(vocabulary,list) or not all(isinstance(x,str) and x.strip() for x in vocabulary):return api_error('VALIDATION_ERROR','작품 어휘를 확인해 주세요.')
    item=Work(owner_id=g.principal.id,title=data['title'],author=data.get('author',''),genre=data.get('genre',''),introduction=data.get('introduction',''),vocabulary=vocabulary,scope=scope);db.session.add(item);db.session.commit();return success({'id':item.id},status=201)


@bp.patch('/works/<identifier>')
def patch_work(identifier):
    item=db.session.get(Work,identifier)
    if not allowed_metadata(item):abort(404,description='API resource unavailable')
    editable(item);data,error=json_body()
    if error:return error
    if set(data)-{'title','author','genre','introduction','vocabulary'}:return api_error('VALIDATION_ERROR','지원하지 않는 변경입니다.')
    for key,value in data.items():
        if key=='vocabulary':
            if not isinstance(value,list) or not all(isinstance(x,str) for x in value):return api_error('VALIDATION_ERROR','어휘를 확인해 주세요.')
        elif not isinstance(value,str):return api_error('VALIDATION_ERROR','문자열이 필요합니다.')
        setattr(item,key,value)
    db.session.commit();return success({'id':item.id})


@bp.delete('/works/<identifier>')
def delete_work(identifier):
    item=db.session.get(Work,identifier)
    if not allowed_metadata(item):abort(404,description='API resource unavailable')
    editable(item,'DELETE')
    if WorkDocument.query.filter_by(work_id=item.id).first():return api_error('RESOURCE_IN_USE','연결된 문서를 먼저 확인해 주세요.',409)
    db.session.delete(item);db.session.commit();return success({'deleted':True})


@bp.get('/source-documents')
def documents():
    query=SourceDocument.query.filter(or_(SourceDocument.owner_id==g.principal.id,(SourceDocument.scope=='PUBLIC') & (SourceDocument.rights_confirmed==True)))
    items=[d for d in query.all() if d.scope in {'PRIVATE','PUBLIC'} and allowed_metadata(d)]
    latest=db.session.query(DocumentRevision.document_id,func.max(DocumentRevision.revision_number).label('number')).filter(DocumentRevision.document_id.in_([d.id for d in items])).group_by(DocumentRevision.document_id).subquery()
    ids=dict(db.session.query(DocumentRevision.document_id,DocumentRevision.id).join(latest,(DocumentRevision.document_id==latest.c.document_id) & (DocumentRevision.revision_number==latest.c.number)).all())
    return success([document_data(d,latest_ids=ids) for d in items])


@bp.post('/source-documents')
def upload():
    file=request.files.get('file');scope=request.form.get('scope','PRIVATE');mode=request.form.get('accessMode','VIEW');kind=request.form.get('documentType','TEXT')
    ocr_mode=request.form.get('ocrMode','precise')
    if ocr_mode=='standard':return api_error('OCR_MODE_RETIRED','새 자료는 고정밀 OCR로 등록해 주세요.',400)
    if ocr_mode!='precise':return api_error('VALIDATION_ERROR','OCR 모드를 확인해 주세요.')
    from ..services.ocr_pipeline import LITERARY_PROFILES
    ocr_profile=request.form.get('ocrProfile','auto')
    if ocr_profile not in LITERARY_PROFILES:return api_error('VALIDATION_ERROR','OCR 장르 프로필을 확인해 주세요.')
    if not file or scope not in {'PRIVATE','PUBLIC'} or mode not in {'MATCH_ONLY','VIEW','DOWNLOAD'} or kind not in {'TEXT','CRITERIA','REFERENCE','INFO'}:return api_error('VALIDATION_ERROR','파일과 자료 속성을 확인해 주세요.')
    rights=request.form.get('rightsConfirmed')=='true';rights_info=request.form.get('rightsInfo','')
    data=file.read(current_app.config['MAX_CONTENT_LENGTH']+1)
    # User approval is bound to these exact bytes, not a filename or a new
    # general PUBLIC permission. The existing verified bootstrap account only.
    approved_reference=(scope=='PUBLIC' and kind=='REFERENCE'
        and hashlib.sha256(data).hexdigest()==PRIMARY_REFERENCE['sha256']
        and g.principal.role=='ADMIN' and g.principal.email_verified is True
        and g.principal.email=='ps25090@onedu.jje.go.kr')
    if scope=='PUBLIC':
        if not approved_reference:require_public_permission(g.principal,'ADD')
        if not rights or not rights_info.strip():return api_error('RIGHTS_REQUIRED','공개 자료의 권리 확인이 필요합니다.',403)
    limit=PRIMARY_REFERENCE['pdfPageCount'] if approved_reference else current_app.config.get('PDF_MAX_PAGES',100)
    pending=False
    try:
        from ..services import ocr_jobs
        is_text=(file.filename or '').lower().endswith('.txt')
        if not is_text and not approved_reference:db.session.remove()
        inspected=ocr_jobs.inspect_upload(data,file.filename or '') if not is_text and not approved_reference else None
        if inspected:
            body=inspected['nativeText'];pending=inspected['needsOcr'] or not body.strip();mime=inspected['mime'];pages=inspected['pages']
            if pending and (scope!='PRIVATE' or mode=='MATCH_ONLY'):
                return api_error('OCR_REVIEW_REQUIRED','스캔 자료는 개인·원문 보기 권한으로 검수 후 확정해 주세요.',409)
            if pending:body='' # Empty immutable input revision; never a source for analysis.
        else:body,mime,pages=extract_file(data,file.filename or '',max_bytes=current_app.config['MAX_CONTENT_LENGTH'],max_pages=limit)
    except ocr_jobs.OcrCapacityError:return api_error('OCR_BUSY','파일 검사 작업이 진행 중입니다. 잠시 뒤 다시 업로드해 주세요.',429)
    except Exception:return api_error('INVALID_FILE','파일 형식·암호·손상·크기·페이지 제한 또는 로컬 OCR 환경을 확인해 주세요.')
    work_id=request.form.get('workId');work=db.session.get(Work,work_id) if work_id else None
    if work_id and (not allowed_metadata(work) or work.owner_id!=g.principal.id or work.scope!=scope):return api_error('INVALID_WORK','작품의 소유권과 공개 범위를 확인해 주세요.',403)
    directory=Path(current_app.config['UPLOAD_FOLDER']).resolve();directory.mkdir(parents=True,exist_ok=True)
    if approved_reference:
        for existing in SourceDocument.query.filter_by(scope='PUBLIC',document_type='REFERENCE',title=PRIMARY_REFERENCE['title']):
            stored=(directory/existing.stored_name).resolve()
            if stored.is_relative_to(directory) and stored.is_file() and hashlib.sha256(stored.read_bytes()).hexdigest()==PRIMARY_REFERENCE['sha256']:
                return success(document_data(existing))
    suffix={'application/pdf':'.pdf','image/png':'.png','image/jpeg':'.jpg','image/tiff':'.tiff'}.get(mime,'.txt')
    name=uuid.uuid4().hex+suffix;target=directory/name
    if not target.resolve().is_relative_to(directory):abort(500)
    item=None;created_file=False
    try:
        with target.open('xb') as out:
            created_file=True;out.write(data)
        item=SourceDocument(workspace_id=workspace().id,owner_id=g.principal.id,title=PRIMARY_REFERENCE['title'] if approved_reference else request.form.get('title') or (file.filename or '자료'),author=request.form.get('author',''),edition=request.form.get('edition',''),original_name=(file.filename or '').replace('\\','/').split('/')[-1],stored_name=name,mime_type=mime,size=len(data),page_count=pages,document_type=kind,scope=scope,access_mode=mode,rights_confirmed=rights,rights_info=rights_info,source_url=request.form.get('sourceUrl',''))
        db.session.add(item);db.session.flush();revision=DocumentRevision(document_id=item.id,revision_number=1,content=body,content_hash=hashlib.sha256(body.encode()).hexdigest(),file_ref=name);db.session.add(revision);db.session.flush()
        item.edition_metadata={**(item.edition_metadata or {}),'ocrImportMode':ocr_mode,'ocrImportProfile':ocr_profile}
        if pending:
            run=ocr_jobs.create_job(item,revision.id,mode=ocr_mode,profile=ocr_profile)
            item.edition_metadata={**item.edition_metadata,'ocr':{'jobId':run.id,'confirmedRevisionId':None,'ocrMode':ocr_mode,'ocrProfile':ocr_profile}}
            item.status='OCR 검수 필요'
        if work:db.session.add(WorkDocument(work_id=work.id,document_id=item.id))
        db.session.commit()
    except Exception:
        db.session.rollback()
        if created_file and target.is_file() and target.resolve().is_relative_to(directory):target.unlink() # this request's new artifact only
        import sys
        if isinstance(sys.exception(),ocr_jobs.OcrCapacityError):return api_error('OCR_BUSY','OCR 대기 한도에 도달했습니다. 진행 중인 작업 후 다시 시도해 주세요.',429)
        raise
    if pending:ocr_jobs.kick()
    return success(document_data(item),status=201)


@bp.get('/source-documents/<identifier>')
def detail(identifier):return success(document_data(document(identifier),True))


@bp.patch('/source-documents/<identifier>/scope')
def change_document_scope(identifier):
    admin_required()
    item=document(identifier)
    if not can_manage_scope(item):abort(404,description='API resource unavailable')
    data,error=json_body()
    if error:return error
    if set(data)!={'scope','expectedRevisionId'} or not isinstance(data.get('scope'),str) or data['scope'] not in {'PRIVATE','PUBLIC'} or not isinstance(data.get('expectedRevisionId'),str):return api_error('VALIDATION_ERROR','공개 범위와 선택한 판본만 전송해 주세요.')
    try:
        # Serialize with revisions/selection; lock acquisition changes no dates.
        db.session.execute(db.update(SourceDocument).where(SourceDocument.id==item.id).values(updated_at=SourceDocument.updated_at))
        db.session.refresh(item)
        latest=revision_for(item)
        if data['expectedRevisionId']!=latest.id:
            db.session.rollback();return api_error('REVISION_CONFLICT','판본이 변경되었습니다. 자료 목록을 새로 확인해 주세요.',409)
        before=item.scope;after=data['scope']
        if before==after:
            db.session.commit();return success(document_data(item))
        if after=='PUBLIC':
            issues=public_scope_issues(item)
            if issues:
                db.session.rollback();return api_error('PUBLIC_METADATA_REQUIRED',' '.join(issues),409)
        item.scope=after
        works=Work.query.join(WorkDocument,WorkDocument.work_id==Work.id).filter(WorkDocument.document_id==item.id).all()
        changed_works=[]
        for work in works:
            # Never promote a foreign work or alter a sibling document.
            if work.owner_id!=item.owner_id:continue
            visible=db.session.query(SourceDocument.id).join(WorkDocument,WorkDocument.document_id==SourceDocument.id).filter(WorkDocument.work_id==work.id,SourceDocument.scope=='PUBLIC',SourceDocument.rights_confirmed==True).first()
            scope='PUBLIC' if visible else 'PRIVATE'
            if work.scope!=scope:work.scope=scope;changed_works.append(work.id)
        db.session.add(ActivityRecord(action='DOCUMENT_SCOPE_CHANGED',actor_id=g.principal.id,target_type='source_document',target_id=item.id,details={'before':before,'after':after,'revisionId':latest.id,'workIds':changed_works}))
        db.session.commit()
    except Exception:
        db.session.rollback()
        return api_error('SCOPE_CHANGE_FAILED','공개 범위를 변경하지 못했습니다. 다시 시도해 주세요.',500)
    return success(document_data(item))


@bp.post('/source-documents/<identifier>/revisions')
def new_revision(identifier):
    item=document(identifier);editable(item);data,error=json_body()
    if error:return error
    if ocr_pending(item):return api_error('OCR_REVIEW_REQUIRED','OCR 검수 화면에서 원문을 확정해 주세요.',409)
    try:body=normalize_text(data['content'])
    except (KeyError,ValueError,TypeError):return api_error('VALIDATION_ERROR','원문 문자열이 필요합니다.')
    latest=revision_for(item)
    if data.get('expectedRevisionId')!=latest.id:return api_error('REVISION_CONFLICT','판본 수정 이력이 변경되었습니다.',409)
    # Acquire a short write lock before checking latest revision again.
    db.session.execute(db.update(SourceDocument).where(SourceDocument.id==item.id).values(updated_at=SourceDocument.updated_at))
    latest=revision_for(item)
    if data['expectedRevisionId']!=latest.id:db.session.rollback();return api_error('REVISION_CONFLICT','판본 수정 이력이 변경되었습니다.',409)
    if body==latest.content:return success({'id':latest.id,'revisionNumber':latest.revision_number})
    revision=DocumentRevision(document_id=item.id,parent_id=latest.id,revision_number=latest.revision_number+1,content=body,content_hash=hashlib.sha256(body.encode()).hexdigest());db.session.add(revision);db.session.commit();return success({'id':revision.id,'revisionNumber':revision.revision_number},status=201)


@bp.get('/source-documents/<identifier>/revisions/<rid>')
def get_revision(identifier,rid):
    item=document(identifier,'VIEW');revision=revision_for(item,rid)
    return success({'id':revision.id,'content':revision.content,'hash':revision.content_hash,'revisionNumber':revision.revision_number})


@bp.get('/files/source/<identifier>')
def download(identifier):
    item=document(identifier,'DOWNLOAD');revision=revision_for(item,request.args.get('revision'))
    if ((item.edition_metadata or {}).get('publication') and item.owner_id!=g.principal.id) or not revision.file_ref:return send_file(io.BytesIO(revision.content.encode()),as_attachment=True,download_name='document.txt',mimetype='text/plain')
    directory=Path(current_app.config['UPLOAD_FOLDER']).resolve();target=(directory/revision.file_ref).resolve()
    if not target.is_relative_to(directory) or not target.is_file():abort(404,description='API resource unavailable')
    suffix={'application/pdf':'.pdf','image/png':'.png','image/jpeg':'.jpg','image/tiff':'.tiff'}.get(item.mime_type,'.txt')
    return send_file(target,as_attachment=True,download_name='document'+suffix,mimetype=item.mime_type)


@bp.post('/writings/<identifier>/documents')
def attach(identifier):
    owned_writing(identifier);data,error=json_body()
    if error:return error
    revision=db.session.get(DocumentRevision,data.get('revisionId'))
    if not revision:abort(404,description='API resource unavailable')
    source=document(revision.document_id)
    revision_for(source,revision.id)
    if ocr_pending(source) or ((source.edition_metadata or {}).get('ocr') and not revision.content.strip()):return api_error('OCR_REVIEW_REQUIRED','OCR 초안은 검수·확정 후 분석에 연결할 수 있습니다.',409)
    # Current selection uses one revision of this document. Past runs retain their
    # immutable context snapshot and the old DocumentRevision itself.
    db.session.execute(db.update(SourceDocument).where(SourceDocument.id==revision.document_id).values(updated_at=SourceDocument.updated_at))
    old_ids=[r.id for r in DocumentRevision.query.filter_by(document_id=revision.document_id) if r.id!=revision.id]
    if old_ids:EssayDocument.query.filter(EssayDocument.writing_id==identifier,EssayDocument.revision_id.in_(old_ids)).delete(synchronize_session=False)
    if not db.session.get(EssayDocument,(identifier,revision.id)):
        db.session.add(EssayDocument(writing_id=identifier,revision_id=revision.id))
    db.session.commit()
    return success({'writingId':identifier,'revisionId':revision.id})


@bp.get('/quote-cards')
def quotes():
    from .writing_tools_api import card_visible
    return success([{'id':q.id,'quote':q.quote_text,'work':q.work,'author':q.author,'page':q.page,'verificationStatus':q.verification_status} for q in QuoteCard.query.filter_by(owner_id=g.principal.id) if card_visible(q) and (not q.document_id or (allowed_metadata(db.session.get(SourceDocument,q.document_id)) and db.session.get(SourceDocument,q.document_id).access_mode in {'VIEW','DOWNLOAD'}))])


@bp.post('/quote-cards')
def create_quote():
    data,error=json_body()
    if error:return error
    if not isinstance(data.get('quote'),str) or not data['quote'].strip():return api_error('VALIDATION_ERROR','인용문이 필요합니다.')
    did=data.get('documentId')
    if did:document(did,'VIEW') # MATCH_ONLY cannot be copied into a new visible quote card
    item=QuoteCard(workspace_id=workspace().id,owner_id=g.principal.id,document_id=did,selected_text=data['quote'],quote_text=data['quote'],work=data.get('work',''),author=data.get('author',''),page=data.get('page',''));db.session.add(item);db.session.commit();return success({'id':item.id},status=201)


@bp.get('/rubrics')
def rubrics():
    from ..serializers import rubric_json
    from .privacy_lifecycle import rubric_expired
    return success([rubric_json(r) for r in Rubric.query.filter_by(owner_id=g.principal.id) if not rubric_expired(r)])


def own_rubric(identifier):
    item=db.session.get(Rubric,identifier)
    if not item or item.owner_id!=g.principal.id:abort(404,description='API resource unavailable')
    from .privacy_lifecycle import rubric_expired
    if rubric_expired(item):abort(404,description='API resource unavailable')
    return item


@bp.post('/rubrics')
def upload_rubric():
    from ..models import RubricFile
    from ..serializers import rubric_json
    file=request.files.get('file')
    if not file:return api_error('FILE_REQUIRED','파일을 선택해 주세요.')
    data=file.read(current_app.config['MAX_CONTENT_LENGTH']+1)
    try:body,mime,pages=extract_file(data,file.filename or '',max_bytes=current_app.config['MAX_CONTENT_LENGTH'],max_pages=current_app.config.get('PDF_MAX_PAGES',100))
    except (ValueError,UnicodeError,RuntimeError):return api_error('FILE_REJECTED','지원되는 텍스트 PDF 또는 UTF-8 파일을 선택해 주세요.')
    directory=Path(current_app.config['UPLOAD_FOLDER']);directory.mkdir(parents=True,exist_ok=True)
    stored=str(uuid.uuid4())+('.pdf' if mime=='application/pdf' else '.txt');target=directory/stored
    item=Rubric(workspace_id=workspace().id,owner_id=g.principal.id,name=(request.form.get('name') or Path(file.filename or '자료').name)[:240],subject=request.form.get('subject','')[:120],activity=request.form.get('activity','')[:240],status='확인 필요')
    created_file=False
    try:
        with target.open('xb') as stream:
            created_file=True;stream.write(data)
        db.session.add(item);db.session.flush()
        db.session.add(RubricFile(rubric_id=item.id,original_name=Path(file.filename or '자료').name[:255],stored_name=stored,mime_type=mime,size=len(data),page_count=pages,ocr_text=body,corrected_text=body))
        db.session.commit()
    except Exception:
        db.session.rollback()
        if created_file and target.is_file():target.unlink()
        raise
    return success(rubric_json(item),status=201)


@bp.get('/rubrics/<identifier>')
def get_rubric(identifier):
    from ..serializers import rubric_json
    return success(rubric_json(own_rubric(identifier)))


@bp.get('/files/rubrics/<identifier>')
def rubric_original(identifier):
    from ..models import RubricFile
    record=db.session.get(RubricFile,identifier)
    if not record:abort(404,description='API resource unavailable')
    own_rubric(record.rubric_id)  # Ownership/retention before filesystem access.
    if record.mime_type not in {'application/pdf','text/plain'}:abort(404,description='API resource unavailable')
    name=record.stored_name
    if not name or any(c in name for c in [':','/','\\','\x00']) or Path(name).name!=name:abort(404,description='API resource unavailable')
    directory=Path(current_app.config['UPLOAD_FOLDER']).resolve();target=directory/name
    if target.is_symlink() or not target.resolve().is_relative_to(directory) or not target.is_file():abort(404,description='API resource unavailable')
    suffix='.pdf' if record.mime_type=='application/pdf' else '.txt'
    try:return send_file(target,mimetype=record.mime_type,as_attachment=False,download_name='rubric'+suffix,max_age=0)
    except FileNotFoundError:abort(404,description='API resource unavailable')


@bp.post('/rubrics/<identifier>/ocr')
def rubric_ocr_disabled(identifier):
    own_rubric(identifier)
    return api_error('OCR_NOT_APPROVED','스캔 OCR은 별도 승인 범위입니다. 텍스트 추출 결과를 확인하세요.',409)


@bp.patch('/rubrics/<identifier>')
def patch_rubric(identifier):
    item=own_rubric(identifier);data,error=json_body()
    if error:return error
    # Keep original file/extracted source intact; this is an assessment rubric,
    # not a library DocumentRevision. No historical document is overwritten.
    if not item.file or not isinstance(data.get('correctedText'),str) or data.get('confirm') is not True:return api_error('VALIDATION_ERROR','수정한 기준을 확인해 주세요.')
    body=normalize_text(data['correctedText'])
    if item.file.corrected_text!=body:item.file.corrected_text=body
    item.status='확인 완료';db.session.commit()
    from ..serializers import rubric_json
    return success(rubric_json(item))


@bp.delete('/rubrics/<identifier>')
def delete_rubric(identifier):
    item=own_rubric(identifier)
    # Retain a criterion referenced by an existing analysis. No implicit purge.
    from ..models import RubricResult,RubricItem
    if RubricResult.query.join(RubricItem,RubricResult.rubric_item_id==RubricItem.id).filter(RubricItem.rubric_id==item.id).first():return api_error('RESOURCE_IN_USE','분석에서 참조한 자료입니다.',409)
    filename=item.file.stored_name if item.file else None
    from .privacy_lifecycle import queue_files,ledger,retry_files
    ledger('rubric',identifier);queue_files([filename] if filename else [])
    db.session.delete(item);db.session.commit();pending=retry_files()
    return success({'deleted':pending==0,'filesPending':pending},status=202 if pending else 200)


@bp.delete('/quote-cards/<identifier>')
def delete_quote(identifier):
    item=db.session.get(QuoteCard,identifier)
    if not item or item.owner_id!=g.principal.id:abort(404,description='API resource unavailable')
    db.session.delete(item);db.session.commit();return success({'deleted':True})


@bp.post('/source-documents/<identifier>/ocr')
def source_ocr_disabled(identifier):
    from ..services.ocr_jobs import config
    if config():
        from .ocr_api import start_job
        return start_job(identifier)
    document(identifier,'VIEW')
    return api_error('OCR_NOT_APPROVED','텍스트 자료는 현재 추출 결과를 사용하세요. 스캔 OCR은 별도 승인 범위입니다.',409)


@bp.delete('/source-documents/<identifier>')
def remove_document(identifier):
    item=document(identifier);editable(item,'DELETE')
    # Revision history used by any run is immutable and remains available.
    used=EssayDocument.query.join(DocumentRevision,EssayDocument.revision_id==DocumentRevision.id).filter(DocumentRevision.document_id==identifier).first()
    from ..models import Analysis
    referenced=any(any(x.get('documentId')==identifier for x in (a.context_snapshot or {}).get('documents',[])) for a in Analysis.query.filter(Analysis.context_snapshot.is_not(None)))
    if used or referenced or QuoteCard.query.filter_by(document_id=identifier).first():return api_error('RESOURCE_IN_USE','참조 중인 문서 revision은 삭제하지 않습니다.',409)
    db.session.query(WorkDocument).filter_by(document_id=identifier).delete()
    files=[item.stored_name]
    from ..services.ocr_jobs import derived_files_for_delete
    files+=derived_files_for_delete(item)
    for revision in DocumentRevision.query.filter_by(document_id=identifier).order_by(DocumentRevision.revision_number.desc()).all():
        if revision.file_ref:files.append(revision.file_ref)
        db.session.delete(revision);db.session.flush()
    from .privacy_lifecycle import queue_files,ledger,retry_files
    ledger('document',identifier,scope=item.scope);queue_files(files)
    db.session.delete(item);db.session.commit();pending=retry_files()
    return success({'deleted':pending==0,'filesPending':pending},status=202 if pending else 200)
