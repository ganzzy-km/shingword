from __future__ import annotations

import time

from conftest import payload

from app.analysis.integration import analyze_sentence, compare_sentences
from app.analysis.quotation import extract_quotations
from app.analysis.spelling import spelling_findings


def test_four_quote_types_and_nested_ranges_are_preserved():
    text = '그는 "첫째"와 \'둘째\', “셋째 ‘안쪽’”을 말했다.'
    quotations = extract_quotations(text)
    assert {item.quote_type for item in quotations} == {
        "straight_double", "straight_single", "curly_double", "curly_single"
    }
    outer = next(item for item in quotations if item.text.startswith("셋째"))
    inner = next(item for item in quotations if item.text == "안쪽")
    assert outer.start < inner.start < inner.end < outer.end
    assert inner.depth > outer.depth
    assert text[outer.start:outer.end] == outer.raw


def test_spelling_is_separate_and_direct_quotes_are_protected():
    text = '작품은 “몇일 동안 외곡된 내면을 들어냈다”라고 설명했다. 상징적으러 보였다.'
    findings = spelling_findings(text)
    protected = [item for item in findings if item.get("protectedQuote")]
    assert {item["current"] for item in protected} >= {"몇일", "외곡", "들어냈다"}
    assert all(not item["auto"] and item["contextRequired"] for item in protected)
    typo = next(item for item in findings if item["current"] == "상징적으러")
    assert typo["suggestion"] == "상징적으로" and typo["auto"]


def test_contextual_deureonaeda_and_liftable_object_are_distinguished():
    abstract = spelling_findings("작품은 인물의 내면을 들어냈다.")
    assert abstract[0]["suggestion"] == "드러냈다"
    assert abstract[0]["errorType"] == "contextual_word_choice"
    assert abstract[0]["contextRequired"]
    assert spelling_findings("창고에서 상자를 들어냈다.") == []


def test_contextual_deureonaeda_dictionary_form_is_reviewed():
    finding = next(item for item in spelling_findings("작가는 주제를 들어내다.") if item["current"] == "들어내다")
    assert finding["suggestion"] == "드러내다"
    assert finding["contextRequired"] is True


def test_morphology_returns_lemma_grammar_and_alternatives():
    result = analyze_sentence("인물은 진실을 드러내고 있었다.")
    morphology = result["morphology"]
    assert morphology["analyzer"] == "kiwi"
    assert morphology["mainVerb"]
    assert morphology["aspect"] == "progressive"
    assert morphology["confidence"] > 0.5
    assert "morphemes" in morphology and "alternatives" in morphology
    assert result["semanticRoles"]["subject"] == ["인물"]
    assert result["semanticRoles"]["target"] == ["진실"]

    irregular = analyze_sentence("인물은 끝까지 걸었다.")["morphology"]
    assert "걷다" in irregular["lemmas"]
    auxiliary = analyze_sentence("인물은 진실을 드러내야 한다.")["morphology"]
    assert auxiliary["modality"] == "obligation"
    assert auxiliary["mainVerb"]


def test_semantic_blockers_override_word_overlap():
    swapped = compare_sentences("작가가 인물을 고립시켰다.", "인물이 작가를 고립시켰다.")
    assert swapped["label"] == "different_meaning"
    assert "subject_target_swap" in {item["code"] for item in swapped["blockers"]}

    polarity = compare_sentences("인물은 떠났다.", "인물은 떠나지 않았다.")
    assert "polarity" in {item["code"] for item in polarity["blockers"]}

    number = compare_sentences("인물은 3일 기다렸다.", "인물은 5일 기다렸다.")
    assert "numbers" in {item["code"] for item in number["blockers"]}

    quote = compare_sentences('인물은 “가겠다”라고 말했다.', '인물은 “안 가겠다”라고 말했다.')
    assert "quotation_content" in {item["code"] for item in quote["blockers"]}

    voice = compare_sentences("인물은 사회에서 고립되었다.", "사회가 인물을 고립시켰다.")
    voice_codes = {item["code"] for item in voice["blockers"]}
    assert "causative" in voice_codes or "passive" in voice_codes


def test_curated_predicate_group_can_support_near_equivalence():
    result = compare_sentences(
        "작품은 인물의 내면을 드러냈다.",
        "작품은 인물의 내면을 보여 주었다.",
    )
    assert result["label"] in {"highly_equivalent", "related_meaning"}
    assert not result["blockers"]


def test_semantic_compare_api_and_optional_dictionary(client):
    compared = client.post("/api/semantic/compare", json={
        "left": "작가가 인물을 고립시켰다.",
        "right": "인물이 작가를 고립시켰다.",
    })
    assert compared.status_code == 200
    assert payload(compared)["label"] == "different_meaning"

    status = payload(client.get("/api/dictionary/status"))
    assert status["status"] == "not_configured"
    lookup = payload(client.get("/api/dictionary/lookup?q=나무"))
    assert lookup["status"] == "not_configured"
    assert lookup["entries"] == []
    assert client.get("/local-admin/api-key").status_code == 404


def test_full_analysis_succeeds_without_dictionary_and_blocks_quote_apply(client):
    writing = payload(client.post("/api/writings", json={
        "title": "인용 보호",
        "work": "작품",
        "inquiryQuestion": "인물의 내면은 어떻게 드러나는가?",
        "content": '작가는 “몇일 동안 외곡했다”라고 썼다. 작품은 내면을 들어냈다.',
        "status": "임시 저장",
    }))
    started = payload(client.post("/api/analyses", json={"writingId": writing["id"]}))
    for _ in range(500):
        job = payload(client.get(f"/api/analysis-jobs/{started['jobId']}"))
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.02)
    assert job["status"] == "completed"
    result = payload(client.get(f"/api/analyses/{started['analysisId']}"))
    assert result["details"]["dictionaryVerification"]["status"] == "not_configured"
    assert result["details"]["dictionaryVerification"]["scoreAffected"] is False
    protected = next(item for item in result["findings"] if item["metadata"].get("protectedQuote"))
    assert client.post(f"/api/findings/{protected['id']}/apply").status_code == 409
