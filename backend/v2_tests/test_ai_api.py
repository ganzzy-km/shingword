from v2_fixture import v2app,user_client
from test_analysis_api import essay,analyze
from app.extensions import db
from app.models import AppSetting,AIInteraction
from components.ai import TEMPLATES


def setup(app):
    c,h,_=user_client(app);w=essay(c,h,'주장 후보가 있다. 관련 근거를 더 확인한다.');ids=analyze(app,c,h,w).json['data'];app.config.update(AI_MAX_SELECTED_CODEPOINTS=1000,AI_POLICY_VERSION='synthetic-policy-v1')
    payload={'spans':[{'start':0,'end':5,'quote':w['content'][:5]}],'questionType':'ASSUMPTION'}
    preview=c.post('/api/analyses/'+ids['analysisId']+'/ai/preview',headers=h,json=payload).json['data'];payload['previewHash']=preview['previewHash']
    return c,h,w,ids,payload,preview


def grant(c,h):return c.post('/api/ai/consent',headers=h,json={'policyVersion':'synthetic-policy-v1','granted':True})


def test_ai_references_only_linked_viewable_snapshot_and_preview_binding(v2app):
    from test_library_api import upload
    c,h,w,ids,p,preview=setup(v2app)
    source=upload(c,h,'가상 작품. 뿌리는 꽃을 받친다. 다른 장면이 있다.').json['data']
    rid=source['latestRevisionId']
    assert c.post('/api/writings/'+w['id']+'/documents',headers=h,json={'revisionId':rid}).status_code==200
    fresh=analyze(v2app,c,h,w).json['data']['analysisId']
    path='/api/analyses/'+fresh+'/ai/'
    assert c.get(path+'references').json['data']==[{'revisionId':rid,'title':source['title']}]
    selected={**p,'references':[{'revisionId':rid,'quote':'뿌리는 꽃을 받친다.'}]}
    response=c.post(path+'preview',headers=h,json=selected);assert response.status_code==200
    ctx=response.json['data']['context']
    assert ctx['excerpts']==preview['context']['excerpts']
    assert ctx['references'][0]['quote']=='뿌리는 꽃을 받친다.'
    assert '다른 장면' not in str(ctx)
    selected['previewHash']=response.json['data']['previewHash'];grant(c,h)
    assert c.post(path+'questions',headers=h,json={**selected,'references':[]}).status_code==409
    result=c.post(path+'questions',headers=h,json=selected).json['data']
    assert result['questions'][0]['focusQuote']==p['spans'][0]['quote']
    with v2app.app_context():
        row=db.session.get(AIInteraction,result['id'])
        assert 'quote' not in row.context['payload']['references'][0]
    assert c.post('/api/analyses/'+ids['analysisId']+'/ai/preview',headers=h,json=selected).status_code==400
    for quote in ['없는 작품 결말', '가상 작품. 뿌리는 꽃을 받친다. 다른 장면이 있다.']:
        assert c.post(path+'preview',headers=h,json={**selected,'references':[{'revisionId':rid,'quote':quote}]}).status_code==400
    other,oh,_=user_client(v2app,'synthetic-reference-other')
    assert other.get(path+'references').status_code==404


def test_ai_match_only_reference_never_exposed(v2app):
    from test_library_api import upload
    c,h,w,ids,p,_=setup(v2app)
    doc=upload(c,h,'가상 비공개 대조 본문.',accessMode='MATCH_ONLY').json['data']
    c.post('/api/writings/'+w['id']+'/documents',headers=h,json={'revisionId':doc['latestRevisionId']})
    fresh=analyze(v2app,c,h,w).json['data']['analysisId'];path='/api/analyses/'+fresh+'/ai/'
    assert c.get(path+'references').json['data']==[]
    assert c.post(path+'preview',headers=h,json={**p,'references':[{'revisionId':doc['latestRevisionId'],'quote':'가상'}]}).status_code==404


def test_ai_reference_access_revoked_during_provider_does_not_store(v2app):
    from test_library_api import upload
    from app.models import SourceDocument
    c,h,w,ids,p,_=setup(v2app)
    doc=upload(c,h,'가상 작품. 뿌리는 꽃을 받친다. 다음 장면.').json['data']
    c.post('/api/writings/'+w['id']+'/documents',headers=h,json={'revisionId':doc['latestRevisionId']})
    fresh=analyze(v2app,c,h,w).json['data']['analysisId'];path='/api/analyses/'+fresh+'/ai/'
    selected={**p,'references':[{'revisionId':doc['latestRevisionId'],'quote':'뿌리는 꽃을 받친다.'}]}
    selected['previewHash']=c.post(path+'preview',headers=h,json=selected).json['data']['previewHash'];grant(c,h)
    with v2app.app_context():db.session.add(AppSetting(key='ai_enabled',value=True));db.session.commit()
    def provider(_):
        source=db.session.get(SourceDocument,doc['id']);source.access_mode='MATCH_ONLY';db.session.commit()
        return {'questions':[]}
    v2app.config.update(EXTERNAL_AI_TERMS_APPROVED=True,AI_PROVIDER=provider,AI_PROVIDER_TEST_ONLY=True,AI_LIMITS={'dailyRequests':1,'monthlyBudgetUnits':10,'callCostUnits':1,'cooldownSeconds':0,'concurrency':1})
    assert c.post(path+'questions',headers=h,json=selected).status_code==404
    with v2app.app_context():assert AIInteraction.query.count()==0


def test_consent_required_and_external_off_fallback(v2app):
    c,h,w,ids,p,preview=setup(v2app);path='/api/analyses/'+ids['analysisId']+'/ai/questions'
    assert c.post(path,headers=h,json=p).status_code==403
    assert grant(c,h).status_code==200
    result=c.post(path,headers=h,json=p).json['data'];assert result['status']=='LOCAL_FALLBACK_EXTERNAL_DISABLED' and len(result['questions'])==1
    assert set(preview['context'])=={'versionId','questionType','excerpts'} and preview['context']['excerpts'][0]['quote']!=w['content']


def test_preview_mismatch_full_body_and_idor(v2app):
    c,h,w,ids,p,preview=setup(v2app);grant(c,h);path='/api/analyses/'+ids['analysisId']+'/ai/'
    wrong={**p,'previewHash':'wrong'};assert c.post(path+'questions',headers=h,json=wrong).status_code==409
    full={**p,'spans':[{'start':0,'end':len(w['content']),'quote':w['content']}]};assert c.post(path+'preview',headers=h,json=full).status_code==400
    other,oh,_=user_client(v2app,'synthetic-other');assert other.post(path+'questions',headers=oh,json=p).status_code==404


def test_cache_user_bound_notes_not_provider_context_and_analysis_unchanged(v2app):
    c,h,w,ids,p,preview=setup(v2app);grant(c,h);path='/api/analyses/'+ids['analysisId']+'/ai/questions';before=c.get('/api/analyses/'+ids['analysisId']).json['data']['result']
    a=c.post(path,headers=h,json=p).json['data'];b=c.post(path,headers=h,json=p).json['data'];assert a['id']==b['id'] and b['cached']
    assert c.patch('/api/ai/interactions/'+a['id']+'/note',headers=h,json={'note':'synthetic private thought'}).status_code==200
    with v2app.app_context():assert 'note' not in db.session.get(AIInteraction,a['id']).context
    assert c.get('/api/analyses/'+ids['analysisId']).json['data']['result']==before


def test_mock_provider_schema_fallback_and_persisted_budget(v2app):
    c,h,w,ids,p,preview=setup(v2app);grant(c,h)
    with v2app.app_context():db.session.add(AppSetting(key='ai_enabled',value=True));db.session.commit()
    called=[]
    def provider(ctx):called.append(ctx);return {'questions':[{'focusQuote':'invented fact','questionType':'ASSUMPTION','question':'invented conclusion'}]}
    v2app.config.update(EXTERNAL_AI_TERMS_APPROVED=True,AI_PROVIDER=provider,AI_PROVIDER_TEST_ONLY=True,AI_LIMITS={'dailyRequests':1,'monthlyBudgetUnits':10,'callCostUnits':1,'cooldownSeconds':0,'concurrency':1})
    path='/api/analyses/'+ids['analysisId']+'/ai/questions';result=c.post(path,headers=h,json=p).json['data'];assert result['status']=='LOCAL_FALLBACK_INVALID_OR_UNAVAILABLE' and len(called)==1
    other={**p,'questionType':'EVIDENCE'};preview2=c.post('/api/analyses/'+ids['analysisId']+'/ai/preview',headers=h,json=other).json['data'];other['previewHash']=preview2['previewHash']
    result=c.post(path,headers=h,json=other).json['data'];assert result['status']=='LOCAL_FALLBACK_LIMIT' and len(called)==1
    assert called[0]==preview['context']


def test_consent_revocation_and_missing_policy(v2app):
    c,h,w,ids,p,preview=setup(v2app);grant(c,h)
    assert c.post('/api/ai/consent',headers=h,json={'policyVersion':'synthetic-policy-v1','granted':False}).status_code==200
    assert c.post('/api/analyses/'+ids['analysisId']+'/ai/questions',headers=h,json=p).status_code==403
    v2app.config['AI_POLICY_VERSION']=None
    assert c.post('/api/ai/consent',headers=h,json={'policyVersion':'synthetic','granted':True}).status_code==503


def test_baze_adapter_existing_ui_contract_no_fallback_cache_or_transaction(v2app):
    from app.v2.baze_provider import BazeProvider,GatewaySettings
    from test_baze_provider import Transport,approved_config
    from components.ai import QUESTION_OPTIONS
    c,h,w,ids,p,preview=setup(v2app);grant(c,h)
    path='/api/analyses/'+ids['analysisId']+'/ai/questions'
    assert c.post(path,headers=h,json=p).json['data']['status']=='LOCAL_FALLBACK_EXTERNAL_DISABLED'
    transport=Transport()
    from app.services.secrets_service import MemorySecretStore
    provider=BazeProvider(GatewaySettings.approved(approved_config()),MemorySecretStore({'BAZE_API_KEY':'synthetic-only-key'}),opener=transport)
    class CheckedProvider:
        cache_tag=provider.cache_tag
        def __call__(self,context):
            assert not db.session().in_transaction()
            return provider(context)
    with v2app.app_context():db.session.add(AppSetting(key='ai_enabled',value=True));db.session.commit()
    v2app.config.update(EXTERNAL_AI_TERMS_APPROVED=True,AI_PROVIDER=CheckedProvider(),AI_PROVIDER_TEST_ONLY=True,AI_LIMITS=approved_config()['AI_LIMITS'])
    result=c.post(path,headers=h,json=p).json['data'];assert result['status']=='PROVIDER_VALIDATED'
    assert result['questions'][0]['question']==QUESTION_OPTIONS['ASSUMPTION'][1]
    assert c.post(path,headers=h,json=p).json['data']['cached'] and len(transport.requests)==1
    v2app.config['EXTERNAL_AI_TERMS_APPROVED']=False
    assert c.post(path,headers=h,json=p).json['data']['status']=='LOCAL_FALLBACK_EXTERNAL_DISABLED'
    assert len(transport.requests)==1


def test_kill_switch_during_provider_call_does_not_store_questions(v2app):
    c,h,w,ids,p,preview=setup(v2app);grant(c,h)
    with v2app.app_context():db.session.add(AppSetting(key='ai_enabled',value=True));db.session.commit()
    def provider(_):
        setting=db.session.get(AppSetting,'ai_enabled');setting.value=False;db.session.commit()
        return {'questions':[]}
    v2app.config.update(EXTERNAL_AI_TERMS_APPROVED=True,AI_PROVIDER=provider,AI_PROVIDER_TEST_ONLY=True,AI_LIMITS={'dailyRequests':1,'monthlyBudgetUnits':10,'callCostUnits':1,'cooldownSeconds':0,'concurrency':1})
    result=c.post('/api/analyses/'+ids['analysisId']+'/ai/questions',headers=h,json=p)
    assert result.status_code==409 and result.json['error']['code']=='AI_DISABLED'
    with v2app.app_context():assert AIInteraction.query.count()==0
