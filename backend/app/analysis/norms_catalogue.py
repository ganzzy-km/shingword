"""Pinned, offline normative reference. Only reviewed detectors emit findings."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from copy import deepcopy
import unicodedata
from .reviewed_norms import provision_links

CATEGORY_LABELS = {"SPELLING": "한글 맞춤법", "PUNCTUATION": "문장 부호", "STANDARD_WORD": "표준어 사정", "PRONUNCIATION": "표준 발음"}

CATALOGUE_SHA256 = "cb5afaad5129f66d1be4de01187b1a77077239d230ceccfd8656cdfb77c31ace"
CATALOGUE_PATH = Path(__file__).parent / "data" / "korean_norms_v1.json"


def load_catalogue(path=CATALOGUE_PATH):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != CATALOGUE_SHA256:
        raise ValueError("NORMS_CATALOGUE_INTEGRITY_INVALID")
    value = json.loads(raw)
    if value["schemaVersion"] != "geulbit.norms.catalogue/1" or len(value["provisions"]) != 134:
        raise ValueError("NORMS_CATALOGUE_SCHEMA_INVALID")
    ids = [p['rule_id'] for p in value['provisions']]
    if len(set(ids)) != len(ids) or len(value['pages']) != value['pageCount']:
        raise ValueError("NORMS_CATALOGUE_SCHEMA_INVALID")
    for page in value['pages']:
        text = page['text']
        if text != unicodedata.normalize('NFC', text) or '\r' in text or hashlib.sha256(text.encode('utf-8')).hexdigest() != page['textSha256']:
            raise ValueError("NORMS_CATALOGUE_NORMALIZATION_INVALID")
    for p in value['provisions']:
        if p['category'] not in CATEGORY_LABELS or p['autoApply'] or not p['sourceSegments']:
            raise ValueError("NORMS_CATALOGUE_SCHEMA_INVALID")
        for segment in p['sourceSegments']:
            text = value['pages'][segment['page']-1]['text']
            if not 0 <= segment['start'] < segment['end'] <= len(text) or hashlib.sha256(text[segment['start']:segment['end']].encode('utf-8')).hexdigest() != segment['textSha256']:
                raise ValueError("NORMS_CATALOGUE_SPAN_INVALID")
    return value


@lru_cache(maxsize=1)
def _default_catalogue():
    return load_catalogue()


@lru_cache(maxsize=1)
def _manifest_data():
    value = _default_catalogue()
    linked = sum(bool(_detector_ids(p)) for p in value["provisions"])
    return {"version": value["version"], "sha256": CATALOGUE_SHA256,
            "sourceSha256": value["sourceSha256"], "pageCount": value["pageCount"],
            "provisionCount": value["provisionCount"], "defaultReference": True,
            "linkedProvisions": linked, "referenceOnlyProvisions": len(value['provisions']) - linked,
            "currentNormsChecked": value["currentNormsChecked"],
            "referenceRole": "PRIMARY_NORMATIVE_BASIS",
            "scope": ["SPELLING", "SPACING", "PUNCTUATION", "STANDARD_WORD", "PRONUNCIATION_REFERENCE"],
            "allProvisionsAvailable": True,
            "decisionPolicy": "REVIEWED_CONDITIONS_AND_EXCEPTIONS_REQUIRED",
            "normalizationVersion": value["normalizationVersion"]}


def catalogue_manifest():
    return deepcopy(_manifest_data())


def detector_provisions(rule_id):
    return [p["rule_id"] for p in _default_catalogue()["provisions"]
            if rule_id in _detector_ids(p)]


@lru_cache(maxsize=1)
def _resolved_links():
    additions = provision_links()
    return {p['rule_id']: tuple(dict.fromkeys(p['detectorRuleIds'] + additions.get(p['rule_id'], [])))
            for p in _default_catalogue()['provisions']}


def _detector_ids(provision):
    return list(_resolved_links()[provision['rule_id']])


def _execution(provision):
    return 'BOUNDED_CANDIDATES' if _detector_ids(provision) else 'REFERENCE_ONLY'


def _execution_reason(provision):
    if _detector_ids(provision):
        return '테스트로 검증한 제한된 표현만 탐지합니다. 조항 전체의 자동 판정은 아닙니다.'
    if provision['category'] == 'PRONUNCIATION':
        return '발음 규정은 실제 발음·한자어·형태소 경계 등의 근거가 필요합니다. 글의 표기만으로 발음 오류를 단정하지 않습니다.'
    return '형태소·단어 뜻·허용 표기·표의 관계를 검증한 판정 조건이 필요합니다. 승인만으로 오류 목록을 추정하지 않습니다.'


def provision_index():
    """Detached, normalized display index. Full source remains the pinned catalogue."""
    return [{"id": p['rule_id'], "title": f"{CATEGORY_LABELS[p['category']]} 제{p['article']}항",
             "category": p['category'], "categoryLabel": CATEGORY_LABELS[p['category']],
             "execution": _execution(p), "executionReason": _execution_reason(p), "detectorRuleIds": _detector_ids(p),
             "pages": sorted({s['page'] for s in p['sourceSegments']}), "autoApply": False}
            for p in _default_catalogue()['provisions']]


def provision_reference(provision_id):
    """Full provision and commentary, without inferring correct/error table columns.

    Coordinates address the immutable normalized reference, never essay spans.
    Return detached records so a caller cannot mutate the default source.
    """
    catalogue = _default_catalogue()
    for provision in catalogue["provisions"]:
        if provision["rule_id"] == provision_id:
            record = deepcopy(provision)
            record['detectorRuleIds'] = _detector_ids(provision)
            record['execution'] = _execution(provision)
            record['executionReason'] = _execution_reason(provision)
            record["source"] = catalogue_manifest()
            record["passages"] = [dict(segment, text=catalogue["pages"][segment["page"]-1]["text"][segment["start"]:segment["end"]])
                                  for segment in provision["sourceSegments"]]
            return record
    raise ValueError("NORMATIVE_PROVISION_NOT_FOUND")
