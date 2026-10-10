from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from flask import current_app

from ..analysis.engine import argument_links, classify_role, metrics, peel_results, quote_checks, spelling_findings, split_sentences
from ..analysis.integration import analyze_document, compare_sentences
from ..analysis.quotation import extract_quotations
from ..extensions import db
from ..models import (
    Analysis, AnalysisFinding, AnalysisJob, AnalysisSentence, ArgumentLink,
    PeelResult, QuoteCard, QuoteCheckResult, RubricItem, RubricResult,
    SpellingResult, Writing, WritingResource,
)


executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="geulbit-analysis")


STEPS = [
    "문장과 문단 나누기", "직접 인용문 보호", "형태소와 의미 역할 분석",
    "문장 역할 분석", "주장과 근거 연결 검사", "PEEL 구조 검사",
    "평가 기준 검사", "인용문 비교", "맞춤법 규칙 검사", "공식 사전 보조 검증", "결과 정리",
]


def submit_analysis(app, job_id):
    executor.submit(_run_analysis, app, job_id)


def _set_step(job, step, progress):
    job.status = "running"
    job.current_step = step
    job.progress = progress
    db.session.commit()


def _cancelled(job):
    db.session.refresh(job)
    if job.cancel_requested:
        job.status = "cancelled"
        job.current_step = "취소됨"
        analysis = db.session.get(Analysis, job.analysis_id)
        analysis.status = "cancelled"
        db.session.commit()
        return True
    return False


def _run_analysis(app, job_id):
    with app.app_context():
        job = db.session.get(AnalysisJob, job_id)
        if not job:
            return
        analysis = db.session.get(Analysis, job.analysis_id)
        writing = db.session.get(Writing, analysis.writing_id)
        completed = []
        try:
            _set_step(job, STEPS[0], 5)
            split = split_sentences(writing.content or "")
            completed.append(STEPS[0])
            if _cancelled(job): return

            _set_step(job, STEPS[1], 10)
            quotations = extract_quotations(writing.content or "")
            completed.append(STEPS[1])

            _set_step(job, STEPS[2], 17)
            linguistic = analyze_document(writing.content or "", split)
            analysis.settings = {**(analysis.settings or {}), "linguisticAnalysis": linguistic}
            db.session.commit()
            completed.append(STEPS[2])
            if _cancelled(job): return

            _set_step(job, STEPS[3], 25)
            classified = []
            for item in split:
                role, confidence, rationale = classify_role(item["text"], writing.inquiry_question)
                item.update({"role": role, "confidence": confidence, "rationale": rationale})
                sentence = AnalysisSentence(analysis_id=analysis.id, paragraph_number=item["paragraph"], sentence_number=item["number"], text=item["text"], start_offset=item["start"], end_offset=item["end"], auto_role=role, confidence=confidence, rationale=rationale)
                db.session.add(sentence)
                db.session.flush()
                item["id"] = sentence.id
                classified.append(item)
            db.session.commit()
            completed.append(STEPS[3])
            if _cancelled(job): return

            _set_step(job, STEPS[4], 36)
            links = argument_links(classified)
            for link in links:
                db.session.add(ArgumentLink(analysis_id=analysis.id, claim_sentence_id=link["claim"]["id"], evidence_sentence_id=link["evidence"]["id"], score=link["score"], status=link["status"], details=link["details"]))
                if link["score"] < 7:
                    db.session.add(AnalysisFinding(analysis_id=analysis.id, finding_type="argument", severity="warning", title=link["status"], current_text=link["evidence"]["text"], reason="주장과 근거의 거리, 핵심어 반복, 설명 문장 유무를 점검한 휴리스틱 결과입니다.", confidence=link["score"] / 10, start_offset=link["evidence"]["start"], end_offset=link["evidence"]["end"], metadata_json={"score": link["score"], "details": link["details"]}))
            completed.append(STEPS[4])
            if _cancelled(job): return

            _set_step(job, STEPS[5], 47)
            peels = peel_results(classified, writing.inquiry_question)
            for result in peels:
                db.session.add(PeelResult(analysis_id=analysis.id, paragraph_number=result["paragraph"], elements=result["elements"], rationale=result["rationale"], guidance=result["guidance"]))
            completed.append(STEPS[5])

            _set_step(job, STEPS[6], 57)
            rubric_ids = [x.resource_id for x in writing.resources if x.resource_type == "rubric"]
            for item in RubricItem.query.filter(RubricItem.rubric_id.in_(rubric_ids)).all() if rubric_ids else []:
                terms = [term for term in item.name.split() if len(term) >= 2]
                matches = [s["number"] for s in classified if any(term in s["text"] for term in terms)]
                status = "사람의 판단 필요" if item.check_type == "사람의 판단 필요" else "충족 가능성 높음" if matches else "확인되지 않음"
                db.session.add(RubricResult(analysis_id=analysis.id, rubric_item_id=item.id, status=status, rationale="평가 기준 핵심 표현과 글의 문장을 비교했습니다. 최종 판단은 사람이 해야 합니다.", related_sentences=matches))
            completed.append(STEPS[6])

            _set_step(job, STEPS[7], 67)
            quote_ids = [x.resource_id for x in writing.resources if x.resource_type == "quote"]
            cards = QuoteCard.query.filter(QuoteCard.id.in_(quote_ids)).all() if quote_ids else QuoteCard.query.filter_by(workspace_id="local-workspace").all()
            quote_results = quote_checks(writing.content or "", cards)
            for result in quote_results:
                card = result["card"]
                semantic = compare_sentences(result["student"], result["source"]) if result["source"] else None
                db.session.add(QuoteCheckResult(analysis_id=analysis.id, student_quote=result["student"], source_quote=result["source"], status=result["status"], confidence=result["confidence"], differences=semantic.get("different_elements", []) if semantic else [], source_document_id=card.document_id if card else None, source_page=card.page if card else None))
                if result["status"] != "정확히 일치":
                    db.session.add(AnalysisFinding(analysis_id=analysis.id, finding_type="citation", severity="warning", title=result["status"], current_text=result["student"], suggestion=result["source"], reason="업로드된 원문 자료와 인용문 카드를 기준으로 비교했습니다. 인용 내용·주체·행위를 분리해 확인하고, 찾지 못한 경우 원문과 쪽수를 직접 확인해 주세요.", confidence=result["confidence"], start_offset=result["start"], end_offset=result["end"], metadata_json={"sourcePage": card.page if card else None, "quotation": result.get("quotation"), "semanticComparison": semantic, "contextRequired": True, "protectedQuote": result.get("quotation")}))
            completed.append(STEPS[7])

            _set_step(job, STEPS[8], 77)
            spelling = spelling_findings(writing.content or "", quotations)
            for result in spelling:
                finding = AnalysisFinding(analysis_id=analysis.id, finding_type="spelling", severity="error" if result["status"] == "명백한 오류" else "warning", title=result["status"], current_text=result["current"], suggestion=result["suggestion"], reason=result["reason"], rule=result["rule"], source_url="https://korean.go.kr/", confidence=result["confidence"], start_offset=result["start"], end_offset=result["end"], metadata_json={"autoFixable": result["auto"], "contextRequired": result.get("contextRequired", not result["auto"]), "errorType": result.get("errorType"), "protectedQuote": result.get("protectedQuote")})
                db.session.add(finding)
                db.session.flush()
                db.session.add(SpellingResult(analysis_id=analysis.id, finding_id=finding.id, auto_fixable=result["auto"], context_question=None if result["auto"] else "이 표현이 나타내는 문맥을 직접 확인해 주세요."))
            completed.append(STEPS[8])
            if _cancelled(job): return

            _set_step(job, STEPS[9], 88)
            dictionary_client = app.extensions["dictionary_client"]
            candidates = _dictionary_candidates(linguistic, spelling)
            dictionary_result = _verify_dictionary(dictionary_client, candidates)
            analysis.settings = {**(analysis.settings or {}), "dictionaryVerification": dictionary_result}
            completed.append(STEPS[9])

            _set_step(job, STEPS[10], 96)
            analysis.metrics = metrics(classified, links, peels, spelling, writing.inquiry_question)
            analysis.status = "completed"
            writing.status = "분석 완료"
            job.status = "completed"
            job.progress = 100
            job.current_step = "완료"
            job.completed_steps = completed + [STEPS[10]]
            db.session.commit()
        except Exception:
            db.session.rollback()
            job = db.session.get(AnalysisJob, job_id)
            if job:
                job.status = "failed"
                job.error_message = "분석을 완료하지 못했습니다. 입력 자료를 확인한 뒤 다시 시도해 주세요."
                analysis = db.session.get(Analysis, job.analysis_id)
                if analysis:
                    analysis.status = "failed"
                db.session.commit()


def _dictionary_candidates(linguistic, spelling):
    values = []
    for finding in spelling:
        suggestion = finding.get("suggestion")
        if suggestion:
            values.extend(part for part in suggestion.split() if len(part) >= 2)
    for sentence in linguistic.get("sentences", []):
        roles = sentence.get("semanticRoles", {})
        predicate = roles.get("predicate", "")
        if predicate:
            values.append(predicate[:-1] if predicate.endswith("다") else predicate)
        values.extend(item.get("expression", "") for item in roles.get("concepts", []))
    return list(dict.fromkeys(value for value in values if value and len(value) <= 30))[:8]


def _verify_dictionary(client, candidates):
    if not candidates:
        candidates = ["분석"]
    verified = []
    status = "available"
    notice = None
    for word in candidates:
        result = client.lookup(word)
        status = result["status"]
        notice = result.get("notice")
        if status != "available":
            break
        verified.append({
            "word": word,
            "registered": bool(result.get("entries")),
            "entries": [
                {
                    "target_code": entry.get("target_code"),
                    "word": entry.get("word"),
                    "pos": entry.get("pos"),
                    "link": entry.get("link"),
                    "source": entry.get("source"),
                }
                for entry in result.get("entries", [])[:3]
            ],
        })
    return {
        "status": status,
        "verifiedWords": len([item for item in verified if item["registered"]]),
        "checkedWords": len(verified),
        "results": verified,
        "notice": notice or (None if status == "available" else "공식 사전 보조 검증을 생략했습니다."),
        "scoreAffected": False,
        "source": "국립국어원 표준국어대사전",
    }
