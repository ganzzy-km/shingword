"""Approved beta configuration; no secrets, migration or implicit activation."""
from pathlib import Path
import json,hashlib
from datetime import datetime,timedelta,timezone
from .privacy_lifecycle import POLICY,ACCOUNT_POLICY,DOCUMENT_POLICY

def approved_ocr_runtime(receipt):
    """Optional release binding, scoped to the app; never mutate global env."""
    pin=receipt.get('ocrRuntime')
    if pin is None:return {}
    try:
        path=Path(pin['configPath'])
        if not path.is_absolute() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=pin['configSha256']:
            raise ValueError('OCR_RELEASE_CONFIG_CHANGED')
        value=json.loads(path.read_text(encoding='utf-8'));manifest=Path(value['manifest'])
        if not manifest.is_absolute() or manifest.is_symlink() or value['manifestSha']!=pin['manifestSha256'] or hashlib.sha256(manifest.read_bytes()).hexdigest()!=pin['manifestSha256']:
            raise ValueError('OCR_RELEASE_MANIFEST_CHANGED')
        for name in ['python','models','tesseract','tessdata']:
            target=Path(value[name])
            if not target.is_absolute() or target.is_symlink() or not target.exists():raise ValueError('OCR_RELEASE_COMPONENT_UNAVAILABLE')
        evidence=value['resourceEvidence'];target=Path(evidence['path'])
        if not target.is_absolute() or target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest()!=evidence['sha256']:
            raise ValueError('OCR_RELEASE_RESOURCE_EVIDENCE_CHANGED')
        return {'OCR_LOCAL_CONFIG':str(path)}
    except (KeyError,TypeError,OSError,json.JSONDecodeError) as error:
        raise ValueError('OCR_RELEASE_BINDING_INVALID') from error


def operating_configuration(root,repo,require_fresh_backup=True):
    receipt=json.loads((root/'operational/beta-release.json').read_text(encoding='utf-8'))
    if receipt.get('approved') is not True or receipt.get('G5')!='WAIVED_BY_USER' or any(receipt.get('gates',{}).get(g)!='PASS' for g in ['G1','G2','G3','G4']):raise ValueError('BETA_TECHNICAL_GATES_REQUIRED')
    if not receipt.get('codeHashes'):raise ValueError('BETA_CODE_EVIDENCE_REQUIRED')
    for name,digest in receipt['codeHashes'].items():
        path=(repo/name).resolve()
        if not path.is_relative_to(repo.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('BETA_CODE_CHANGED')
    now=datetime.now(timezone.utc);verified=False
    for receipt_path in (root/'operational/local-backups').glob('geulbit-*.verified.json'):
        if receipt_path.is_symlink():raise ValueError('BETA_BACKUP_PATH_INVALID')
        value=json.loads(receipt_path.read_text(encoding='utf-8'));archive=receipt_path.with_name(receipt_path.name.replace('.verified.json','.gbb'))
        if archive.is_symlink() or not archive.is_file() or archive.stat().st_size>65*1024*1024:continue
        created=datetime.fromisoformat(value['createdAt'])
        oldest=now-timedelta(days=1 if require_fresh_backup else 7)
        from ..storage import SCHEMA_HEAD
        if value.get('restoreVerified') is True and value.get('revision')==SCHEMA_HEAD and oldest<=created<=now and hashlib.sha256(archive.read_bytes()).hexdigest()==value.get('sha256'):verified=True
    if not verified:raise ValueError('BETA_FRESH_VERIFIED_BACKUP_REQUIRED')
    policy=json.loads((repo/'backend/config/privacy.example.json').read_text(encoding='utf-8'))
    if policy['backupMode']!='7d-encrypted-local-c-v1' or policy['approvedRetention']['independentPrivateDocuments']!=DOCUMENT_POLICY:raise ValueError('BETA_RETENTION_CONTRACT_REQUIRED')
    if not policy['betaSignup']['policy']['approved']:raise ValueError('BETA_CONSENT_CONTRACT_REQUIRED')
    return dict(BETA_SIGNUP_ENABLED=True,BETA_SIGNUP_POLICY=policy['betaSignup']['policy'],PERSONAL_DATA_POLICY=POLICY,PRIVATE_DOCUMENT_RETENTION_POLICY=DOCUMENT_POLICY,RETENTION_APPROVED=True,RETENTION_DATES_VERIFIED=True,RETENTION_LOCAL_BACKUP_APPROVED=True,RETENTION_BACKUPS_VERIFIED=True,RETENTION_POLICY={'basis':POLICY,'backupRetention':'7d-encrypted-local-c-v1','targetScope':'PRIVATE_ESSAY_GRAPH','privateDocuments':'SEPARATE_APPROVED_LIFECYCLE'},ACCOUNT_RETENTION_APPROVED=True,ACCOUNT_RETENTION_POLICY=ACCOUNT_POLICY,ACCOUNT_PUBLIC_OWNER_ERASURE_APPROVED=True,EXTERNAL_AI_TERMS_APPROVED=False,AI_PROVIDER=None,**approved_ocr_runtime(receipt))
