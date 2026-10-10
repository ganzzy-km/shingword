import difflib

from flask import Blueprint, current_app, request

from ..extensions import db
from ..models import Analysis, AnalysisFinding, AnalysisJob, FindingAction, Revision, RevisionChange, Writing, WritingVersion
from ..serializers import analysis_json, finding_json
from ..services.analysis_service import submit_analysis
from ..utils import api_error, iso, json_body, success


bp = Blueprint("analyses", __name__, url_prefix="/api")


@bp.post("/analyses")
def create_analysis():
    data, error = json_body()
    if error:
        return error
    writing = db.session.get(Writing, data.get("writingId"))
    if not writing:
        return api_error("NOT_FOUND", "분석할 글을 찾을 수 없습니다.", 404)
    if not writing.inquiry_question.strip():
        return api_error("VALIDATION_ERROR", "탐구 질문을 입력해 주세요.", fields={"inquiryQuestion": "필수 항목입니다."})
    if not writing.content.strip():
        return api_error("VALIDATION_ERROR", "분석할 본문을 입력해 주세요.", fields={"content": "필수 항목입니다."})
    previous_analyses = Analysis.query.filter_by(writing_id=writing.id).count()
    latest_version = WritingVersion.query.filter_by(writing_id=writing.id).order_by(WritingVersion.version_number.desc()).first()
    if not latest_version or latest_version.content != writing.content:
        latest_version = WritingVersion(
            writing_id=writing.id,
            parent_id=latest_version.id if latest_version else None,
            name="분석 원문" if previous_analyses == 0 else "재분석 원문",
            content=writing.content,
            version_number=(latest_version.version_number + 1) if latest_version else 1,
        )
        db.session.add(latest_version)
        db.session.flush()
    if previous_analyses == 0:
        writing.original_version_id = latest_version.id
    analysis = Analysis(writing_id=writing.id, status="queued", analysis_types=data.get("analysisTypes", ["전체 분석"]), settings=data.get("settings", {}))
    db.session.add(analysis)
    db.session.flush()
    job = AnalysisJob(analysis_id=analysis.id, status="queued", progress=0, current_step="대기")
    db.session.add(job)
    writing.status = "분석 중"
    db.session.commit()
    submit_analysis(current_app._get_current_object(), job.id)
    return success({"analysisId": analysis.id, "jobId": job.id, "status": job.status}, "분석 작업이 시작되었습니다.", 202)


@bp.get("/analysis-jobs/<job_id>")
def get_job(job_id):
    job = db.session.get(AnalysisJob, job_id)
    if not job:
        return api_error("NOT_FOUND", "분석 작업을 찾을 수 없습니다.", 404)
    return success({"id": job.id, "analysisId": job.analysis_id, "status": job.status, "progress": job.progress, "currentStep": job.current_step, "completedSteps": job.completed_steps or [], "errorMessage": job.error_message, "cancelRequested": job.cancel_requested, "updatedAt": iso(job.updated_at)})


@bp.post("/analysis-jobs/<job_id>/cancel")
def cancel_job(job_id):
    job = db.session.get(AnalysisJob, job_id)
    if not job:
        return api_error("NOT_FOUND", "분석 작업을 찾을 수 없습니다.", 404)
    if job.status in {"completed", "failed", "cancelled"}:
        return api_error("INVALID_STATE", "이미 종료된 작업입니다.", 409)
    job.cancel_requested = True
    job.status = "cancel_requested"
    db.session.commit()
    return success({"id": job.id, "status": job.status}, "취소를 요청했습니다.")


@bp.get("/analyses/<analysis_id>")
def get_analysis(analysis_id):
    item = db.session.get(Analysis, analysis_id)
    return success(analysis_json(item)) if item else api_error("NOT_FOUND", "분석 결과를 찾을 수 없습니다.", 404)


@bp.patch("/analyses/<analysis_id>/sentences/<sentence_id>")
def change_role(analysis_id, sentence_id):
    item = next((x for x in db.session.get(Analysis, analysis_id).sentences if x.id == sentence_id), None) if db.session.get(Analysis, analysis_id) else None
    if not item:
        return api_error("NOT_FOUND", "문장을 찾을 수 없습니다.", 404)
    data, error = json_body()
    if error:
        return error
    if data.get("role") not in {"주장", "근거", "설명", "효과", "탐구 질문 연결", "분류되지 않음"}:
        return api_error("VALIDATION_ERROR", "허용되지 않은 문장 역할입니다.")
    item.user_role = data["role"]
    db.session.commit()
    return success({"id": item.id, "autoRole": item.auto_role, "userRole": item.user_role, "changed": item.user_role != item.auto_role}, "문장 역할이 저장되었습니다.")


@bp.post("/findings/<finding_id>/actions")
def finding_action(finding_id):
    item = db.session.get(AnalysisFinding, finding_id)
    if not item:
        return api_error("NOT_FOUND", "분석 결과를 찾을 수 없습니다.", 404)
    data, error = json_body()
    if error:
        return error
    action = data.get("action")
    if action not in {"ignore", "confirm"}:
        return api_error("VALIDATION_ERROR", "허용되지 않은 조치입니다.")
    item.status = "ignored" if action == "ignore" else "confirmed"
    db.session.add(FindingAction(finding_id=item.id, action=action))
    db.session.commit()
    return success(finding_json(item), "처리 상태가 저장되었습니다.")


def _apply_findings(writing, findings, name):
    content = writing.content or ""
    patches = []
    for finding in findings:
        if not finding.suggestion or finding.start_offset is None or finding.end_offset is None:
            continue
        if finding.metadata_json.get("contextRequired") or finding.metadata_json.get("protectedQuote"):
            continue
        if content[finding.start_offset:finding.end_offset] != finding.current_text:
            raise ValueError(finding.id)
        patches.append(finding)
    base = writing.versions[-1] if writing.versions else WritingVersion(writing_id=writing.id, name="원문", content=content, version_number=1)
    if base.id is None:
        db.session.add(base); db.session.flush()
    updated = content
    for finding in sorted(patches, key=lambda x: x.start_offset, reverse=True):
        updated = updated[:finding.start_offset] + finding.suggestion + updated[finding.end_offset:]
    version = WritingVersion(writing_id=writing.id, parent_id=base.id, name=name, content=updated, version_number=len(writing.versions) + 1, change_count=len(patches))
    db.session.add(version); db.session.flush()
    revision = Revision(writing_id=writing.id, base_version_id=base.id, result_version_id=version.id, status="applied")
    db.session.add(revision); db.session.flush()
    for finding in patches:
        db.session.add(RevisionChange(revision_id=revision.id, finding_id=finding.id, before_text=finding.current_text, after_text=finding.suggestion, start_offset=finding.start_offset, end_offset=finding.end_offset))
        finding.status = "applied"
        db.session.add(FindingAction(finding_id=finding.id, action="apply"))
    writing.content = updated
    writing.status = "수정 중"
    writing.revision_number += 1
    return revision, version


@bp.post("/findings/<finding_id>/apply")
def apply_finding(finding_id):
    finding = db.session.get(AnalysisFinding, finding_id)
    if not finding:
        return api_error("NOT_FOUND", "분석 결과를 찾을 수 없습니다.", 404)
    analysis = db.session.get(Analysis, finding.analysis_id)
    writing = db.session.get(Writing, analysis.writing_id)
    try:
        revision, version = _apply_findings(writing, [finding], "수정 제안 적용")
    except ValueError:
        return api_error("POSITION_CONFLICT", "글이 변경되어 제안 위치가 일치하지 않습니다. 다시 분석해 주세요.", 409)
    if version.change_count == 0:
        return api_error("NOT_APPLICABLE", "자동 적용할 수 없는 제안입니다.", 409)
    db.session.commit()
    return success({"revisionId": revision.id, "versionId": version.id, "content": version.content, "changeCount": version.change_count}, "수정 제안을 적용했습니다.")


@bp.post("/revisions")
def apply_many():
    data, error = json_body()
    if error:
        return error
    analysis = db.session.get(Analysis, data.get("analysisId"))
    if not analysis:
        return api_error("NOT_FOUND", "분석 결과를 찾을 수 없습니다.", 404)
    ids = data.get("findingIds", [])
    findings = [x for x in analysis.findings if x.id in ids]
    writing = db.session.get(Writing, analysis.writing_id)
    try:
        revision, version = _apply_findings(writing, findings, str(data.get("name", "수정 제안 일괄 적용"))[:200])
    except ValueError as exc:
        return api_error("POSITION_CONFLICT", "글이 변경되어 일부 제안 위치가 일치하지 않습니다.", 409, {"findingId": str(exc)})
    if version.change_count == 0:
        return api_error("NOT_APPLICABLE", "자동 적용 가능한 제안이 없습니다.", 409)
    db.session.commit()
    return success({"revisionId": revision.id, "versionId": version.id, "content": version.content, "changeCount": version.change_count}, "수정 제안을 적용했습니다.", 201)


@bp.post("/revisions/<revision_id>/undo")
def undo_revision(revision_id):
    revision = db.session.get(Revision, revision_id)
    if not revision:
        return api_error("NOT_FOUND", "수정 기록을 찾을 수 없습니다.", 404)
    if revision.status == "undone":
        return api_error("INVALID_STATE", "이미 실행 취소한 수정입니다.", 409)
    writing = db.session.get(Writing, revision.writing_id)
    base = db.session.get(WritingVersion, revision.base_version_id)
    undo_version = WritingVersion(writing_id=writing.id, parent_id=revision.result_version_id, name="실행 취소", content=base.content, version_number=len(writing.versions) + 1, change_count=len(revision.changes) if hasattr(revision, "changes") else 1)
    db.session.add(undo_version)
    writing.content = base.content
    writing.revision_number += 1
    revision.status = "undone"
    RevisionChange.query.filter_by(revision_id=revision.id).update({"undone": True})
    db.session.commit()
    return success({"revisionId": revision.id, "versionId": undo_version.id, "content": writing.content}, "수정을 실행 취소했습니다.")
