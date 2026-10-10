from datetime import date
import difflib

from flask import Blueprint, request
from sqlalchemy import or_

from ..extensions import db
from ..models import DraftAutosave, Writing, WritingResource, WritingVersion
from ..serializers import writing_json
from ..utils import api_error, iso, json_body, paginate, success, validate_length


bp = Blueprint("writings", __name__, url_prefix="/api")


def _parse_due_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("날짜 형식은 YYYY-MM-DD여야 합니다.")


def _apply_writing_data(item, data, require_question=False):
    errors = validate_length(data, {"title": 240, "work": 240, "author": 160, "inquiryQuestion": 5000, "subject": 120, "conditions": 10000})
    if require_question and not str(data.get("inquiryQuestion", item.inquiry_question or "")).strip():
        errors["inquiryQuestion"] = "탐구 질문을 입력해 주세요."
    if errors:
        return errors
    mapping = {"title": "title", "work": "work", "author": "author", "inquiryQuestion": "inquiry_question", "subject": "subject", "conditions": "conditions", "content": "content", "status": "status"}
    for key, attr in mapping.items():
        if key in data and isinstance(data[key], str):
            setattr(item, attr, data[key])
    if "dueDate" in data:
        item.due_date = _parse_due_date(data["dueDate"])
    return None


def _sync_resources(item, resources):
    if not isinstance(resources, list):
        return
    item.resources.clear()
    for value in resources:
        if isinstance(value, dict) and value.get("type") in {"rubric", "source", "quote"} and isinstance(value.get("id"), str):
            item.resources.append(WritingResource(resource_type=value["type"], resource_id=value["id"]))


@bp.get("/writings")
@bp.get("/records")
def list_writings():
    query = Writing.query.filter_by(workspace_id="local-workspace")
    search = request.args.get("search", "").strip()
    if search:
        query = query.filter(or_(Writing.title.contains(search), Writing.work.contains(search)))
    if request.args.get("status"):
        query = query.filter_by(status=request.args["status"])
    sort = request.args.get("sort", "updated-desc")
    query = query.order_by(Writing.updated_at.asc() if sort == "updated-asc" else Writing.updated_at.desc())
    return paginate(query, lambda x: writing_json(x, False))


@bp.post("/writings")
def create_writing():
    data, error = json_body()
    if error:
        return error
    item = Writing(workspace_id="local-workspace")
    try:
        errors = _apply_writing_data(item, data, require_question=data.get("status") not in {None, "임시 저장"})
    except ValueError as exc:
        return api_error("VALIDATION_ERROR", str(exc))
    if errors:
        return api_error("VALIDATION_ERROR", "입력값을 확인해 주세요.", fields=errors)
    item.status = data.get("status", "임시 저장")
    db.session.add(item)
    db.session.flush()
    version = WritingVersion(writing_id=item.id, name="원문", content=item.content or "", version_number=1)
    db.session.add(version)
    db.session.flush()
    item.original_version_id = version.id
    _sync_resources(item, data.get("resources", []))
    db.session.commit()
    return success(writing_json(item), "글이 저장되었습니다.", 201)


@bp.get("/writings/<item_id>")
def get_writing(item_id):
    item = db.session.get(Writing, item_id)
    return success(writing_json(item)) if item else api_error("NOT_FOUND", "글을 찾을 수 없습니다.", 404)


@bp.patch("/writings/<item_id>")
def update_writing(item_id):
    item = db.session.get(Writing, item_id)
    if not item:
        return api_error("NOT_FOUND", "글을 찾을 수 없습니다.", 404)
    data, error = json_body()
    if error:
        return error
    try:
        errors = _apply_writing_data(item, data, require_question=data.get("status") not in {None, "임시 저장"})
    except ValueError as exc:
        return api_error("VALIDATION_ERROR", str(exc))
    if errors:
        return api_error("VALIDATION_ERROR", "입력값을 확인해 주세요.", fields=errors)
    _sync_resources(item, data.get("resources"))
    db.session.commit()
    return success(writing_json(item), "글이 수정되었습니다.")


@bp.post("/writings/<item_id>/autosave")
def autosave(item_id):
    item = db.session.get(Writing, item_id)
    if not item:
        return api_error("NOT_FOUND", "글을 찾을 수 없습니다.", 404)
    data, error = json_body()
    if error:
        return error
    revision = data.get("revisionNumber")
    if not isinstance(revision, int):
        return api_error("VALIDATION_ERROR", "revisionNumber가 필요합니다.")
    if revision != item.revision_number:
        return api_error("SAVE_CONFLICT", "다른 저장 내용이 먼저 반영되었습니다. 최신 내용을 다시 불러와 주세요.", 409, {"revisionNumber": item.revision_number})
    if not isinstance(data.get("content", ""), str):
        return api_error("VALIDATION_ERROR", "본문은 문자열이어야 합니다.")
    item.content = data.get("content", "")
    item.revision_number += 1
    item.status = "임시 저장" if item.status == "임시 저장" else item.status
    db.session.add(DraftAutosave(writing_id=item.id, revision_number=item.revision_number, content=item.content))
    db.session.commit()
    return success(writing_json(item), "자동 저장되었습니다.")


@bp.post("/writings/<item_id>/versions")
def create_version(item_id):
    item = db.session.get(Writing, item_id)
    if not item:
        return api_error("NOT_FOUND", "글을 찾을 수 없습니다.", 404)
    data, error = json_body()
    if error:
        return error
    parent = item.versions[-1] if item.versions else None
    content = data.get("content", item.content)
    if not isinstance(content, str):
        return api_error("VALIDATION_ERROR", "본문은 문자열이어야 합니다.")
    version = WritingVersion(writing_id=item.id, parent_id=parent.id if parent else None, name=str(data.get("name", f"버전 {len(item.versions) + 1}"))[:200], content=content, version_number=len(item.versions) + 1, change_count=sum(1 for x in difflib.ndiff((parent.content if parent else "").splitlines(), content.splitlines()) if x.startswith(("+ ", "- "))))
    db.session.add(version)
    item.content = content
    item.revision_number += 1
    db.session.commit()
    return success({"id": version.id, "name": version.name, "versionNumber": version.version_number, "changeCount": version.change_count, "createdAt": iso(version.created_at)}, "새 버전이 저장되었습니다.", 201)


@bp.get("/writings/<item_id>/versions")
def list_versions(item_id):
    item = db.session.get(Writing, item_id)
    if not item:
        return api_error("NOT_FOUND", "글을 찾을 수 없습니다.", 404)
    return success([{"id": x.id, "name": x.name, "versionNumber": x.version_number, "changeCount": x.change_count, "parentId": x.parent_id, "isOriginal": x.id == item.original_version_id, "createdAt": iso(x.created_at)} for x in sorted(item.versions, key=lambda v: v.version_number)])


@bp.get("/writing-versions/<left_id>/compare/<right_id>")
def compare_versions(left_id, right_id):
    left = db.session.get(WritingVersion, left_id)
    right = db.session.get(WritingVersion, right_id)
    if not left or not right or left.writing_id != right.writing_id:
        return api_error("NOT_FOUND", "비교할 버전을 찾을 수 없습니다.", 404)
    operations = []
    matcher = difflib.SequenceMatcher(None, left.content, right.content)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        operations.append({"type": tag, "left": left.content[i1:i2], "right": right.content[j1:j2], "leftRange": [i1, i2], "rightRange": [j1, j2]})
    return success({"left": {"id": left.id, "name": left.name, "content": left.content}, "right": {"id": right.id, "name": right.name, "content": right.content}, "operations": operations})


@bp.patch("/records/<item_id>")
def rename_record(item_id):
    return update_writing(item_id)


@bp.post("/records/<item_id>/duplicate")
def duplicate_record(item_id):
    source = db.session.get(Writing, item_id)
    if not source:
        return api_error("NOT_FOUND", "기록을 찾을 수 없습니다.", 404)
    clone = Writing(workspace_id="local-workspace", title=f"{source.title} 복사본", work=source.work, author=source.author, inquiry_question=source.inquiry_question, subject=source.subject, conditions=source.conditions, due_date=source.due_date, content=source.content, status="임시 저장")
    db.session.add(clone)
    db.session.flush()
    version = WritingVersion(writing_id=clone.id, name="원문", content=clone.content, version_number=1)
    db.session.add(version)
    db.session.flush()
    clone.original_version_id = version.id
    db.session.commit()
    return success(writing_json(clone), "복제되었습니다.", 201)


@bp.delete("/records/<item_id>")
@bp.delete("/writings/<item_id>")
def delete_record(item_id):
    item = db.session.get(Writing, item_id)
    if not item:
        return api_error("NOT_FOUND", "기록을 찾을 수 없습니다.", 404)
    confirmation = request.get_json(silent=True) or {}
    if confirmation.get("confirmation") not in {item.title, "삭제"}:
        return api_error("CONFIRMATION_REQUIRED", "기록 제목 또는 '삭제'를 정확히 입력해 주세요.", 400)
    # ORM 관계 삭제는 Revision이 참조하는 WritingVersion을 먼저 지울 수 있다.
    # 한 문장의 DB 삭제로 맡기면 SQLite가 writing 하위 CASCADE를 함께 처리한다.
    Writing.query.filter_by(id=item.id).delete(synchronize_session=False)
    db.session.commit()
    return success(None, "분석 기록이 삭제되었습니다.")
