import base64
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))
from flask import Flask, request
import pytest
from app.v2.network_gate import IsolatedNetworkGate

PASSWORD = "synthetic-private-test-password"
HOST = "crushable-movie-usable.ngrok-free.dev"


def client(limit=120, clock=lambda: 0):
    app = Flask(__name__)
    @app.route("/probe", methods=["GET", "POST"])
    def probe():
        return {"authorizationRemoved": "Authorization" not in request.headers}
    app.wsgi_app = IsolatedNetworkGate(app.wsgi_app, HOST, PASSWORD, limit=limit, clock=clock)
    return app.test_client()


def headers(value=PASSWORD):
    return {"Authorization": "Basic " + base64.b64encode(("geulbit:"+value).encode()).decode()}


@pytest.mark.parametrize("auth", [{}, headers("wrong"), {"Authorization": "Basic !!!"}, {"Authorization":"Bearer invalid"}])
def test_private_test_rejects_unauthorized(auth):
    r=client().get("/probe",base_url="https://"+HOST,headers=auth)
    assert r.status_code==401 and "Basic" in r.headers["WWW-Authenticate"]


@pytest.mark.parametrize("origin", ["http://"+HOST,"https://evil.example","https://"+HOST+":8443"])
def test_exact_https_host(origin):
    assert client().get("/probe",base_url=origin,headers=headers()).status_code==400


def test_allowed_request_and_credentials_not_forwarded():
    r=client().get("/probe",base_url="https://"+HOST,headers=headers())
    assert r.status_code==200 and r.json["authorizationRemoved"]


def test_cross_origin_and_rate_limit():
    c=client();h=headers();h["Origin"]="https://evil.example"
    assert c.post("/probe",base_url="https://"+HOST,headers=h).status_code==403
    clock=[0];c=client(limit=2,clock=lambda:clock[0])
    for _ in range(2):assert c.get("/probe",base_url="https://"+HOST,headers=headers()).status_code==200
    assert c.get("/probe",base_url="https://"+HOST,headers=headers()).status_code==429
    clock[0]=61
    assert c.get("/probe",base_url="https://"+HOST,headers=headers()).status_code==200


def test_no_unrestricted_configuration():
    with pytest.raises(ValueError,match="NETWORK_ACCESS_KEY_REQUIRED"):
        IsolatedNetworkGate(None,HOST,"")

def test_google_only_entry_has_no_basic_challenge_but_preserves_boundaries():
    app=Flask(__name__)
    @app.route('/probe',methods=['GET','POST'])
    def probe():return {'ok':True}
    app.wsgi_app=IsolatedNetworkGate(app.wsgi_app,HOST,PASSWORD,google_only=True,limit=5)
    c=app.test_client()
    r=c.get('/probe',base_url='https://'+HOST)
    assert r.status_code==200 and 'WWW-Authenticate' not in r.headers and 'Set-Cookie' not in r.headers
    assert c.get('/probe',base_url='https://evil.example').status_code==400
    assert c.post('/probe',base_url='https://'+HOST,headers={'Origin':'https://evil.example'}).status_code==403
    for _ in range(3):assert c.get('/probe',base_url='https://'+HOST).status_code==200
    assert c.get('/probe',base_url='https://'+HOST).status_code==429


def test_verified_basic_grants_host_only_secure_bounded_cookie():
    c=client();r=c.get('/probe',base_url='https://'+HOST,headers=headers())
    cookie=r.headers['Set-Cookie']
    assert all(v in cookie for v in ['Secure','HttpOnly','SameSite=Lax','Max-Age=3600','Path=/'])
    assert 'Domain=' not in cookie
    # Background/callback requests need not resend cached Basic credentials.
    assert c.get('/probe',base_url='https://'+HOST).status_code==200
    assert c.post('/probe',base_url='https://'+HOST,headers={'Origin':'https://evil.example'}).status_code==403


def test_access_cookie_rejects_tampering_expiry_future_and_other_host():
    now=[10000]
    gate=IsolatedNetworkGate(None,HOST,PASSWORD,wall_clock=lambda:now[0])
    token=gate.access_cookie();header=gate.COOKIE+'='+token
    assert gate.valid_cookie(header)
    assert not gate.valid_cookie(header+'x')
    assert not IsolatedNetworkGate(None,'other.example',PASSWORD,wall_clock=lambda:now[0]).valid_cookie(header)
    now[0]=9999;assert not gate.valid_cookie(header)
    now[0]=13600;assert not gate.valid_cookie(header)


def test_missing_test_access_api_does_not_prompt_browser_basic_dialog():
    r=client().get('/api/auth/session',base_url='https://'+HOST)
    assert r.status_code==401 and r.json['error']['code']=='PRIVATE_TEST_ACCESS_REQUIRED'
    assert 'WWW-Authenticate' not in r.headers


def test_google_session_error_does_not_remove_private_access():
    app=Flask(__name__)
    @app.get('/api/auth/session')
    def session():return {'error':{'code':'ACCESS_DENIED'}},401
    app.wsgi_app=IsolatedNetworkGate(app.wsgi_app,HOST,PASSWORD)
    c=app.test_client()
    r=c.get('/api/auth/session',base_url='https://'+HOST,headers=headers())
    assert r.status_code==401 and 'WWW-Authenticate' not in r.headers
    assert c.get_cookie(IsolatedNetworkGate.COOKIE,domain=HOST)
    r=c.get('/api/auth/session',base_url='https://'+HOST)
    assert r.json['error']['code']=='ACCESS_DENIED'
