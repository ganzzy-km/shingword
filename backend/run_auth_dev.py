"""Actual Google development service on an explicitly isolated Data Root only."""
import argparse,os,sys,winreg
from pathlib import Path
from waitress import create_server
from flask.cli import ScriptInfo
from auth_setup import approved_store,ROOT
from app.storage import initialize_storage,validate_volume
from app import create_app
from app.v2.deployment import waitress_proxy_options

PUBLIC_NAMES=['GEULBIT_PUBLIC_ORIGIN','GEULBIT_GOOGLE_REDIRECT_URI','GEULBIT_TRUSTED_PROXY','GEULBIT_SESSION_MAX_AGE','GEULBIT_OIDC_STATE_TTL','GEULBIT_VOLUME_ID']
def load_local_settings():
 with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as k:
  for n in PUBLIC_NAMES:
   try:value=winreg.QueryValueEx(k,n)[0]
   except FileNotFoundError:raise RuntimeError('LOCAL_AUTH_SETTINGS_REQUIRED') from None
   os.environ[n]=value
 if os.environ['GEULBIT_PUBLIC_ORIGIN']!='https://localhost:8770' or os.environ['GEULBIT_GOOGLE_REDIRECT_URI']!='https://localhost:8770/api/auth/callback' or os.environ['GEULBIT_TRUSTED_PROXY']!='127.0.0.1':raise RuntimeError('EXACT_APPROVED_LOCAL_ORIGIN_REQUIRED')
 for n in ['GEULBIT_SESSION_MAX_AGE','GEULBIT_OIDC_STATE_TTL']:
  if int(os.environ[n])<1:raise RuntimeError('APPROVED_TTL_REQUIRED')

def validate_dev_root(value):
 root=Path(value).resolve()
 if root.parent!=(ROOT/'temp').resolve() or not root.name.startswith('oidc-dev-'):raise RuntimeError('ISOLATED_OIDC_DEV_ROOT_REQUIRED')
 return root

def bootstrap_designated_admin(app,subject,account):
 if account!='ps25090@onedu.jje.go.kr':raise RuntimeError('USER_DESIGNATED_ADMIN_REQUIRED')
 app.cli.main(args=['bootstrap-admin','--issuer','https://accounts.google.com','--subject',subject,'--confirm-account',account],standalone_mode=False,obj=ScriptInfo(create_app=lambda:app))

def main():
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--init',action='store_true');p.add_argument('--allow-google',action='store_true');p.add_argument('--bootstrap-subject');p.add_argument('--confirm-account');args=p.parse_args()
 store=approved_store();load_local_settings();root=validate_dev_root(args.root)
 if not all(store.contains(n) or os.getenv(n) for n in ['GEULBIT_GOOGLE_CLIENT_ID','GEULBIT_GOOGLE_CLIENT_SECRET','GEULBIT_SESSION_SIGNING_KEY']):raise RuntimeError('GOOGLE_OR_SESSION_CREDENTIALS_REQUIRED')
 if not args.allow_google:raise RuntimeError('EXPLICIT_DEVELOPMENT_GOOGLE_EXECUTION_REQUIRED')
 volume=os.environ['GEULBIT_VOLUME_ID'];validate_volume(root,volume)
 if args.init:initialize_storage(root,volume)
 if not (root/'db/geulbit.sqlite3').is_file():raise RuntimeError('EXPLICIT_ISOLATED_INIT_REQUIRED')
 os.environ['GEULBIT_GOOGLE_EXTERNAL_APPROVED']='1'  # This process only; never operating configuration.
 app=create_app({'DATA_ROOT':str(root),'VOLUME_ID':volume,'GEULBIT_V2':True,'SECRET_STORE':store,'SESSION_MAX_AGE':int(os.environ['GEULBIT_SESSION_MAX_AGE'])})
 if args.bootstrap_subject:
  bootstrap_designated_admin(app,args.bootstrap_subject,args.confirm_account);return
 server=create_server(app,host='127.0.0.1',port=5000,threads=6,**waitress_proxy_options())
 print('ISOLATED_OIDC_DEV_WAITRESS 127.0.0.1:5000; Google live login enabled only for this isolated process',flush=True)
 try:server.run()
 finally:server.close()
if __name__=='__main__':
 try:main()
 except Exception as e:print('BLOCKED: '+type(e).__name__);sys.exit(1)
