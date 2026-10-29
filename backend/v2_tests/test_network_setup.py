import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))
import pytest
import auth_setup
import network_service
from app.services.secrets_service import MemorySecretStore

def test_manual_stop_waits_until_maintenance_restart_finishes(monkeypatch,tmp_path):
    import threading
    monkeypatch.setattr(network_service,'ROOT',tmp_path)
    held=threading.Event();release=threading.Event();order=[];errors=[]
    def maintenance():
        try:
            with network_service.lifecycle_lock(3000):
                order.append('maintenance-stop');held.set()
                assert release.wait(3)
                order.append('maintenance-restart')
        except BaseException as error:errors.append(error)
    def manual_stop():
        try:
            with network_service.lifecycle_lock(3000):order.append('manual-stop')
        except BaseException as error:errors.append(error)
    first=threading.Thread(target=maintenance);first.start();assert held.wait(3)
    second=threading.Thread(target=manual_stop);second.start()
    release.set();first.join(4);second.join(4)
    assert not first.is_alive() and not second.is_alive() and not errors
    assert order==['maintenance-stop','maintenance-restart','manual-stop']

def test_lifecycle_busy_fails_before_operation_and_releases(monkeypatch,tmp_path):
    import threading
    monkeypatch.setattr(network_service,'ROOT',tmp_path)
    errors=[]
    def contender():
        try:
            with network_service.lifecycle_lock(0):errors.append('unsafe-entry')
        except RuntimeError as error:errors.append(str(error))
    with network_service.lifecycle_lock():
        thread=threading.Thread(target=contender);thread.start();thread.join(3)
    assert errors==['LIFECYCLE_OPERATION_BUSY']
    with network_service.lifecycle_lock(0):pass

def test_stop_and_maintenance_cli_share_lifecycle_barrier(monkeypatch,capsys):
    from contextlib import contextmanager
    monkeypatch.setattr(network_service,'OPERATING',False)
    monkeypatch.setattr(network_service,'BETA_TEST',False)
    order=[]
    @contextmanager
    def lock():
        order.append('locked');yield;order.append('released')
    monkeypatch.setattr(network_service,'lifecycle_lock',lock)
    monkeypatch.setattr(network_service,'execute_command',lambda command:order.append(command) or {})
    for command in ['stop','maintenance-cycle','restart']:
        monkeypatch.setattr(sys,'argv',['network_service.py',command,'--operating'])
        network_service.main()
        assert order[-3:]==['locked',command,'released']

def test_cli_mode_reaches_worker_and_modes_are_exclusive(monkeypatch,capsys):
    monkeypatch.setattr(network_service,'OPERATING',False)
    monkeypatch.setattr(network_service,'BETA_TEST',False)
    monkeypatch.setattr(sys,'argv',['network_service.py','status','--operating'])
    monkeypatch.setattr(network_service,'status',lambda:{'operating':network_service.OPERATING})
    network_service.main();assert 'true' in capsys.readouterr().out
    monkeypatch.setattr(sys,'argv',['network_service.py','status','--operating','--beta-test'])
    with pytest.raises(RuntimeError,match='EXCLUSIVE_SERVICE_MODE'):network_service.main()

def test_maintenance_never_autostarts_a_stopped_service(monkeypatch):
    monkeypatch.setattr(network_service,'OPERATING',True)
    seen=[];monkeypatch.setattr(network_service,'safety_preflight',lambda **kwargs:seen.append(kwargs))
    monkeypatch.setattr(network_service,'read_state',lambda:{'mode':'operating'})
    monkeypatch.setattr(network_service,'start',lambda:pytest.fail('Unapproved autostart'))
    assert network_service.maintenance_cycle()=={'status':'NOT_RUNNING_NO_AUTOSTART'}
    assert seen==[{'maintenance':True}]

def test_scheduler_errors_never_report_registration_success(monkeypatch):
    import subprocess
    monkeypatch.setattr(network_service,'OPERATING',True)
    monkeypatch.setattr(network_service,'safety_preflight',lambda:None)
    seen=[]
    def reject(args,**kwargs):
        seen.append(args[-1]);assert kwargs['check'] is True
        raise subprocess.CalledProcessError(1,args)
    monkeypatch.setattr(network_service.subprocess,'run',reject)
    with pytest.raises(subprocess.CalledProcessError):network_service.scheduler_install()
    assert "$ErrorActionPreference='Stop'" in seen[0]
    assert 'TASK_OWNERSHIP_CONFLICT' in seen[0] and 'TASK_REGISTRATION_NOT_VERIFIED' in seen[0]


def test_hidden_registration_preserves_other_secrets(monkeypatch):
    store=MemorySecretStore()
    for key in ['GOOGLE_TEST','BAZE_TEST','SESSION_TEST']:store.set(key,'synthetic-existing')
    values=iter(['synthetic-ngrok-authtoken','synthetic-network-password'])
    monkeypatch.setattr(auth_setup.sys.stdin,'isatty',lambda:True)
    monkeypatch.setattr(auth_setup.getpass,'getpass',lambda _:next(values))
    assert auth_setup.register_ngrok(store)['otherEntries']=='PRESERVED'
    for key in ['GOOGLE_TEST','BAZE_TEST','SESSION_TEST']:assert store.get(key)=='synthetic-existing'
    assert store.contains('GEULBIT_NGROK_AUTHTOKEN') and store.contains('GEULBIT_NETWORK_ACCESS_KEY')
    monkeypatch.setattr(auth_setup.getpass,'getpass',lambda _:pytest.fail('Existing secrets must not prompt'))
    auth_setup.register_ngrok(store)


def test_resource_identifier_not_accepted_as_token(monkeypatch):
    store=MemorySecretStore()
    monkeypatch.setattr(auth_setup.sys.stdin,'isatty',lambda:True)
    monkeypatch.setattr(auth_setup.getpass,'getpass',lambda _:'rd_synthetic')
    with pytest.raises(RuntimeError,match='NGROK_AUTHTOKEN_FORMAT_INVALID'):auth_setup.register_ngrok(store)
    assert not store.contains('GEULBIT_NGROK_AUTHTOKEN')


def test_process_identity_prevents_recycled_pid_stop(monkeypatch):
    record={'pid':100,'created':123,'image':'synthetic.exe'}
    monkeypatch.setattr(network_service,'process_record',lambda _:dict(record,created=456))
    assert not network_service.owned(record)
    monkeypatch.setattr(network_service,'process_record',lambda _:record)
    assert network_service.owned(record)


def test_existing_isolated_storage_never_initialized(monkeypatch,tmp_path):
    monkeypatch.setattr(network_service,'DEV_ROOT',tmp_path)
    monkeypatch.setattr(network_service,'approved_store',lambda:None)
    monkeypatch.setattr(network_service,'identity',lambda:'synthetic-volume')
    monkeypatch.setattr(network_service,'validate_volume',lambda *args:None)
    checked=[]
    monkeypatch.setattr(network_service,'check_database',lambda path:checked.append(path))
    monkeypatch.setattr(network_service,'initialize_storage',lambda *args:pytest.fail('Reinitialization forbidden'))
    assert network_service.prepare()['isolatedStorage']=='EXISTING_PRESERVED'
    assert checked==[tmp_path/'db/geulbit.sqlite3']


def test_process_scoped_origin_never_overwrites_localhost_settings():
    assert network_service.settings()['GEULBIT_GOOGLE_REDIRECT_URI']=='https://crushable-movie-usable.ngrok-free.dev/api/auth/callback'
    assert network_service.settings()['GEULBIT_TRUSTED_PROXY']=='127.0.0.1'
    assert network_service.DEV_ROOT!=auth_setup.ROOT


def test_launcher_and_worker_share_stop_event(monkeypatch):
    import socket
    from types import SimpleNamespace
    store=MemorySecretStore()
    store.set('GEULBIT_NETWORK_ACCESS_KEY','synthetic-network-password')
    monkeypatch.setattr(network_service,'approved_store',lambda:store)
    monkeypatch.setattr(network_service,'read_state',lambda:{})
    monkeypatch.setattr(network_service,'safety_preflight',lambda:None)
    monkeypatch.setattr(network_service,'owned',lambda record:bool(record))
    monkeypatch.setattr(network_service,'status',lambda:{'status':'LOCAL_TEST'})
    saved=[]; spawned=[]
    monkeypatch.setattr(network_service,'save_state',lambda state:saved.append(dict(state)))
    def spawn(args,*,env=None):
        spawned.append(env)
        return {'pid':123,'created':456,'image':'synthetic-launcher'}
    monkeypatch.setattr(network_service,'spawn',spawn)
    monkeypatch.setattr(network_service,'fetch',lambda *args,**kwargs:SimpleNamespace(status_code=200 if kwargs.get('authenticated',True) else 401))
    class FreeSocket:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def connect_ex(self,address):return 1
    monkeypatch.setattr(socket,'socket',lambda:FreeSocket())
    assert network_service.start(local_only=True)=={'status':'LOCAL_TEST'}
    stop_id=saved[0]['serverStopId']
    assert spawned[0]['GEULBIT_P14_STOP_ID']==stop_id
    assert len(stop_id)==32 and stop_id!='123'
