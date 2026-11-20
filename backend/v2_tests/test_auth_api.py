from v2_fixture import v2app,user_client
from app.extensions import db
from app.models import User,ActivityRecord


def test_anonymous_api_denied(v2app):
    assert v2app.test_client().get('/api/admin/users').status_code==401

def test_google_only_landing_redirect_and_private_api_not_public(v2app):
    from app.v2.network_gate import IsolatedNetworkGate
    host='crushable-movie-usable.ngrok-free.dev'
    v2app.config['GOOGLE_LOGIN_ON_LANDING']=True
    v2app.wsgi_app=IsolatedNetworkGate(v2app.wsgi_app,host,'synthetic-private-test-password',google_only=True)
    client=v2app.test_client();base='https://'+host
    r=client.get('/',base_url=base)
    assert r.status_code==302 and r.headers['Location']=='/api/auth/login'
    assert 'WWW-Authenticate' not in r.headers
    assert client.get('/api/writings',base_url=base).status_code==401
    assert client.post('/api/writings',base_url=base,json={}).status_code==401
    assert client.get('/api/admin/users',base_url=base).status_code==401

def test_google_only_valid_user_not_redirected(v2app):
    v2app.config['GOOGLE_LOGIN_ON_LANDING']=True
    client,headers,uid=user_client(v2app)
    r=client.get('/')
    assert r.status_code!=302


def test_missing_google_configuration_pending_external(v2app):
    response=v2app.test_client().get('/api/auth/login')
    assert response.status_code==503 and response.json['error']['code']=='PENDING_EXTERNAL'


def test_signed_session_and_csrf(v2app):
    client,headers,uid=user_client(v2app)
    response=client.get('/api/auth/session');assert response.json['data']['id']==uid
    assert response.json['data']['csrfToken']==headers['X-CSRF-Token']
    assert client.post('/api/auth/logout').status_code==401
    assert client.post('/api/auth/logout',headers=headers).status_code==200
    assert client.get('/api/auth/session').status_code==401


def test_user_cannot_operate_accounts(v2app):
    client,headers,uid=user_client(v2app)
    assert client.get('/api/admin/users').status_code==403
    assert client.patch('/api/admin/users/'+uid,headers=headers,json={'status':'ACTIVE'}).status_code==403


def test_admin_approval_and_revocation(v2app):
    client,headers,uid=user_client(v2app,'synthetic-admin','ADMIN')
    other,other_headers,other_id=user_client(v2app,'synthetic-student')
    assert client.patch('/api/admin/users/'+other_id,headers=headers,json={'status':'INACTIVE'}).status_code==200
    assert other.get('/api/auth/session').status_code==401
    assert client.patch('/api/admin/users/'+other_id,headers=headers,json={'status':'ACTIVE'}).status_code==200
    assert other.get('/api/auth/session').status_code==401
    assert client.patch('/api/admin/users/'+other_id,headers=headers,json={'role':'ADMIN'}).status_code==400
    with v2app.app_context():assert ActivityRecord.query.filter_by(action='ACCOUNT_STATUS_CHANGED').count()==2


def test_pending_and_inactive_cookie_rejected(v2app):
    client,headers,uid=user_client(v2app)
    for state in ['PENDING_APPROVAL','INACTIVE']:
        with v2app.app_context():db.session.get(User,uid).status=state;db.session.commit()
        assert client.get('/api/auth/session').status_code==401


def test_tampered_cookie_and_unknown_callback(v2app):
    client=v2app.test_client();client.set_cookie('geulbit_session','synthetic-tampered')
    assert client.get('/api/auth/session').status_code==401
    assert client.get('/api/auth/callback?state=wrong&code=fake').status_code==503


def test_bootstrap_requires_explicit_verified_existing_account(v2app):
    client,headers,uid=user_client(v2app,email='synthetic-admin@example.test',verified=True)
    runner=v2app.test_cli_runner()
    args=['bootstrap-admin','--issuer','https://accounts.google.com','--subject','synthetic-user','--confirm-account','wrong@example.test']
    assert runner.invoke(args=args).exit_code!=0
    args[-1]='synthetic-admin@example.test';assert runner.invoke(args=args).exit_code==0
    assert runner.invoke(args=args).exit_code!=0
    with v2app.app_context():assert db.session.get(User,uid).role=='ADMIN'


def test_oidc_callback_real_signature_mock_provider_and_secure_cookie(v2app):
    import json,time
    from datetime import datetime,timedelta,timezone
    from types import SimpleNamespace
    from urllib.parse import parse_qs,urlsplit
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from google.auth import crypt,jwt
    from components.auth import GoogleCodeFlow
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'synthetic-oidc')]);now=datetime.now(timezone.utc)
    cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(hours=1)).sign(key,hashes.SHA256())
    signer=crypt.RSASigner.from_string(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()),key_id='synthetic-key')
    holder={}
    def exchange(_payload):
        stamp=int(time.time())
        return {'id_token':jwt.encode(signer,{'iss':'https://accounts.google.com','aud':'synthetic-client','sub':'signed-synthetic-sub','iat':stamp-1,'exp':stamp+300,'nonce':holder['nonce'],'email':'synthetic@example.test','email_verified':True,'name':'가상 검증 계정','picture':'https://lh3.googleusercontent.com/a/synthetic-photo'}).decode()}
    v2app.config['OIDC_FLOW']=GoogleCodeFlow(client_id='synthetic-client',client_secret='synthetic-secret',redirect_uri='https://example.invalid/api/auth/callback',state_ttl=300,testing=True,exchange=exchange,certificate_request=lambda *_a,**_k:SimpleNamespace(status=200,data=json.dumps({'synthetic-key':cert.public_bytes(serialization.Encoding.PEM).decode()}).encode()))
    client=v2app.test_client()
    previous,_,_=user_client(v2app,'previous-synthetic-account')
    client.set_cookie('geulbit_session',previous.get_cookie('geulbit_session').value)
    for active in [False,True]:
        response=client.get('/api/auth/login');assert response.status_code==302
        assert 'Secure' in response.headers['Set-Cookie'] and 'HttpOnly' in response.headers['Set-Cookie']
        query=parse_qs(urlsplit(response.location).query);holder['nonce']=query['nonce'][0]
        callback='/api/auth/callback?state='+query['state'][0]+'&code=synthetic'
        response=client.get(callback)
        if not active:
            assert response.json['data']['status']=='PENDING_APPROVAL'
            assert response.headers['Cache-Control']=='no-store'
            with v2app.app_context():
                user=User.query.filter_by(oidc_subject='signed-synthetic-sub').one()
                assert user.role=='USER' and user.email_verified
                pending_id=user.id
            assert client.get('/api/auth/session').status_code==401
            admin,admin_headers,_=user_client(v2app,'explicit-synthetic-approver','ADMIN')
            assert admin.patch('/api/admin/users/'+pending_id,headers=admin_headers,json={'status':'ACTIVE'}).status_code==200
        else:
            assert response.status_code==302 and 'Secure' in response.headers['Set-Cookie']
            account=client.get('/api/auth/session').json['data']
            assert account['displayName']=='가상 검증 계정' and account['email']=='synthetic@example.test'
            assert account['pictureUrl']=='https://lh3.googleusercontent.com/a/synthetic-photo'
            assert account['loginMethod']=='Google OIDC' and account['role']=='USER'
            assert not set(account)&{'sub','oidc_subject','session_version','id_token','access_token'}
        assert client.get(callback).status_code==401


def test_missing_session_configuration_fails_closed(v2app):
    v2app.config['SESSION_MAX_AGE']=None
    assert v2app.test_client().get('/api/auth/login').status_code==503


def test_profile_optional_old_cookie_and_private_responses_not_cached(v2app):
    client,headers,uid=user_client(v2app,email='synthetic-account@example.test')
    response=client.get('/api/auth/session')
    assert response.status_code==200 and response.headers['Cache-Control']=='no-store'
    assert response.json['data']['email']=='synthetic-account@example.test'
    assert 'displayName' not in response.json['data'] and 'pictureUrl' not in response.json['data']
    for url in ['/api/writings','/api/admin/users','/']:
        assert client.get(url).headers['Cache-Control']=='no-store'


def test_browser_pending_callback_shows_server_confirmed_status(v2app):
    import time
    from types import SimpleNamespace
    from components.auth import Challenge
    class VerifiedFixture:
        testing=True
        def finish(self,*args,**kwargs):
            return {'sub':'synthetic-pending-browser','email':'pending@example.test','emailVerified':True}
    v2app.config['OIDC_FLOW']=VerifiedFixture()
    client=v2app.test_client()
    v2app.extensions['v2_challenges']['synthetic-ticket']=Challenge('state','nonce','https://example.invalid/api/auth/callback',time.time())
    client.set_cookie('geulbit_login','synthetic-ticket')
    response=client.get('/api/auth/callback',headers={'Accept':'text/html'})
    assert response.status_code==200 and 'PENDING_APPROVAL' in response.get_data(as_text=True)
    assert '관리자 승인 대기' in response.get_data(as_text=True)
    assert client.get('/api/writings').status_code==401
    assert not client.get_cookie('geulbit_session')
