import v2_fixture  # existing isolated backend import path
import json,hashlib
from pathlib import Path
from datetime import datetime,timezone,timedelta
import pytest
from app.v2.beta_runtime import external_ai_configuration, operating_configuration
from app.storage import SCHEMA_HEAD


def test_approved_structure_provider_can_share_an_account_only_monthly_limit(monkeypatch):
    from flask import Flask
    from app.services.secrets_service import MemorySecretStore
    from app.v2.baze_provider import install_structure_provider
    from test_baze_provider import approved_config

    monkeypatch.delenv('GEULBIT_STRUCTURE_AI_CONFIG_FILE', raising=False)
    external = approved_config()
    gateway = external['BAZE_GATEWAY']
    limits = external['AI_LIMITS']
    del limits['monthlyBudgetUnits']
    limits['monthlyRequests'] = 10
    structure = {'approved': True, 'policyVersion': 'synthetic-paragraph-policy', 'notice': 'Synthetic paragraph notice',
                 'gateway': {**gateway, 'structuredOutputConfirmed': True}, 'callCostUnits': limits['callCostUnits']}
    receipt = {'externalAi': {'approved': True, 'notice': 'Synthetic selected passage notice',
                             'policyVersion': external['AI_POLICY_VERSION'], 'gateway': gateway, 'limits': limits,
                             'structure': structure}}
    app = Flask(__name__)
    app.config.update(external_ai_configuration(receipt), SECRET_STORE=MemorySecretStore({'BAZE_API_KEY': 'synthetic-only'}))
    install_structure_provider(app)
    assert app.extensions['structure_provider'].settings.model == gateway['model']
    assert app.config['AI_LIMITS']['monthlyRequests'] == 10
    assert 'monthlyBudgetUnits' not in app.config['AI_LIMITS']
    assert app.config['AI_STRUCTURE_POLICY_NOTICE'] == structure['notice']
    limits['monthlyBudgetUnits'] = structure['callCostUnits'] - 1
    with pytest.raises(ValueError, match='BETA_STRUCTURE_AI_COST_UNCONFIRMED'):
        external_ai_configuration(receipt)


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
    from test_baze_provider import approved_config
    external = approved_config()
    receipt['externalAi'] = {
        'approved': True, 'notice': 'Synthetic provider and processing notice',
        'policyVersion': external['AI_POLICY_VERSION'],
        'gateway': external['BAZE_GATEWAY'], 'limits': external['AI_LIMITS'],
    }
    gate.write_text(json.dumps(receipt))
    config = operating_configuration(root, repo)
    assert config['AI_ENABLED_DEFAULT'] and config['EXTERNAL_AI_TERMS_APPROVED']
    assert config['AI_POLICY_NOTICE'] == receipt['externalAi']['notice']
    receipt['externalAi']['gateway']['pricingConfirmed'] = False
    gate.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='BAZE_CONFIGURATION_UNCONFIRMED'):
        operating_configuration(root, repo)
    del receipt['externalAi']
    gate.write_text(json.dumps(receipt))
    proof=archive.with_suffix('.verified.json');value=json.loads(proof.read_text());value['createdAt']=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat();proof.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='BACKUP'):operating_configuration(root,repo)
    assert operating_configuration(root,repo,require_fresh_backup=False)['RETENTION_APPROVED']
    value['createdAt']=datetime.now(timezone.utc).isoformat();proof.write_text(json.dumps(value))
    receipt['gates']['G4']='FAIL';gate.write_text(json.dumps(receipt))
    with pytest.raises(ValueError,match='GATES'):operating_configuration(root,repo)
    receipt['gates']['G4']='PASS';gate.write_text(json.dumps(receipt));code.write_text('modified')
    with pytest.raises(ValueError,match='CODE_CHANGED'):operating_configuration(root,repo)
