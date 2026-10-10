from __future__ import annotations

import hashlib
import io
import json
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, request, send_file

from ..extensions import db
from ..models import (
    ActivityRecord, Analysis, AnalysisFinding, AnalysisJob, AnalysisSentence,
    ArgumentLink, BackupRecord, DraftAutosave, FindingAction, LanguageRule,
    OcrRun, OfficialSource, PeelResult, QuoteCard, QuoteCheckResult,
    QuoteVerification, Revision, RevisionChange, Rubric, RubricResult,
    SourceDocument, SpellingResult, Workspace, WorkspaceSetting, Writing,
    WritingResource, WritingVersion,
)
from ..seed import ensure_defaults
from ..utils import api_error, iso, json_body, sha256_file, success


bp = Blueprint("data", __name__, url_prefix="/api")


def _database_path():
    return Path(current_app.config["DATABASE_PATH"]).resolve()


def _snapshot_database(target):
    source = sqlite3.connect(_database_path().as_uri() + "?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()


def _safe_zip_members(archive):
    total = 0
    for item in archive.infolist():
        path = Path(item.filename)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("백업 파일에 안전하지 않은 경로가 있습니다.")
        total += item.file_size
        if total > 1024 * 1024 * 1024:
            raise ValueError("백업 압축 해제 크기가 너무 큽니다.")


@bp.get("/rules")
def list_rules():
    rules = LanguageRule.query.order_by(LanguageRule.created_at.asc()).all()
    return success([{
        "id": item.id, "name": item.name, "pattern": item.pattern, "replacement": item.replacement,
        "status": item.status, "explanation": item.explanation, "clause": item.clause,
        "autoFixable": item.auto_fixable, "contextRequired": item.context_required,
        "source": {"name": source.name, "url": source.url, "checkedAt": source.checked_at.isoformat()} if (source := db.session.get(OfficialSource, item.source_id)) else None,
    } for item in rules])


@bp.get("/backups")
def list_backups():
    return success([{"id": x.id, "filename": x.filename, "size": x.size, "sha256": x.sha256, "includeUploads": x.include_uploads, "schemaVersion": x.schema_version, "createdAt": iso(x.created_at)} for x in BackupRecord.query.order_by(BackupRecord.created_at.desc()).all()])


@bp.post("/backups")
def create_backup():
    data = request.get_json(silent=True) or {}
    include_uploads = data.get("includeUploads", True) is not False
    backup_root = Path(current_app.config["BACKUP_FOLDER"])
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"geulbit-backup-{timestamp}-{uuid.uuid4().hex[:8]}.zip"
    target = backup_root / filename
    with tempfile.TemporaryDirectory(dir=current_app.config["TEMP_FOLDER"]) as temp:
        snapshot = Path(temp) / "geulbit.db"
        _snapshot_database(snapshot)
        manifest = {"appVersion": current_app.config["APP_VERSION"], "schemaVersion": "1", "createdAt": datetime.now(timezone.utc).isoformat(), "includeUploads": include_uploads, "databaseSha256": sha256_file(snapshot)}
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, "database/geulbit.db")
            if include_uploads:
                upload_root = Path(current_app.config["UPLOAD_FOLDER"])
                if upload_root.exists():
                    for path in upload_root.iterdir():
                        if path.is_file():
                            archive.write(path, f"uploads/{path.name}")
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    record = BackupRecord(filename=filename, size=target.stat().st_size, sha256=sha256_file(target), include_uploads=include_uploads, schema_version="1")
    db.session.add(record)
    setting = WorkspaceSetting.query.filter_by(workspace_id="local-workspace", key="lastBackupAt").first()
    if setting:
        setting.value = datetime.now(timezone.utc).isoformat()
    db.session.commit()
    return success({"id": record.id, "filename": filename, "size": record.size, "sha256": record.sha256, "downloadUrl": f"/api/backups/{record.id}/download"}, "백업 파일을 만들었습니다.", 201)


@bp.get("/backups/<backup_id>/download")
def download_backup(backup_id):
    record = db.session.get(BackupRecord, backup_id)
    if not record:
        return api_error("NOT_FOUND", "백업 파일을 찾을 수 없습니다.", 404)
    path = (Path(current_app.config["BACKUP_FOLDER"]) / record.filename).resolve()
    if path.parent != Path(current_app.config["BACKUP_FOLDER"]).resolve() or not path.is_file():
        return api_error("NOT_FOUND", "백업 파일을 찾을 수 없습니다.", 404)
    return send_file(path, as_attachment=True, download_name=record.filename, mimetype="application/zip")


@bp.post("/backups/restore")
def restore_backup():
    if request.form.get("confirmation") != "복원":
        return api_error("CONFIRMATION_REQUIRED", "복원을 실행하려면 확인 문자열 '복원'이 필요합니다.")
    upload = request.files.get("file")
    if not upload:
        return api_error("VALIDATION_ERROR", "복원할 ZIP 파일을 선택해 주세요.")
    with tempfile.TemporaryDirectory(dir=current_app.config["TEMP_FOLDER"]) as temp:
        uploaded = Path(temp) / "backup.zip"
        upload.save(uploaded)
        try:
            with zipfile.ZipFile(uploaded) as archive:
                _safe_zip_members(archive)
                manifest = json.loads(archive.read("manifest.json"))
                if manifest.get("schemaVersion") != "1":
                    raise ValueError("지원하지 않는 데이터베이스 스키마입니다.")
                db_bytes = archive.read("database/geulbit.db")
                if hashlib.sha256(db_bytes).hexdigest() != manifest.get("databaseSha256"):
                    raise ValueError("백업 데이터베이스 해시가 일치하지 않습니다.")
                restored = Path(temp) / "restored.db"
                restored.write_bytes(db_bytes)
                check = sqlite3.connect(restored)
                try:
                    if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise ValueError("백업 데이터베이스 무결성 검사에 실패했습니다.")
                finally:
                    check.close()
                safety = Path(current_app.config["BACKUP_FOLDER"]) / f"pre-restore-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.db"
                safety.parent.mkdir(parents=True, exist_ok=True)
                _snapshot_database(safety)
                db.session.remove()
                # SQLite backup protocol handles live WAL; copying a DB file
                # over an open connection can corrupt the target.
                db.engine.dispose()
                with sqlite3.connect(restored.as_uri() + "?mode=ro", uri=True) as source:
                    with sqlite3.connect(_database_path().as_uri() + "?mode=rw", uri=True) as destination:
                        source.backup(destination)
                        if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            raise ValueError("복원 데이터베이스 무결성 검사에 실패했습니다.")
                upload_root = Path(current_app.config["UPLOAD_FOLDER"])
                upload_root.mkdir(parents=True, exist_ok=True)
                for member in archive.infolist():
                    if member.filename.startswith("uploads/") and not member.is_dir():
                        name = Path(member.filename).name
                        (upload_root / name).write_bytes(archive.read(member))
        except (KeyError, json.JSONDecodeError, zipfile.BadZipFile, ValueError) as exc:
            return api_error("INVALID_BACKUP", str(exc))
    return success({"restartRequired": True}, "백업을 복원했습니다. 서버를 다시 시작해 주세요.")


@bp.get("/backups/export")
def export_data():
    data = {
        "workspace": {"id": (workspace := db.session.get(Workspace, "local-workspace")).id, "userName": workspace.user_name, "workspaceName": workspace.name},
        "rubrics": [{"id": x.id, "name": x.name, "subject": x.subject, "activity": x.activity, "status": x.status} for x in Rubric.query.all()],
        "sources": [{"id": x.id, "title": x.title, "author": x.author, "status": x.status, "originalName": x.original_name} for x in SourceDocument.query.all()],
        "quotes": [{"id": x.id, "quote": x.quote_text, "work": x.work, "author": x.author, "page": x.page} for x in QuoteCard.query.all()],
        "writings": [{"id": x.id, "title": x.title, "work": x.work, "content": x.content, "status": x.status} for x in Writing.query.all()],
    }
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    return send_file(io.BytesIO(payload), mimetype="application/json", as_attachment=True, download_name="geulbit-export.json")


@bp.delete("/records")
def delete_all_records():
    data, error = json_body()
    if error:
        return error
    if data.get("confirmation") != "분석 기록 전체 삭제":
        return api_error("CONFIRMATION_REQUIRED", "정확한 확인 문자열이 필요합니다.")
    Writing.query.delete()
    db.session.commit()
    return success(None, "분석 기록과 수정 버전을 삭제했습니다. 등록 자료는 유지됩니다.")


@bp.post("/workspace/reset")
def reset_workspace():
    data, error = json_body()
    if error:
        return error
    if data.get("confirmation") != "초기화":
        return api_error("CONFIRMATION_REQUIRED", "초기화를 실행하려면 확인 문자열 '초기화'가 필요합니다.")
    for model in [FindingAction, RevisionChange, Revision, SpellingResult, QuoteCheckResult, RubricResult, PeelResult, ArgumentLink, AnalysisFinding, AnalysisSentence, AnalysisJob, Analysis, DraftAutosave, WritingResource, WritingVersion, Writing, QuoteVerification, QuoteCard, OcrRun, SourceDocument, Rubric]:
        model.query.delete(synchronize_session=False)
    WorkspaceSetting.query.delete(synchronize_session=False)
    workspace = db.session.get(Workspace, "local-workspace")
    workspace.user_name = ""
    workspace.name = "글빛 작업 공간"
    db.session.commit()
    ensure_defaults()
    upload_root = Path(current_app.config["UPLOAD_FOLDER"])
    if upload_root.exists():
        for path in upload_root.iterdir():
            if path.is_file():
                path.unlink(missing_ok=True)
    return success({"workspace": {"id": workspace.id, "userName": workspace.user_name, "workspaceName": workspace.name}}, "작업 공간을 초기화했습니다.")
