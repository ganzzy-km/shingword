import v2_fixture  # existing isolated backend import path
import json,hashlib
from pathlib import Path
from datetime import datetime,timezone,timedelta
import pytest
from app.v2.beta_runtime import operating_configuration
from app.storage import SCHEMA_HEAD

def test_operating_configuration_requires_gates_code_and_verified_backup(tmp_path):
    root=tmp_path/'data';(root/'operational/local-backups').mkdir(parents=True);repo=tmp_path/'repo';(repo/'backend/config').mkdir(parents=True)
    code=repo/'backend/test.py';code.write_text('synthetic approved code')
    receipt={'approved':True,'G5':'WAIVED_BY_USER','gates':{g:'PASS' for g in ['G1','G2','G3','G4']},'codeHashes':{'backend/test.py':hashlib.sha256(code.read_bytes()).hexdigest()}}
    policy={'backupMode':'7d-encrypted-local-c-v1','approvedRetention':{'independentPrivateDocuments':'last-document-body-change/7d-v1'},'betaSignup':{'policy':{'approved':True,'version':'synthetic','notice':'synthetic'}}}
    (repo/'backend/config/privacy.example.json').write_text(json.dumps(policy));gate=root/'operational/beta-release.json';gate.write_text(json.dumps(receipt))
    with pytest.raises(ValueError,match='BACKUP'):operating_configuration(root,repo)
    archive=root/'operational/local-backups/geulbit-synthetic.gbb';archive.write_bytes(b'synthetic encrypted fixture')
    archive.with_suffix('.verified.json').write_text(json.dumps({'restoreVerified':True,'revision':SCHEMA_HEAD,'createdAt':datetime.now(timezone.utc).isoformat(),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}))
    config=operating_configuration(root,repo);assert config['BETA_SIGNUP_ENABLED'] and config['PRIVATE_DOCUMENT_RETENTION_POLICY']=='last-document-body-change/7d-v1'
    assert config['AI_PROVIDER'] is None and not config['EXTERNAL_AI_TERMS_APPROVED']
    proof=archive.with_suffix('.verified.json');value=json.loads(proof.read_text());value['createdAt']=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat();proof.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='BACKUP'):operating_configuration(root,repo)
    assert operating_configuration(root,repo,require_fresh_backup=False)['RETENTION_APPROVED']
    value['createdAt']=datetime.now(timezone.utc).isoformat();proof.write_text(json.dumps(value))
    receipt['gates']['G4']='FAIL';gate.write_text(json.dumps(receipt))
    with pytest.raises(ValueError,match='GATES'):operating_configuration(root,repo)
    receipt['gates']['G4']='PASS';gate.write_text(json.dumps(receipt));code.write_text('modified')
    with pytest.raises(ValueError,match='CODE_CHANGED'):operating_configuration(root,repo)
