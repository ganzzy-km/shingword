"""Release-only optional binding: no secret/global env mutation or fallback."""
import hashlib,json,os
from pathlib import Path
import pytest
import v2_fixture
from app.v2.beta_runtime import approved_ocr_runtime

sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

@pytest.fixture
def binding(tmp_path):
    manifest=tmp_path/'models.json';manifest.write_text('{}')
    evidence=tmp_path/'resources.json';evidence.write_text('{"status":"PASS"}')
    executable=tmp_path/'synthetic-python.exe';executable.write_bytes(b'not executable: binding contract only')
    config=tmp_path/'ocr.json';value={'python':str(executable),'models':str(tmp_path),'tesseract':str(executable),
        'tessdata':str(tmp_path),'manifest':str(manifest),'manifestSha':sha(manifest),
        'resourceEvidence':{'path':str(evidence),'sha256':sha(evidence)}}
    config.write_text(json.dumps(value))
    return {'ocrRuntime':{'configPath':str(config),'configSha256':sha(config),'manifestSha256':sha(manifest)}},config,value

def test_legacy_receipt_has_no_runtime_side_effect():
    before=dict(os.environ);assert approved_ocr_runtime({})=={};assert dict(os.environ)==before

def test_exact_optional_runtime_is_app_local(binding):
    receipt,config,_=binding;before=dict(os.environ)
    assert approved_ocr_runtime(receipt)=={'OCR_LOCAL_CONFIG':str(config)}
    assert dict(os.environ)==before

@pytest.mark.parametrize('what',['config','manifest','evidence','python'])
def test_changed_or_missing_runtime_fails_closed(binding,what):
    receipt,config,value=binding
    if what=='config':config.write_text('{}')
    elif what=='manifest':Path(value['manifest']).write_text('changed')
    elif what=='evidence':Path(value['resourceEvidence']['path']).write_text('changed')
    else:Path(value['python']).unlink()
    with pytest.raises(ValueError,match='OCR_RELEASE_'):approved_ocr_runtime(receipt)

@pytest.mark.parametrize('key',['configPath','configSha256','manifestSha256'])
def test_incomplete_binding_is_not_optional_fallback(binding,key):
    receipt,_,_=binding;del receipt['ocrRuntime'][key]
    with pytest.raises(ValueError,match='OCR_RELEASE_'):approved_ocr_runtime(receipt)
