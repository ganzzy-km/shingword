from pathlib import Path
import re
from threading import Lock

from flask import Blueprint, current_app, request, send_file
from sqlalchemy import or_

from ..extensions import db
from ..models import OcrRun, QuoteCard, QuoteVerification, Rubric, RubricFile, RubricItem, SourceDocument, SourcePage
from ..serializers import quote_json, rubric_json, source_json
from ..services.ocr_service import OcrFileError, diagnose_ocr, extract_pages
from ..utils import api_error, json_body, paginate, resolve_upload, save_upload, success, validate_length


bp = Blueprint("resources", __name__, url_prefix="/api")
_active_ocr_targets: set[tuple[str, str]] = set()
_active_ocr_lock = Lock()


def _rubric_items_from_text(text):
    """Turn user-confirmed OCR lines into conservative, editable rubric cards."""
    candidates = []
    seen = set()
    for raw_line in re.split(r"[\r\n]+", text or ""):
        line = re.sub(r"^\s*(?:[-*•◦▪·]|\(?\d{1,3}\)?[.)]|[가-힣][.)])\s*", "", raw_line)
        line = re.sub(r"\s+", " ", line).strip(" \t-|")
        if len(line) < 4 or line in seen:
            continue
        seen.add(line)
        candidates.append(line[:240])
        if len(candidates) >= 100:
            break
    return candidates


def _ocr_options():
    return {
        "configured_command": current_app.config.get("TESSERACT_CMD"),
        "maximum_pages": current_app.config["OCR_MAX_PAGES"],
        "maximum_pixels": current_app.config["OCR_MAX_IMAGE_PIXELS"],
        "dpi": current_app.config["OCR_DPI"],
        "timeout_seconds": current_app.config["OCR_PAGE_TIMEOUT_SECONDS"],
        "total_timeout_seconds": current_app.config["OCR_TOTAL_TIMEOUT_SECONDS"],
    }


def _display_status(status):
    return {
        "not_required": "등록 완료",
        "needs_ocr": "OCR 필요",
        "ready": "OCR 준비 완료",
        "processing": "OCR 처리 중",
        "completed": "OCR 확인 필요",
        "partial": "OCR 일부 완료",
        "unavailable": "OCR 실행 환경 필요",
        "failed": "처리 실패",
    }.get(status, "처리 실패")


def _failed_result(message):
    return {"status": "failed", "pages": [], "warning": message, "message": message}


def _extract_result(path, extension, language):
    try:
        return extract_pages(path, extension, language, **_ocr_options())
    except OcrFileError as exc:
        current_app.logger.warning("OCR file validation failed: %s", type(exc).__name__)
        return _failed_result(str(exc))
    except Exception:
        current_app.logger.exception("OCR processing failed")
        return _failed_result("문서에서 글자를 추출하지 못했습니다. 파일을 확인한 뒤 다시 시도해 주세요.")


def _finish_run(run, result):
    run.status = result["status"]
    run.error_message = result.get("warning") if result["status"] in {"partial", "unavailable", "failed"} else None


def _claim_ocr(target_type, target_id):
    key = (target_type, target_id)
    with _active_ocr_lock:
        if key in _active_ocr_targets:
            return None
        _active_ocr_targets.add(key)
    return key


def _release_ocr(key):
    with _active_ocr_lock:
        _active_ocr_targets.discard(key)


def _apply_ocr(target_type, target_id, path, extension):
    run = OcrRun(target_type=target_type, target_id=target_id, status="processing", language=current_app.config["OCR_LANGUAGE"])
    db.session.add(run)
    db.session.flush()
    result = _extract_result(path, extension, run.language)
    _finish_run(run, result)
    return run, result


@bp.get("/ocr/status")
def ocr_status():
    languages = tuple(current_app.config["OCR_LANGUAGE"].split("+"))
    return success(diagnose_ocr(current_app.config.get("TESSERACT_CMD"), languages))


@bp.get("/rubrics")
def list_rubrics():
    query = Rubric.query.filter_by(workspace_id="local-workspace")
    search = request.args.get("search", "").strip()
    if search:
        query = query.filter(or_(Rubric.name.contains(search), Rubric.subject.contains(search), Rubric.activity.contains(search)))
    if request.args.get("status"):
        query = query.filter_by(status=request.args["status"])
    return paginate(query.order_by(Rubric.created_at.desc()), rubric_json)


@bp.post("/rubrics")
def create_rubric():
    if request.content_type and request.content_type.startswith("multipart/form-data"):
        file = request.files.get("file")
        if not file:
            return api_error("VALIDATION_ERROR", "파일을 선택해 주세요.", fields={"file": "필수 항목입니다."})
        try:
            saved = save_upload(file)
        except ValueError as exc:
            return api_error("INVALID_FILE", str(exc))
        name = request.form.get("name", "").strip() or Path(saved["original_name"]).stem
        rubric = Rubric(workspace_id="local-workspace", name=name, subject=request.form.get("subject", "")[:120], activity=request.form.get("activity", "")[:120], status="업로드됨")
        db.session.add(rubric)
        db.session.flush()
        run, result = _apply_ocr("rubric", rubric.id, saved["path"], saved["path"].suffix)
        pages = result["pages"]
        text = "\n\n".join(x["text"] or "" for x in pages).strip() or None
        confidence_values = [x["confidence"] for x in pages if x["confidence"] is not None]
        rubric.status = _display_status(run.status)
        rubric.file = RubricFile(rubric_id=rubric.id, original_name=saved["original_name"], stored_name=saved["stored_name"], mime_type=saved["mime_type"], size=saved["size"], page_count=len(pages), ocr_text=text, corrected_text=text, ocr_confidence=sum(confidence_values) / len(confidence_values) if confidence_values else None)
    else:
        data, error = json_body()
        if error:
            return error
        errors = validate_length(data, {"name": 240, "subject": 120, "activity": 120, "description": 10000})
        if not data.get("name", "").strip():
            errors["name"] = "필수 항목입니다."
        if errors:
            return api_error("VALIDATION_ERROR", "입력값을 확인해 주세요.", fields=errors)
        rubric = Rubric(workspace_id="local-workspace", name=data["name"].strip(), subject=data.get("subject", "").strip(), activity=data.get("activity", "").strip(), description=data.get("description", "").strip(), status="등록 완료")
        db.session.add(rubric)
        db.session.flush()
        for index, item in enumerate(data.get("items", [])):
            if isinstance(item, dict) and str(item.get("name", "")).strip():
                db.session.add(RubricItem(rubric_id=rubric.id, name=str(item["name"])[:240], description=str(item.get("description", ""))[:10000], check_type=str(item.get("checkType", "사람의 판단 필요"))[:60], source_location=str(item.get("sourceLocation", ""))[:200], position=index))
    db.session.commit()
    return success(rubric_json(rubric), "평가 기준이 저장되었습니다.", 201)


@bp.get("/rubrics/<item_id>")
def get_rubric(item_id):
    item = db.session.get(Rubric, item_id)
    return success(rubric_json(item)) if item else api_error("NOT_FOUND", "평가 기준을 찾을 수 없습니다.", 404)


@bp.post("/rubrics/<item_id>/ocr")
def run_rubric_ocr(item_id):
    item = db.session.get(Rubric, item_id)
    if not item or not item.file:
        return api_error("NOT_FOUND", "OCR을 실행할 평가 기준 파일을 찾을 수 없습니다.", 404)
    key = _claim_ocr("rubric", item_id)
    if not key:
        return api_error("OCR_ALREADY_RUNNING", "이 자료의 OCR을 이미 처리하고 있습니다.", 409)
    try:
        path = resolve_upload(item.file.stored_name)
        if not path:
            return api_error("FILE_NOT_FOUND", "업로드한 원본 파일을 찾을 수 없습니다.", 404)
        run = OcrRun(target_type="rubric", target_id=item_id, status="processing", language=current_app.config["OCR_LANGUAGE"])
        db.session.add(run)
        item.status = _display_status("processing")
        db.session.commit()
        result = _extract_result(path, path.suffix, run.language)
        _finish_run(run, result)
        pages = result["pages"]
        text = "\n\n".join(page["text"] or "" for page in pages).strip() or None
        confidence_values = [page["confidence"] for page in pages if page["confidence"] is not None]
        if text is not None:
            item.file.ocr_text = text
            item.file.corrected_text = text
        item.file.page_count = len(pages) or item.file.page_count
        item.file.ocr_confidence = sum(confidence_values) / len(confidence_values) if confidence_values else None
        item.status = _display_status(run.status)
        db.session.commit()
        data = rubric_json(item)
        data["ocrPages"] = pages
        return success(data, result["message"])
    finally:
        _release_ocr(key)


@bp.patch("/rubrics/<item_id>")
def update_rubric(item_id):
    item = db.session.get(Rubric, item_id)
    if not item:
        return api_error("NOT_FOUND", "평가 기준을 찾을 수 없습니다.", 404)
    data, error = json_body()
    if error:
        return error
    for api, attr, limit in [("name", "name", 240), ("subject", "subject", 120), ("activity", "activity", 120), ("description", "description", 10000), ("status", "status", 40)]:
        if api in data and isinstance(data[api], str):
            setattr(item, attr, data[api].strip()[:limit])
    if item.file and "correctedText" in data and isinstance(data["correctedText"], str):
        item.file.corrected_text = data["correctedText"]
        confirmed = data.get("confirm", False)
        item.status = "등록 완료" if confirmed else "OCR 확인 필요"
        if confirmed and not item.items:
            for index, name in enumerate(_rubric_items_from_text(data["correctedText"])):
                item.items.append(RubricItem(
                    name=name,
                    description="OCR 결과를 사용자가 확인해 만든 평가 기준입니다.",
                    check_type="사람의 판단 필요",
                    source_location=f"확인된 OCR {index + 1}행",
                    position=index,
                ))
    if "items" in data and isinstance(data["items"], list):
        item.items.clear()
        for index, value in enumerate(data["items"]):
            if isinstance(value, dict) and str(value.get("name", "")).strip():
                item.items.append(RubricItem(name=str(value["name"])[:240], description=str(value.get("description", ""))[:10000], check_type=str(value.get("checkType", "사람의 판단 필요"))[:60], source_location=str(value.get("sourceLocation", ""))[:200], position=index))
    db.session.commit()
    return success(rubric_json(item), "평가 기준이 수정되었습니다.")


@bp.post("/rubrics/<item_id>/duplicate")
def duplicate_rubric(item_id):
    source = db.session.get(Rubric, item_id)
    if not source:
        return api_error("NOT_FOUND", "평가 기준을 찾을 수 없습니다.", 404)
    clone = Rubric(workspace_id="local-workspace", name=f"{source.name} 복사본", subject=source.subject, activity=source.activity, status="등록 완료", description=source.description)
    clone.items = [RubricItem(name=x.name, description=x.description, check_type=x.check_type, source_location=x.source_location, position=x.position) for x in source.items]
    db.session.add(clone)
    db.session.commit()
    return success(rubric_json(clone), "복제되었습니다.", 201)


@bp.delete("/rubrics/<item_id>")
def delete_rubric(item_id):
    item = db.session.get(Rubric, item_id)
    if not item:
        return api_error("NOT_FOUND", "평가 기준을 찾을 수 없습니다.", 404)
    stored = item.file.stored_name if item.file else None
    OcrRun.query.filter_by(target_type="rubric", target_id=item.id).delete(synchronize_session=False)
    db.session.delete(item)
    db.session.commit()
    path = resolve_upload(stored) if stored else None
    if path:
        path.unlink(missing_ok=True)
    return success(None, "삭제되었습니다.")


@bp.get("/source-documents")
def list_sources():
    query = SourceDocument.query.filter_by(workspace_id="local-workspace")
    search = request.args.get("search", "").strip()
    if search:
        query = query.filter(or_(SourceDocument.title.contains(search), SourceDocument.author.contains(search), SourceDocument.original_name.contains(search)))
    if request.args.get("status"):
        query = query.filter_by(status=request.args["status"])
    return paginate(query.order_by(SourceDocument.created_at.desc()), source_json)


@bp.post("/source-documents")
def create_source():
    file = request.files.get("file")
    if not file:
        return api_error("VALIDATION_ERROR", "파일을 선택해 주세요.", fields={"file": "필수 항목입니다."})
    try:
        saved = save_upload(file)
    except ValueError as exc:
        return api_error("INVALID_FILE", str(exc))
    title = request.form.get("title", "").strip() or Path(saved["original_name"]).stem
    item = SourceDocument(workspace_id="local-workspace", title=title[:240], author=request.form.get("author", "")[:160], edition=request.form.get("edition", "")[:200], original_name=saved["original_name"], stored_name=saved["stored_name"], mime_type=saved["mime_type"], size=saved["size"], status="업로드됨")
    db.session.add(item)
    db.session.flush()
    run, result = _apply_ocr("source-document", item.id, saved["path"], saved["path"].suffix)
    pages = result["pages"]
    for page in pages:
        item.pages.append(SourcePage(page_number=page["page"], original_text=page["text"], corrected_text=page["text"], confidence=page["confidence"], extraction_method=page["method"]))
    item.page_count = len(pages)
    item.status = _display_status(run.status)
    db.session.commit()
    return success(source_json(item, True), "작품 자료가 업로드되었습니다.", 201)


@bp.get("/source-documents/<item_id>")
def get_source(item_id):
    item = db.session.get(SourceDocument, item_id)
    return success(source_json(item, True)) if item else api_error("NOT_FOUND", "작품 자료를 찾을 수 없습니다.", 404)


@bp.post("/source-documents/<item_id>/ocr")
def run_source_ocr(item_id):
    item = db.session.get(SourceDocument, item_id)
    if not item:
        return api_error("NOT_FOUND", "OCR을 실행할 작품 자료를 찾을 수 없습니다.", 404)
    key = _claim_ocr("source-document", item_id)
    if not key:
        return api_error("OCR_ALREADY_RUNNING", "이 자료의 OCR을 이미 처리하고 있습니다.", 409)
    try:
        path = resolve_upload(item.stored_name)
        if not path:
            return api_error("FILE_NOT_FOUND", "업로드한 원본 파일을 찾을 수 없습니다.", 404)
        run = OcrRun(target_type="source-document", target_id=item_id, status="processing", language=current_app.config["OCR_LANGUAGE"])
        db.session.add(run)
        item.status = _display_status("processing")
        db.session.commit()
        result = _extract_result(path, path.suffix, run.language)
        _finish_run(run, result)
        existing = {page.page_number: page for page in item.pages}
        for extracted in result["pages"]:
            page = existing.get(extracted["page"])
            if page is None:
                page = SourcePage(document_id=item.id, page_number=extracted["page"])
                db.session.add(page)
            user_edited = page.original_text is not None and page.corrected_text not in {None, page.original_text}
            page.original_text = extracted["text"]
            if not user_edited:
                page.corrected_text = extracted["text"]
            page.confidence = extracted["confidence"]
            page.extraction_method = extracted["method"]
        item.page_count = len(result["pages"]) or item.page_count
        item.status = _display_status(run.status)
        db.session.commit()
        return success(source_json(item, True), result["message"])
    finally:
        _release_ocr(key)


@bp.patch("/source-documents/<item_id>")
def update_source(item_id):
    item = db.session.get(SourceDocument, item_id)
    if not item:
        return api_error("NOT_FOUND", "작품 자료를 찾을 수 없습니다.", 404)
    data, error = json_body()
    if error:
        return error
    for api, attr, limit in [("title", "title", 240), ("author", "author", 160), ("edition", "edition", 200), ("status", "status", 40)]:
        if api in data and isinstance(data[api], str):
            setattr(item, attr, data[api].strip()[:limit])
    db.session.commit()
    return success(source_json(item, True), "작품 자료가 수정되었습니다.")


@bp.patch("/source-documents/<item_id>/pages/<int:page_number>")
def update_page(item_id, page_number):
    page = SourcePage.query.filter_by(document_id=item_id, page_number=page_number).first()
    if not page:
        return api_error("NOT_FOUND", "페이지를 찾을 수 없습니다.", 404)
    data, error = json_body()
    if error:
        return error
    if not isinstance(data.get("correctedText"), str):
        return api_error("VALIDATION_ERROR", "수정한 OCR 텍스트를 입력해 주세요.")
    page.corrected_text = data["correctedText"]
    page.document.status = "등록 완료" if data.get("confirm", False) else "OCR 확인 필요"
    db.session.commit()
    return success(source_json(page.document, True), "OCR 결과가 저장되었습니다.")


@bp.delete("/source-documents/<item_id>")
def delete_source(item_id):
    item = db.session.get(SourceDocument, item_id)
    if not item:
        return api_error("NOT_FOUND", "작품 자료를 찾을 수 없습니다.", 404)
    if item.quote_cards:
        return api_error("RESOURCE_IN_USE", "연결된 인용문 카드가 있어 삭제할 수 없습니다.", 409)
    stored = item.stored_name
    OcrRun.query.filter_by(target_type="source-document", target_id=item.id).delete(synchronize_session=False)
    db.session.delete(item)
    db.session.commit()
    path = resolve_upload(stored)
    if path:
        path.unlink(missing_ok=True)
    return success(None, "삭제되었습니다.")


@bp.get("/files/<kind>/<item_id>")
def download_file(kind, item_id):
    if kind == "rubrics":
        item = db.session.get(RubricFile, item_id)
    elif kind == "sources":
        item = db.session.get(SourceDocument, item_id)
    else:
        item = None
    if not item:
        return api_error("NOT_FOUND", "파일을 찾을 수 없습니다.", 404)
    path = resolve_upload(item.stored_name)
    if not path:
        return api_error("NOT_FOUND", "파일을 찾을 수 없습니다.", 404)
    return send_file(path, mimetype=item.mime_type, as_attachment=request.args.get("download") == "1", download_name=item.original_name)


@bp.get("/quote-cards")
def list_quotes():
    query = QuoteCard.query.filter_by(workspace_id="local-workspace")
    search = request.args.get("search", "").strip()
    if search:
        query = query.filter(or_(QuoteCard.quote_text.contains(search), QuoteCard.work.contains(search), QuoteCard.author.contains(search)))
    if request.args.get("documentId"):
        query = query.filter_by(document_id=request.args["documentId"])
    return paginate(query.order_by(QuoteCard.created_at.desc()), quote_json)


@bp.post("/quote-cards")
def create_quote():
    data, error = json_body()
    if error:
        return error
    selected = str(data.get("selectedText", "")).strip()
    quote = str(data.get("quote", selected)).strip()
    if not selected or not quote:
        return api_error("VALIDATION_ERROR", "선택한 원문과 인용문을 입력해 주세요.")
    status = "확인 완료" if selected == quote else "원문과 다름"
    item = QuoteCard(workspace_id="local-workspace", document_id=data.get("documentId"), selected_text=selected, quote_text=quote, work=str(data.get("work", ""))[:240], author=str(data.get("author", ""))[:160], page=str(data.get("page", ""))[:60], scene=str(data.get("scene", ""))[:5000], characters=data.get("characters", []) if isinstance(data.get("characters", []), list) else [], keywords=data.get("keywords", []) if isinstance(data.get("keywords", []), list) else [], inquiry_question=str(data.get("inquiryQuestion", ""))[:5000], verification_status=status)
    db.session.add(item)
    db.session.flush()
    db.session.add(QuoteVerification(quote_card_id=item.id, status=status, difference={"selectedText": selected, "quote": quote} if status == "원문과 다름" else None, reason="선택한 원문과 입력한 인용문을 비교했습니다."))
    db.session.commit()
    return success(quote_json(item), "인용문 카드가 저장되었습니다.", 201)


@bp.patch("/quote-cards/<item_id>")
def update_quote(item_id):
    item = db.session.get(QuoteCard, item_id)
    if not item:
        return api_error("NOT_FOUND", "인용문 카드를 찾을 수 없습니다.", 404)
    data, error = json_body()
    if error:
        return error
    mapping = {"selectedText": "selected_text", "quote": "quote_text", "work": "work", "author": "author", "page": "page", "scene": "scene", "inquiryQuestion": "inquiry_question"}
    for key, attr in mapping.items():
        if key in data and isinstance(data[key], str):
            setattr(item, attr, data[key])
    for key in ["characters", "keywords"]:
        if key in data and isinstance(data[key], list):
            setattr(item, key, data[key])
    item.verification_status = "확인 완료" if item.selected_text == item.quote_text else "원문과 다름"
    db.session.commit()
    return success(quote_json(item), "인용문 카드가 수정되었습니다.")


@bp.post("/quote-cards/<item_id>/duplicate")
def duplicate_quote(item_id):
    item = db.session.get(QuoteCard, item_id)
    if not item:
        return api_error("NOT_FOUND", "인용문 카드를 찾을 수 없습니다.", 404)
    clone = QuoteCard(workspace_id="local-workspace", document_id=item.document_id, selected_text=item.selected_text, quote_text=item.quote_text, work=item.work, author=item.author, page=item.page, scene=item.scene, characters=item.characters, keywords=item.keywords, inquiry_question=item.inquiry_question, verification_status=item.verification_status)
    db.session.add(clone)
    db.session.commit()
    return success(quote_json(clone), "복제되었습니다.", 201)


@bp.delete("/quote-cards/<item_id>")
def delete_quote(item_id):
    item = db.session.get(QuoteCard, item_id)
    if not item:
        return api_error("NOT_FOUND", "인용문 카드를 찾을 수 없습니다.", 404)
    db.session.delete(item)
    db.session.commit()
    return success(None, "삭제되었습니다.")
