import os,sys
from pathlib import Path
from flask import Flask
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]))
from app.v2.server_secrets import load_auth_secrets
from app.services.secrets_service import MemorySecretStore
from auth_setup import prepare_session,prepare_tls
from run_auth_dev import validate_dev_root

def test_auth_secret_loader_preserves_store_and_does_not_generate(monkeypatch):
 for k in ['GEULBIT_SESSION_SIGNING_KEY','GEULBIT_GOOGLE_CLIENT_ID','GEULBIT_GOOGLE_CLIENT_SECRET']:monkeypatch.delenv(k,raising=False)
 s=MemorySecretStore({'BAZE_API_KEY':'synthetic-baze','GEULBIT_SESSION_SIGNING_KEY':'synthetic-only-0000000000000000000000','GEULBIT_GOOGLE_CLIENT_ID':'synthetic-client','GEULBIT_GOOGLE_CLIENT_SECRET':'synthetic-secret'})
 before=dict(s.values);a=Flask(__name__);a.config['SECRET_STORE']=s;load_auth_secrets(a)
 assert a.config['GOOGLE_CLIENT_SECRET']=='synthetic-secret' and s.values==before

def test_testing_never_loads_operational_secrets():
 class Forbidden:
  def get(self,k):raise AssertionError('operating secret accessed')
 a=Flask(__name__);a.config.update(TESTING=True,SECRET_STORE=Forbidden());load_auth_secrets(a)
 assert not a.config.get('GOOGLE_CLIENT_SECRET')

def test_environment_precedence_no_runtime_secret_creation(monkeypatch):
 monkeypatch.setenv('GEULBIT_GOOGLE_CLIENT_SECRET','synthetic-environment')
 a=Flask(__name__);s=MemorySecretStore();a.config['SECRET_STORE']=s;load_auth_secrets(a)
 assert a.config['GOOGLE_CLIENT_SECRET']=='synthetic-environment' and not a.config['SESSION_SIGNING_KEY'] and not s.values

def test_session_generation_preserves_existing_credentials():
 s=MemorySecretStore({'BAZE_API_KEY':'synthetic-baze'});prepare_session(s);v=s.get('GEULBIT_SESSION_SIGNING_KEY');assert len(v)>=32;prepare_session(s);assert s.get('GEULBIT_SESSION_SIGNING_KEY')==v and s.get('BAZE_API_KEY')=='synthetic-baze'

@pytest.mark.parametrize('root',['C:/Users/USER/GeulbitData','C:/Users/USER/GeulbitData/temp/v2-qa-test','C:/Users/USER/GeulbitData/temp/oidc-dev-test/../bad','C:/other/oidc-dev-test'])
def test_development_service_refuses_operational_or_unapproved_root(root):
 with pytest.raises(RuntimeError):validate_dev_root(root)

def test_tls_key_encrypted_localhost_leaf_and_existing_state_preserved(tmp_path):
 from cryptography import x509
 from cryptography.hazmat.primitives import serialization
 s=MemorySecretStore();m=prepare_tls(s,tmp_path);key=(tmp_path/'localhost.key.pem').read_bytes();assert b'ENCRYPTED PRIVATE KEY' in key
 with pytest.raises(TypeError):serialization.load_pem_private_key(key,password=None)
 cert=x509.load_pem_x509_certificate((tmp_path/'localhost.cert.pem').read_bytes());assert not cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
 assert cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)==['localhost']
 assert prepare_tls(s,tmp_path)==m

def test_partial_tls_material_never_overwritten(tmp_path):
 (tmp_path/'localhost.cert.pem').write_text('preserve-existing')
 with pytest.raises(RuntimeError):prepare_tls(MemorySecretStore(),tmp_path)
 assert (tmp_path/'localhost.cert.pem').read_text()=='preserve-existing'

@pytest.mark.parametrize('code',['APPROVED_DATA_ROOT_REQUIRED','WRONG_VOLUME','DATA_ROOT_REDIRECTED','MIGRATION_REQUIRED'])
def test_pre_prompt_block_reports_only_safe_code(monkeypatch,capsys,code):
 import auth_setup as setup,json
 monkeypatch.setattr(sys,'argv',['auth_setup.py','google'])
 def blocked():raise RuntimeError(code)
 def forbidden(*args):raise AssertionError('Input must not be requested before storage approval')
 monkeypatch.setattr(setup,'approved_store',blocked);monkeypatch.setattr(setup.getpass,'getpass',forbidden)
 assert setup.run_cli()==1
 assert json.loads(capsys.readouterr().out)=={'status':'BLOCKED','errorType':'RuntimeError','errorCode':code}

def test_unknown_exception_diagnostic_never_discloses_text(monkeypatch,capsys):
 import auth_setup as setup,json
 monkeypatch.setattr(sys,'argv',['auth_setup.py','google'])
 def blocked():raise RuntimeError('synthetic-secret-and-sensitive-path')
 monkeypatch.setattr(setup,'approved_store',blocked)
 assert setup.run_cli()==1
 output=capsys.readouterr().out;assert 'synthetic-secret' not in output
 assert json.loads(output)['errorCode']=='UNCLASSIFIED_SETUP_FAILURE'

def test_existing_google_credentials_block_before_prompt_and_preserve_store(monkeypatch):
 import auth_setup as setup
 s=MemorySecretStore({'GEULBIT_GOOGLE_CLIENT_ID':'synthetic','BAZE_API_KEY':'synthetic-baze','GEULBIT_SESSION_SIGNING_KEY':'synthetic-session'});before=dict(s.values)
 def forbidden(*args):raise AssertionError('Existing credentials must be preserved before prompting')
 monkeypatch.setattr(setup.getpass,'getpass',forbidden)
 with pytest.raises(RuntimeError,match='EXISTING_GOOGLE_CREDENTIALS_PRESERVED'):setup.register_google(s)
 assert s.values==before

@pytest.mark.parametrize('inputs,code',[
 (['synthetic-invalid-client'],'GOOGLE_CLIENT_ID_FORMAT_INVALID'),
 (['synthetic.apps.googleusercontent.com',''],'GOOGLE_CLIENT_SECRET_REQUIRED'),
])
def test_invalid_google_input_identifies_field_without_values_or_writes(monkeypatch,capsys,inputs,code):
 import auth_setup as setup,json
 s=MemorySecretStore({'BAZE_API_KEY':'synthetic-baze','GEULBIT_SESSION_SIGNING_KEY':'synthetic-session'});before=dict(s.values);answers=iter(inputs)
 monkeypatch.setattr(sys,'argv',['auth_setup.py','google']);monkeypatch.setattr(setup,'approved_store',lambda:s)
 monkeypatch.setattr(setup.getpass,'getpass',lambda *args:next(answers))
 assert setup.run_cli()==1
 output=capsys.readouterr().out;assert 'synthetic' not in output and s.values==before
 assert json.loads(output)['errorCode']==code

@pytest.mark.parametrize('secret',['synthetic-new-secret',''])
def test_explicit_google_secret_repair_preserves_all_other_entries(monkeypatch,secret):
 import auth_setup as setup,threading
 class Store(MemorySecretStore):
  _lock=threading.RLock()
  def _load(self):return dict(self.values)
  def _save(self,values):self.values=dict(values)
 s=Store({'GEULBIT_GOOGLE_CLIENT_ID':'synthetic.apps.googleusercontent.com','GEULBIT_GOOGLE_CLIENT_SECRET':'synthetic-old-secret','BAZE_API_KEY':'synthetic-baze','GEULBIT_SESSION_SIGNING_KEY':'synthetic-session'});before=dict(s.values)
 monkeypatch.setattr(setup.getpass,'getpass',lambda *args:secret)
 if secret:
  setup.replace_google_secret(s);assert s.values=={**before,'GEULBIT_GOOGLE_CLIENT_SECRET':secret}
 else:
  with pytest.raises(RuntimeError,match='GOOGLE_CLIENT_SECRET_REQUIRED'):setup.replace_google_secret(s)
  assert s.values==before

def test_bootstrap_cli_uses_explicit_isolated_app():
 import click
 from flask import current_app
 from run_auth_dev import bootstrap_designated_admin
 app=Flask('synthetic-isolated-bootstrap');seen=[]
 @app.cli.command('bootstrap-admin')
 @click.option('--issuer')
 @click.option('--subject')
 @click.option('--confirm-account')
 def bootstrap(issuer,subject,confirm_account):
  assert current_app._get_current_object() is app
  seen.append((issuer,subject,confirm_account))
 bootstrap_designated_admin(app,'synthetic-verified-sub','ps25090@onedu.jje.go.kr')
 assert seen==[('https://accounts.google.com','synthetic-verified-sub','ps25090@onedu.jje.go.kr')]

def test_bootstrap_cli_refuses_different_admin_candidate():
 from run_auth_dev import bootstrap_designated_admin
 with pytest.raises(RuntimeError,match='USER_DESIGNATED_ADMIN_REQUIRED'):
  bootstrap_designated_admin(Flask('synthetic'),'synthetic-sub','other@example.invalid')
