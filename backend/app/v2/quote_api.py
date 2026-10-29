from flask import Blueprint,g,abort,current_app
from ..extensions import db
from ..models import SourceDocument,DocumentRevision,Workspace,WorkspaceSetting
from ..seed import DEFAULT_SETTINGS
from ..utils import success,api_error,json_body
from components.quote_match import SelectedRevision,match_quote,require_revision_access,canonical_revision_text
from .library_api import document,revision_for,workspace
from .analysis_api import source_analysis_enabled

bp=Blueprint('v2_quote',__name__,url_prefix='/api')


def selected(revision,source):
    return SelectedRevision(revision.id,source.id,source.owner_id,source.scope,source.access_mode,bool(source.rights_confirmed),revision.content)


@bp.post('/source-documents/<identifier>/search')
def search(identifier):
    source=document(identifier);data,error=json_body()
    if error:return error
    if not isinstance(data.get('revisionId'),str):return api_error('REVISION_REQUIRED','선택한 판본 revision ID가 필요합니다.')
    revision=revision_for(source,data['revisionId']);current=workspace()
    setting=WorkspaceSetting.query.filter_by(workspace_id=current.id,key='quoteSimilarityThreshold').first()
    threshold=setting.value if setting else DEFAULT_SETTINGS['quoteSimilarityThreshold']
    quote=data.get('quote');quoted=False
    if source_analysis_enabled():
        if not match_budget(g.principal.id,source):return api_error('MATCH_RATE_LIMIT','잠시 후 다시 대조해 주세요.',429)
        from ..analysis.quotation import extract_quotations
        ranges=extract_quotations(quote) if isinstance(quote,str) else []
        if len(ranges)==1 and ranges[0].start==0 and ranges[0].end==len(quote):quote=ranges[0].text;quoted=True
        if source.access_mode=='MATCH_ONLY' and (not isinstance(quote,str) or len(quote.strip())<3):return api_error('QUOTE_TOO_SHORT','제한 자료는 3자 이상의 인용 구절을 사용해 주세요.')
    try:result=match_quote(g.principal,selected(revision,source),quote,minimum_similarity=threshold*100,quoted=quoted)
    except (TypeError,ValueError):return api_error('VALIDATION_ERROR','인용문과 검색 설정을 확인해 주세요.')
    db.session.commit();return success(result)

def match_budget(user_id,source):
    if source.access_mode!='MATCH_ONLY':return True
    import time,threading
    state=current_app.extensions.setdefault('v22_match_budget',{'lock':threading.Lock(),'requests':{}})
    with state['lock']:
        now=time.monotonic();key=(user_id,getattr(source,'document_id',source.id));count,until=state['requests'].get(key,(0,now+3600))
        if until<=now:count,until=0,now+3600
        if count>=60:return False
        # Bounded owner/document counters; old entries do not become a text cache.
        if len(state['requests'])>4096:state['requests']={k:v for k,v in state['requests'].items() if v[1]>now}
        state['requests'][key]=(count+1,until);return True


def selected_for_context(context,actor):
    import hashlib
    result=[]
    for ref in context['documents']:
        revision=db.session.get(DocumentRevision,ref['revisionId']);source=db.session.get(SourceDocument,ref['documentId'])
        if not revision or not source or revision.document_id!=source.id or revision.content_hash!=ref['sha256'] or hashlib.sha256(revision.content.encode()).hexdigest()!=ref['sha256']:raise ValueError('DOCUMENT_PROVENANCE_INVALID')
        # Reuse the matcher's exact permission gate without searching the source.
        from .privacy_lifecycle import document_expired
        if document_expired(source):raise ValueError('DOCUMENT_EXPIRED')
        pinned=(source.edition_metadata or {}).get('publication',{}).get('revisionId')
        if pinned and actor.id!=source.owner_id and revision.id!=pinned:raise ValueError('DOCUMENT_PROVENANCE_INVALID')
        candidate=selected(revision,source);require_revision_access(actor,candidate);canonical_revision_text(candidate)
        result.append(candidate)
    threshold=context['quoteSimilarityThreshold']
    return result,threshold*100


def quote_checks(body,result,selected_data,actor):
    selected_revisions,threshold=selected_data
    checks=[]
    for quote in result['quotations']:
        text=body[quote['contentStart']:quote['contentEnd']]
        if not text.strip():continue
        for revision in selected_revisions:
            if source_analysis_enabled():
                if revision.access_mode=='MATCH_ONLY' and len(text.strip())<3:
                    checks.append({'essaySpan':{'start':quote['contentStart'],'end':quote['contentEnd']},'revisionId':revision.id,'documentId':revision.document_id,'status':'QUOTE_TOO_SHORT','limitation':'대조 전용 자료는 대량 추출 방지를 위해 3자 이상의 인용만 확인합니다. 짧은 인용을 오류로 단정하지 않습니다.'});continue
                if not match_budget(actor.id,revision):
                    checks.append({'essaySpan':{'start':quote['contentStart'],'end':quote['contentEnd']},'revisionId':revision.id,'documentId':revision.document_id,'status':'MATCH_LIMIT_REACHED','limitation':'제한 자료의 반복 대조 한도에 도달했습니다. 로컬 분석은 유지됩니다.'});continue
            match=match_quote(actor,revision,text,minimum_similarity=threshold,quoted=source_analysis_enabled())
            match.pop('excerpt',None) # do not duplicate document source into stored analysis
            checks.append({'essaySpan':{'start':quote['contentStart'],'end':quote['contentEnd']},**match})
    return checks
