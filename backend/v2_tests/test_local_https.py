import sys,threading,ssl,http.client
from pathlib import Path
import pytest
from flask import Flask,request,make_response
from waitress import create_server
sys.path.insert(0,str(Path(__file__).parents[1]))
from app.services.secrets_service import MemorySecretStore
from app.v2.deployment import waitress_proxy_options
from auth_setup import prepare_tls
from local_https_proxy import create_proxy,LocalTLSProxy

@pytest.fixture
def proxy(tmp_path):
 app=Flask(__name__)
 @app.route('/probe',methods=['GET','POST'])
 def probe():
  r=make_response({'scheme':request.scheme,'host':request.host,'forwardedHost':request.headers.get('X-Forwarded-Host'),'forwardedIp':request.headers.get('X-Forwarded-For'),'body':request.get_data(as_text=True)})
  r.set_cookie('synthetic_cookie','synthetic',httponly=True,secure=True,samesite='Lax');return r
 w=create_server(app,host='127.0.0.1',port=0,threads=1,**waitress_proxy_options({'GEULBIT_PUBLIC_ORIGIN':'https://localhost:8770','GEULBIT_TRUSTED_PROXY':'127.0.0.1'}));wt=threading.Thread(target=w.run,daemon=True);wt.start()
 old=LocalTLSProxy.upstream_port;LocalTLSProxy.upstream_port=int(w.effective_port)
 store=MemorySecretStore();prepare_tls(store,tmp_path);p=create_proxy(tmp_path,store,port=0);pt=threading.Thread(target=p.serve_forever,daemon=True);pt.start()
 yield p.server_port,tmp_path
 p.shutdown();p.server_close();w.close();wt.join(timeout=5);pt.join(timeout=5);LocalTLSProxy.upstream_port=old

def connect(proxy):
 port,directory=proxy;return http.client.HTTPSConnection('localhost',port,context=ssl.create_default_context(cafile=str(directory/'localhost.cert.pem')),timeout=5)

def test_tls_verified_and_incoming_forwarded_headers_stripped(proxy):
 import json
 c=connect(proxy);c.request('POST','/probe',body='synthetic',headers={'Host':'localhost:8770','X-Forwarded-Proto':'http','X-Forwarded-Host':'evil.invalid','Forwarded':'host=evil.invalid','X-Forwarded-For':'203.0.113.10'});r=c.getresponse();d=json.loads(r.read());assert d=={'scheme':'https','host':'localhost:8770','forwardedHost':None,'forwardedIp':None,'body':'synthetic'}
 cookie=r.getheader('Set-Cookie');assert all(v in cookie for v in ['Secure','HttpOnly','SameSite=Lax']);c.close()

@pytest.mark.parametrize('host',['evil.invalid','127.0.0.1:8770','localhost:5000'])
def test_wrong_host_blocked(proxy,host):
 c=connect(proxy);c.request('GET','/probe',headers={'Host':host});assert c.getresponse().status==400;c.close()

@pytest.mark.parametrize('path',['https://evil.invalid/probe','//evil.invalid/probe'])
def test_not_an_open_proxy(proxy,path):
 c=connect(proxy);c.request('GET',path,headers={'Host':'localhost:8770'});assert c.getresponse().status==400;c.close()

def test_transfer_encoding_rejected(proxy):
 c=connect(proxy);c.request('POST','/probe',body='x',headers={'Host':'localhost:8770','Transfer-Encoding':'chunked'});assert c.getresponse().status==400;c.close()
