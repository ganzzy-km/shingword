"""P14 lifecycle adapter. Reuses storage, auth and Waitress; never operating DB."""
import argparse
from contextlib import contextmanager, nullcontext
import hashlib
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import secrets
import sqlite3
import subprocess
import sys
import time
import threading
import winreg

import requests
from auth_setup import approved_store, ROOT
from app.storage import initialize_storage, check_database, validate_volume
from app.v2.network_gate import IsolatedNetworkGate
from app.v2.deployment import waitress_proxy_options

ORIGIN = "https://crushable-movie-usable.ngrok-free.dev"
HOST = "crushable-movie-usable.ngrok-free.dev"
CALLBACK = ORIGIN + "/api/auth/callback"
DEV_ROOT = ROOT / "temp" / "ngrok-dev-local"
OPERATING=False
BETA_TEST=False
BETA_ROOT=ROOT/'temp/ngrok-beta-local'

def active_root():return ROOT if OPERATING else BETA_ROOT if BETA_TEST else DEV_ROOT

STATE = ROOT / "operational" / "p14-state.json"
SCRIPT = Path(__file__).resolve()
UPSTREAM = "http://127.0.0.1:5070"


def identity():
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        return winreg.QueryValueEx(key, "GEULBIT_VOLUME_ID")[0]


def process_record(pid):
    # Kernel creation timestamp + image path prevent killing a recycled PID.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        creation, exit_time, system, user = (wintypes.FILETIME() for _ in range(4))
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        if not kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(system), ctypes.byref(user)):
            return None
        if exit_time.dwHighDateTime or exit_time.dwLowDateTime:
            return None
        path, length = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
        kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length)):
            return None
        return {"pid": pid, "created": (creation.dwHighDateTime << 32) | creation.dwLowDateTime, "image": path.value}
    finally:
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(handle)


def owned(record):
    return bool(record and process_record(record["pid"]) == record)


def stop_event(pid, *, create=False):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    name = "Local\\GeulbitP14Stop-" + str(pid)
    if create:
        kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateEventW.restype = wintypes.HANDLE
        handle = kernel.CreateEventW(None, False, False, name)
    else:
        kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.OpenEventW.restype = wintypes.HANDLE
        handle = kernel.OpenEventW(2, False, name)
    if not handle:
        raise RuntimeError("OWNED_PROCESS_STOP_FAILED")
    return kernel, handle


def read_state():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(value):
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    os.replace(temporary, STATE)


def stop():
    state = read_state()
    for name in ("tunnel", "server"):
        record = state.get(name)
        if owned(record):
            if name == "server":
                kernel, handle = stop_event(state.get("serverStopId", record["pid"]))
                kernel.SetEvent.argtypes = [wintypes.HANDLE]
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                try:
                    if not kernel.SetEvent(handle):
                        raise RuntimeError("OWNED_PROCESS_STOP_FAILED")
                finally:
                    kernel.CloseHandle(handle)
            else:
                subprocess.run(["taskkill", "/PID", str(record["pid"]), "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            for _ in range(30):
                if not owned(record):
                    break
                time.sleep(.2)
            if owned(record):
                raise RuntimeError("OWNED_PROCESS_STOP_FAILED")
    save_state({"status": "STOPPED", "origin": ORIGIN})
    return {"status": "STOPPED", "origin": ORIGIN}


def fetch(url, store, *, local=False, path="/api/health", authenticated=True):
    headers = {"ngrok-skip-browser-warning": "1"}
    if local:
        headers.update(Host=HOST, **{"X-Forwarded-Proto": "https"})
    if authenticated:
        value = ("geulbit:" + store.get("GEULBIT_NETWORK_ACCESS_KEY")).encode()
        headers["Authorization"] = "Basic " + base64.b64encode(value).decode()
    return requests.get(url + path, headers=headers, timeout=5, allow_redirects=False)


def status():
    store = approved_store()
    state = read_state()
    mode=state.get('mode','isolated')
    # stop() intentionally drops process/mode records. Only a proven stopped
    # state may use the requested CLI mode; never reclassify a running service.
    if ('mode' not in state and state.get('status')=='STOPPED'
            and not owned(state.get('server')) and not owned(state.get('tunnel'))):
        mode='operating' if OPERATING else 'beta-test' if BETA_TEST else 'isolated'
    root=ROOT if mode=='operating' else BETA_ROOT if mode=='beta-test' else DEV_ROOT
    result = {"origin": ORIGIN, "upstream": UPSTREAM, "mode":mode,"dataRoot":str(root),
              "ngrokRegistered": store.contains("GEULBIT_NGROK_AUTHTOKEN"),
              "privateAccessRegistered": store.contains("GEULBIT_NETWORK_ACCESS_KEY"),
              "entryAuthentication": "GOOGLE_ONLY" if mode=='operating' else "BASIC_AND_GOOGLE",
              "serverPid": state.get("server", {}).get("pid") if owned(state.get("server")) else None,
              "tunnelPid": state.get("tunnel", {}).get("pid") if owned(state.get("tunnel")) else None}
    if result["serverPid"]:
        try:
            result["localHealth"] = fetch(UPSTREAM, store, local=True).status_code
        except requests.RequestException:
            result["localHealth"] = "UNAVAILABLE"
    if result["tunnelPid"]:
        try:
            result["externalHealth"] = fetch(ORIGIN, store).status_code
        except requests.RequestException:
            result["externalHealth"] = "UNAVAILABLE"
    return result


def prepare():
    if OPERATING:raise RuntimeError("OPERATING_INITIALIZATION_FORBIDDEN")
    approved_store()
    validate_volume(active_root(), identity())
    if active_root().exists():
        check_database(active_root() / "db" / "geulbit.sqlite3")
        return {"isolatedStorage": "EXISTING_PRESERVED"}
    initialize_storage(active_root(), identity())
    return {"isolatedStorage": "EXPLICITLY_INITIALIZED", "operatingStorage": "UNCHANGED"}


def settings():
    return {"GEULBIT_PUBLIC_ORIGIN": ORIGIN, "GEULBIT_GOOGLE_REDIRECT_URI": CALLBACK,
            "GEULBIT_TRUSTED_PROXY": "127.0.0.1", "GEULBIT_SESSION_MAX_AGE": "3600",
            "GEULBIT_OIDC_STATE_TTL": "300", "GEULBIT_GOOGLE_EXTERNAL_APPROVED": "1"}


def safety_preflight(maintenance=False):
    root = active_root().resolve()
    if not OPERATING and (root.parent != (ROOT / "temp").resolve() or root.name not in {"ngrok-dev-local","ngrok-beta-local"}):
        raise RuntimeError("ISOLATED_NETWORK_ROOT_REQUIRED")
    if OPERATING:
        if root!=ROOT.resolve():raise RuntimeError("EXACT_OPERATING_ROOT_REQUIRED")
        from app.v2.beta_runtime import operating_configuration
        operating_configuration(ROOT,SCRIPT.parent.parent,require_fresh_backup=not maintenance)
    validate_volume(root, identity())
    check_database(root / "db" / "geulbit.sqlite3")
    with sqlite3.connect((root / "db" / "geulbit.sqlite3").as_uri() + "?mode=ro", uri=True) as connection:
        setting = connection.execute("SELECT value FROM app_settings WHERE key='ai_enabled'").fetchone()
        if setting and json.loads(setting[0]) is True:
            raise RuntimeError("EXTERNAL_AI_MUST_BE_DISABLED")
    return {"isolation": not OPERATING, "debug": False, "externalAI": False, "scheduledDeletion": OPERATING}


def service_app(maintenance=False):
    from app import create_app
    store = approved_store()
    safety_preflight(maintenance=maintenance)
    os.environ.update(settings())
    config={"DATA_ROOT": str(active_root()), "VOLUME_ID": identity(), "GEULBIT_V2": True,
                      "SECRET_STORE": store, "SESSION_MAX_AGE": 3600,
                      "ISOLATED_GOOGLE_ACCOUNT": "ps25090@onedu.jje.go.kr",
                      "EXTERNAL_AI_TERMS_APPROVED": False, "AI_PROVIDER": None}
    if OPERATING:
        from app.v2.beta_runtime import operating_configuration
        config.update(operating_configuration(ROOT,SCRIPT.parent.parent,require_fresh_backup=not maintenance));config.pop("ISOLATED_GOOGLE_ACCOUNT")
    elif BETA_TEST:
        policy=json.loads((SCRIPT.parent.parent/"backend/config/privacy.example.json").read_text(encoding="utf-8"))
        config.update(BETA_SIGNUP_ENABLED=True,BETA_SIGNUP_POLICY=policy["betaSignup"]["policy"])
    if OPERATING:
        config['GOOGLE_LOGIN_ON_LANDING']=True
        config['GEULBIT_S4_ENGINE']=True
    app = create_app(config)
    app.debug = False
    return app, store


def bootstrap_admin():
    from app.models import User
    from run_auth_dev import bootstrap_designated_admin
    if OPERATING:raise RuntimeError("OPERATING_BOOTSTRAP_REQUIRES_EXPLICIT_LOCAL_VERIFIED_SUB")
    app, _ = service_app()
    with app.app_context():
        user = User.query.filter_by(oidc_issuer="https://accounts.google.com", email="ps25090@onedu.jje.go.kr", email_verified=True).one_or_none()
        if not user or not user.oidc_subject:
            raise RuntimeError("VERIFIED_DESIGNATED_GOOGLE_ACCOUNT_REQUIRED")
        bootstrap_designated_admin(app, user.oidc_subject, "ps25090@onedu.jje.go.kr")
    return {"adminBootstrap": "COMPLETED_ISOLATED_ONLY"}


def serve():
    from waitress import create_server
    app, store = service_app()
    app.wsgi_app = IsolatedNetworkGate(app.wsgi_app, HOST, store.get("GEULBIT_NETWORK_ACCESS_KEY"),google_only=OPERATING)
    server = create_server(app, host="127.0.0.1", port=5070, threads=6, **waitress_proxy_options(settings()))
    kernel, handle = stop_event(os.environ.get("GEULBIT_P14_STOP_ID", os.getpid()), create=True)
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    def watch_stop():
        if kernel.WaitForSingleObject(handle, 0xFFFFFFFF) == 0:
            server.close()
            server.task_dispatcher.shutdown(timeout=5)
            while server.task_dispatcher.threads:
                time.sleep(.1)  # Preserve an in-flight write; never force-kill it.
            server.asyncore.close_all(map=server._map)
    threading.Thread(target=watch_stop, daemon=True).start()
    try:
        server.run()
    finally:
        server.close()
        kernel.CloseHandle(handle)


def spawn(args, *, env=None):
    process = subprocess.Popen(args, cwd=SCRIPT.parent.parent, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(20):
        record = process_record(process.pid)
        if record:
            return record
        if process.poll() is not None:
            break
        time.sleep(.1)
    raise RuntimeError("CHILD_START_FAILED")


def start(local_only=False):
    store = approved_store()
    state = read_state()
    if owned(state.get("server")):
        if local_only or owned(state.get("tunnel")):
            return status()
        raise RuntimeError("LOCAL_SERVER_RUNNING_STOP_BEFORE_FULL_START")
    if owned(state.get("tunnel")):
        raise RuntimeError("OWNED_TUNNEL_ALREADY_RUNNING")
    safety_preflight()
    if not store.contains("GEULBIT_NETWORK_ACCESS_KEY"):
        raise RuntimeError("PRIVATE_ACCESS_SETUP_REQUIRED")
    if not (SCRIPT.parent.parent / "dist" / "index.html").is_file():
        raise RuntimeError("FRONTEND_BUILD_REQUIRED")
    ngrok = shutil.which("ngrok")
    if not local_only and (not ngrok or not store.contains("GEULBIT_NGROK_AUTHTOKEN")):
        raise RuntimeError("NGROK_SETUP_REQUIRED")
    import socket
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 5070)) == 0:
            raise RuntimeError("PORT_5070_ALREADY_IN_USE")
    state = {"origin": ORIGIN, "upstream": UPSTREAM,"mode":"operating" if OPERATING else "beta-test" if BETA_TEST else "isolated"}
    try:
        # Windows venv python may be a launcher with a separate worker PID.
        # Share an event identifier, independent of either process's PID.
        state["serverStopId"] = secrets.token_hex(16)
        server_env = os.environ.copy()
        server_env["GEULBIT_P14_STOP_ID"] = state["serverStopId"]
        state["server"] = spawn([sys.executable, str(SCRIPT), "serve"]+(["--operating"] if OPERATING else ["--beta-test"] if BETA_TEST else []), env=server_env)
        save_state(state)
        for _ in range(30):
            if not owned(state["server"]):
                raise RuntimeError("SERVER_START_FAILED")
            try:
                if fetch(UPSTREAM, store, local=True).status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(.2)
        else:
            raise RuntimeError("LOCAL_HEALTH_FAILED")
        if fetch(UPSTREAM, store, local=True, authenticated=False).status_code != (200 if OPERATING else 401):
            raise RuntimeError("PRIVATE_ACCESS_GATE_FAILED")
        if OPERATING and fetch(UPSTREAM,store,local=True,path='/api/writings',authenticated=False).status_code!=401:
            raise RuntimeError("PRIVATE_ACCESS_GATE_FAILED")
        if local_only:
            return status()
        config = ROOT / "operational" / "p14-ngrok.yml"
        config.write_text('version: "3"\nagent:\n  web_addr: false\n  remote_management: false\n  update_check: false\n', encoding="utf-8")
        env = os.environ.copy()
        env["NGROK_AUTHTOKEN"] = store.get("GEULBIT_NGROK_AUTHTOKEN")
        state["tunnel"] = spawn([ngrok, "http", UPSTREAM, "--url", ORIGIN, "--inspect=false", "--config", str(config)], env=env)
        save_state(state)
        for _ in range(20):
            if not owned(state["tunnel"]):
                raise RuntimeError("NGROK_CONNECTION_FAILED")
            try:
                if fetch(ORIGIN, store).status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(.5)
        else:
            raise RuntimeError("EXTERNAL_HEALTH_FAILED")
        if fetch(ORIGIN, store, authenticated=False).status_code != (200 if OPERATING else 401):
            raise RuntimeError("EXTERNAL_ACCESS_GATE_FAILED")
        if OPERATING and fetch(ORIGIN,store,path='/api/writings',authenticated=False).status_code!=401:
            raise RuntimeError("EXTERNAL_ACCESS_GATE_FAILED")
        return status()
    except Exception:
        stop()
        raise


def maintenance_cycle():
    if not OPERATING:raise RuntimeError("OPERATING_MODE_REQUIRED")
    # One-shot copy retry is independent of DB/server lifetime and never starts
    # Waitress/ngrok. Missing or unplugged external storage cannot block upkeep.
    from app.services.external_backup import dispatch
    dispatch(ROOT,SCRIPT.parent/'privacy_service.py')
    safety_preflight(maintenance=True)
    state=read_state()
    if state.get('mode')!='operating' or not owned(state.get('server')):return {'status':'NOT_RUNNING_NO_AUTOSTART'}
    stop()
    app,_=service_app(maintenance=True)
    try:
        from app.v2.operations_api import purge_due_essays
        from app.v2.privacy_lifecycle import purge_due_documents,purge_due_rubrics,retry_files,prune_audit
        from app.extensions import db
        with app.app_context():
            essays=purge_due_essays(app);documents=purge_due_documents();rubrics=purge_due_rubrics();pending=retry_files();prune_audit();accounts=app.extensions.get('account_retention_result',{})
            db.session.remove();db.engine.dispose()
        if documents.get('blocked') or rubrics.get('blocked') or pending or accounts.get('blocked'):raise RuntimeError('RETENTION_INCOMPLETE_SERVICE_STOPPED')
    finally:
        app.extensions['storage_writer_lease'].close()
    # Existing backup CLI obtains exclusive lease and issues durable verified receipt.
    result=subprocess.run([sys.executable,str(SCRIPT.parent/'privacy_service.py'),'backup'],capture_output=True,text=True,timeout=120,check=False)
    if result.returncode:raise RuntimeError('BACKUP_FAILED_SERVICE_STOPPED')
    start()
    return {'status':'PASS','essaysRemoved':essays,'documents':documents,'backup':'VERIFIED_OR_NOT_DUE','server':'RESTARTED'}


def scheduler_install():
    if not OPERATING:raise RuntimeError('OPERATING_MODE_REQUIRED')
    safety_preflight()
    # Native Windows scheduler, owned task only; no secrets in action arguments.
    python=str(Path(sys.executable).resolve()).replace("'","''");script=str(SCRIPT).replace("'","''")
    command=f'$action=New-ScheduledTaskAction -Execute \'{python}\' -Argument \'"{script}" maintenance-cycle --operating\'; $trigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddHours(1) -RepetitionInterval (New-TimeSpan -Hours 1); $settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10); Register-ScheduledTask -TaskName \'GeulbitPrivateBetaMaintenance\' -Action $action -Trigger $trigger -Settings $settings -Description \'Geulbit approved private beta retention and daily verified local backup\' -Force | Out-Null'
    guard=f'$old=Get-ScheduledTask -TaskName \'GeulbitPrivateBetaMaintenance\' -ErrorAction SilentlyContinue; if ($old -and ($old.Actions.Count -ne 1 -or $old.Actions[0].Execute -ne \'{python}\' -or $old.Actions[0].Arguments -ne \'"{script}" maintenance-cycle --operating\')) {{ throw \'TASK_OWNERSHIP_CONFLICT\' }}; '
    verify=f'$saved=Get-ScheduledTask -TaskName \'GeulbitPrivateBetaMaintenance\' -ErrorAction Stop; if (-not $saved.Settings.Enabled -or $saved.Actions[0].Execute -ne \'{python}\' -or $saved.Actions[0].Arguments -ne \'"{script}" maintenance-cycle --operating\') {{ throw \'TASK_REGISTRATION_NOT_VERIFIED\' }}'
    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',"$ErrorActionPreference='Stop'; "+guard+command+'; '+verify],capture_output=True,timeout=30,check=True)
    return {'scheduler':'REGISTERED_CURRENT_USER_ONLY','intervalMinutes':60,'backupFrequencyHours':24}


@contextmanager
def lifecycle_lock(timeout_ms=180000):
    """Serialize CLI maintenance and manual STOP; crash releases the OS mutex."""
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateMutexW.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.ReleaseMutex.argtypes=[wintypes.HANDLE]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    name='Local\\GeulbitLifecycle-'+hashlib.sha256(str(ROOT.resolve()).encode()).hexdigest()
    handle=kernel.CreateMutexW(None,False,name)
    if not handle:raise RuntimeError('LIFECYCLE_LOCK_UNAVAILABLE')
    acquired=False
    try:
        acquired=kernel.WaitForSingleObject(handle,timeout_ms) in (0,128)
        if not acquired:raise RuntimeError('LIFECYCLE_OPERATION_BUSY')
        yield
    finally:
        if acquired:kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def execute_command(command):
    if command=="maintenance-cycle":return maintenance_cycle()
    if command=="scheduler-install":return scheduler_install()
    if command=="restart":
        stop()
        return start()
    return {"prepare":prepare,"start":start,"start-local":lambda:start(True),"status":status,"stop":stop,"bootstrap-admin":bootstrap_admin}[command]()


def main():
    global OPERATING,BETA_TEST
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "start", "start-local", "status", "stop", "restart", "serve", "bootstrap-admin", "maintenance-cycle", "scheduler-install"])
    parser.add_argument("--operating",action="store_true");parser.add_argument("--beta-test",action="store_true")
    args = parser.parse_args();OPERATING=args.operating;BETA_TEST=args.beta_test
    if OPERATING and BETA_TEST:raise RuntimeError("EXCLUSIVE_SERVICE_MODE_REQUIRED")
    if args.command == "serve":
        serve()
        return
    serialized={'prepare','start','start-local','stop','restart','maintenance-cycle'}
    with lifecycle_lock() if args.command in serialized else nullcontext():
        result=execute_command(args.command)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never print exception text: requests/CLI errors may contain secrets.
        codes = {"CHILD_START_FAILED", "PRIVATE_ACCESS_SETUP_REQUIRED", "FRONTEND_BUILD_REQUIRED", "NGROK_SETUP_REQUIRED",
                 "ISOLATED_NETWORK_ROOT_REQUIRED", "EXTERNAL_AI_MUST_BE_DISABLED",
                 "VERIFIED_DESIGNATED_GOOGLE_ACCOUNT_REQUIRED",
                 "LIFECYCLE_LOCK_UNAVAILABLE", "LIFECYCLE_OPERATION_BUSY",
                 "PORT_5070_ALREADY_IN_USE", "SERVER_START_FAILED", "LOCAL_HEALTH_FAILED", "PRIVATE_ACCESS_GATE_FAILED",
                 "NGROK_CONNECTION_FAILED", "EXTERNAL_HEALTH_FAILED", "EXTERNAL_ACCESS_GATE_FAILED",
                 "LOCAL_SERVER_RUNNING_STOP_BEFORE_FULL_START", "OWNED_TUNNEL_ALREADY_RUNNING", "OWNED_PROCESS_STOP_FAILED"}
        code = str(error) if str(error) in codes else "NETWORK_CONFIGURATION_BLOCKED"
        print(json.dumps({"status": "BLOCKED", "errorCode": code}))
        sys.exit(1)
