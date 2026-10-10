from __future__ import annotations

import re

from .quotation import QuotationRange, containing_quotation, extract_quotations


RULES = [
    (re.compile(r"할수\s+있다"), "할 수 있다", "명백한 오류", "의존 명사 '수'는 앞말과 띄어 씁니다.", "한글 맞춤법 제42항", True, "spacing"),
    (re.compile(r"몇일"), "며칠", "명백한 오류", "날짜를 나타내는 말은 '며칠'로 적습니다.", "한글 맞춤법 제27항", True, "spelling"),
    (re.compile(r"외곡"), "왜곡", "명백한 오류", "'사실과 다르게 해석함'을 뜻하는 표준 표기는 '왜곡'입니다.", "표준어 표기", True, "spelling"),
    (re.compile(r"상징적으러"), "상징적으로", "명백한 오류", "부사형 조사는 '으로'를 사용하므로 '상징적으로'로 적습니다.", "조사 결합", True, "typo"),
    (re.compile(r"로써"), None, "문맥 확인 필요", "자격은 '로서', 수단은 '로써'를 사용하므로 문맥 확인이 필요합니다.", "어문 규범 일반", False, "context"),
]

ABSTRACT_OBJECTS = {"내면", "감정", "본질", "진실", "갈등", "특징", "의미", "모습", "생각", "정체성", "상처", "주제", "의도", "성격", "심리", "현실"}
LIFTABLE_OBJECTS = {"상자", "짐", "가방", "돌", "물건", "책", "의자"}


def spelling_findings(text: str, quotations: list[QuotationRange] | None = None) -> list[dict]:
    quotations = quotations if quotations is not None else extract_quotations(text)
    findings: list[dict] = []
    for pattern, replacement, status, reason, clause, auto, error_type in RULES:
        for match in pattern.finditer(text):
            findings.append(_finding(match, replacement, status, reason, clause, auto, error_type, quotations))

    for match in re.finditer(r"(?P<object>[가-힣A-Za-z0-9]+)(?:을|를)\s+(?P<verb>들어내다|들어낸다|들어냈(?:다|어요|습니다))", text):
        obj = match.group("object")
        if obj in LIFTABLE_OBJECTS:
            continue
        word_start, word_end = match.span("verb")
        pseudo = re.match(r".+", text[word_start:word_end])
        if pseudo:
            pseudo_start = word_start
            pseudo_end = word_end
            quote = containing_quotation(pseudo_start, pseudo_end, quotations)
            findings.append({
                "current": text[pseudo_start:pseudo_end],
                "suggestion": text[pseudo_start:pseudo_end].replace("들어", "드러", 1),
                "status": "인용문 내부 오류 가능성" if quote else "문맥상 어휘 선택 확인",
                "reason": f"'{obj}'이 보이거나 알려지게 한다는 뜻에는 '드러내다'가 자연스럽습니다. 물건을 들어 옮기는 뜻이면 '들어내다'가 맞으므로 문맥을 확인해 주세요.",
                "rule": "문맥상 어휘 선택",
                "auto": False,
                "start": pseudo_start,
                "end": pseudo_end,
                "confidence": 0.78 if quote is None else 0.58,
                "errorType": "contextual_word_choice",
                "protectedQuote": quote.to_dict() if quote else None,
                "contextRequired": True,
            })
    return sorted(findings, key=lambda item: (item["start"], item["end"]))


def _finding(match, replacement, status, reason, clause, auto, error_type, quotations):
    quote = containing_quotation(match.start(), match.end(), quotations)
    if quote:
        status = "인용문 내부 오류 가능성"
        auto = False
        reason = f"직접 인용문 내부에서 {reason} 원문 인용일 수 있으므로 자동으로 바꾸지 않고 출처와 대조해야 합니다."
    return {
        "current": match.group(0),
        "suggestion": replacement,
        "status": status,
        "reason": reason,
        "rule": clause,
        "auto": auto,
        "start": match.start(),
        "end": match.end(),
        "confidence": 0.95 if auto else (0.62 if quote else 0.45),
        "errorType": error_type,
        "protectedQuote": quote.to_dict() if quote else None,
        "contextRequired": not auto,
    }
