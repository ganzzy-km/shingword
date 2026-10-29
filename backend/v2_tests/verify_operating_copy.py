"""Read-only operating snapshot; migrations/restores only inside a private temporary copy."""
import json,os,sqlite3,sys,hashlib,shutil,subprocess,tempfile
from pathlib import Path
from contextlib import closing
sys.path.insert(0,str(Path(__file__).parents[1]))
from flask import Flask
from flask_migrate import upgrade
from app.extensions import db,migrate
from app.services.backup_service import file_names,build_bundle,read_bundle,write_bundle,restore_bundle

ROOT=Path('C:/Users/USER/GeulbitData');SOURCE=ROOT/'db/geulbit.sqlite3'
def inventory(c):
    names=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='alembic_version' ORDER BY name")]
    return {n:c.execute('SELECT * FROM "'+n+'" ORDER BY rowid').fetchall() for n in names}

def main():
    assert ROOT.resolve()==ROOT and SOURCE.is_file() and not SOURCE.is_symlink()
    base=ROOT/'temp';base.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='v21-migration-check-',dir=base) as folder:
        target=Path(folder);assert target.resolve().parent==base.resolve() and target.name.startswith('v21-migration-check-')
        # Copies may contain personal data; restrict only this newly created test directory.
        sid=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command','[Security.Principal.WindowsIdentity]::GetCurrent().User.Value'],capture_output=True,text=True,check=True).stdout.strip()
        assert sid.startswith('S-1-5-')
        subprocess.run(['icacls',str(target),'/inheritance:r','/grant:r','*'+sid+':(OI)(CI)F','*S-1-5-18:(OI)(CI)F'],capture_output=True,check=True)
        path=target/'copy.sqlite3';(target/'files').mkdir();(target/'temp').mkdir()
        with closing(sqlite3.connect(SOURCE.as_uri()+'?mode=ro',uri=True,timeout=30)) as source,closing(sqlite3.connect(path)) as copy:
            source.execute('BEGIN');assert source.execute('SELECT version_num FROM alembic_version').fetchone()==('0003_resource_ownership',)
            assert source.execute('PRAGMA integrity_check').fetchone()==('ok',)
            before=inventory(source);source.backup(copy)
        with closing(sqlite3.connect(path)) as copy:
            assert inventory(copy)==before
            names=file_names(copy)
        for name in names:
            original=ROOT/'files'/name
            assert not original.is_symlink() and original.resolve().is_relative_to((ROOT/'files').resolve())
            payload=original.read_bytes();digest=hashlib.sha256(payload).digest()
            (target/'files'/name).write_bytes(payload)
            assert hashlib.sha256(original.read_bytes()).digest()==digest
        app=Flask('v21-copy-only');app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///'+str(path),DATABASE_PATH=path,UPLOAD_FOLDER=target/'files',TEMP_FOLDER=target/'temp')
        db.init_app(app);migrate.init_app(app,db,directory=str(Path(__file__).parents[1]/'migrations'))
        with app.app_context():
            upgrade();upgrade()
            with closing(sqlite3.connect(path)) as copy:
                after=inventory(copy)
                assert all(after[n]==rows for n,rows in before.items())
                assert after['user_annotations']==[]
                assert copy.execute('SELECT version_num FROM alembic_version').fetchone()==('0004_user_annotations',)
                assert copy.execute('PRAGMA integrity_check').fetchone()==('ok',) and copy.execute('PRAGMA foreign_key_check').fetchall()==[]
            key=os.urandom(32);bundle=build_bundle(key,quiescent=True)
            receipt=write_bundle(target/'isolated.gbb',bundle);members,manifest=read_bundle(bundle,key)
            assert manifest['revision']=='0004_user_annotations' and all(hashlib.sha256(data).hexdigest()==manifest['sha256'][name] for name,data in members.items())
            result=restore_bundle(bundle,key,target/'restored',path)
            assert result['quarantined'] and result['sessionsInvalidated']
            with closing(sqlite3.connect(target/'restored/db/geulbit.sqlite3')) as restored:
                assert restored.execute('PRAGMA integrity_check').fetchone()==('ok',) and restored.execute('PRAGMA foreign_key_check').fetchall()==[]
            db.session.remove();db.engine.dispose()
        # The temporary directory is now closed and is the only cleanup target.
        evidence={'status':'PASS','sourceAccess':'SQLITE_READ_ONLY_ONLINE_BACKUP','operatingRevision':'0003_resource_ownership','copyRevision':'0004_user_annotations','oldTables':len(before),'existingRowsPreserved':True,'linkedFilesVerified':len(names),'integrity':'ok','fkViolations':0,'upgradeRepeat':'PASS','encryptedBundleBytes':receipt['bytes'],'bundleManifestHashes':'PASS','restoreQuarantine':'PASS','restoreSessionsInvalidated':'PASS','copiedPersonalDataCleanup':'PENDING'}
    evidence['copiedPersonalDataCleanup']='PASS'
    with closing(sqlite3.connect(SOURCE.as_uri()+'?mode=ro',uri=True)) as live:assert live.execute('SELECT version_num FROM alembic_version').fetchone()==('0003_resource_ownership',)
    output=Path('artifacts/v21/operating-copy-results.json');output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print(json.dumps(evidence))
if __name__=='__main__':
    try:main()
    except Exception as error:
        print(json.dumps({'status':'BLOCKED','errorType':type(error).__name__}));raise SystemExit(1)
