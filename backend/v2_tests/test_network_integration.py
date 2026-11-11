import base64
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]))
from v2_fixture import v2app, user_client
from test_analysis_api import essay, analyze
from app.v2.network_gate import IsolatedNetworkGate


def test_private_network_same_origin_save_analyze_pdf_logout(v2app):
    host='crushable-movie-usable.ngrok-free.dev'
    password='synthetic-network-access-password'
    v2app.config.update(SERVER_NAME=host,PREFERRED_URL_SCHEME='https')
    c,h,_=user_client(v2app)
    cookie=c.get_cookie('geulbit_session',domain='localhost')
    c.set_cookie('geulbit_session',cookie.value,domain=host)
    v2app.wsgi_app=IsolatedNetworkGate(v2app.wsgi_app,host,password)
    c.environ_base['HTTP_AUTHORIZATION']='Basic '+base64.b64encode(('geulbit:'+password).encode()).decode()
    assert c.get('/api/auth/session').status_code==200
    body='나는 독자로서 책을 읽을수 있다. 몇 일 동안 인물의 행동을 살폈다. 친구뿐 아니라 이웃도 도움을 받았다.'
    writing=essay(c,h,body)
    ids=analyze(v2app,c,h,writing).json['data']
    run=c.get('/api/analyses/'+ids['analysisId']).json['data']
    assert run['sourceVersion']['content']==body
    rules=[f for f in run['findings'] if (f.get('rule') or '').startswith('gb-local-')]
    assert {f['rule'] for f in rules}=={'gb-local-001','gb-local-002'}
    for f in rules:assert body[f['startOffset']:f['endOffset']]==f['current']
    pdf=c.get('/api/analyses/'+ids['analysisId']+'/pdf')
    assert pdf.status_code==200 and pdf.data.startswith(b'%PDF')
    assert c.post('/api/auth/logout',headers=h).status_code==200
    assert c.get('/api/auth/session').status_code==401
    outsider=v2app.test_client()
    assert outsider.get('/').status_code==401
    assert outsider.get('/api/health').status_code==401


def test_network_google_account_restriction_before_persistence(v2app):
    import time
    from components.auth import Challenge
    from app.extensions import db
    from app.models import User
    class VerifiedFixture:
        testing=True
        def finish(self,*args,**kwargs):
            return {'sub':'synthetic-other-account','email':'other@example.test','emailVerified':True}
    v2app.config.update(OIDC_FLOW=VerifiedFixture(),ISOLATED_GOOGLE_ACCOUNT='ps25090@onedu.jje.go.kr')
    v2app.extensions['v2_challenges']['synthetic-ticket']=Challenge('state','nonce','https://example.invalid/api/auth/callback',time.time())
    c=v2app.test_client();c.set_cookie('geulbit_login','synthetic-ticket')
    assert c.get('/api/auth/callback').status_code==401
    with v2app.app_context():assert User.query.filter_by(oidc_subject='synthetic-other-account').count()==0
