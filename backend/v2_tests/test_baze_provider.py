import io
import json
import pytest
from v2_fixture import v2app
from app.v2.baze_provider import BazeProvider, GatewaySettings, ProviderUnavailable, install_provider, NoRedirect
from app.services.secrets_service import MemorySecretStore
from components.ai import QUESTION_OPTIONS, selection_questions

CONTEXT={'versionId':'synthetic-version-not-for-provider','questionType':'EVIDENCE','excerpts':[{'start':0,'end':6,'quote':'선택 구절.'}]}


def test_linked_reference_transport_minimal_no_ids_and_focus_stays_in_essay():
    transport=Transport()
    provider=BazeProvider(GatewaySettings.approved(approved_config()),MemorySecretStore({'BAZE_API_KEY':'synthetic-only-key'}),opener=transport)
    context={**CONTEXT,'references':[{'revisionId':'private-revision-id','start':2,'end':9,'quote':'가상 작품말.'}]}
    result=provider(context)
    assert result['questions'][0]['focusQuote']=='선택 구절.'
    request,_=transport.requests[0];selected=json.loads(json.loads(request.data)['messages'][1]['content'])
    assert selected['workExcerpts']==['가상 작품말.'] and selected['excerpts']==['선택 구절.']
    assert b'private-revision-id' not in request.data


def approved_config():
    return {'EXTERNAL_AI_TERMS_APPROVED':True,'AI_POLICY_VERSION':'synthetic-policy',
        'AI_LIMITS':{'dailyRequests':2,'monthlyBudgetUnits':10,'callCostUnits':2,'cooldownSeconds':1,'concurrency':1},
        'BAZE_GATEWAY':{'baseUrl':'https://factchat-cloud.mindlogic.ai/v1/gateway','model':'synthetic-test-model',
        'maxCompletionTokens':256,'maxSelectedCodepoints':1000,'timeoutSeconds':10,
        'endpointConfirmed':True,'modelConfirmed':True,'pricingConfirmed':True,'processingTermsConfirmed':True,
        'costUpperBoundConfirmed':True,'processingTermsReference':'synthetic-reviewed-terms','pricingReference':'synthetic-upper-bound'}}


class Response(io.BytesIO):
    status=200
    def geturl(self):return 'https://factchat-cloud.mindlogic.ai/v1/gateway/chat/completions/'


class Transport:
    def __init__(self,value=None,raw=None,finish='stop',status=200):
        self.requests=[];self.status=status
        self.raw=raw if raw is not None else json.dumps({'choices':[{'finish_reason':finish,'message':{'content':json.dumps(value or {'status':'OK','selections':[{'excerptIndex':0,'questionIndex':1}]})}}]}).encode()
    def open(self,request,timeout):
        self.requests.append((request,timeout));r=Response(self.raw);r.status=self.status;return r


def provider(transport,store=None):
    return BazeProvider(GatewaySettings.approved(approved_config()),store or MemorySecretStore({'BAZE_API_KEY':'synthetic-test-only-key'}),opener=transport)


def test_real_protocol_minimal_context_no_ids_tools_or_retries():
    transport=Transport();result=provider(transport)(CONTEXT)
    assert result['questions']==[{'focusQuote':'선택 구절.','questionType':'EVIDENCE','question':QUESTION_OPTIONS['EVIDENCE'][1]}]
    request,timeout=transport.requests[0];payload=json.loads(request.data)
    assert request.full_url=='https://factchat-cloud.mindlogic.ai/v1/gateway/chat/completions/'
    assert request.get_header('Authorization')=='Bearer synthetic-test-only-key' and timeout==10
    assert payload['stream'] is False and payload['max_completion_tokens']==256
    assert set(payload)=={'model','stream','max_completion_tokens','response_format','messages'}
    assert payload['response_format']['json_schema']['strict'] is True
    schema_text=json.dumps(payload['response_format']['json_schema']['schema'])
    assert all(field not in schema_text for field in ('maxItems','minimum','maximum'))
    selected=json.loads(payload['messages'][1]['content']);assert set(selected)=={'questionType','excerpts','questionOptions'}
    assert selected['excerpts']==['선택 구절.'] and CONTEXT['versionId'] not in request.data.decode()
    assert len(transport.requests)==1


@pytest.mark.parametrize('base',['http://factchat-cloud.mindlogic.ai/v1/gateway','https://attacker.invalid/v1/gateway','https://factchat-cloud.mindlogic.ai.evil/v1/gateway','https://user:password@factchat-cloud.mindlogic.ai/v1/gateway','https://factchat-cloud.mindlogic.ai/v1/gateway?secret=x'])
def test_arbitrary_hosts_http_credentials_and_queries_are_blocked(base):
    config=approved_config();config['BAZE_GATEWAY']['baseUrl']=base
    with pytest.raises(ValueError):GatewaySettings.approved(config)


@pytest.mark.parametrize('key',['endpointConfirmed','modelConfirmed','pricingConfirmed','processingTermsConfirmed','costUpperBoundConfirmed'])
def test_unconfirmed_configuration_blocks_before_secret_or_transport(key):
    config=approved_config();config['BAZE_GATEWAY'][key]=False
    with pytest.raises(ValueError):GatewaySettings.approved(config)


@pytest.mark.parametrize('key,value',[('maxCompletionTokens',True),('maxCompletionTokens',2049),('maxSelectedCodepoints',0),('timeoutSeconds',31),('model','\nunsafe')])
def test_limits_and_model_are_strict(key,value):
    config=approved_config();config['BAZE_GATEWAY'][key]=value
    with pytest.raises(ValueError):GatewaySettings.approved(config)


def test_zero_cost_cannot_bypass_monthly_budget():
    config=approved_config();config['AI_LIMITS']['callCostUnits']=0
    with pytest.raises(ValueError):GatewaySettings.approved(config)


@pytest.mark.parametrize('raw,finish,status',[(b'not-json','stop',200),(b'x'*65537,'stop',200),(None,'length',200),(None,'stop',401),(None,'stop',429),(None,'stop',503)],ids=['bad-json','oversized','truncated','unauthorized','rate-limit','unavailable'])
def test_bad_responses_no_retry_and_constant_diagnostic(raw,finish,status):
    transport=Transport(raw=raw,finish=finish,status=status)
    with pytest.raises(ProviderUnavailable,match='^BAZE_REQUEST_UNAVAILABLE$'):provider(transport)(CONTEXT)
    assert len(transport.requests)==1


@pytest.mark.parametrize('value',[{'status':'OK','selections':[{'excerptIndex':0,'questionIndex':1}]*3},{'status':'OK','selections':[{'excerptIndex':True,'questionIndex':0}]},{'status':'OK','selections':[{'excerptIndex':0,'questionIndex':3}]},{'status':'OK','selections':[{'excerptIndex':0,'questionIndex':0,'fact':'invented ending'}]},{'status':'INSUFFICIENT_CONTEXT','selections':[{'excerptIndex':0,'questionIndex':0}]},{'status':'OK','selections':[{'excerptIndex':0,'questionIndex':0}]*2}])
def test_untrusted_output_cannot_inject_facts_or_invalid_indices(value):
    with pytest.raises(ValueError):selection_questions(value,CONTEXT)


def test_insufficient_context_and_two_questions():
    assert provider(Transport(value={'status':'INSUFFICIENT_CONTEXT','selections':[]}))(CONTEXT)=={'questions':[]}
    assert len(provider(Transport(value={'status':'OK','selections':[{'excerptIndex':0,'questionIndex':0},{'excerptIndex':0,'questionIndex':2}]}))(CONTEXT)['questions'])==2


def test_unknown_context_and_missing_key_never_send():
    transport=Transport()
    with pytest.raises(ProviderUnavailable):provider(transport)({**CONTEXT,'note':'private thought'})
    with pytest.raises(ProviderUnavailable):provider(transport,MemorySecretStore())(CONTEXT)
    assert not transport.requests


def test_redirect_cannot_forward_authorization():
    assert NoRedirect().redirect_request(None,None,302,'redirect',{},'https://attacker.invalid') is None


def test_inactive_install_never_reads_key(v2app):
    class ForbiddenStore:
        def contains(self,*args):raise AssertionError('No key read while disabled')
    v2app.config.update(EXTERNAL_AI_TERMS_APPROVED=False,BAZE_GATEWAY=approved_config()['BAZE_GATEWAY'],SECRET_STORE=ForbiddenStore())
    install_provider(v2app);assert not v2app.config.get('AI_PROVIDER')


def test_explicit_trusted_install_uses_existing_store(v2app):
    v2app.config.update(approved_config());v2app.config['SECRET_STORE']=MemorySecretStore({'BAZE_API_KEY':'synthetic-key'})
    v2app.extensions['secret_store']=v2app.config['SECRET_STORE']
    install_provider(v2app)
    assert isinstance(v2app.config['AI_PROVIDER'],BazeProvider) and v2app.config['AI_MAX_SELECTED_CODEPOINTS']==1000


def test_safe_timeout_diagnostic_does_not_contain_provider_text():
    class Timeout:
        def open(self,*args,**kwargs):raise TimeoutError('synthetic-key private text')
    with pytest.raises(ProviderUnavailable) as error:provider(Timeout())(CONTEXT)
    assert str(error.value)=='BAZE_REQUEST_UNAVAILABLE'


def test_gateway_tls_requires_trusted_chain_and_correct_hostname():
    import ssl
    from app.v2.baze_provider import gateway_tls_context
    context=gateway_tls_context()
    assert context.verify_mode==ssl.CERT_REQUIRED and context.check_hostname is True
    assert context.cert_store_stats()['x509_ca']>0
