"""Local-only synthetic QA host. Never registered by the product app."""
import argparse
import re
import ctypes
from ctypes import wintypes
import sys
import logging
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]))
from flask import jsonify,make_response
from werkzeug.serving import make_server
from app import create_app
from app.extensions import db
from app.models import User
from app.v2.auth_api import boundary,COOKIE
from app.v2.common import principal
from components.auth import SessionBoundary
from app.services.secrets_service import MemorySecretStore

parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--port',type=int,default=8766);parser.add_argument('--mock-oidc',action='store_true');parser.add_argument('--trusted-local-tls',action='store_true');parser.add_argument('--beta-signup',action='store_true');parser.add_argument('--dist');parser.add_argument('--waitress',action='store_true');parser.add_argument('--retention',action='store_true');args=parser.parse_args()
root=Path(args.root).resolve();expected=(Path('C:/Users/USER/GeulbitData')/'temp').resolve()
repo=Path(__file__).resolve().parents[2]
if root.parent not in {expected,(repo/'artifacts/v21').resolve()} or not root.name.startswith('v2-qa-') or (root/'qa.sqlite3').exists():raise SystemExit('ISOLATED_NEW_QA_ROOT_REQUIRED')
root.mkdir(parents=True,exist_ok=True)
dist=Path(args.dist).resolve() if args.dist else repo/'dist'
if args.dist and not dist.is_relative_to((repo/'artifacts').resolve()):raise SystemExit('ISOLATED_CANDIDATE_DIST_REQUIRED')
app=create_app({'TESTING':True,'GEULBIT_V2':True,'SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(root/'qa.sqlite3'),'DATABASE_PATH':root/'qa.sqlite3','UPLOAD_FOLDER':root/'files','TEMP_FOLDER':root/'temp','BACKUP_FOLDER':root/'backups','FRONTEND_DIST':dist,'SECRET_STORE':MemorySecretStore(),'ADMIN_STATE_FILE':root/'admin.json','ADMIN_AUDIT_FILE':root/'audit.jsonl','SESSION_SIGNING_KEY':'synthetic-qa-only-not-production-000000000000','SESSION_MAX_AGE':3600})
if args.beta_signup:
    import json
    policy=json.loads((repo/'backend/config/privacy.example.json').read_text(encoding='utf-8'))
    app.config.update(BETA_SIGNUP_ENABLED=True,BETA_SIGNUP_POLICY=policy['betaSignup']['policy'])
if args.retention:
    from app.v2.privacy_lifecycle import POLICY
    app.config['PERSONAL_DATA_POLICY']=POLICY # Synthetic DB only; real seven-day deadlines.
if args.mock_oidc:
    # Explicit synthetic provider, only in this isolated test entry point.
    import json,time,secrets
    from google.auth import crypt,jwt
    from datetime import datetime,timedelta,timezone
    from types import SimpleNamespace
    from urllib.parse import urlencode
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from components.auth import GoogleCodeFlow
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'synthetic-qa.invalid')])
    cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1).not_valid_before(datetime.now(timezone.utc)-timedelta(minutes=1)).not_valid_after(datetime.now(timezone.utc)+timedelta(days=1)).sign(key,hashes.SHA256())
    signer=crypt.RSASigner.from_string(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()),key_id="qa-key")
    codes={}
    def exchange(payload):
        nonce=codes.pop(payload['code']);now=int(time.time())
        return {'id_token':jwt.encode(signer,{'iss':'https://accounts.google.com','aud':'synthetic-qa-client','sub':'synthetic-qa-oidc','email':'synthetic@example.test','email_verified':True,'name':'가상 검증 계정','iat':now,'exp':now+300,'nonce':nonce}).decode()}
    class MockGoogleFlow(GoogleCodeFlow):
        def begin(self,*,now):
            _,challenge=super().begin(now=now);code=secrets.token_urlsafe(32);codes[code]=challenge.nonce
            return self.redirect_uri+'?'+urlencode({'state':challenge.state,'code':code}),challenge
    app.config['OIDC_FLOW']=MockGoogleFlow(client_id='synthetic-qa-client',client_secret='synthetic-not-a-real-secret',redirect_uri='https://'+('localhost' if args.trusted_local_tls else '127.0.0.1')+':'+str(args.port)+'/api/auth/callback',state_ttl=300,testing=True,exchange=exchange,certificate_request=lambda *_a,**_k:SimpleNamespace(status=200,data=json.dumps({'qa-key':cert.public_bytes(serialization.Encoding.PEM).decode()}).encode()))
@app.get('/__qa__/session/<name>')
def session(name):
    if name not in {'student','other','admin'} and not re.fullmatch(r'load-(?:[0-2][0-9]|3[0-9])',name):return jsonify({'error':'synthetic fixture unavailable'}),404
    user=User.query.filter_by(oidc_subject='synthetic-qa-'+name).first()
    if not user:
        user=User(oidc_issuer='https://accounts.google.com',oidc_subject='synthetic-qa-'+name,email=name+'@example.test',role='ADMIN' if name=='admin' else 'USER',status='ACTIVE');db.session.add(user);db.session.commit()
    cookie,_=boundary().issue(principal(user),profile={'displayName':'가상 '+name+' 계정'});response=make_response(jsonify({'synthetic':True}));response.set_cookie(COOKIE,cookie,**SessionBoundary.cookie_attributes);return response
@app.get('/__qa__/metrics')
def metrics():
    class Memory(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD),('peak',ctypes.c_size_t),('rss',ctypes.c_size_t),('pagedPeak',ctypes.c_size_t),('paged',ctypes.c_size_t),('nonpagedPeak',ctypes.c_size_t),('nonpaged',ctypes.c_size_t),('pagefile',ctypes.c_size_t),('pagefilePeak',ctypes.c_size_t)]
    memory=Memory();memory.cb=ctypes.sizeof(memory)
    ctypes.windll.kernel32.GetCurrentProcess.restype=wintypes.HANDLE
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Memory),wintypes.DWORD]
    ctypes.windll.psapi.GetProcessMemoryInfo.restype=wintypes.BOOL
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(),ctypes.byref(memory),memory.cb)
    return jsonify({'rssBytes':memory.rss,'peakRssBytes':memory.peak})
context='adhoc'
if args.trusted_local_tls:
    import ssl
    from auth_setup import ROOT,approved_store
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(ROOT/'operational/tls/localhost.cert.pem'),str(ROOT/'operational/tls/localhost.key.pem'),password=approved_store().get('GEULBIT_LOCAL_TLS_KEY_PASSWORD'))
logging.getLogger('werkzeug').setLevel(logging.ERROR) # no callback code/state in QA access logs
if args.waitress:
    import threading
    from waitress import create_server
    from auth_setup import prepare_tls
    from local_https_proxy import create_proxy,LocalTLSProxy
    from app.v2.deployment import waitress_proxy_options
    store=MemorySecretStore();prepare_tls(store,root/'tls')
    origin='https://localhost:'+str(args.port)
    server=create_server(app,host='127.0.0.1',port=0,threads=4,**waitress_proxy_options({'GEULBIT_PUBLIC_ORIGIN':origin,'GEULBIT_TRUSTED_PROXY':'127.0.0.1'}))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    handler=type('IsolatedTLSProxy',(LocalTLSProxy,),{'public_host':'localhost:'+str(args.port),'upstream_port':int(server.effective_port)})
    proxy=create_proxy(root/'tls',store,port=args.port,handler=handler)
    print('SYNTHETIC_WAITRESS_TLS_QA_READY',flush=True)
    try:proxy.serve_forever()
    finally:proxy.server_close();server.close();server.task_dispatcher.shutdown();thread.join(2)
else:
    print('SYNTHETIC_QA_READY localhost TLS; isolated root',str(root),flush=True)
    make_server('127.0.0.1',args.port,app,threaded=True,ssl_context=context).serve_forever()
