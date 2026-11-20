"""Local operator adapter. No automatic deletion, public release or migration."""
import argparse
import base64
import json
import secrets
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path
from flask import Flask
from auth_setup import approved_store,ROOT
from app.services.backup_service import validate_device,build_bundle,write_bundle,restore_bundle,backup_due,read_bundle,prune_encrypted,LIMIT

CONFIG=ROOT/'operational/backup-config.json'
KEY='GEULBIT_BACKUP_ENCRYPTION_KEY'


def discard_verified_isolation(target):
    target=Path(target)
    if target.resolve().parent!=(ROOT/'temp').resolve() or not target.name.startswith('restore-check-') or target.is_symlink():raise ValueError('ISOLATION_CLEANUP_BLOCKED')
    for name in ['db','files']:
        folder=target/name
        if folder.is_symlink():raise ValueError('ISOLATION_CLEANUP_BLOCKED')
        for item in folder.iterdir():
            if not item.is_file() or item.is_symlink():raise ValueError('ISOLATION_CLEANUP_BLOCKED')
            item.unlink()
        folder.rmdir()
    target.rmdir()


def assert_writers_stopped():
    # Conservative across relative launch paths and Python launcher/worker PIDs.
    command="$p=Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {$_.Name -match 'python|waitress' -and $_.CommandLine -match 'network_service.py.*serve|run_auth_dev.py|backend[\\/]serve.py|waitress'}; @($p).Count"
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True,timeout=15,check=True)
    if result.stdout.strip()!='0':raise ValueError('ALL_WRITERS_MUST_BE_STOPPED')


def config():
    if not CONFIG.is_file():raise ValueError('BACKUP_DEVICE_NOT_CONFIGURED')
    value=json.loads(CONFIG.read_text(encoding='utf-8'))
    if value.get('approved') is not True or value.get('retentionDays')!=7 or value.get('frequencyHours')!=24:raise ValueError('BACKUP_POLICY_UNCONFIRMED')
    if value.get('mode')=='local-c-7d-v1':
        from app.storage import validate_volume
        target=Path(value['directory'])
        expected=ROOT/'operational/local-backups'
        if target!=expected or any(p.is_symlink() for p in [ROOT,ROOT/'operational',target]) or not target.is_dir():raise ValueError('LOCAL_BACKUP_DIRECTORY_INVALID')
        validate_volume(ROOT,value['volumeId'])
        validate_volume(target,value['volumeId'])
    else:
        validate_device(value['directory'],ROOT,value['volumeId'],value['physicalDiskId'])
    return value


def verified_last(directory,key,now,revision=None):
    """Only durable restore-verified, exact-byte receipts affect NOT_DUE."""
    import hashlib
    last=None
    for archive in directory.glob('geulbit-*.gbb'):
        receipt=archive.with_suffix('.verified.json')
        if archive.is_symlink() or receipt.is_symlink():raise ValueError('BACKUP_UNVERIFIED')
        if not receipt.is_file():continue
        if archive.stat().st_size>LIMIT+1024*1024 or receipt.stat().st_size>4096:raise ValueError('BACKUP_SIZE_INVALID')
        value=json.loads(receipt.read_text(encoding='utf-8'));data=archive.read_bytes()
        if value.get('restoreVerified') is not True or value.get('sha256')!=hashlib.sha256(data).hexdigest():raise ValueError('BACKUP_RECEIPT_INVALID')
        _,manifest=read_bundle(data,key,now,allow_expired=True,revision=None)
        if value.get('createdAt')!=manifest['createdAt']:raise ValueError('BACKUP_RECEIPT_INVALID')
        if value.get('revision',manifest['revision'])!=manifest['revision']:raise ValueError('BACKUP_RECEIPT_INVALID')
        from app.storage import SCHEMA_HEAD
        if manifest['revision']!=(revision or SCHEMA_HEAD):continue
        created=datetime.fromisoformat(manifest['createdAt']);last=max(last,created) if last else created
    return last


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['status','backup-key','backup','restore','sync-external-backups'])
    parser.add_argument('--archive');parser.add_argument('--isolation-name')
    parser.add_argument('--pre-migration-backup',action='store_true',help='Explicit fresh 0003 backup only, before an approved 0004 migration')
    args=parser.parse_args()
    if args.pre_migration_backup and args.command!='backup':raise ValueError('PRE_MIGRATION_BACKUP_ONLY')
    if args.command=='sync-external-backups':
        from app.services.external_backup import load_configuration,sync_once
        external=load_configuration(ROOT)
        if external.get('enabled') is not True:
            result={'status':'DISABLED','reason':'CONFIGURATION_REQUIRED','copies':[]}
        else:
            result=sync_once(Path(config()['directory']),external,ROOT/'operational/external-backup-copy')
        print(json.dumps(result))
        return result
    store=approved_store(before_v21_migration=True) if args.pre_migration_backup else approved_store()
    if args.command=='status':
        print(json.dumps({'backupKeyRegistered':store.contains(KEY),'deviceConfigurationPresent':CONFIG.is_file(),'automaticDeletion':False,'automaticBackup':False}));return
    if args.command=='backup-key':
        if not store.contains(KEY):store.set(KEY,base64.b64encode(secrets.token_bytes(32)).decode('ascii'))
        print(json.dumps({'backupKey':'REGISTERED_DPAPI','otherEntries':'PRESERVED'}));return
    cfg=config()
    from app.services.storage_lease import StorageLease
    with StorageLease(ROOT/'db/geulbit.sqlite3',exclusive=True):
        result=maintenance(args,store,cfg)
    if args.command=='backup' and not args.pre_migration_backup:
        from app.services.external_backup import dispatch
        dispatch(ROOT,Path(__file__).resolve())
    return result


def maintenance(args,store,cfg):
    assert_writers_stopped()
    pre_migration=getattr(args,'pre_migration_backup',False)
    if pre_migration and args.command!='backup':raise ValueError('PRE_MIGRATION_BACKUP_ONLY')
    from app.storage import SCHEMA_HEAD
    revision='0003_resource_ownership' if pre_migration else SCHEMA_HEAD
    key=base64.b64decode(store.get(KEY),validate=True)
    if len(key)!=32:raise ValueError('BACKUP_KEY_INVALID')
    app=Flask(__name__);app.config.update(DATABASE_PATH=ROOT/'db/geulbit.sqlite3',UPLOAD_FOLDER=ROOT/'files',TEMP_FOLDER=ROOT/'temp')
    directory=Path(cfg['directory']).resolve();now=datetime.now(timezone.utc)
    with app.app_context():
        if args.command=='restore':
            archive=Path(args.archive or '').resolve();name=args.isolation_name
            if archive.parent!=directory or archive.is_symlink() or archive.stat().st_size>LIMIT+1024*1024:raise ValueError('APPROVED_ARCHIVE_REQUIRED')
            if not name or not name.startswith('restore-') or Path(name).name!=name or '/' in name or '\\' in name:raise ValueError('NEW_ISOLATION_NAME_REQUIRED')
            result=restore_bundle(archive.read_bytes(),key,ROOT/'temp'/name,app.config['DATABASE_PATH'])
        else:
            last=None if pre_migration else verified_last(directory,key,now)
            if not backup_due(last,now):result={'status':'NOT_DUE'}
            else:
                target=directory/('geulbit-'+now.strftime('%Y%m%dT%H%M%S%fZ')+'.gbb')
                data=build_bundle(key,quiescent=True,now=now,revision=revision)
                result=write_bundle(target,data)
                # Verify restore before issuing a successful backup receipt.
                isolation=ROOT/'temp'/('restore-check-'+now.strftime('%Y%m%dT%H%M%S%fZ'))
                result['restore']=restore_bundle(data,key,isolation,app.config['DATABASE_PATH'],now=now,revision=revision)
                discard_verified_isolation(isolation)
                import hashlib
                _,manifest=read_bundle(data,key,now,revision=revision)
                receipt={'restoreVerified':True,'sha256':hashlib.sha256(data).hexdigest(),'createdAt':manifest['createdAt'],'revision':result['restore']['revision']}
                with target.with_suffix('.verified.json').open('x',encoding='utf-8') as handle:
                    json.dump(receipt,handle);handle.flush()
                    import os
                    os.fsync(handle.fileno())
                result['pruned']=0 if pre_migration else prune_encrypted(directory,key,now)
    print(json.dumps(result))


if __name__=='__main__':
    try:
        outcome=main()
        if isinstance(outcome,dict) and outcome.get('status') in {'PARTIAL_FAILURE','BLOCKED'}:sys.exit(1)
    except Exception:
        print(json.dumps({'status':'BLOCKED','errorCode':'BACKUP_CONFIGURATION_OR_VERIFICATION_FAILED'}));sys.exit(1)
