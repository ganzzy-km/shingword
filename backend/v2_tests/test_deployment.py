import sys,time
from pathlib import Path
from types import SimpleNamespace
import pytest
from flask import Flask
sys.path.insert(0,str(Path(__file__).parents[1]))
from app.v2.deployment import configure_deployment,https_origin,waitress_proxy_options
from components.auth import GoogleCodeFlow,AuthDenied,SessionBoundary,Principal

@pytest.mark.parametrize('value',['http://school.example','https://school.example/path','https://u:p@school.example','https://school.example?x=1','https://school.example#x','https://school.example:bad','https://school.example\n'])
def test_invalid_public_origins(value):
 with pytest.raises(ValueError):https_origin(value)

@pytest.mark.parametrize('callback',['https://other.example/api/auth/callback','https://school.example/callback','https://school.example/api/auth/callback/'])
def test_callback_must_match_exact_origin_and_route(callback):
 app=Flask(__name__);app.config.update(PUBLIC_ORIGIN='https://school.example',OIDC_FLOW=SimpleNamespace(redirect_uri=callback,testing=False))
 with pytest.raises(ValueError,match='MISMATCH'):configure_deployment(app)

@pytest.mark.parametrize('uri',['https://school.example/api/auth/callback?x=1','https://school.example:bad/api/auth/callback','https://u:p@school.example/api/auth/callback','https://school.example/api/auth/callback\n'])
def test_redirect_url_rejection(uri):
 with pytest.raises(AuthDenied):GoogleCodeFlow(client_id='synthetic',client_secret='synthetic',redirect_uri=uri,state_ttl=300)

def test_host_and_scheme_and_forwarded_spoof_rejected():
 app=Flask(__name__);app.config.update(PUBLIC_ORIGIN='https://school.example',OIDC_FLOW=SimpleNamespace(redirect_uri='https://school.example/api/auth/callback',testing=False));configure_deployment(app)
 @app.get('/api/probe')
 def probe():return {'ok':True}
 c=app.test_client()
 assert c.get('/api/probe',base_url='https://school.example').status_code==200
 assert c.get('/api/probe',base_url='https://evil.example').status_code==400
 assert c.get('/api/probe',base_url='http://school.example',headers={'X-Forwarded-Proto':'https','X-Forwarded-Host':'school.example'}).status_code==400
 assert c.get('/api/probe',base_url='https://school.example:8443').status_code==400

@pytest.mark.parametrize('proxy',['*','192.168.1.2','127.0.0.1,::1'])
def test_proxy_is_explicit_loopback_only(proxy):
 with pytest.raises(ValueError):waitress_proxy_options({'GEULBIT_TRUSTED_PROXY':proxy,'GEULBIT_PUBLIC_ORIGIN':'https://school.example'})

def test_proxy_off_by_default_and_never_trusts_host_or_ip():
 assert waitress_proxy_options({})=={'clear_untrusted_proxy_headers':True,'log_untrusted_proxy_headers':False}
 options=waitress_proxy_options({'GEULBIT_TRUSTED_PROXY':'127.0.0.1','GEULBIT_PUBLIC_ORIGIN':'https://school.example'})
 assert options['trusted_proxy_headers']=={'x-forwarded-proto'} and options['trusted_proxy_count']==1
 with pytest.raises(ValueError):waitress_proxy_options({'GEULBIT_TRUSTED_PROXY':'127.0.0.1'})

def test_signed_session_expires_without_sleep(monkeypatch):
 from itsdangerous import TimestampSigner
 clock=[1000];monkeypatch.setattr(TimestampSigner,'get_timestamp',lambda self:clock[0])
 b=SessionBoundary('synthetic-only-secret-0000000000000000',max_age=10);u=Principal('id','sub','USER','ACTIVE',1);cookie,_=b.issue(u)
 clock[0]=1010;assert b.verify(cookie,load_user=lambda _:u)==u
 clock[0]=1011
 with pytest.raises(AuthDenied):b.verify(cookie,load_user=lambda _:u)


def test_waitress_proxy_headers_on_actual_loopback_socket():
 import threading,requests
 from waitress import create_server
 app=Flask(__name__);app.config['PUBLIC_ORIGIN']='https://school.example';configure_deployment(app)
 @app.get('/api/probe')
 def probe():return {'ok':True}
 for trusted in [False,True]:
  env={'GEULBIT_PUBLIC_ORIGIN':'https://school.example'}
  if trusted:env['GEULBIT_TRUSTED_PROXY']='127.0.0.1'
  server=create_server(app,host='127.0.0.1',port=0,threads=1,**waitress_proxy_options(env));thread=threading.Thread(target=server.run,daemon=True);thread.start()
  try:
   url='http://127.0.0.1:'+str(server.effective_port)+'/api/probe'
   r=requests.get(url,headers={'Host':'school.example','X-Forwarded-Proto':'https','X-Forwarded-Host':'evil.example','X-Forwarded-For':'203.0.113.1'},timeout=5)
   assert r.status_code==(200 if trusted else 400)
   assert requests.get(url,headers={'Host':'evil.example','X-Forwarded-Proto':'https'},timeout=5).status_code==400
  finally:server.close();thread.join(timeout=5)
