from __future__ import annotations

from .concepts import normalize_predicate
from .thresholds import (
    HIGH_EQUIVALENCE_THRESHOLD,
    LOW_MORPHOLOGY_CONFIDENCE,
    RELATED_MEANING_THRESHOLD,
    SEMANTIC_WEIGHTS,
)


LABELS = {
    "highly_equivalent": "같은 의미일 가능성이 높음",
    "related_meaning": "비슷하거나 관련된 의미",
    "different_meaning": "다른 의미",
    "undecidable": "판단 보류",
}


def compare_semantics(left: dict, right: dict, left_morphology: dict, right_morphology: dict) -> dict:
    matched: list[dict] = []
    different: list[dict] = []
    blockers: list[dict] = []

    role_score = _role_score(left, right, matched, different, blockers)
    predicate_score = _predicate_score(left, right, matched, different, blockers)
    concept_score = _set_score(_concept_groups(left), _concept_groups(right))
    _record("concepts", _concept_groups(left), _concept_groups(right), concept_score, matched, different)
    polarity_score = _equal_score(left.get("polarity"), right.get("polarity"))
    _record("polarity", left.get("polarity"), right.get("polarity"), polarity_score, matched, different)
    if polarity_score == 0:
        blockers.append(_blocker("polarity", "긍정과 부정이 다릅니다."))

    grammar_fields = ["tense", "aspect", "modality"]
    grammar_scores = [_equal_score(left.get(key), right.get(key)) for key in grammar_fields]
    grammar_score = sum(grammar_scores) / len(grammar_scores)
    for key, value in zip(grammar_fields, grammar_scores):
        _record(key, left.get(key), right.get(key), value, matched, different)
    if left.get("modality") != right.get("modality"):
        blockers.append(_blocker("modality", "가능·의무·추정 같은 양태가 다릅니다."))

    entity_score = (_set_score(left.get("numbers", []), right.get("numbers", [])) + _set_score(left.get("properNouns", []), right.get("properNouns", []))) / 2
    if set(left.get("numbers", [])) != set(right.get("numbers", [])):
        blockers.append(_blocker("numbers", "수치나 날짜가 다릅니다."))
    if set(left.get("properNouns", [])) != set(right.get("properNouns", [])):
        blockers.append(_blocker("proper_nouns", "고유명사가 다릅니다."))

    _voice_and_relation_blockers(left, right, blockers)
    _quotation_blockers(left, right, blockers)

    scores = {
        "roles": role_score,
        "predicate": predicate_score,
        "concepts": concept_score,
        "polarity": polarity_score,
        "grammar": grammar_score,
        "entities": entity_score,
    }
    similarity = round(sum(scores[key] * SEMANTIC_WEIGHTS[key] for key in SEMANTIC_WEIGHTS), 3)
    morphology_confidence = round(min(float(left_morphology.get("confidence", 0)), float(right_morphology.get("confidence", 0))), 3)
    if morphology_confidence < LOW_MORPHOLOGY_CONFIDENCE:
        blockers.append(_blocker("low_morphology_confidence", "형태소 분석 신뢰도가 낮아 의미를 확정하기 어렵습니다."))
        label = "undecidable"
    elif blockers:
        label = "different_meaning"
    elif similarity >= HIGH_EQUIVALENCE_THRESHOLD:
        label = "highly_equivalent"
    elif similarity >= RELATED_MEANING_THRESHOLD:
        label = "related_meaning"
    else:
        label = "different_meaning"

    return {
        "morphological_confidence": morphology_confidence,
        "semantic_similarity": similarity,
        "label": label,
        "labelKo": LABELS[label],
        "matched_elements": matched,
        "different_elements": different,
        "blockers": _deduplicate_blockers(blockers),
        "componentScores": {key: round(value, 3) for key, value in scores.items()},
        "explanation": _explanation(label, blockers, matched, different),
        "heuristicNotice": "점수와 임계값은 논문 평가 점수가 아닌 글빛 프로젝트의 초기 공학적 휴리스틱입니다.",
    }


def _role_score(left, right, matched, different, blockers):
    values = []
    for key in ("subject", "target", "recipient"):
        value = _set_score(left.get(key, []), right.get(key, []))
        values.append(value)
        _record(key, left.get(key, []), right.get(key, []), value, matched, different)
    if set(left.get("subject", [])) == set(right.get("target", [])) and set(left.get("target", [])) == set(right.get("subject", [])) and (left.get("subject") or left.get("target")):
        blockers.append(_blocker("subject_target_swap", "주체와 대상의 역할이 서로 바뀌었습니다."))
    elif set(left.get("subject", [])) != set(right.get("subject", [])) or set(left.get("target", [])) != set(right.get("target", [])):
        blockers.append(_blocker("role_difference", "주체 또는 대상 역할이 다릅니다."))
    return sum(values) / len(values)


def _predicate_score(left, right, matched, different, blockers):
    left_group = left.get("predicateGroup") or normalize_predicate(left.get("predicate", ""))[0]
    right_group = right.get("predicateGroup") or normalize_predicate(right.get("predicate", ""))[0]
    score = _equal_score(left_group, right_group)
    _record("predicate", left.get("predicate"), right.get("predicate"), score, matched, different)
    if score == 0:
        blockers.append(_blocker("predicate_relation", "핵심 서술 관계가 다릅니다."))
    return score


def _voice_and_relation_blockers(left, right, blockers):
    if bool(left.get("causative")) != bool(right.get("causative")):
        blockers.append(_blocker("causative", "사동 여부가 다릅니다."))
    if bool(left.get("passive")) != bool(right.get("passive")):
        blockers.append(_blocker("passive", "피동 여부가 다릅니다."))
    if left.get("relation") != right.get("relation"):
        key = "cause_effect" if "cause_effect" in {left.get("relation"), right.get("relation")} else "comparison"
        blockers.append(_blocker(key, "비교 또는 원인·결과 관계가 다릅니다."))


def _quotation_blockers(left, right, blockers):
    left_quotes = left.get("quotation") or []
    right_quotes = right.get("quotation") or []
    if [item.get("text") for item in left_quotes] != [item.get("text") for item in right_quotes]:
        if left_quotes or right_quotes:
            blockers.append(_blocker("quotation_content", "직접 인용문의 핵심 내용이 다릅니다."))
    if [item.get("speaker") for item in left_quotes] != [item.get("speaker") for item in right_quotes]:
        if left_quotes or right_quotes:
            blockers.append(_blocker("quotation_speaker", "인용 주체가 다릅니다."))
    if [item.get("action") for item in left_quotes] != [item.get("action") for item in right_quotes]:
        if left_quotes or right_quotes:
            blockers.append(_blocker("quotation_action", "인용 행위가 다릅니다."))


def _concept_groups(value):
    return [item["group"] for item in value.get("concepts", []) if item.get("verified") and item.get("group")]


def _set_score(left, right):
    left_set, right_set = set(left or []), set(right or [])
    if not left_set and not right_set:
        return 1.0
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _equal_score(left, right):
    if not left and not right:
        return 1.0
    return 1.0 if left == right else 0.0


def _record(name, left, right, score, matched, different):
    item = {"element": name, "left": left, "right": right, "score": round(score, 3)}
    (matched if score == 1 else different).append(item)


def _blocker(code, reason):
    return {"code": code, "reason": reason}


def _deduplicate_blockers(values):
    return list({item["code"]: item for item in values}.values())


def _explanation(label, blockers, matched, different):
    if label == "undecidable":
        return "형태소 분석의 복수 후보 또는 낮은 신뢰도 때문에 사람의 확인이 필요합니다."
    if blockers:
        return "단어가 비슷하더라도 " + " ".join(item["reason"] for item in _deduplicate_blockers(blockers))
    if label == "highly_equivalent":
        return "주체·대상·핵심 서술·극성과 주요 개념이 일치합니다."
    if label == "related_meaning":
        return "주요 요소 일부는 일치하지만 표현 관계가 완전히 같다고 확정할 수 없습니다."
    return "핵심 의미 요소의 일치가 부족합니다."
