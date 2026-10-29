"""Encrypted offline bundle over the existing SQLite Online Backup primitive.

The caller must stop all writers and pin a distinct healthy physical device.
Restore only creates a new isolation directory; never replaces a live database.
"""
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import zipfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import current_app
from ..storage import validate_volume
from ..routes.data import _snapshot_database

MAGIC=b'GEULBIT-BACKUP-1\0'
LIMIT=64*1024*1024
from ..storage import SCHEMA_HEAD
REVISION=SCHEMA_HEAD
SUPPORTED_REVISIONS={'0003_resource_ownership','0004_user_annotations',REVISION}


def physical_disk(path):
    letter=Path(path).drive[:1]
    if os.name!='nt' or not letter.isalpha():raise ValueError('LOCAL_BACKUP_DEVICE_REQUIRED')
    command=f"$d=Get-Partition -DriveLetter {letter} -ErrorAction Stop | Get-Disk -ErrorAction Stop; if($d.HealthStatus -ne 'Healthy'){{throw 'unhealthy'}}; $d.UniqueId"
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True,timeout=15,check=True)
    value=result.stdout.strip()
    if not value:raise ValueError('PHYSICAL_DISK_UNVERIFIED')
    return value


def validate_device(target,source,volume_id,disk_id):
    target=Path(target)
    validate_volume(target,volume_id)
    if not disk_id or physical_disk(target)!=disk_id or physical_disk(target)==physical_disk(source):raise ValueError('SEPARATE_PINNED_DEVICE_REQUIRED')
    if not target.is_dir():raise ValueError('BACKUP_DIRECTORY_REQUIRED')


def digest(data):return hashlib.sha256(data).hexdigest()


def file_names(connection):
    rows=connection.execute('SELECT stored_name FROM source_document UNION SELECT file_ref FROM document_revisions WHERE file_ref IS NOT NULL UNION SELECT stored_name FROM rubric_file').fetchall()
    names={row[0] for row in rows}
    if any(not isinstance(n,str) or not n or n in {'.','..'} or '/' in n or '\\' in n or ':' in n for n in names):raise ValueError('UNSAFE_FILE_REFERENCE')
    return names


def verify_db(connection,revision=REVISION):
    if revision not in SUPPORTED_REVISIONS:raise ValueError('BACKUP_REVISION_UNSUPPORTED')
    if connection.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or connection.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('BACKUP_DATABASE_INVALID')
    if connection.execute('SELECT version_num FROM alembic_version').fetchone()[0]!=revision:raise ValueError('BACKUP_REVISION_UNSUPPORTED')


def build_bundle(key,*,quiescent=False,now=None,revision=REVISION):
    if quiescent is not True:raise ValueError('ALL_WRITERS_MUST_BE_STOPPED')
    if len(key)!=32:raise ValueError('BACKUP_KEY_INVALID')
    now=now or datetime.now(timezone.utc)
    temp=Path(current_app.config['TEMP_FOLDER']);temp.mkdir(parents=True,exist_ok=True)
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='backup-isolated-',dir=temp) as directory:
        snapshot=Path(directory)/'database.sqlite3';_snapshot_database(snapshot)
        with closing(sqlite3.connect(snapshot)) as c:
            verify_db(c,revision)
            if c.execute("SELECT 1 FROM analysis_job WHERE status IN ('queued','running') LIMIT 1").fetchone():raise ValueError('BACKUP_WORK_IN_PROGRESS')
            if any(json.loads(r[0]).get('state')=='FILES_PENDING' for r in c.execute("SELECT value FROM app_settings WHERE key LIKE 'privacy_job:%'")):raise ValueError('BACKUP_DELETION_PENDING')
            names=file_names(c)
        members={'database.sqlite3':snapshot.read_bytes()};root=Path(current_app.config['UPLOAD_FOLDER']).resolve()
        for name in sorted(names):
            path=root/name
            if path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError('UNSAFE_FILE_REFERENCE')
            if path.stat().st_size+sum(map(len,members.values()))>LIMIT:raise ValueError('BACKUP_SIZE_LIMIT')
            members['files/'+name]=path.read_bytes()
            if sum(map(len,members.values()))>LIMIT:raise ValueError('BACKUP_SIZE_LIMIT')
        if sum(map(len,members.values()))>LIMIT:raise ValueError('BACKUP_SIZE_LIMIT')
        manifest={'format':1,'revision':revision,'sourceIdentity':digest(str(Path(current_app.config['DATABASE_PATH']).resolve()).encode()),'createdAt':now.isoformat(),'sha256':{name:digest(data) for name,data in members.items()}}
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json',json.dumps(manifest,sort_keys=True))
            for name,data in members.items():archive.writestr(name,data)
        nonce=os.urandom(12)
        return MAGIC+nonce+AESGCM(key).encrypt(nonce,stream.getvalue(),MAGIC)


def write_bundle(target,data):
    """Exclusive creation and flush; no overwrite or partial successful receipt."""
    target=Path(target)
    if target.exists():raise ValueError('EXISTING_BACKUP_PRESERVED')
    if shutil.disk_usage(target.parent).free<len(data)+16*1024*1024:raise ValueError('BACKUP_SPACE_INSUFFICIENT')
    created=False
    try:
        with target.open('xb') as stream:
            created=True;stream.write(data);stream.flush();os.fsync(stream.fileno())
    except OSError:
        # Only this newly created encrypted incomplete file can be removed.
        if created and target.is_file():target.unlink()
        raise
    return {'sha256':digest(data),'bytes':len(data)}


def read_bundle(data,key,now=None,*,allow_expired=False,revision=REVISION):
    now=now or datetime.now(timezone.utc)
    if len(data)>LIMIT+1024*1024 or not data.startswith(MAGIC):raise ValueError('BACKUP_FORMAT_INVALID')
    start=len(MAGIC)
    try:plain=AESGCM(key).decrypt(data[start:start+12],data[start+12:],MAGIC)
    except Exception:raise ValueError('BACKUP_AUTHENTICATION_FAILED') from None
    with zipfile.ZipFile(io.BytesIO(plain)) as archive:
        infos=archive.infolist();names=[i.filename for i in infos]
        if len(names)!=len(set(names)) or sum(i.file_size for i in infos)>LIMIT:raise ValueError('BACKUP_SIZE_OR_DUPLICATE_INVALID')
        for item in infos:
            p=PurePosixPath(item.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in item.filename or ':' in item.filename or (item.external_attr>>16)&0o170000==0o120000:raise ValueError('UNSAFE_BACKUP_MEMBER')
        members={n:archive.read(n) for n in names};manifest=json.loads(members.pop('manifest.json'))
        created=datetime.fromisoformat(manifest['createdAt'])
        if created>now or (not allow_expired and now-created>=timedelta(days=7)):raise ValueError('BACKUP_EXPIRED_OR_FUTURE')
        schema=manifest.get('revision')
        if manifest.get('format')!=1 or schema not in SUPPORTED_REVISIONS or (revision is not None and schema!=revision) or set(manifest['sha256'])!=set(members):raise ValueError('BACKUP_MANIFEST_INVALID')
        if any(digest(v)!=manifest['sha256'][n] for n,v in members.items()):raise ValueError('BACKUP_HASH_MISMATCH')
        if 'database.sqlite3' not in members or any(n!='database.sqlite3' and (not n.startswith('files/') or len(PurePosixPath(n).parts)!=2) for n in members):raise ValueError('UNSAFE_BACKUP_MEMBER')
        return members,manifest


def restore_bundle(data,key,target,authority,*,now=None,revision=REVISION):
    """A fresh isolation only, with latest revocations reapplied before success."""
    now=now or datetime.now(timezone.utc);target=Path(target);authority=Path(authority);schema_revision=revision
    if target.exists():raise ValueError('RESTORE_NEW_ISOLATION_REQUIRED')
    # The latest authoritative DB is mandatory: an old backup cannot clear revocation.
    with closing(sqlite3.connect(authority.resolve().as_uri()+'?mode=ro',uri=True)) as live:
        verify_db(live,schema_revision)
        revocations=[json.loads(r[0]) for r in live.execute("SELECT value FROM app_settings WHERE key LIKE 'privacy_revoke:%'")]
        users={r[0]:(r[1],r[2]) for r in live.execute('SELECT id,status,session_version FROM users')}
        erased_users={r[0] for r in live.execute("SELECT id FROM users WHERE oidc_issuer='urn:geulbit:erased-owner'")}
        live_docs={r[0] for r in live.execute('SELECT id FROM source_document')}
        live_rubrics={r[0] for r in live.execute('SELECT id FROM rubric')}
        live_works={r[0] for r in live.execute('SELECT id FROM works')}
        live_quotes={r[0] for r in live.execute('SELECT id FROM quote_card')}
    members,manifest=read_bundle(data,key,now,revision=schema_revision)
    if manifest.get('sourceIdentity')!=digest(str(authority.resolve()).encode()):raise ValueError('BACKUP_AUTHORITY_MISMATCH')
    # An old encrypted archive must never recreate erased Google identity.
    # Fail before writing restoration files; independent review must approve
    # any future sanitizing restore path instead of silently guessing owners.
    with closing(sqlite3.connect(':memory:')) as probe:
        # SQLite deserialize has no WAL sidecar. The Online Backup image
        # is complete; use rollback header mode only for this in-memory probe.
        image=bytearray(members['database.sqlite3']);image[18:20]=b'\x01\x01'
        probe.deserialize(bytes(image))
        verify_db(probe,schema_revision)
        for identifier,issuer in probe.execute('SELECT id,oidc_issuer FROM users'):
            if (identifier not in users or identifier in erased_users) and issuer!='urn:geulbit:erased-owner':
                raise ValueError('BACKUP_ERASED_IDENTITY_RESTORE_BLOCKED')
    target.mkdir(parents=True);(target/'db').mkdir();(target/'files').mkdir()
    try:
        path=target/'db/geulbit.sqlite3';path.write_bytes(members.pop('database.sqlite3'))
        with closing(sqlite3.connect(path)) as c:
            c.execute('PRAGMA foreign_keys=ON');verify_db(c,schema_revision)
            from ..v2.operations_api import remove_essay_graph
            erase=lambda identifier:remove_essay_graph(identifier,executor=lambda sql,args:c.execute(str(sql),args))
            def erase_document_runs(identifier):
                owner=c.execute('SELECT owner_id FROM source_document WHERE id=?',(identifier,)).fetchone()
                for run,writing,context in c.execute('SELECT id,writing_id,context_snapshot FROM analysis').fetchall():
                    snapshot=json.loads(context) if isinstance(context,str) else context or {}
                    if not any(ref.get('documentId')==identifier for ref in snapshot.get('documents',[])):continue
                    essay_owner=c.execute('SELECT owner_id FROM writing WHERE id=?',(writing,)).fetchone()
                    if not owner or not essay_owner or owner[0]!=essay_owner[0]:raise ValueError('RESTORE_DOCUMENT_OWNERSHIP_CONFLICT')
                    c.execute('DELETE FROM ai_interactions WHERE analysis_id=?',(run,));c.execute('DELETE FROM feedback_reactions WHERE analysis_id=?',(run,));c.execute('DELETE FROM analysis WHERE id=?',(run,))
            for identifier, in c.execute('SELECT id FROM writing WHERE expires_at<=?',(now.replace(tzinfo=None),)).fetchall():erase(identifier)
            for entry in revocations:
                if entry['kind']=='essay':erase(entry['id'])
                elif entry['kind']=='user':
                    for identifier, in c.execute('SELECT id FROM writing WHERE owner_id=?',(entry['id'],)).fetchall():erase(identifier)
                    c.execute("UPDATE users SET status='INACTIVE' WHERE id=?",(entry['id'],))
                elif entry['kind']=='document':
                    identifier=entry['id']
                    if c.execute("SELECT 1 FROM source_document WHERE id=? AND scope='PUBLIC'",(identifier,)).fetchone() and entry.get('scope')!='PUBLIC':raise ValueError('RESTORE_PUBLIC_CONFLICT')
                    erase_document_runs(identifier)
                    # Do not guess ownership or silently destroy references.
                    revisions=c.execute('SELECT id FROM document_revisions WHERE document_id=? ORDER BY revision_number DESC',(identifier,)).fetchall()
                    for revision, in revisions:
                        c.execute('DELETE FROM essay_documents WHERE revision_id=?',(revision,))
                        c.execute('DELETE FROM document_revisions WHERE id=?',(revision,))
                    c.execute('DELETE FROM quote_card WHERE document_id=?',(identifier,));c.execute('DELETE FROM work_documents WHERE document_id=?',(identifier,));c.execute('DELETE FROM source_document WHERE id=?',(identifier,))
            for identifier,owner,scope in c.execute('SELECT id,owner_id,scope FROM source_document').fetchall():
                document_expired=False
                if scope=='PRIVATE':
                    revisions=c.execute('SELECT content_hash,created_at FROM document_revisions WHERE document_id=? ORDER BY revision_number DESC',(identifier,)).fetchall()
                    if not revisions:raise ValueError('RESTORE_DOCUMENT_PROVENANCE_REQUIRED')
                    content_hash,changed=revisions[0]
                    for old_hash,old_changed in revisions[1:]:
                        if old_hash!=content_hash:break
                        changed=old_changed
                    at=datetime.fromisoformat(changed)
                    if at.tzinfo is None:at=at.replace(tzinfo=timezone.utc)
                    document_expired=at+timedelta(days=7)<=now
                if identifier in live_docs and not document_expired and not (scope=='PRIVATE' and (owner not in users or users[owner][0]!='ACTIVE')):continue
                erase_document_runs(identifier)
                for revision, in c.execute('SELECT id FROM document_revisions WHERE document_id=? ORDER BY revision_number DESC',(identifier,)).fetchall():
                    c.execute('DELETE FROM essay_documents WHERE revision_id=?',(revision,));c.execute('DELETE FROM document_revisions WHERE id=?',(revision,))
                c.execute('DELETE FROM quote_card WHERE document_id=?',(identifier,));c.execute('DELETE FROM work_documents WHERE document_id=?',(identifier,));c.execute('DELETE FROM source_document WHERE id=?',(identifier,))
            for identifier,owner in c.execute('SELECT id,owner_id FROM rubric').fetchall():
                modified=c.execute('SELECT updated_at FROM rubric_file WHERE rubric_id=?',(identifier,)).fetchone()
                if not modified:raise ValueError('RESTORE_RUBRIC_PROVENANCE_REQUIRED')
                at=datetime.fromisoformat(modified[0])
                if at.tzinfo is None:at=at.replace(tzinfo=timezone.utc)
                if at+timedelta(days=7)<=now or identifier not in live_rubrics or (owner and (owner not in users or users[owner][0]!='ACTIVE')):
                    c.execute("DELETE FROM writing_resource WHERE resource_id=?",(identifier,));c.execute('DELETE FROM rubric WHERE id=?',(identifier,))
            for identifier,owner,scope in c.execute('SELECT id,owner_id,scope FROM works').fetchall():
                if identifier not in live_works or (scope=='PRIVATE' and (owner not in users or users[owner][0]!='ACTIVE')):
                    c.execute('DELETE FROM work_documents WHERE work_id=?',(identifier,));c.execute('DELETE FROM works WHERE id=?',(identifier,))
            for identifier, in c.execute('SELECT id FROM quote_card').fetchall():
                if identifier not in live_quotes:c.execute('DELETE FROM quote_card WHERE id=?',(identifier,))
            for identifier,status,version in c.execute('SELECT id,status,session_version FROM users').fetchall():
                latest=users.get(identifier)
                # Missing/withdrawn users cannot be resurrected from a backup.
                restored_status='INACTIVE' if not latest or latest[0]!='ACTIVE' or status=='INACTIVE' else 'ACTIVE'
                c.execute('UPDATE users SET status=?,session_version=? WHERE id=?',(restored_status,max(version,latest[1] if latest else version)+1,identifier))
            c.execute("UPDATE app_settings SET value='false' WHERE key='ai_enabled'")
            # Mark restoration as quarantined; this is never a server startup approval.
            c.execute("INSERT OR REPLACE INTO app_settings(key,value,created_at,updated_at) VALUES ('restore_quarantine','true',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
            for entry in revocations:
                k='privacy_revoke:'+entry['kind']+':'+entry['id']
                c.execute('INSERT OR REPLACE INTO app_settings(key,value,created_at,updated_at) VALUES (?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)',(k,json.dumps(entry)))
            names=file_names(c);verify_db(c,schema_revision);c.commit()
        for name in names:
            content=members.get('files/'+name)
            if content is None:raise ValueError('BACKUP_REFERENCED_FILE_MISSING')
            (target/'files'/name).write_bytes(content)
        # Unreferenced/deleted bytes are not written into the restored file store.
        return {'revision':manifest['revision'],'files':len(names),'quarantined':True,'sessionsInvalidated':True}
    except Exception:
        # Preserve incomplete isolation for diagnosis, with a mandatory block marker.
        (target/'RESTORE_BLOCKED').write_text('RESTORE_INCOMPLETE',encoding='utf-8')
        raise


def backup_due(last_created,now=None):
    return last_created is None or (now or datetime.now(timezone.utc))-last_created>=timedelta(days=1)


def prune_encrypted(target,key,now=None):
    """Only authenticated bundles in the explicitly approved backup directory."""
    now=now or datetime.now(timezone.utc);removed=0
    for path in Path(target).glob('geulbit-*.gbb'):
        if path.is_symlink() or path.stat().st_size>LIMIT+1024*1024:raise ValueError('BACKUP_UNVERIFIED')
        _,manifest=read_bundle(path.read_bytes(),key,now,allow_expired=True,revision=None)
        if now-datetime.fromisoformat(manifest['createdAt'])>=timedelta(days=7):path.unlink();removed+=1
    return removed
