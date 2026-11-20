"""Run the existing STAGING adapter on a disposable synthetic clone and port."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import threading
import time


REPO = Path(__file__).resolve().parents[2]
SOURCE = Path('C:/Users/USER/GeulbitStagingData')
BASE = 'https://factchat-cloud.mindlogic.ai/v1/gateway'
PORT = 8796
sys.path.insert(0, str(REPO / 'backend'))


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(directory):
    return {p.relative_to(directory).as_posix(): file_hash(p) for p in directory.rglob('*') if p.is_file()}


def db_snapshot(path):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as connection:
        assert connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
        revision = connection.execute('SELECT version_num FROM alembic_version').fetchone()[0]
        tables = {}
        for name, in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            if name != 'alembic_version':
                safe = '"' + name.replace('"', '""') + '"'
                rows = connection.execute(f'SELECT * FROM {safe} ORDER BY rowid').fetchall()
                tables[name] = (len(rows), hashlib.sha256(repr(rows).encode()).hexdigest())
        return revision, tables


def migrate(path, method, revision):
    from flask import Flask
    from app.extensions import db, migrate as extension
    import app.models  # Register metadata.
    app = Flask('dual-structure-migration')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + path.as_posix()
    db.init_app(app)
    directory = str(REPO / 'backend/migrations')
    extension.init_app(app, db, directory=directory)
    with app.app_context():
        method(directory=directory, revision=revision)
        db.session.remove()
        db.engine.dispose()


def initialize(adapter, paths):
    from flask_migrate import upgrade, downgrade
    from app.storage import SCHEMA_HEAD, windows_volume
    from auth_setup import prepare_tls
    original = adapter.checked(SOURCE / 'operational/staging-profile.json')
    marker = adapter.read(original)
    if marker.get('profile') != 'STAGING' or marker.get('syntheticOnly') is not True or marker.get('schema') != '0005_writing_tools':
        raise ValueError('SYNTHETIC_0005_STAGING_REQUIRED')
    paths['root'].mkdir()
    for name in ('database', 'files', 'temp', 'backups', 'tls', 'logs', 'cache'):
        path = paths[name].parent if name == 'database' else paths[name]
        path.mkdir(parents=True, exist_ok=True)
    original_db = adapter.checked(SOURCE / 'db/geulbit.sqlite3')
    with closing(sqlite3.connect(original_db.as_uri() + '?mode=ro', uri=True)) as old, closing(sqlite3.connect(paths['database'])) as new:
        old.backup(new)
        new.execute('PRAGMA journal_mode=WAL')
    old_revision, baseline = db_snapshot(paths['database'])
    assert old_revision == '0005_writing_tools'
    migrate(paths['database'], upgrade, SCHEMA_HEAD)
    revision, candidate = db_snapshot(paths['database'])
    assert revision == SCHEMA_HEAD and {key: candidate[key] for key in baseline} == baseline
    assert set(candidate) - set(baseline) == {'essay_structure_maps', 'essay_structure_runs'}
    migrate(paths['database'], downgrade, old_revision)
    assert db_snapshot(paths['database']) == (old_revision, baseline)
    migrate(paths['database'], upgrade, SCHEMA_HEAD)
    assert db_snapshot(paths['database']) == (SCHEMA_HEAD, candidate)
    files = SOURCE / 'files'
    for source in files.rglob('*'):
        adapter.checked(source)
        if source.is_file():
            target = paths['files'] / source.relative_to(files)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    assert inventory(files) == inventory(paths['files'])
    volume = windows_volume(paths['root'])
    adapter.write(paths['root'] / 'operational/storage.json', {
        'root': str(paths['root']), 'volumeId': volume.identity, 'filesystem': volume.filesystem,
        'schemaHead': SCHEMA_HEAD}, new=True)
    adapter.write(paths['marker'], {'format': 1, 'profile': 'STAGING', 'syntheticOnly': True,
        'root': str(paths['root']), 'volumeId': volume.identity, 'schema': SCHEMA_HEAD, 'port': PORT,
        'codeRoot': str(REPO), 'cookie': adapter.COOKIE, 'createdAt': datetime.now(timezone.utc).isoformat()}, new=True)
    prepare_tls(adapter.secret_store(paths, create=True), paths['tls'])
    print(json.dumps({'status': 'PASS', 'sourceRevision': old_revision, 'targetRevision': SCHEMA_HEAD,
        'roundTrip': True, 'oldTablesPreserved': len(baseline), 'oldRowsPreserved': sum(row[0] for row in baseline.values()),
        'filesPreserved': len(inventory(files)), 'integrity': 'ok', 'foreignKeyViolations': 0}), flush=True)


class SyntheticGateway:
    def __init__(self):
        self.requests = 0

    def open(self, req, timeout):
        self.requests += 1
        payload = json.loads(req.data)
        assert req.full_url == BASE + '/chat/completions/' and timeout <= 10
        assert payload['response_format']['json_schema']['strict'] is True
        supplied = json.loads(payload['messages'][1]['content'])
        assert set(supplied) == {'sentences'} and all(set(row) == {'id', 'text'} for row in supplied['sentences'])
        time.sleep(1.4)  # Make the real asynchronous status visible in Chrome.
        first, second, *_ = supplied['sentences']
        phrase = '‘십 분’' if '‘십 분’' in second['text'] else ''
        value = {'nodes': [
            {'id': 'c', 'role': 'CLAIM', 'basis': 'EXPLICIT', 'spans': [{'sentenceId': first['id'], 'text': '', 'occurrence': 1}]},
            {'id': 'e', 'role': 'EVIDENCE', 'basis': 'IMPLICIT', 'spans': [{'sentenceId': second['id'], 'text': phrase, 'occurrence': 1}]},
        ], 'relations': [{'sourceId': 'e', 'targetId': 'c', 'type': 'QUALIFIES', 'basis': 'IMPLICIT'}]}
        class Response(io.BytesIO):
            status = 200
            headers = {'X-Credits-Charged': '0.010'}

            def geturl(self):
                return req.full_url
        return Response(json.dumps({'model': payload['model'], 'choices': [{'finish_reason': 'stop',
            'message': {'content': json.dumps(value)}}], 'usage': {'prompt_tokens': 320, 'completion_tokens': 140,
            'total_tokens': 460}}).encode())


def serve(adapter, paths, args, signal):
    from flask import jsonify
    from waitress import create_server
    from app.extensions import db
    from app.models import AppSetting
    from app.services.analysis_service import executor as s4_executor
    from app.services.secrets_service import MemorySecretStore
    from app.v2.baze_provider import BazeProvider, GatewaySettings
    from app.v2.deployment import waitress_proxy_options
    from app.v2.dual_structure_api import executor as ai_executor
    from local_https_proxy import create_proxy, LocalTLSProxy
    app = adapter.create_staging_app(paths)
    mock = SyntheticGateway()
    dist = (REPO / 'artifacts/dual-structure/build').resolve(strict=True)
    assert (dist / 'index.html').is_file() and dist.is_relative_to(REPO)
    app.config.update(FRONTEND_DIST=dist, AI_STRUCTURE_ENABLED=True, EXTERNAL_AI_TERMS_APPROVED=True,
        AI_STRUCTURE_POLICY_VERSION='synthetic-staging-structure-v1', AI_STRUCTURE_CALL_COST_UNITS=2,
        AI_LIMITS={'dailyRequests': 12, 'monthlyBudgetUnits': 60, 'callCostUnits': 1, 'cooldownSeconds': 0, 'concurrency': 2})
    if args.ocr_config:
        app.config['OCR_LOCAL_CONFIG'] = str(Path(args.ocr_config).resolve(strict=True))
    app.extensions['structure_provider'] = BazeProvider(GatewaySettings(BASE, 'synthetic-staging', 1024, 6000, 6),
        MemorySecretStore({'BAZE_API_KEY': 'synthetic-staging-unused-outside-mock'}), opener=mock)
    with app.app_context():
        db.session.merge(AppSetting(key='ai_enabled', value=True))
        db.session.commit()

    @app.get('/__staging__/dual/metrics')
    def metrics():
        return jsonify(providerCalls=mock.requests, externalCalls=0)

    origin = 'https://localhost:' + str(PORT)
    server = create_server(app, host='127.0.0.1', port=0, threads=4,
        **waitress_proxy_options({'GEULBIT_PUBLIC_ORIGIN': origin, 'GEULBIT_TRUSTED_PROXY': '127.0.0.1'}))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    handler = type('StagingTLSProxy', (LocalTLSProxy,), {'public_host': 'localhost:' + str(PORT),
        'upstream_port': int(server.effective_port)})
    proxy = create_proxy(paths['tls'], adapter.secret_store(paths), port=PORT, handler=handler)

    def watch():
        while not signal.exists():
            time.sleep(.15)
        proxy.shutdown()

    threading.Thread(target=watch, daemon=True).start()
    print(json.dumps({'status': 'READY', 'profile': 'STAGING', 'origin': origin, 'provider': 'mock-transport'}), flush=True)
    try:
        proxy.serve_forever()
    finally:
        proxy.server_close()
        server.close()
        server.task_dispatcher.shutdown(timeout=5)
        server.asyncore.close_all(map=server._map)
        thread.join(2)
        ai_executor.shutdown(wait=True)
        s4_executor.shutdown(wait=True)
        adapter.close_app(app)
    print(json.dumps({'status': 'STOPPED', 'providerCalls': mock.requests, 'externalCalls': 0}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'serve', 'stop'])
    parser.add_argument('--root', required=True)
    parser.add_argument('--adapter', required=True)
    parser.add_argument('--token', default='first')
    parser.add_argument('--ocr-config')
    args = parser.parse_args()
    root = Path(args.root)
    if root.parent != SOURCE / 'temp' or not re.fullmatch(r'patch-dual-001-[a-z0-9-]+', root.name) or not re.fullmatch(r'[a-z0-9-]+', args.token):
        raise SystemExit('EXPLICIT_ISOLATED_STAGING_CLONE_REQUIRED')
    adapter_path = Path(args.adapter).resolve(strict=True)
    if adapter_path.name != 'staging_service.py' or not adapter_path.is_relative_to(Path('C:/Projects/dream-hs-automation-bounded-v3/output/geulbit/runtime/v22/PATCH-STAGING-001').resolve()):
        raise SystemExit('EXISTING_STAGING_ADAPTER_REQUIRED')
    spec = importlib.util.spec_from_file_location('geulbit_staging_adapter', adapter_path)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    from app.storage import SCHEMA_HEAD
    adapter.REPO, adapter.SCHEMA, adapter.PORT, adapter.COOKIE = REPO, SCHEMA_HEAD, PORT, 'geulbit_dual_staging_session'
    paths = adapter.profile_paths('STAGING', root, expected_root=root)
    signal = paths['marker'].parent / f'dual-{args.token}.stop'
    if args.action == 'init':
        initialize(adapter, paths)
    elif args.action == 'stop':
        adapter.owned_profile(paths)
        signal.touch(exist_ok=False)
    else:
        if signal.exists():
            raise SystemExit('USE_NEW_STAGING_RUN_TOKEN')
        serve(adapter, paths, args, signal)


if __name__ == '__main__':
    main()
