import threading
import time
from datetime import datetime,timezone
from flask import Blueprint,current_app,g,abort
from ..extensions import db
from ..models import Writing,WritingVersion,Analysis,AnalysisJob,User
from ..analysis.snapshot import analyze_snapshot,validate_snapshot,_source_manifest,SCHEMA_VERSION,ENGINE_VERSION
from ..analysis.ruleset import local_findings,catalogue,ruleset_hash,RULESET_VERSION
from ..models import AppSetting,EssayDocument,DocumentRevision,SourceDocument,WorkDocument,Work,WorkspaceSetting,Workspace,FeedbackReaction
from ..analysis.structure import analyze_structure,prepare_relation_sources
from ..analysis.norms_catalogue import catalogue_manifest,provision_index,provision_reference
from ..services.analysis_service import executor  # reuse existing two-worker executor
from ..utils import success,api_error,json_body
from .common import owned_writing,iso
from .essays import freeze_version,SaveConflict

bp=Blueprint('v2_analysis',__name__,url_prefix='/api')
capacity=threading.BoundedSemaphore(32)  # bound pending IDs, not a new task engine


def source_analysis_enabled():
    return current_app.config.get('GEULBIT_V22') is True or current_app.config.get('GEULBIT_S4_ENGINE') is True


def analyze_input(text,version_id,context):
    return analyze_structure(text,version_id=version_id,disabled_rules=context['disabledRules'],vocabulary=context['vocabulary'],source_information=context.get('_relationSources'))


def context_for(item):
    setting=db.session.get(AppSetting,'disabled_rules');disabled=setting.value if setting else []
    if not isinstance(disabled,list) or not all(isinstance(x,str) and x in {r['rule_id'] for r in catalogue()} for x in disabled):raise ValueError('RULE_CONFIGURATION_INVALID')
    from .library_api import document,revision_for
    documents=[];vocabulary=set()
    for link in EssayDocument.query.filter_by(writing_id=item.id):
        revision=db.session.get(DocumentRevision,link.revision_id);source=document(revision.document_id)
        revision_for(source,revision.id)
        documents.append({'revisionId':revision.id,'documentId':source.id,'sha256':revision.content_hash,'accessMode':source.access_mode,'scope':source.scope})
        if source_analysis_enabled():
            associated=Work.query.join(WorkDocument,WorkDocument.work_id==Work.id).filter(WorkDocument.document_id==source.id).order_by(Work.id).all()
            associated=[w for w in associated if w.owner_id==g.principal.id or w.scope=='PUBLIC']
            documents[-1]['workMetadata']=[{'workId':w.id,'title':w.title,'author':w.author,'genre':w.genre,'aliases':getattr(w,'aliases',None) or []} for w in associated]
            documents[-1]['edition']=source.edition;documents[-1]['editionMetadata']=source.edition_metadata or {}
        for association in WorkDocument.query.filter_by(document_id=source.id):
            work=db.session.get(Work,association.work_id)
            if work and (work.owner_id==g.principal.id or work.scope=='PUBLIC'):vocabulary.update(work.vocabulary or [])
    from ..seed import DEFAULT_SETTINGS
    private_workspace=Workspace.query.filter_by(owner_id=g.principal.id).first()
    threshold=WorkspaceSetting.query.filter_by(workspace_id=private_workspace.id,key='quoteSimilarityThreshold').first() if private_workspace else None
    essay_context={'work':item.work,'inquiryQuestion':item.inquiry_question}
    if source_analysis_enabled():essay_context['title']=item.title
    return {'documents':sorted(documents,key=lambda x:x['revisionId']),'essayContext':essay_context,'disabledRules':sorted(set(disabled)),'vocabulary':sorted(vocabulary),'rulesetHash':ruleset_hash(),'rulesetVersion':RULESET_VERSION,'normsCatalogue':catalogue_manifest(),'quoteSimilarityThreshold':threshold.value if threshold else DEFAULT_SETTINGS['quoteSimilarityThreshold']}


def available(item):
    user=db.session.get(User,item.owner_id) if item else None
    return bool(item and user and user.status=='ACTIVE' and (not item.expires_at or item.expires_at.replace(tzinfo=timezone.utc)>datetime.now(timezone.utc)))


def run_job(app,job_id):
    with app.app_context():
        try:
            job=db.session.get(AnalysisJob,job_id)
            if not job:return
            run=db.session.get(Analysis,job.analysis_id);item=db.session.get(Writing,run.writing_id)
            if job.cancel_requested or not available(item):
                job.status=run.status='cancelled';job.current_step='실행 취소';db.session.commit();return
            version=db.session.get(WritingVersion,run.essay_version_id)
            body=version.content;vid=version.id;context=run.context_snapshot
            from .quote_api import selected_for_context,quote_checks
            from .common import principal
            actor=principal(db.session.get(User,item.owner_id));selected=selected_for_context(context,actor)
            job.status=run.status='running';job.progress=10;job.current_step='로컬 분석';db.session.commit()
            # Release connection/read transaction before CPU work.
            source_inputs=[]
            if source_analysis_enabled():
                for ref,candidate in zip(context['documents'],selected[0]):
                    meta=(ref.get('workMetadata') or [{'title':'자료','author':'','genre':'기타'}])[0]
                    source_inputs.append({'revisionId':candidate.id,'documentId':candidate.document_id,'text':candidate.text,'accessMode':candidate.access_mode,'revisionHash':ref['sha256'],'edition':ref.get('edition',''),'editionMetadata':ref.get('editionMetadata',{}),**meta})
            db.session.remove();started=time.monotonic();prepared_checks=None;analysis_context=context
            if source_analysis_enabled():
                from ..analysis.quotation import extract_quotations
                # Reuse the exact parser/matcher once, before relationship work.
                quote_input={'quotations':[{'contentStart':q.content_start,'contentEnd':q.content_end} for q in extract_quotations(body)]}
                prepared_checks=quote_checks(body,quote_input,selected,actor)
                analysis_context={**context,'_relationSources':prepare_relation_sources(body,context['documents'],prepared_checks)}
            result=analyze_input(body,vid,analysis_context)
            result['quoteChecks']=prepared_checks if prepared_checks is not None else quote_checks(body,result,selected,actor)
            if source_analysis_enabled():
                from ..analysis.source_context import source_context
                result['sourceContext']=source_context(body,result,source_inputs,result['quoteChecks'])
                if app.config.get('GEULBIT_V22'):
                    from .dictionary_support import verify_findings
                    result['dictionarySupport']=verify_findings(body,result)
            validate_snapshot(result,body,version_id=vid)
            timeout=app.config.get('ANALYSIS_TIMEOUT_SECONDS',120)
            if type(timeout) not in (int,float) or timeout<=0 or time.monotonic()-started>timeout:raise TimeoutError()
            job=db.session.get(AnalysisJob,job_id)
            if not job:return  # an approved cleanup may have removed the job
            run=db.session.get(Analysis,job.analysis_id);item=db.session.get(Writing,run.writing_id)
            if job.cancel_requested or not available(item):
                job.status=run.status='cancelled';job.current_step='실행 취소';db.session.commit();return
            selected_for_context(context,actor)  # recheck document expiry after CPU work
            run.result_snapshot=result;run.metrics={'문장 수':{'value':len(result['sentences']),'calculable':True,'description':'확정된 버전에서 처리한 문장 수입니다. 평가 점수가 아닙니다.'}}
            run.status='completed';run.completed_at=datetime.now(timezone.utc)
            job.status='completed';job.progress=100;job.current_step='분석 완료';job.completed_steps=['확정 버전','Kiwi','결과 검증']
            db.session.commit()
        except Exception as error:
            db.session.rollback()
            job=db.session.get(AnalysisJob,job_id)
            if job:
                run=db.session.get(Analysis,job.analysis_id)
                if run and run.result_snapshot is None:
                    run.status=job.status='failed';job.error_message='분석 시간 제한을 초과했습니다.' if isinstance(error,TimeoutError) else '로컬 분석에 실패했습니다. 이전 성공 결과는 보존됩니다.'
                    job.current_step='분석 실패';db.session.commit()
            app.logger.error('Analysis failed: %s',type(error).__name__)


@bp.post('/analyses')
def create_analysis():
    data,error=json_body()
    if error:return error
    item=owned_writing(data.get('writingId'))
    if not isinstance(data.get('content'),str) or not data['content'].strip():return api_error('VALIDATION_ERROR','현재 편집 본문과 revisionNumber를 전송해 주세요.')
    if not capacity.acquire(blocking=False):return api_error('ANALYSIS_BUSY','분석 대기열이 가득 찼습니다. 잠시 후 다시 시도해 주세요.',429)
    try:
        version=freeze_version(item,{'content':data['content'],'revisionNumber':data.get('revisionNumber')})
        context=context_for(item)
        run=Analysis(writing_id=item.id,essay_version_id=version.id,status='queued',analysis_types=['전체 분석'],context_snapshot=context,input_manifest={'input':{'versionId':version.id,'sha256':version.snapshot_hash,'codePoints':len(version.content)},'engine':_source_manifest(),'context':context},schema_version=SCHEMA_VERSION,engine_version=ENGINE_VERSION,ruleset_hash=context.get('rulesetHash'))
        db.session.add(run);db.session.flush();job=AnalysisJob(analysis_id=run.id,status='queued');db.session.add(job);db.session.commit()
        ids={'analysisId':run.id,'jobId':job.id,'status':'queued','essayVersionId':version.id,'revisionNumber':item.revision_number}
        app=current_app._get_current_object()
        if app.testing and app.config.get('ANALYSIS_SYNCHRONOUS'):
            run_job(app,job.id);capacity.release()
        else:
            try:
                future=executor.submit(run_job,app,job.id);future.add_done_callback(lambda _f:capacity.release())
            except Exception:
                job.status=run.status='failed';job.error_message='실행 준비 실패';db.session.commit()
                raise
        return success(ids,status=202)
    except SaveConflict:
        db.session.rollback();capacity.release();return api_error('SAVE_CONFLICT','현재 초안 revision이 변경되었습니다.',409)
    except (ValueError,TypeError):
        db.session.rollback();capacity.release();return api_error('VALIDATION_ERROR','분석 입력을 확인해 주세요.')
    except Exception:
        db.session.rollback();capacity.release();raise


def owned_run(identifier,*,saved_read=False):
    run=db.session.get(Analysis,identifier)
    if not run or not run.essay_version_id:abort(404,description='API resource unavailable')
    owned_writing(run.writing_id)
    from .privacy_lifecycle import document_expired
    for ref in (run.context_snapshot or {}).get('documents',[]):
        source=db.session.get(SourceDocument,ref.get('documentId'))
        from .library_api import allowed_metadata
        if not source or not allowed_metadata(source):
            # A stored analysis belongs to its writer. Withdrawal of a formerly
            # public document revokes fresh source use, not this saved result.
            # All other consumers retain current source access checks.
            withdrawn_public=bool(saved_read and run.status=='completed' and source and ref.get('scope')=='PUBLIC' and source.scope=='PRIVATE' and not document_expired(source))
            if not withdrawn_public:abort(404,description='API resource unavailable')
    return run


def argument_view(run,version,body,result):
    # Old snapshots retain their original evidence. Nearest-following legacy
    # relations cannot silently become validated links in the new UI.
    nodes=[];ids={}
    for c in result.get('roleCandidates',[]):
        roles=[r for r in c.get('roles',[]) if r in ('CLAIM_CANDIDATE','EVIDENCE_CANDIDATE')]
        if not roles:continue
        identifier=run.id+':role:'+c['id'];ids[c['id']]=identifier
        nodes.append({'id':identifier,'analysisRunId':run.id,'essayVersionId':version.id,
            'sentenceNumber':c['sentenceNumber'],'span':{'start':c['start'],'end':c['end']},
            'quote':body[c['start']:c['end']],'roles':roles,'scores':c['scores'],
            'signals':c['claimSignals']+c['evidenceTypes']})
    links=[]
    for r in result.get('relations',[]):
        if r.get('assessment')!='SUFFICIENT_SIGNALS':continue
        if r.get('interpretation')!='STRUCTURAL_SUPPORT_CANDIDATE_NOT_LOGICAL_VALIDITY' or r.get('claimId') not in ids or r.get('evidenceId') not in ids:continue
        links.append({**r,'id':run.id+':'+r['id'],'claimId':ids[r['claimId']],'evidenceId':ids[r['evidenceId']],
            'analysisRunId':run.id,'essayVersionId':version.id,
            'claimSentenceId':run.id+':s'+str(r['claimSentence']),'evidenceSentenceId':run.id+':s'+str(r['evidenceSentence']),
            'claimText':body[r['claimSpan']['start']:r['claimSpan']['end']],
            'evidenceText':body[r['evidenceSpan']['start']:r['evidenceSpan']['end']],
            'status':'확인 필요','details':{'signals':r['signals'],'scoreMeaning':'STRUCTURAL_SIGNAL_COUNT_NOT_PROBABILITY'}})
    for link in links:
        span=(link.get('followingExplanation') or {}).get('span')
        if span:link['explanationText']=body[span['start']:span['end']]
    return {'argumentCandidates':nodes,'argumentLinks':links,'structureVersion':result.get('manifest',{}).get('structureVersion')}


def run_data(run):
    version=db.session.get(WritingVersion,run.essay_version_id);item=owned_writing(run.writing_id)
    result=run.result_snapshot or {};body=version.content
    findings=[]
    reactions={r.feedback_id:r.action for r in FeedbackReaction.query.filter_by(user_id=g.principal.id,analysis_id=run.id)}
    for i,f in enumerate(result.get('findings',[])):
        findings.append({'id':run.id+':'+str(i),'type':'expression' if f.get('category')=='expression' else 'spelling' if 'ruleId' in f else 'argument','severity':'error' if f.get('tier')=='오류 후보' else 'warning','title':f.get('tier','확인 필요'),'current':body[f['start']:f['end']],'reason':f['reason'],'suggestion':f.get('suggestion'),'rule':f.get('ruleId'),'sourceUrl':f.get('source',{}).get('url'),'startOffset':f['start'],'endOffset':f['end'],'status':reactions.get(run.id+':'+str(i),'open'),'metadata':{'essayVersionId':version.id,'tier':f.get('tier'),'autoApply':False}})
    for rendered,raw in zip(findings,result.get('findings',[])):
        rendered['metadata'].update(selectionPolicy=raw.get('selectionPolicy'),alternatives=raw.get('alternatives',[]))
        if raw.get('tier')=='표현 제안':rendered['severity']='info'
    quote_labels={'EXACT_MATCH':'선택한 판본에서 일치 구간 발견','NORMALIZED_MATCH':'선택한 판본에서 정규화 일치 구간 발견','SIMILAR_DIFFERENCE_CANDIDATE':'유사하지만 차이가 있는 구간 발견','NOT_FOUND_IN_SELECTED_REVISION':'선택한 판본에서 발견하지 못함'}
    quote_labels.update({'OMISSION_MATCH':'생략 인용 구간과 순서 일치','OMISSION_SIMILAR_CANDIDATE':'표현이 다른 생략 인용 후보','OMISSION_ORDER_MISMATCH':'선택 판본에서 인용 순서 확인 필요','PARTIAL_OMISSION_CANDIDATE':'생략 인용 일부만 확인됨','MATCH_LIMIT_REACHED':'반복 대조 한도 도달'})
    quote_labels['QUOTE_TOO_SHORT']='대조 전용 자료의 짧은 인용 확인 제한'
    for q in result.get('quoteChecks',[]):
        span=q['essaySpan'];fid=run.id+':'+str(len(findings))
        findings.append({'id':fid,'type':'quotation','severity':'info','title':quote_labels[q['status']],'current':body[span['start']:span['end']],'reason':q['limitation'],'startOffset':span['start'],'endOffset':span['end'],'status':reactions.get(fid,'open'),'metadata':{'essayVersionId':version.id,'documentId':q['documentId'],'revisionId':q['revisionId'],'sourceSpan':q.get('sourceSpan'),'autoApply':False}})
    candidates={s['sentenceNumber']:s for s in result.get('roleCandidates',[])}
    sentences=[{'id':run.id+':s'+str(s['number']),'paragraphNumber':s['paragraph'],'sentenceNumber':s['number'],'text':body[s['start']:s['end']],'startOffset':s['start'],'endOffset':s['end'],'autoRole':'분류되지 않음','rationale':'역할은 후보 단서이며 확정 분류가 아닙니다.','candidates':candidates.get(s['number'])} for s in result.get('sentences',[])]
    return {'id':run.id,'writingId':run.writing_id,'essayVersionId':version.id,'status':run.status,'createdAt':iso(run.created_at),'completedAt':iso(run.completed_at),'sourceVersion':{'id':version.id,'content':body,'sha256':version.snapshot_hash},'writing':{'title':item.title,'work':item.work,'inquiryQuestion':item.inquiry_question},'metrics':run.metrics or {},'disclaimer':' '.join(result.get('limitations',[])) or run.disclaimer,'sentences':sentences,'findings':findings,**argument_view(run,version,body,result),'relationCandidates':result.get('relations',[]),'peelResults':[],'details':{},'result':result,'inputManifest':run.input_manifest,'contextSnapshot':run.context_snapshot}


@bp.get('/analyses/<identifier>')
def get_analysis(identifier):return success(run_data(owned_run(identifier,saved_read=True)))


@bp.get('/analysis-jobs/<identifier>')
def get_job(identifier):
    job=db.session.get(AnalysisJob,identifier)
    if not job:abort(404,description='API resource unavailable')
    owned_run(job.analysis_id)
    return success({'id':job.id,'analysisId':job.analysis_id,'status':job.status,'progress':job.progress,'currentStep':job.current_step,'errorMessage':job.error_message,'completedSteps':job.completed_steps})


@bp.post('/analysis-jobs/<identifier>/cancel')
def cancel(identifier):
    job=db.session.get(AnalysisJob,identifier)
    if not job:abort(404,description='API resource unavailable')
    owned_run(job.analysis_id)
    if job.status not in {'queued','running','cancel_requested'}:return api_error('INVALID_STATE','종료된 실행입니다.',409)
    job.cancel_requested=True;db.session.commit();return success({'status':'cancel_requested'})


@bp.get('/rules')
def rules():
    disabled=(db.session.get(AppSetting,'disabled_rules').value if db.session.get(AppSetting,'disabled_rules') else [])
    output=[]
    for r in catalogue():
        primary=r['source']['primaryReference']
        output.append({'id':r['rule_id'],'name':r['title'],'categoryLabel':r['categoryLabel'],
            'scope':r['scope'],'active':r['rule_id'] not in disabled,'version':r['version'],
            'pattern':r['condition'],'replacement':r['suggestion'],
            # Catalogue positive/negative mean detector hits/non-hits, not grammatical correctness.
            'incorrectExamples':r['positive_examples'],'correctExamples':r['negative_examples'],
            'exceptionExamples':r['exception_examples'],'primaryReference':primary,
            'status':'비활성' if r['rule_id'] in disabled else r['tier'],'explanation':r['reason'],
            'clause':r['source']['legacyCaption'],'autoFixable':False,'contextRequired':True,
            'source':{'name':'로컬 표현 검토 · 규범 오류 아님' if r['category']=='expression' else '국립국어원 규범·해설 기반 제공 자료집' if primary else ('국립국어원' if r['source']['url'] else '출처 대조가 필요한 로컬 후보'),
                'url':r['source']['url'] or '', 'checkedAt':r['source']['verifiedAt']},'catalogue':r})
    return success(output)


@bp.get('/rules/reference')
def rules_reference_index():
    return success({'manifest':catalogue_manifest(),'provisions':provision_index()})


@bp.get('/rules/reference/<identifier>')
def rules_reference_detail(identifier):
    try:return success(provision_reference(identifier))
    except ValueError:return api_error('NOT_FOUND','규정을 찾을 수 없습니다.',404)


@bp.get('/dictionary/status')
def dictionary_status():return success({'status':'disabled','available':False,'notice':'로컬 분석은 외부 사전이나 AI 없이 동작합니다.','checkedAt':None})


@bp.post('/findings/<identifier>/actions')
def reaction(identifier):
    try:run_id,index=identifier.rsplit(':',1);index=int(index)
    except (ValueError,TypeError):abort(404,description='API resource unavailable')
    run=owned_run(run_id);findings=run_data(run)['findings']
    if index<0 or index>=len(findings):abort(404,description='API resource unavailable')
    data,error=json_body()
    if error:return error
    actions={'confirm':'confirmed','fixed':'fixed','ignore':'ignored','incorrect':'incorrect'}
    if data.get('action') not in actions:return api_error('VALIDATION_ERROR','반응을 확인해 주세요.')
    item=FeedbackReaction.query.filter_by(user_id=g.principal.id,analysis_id=run.id,feedback_id=identifier).first()
    if item:item.action=actions[data['action']]
    else:db.session.add(FeedbackReaction(user_id=g.principal.id,analysis_id=run.id,feedback_id=identifier,action=actions[data['action']]))
    db.session.commit();return success(run_data(run)['findings'][index])


@bp.post('/findings/<identifier>/apply')
def automatic_apply(identifier):
    try:run_id,_index=identifier.rsplit(':',1)
    except ValueError:abort(404,description='API resource unavailable')
    owned_run(run_id)
    return api_error('MANUAL_REVIEW_REQUIRED','제안은 직접 확인한 뒤 편집기에서 수정해 주세요.',409)


@bp.get('/analyses/<left>/compare/<right>')
def compare_runs(left,right):
    a=owned_run(left);b=owned_run(right)
    if a.writing_id!=b.writing_id:abort(404,description='API resource unavailable')
    return success({'left':{'runId':a.id,'versionId':a.essay_version_id,'findings':run_data(a)['findings']},'right':{'runId':b.id,'versionId':b.essay_version_id,'findings':run_data(b)['findings']},'notice':'서로 다른 실행의 후보 비교이며 규칙 정확성이나 글의 점수를 뜻하지 않습니다.'})
