from __future__ import annotations

import difflib
import re
from collections import Counter

from .quotation import extract_quotations
from .spelling import spelling_findings


SENTENCE_ENDINGS = ".!?。！？"
TRAILING_CLOSERS = "\"'”’)]}」』】"


def _sentence_spans(paragraph):
    quotations = extract_quotations(paragraph)

    def containing_quotation(position):
        matches = [item for item in quotations if item.start < position < item.end - 1]
        return max(matches, key=lambda item: item.end - item.start, default=None)

    def quotation_ends_sentence(position, quotation):
        remaining_quote = paragraph[position + 1 : quotation.end - 1]
        if remaining_quote.strip(SENTENCE_ENDINGS + " \t"):
            return False
        following = paragraph[quotation.end :]
        return not following or following[0].isspace()

    spans = []
    start = 0
    index = 0
    while index < len(paragraph):
        character = paragraph[index]
        quotation = containing_quotation(index)
        if character == "\n" and quotation is None:
            if paragraph[start:index].strip():
                spans.append((start, index))
            start = index + 1
            index += 1
            continue
        if character in SENTENCE_ENDINGS:
            if quotation is not None and not quotation_ends_sentence(index, quotation):
                index += 1
                continue
            end = quotation.end if quotation is not None else index + 1
            while end < len(paragraph) and paragraph[end] in SENTENCE_ENDINGS:
                end += 1
            while end < len(paragraph) and paragraph[end] in TRAILING_CLOSERS:
                end += 1
            if paragraph[start:end].strip():
                spans.append((start, end))
            start = end
            index = end
            continue
        index += 1
    if paragraph[start:].strip():
        spans.append((start, len(paragraph)))
    return spans


def split_sentences(text):
    results = []
    sentence_number = 0
    cursor = 0
    for paragraph_number, paragraph in enumerate(re.split(r"\n\s*\n", text), 1):
        if not paragraph.strip():
            cursor += len(paragraph) + 2
            continue
        start_base = text.find(paragraph, cursor)
        for span_start, span_end in _sentence_spans(paragraph):
            raw_sentence = paragraph[span_start:span_end]
            sentence = raw_sentence.strip()
            if not sentence:
                continue
            sentence_number += 1
            relative = span_start + len(raw_sentence) - len(raw_sentence.lstrip())
            start = start_base + relative
            results.append({"paragraph": paragraph_number, "number": sentence_number, "text": sentence, "start": start, "end": start + len(sentence)})
        cursor = start_base + len(paragraph)
    return results


def classify_role(text, inquiry_question=""):
    if any(x in text for x in ["따라서", "그러므로", "결국", "라고 볼 수"]):
        return "효과", 0.68, "결론이나 효과를 나타내는 연결 표현이 있습니다."
    if any(x in text for x in ["예를 들어", "실제로", "때문", "근거", "인용", "에서", "장면", "대사", "지문"]):
        return "근거", 0.58, "작품의 장면이나 근거를 제시하는 표현이 있습니다."
    if any(x in text for x in ["즉", "이는", "의미", "보여 준", "설명"]):
        return "설명", 0.58, "앞선 근거의 의미를 설명하는 표현이 있습니다."
    question_terms = meaningful_terms(inquiry_question)
    if question_terms and question_terms.intersection(meaningful_terms(text)):
        return "탐구 질문 연결", 0.52, "탐구 질문의 핵심 표현과 일부 겹칩니다."
    if len(text) >= 20:
        return "주장", 0.42, "서술형 핵심 문장으로 보이지만 의미 확정에는 사람의 확인이 필요합니다."
    return "분류되지 않음", None, "자동 분류 근거가 충분하지 않습니다."


def meaningful_terms(text):
    words = re.findall(r"[가-힣A-Za-z]{2,}", text or "")
    stop = {"그리고", "그러나", "따라서", "있다", "한다", "대한", "에서", "으로", "이다"}
    return {word for word in words if word not in stop}


def argument_links(sentences):
    links = []
    for claim in [x for x in sentences if x["role"] == "주장"]:
        candidates = [x for x in sentences if x["role"] == "근거" and x["number"] > claim["number"]]
        if not candidates:
            continue
        evidence = min(candidates, key=lambda x: x["number"] - claim["number"])
        details = {}
        details["sameParagraph"] = 2 if claim["paragraph"] == evidence["paragraph"] else 0
        details["nearby"] = 2 if evidence["number"] - claim["number"] <= 2 else 0
        overlap = meaningful_terms(claim["text"]).intersection(meaningful_terms(evidence["text"]))
        details["sameSubject"] = 2 if len(overlap) >= 2 else 0
        details["repeatedNoun"] = 1 if overlap else 0
        details["connector"] = 1 if any(x in evidence["text"] for x in ["예를 들어", "특히", "실제로", "때문"] ) else 0
        explanation = any(x in evidence["text"] for x in ["이는", "즉", "의미", "알 수 있다", "드러낸다", "보여 준다"]) or any(
            x["role"] == "설명"
            and x["paragraph"] == evidence["paragraph"]
            and 0 < x["number"] - evidence["number"] <= 2
            for x in sentences
        )
        details["followingExplanation"] = 2 if explanation else 0
        score = sum(details.values())
        status = "연결 가능성 높음" if score >= 7 else "연결 보완 필요" if score >= 4 else "연결이 불분명함"
        links.append({"claim": claim, "evidence": evidence, "score": score, "status": status, "details": details})
    return links


def peel_results(sentences, inquiry_question):
    paragraphs = sorted({x["paragraph"] for x in sentences})
    result = []
    question_terms = meaningful_terms(inquiry_question)
    for number in paragraphs:
        group = [x for x in sentences if x["paragraph"] == number]
        roles = {x["role"] for x in group}
        linked = any(question_terms.intersection(meaningful_terms(x["text"])) for x in group) if question_terms else False
        joined = " ".join(x["text"] for x in group)
        point = "주장" in roles or any(x in joined for x in ["주장", "핵심", "중심", "라고 볼 수", "상징한다", "나타낸다"])
        evidence = "근거" in roles or any(x in joined for x in ["예를 들어", "실제로", "인용", "장면", "대사", "지문", "본문에서"])
        explanation = "설명" in roles or any(x in joined for x in ["이는", "즉", "의미", "알 수 있다", "드러낸다", "보여 준다"])
        link = linked or bool(roles.intersection({"효과", "탐구 질문 연결"})) or any(x in joined for x in ["따라서", "그러므로", "결국", "이를 통해", "라고 볼 수"])
        elements = {
            "P": "충족" if point else "보완 필요",
            "E1": "충족" if evidence else "보완 필요",
            "E2": "충족" if explanation else "보완 필요",
            "L": "충족" if link else "보완 필요",
        }
        missing = [key for key, value in elements.items() if value != "충족"]
        guidance = "P·E·E·L 네 요소가 확인되었습니다." if not missing else f"{', '.join(missing)} 요소를 보완하고 문단의 논리 흐름을 직접 확인해 주세요."
        result.append({"paragraph": number, "elements": elements, "rationale": "문장 역할, 근거·설명·결론 표현과 탐구 질문 연결을 함께 확인한 결과입니다.", "guidance": guidance})
    return result


def quote_checks(text, quote_cards):
    checks = []
    cards = list(quote_cards)
    for quotation in extract_quotations(text):
        student = quotation.text
        exact = next((c for c in cards if c.quote_text == student or c.selected_text == student), None)
        if exact:
            status, confidence, source = "정확히 일치", 1.0, exact
        else:
            normalized = re.sub(r"[\s\W]+", "", student)
            scored = [(difflib.SequenceMatcher(None, normalized, re.sub(r"[\s\W]+", "", c.selected_text)).ratio(), c) for c in cards]
            score, source = max(scored, default=(0, None), key=lambda x: x[0])
            if score >= 0.95:
                status = "띄어쓰기나 문장 부호 차이"
            elif score >= 0.7:
                status = "원문과 다른 단어"
            else:
                status, source = "등록 자료에서 확인되지 않음", None
            confidence = score if source else None
        checks.append({"student": student, "source": source.quote_text if source else None, "status": status, "confidence": confidence, "card": source, "start": quotation.content_start, "end": quotation.content_end, "quotation": quotation.to_dict()})
    return checks


def metrics(sentences, links, peels, findings, inquiry_question):
    evidence_count = len([x for x in sentences if x["role"] == "근거"])
    explained = len([
        evidence for evidence in sentences if evidence["role"] == "근거" and (
            any(cue in evidence["text"] for cue in ["이는", "즉", "의미", "알 수 있다", "드러낸다", "보여 준다"])
            or any(
                candidate["role"] == "설명"
                and candidate["paragraph"] == evidence["paragraph"]
                and 0 < candidate["number"] - evidence["number"] <= 2
                for candidate in sentences
            )
        )
    ])
    peel_elements = [status for peel in peels for status in peel["elements"].values()]
    peel_satisfied = len([status for status in peel_elements if status == "충족"])
    question_terms = meaningful_terms(inquiry_question)
    linked = len([x for x in sentences if question_terms and question_terms.intersection(meaningful_terms(x["text"]))])

    def ratio(numerator, denominator, description, related):
        return {"value": round(numerator * 100 / denominator) if denominator else None, "calculable": bool(denominator), "numerator": numerator, "denominator": denominator, "description": description, "relatedType": related}

    return {
        "근거 연결률": ratio(len([x for x in links if x["score"] >= 4]), len(links), "주장과 근거의 휴리스틱 연결 비율", "argument"),
        "근거 분석률": ratio(explained, evidence_count, "근거 뒤에 의미 설명이 있는 비율", "argument"),
        "PEEL 충족률": ratio(peel_satisfied, len(peel_elements), "분석 대상 문단에서 확인된 P·E·E·L 요소의 비율", "peel"),
        "탐구 질문 연결률": ratio(linked, len(sentences), "탐구 질문 핵심어가 나타난 문장 비율", "inquiry"),
        "명백한 맞춤법 오류 수": {"value": len([x for x in findings if x["status"] == "명백한 오류"]), "calculable": True, "numerator": None, "denominator": None, "description": "자동 판정 가능한 규칙 위반 수", "relatedType": "spelling"},
        "수정 권장 수": {"value": len([x for x in findings if x["status"] == "수정 권장"]), "calculable": True, "numerator": None, "denominator": None, "description": "수정 권장 결과 수", "relatedType": "spelling"},
        "사용자 확인 필요 수": {"value": len([x for x in findings if x["status"] == "문맥 확인 필요"]), "calculable": True, "numerator": None, "denominator": None, "description": "사람의 문맥 확인이 필요한 결과 수", "relatedType": "spelling"},
    }
