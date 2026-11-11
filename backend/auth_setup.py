"""Explicit local setup; getpass inputs, DPAPI storage, no network/DB writes."""
import argparse,getpass,json,secrets,sys,os,winreg
from pathlib import Path
from datetime import datetime,timedelta,timezone
from app.storage import validate_volume,check_database
from app.services.secrets_service import DpapiSecretStore
ROOT=Path('C:/Users/USER/GeulbitData')

# Only constant diagnostic codes may leave this process. Never expose exception
# text, chained Windows errors, configuration values or filesystem paths.
SAFE_ERROR_CODES=frozenset({
 'APPROVED_DATA_ROOT_REQUIRED','EXISTING_GOOGLE_CREDENTIALS_PRESERVED',
 'GOOGLE_CREDENTIAL_FORMAT_INVALID','SESSION_SECRET_TOO_SHORT',
 'GOOGLE_CLIENT_ID_FORMAT_INVALID','GOOGLE_CLIENT_SECRET_REQUIRED',
 'PARTIAL_TLS_STATE_PRESERVED','TLS_CERTIFICATE_STATE_INVALID',
 'LOCALHOST_CERTIFICATE_REQUIRED','NON_CA_LOCALHOST_LEAF_REQUIRED',
 'EXISTING_TLS_SECRET_PRESERVED','LOCAL_WINDOWS_VOLUME_REQUIRED',
 'VOLUME_UNAVAILABLE','VOLUME_ID_UNAVAILABLE','VOLUME_HEALTH_UNVERIFIED',
 'INVALID_DATA_ROOT','VOLUME_ID_REQUIRED','WRONG_VOLUME',
 'UNSUPPORTED_FILESYSTEM','UNHEALTHY_VOLUME','REPARSE_PATH_FORBIDDEN',
 'DATA_ROOT_REDIRECTED','DATABASE_MISSING','DATABASE_CORRUPT',
 'FOREIGN_KEY_VIOLATION','MIGRATION_REQUIRED','WAL_REQUIRED',
 'DATABASE_STATE_UNVERIFIED',
 'INTERACTIVE_SECRET_INPUT_REQUIRED','NGROK_AUTHTOKEN_FORMAT_INVALID','NETWORK_ACCESS_PASSWORD_TOO_SHORT',
})

def safe_error_code(error):
 code=str(error)
 if code in SAFE_ERROR_CODES:return code
 if isinstance(error,FileNotFoundError):return 'REQUIRED_CONFIGURATION_OR_FILE_MISSING'
 if isinstance(error,PermissionError):return 'LOCAL_PERMISSION_DENIED'
 from app.services.secrets_service import SecretStoreError,SafeStorageUnavailable
 if isinstance(error,SecretStoreError):return 'SECRET_STORE_UNREADABLE'
 if isinstance(error,SafeStorageUnavailable):return 'DPAPI_UNAVAILABLE'
 return 'UNCLASSIFIED_SETUP_FAILURE'

def approved_store(*, before_v21_migration=False):
 with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as k:
  root=Path(winreg.QueryValueEx(k,'GEULBIT_DATA_ROOT')[0]);volume=winreg.QueryValueEx(k,'GEULBIT_VOLUME_ID')[0]
 if root!=ROOT:raise RuntimeError('APPROVED_DATA_ROOT_REQUIRED')
 validate_volume(root,volume)
 database=root/'db/geulbit.sqlite3'
 if before_v21_migration:
  # Explicit local backup/migration bootstrap only. Normal startup still
  # requires the latest schema; never create a DB or relocate the key store.
  import sqlite3
  from contextlib import closing
  from app.storage import StorageBlocked,SCHEMA_HEAD
  from app.services.backup_service import verify_db
  if SCHEMA_HEAD!='0004_user_annotations' or not database.is_file() or database.is_symlink():raise StorageBlocked('V21_EXISTING_DATABASE_REQUIRED')
  with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as connection:
   if connection.execute('SELECT version_num FROM alembic_version').fetchall()!=[('0003_resource_ownership',)]:raise StorageBlocked('V21_PRE_MIGRATION_REVISION_REQUIRED')
   verify_db(connection,'0003_resource_ownership')
   if connection.execute('PRAGMA journal_mode').fetchone()!=('wal',):raise StorageBlocked('WAL_REQUIRED')
 else:check_database(database)
 return DpapiSecretStore(root/'operational/secrets.dat')

def prepare_session(store):
 if not store.contains('GEULBIT_SESSION_SIGNING_KEY'):store.set('GEULBIT_SESSION_SIGNING_KEY',secrets.token_urlsafe(48))
 if len(store.get('GEULBIT_SESSION_SIGNING_KEY'))<32:raise RuntimeError('SESSION_SECRET_TOO_SHORT')
 return {'sessionSecret':'REGISTERED_EXISTING_OR_GENERATED','storage':'DPAPI CurrentUser'}

def register_ngrok(store):
 if not sys.stdin.isatty():raise RuntimeError('INTERACTIVE_SECRET_INPUT_REQUIRED')
 if not store.contains('GEULBIT_NGROK_AUTHTOKEN'):
  token=getpass.getpass('ngrok Authtoken (hidden): ').strip()
  if not token or token.startswith('rd_') or any(c.isspace() for c in token):
   raise RuntimeError('NGROK_AUTHTOKEN_FORMAT_INVALID')
  store.set('GEULBIT_NGROK_AUTHTOKEN',token)
 if not store.contains('GEULBIT_NETWORK_ACCESS_KEY'):
  password=getpass.getpass('Private test access password, at least 16 characters (hidden): ')
  if len(password)<16:raise RuntimeError('NETWORK_ACCESS_PASSWORD_TOO_SHORT')
  store.set('GEULBIT_NETWORK_ACCESS_KEY',password)
 return {'ngrokAuthtoken':'REGISTERED_DPAPI','otherEntries':'PRESERVED'}

def register_google(store):
 if store.contains('GEULBIT_GOOGLE_CLIENT_ID') or store.contains('GEULBIT_GOOGLE_CLIENT_SECRET'):
  raise RuntimeError('EXISTING_GOOGLE_CREDENTIALS_PRESERVED')
 cid=getpass.getpass('Google Client ID (hidden): ').strip()
 if not cid.endswith('.apps.googleusercontent.com'):raise RuntimeError('GOOGLE_CLIENT_ID_FORMAT_INVALID')
 secret=getpass.getpass('Google Client Secret (hidden): ').strip()
 if not secret:raise RuntimeError('GOOGLE_CLIENT_SECRET_REQUIRED')
 # One atomic existing store save: preserve BAZE and all unrelated values.
 with store._lock:
  values=store._load();values.update(GEULBIT_GOOGLE_CLIENT_ID=cid,GEULBIT_GOOGLE_CLIENT_SECRET=secret);store._save(values)
 return {'googleCredentials':'REGISTERED_DPAPI','externalLogin':'NOT_ATTEMPTED'}

def replace_google_secret(store):
 # Operator-only explicit repair. No inference, generated credentials or reset.
 if not store.get('GEULBIT_GOOGLE_CLIENT_ID'):raise RuntimeError('GOOGLE_CLIENT_ID_FORMAT_INVALID')
 secret=getpass.getpass('Current Google Client Secret (hidden): ').strip()
 if not secret:raise RuntimeError('GOOGLE_CLIENT_SECRET_REQUIRED')
 with store._lock:
  values=store._load();values['GEULBIT_GOOGLE_CLIENT_SECRET']=secret;store._save(values)
 return {'googleClientSecret':'UPDATED_DPAPI','otherEntries':'PRESERVED','externalLogin':'NOT_ATTEMPTED'}

def prepare_tls(store,directory):
 from cryptography import x509
 from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
 from cryptography.hazmat.primitives import hashes,serialization
 from cryptography.hazmat.primitives.asymmetric import rsa
 directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
 paths=[directory/n for n in ['localhost.cert.pem','localhost.cert.cer','localhost.key.pem','tls.json']]
 if any(p.exists() for p in paths):
  if not all(p.is_file() for p in paths):raise RuntimeError('PARTIAL_TLS_STATE_PRESERVED')
  cert=x509.load_pem_x509_certificate(paths[0].read_bytes());manifest=json.loads(paths[3].read_text())
  if cert.fingerprint(hashes.SHA256()).hex()!=manifest['sha256'] or cert.not_valid_after_utc<=datetime.now(timezone.utc):raise RuntimeError('TLS_CERTIFICATE_STATE_INVALID')
  if cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)!=['localhost']:raise RuntimeError('LOCALHOST_CERTIFICATE_REQUIRED')
  if cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:raise RuntimeError('NON_CA_LOCALHOST_LEAF_REQUIRED')
  serialization.load_pem_private_key(paths[2].read_bytes(),password=store.get('GEULBIT_LOCAL_TLS_KEY_PASSWORD').encode())
  return manifest
 if store.contains('GEULBIT_LOCAL_TLS_KEY_PASSWORD'):raise RuntimeError('EXISTING_TLS_SECRET_PRESERVED')
 key=rsa.generate_private_key(public_exponent=65537,key_size=2048);name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Geulbit localhost development')]);now=datetime.now(timezone.utc)
 cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=90)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),critical=False).add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True).add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False).add_extension(x509.KeyUsage(digital_signature=True,key_encipherment=True,content_commitment=False,data_encipherment=False,key_agreement=False,key_cert_sign=False,crl_sign=False,encipher_only=None,decipher_only=None),critical=True).sign(key,hashes.SHA256()))
 password=secrets.token_urlsafe(48);store.set('GEULBIT_LOCAL_TLS_KEY_PASSWORD',password)
 for p,content in [(paths[0],cert.public_bytes(serialization.Encoding.PEM)),(paths[1],cert.public_bytes(serialization.Encoding.DER)),(paths[2],key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.BestAvailableEncryption(password.encode())))]:
  with p.open('xb') as f:f.write(content)
 manifest={'purpose':'localhost-only non-CA development leaf','sha256':cert.fingerprint(hashes.SHA256()).hex(),'thumbprint':cert.fingerprint(hashes.SHA1()).hex().upper(),'expiresAt':cert.not_valid_after_utc.isoformat(),'privateKey':'encrypted PKCS8; password in DPAPI','trustScope':'CurrentUser Root only'}
 with paths[3].open('x') as f:json.dump(manifest,f,indent=2)
 return manifest

def main():
 parser=argparse.ArgumentParser();parser.add_argument('command',choices=['status','google','google-secret','session','tls','ngrok']);args=parser.parse_args();store=approved_store()
 if args.command=='status':result={n:store.contains(n) for n in ['GEULBIT_GOOGLE_CLIENT_ID','GEULBIT_GOOGLE_CLIENT_SECRET','GEULBIT_SESSION_SIGNING_KEY']}
 elif args.command=='google':result=register_google(store)
 elif args.command=='google-secret':result=replace_google_secret(store)
 elif args.command=='session':result=prepare_session(store)
 elif args.command=='ngrok':result=register_ngrok(store)
 else:result=prepare_tls(store,ROOT/'operational/tls')
 print(json.dumps(result))
def run_cli():
 try:main()
 except Exception as e:
  print(json.dumps({'status':'BLOCKED','errorType':type(e).__name__,'errorCode':safe_error_code(e)}));return 1
 return 0

if __name__=='__main__':sys.exit(run_cli())
