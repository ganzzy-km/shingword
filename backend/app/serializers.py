from .extensions import db
from .utils import iso


def _analysis_metrics_json(item, peels):
    data = {name: dict(metric) for name, metric in (item.metrics or {}).items()}
    statuses = [status for peel in peels for status in (peel.elements or {}).values()]
    if statuses:
        metric = data.setdefault("PEEL 충족률", {})
        metric.update({
            "value": round(sum(status == "충족" for status in statuses) * 100 / len(statuses)),
            "calculable": True,
            "numerator": sum(status == "충족" for status in statuses),
            "denominator": len(statuses),
            "description": "분석 대상 문단에서 확인된 P·E·E·L 요소의 비율",
            "relatedType": "peel",
        })
    return data


def workspace_json(item):
    return {"id": item.id, "userName": item.user_name, "workspaceName": item.name, "updatedAt": iso(item.updated_at)}


def _ocr_json(target_type, target_id):
    from .models import OcrRun

    run = OcrRun.query.filter_by(target_type=target_type, target_id=target_id).order_by(OcrRun.created_at.desc()).first()
    if not run:
        return None
    status = {"needs_environment": "unavailable", "running": "processing"}.get(run.status, run.status)
    labels = {
        "not_required": "OCR 불필요",
        "needs_ocr": "OCR 필요",
        "ready": "OCR 준비 완료",
        "processing": "OCR 처리 중",
        "completed": "OCR 완료",
        "partial": "일부 페이지만 완료",
        "unavailable": "OCR 실행 환경 필요",
        "failed": "OCR 실패",
    }
    messages = {
        "not_required": "문서의 원문 텍스트를 추출했습니다. OCR이 필요하지 않습니다.",
        "processing": "문서에서 글자를 추출하고 있습니다.",
        "completed": "OCR이 완료되었습니다. 추출 결과를 확인해 주세요.",
        "partial": "이 파일의 일부 페이지만 처리되었습니다. 결과를 확인해 주세요.",
        "unavailable": "서버에 한글 OCR 환경이 설치되어 있지 않습니다. 다른 기능은 계속 사용할 수 있습니다.",
        "failed": "문서에서 글자를 추출하지 못했습니다. 파일을 확인한 뒤 다시 시도해 주세요.",
    }
    return {
        "status": status,
        "label": labels.get(status, "OCR 상태 확인 필요"),
        "message": run.error_message or messages.get(status, "OCR 상태를 확인해 주세요."),
        "language": run.language,
        "updatedAt": iso(run.updated_at),
    }


def rubric_json(item):
    file = item.file
    return {
        "id": item.id,
        "fileId": file.id if file else None,
        "name": item.name,
        "subject": item.subject,
        "activity": item.activity,
        "status": item.status,
        "description": item.description,
        "pages": file.page_count if file else 0,
        "cards": len(item.items),
        "date": iso(item.created_at),
        "originalName": file.original_name if file else None,
        "mimeType": file.mime_type if file else None,
        "size": file.size if file else 0,
        "ocrText": file.ocr_text if file else None,
        "correctedText": file.corrected_text if file else None,
        "ocrConfidence": file.ocr_confidence if file else None,
        "ocr": _ocr_json("rubric", item.id),
        "items": [{"id": x.id, "name": x.name, "description": x.description, "checkType": x.check_type, "sourceLocation": x.source_location, "position": x.position} for x in item.items],
    }


def source_json(item, include_pages=False):
    data = {
        "id": item.id, "title": item.title, "author": item.author, "edition": item.edition,
        "originalName": item.original_name, "mimeType": item.mime_type, "size": item.size,
        "status": item.status, "pages": item.page_count, "cards": len(item.quote_cards),
        "date": iso(item.created_at), "ocr": _ocr_json("source-document", item.id),
    }
    if include_pages:
        data["pageData"] = [{"id": p.id, "pageNumber": p.page_number, "originalText": p.original_text, "correctedText": p.corrected_text, "confidence": p.confidence, "extractionMethod": p.extraction_method, "status": "not_required" if p.extraction_method == "native_text" else "completed" if p.extraction_method == "ocr" else p.extraction_method} for p in sorted(item.pages, key=lambda x: x.page_number)]
    return data


def quote_json(item):
    return {
        "id": item.id, "documentId": item.document_id, "selectedText": item.selected_text,
        "quote": item.quote_text, "work": item.work, "author": item.author, "page": item.page,
        "scene": item.scene, "characters": item.characters or [], "keywords": item.keywords or [],
        "inquiryQuestion": item.inquiry_question, "verificationStatus": item.verification_status,
        "createdAt": iso(item.created_at),
    }


def writing_json(item, include_content=True):
    from .models import Analysis, PeelResult
    analyses = Analysis.query.filter_by(writing_id=item.id).order_by(Analysis.created_at.desc()).all()
    peels_by_analysis = {analysis.id: [] for analysis in analyses}
    if analyses:
        for peel in PeelResult.query.filter(PeelResult.analysis_id.in_([analysis.id for analysis in analyses])).all():
            peels_by_analysis[peel.analysis_id].append(peel)
    latest_analysis = analyses[0] if analyses else None
    data = {
        "id": item.id, "title": item.title, "work": item.work, "author": item.author,
        "inquiryQuestion": item.inquiry_question, "subject": item.subject, "conditions": item.conditions,
        "dueDate": item.due_date.isoformat() if item.due_date else None, "status": item.status,
        "revisionNumber": item.revision_number, "createdAt": iso(item.created_at), "updatedAt": iso(item.updated_at),
        "characterCount": len(item.content or ""),
        "paragraphCount": len([p for p in (item.content or "").split("\n\n") if p.strip()]),
        "latestAnalysisId": latest_analysis.id if latest_analysis else None,
        "analysisRuns": [{
            "id": analysis.id,
            "status": analysis.status,
            "metrics": _analysis_metrics_json(analysis, peels_by_analysis[analysis.id]),
            "createdAt": iso(analysis.created_at),
        } for analysis in analyses],
    }
    if include_content:
        data["content"] = item.content or ""
        data["resources"] = [{"type": r.resource_type, "id": r.resource_id} for r in item.resources]
    return data


def finding_json(item):
    return {
        "id": item.id, "type": item.finding_type, "severity": item.severity, "title": item.title,
        "current": item.current_text, "suggestion": item.suggestion, "reason": item.reason,
        "rule": item.rule, "sourceUrl": item.source_url, "confidence": item.confidence,
        "startOffset": item.start_offset, "endOffset": item.end_offset, "status": item.status,
        "metadata": item.metadata_json or {},
    }


def analysis_json(item):
    from .models import ArgumentLink, PeelResult, Writing

    writing = db.session.get(Writing, item.writing_id)
    sentences = sorted(item.sentences, key=lambda x: x.sentence_number)
    sentence_by_id = {sentence.id: sentence for sentence in sentences}
    links = ArgumentLink.query.filter_by(analysis_id=item.id).order_by(ArgumentLink.id.asc()).all()
    peels = PeelResult.query.filter_by(analysis_id=item.id).order_by(PeelResult.paragraph_number.asc()).all()
    return {
        "id": item.id, "writingId": item.writing_id, "status": item.status,
        "writing": {"title": writing.title, "work": writing.work, "inquiryQuestion": writing.inquiry_question} if writing else None,
        "analysisTypes": item.analysis_types or [], "metrics": _analysis_metrics_json(item, peels), "disclaimer": item.disclaimer,
        "details": item.settings or {},
        "createdAt": iso(item.created_at),
        "sentences": [{"id": s.id, "paragraphNumber": s.paragraph_number, "sentenceNumber": s.sentence_number, "text": s.text, "startOffset": s.start_offset, "endOffset": s.end_offset, "autoRole": s.auto_role, "userRole": s.user_role, "confidence": s.confidence, "rationale": s.rationale} for s in sentences],
        "argumentLinks": [{
            "id": link.id,
            "claimSentenceId": link.claim_sentence_id,
            "evidenceSentenceId": link.evidence_sentence_id,
            "claimText": sentence_by_id[link.claim_sentence_id].text if link.claim_sentence_id in sentence_by_id else "",
            "evidenceText": sentence_by_id[link.evidence_sentence_id].text if link.evidence_sentence_id in sentence_by_id else "",
            "score": link.score,
            "status": link.status,
            "details": link.details or {},
        } for link in links],
        "peelResults": [{
            "id": peel.id,
            "paragraphNumber": peel.paragraph_number,
            "elements": peel.elements or {},
            "rationale": peel.rationale,
            "guidance": peel.guidance,
        } for peel in peels],
        "findings": [finding_json(f) for f in item.findings],
    }
