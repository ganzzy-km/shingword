"""Owner-only review of local OCR drafts; immutable revisions require confirmation."""
import hashlib
import io
import json
import math
from flask import Blueprint,g,abort,request,current_app,send_file
from ..extensions import db
from ..models import OcrRun,AppSetting,DocumentRevision,SourceDocument
from ..utils import success,api_error,json_body
from ..analysis.snapshot import normalize_text
from ..services import ocr_jobs as jobs
from .library_api import document,editable,revision_for

bp=Blueprint('v2_ocr',__name__,url_prefix='/api')


def owned_job(identifier):
    run,record=jobs.row(identifier)
    if not run:abort(404,description='API resource unavailable')
    item=document(run.target_id,'VIEW')
    # No automatic ADMIN access to private text, nor public visitor review rights.
    if item.owner_id!=g.principal.id or record.value['owner']!=g.principal.id:abort(404,description='API resource unavailable')
    if item.scope=='PUBLIC':editable(item)
    return item,run,record


def public_job(run,record):
    value=record.value
    pages=[]
    for page in value['pages']:
        number=str(page['page']);draft=value['drafts'].get(number,page['draft']['text'])
        pages.append({'page':page['page'],'width':page['width'],'height':page['height'],
                      'imageUrl':f'/api/ocr-jobs/{run.id}/pages/{page["page"]}/image',
                      'lines':page['lines'],'draft':draft,'recognizedText':page['draft']['text'],'geometry':page['geometry'],'structure':page['structure'],
                      'unavailable':page.get('unavailable',[]),'calls':page['calls'],'seconds':page['seconds'],'modelVersions':page.get('modelVersions',{}),'literary':page.get('literary'),'localRefinement':page.get('localRefinement'),'precision':page.get('precision'),'preprocessing':page.get('preprocessing'),'lineMap':page['draft'].get('lineMap',[])})
    return {'id':run.id,'documentId':run.target_id,'status':run.status,'error':run.error_message,
            'operation':value['operation'],'inputRevisionId':value['inputRevisionId'],'draftVersion':value['draftVersion'],
            'completedPages':value['completedPages'],'totalPages':value['totalPages'],'pages':pages,
            'alternative':value.get('alternative'),'confirmedRevisionId':value.get('confirmedRevisionId'),'timing':value.get('timing'),
            'peakWorkerBytes':value.get('peakWorkerBytes'),'seconds':value.get('seconds'),'ocrMode':value.get('ocrMode','precise'),'ocrProfile':value.get('ocrProfile','auto'),'modelManifestSha':value.get('modelManifestSha'),
            'engines':{'paddle':'korean_PP-OCRv5_mobile_rec','detector':'PP-OCRv5_mobile_det'} if value.get('ocrMode')=='standard' else {'paddle':'korean_PP-OCRv5_mobile_rec','tesseract':'kor+eng tessdata_best','structure':'PP-StructureV3','vl':'PaddleOCR-VL-0.9B (선택 영역)'}}


@bp.get('/ocr-jobs/<identifier>')
def get_job(identifier):
    _,run,record=owned_job(identifier);jobs.kick();return success(public_job(run,record))


@bp.get('/source-documents/<identifier>/ocr')
def get_document_job(identifier):
    item=document(identifier,'VIEW')
    if item.owner_id!=g.principal.id:abort(404)
    run=next((r for r in OcrRun.query.filter_by(target_type='source-v2',target_id=item.id).order_by(OcrRun.created_at.desc()) if jobs.row(r.id)[1] and jobs.row(r.id)[1].value['operation']=='document'),None)
    if not run:abort(404)
    return get_job(run.id)


def start_job(identifier):
    item=document(identifier,'VIEW')
    if item.owner_id!=g.principal.id:abort(404)
    editable(item);data,error=json_body()
    if error:return error
    mode=data.get('ocrMode','precise');profile=data.get('ocrProfile','auto')
    if mode=='standard':return api_error('OCR_MODE_RETIRED','새 작업은 고정밀 OCR로 시작해 주세요.',400)
    from ..services.ocr_pipeline import LITERARY_PROFILES
    if set(data)-{'expectedRevisionId','table','ocrMode','ocrProfile'} or not isinstance(profile,str) or profile not in LITERARY_PROFILES or not isinstance(data.get('table',False),bool) or not isinstance(mode,str) or mode!='precise':return api_error('VALIDATION_ERROR','OCR 모드와 옵션을 확인해 주세요.')
    jobs.lock_document(item);latest=revision_for(item)
    if data.get('expectedRevisionId')!=latest.id:db.session.rollback();return api_error('REVISION_CONFLICT','현재 판본을 다시 확인해 주세요.',409)
    existing=next((r for r in OcrRun.query.filter_by(target_type='source-v2',target_id=item.id).order_by(OcrRun.created_at.desc()) if jobs.row(r.id)[1] and jobs.row(r.id)[1].value['operation']=='document'),None)
    if existing and existing.status=='CONFIRMED':
        prior=jobs.row(existing.id)[1].value
        if prior.get('confirmedRevisionId')==latest.id and prior['fingerprint']==jobs.config()['fingerprint'] and prior['table']==data.get('table',False) and prior.get('ocrMode','precise')==mode and prior.get('ocrProfile','auto')==profile:
            db.session.commit();return get_job(existing.id)
    if existing and existing.status in jobs.ACTIVE and (jobs.row(existing.id)[1].value.get('ocrMode','precise')!=mode or jobs.row(existing.id)[1].value.get('ocrProfile','auto')!=profile):
        db.session.rollback();return api_error('OCR_MODE_CONFLICT','진행 중인 작업이 끝난 뒤 다른 모드로 비교해 주세요.',409)
    if existing and (existing.status in jobs.ACTIVE or (existing.status=='REVIEW_READY' and jobs.row(existing.id)[1].value['table']==data.get('table',False) and jobs.row(existing.id)[1].value.get('ocrMode','precise')==mode and jobs.row(existing.id)[1].value.get('ocrProfile','auto')==profile)):
        db.session.commit();return get_job(existing.id)
    try:run=jobs.create_job(item,latest.id,table=data.get('table',False),mode=mode,profile=profile)
    except jobs.OcrCapacityError:db.session.rollback();return api_error('OCR_BUSY','OCR 대기 한도에 도달했습니다.',429)
    except ValueError:db.session.rollback();return api_error('OCR_UNAVAILABLE','로컬 OCR 환경을 확인해 주세요.',503)
    if not (item.edition_metadata or {}).get('ocr',{}).get('confirmedRevisionId'):
        _,created=jobs.row(run.id)
        item.edition_metadata={**(item.edition_metadata or {}),'ocr':{'jobId':run.id,'confirmedRevisionId':latest.id if latest.content.strip() else None,'retentionDeadline':created.value.get('retentionDeadline'),'ocrMode':mode,'ocrProfile':profile}}
    db.session.commit();jobs.kick();return success({'id':run.id,'status':run.status},status=202)


@bp.get('/ocr-jobs/<identifier>/pages/<int:number>/image')
def page_image(identifier,number):
    _,run,record=owned_job(identifier)
    page=next((p for p in record.value['pages'] if p['page']==number),None)
    if not page:abort(404)
    path=jobs.local_file(page['imageFile'])
    if not path.is_file():abort(404)
    response=send_file(path,mimetype='image/png');response.headers['Cache-Control']='private, no-store';return response


@bp.patch('/ocr-jobs/<identifier>/draft')
def save_draft(identifier):
    item,run,record=owned_job(identifier);data,error=json_body()
    if error:return error
    if set(data)!={'expectedDraftVersion','pages'} or not isinstance(data['expectedDraftVersion'],int) or isinstance(data['expectedDraftVersion'],bool) or not isinstance(data['pages'],dict):return api_error('VALIDATION_ERROR','검수 페이지와 버전을 확인해 주세요.')
    jobs.lock_document(item);db.session.refresh(record);db.session.refresh(run)
    if run.status!='REVIEW_READY':db.session.rollback();return api_error('OCR_STATE_CONFLICT','검수 가능한 작업이 아닙니다.',409)
    value=record.value
    if value['draftVersion']!=data['expectedDraftVersion']:db.session.rollback();return api_error('DRAFT_CONFLICT','다른 화면에서 수정되었습니다. 입력을 보존하고 최신 초안을 확인해 주세요.',409)
    valid={str(p['page']) for p in value['pages']}
    if set(data['pages'])-valid or any(not isinstance(t,str) or len(t)>200000 for t in data['pages'].values()) or sum(len(t.encode()) for t in data['pages'].values())>2*1024*1024:
        db.session.rollback();return api_error('VALIDATION_ERROR','페이지 내용의 크기와 번호를 확인해 주세요.')
    record.value={**value,'drafts':{**value['drafts'],**data['pages']},'draftVersion':value['draftVersion']+1};db.session.commit()
    return success(public_job(run,record))


@bp.post('/ocr-jobs/<identifier>/confirm')
def confirm(identifier):
    item,run,record=owned_job(identifier);data,error=json_body()
    if error:return error
    if set(data)!={'expectedDraftVersion','expectedRevisionId'}:return api_error('VALIDATION_ERROR','검수 버전과 판본을 확인해 주세요.')
    jobs.lock_document(item);db.session.refresh(record);db.session.refresh(run);value=record.value
    if run.status=='CONFIRMED' and value.get('confirmedRevisionId'):
        db.session.commit();return success({'revisionId':value['confirmedRevisionId'],'idempotent':True})
    if run.status!='REVIEW_READY' or value['operation']!='document' or not jobs.valid(run,value):db.session.rollback();return api_error('OCR_STATE_CONFLICT','확정할 수 없는 작업입니다.',409)
    latest=revision_for(item)
    if value['draftVersion']!=data['expectedDraftVersion'] or latest.id!=data['expectedRevisionId'] or latest.id!=value['inputRevisionId']:
        db.session.rollback();return api_error('REVISION_CONFLICT','초안 또는 원문 판본이 변경되었습니다.',409)
    if hashlib.sha256(jobs.local_file(item.stored_name).read_bytes()).hexdigest()!=value['inputSha']:
        db.session.rollback();return api_error('INPUT_CHANGED','원본 파일 무결성을 확인해 주세요.',409)
    pieces=[];offset=0;mapping=[]
    for page in value['pages']:
        text=normalize_text(value['drafts'].get(str(page['page']),page['draft']['text']))
        pieces.append(text);unchanged=text==page['draft']['text']
        mapping.append({'page':page['page'],'span':[offset,offset+len(text)],'lineMap':page['draft']['lineMap'] if unchanged else None,'mappingStatus':'ORIGINAL_LINES' if unchanged else 'USER_EDITED_NO_GUESSED_MAPPING'})
        offset+=len(text)+2
    text='\n\n'.join(pieces)
    if not text.strip():db.session.rollback();return api_error('EMPTY_TEXT','원문을 확인하고 빈 페이지 여부를 검토해 주세요.')
    revision=DocumentRevision(document_id=item.id,parent_id=latest.id,revision_number=latest.revision_number+1,content=text,content_hash=hashlib.sha256(text.encode()).hexdigest(),file_ref=item.stored_name)
    db.session.add(revision);db.session.flush()
    record.value={**value,'confirmedRevisionId':revision.id,'confirmedTextHash':revision.content_hash,'confirmedMapping':mapping}
    run.status='CONFIRMED';item.status='등록 완료'
    item.edition_metadata={**(item.edition_metadata or {}),'ocr':{'jobId':run.id,'confirmedRevisionId':revision.id,'inputSha':value['inputSha'],'fingerprint':value['fingerprint'],'reviewedBy':g.principal.id,'retentionDeadline':value.get('retentionDeadline'),'ocrMode':value.get('ocrMode','precise'),'ocrProfile':value.get('ocrProfile','auto')}}
    db.session.commit();return success({'revisionId':revision.id,'revisionNumber':revision.revision_number},status=201)


@bp.post('/ocr-jobs/<identifier>/region')
def region(identifier):
    item,run,record=owned_job(identifier);data,error=json_body()
    if error:return error
    if set(data)!={'page','box','engine'} or not isinstance(data['engine'],str) or data['engine'] not in {'paddle','tesseract','tesseract-line','vl'} or not isinstance(data['page'],int) or isinstance(data['page'],bool) or not isinstance(data['box'],list) or len(data['box'])!=4:return api_error('VALIDATION_ERROR','페이지·선택 영역·엔진을 확인해 주세요.')
    if run.status!='REVIEW_READY':return api_error('OCR_STATE_CONFLICT','검수 중에만 영역을 재인식할 수 있습니다.',409)
    if record.value.get('ocrMode','precise')=='standard' and data['engine']!='paddle':return api_error('OCR_MODE_ENGINE','일반 OCR은 경량 Paddle 인식만 사용합니다.',400)
    page=next((p for p in record.value['pages'] if p['page']==data['page']),None);box=data['box']
    if not page or any(not isinstance(n,(int,float)) or isinstance(n,bool) or not math.isfinite(n) for n in box) or not 0<=box[0]<box[2]<=page['width'] or not 0<=box[1]<box[3]<=page['height'] or (box[2]-box[0])*(box[3]-box[1])>1_500_000:return api_error('REGION_LIMIT','원본 안의 작은 영역을 선택해 주세요.')
    jobs.lock_document(item)
    existing=OcrRun.query.filter_by(target_type='source-v2',target_id=item.id).all()
    for old in existing:
        _,meta=jobs.row(old.id)
        if old.status in jobs.ACTIVE and meta.value.get('parent')==run.id:
            if meta.value['box']=={'page':data['page'],'rect':box} and meta.value['engine']==data['engine']:
                db.session.commit();return success({'id':old.id,'status':old.status},status=202)
            db.session.rollback();return api_error('OCR_BUSY','현재 선택 영역의 재인식이 끝난 뒤 다시 요청해 주세요.',409)
    try:
        if data['engine']=='vl' and not jobs.vl_admission()['allowed']:
            db.session.rollback();return api_error('OCR_RESOURCE_BUSY','VL은 메모리 여유와 S4 실행 예산이 확인될 때만 실행할 수 있습니다. 원본과 초안은 보존됩니다.',503)
        child=jobs.create_job(item,record.value['inputRevisionId'],operation='region',parent=run.id,box={'page':data['page'],'rect':box},engine=data['engine'],mode=record.value.get('ocrMode','precise'),profile=record.value.get('ocrProfile','auto'))
    except jobs.OcrCapacityError:db.session.rollback();return api_error('OCR_BUSY','OCR 대기 한도에 도달했습니다.',429)
    except ValueError:db.session.rollback();return api_error('OCR_UNAVAILABLE','로컬 OCR 환경을 확인해 주세요.',503)
    db.session.commit();jobs.kick();return success({'id':child.id,'status':child.status},status=202)


@bp.post('/ocr-jobs/<identifier>/cancel')
def cancel(identifier):
    item,run,record=owned_job(identifier);jobs.lock_document(item)
    if run.status not in jobs.ACTIVE:db.session.rollback();return api_error('OCR_STATE_CONFLICT','실행 중인 작업만 취소할 수 있습니다.',409)
    jobs.local_file(record.value['prefix']+'-cancel').touch();run.status='CANCELLED';db.session.commit();return success({'status':'CANCELLED'})


@bp.post('/ocr-jobs/<identifier>/retry')
def retry(identifier):
    item,run,record=owned_job(identifier);jobs.lock_document(item)
    if run.status not in {'FAILED','failed','interrupted','CANCELLED'} or not jobs.valid(run,record.value):db.session.rollback();return api_error('OCR_STATE_CONFLICT','재개 가능한 작업이 아닙니다.',409)
    attempts=record.value.get('retries',0)
    if attempts>=2:db.session.rollback();return api_error('RETRY_LIMIT','자동 재처리 한도에 도달했습니다. 원본과 완료 페이지는 보존됩니다.',409)
    jobs.local_file(record.value['prefix']+'-cancel').unlink(missing_ok=True)
    record.value={**record.value,'retries':attempts+1};run.status='queued';run.error_message=None;db.session.commit();jobs.kick()
    return success({'id':run.id,'status':run.status},status=202)


@bp.get('/ocr-jobs/<identifier>/export/<kind>')
def export(identifier,kind):
    item,run,record=owned_job(identifier);document(item.id,'DOWNLOAD')
    if run.status!='CONFIRMED' or kind not in {'txt','json'}:abort(404)
    value=record.value;revision=revision_for(item,value['confirmedRevisionId'])
    if kind=='txt':body=revision.content.encode('utf-8');mime='text/plain; charset=utf-8'
    else:
        body=json.dumps({'revisionId':revision.id,'contentHash':revision.content_hash,'text':revision.content,'pages':value['pages'],'mapping':value['confirmedMapping'],'inputSha':value['inputSha'],'modelFingerprint':value['fingerprint'],'ocrMode':value.get('ocrMode','precise'),'modelManifestSha':value.get('modelManifestSha')},ensure_ascii=False).encode('utf-8');mime='application/json'
    response=send_file(io.BytesIO(body),as_attachment=True,download_name='ocr-confirmed.'+kind,mimetype=mime);response.headers['Cache-Control']='private, no-store';return response
