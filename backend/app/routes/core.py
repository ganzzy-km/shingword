from flask import Blueprint, current_app, request
from sqlalchemy import func, text

from ..extensions import db
from ..models import (
    Analysis, AnalysisJob, QuoteCard, Rubric, SourceDocument, Workspace,
    WorkspaceSetting, Writing,
)
from ..seed import DEFAULT_SETTINGS
from ..serializers import workspace_json
from ..utils import api_error, iso, json_body, success, validate_length


bp = Blueprint("core", __name__, url_prefix="/api")
ALLOWED_SETTINGS = {
    "theme": (str, None, None), "pageAnimation": (bool, None, None), "bookTexture": (bool, None, None),
    "autosaveInterval": (int, 10, 3600), "argumentLinkThreshold": (int, 1, 10),
    "quoteSimilarityThreshold": (float, 0.5, 1.0), "defaultAnalysisType": (str, None, None),
    "allowBulkSpellingFix": (bool, None, None), "lowOcrConfidenceThreshold": (int, 0, 100),
    "ocrLanguage": (str, None, None), "imageZoom": (int, 50, 300),
    "ocrPreprocessing": (bool, None, None), "fontSize": (str, None, None),
    "highContrast": (bool, None, None), "reduceMotion": (bool, None, None),
    "nonColorStatus": (bool, None, None), "lastBackupAt": ((str, type(None)), None, None),
}


@bp.get("/health")
def health():
    database = "ok"
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        database = "error"
    if current_app.extensions.get("storage_guard"):
        return success({"status": "blocked", "database": database, "version": current_app.config["APP_VERSION"], "blockedGate": "AUTHENTICATION_NOT_IMPLEMENTED"}, status=503)
    return success({"status": "ok" if database == "ok" else "degraded", "database": database, "version": current_app.config["APP_VERSION"]}, status=200 if database == "ok" else 503)


@bp.get("/dashboard")
def dashboard():
    latest = Analysis.query.order_by(Analysis.created_at.desc()).first()
    recent = Writing.query.order_by(Writing.updated_at.desc()).limit(5).all()
    return success({
        "summary": {
            "rubrics": Rubric.query.count(), "sources": SourceDocument.query.count(),
            "ocrPending": SourceDocument.query.filter(SourceDocument.status.in_(["OCR 확인 필요", "OCR 실행 환경 필요"])).count(),
            "drafts": Writing.query.filter_by(status="임시 저장").count(),
        },
        "latestAnalysis": {"id": latest.id, "writingId": latest.writing_id, "status": latest.status, "metrics": latest.metrics or {}, "createdAt": iso(latest.created_at)} if latest else None,
        "ocrPending": [{"id": x.id, "name": x.original_name, "pages": x.page_count, "date": iso(x.created_at)} for x in SourceDocument.query.filter(SourceDocument.status.in_(["OCR 확인 필요", "OCR 실행 환경 필요"])).limit(5)],
        "recentRecords": [{"id": x.id, "date": iso(x.updated_at), "title": x.title, "work": x.work, "status": x.status} for x in recent],
    })


@bp.get("/workspace")
def get_workspace():
    return success(workspace_json(db.session.get(Workspace, "local-workspace")))


@bp.patch("/workspace")
def update_workspace():
    data, error = json_body()
    if error:
        return error
    errors = validate_length(data, {"userName": 120, "workspaceName": 200})
    if errors:
        return api_error("VALIDATION_ERROR", "입력값을 확인해 주세요.", fields=errors)
    item = db.session.get(Workspace, "local-workspace")
    if "userName" in data:
        item.user_name = data["userName"].strip()
    if "workspaceName" in data:
        if not data["workspaceName"].strip():
            return api_error("VALIDATION_ERROR", "작업 공간 이름을 입력해 주세요.", fields={"workspaceName": "필수 항목입니다."})
        item.name = data["workspaceName"].strip()
    db.session.commit()
    return success(workspace_json(item), "저장되었습니다.")


@bp.get("/settings")
def get_settings():
    values = dict(DEFAULT_SETTINGS)
    for item in WorkspaceSetting.query.filter_by(workspace_id="local-workspace"):
        values[item.key] = item.value
    return success(values)


@bp.patch("/settings")
def update_settings():
    data, error = json_body()
    if error:
        return error
    fields = {}
    for key, value in data.items():
        if key == "theme" and value not in {"default", "bookshelf"}:
            fields[key] = "기본 테마 또는 책장 테마를 선택해 주세요."
            continue
        rule = ALLOWED_SETTINGS.get(key)
        if not rule:
            fields[key] = "허용되지 않은 설정입니다."
            continue
        expected, minimum, maximum = rule
        if not isinstance(value, expected) or (minimum is not None and not minimum <= value <= maximum):
            fields[key] = "허용된 형식 또는 범위를 벗어났습니다."
    if fields:
        return api_error("VALIDATION_ERROR", "설정값을 확인해 주세요.", fields=fields)
    for key, value in data.items():
        item = WorkspaceSetting.query.filter_by(workspace_id="local-workspace", key=key).first()
        if item:
            item.value = value
        else:
            db.session.add(WorkspaceSetting(workspace_id="local-workspace", key=key, value=value))
    db.session.commit()
    return get_settings()
