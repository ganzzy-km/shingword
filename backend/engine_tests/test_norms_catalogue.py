import hashlib
import json
from pathlib import Path
import unicodedata

import pytest
from backend.app.analysis.norms_catalogue import load_catalogue, catalogue_manifest, detector_provisions, CATALOGUE_SHA256
from backend.app.analysis.norms_catalogue import provision_reference
from backend.app.analysis.norms_catalogue import provision_index


def test_full_reference_normalization_and_source_spans():
    data = load_catalogue()
    assert len(data["pages"]) == 314
    assert len(data["provisions"]) == 134
    for page in data["pages"]:
        text = page["text"]
        assert text == unicodedata.normalize("NFC", text) and "\r" not in text
        assert hashlib.sha256(text.encode()).hexdigest() == page["textSha256"]
    for group, count in [("SPELLING",57),("PUNCTUATION",21),("STANDARD_WORD",26),("PRONUNCIATION",30)]:
        assert [p["article"] for p in data["provisions"] if p["category"] == group] == list(range(1,count+1))
    for provision in data["provisions"]:
        assert provision["defaultReference"] and not provision["autoApply"]
        assert provision["sourceSegments"]
        for segment in provision["sourceSegments"]:
            text = data["pages"][segment["page"]-1]["text"]
            assert 0 <= segment["start"] < segment["end"] <= len(text)
            value = text[segment["start"]:segment["end"]]
            assert hashlib.sha256(value.encode()).hexdigest() == segment["textSha256"]
        for marker in provision["exception"]["markers"]:
            assert data["pages"][marker["page"]-1]["text"][marker["start"]:marker["end"]] == marker["label"]


def test_defaults_and_reference_only_never_claim_executable_approval():
    metadata = catalogue_manifest()
    assert metadata["sha256"] == CATALOGUE_SHA256
    assert metadata["linkedProvisions"] == 11 and metadata["referenceOnlyProvisions"] == 123
    assert detector_provisions("gb-local-001") == ["SPELLING-042"]
    assert detector_provisions("gb-local-003") == []
    for p in load_catalogue()["provisions"]:
        assert not p["condition"]["interpretationVerified"]
        assert p["exampleReview"] == "NOT_INFERRED_FROM_TABLE_COLUMNS"
        if not p["detectorRuleIds"]:
            assert p["execution"] == "REFERENCE_ONLY"

def test_all_normalized_display_entries_cover_the_pinned_source():
    index = provision_index()
    assert len(index) == 134 and len({p['id'] for p in index}) == 134
    assert sum(bool(p['detectorRuleIds']) for p in index) == 11
    for summary, original in zip(index, load_catalogue()['provisions']):
        assert summary['title'] and summary['categoryLabel']
        assert summary['pages'] == sorted({s['page'] for s in original['sourceSegments']})
        assert summary['autoApply'] is False
    index[0]['detectorRuleIds'].append('fake')
    assert 'fake' not in provision_index()[0]['detectorRuleIds']


def test_corrupted_catalogue_rejected(tmp_path):
    path = tmp_path / "changed.json"
    path.write_text('{"schemaVersion":"geulbit.norms.catalogue/1"}')
    with pytest.raises(ValueError, match="NORMS_CATALOGUE_INTEGRITY_INVALID"):
        load_catalogue(path)


def test_every_provision_available_as_primary_basis_with_full_exceptions():
    for provision in load_catalogue()["provisions"]:
        record = provision_reference(provision["rule_id"])
        assert record["source"]["referenceRole"] == "PRIMARY_NORMATIVE_BASIS"
        assert record["exception"] == provision["exception"]
        assert len(record["passages"]) == len(provision["sourceSegments"])
        for passage in record["passages"]:
            assert hashlib.sha256(passage["text"].encode()).hexdigest() == passage["textSha256"]
        record["exception"]["markers"].clear()
        assert provision_reference(provision["rule_id"])["exception"] == provision["exception"]
    with pytest.raises(ValueError, match="NORMATIVE_PROVISION_NOT_FOUND"):
        provision_reference("UNKNOWN-001")


def test_offline_import_reproducible():
    source = Path("C:/Users/USER/Pictures/geulbit_korean_norms_reference_v1.pdf")
    if not source.exists():
        pytest.skip("Supplied PDF unavailable outside local reference verification")
    import importlib.util
    script = Path(__file__).resolve().parents[2] / "scripts" / "normalize_korean_norms.py"
    spec = importlib.util.spec_from_file_location("norms_import", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    encoded = (json.dumps(module.build(source), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    assert hashlib.sha256(encoded).hexdigest() == CATALOGUE_SHA256
