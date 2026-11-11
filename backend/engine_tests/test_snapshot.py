import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from analysis import snapshot


@pytest.mark.parametrize("text", ["", " \n\n\t", "한글 문장이다.", "가 e\u0301", "가😀나. 🐧 漢字.",
                                   "첫째.\r\n\r\n둘째.\r셋째.", "“인용. 계속!”이라 말했다.",
                                   "같은 문장.\n\n같은 문장."])
def test_golden_normalization_spans_and_coverage(text):
    result = snapshot.analyze_snapshot(text, version_id="golden-v1")
    canonical = snapshot.normalize_text(text)
    assert result["input"]["sha256"] == hashlib.sha256(canonical.encode()).hexdigest()
    snapshot.validate_snapshot(result, canonical, version_id="golden-v1")
    assert "text" not in result and "content" not in result
    assert "\r" not in canonical


def test_deterministic_json_and_real_kiwi():
    text = "학생은 작품의 의미를 살핀다. “함께 읽자.”라는 대사를 인용했다."
    a = snapshot.analyze_snapshot(text, version_id="v1")
    b = snapshot.analyze_snapshot(text, version_id="v1")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["manifest"]["analyzer"] == "kiwi"
    assert a["manifest"]["analyzerVersion"] and a["manifest"]["engineHash"]


@pytest.mark.parametrize("bad", [None, 12, "\ud800"])
def test_invalid_input_has_explicit_error(bad):
    with pytest.raises(ValueError):
        snapshot.analyze_snapshot(bad, version_id="v1")


def test_kiwi_failure_is_not_success(monkeypatch):
    monkeypatch.setattr(snapshot, "kiwi_available", lambda: False)
    with pytest.raises(snapshot.AnalysisUnavailable, match="KIWI_UNAVAILABLE"):
        snapshot.analyze_snapshot("글", version_id="v1")


def test_tampered_result_or_version_is_rejected():
    text = "첫 글. 같은 문장. 같은 문장."
    result = snapshot.analyze_snapshot(text, version_id="v1")
    with pytest.raises(ValueError, match="MANIFEST"):
        snapshot.validate_snapshot(result, text, version_id="v2")
    changed = copy.deepcopy(result)
    changed["sentences"][1]["start"] = 0
    with pytest.raises(ValueError, match="SPAN"):
        snapshot.validate_snapshot(changed, text, version_id="v1")


def test_package_has_no_framework_database_or_network_dependency():
    root = Path(__file__).resolve().parents[2]
    code = """
import sys,socket,sqlite3
sys.path.insert(0,'backend/app')
def forbidden(*a,**k):raise AssertionError('forbidden I/O')
socket.create_connection=forbidden
socket.socket.connect=forbidden
sqlite3.connect=forbidden
from analysis.structure import analyze_structure
result=analyze_structure('순수 분석이다.',version_id='v1')
assert result['sentences']
assert result['manifest']['normsCatalogue']['referenceRole']=='PRIMARY_NORMATIVE_BASIS'
assert not any(n in sys.modules for n in ('flask','sqlalchemy','app'))
"""
    subprocess.run([sys.executable, "-c", code], cwd=root, check=True, capture_output=True)


def test_frontend_utf16_matches_python_code_points():
    root = Path(__file__).resolve().parents[2]
    text = snapshot.normalize_text("가😀漢字\r\n한글 e\u0301")
    script = """
import fs from 'node:fs';import ts from './node_modules/typescript/lib/typescript.js';
const source=ts.transpileModule(fs.readFileSync('src/book-layout.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020}}).outputText;
const {utf16Offset}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const text=JSON.parse(process.argv[1]);console.log(JSON.stringify(Array.from({length:Array.from(text).length+1},(_,i)=>utf16Offset(text,i))));
"""
    output = subprocess.check_output(["node", "--input-type=module", "-e", script, json.dumps(text)], cwd=root)
    assert json.loads(output) == [len(text[:i].encode("utf-16-le")) // 2 for i in range(len(text)+1)]


@pytest.mark.parametrize("size", [10000, 30000])
def test_entire_long_essay_is_processed(size):
    text = ("문학은 삶을 비춘다. 🐧 인물은 책을 읽는다.\n\n" * 1500)[:size]
    result = snapshot.analyze_snapshot(text, version_id=f"long-{size}")
    assert result["input"]["codePoints"] == size
    assert result["partitions"][-1]["end"] == size
    assert result["sentences"][-1]["end"] >= len(text.rstrip())
