from __future__ import annotations

from .morphology import analyze_morphology, kiwi_available, kiwi_error
from .quotation import extract_quotations
from .semantic_compare import compare_semantics
from .semantic_roles import extract_semantic_roles


def analyze_sentence(text: str) -> dict:
    morphology = analyze_morphology(text)
    return {
        "text": text,
        "morphology": morphology,
        "semanticRoles": extract_semantic_roles(text, morphology),
    }


def compare_sentences(left: str, right: str) -> dict:
    left_result = analyze_sentence(left)
    right_result = analyze_sentence(right)
    comparison = compare_semantics(
        left_result["semanticRoles"],
        right_result["semanticRoles"],
        left_result["morphology"],
        right_result["morphology"],
    )
    return {"left": left_result, "right": right_result, **comparison}


def analyze_document(text: str, sentences: list[dict]) -> dict:
    sentence_results = []
    for sentence in sentences:
        result = analyze_sentence(sentence["text"])
        sentence_results.append({
            "sentenceNumber": sentence["number"],
            "paragraphNumber": sentence["paragraph"],
            "startOffset": sentence["start"],
            "endOffset": sentence["end"],
            **result,
        })
    confidences = [item["morphology"].get("confidence", 0) for item in sentence_results]
    return {
        "version": 1,
        "analyzer": "kiwi" if kiwi_available() else "fallback",
        "analyzerError": kiwi_error(),
        "morphologicalConfidence": round(sum(confidences) / len(confidences), 3) if confidences else None,
        "quotations": [item.to_dict() for item in extract_quotations(text)],
        "sentences": sentence_results,
        "heuristicNotice": "형태소 신뢰도와 의미 점수는 분리되며, 의미 임계값은 글빛 프로젝트의 초기 공학적 휴리스틱입니다.",
    }

