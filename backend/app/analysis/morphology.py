from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass


VERB_TAGS = {"VV", "VA", "VX", "VCP", "VCN", "XSV", "XSA"}
PARTICLE_PREFIX = "J"
ENDING_PREFIX = "E"
NEGATIVE_FORMS = {"안", "않", "못", "없", "아니", "말"}
PASSIVE_LEMMAS = {"고립되다", "밝혀지다", "쓰이다", "읽히다", "잡히다", "열리다", "불리다", "닫히다"}
_KIWI = None
_KIWI_ERROR: str | None = None
_LOCK = threading.Lock()


def kiwi_available() -> bool:
    _get_kiwi()
    return _KIWI is not None


def kiwi_error() -> str | None:
    _get_kiwi()
    return _KIWI_ERROR


def _get_kiwi():
    global _KIWI, _KIWI_ERROR
    if _KIWI is not None or _KIWI_ERROR is not None:
        return _KIWI
    with _LOCK:
        if _KIWI is not None or _KIWI_ERROR is not None:
            return _KIWI
        try:
            from kiwipiepy import Kiwi

            _KIWI = Kiwi(num_workers=-1, model_type="cong")
        except Exception as exc:  # 선택 의존성 실패 시 전체 분석을 중단하지 않는다.
            _KIWI_ERROR = type(exc).__name__
    return _KIWI


def _lemma(form: str, tag: str) -> str:
    if _base_tag(tag) in VERB_TAGS and form not in {"이다", "아니다"}:
        return form if form.endswith("다") else f"{form}다"
    return form


def _base_tag(tag: str) -> str:
    return tag.split("-", 1)[0]


def _token_dict(token, text: str) -> dict:
    length = getattr(token, "len", len(token.form))
    start = int(getattr(token, "start", 0))
    return {
        "surface": text[start : start + length] or token.form,
        "form": token.form,
        "pos": token.tag,
        "lemma": _lemma(token.form, token.tag),
        "start": start,
        "end": start + length,
    }


def analyze_morphology(text: str, top_n: int = 3) -> dict:
    kiwi = _get_kiwi()
    if kiwi is None:
        return _fallback_analysis(text)
    try:
        candidates = kiwi.analyze(text, top_n=max(1, top_n))
        tokens, score = candidates[0]
        mapped = [_token_dict(token, text) for token in tokens]
        alternatives = []
        best_signature = tuple((token.form, token.tag) for token in tokens)
        next_distinct_score = None
        for alt_tokens, alt_score in candidates[1:]:
            signature = tuple((token.form, token.tag) for token in alt_tokens)
            if signature == best_signature:
                continue
            if next_distinct_score is None:
                next_distinct_score = float(alt_score)
            alternatives.append({
                "score": round(float(alt_score), 4),
                "morphemes": [{"form": token.form, "pos": token.tag, "lemma": _lemma(token.form, token.tag)} for token in alt_tokens],
            })
        if next_distinct_score is not None:
            gap = max(0.0, float(score) - next_distinct_score)
            confidence = 0.55 + 0.43 * (1 - math.exp(-gap / 5))
        else:
            confidence = 0.82
        return _summarize(text, mapped, round(min(0.98, confidence), 3), alternatives, "kiwi")
    except Exception as exc:
        result = _fallback_analysis(text)
        result["analyzerError"] = type(exc).__name__
        return result


def _summarize(text: str, tokens: list[dict], confidence: float, alternatives: list[dict], analyzer: str) -> dict:
    verb_tokens = [item for item in tokens if _base_tag(item["pos"]) in VERB_TAGS]
    main = next((item for item in verb_tokens if _base_tag(item["pos"]) != "VX"), verb_tokens[0] if verb_tokens else None)
    auxiliaries = [item["lemma"] for item in verb_tokens if _base_tag(item["pos"]) == "VX"]
    forms = [item["form"] for item in tokens]
    compact = re.sub(r"\s+", "", text)
    polarity = "negative" if any(form in NEGATIVE_FORMS for form in forms) or re.search(r"지않|지못|아니|없", compact) else "positive"
    tense = "past" if any(form in {"었", "았", "였", "더"} for form in forms) or re.search(r"[았었였]다", compact) else "future" if "겠" in forms else "present"
    aspect = "progressive" if re.search(r"고\s*있", text) else "completed" if re.search(r"(어|아|여)\s*(버리|내)", text) else "simple"
    modality = _modality(text, forms)
    causative = bool(re.search(r"시[키켰킨킬킴]|게\s*하", text)) or "시키" in forms
    passive = bool(re.search(r"(되|받|당하|어지|아지|여지)", text)) or (main is not None and main["lemma"] in PASSIVE_LEMMAS)
    return {
        "surface": text,
        "morphemes": tokens,
        "lemmas": [item["lemma"] for item in tokens],
        "particles": [item for item in tokens if item["pos"].startswith(PARTICLE_PREFIX)],
        "endings": [item for item in tokens if item["pos"].startswith(ENDING_PREFIX)],
        "mainVerb": main["lemma"] if main else "",
        "auxiliaryVerbs": auxiliaries,
        "polarity": polarity,
        "tense": tense,
        "aspect": aspect,
        "modality": modality,
        "causative": causative,
        "passive": passive,
        "confidence": confidence,
        "alternatives": alternatives,
        "analyzer": analyzer,
    }


def _modality(text: str, forms: list[str]) -> str:
    compact = re.sub(r"\s+", "", text)
    if re.search(r"해야|하여야|[어아여]?야(?:하|한|합|했|해)", compact):
        return "obligation"
    if re.search(r"수있|가능하", compact):
        return "possibility"
    if re.search(r"것같|듯하|모르", compact):
        return "uncertainty"
    if "겠" in forms or re.search(r"려고하", compact):
        return "intention"
    return "assertive"


def _fallback_analysis(text: str) -> dict:
    tokens = []
    for match in re.finditer(r"[가-힣A-Za-z0-9]+|[^\s]", text):
        surface = match.group(0)
        tag = "NNG" if re.fullmatch(r"[가-힣A-Za-z0-9]+", surface) else "SW"
        tokens.append({"surface": surface, "form": surface, "pos": tag, "lemma": surface, "start": match.start(), "end": match.end()})
    result = _summarize(text, tokens, 0.35, [], "fallback")
    result["notice"] = "Kiwi를 사용할 수 없어 제한된 규칙 분석을 사용했습니다."
    return result
