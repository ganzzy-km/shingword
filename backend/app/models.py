from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Index

from .extensions import db


def utcnow():
    return datetime.now(timezone.utc)


def uuid4():
    return str(uuid.uuid4())


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Workspace(db.Model, TimestampMixin):
    id = db.Column(db.String(64), primary_key=True, default="local-workspace")
    user_name = db.Column(db.String(120), default="", nullable=False)
    name = db.Column(db.String(200), default="글빛 작업 공간", nullable=False)


class WorkspaceSetting(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    workspace_id = db.Column(
        db.String(64), db.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    key = db.Column(db.String(100), nullable=False)
    value = db.Column(db.JSON, nullable=False)
    __table_args__ = (db.UniqueConstraint("workspace_id", "key"),)


class Rubric(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    workspace_id = db.Column(db.String(64), db.ForeignKey("workspace.id"), nullable=False)
    name = db.Column(db.String(240), nullable=False, index=True)
    subject = db.Column(db.String(120), default="")
    activity = db.Column(db.String(120), default="")
    status = db.Column(db.String(40), default="등록 완료", nullable=False, index=True)
    description = db.Column(db.Text, default="")
    file = db.relationship("RubricFile", backref="rubric", uselist=False, cascade="all, delete-orphan")
    items = db.relationship("RubricItem", backref="rubric", cascade="all, delete-orphan")


class RubricFile(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    rubric_id = db.Column(db.String(36), db.ForeignKey("rubric.id", ondelete="CASCADE"), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False, unique=True)
    mime_type = db.Column(db.String(120), nullable=False)
    size = db.Column(db.Integer, nullable=False)
    page_count = db.Column(db.Integer, default=0, nullable=False)
    ocr_text = db.Column(db.Text)
    corrected_text = db.Column(db.Text)
    ocr_confidence = db.Column(db.Float)


class RubricItem(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    rubric_id = db.Column(db.String(36), db.ForeignKey("rubric.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(240), nullable=False)
    description = db.Column(db.Text, default="")
    check_type = db.Column(db.String(60), default="사람의 판단 필요")
    source_location = db.Column(db.String(200), default="")
    position = db.Column(db.Integer, default=0)


class SourceDocument(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    workspace_id = db.Column(db.String(64), db.ForeignKey("workspace.id"), nullable=False)
    title = db.Column(db.String(240), nullable=False, index=True)
    author = db.Column(db.String(160), default="", index=True)
    edition = db.Column(db.String(200), default="")
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False, unique=True)
    mime_type = db.Column(db.String(120), nullable=False)
    size = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(40), default="업로드됨", nullable=False, index=True)
    page_count = db.Column(db.Integer, default=0, nullable=False)
    pages = db.relationship("SourcePage", backref="document", cascade="all, delete-orphan")
    quote_cards = db.relationship("QuoteCard", backref="document")


class SourcePage(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    document_id = db.Column(db.String(36), db.ForeignKey("source_document.id", ondelete="CASCADE"), nullable=False)
    page_number = db.Column(db.Integer, nullable=False)
    original_text = db.Column(db.Text)
    corrected_text = db.Column(db.Text)
    confidence = db.Column(db.Float)
    extraction_method = db.Column(db.String(40), default="unavailable")
    __table_args__ = (db.UniqueConstraint("document_id", "page_number"),)


class OcrRun(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    target_type = db.Column(db.String(30), nullable=False, index=True)
    target_id = db.Column(db.String(36), nullable=False, index=True)
    status = db.Column(db.String(40), default="queued", nullable=False)
    language = db.Column(db.String(40), default="kor+eng")
    error_message = db.Column(db.Text)


class QuoteCard(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    workspace_id = db.Column(db.String(64), db.ForeignKey("workspace.id"), nullable=False)
    document_id = db.Column(db.String(36), db.ForeignKey("source_document.id", ondelete="RESTRICT"))
    selected_text = db.Column(db.Text, nullable=False)
    quote_text = db.Column(db.Text, nullable=False)
    work = db.Column(db.String(240), default="")
    author = db.Column(db.String(160), default="")
    page = db.Column(db.String(60), default="")
    scene = db.Column(db.Text, default="")
    characters = db.Column(db.JSON, default=list)
    keywords = db.Column(db.JSON, default=list)
    inquiry_question = db.Column(db.Text, default="")
    verification_status = db.Column(db.String(40), default="확인 필요", nullable=False, index=True)


class QuoteVerification(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    quote_card_id = db.Column(db.String(36), db.ForeignKey("quote_card.id", ondelete="CASCADE"), nullable=False)
    status = db.Column(db.String(40), nullable=False)
    difference = db.Column(db.JSON)
    reason = db.Column(db.Text, default="")


class Writing(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    workspace_id = db.Column(db.String(64), db.ForeignKey("workspace.id"), nullable=False)
    title = db.Column(db.String(240), default="", index=True)
    work = db.Column(db.String(240), default="", index=True)
    author = db.Column(db.String(160), default="")
    inquiry_question = db.Column(db.Text, default="")
    subject = db.Column(db.String(120), default="")
    conditions = db.Column(db.Text, default="")
    due_date = db.Column(db.Date)
    content = db.Column(db.Text, default="")
    status = db.Column(db.String(40), default="임시 저장", nullable=False, index=True)
    revision_number = db.Column(db.Integer, default=1, nullable=False)
    original_version_id = db.Column(db.String(36))
    versions = db.relationship("WritingVersion", backref="writing", cascade="all, delete-orphan")
    resources = db.relationship("WritingResource", backref="writing", cascade="all, delete-orphan")


class WritingVersion(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    writing_id = db.Column(db.String(36), db.ForeignKey("writing.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id = db.Column(db.String(36), db.ForeignKey("writing_version.id"))
    name = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, default="")
    version_number = db.Column(db.Integer, nullable=False)
    change_count = db.Column(db.Integer, default=0)


class WritingResource(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    writing_id = db.Column(db.String(36), db.ForeignKey("writing.id", ondelete="CASCADE"), nullable=False)
    resource_type = db.Column(db.String(40), nullable=False)
    resource_id = db.Column(db.String(36), nullable=False)
    __table_args__ = (db.UniqueConstraint("writing_id", "resource_type", "resource_id"),)


class DraftAutosave(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    writing_id = db.Column(db.String(36), db.ForeignKey("writing.id", ondelete="CASCADE"), nullable=False)
    revision_number = db.Column(db.Integer, nullable=False)
    content = db.Column(db.Text, default="")


class Analysis(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    writing_id = db.Column(db.String(36), db.ForeignKey("writing.id", ondelete="CASCADE"), nullable=False, index=True)
    status = db.Column(db.String(40), default="queued", nullable=False, index=True)
    analysis_types = db.Column(db.JSON, default=list)
    settings = db.Column(db.JSON, default=dict)
    metrics = db.Column(db.JSON, default=dict)
    disclaimer = db.Column(db.Text, default="이 지표는 교사의 평가 점수가 아니라 글의 구조를 점검하기 위한 참고 정보입니다.")
    sentences = db.relationship("AnalysisSentence", backref="analysis", cascade="all, delete-orphan")
    findings = db.relationship("AnalysisFinding", backref="analysis", cascade="all, delete-orphan")


class AnalysisJob(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    analysis_id = db.Column(db.String(36), db.ForeignKey("analysis.id", ondelete="CASCADE"), nullable=False, unique=True)
    status = db.Column(db.String(40), default="queued", nullable=False, index=True)
    progress = db.Column(db.Integer, default=0, nullable=False)
    current_step = db.Column(db.String(120), default="대기")
    completed_steps = db.Column(db.JSON, default=list)
    error_message = db.Column(db.Text)
    cancel_requested = db.Column(db.Boolean, default=False, nullable=False)


class AnalysisSentence(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    analysis_id = db.Column(db.String(36), db.ForeignKey("analysis.id", ondelete="CASCADE"), nullable=False, index=True)
    paragraph_number = db.Column(db.Integer, nullable=False)
    sentence_number = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False)
    start_offset = db.Column(db.Integer, nullable=False)
    end_offset = db.Column(db.Integer, nullable=False)
    auto_role = db.Column(db.String(40), default="분류되지 않음")
    user_role = db.Column(db.String(40))
    confidence = db.Column(db.Float)
    rationale = db.Column(db.Text, default="")


class AnalysisFinding(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    analysis_id = db.Column(db.String(36), db.ForeignKey("analysis.id", ondelete="CASCADE"), nullable=False, index=True)
    finding_type = db.Column(db.String(60), nullable=False, index=True)
    severity = db.Column(db.String(30), default="info")
    title = db.Column(db.String(240), nullable=False)
    current_text = db.Column(db.Text, default="")
    suggestion = db.Column(db.Text)
    reason = db.Column(db.Text, default="")
    rule = db.Column(db.String(240))
    source_url = db.Column(db.String(500))
    confidence = db.Column(db.Float)
    start_offset = db.Column(db.Integer)
    end_offset = db.Column(db.Integer)
    status = db.Column(db.String(40), default="open", nullable=False)
    metadata_json = db.Column(db.JSON, default=dict)


class ArgumentLink(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    analysis_id = db.Column(db.String(36), db.ForeignKey("analysis.id", ondelete="CASCADE"), nullable=False)
    claim_sentence_id = db.Column(db.String(36), db.ForeignKey("analysis_sentence.id"), nullable=False)
    evidence_sentence_id = db.Column(db.String(36), db.ForeignKey("analysis_sentence.id"), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(40), nullable=False)
    details = db.Column(db.JSON, default=dict)


class PeelResult(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    analysis_id = db.Column(db.String(36), db.ForeignKey("analysis.id", ondelete="CASCADE"), nullable=False)
    paragraph_number = db.Column(db.Integer, nullable=False)
    elements = db.Column(db.JSON, default=dict)
    rationale = db.Column(db.Text, default="")
    guidance = db.Column(db.Text, default="")


class RubricResult(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    analysis_id = db.Column(db.String(36), db.ForeignKey("analysis.id", ondelete="CASCADE"), nullable=False)
    rubric_item_id = db.Column(db.String(36), db.ForeignKey("rubric_item.id", ondelete="SET NULL"))
    status = db.Column(db.String(40), nullable=False)
    rationale = db.Column(db.Text, default="")
    related_sentences = db.Column(db.JSON, default=list)


class QuoteCheckResult(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    analysis_id = db.Column(db.String(36), db.ForeignKey("analysis.id", ondelete="CASCADE"), nullable=False)
    student_quote = db.Column(db.Text, nullable=False)
    source_quote = db.Column(db.Text)
    status = db.Column(db.String(60), nullable=False)
    confidence = db.Column(db.Float)
    differences = db.Column(db.JSON, default=list)
    source_document_id = db.Column(db.String(36), db.ForeignKey("source_document.id", ondelete="SET NULL"))
    source_page = db.Column(db.String(60))


class SpellingResult(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    analysis_id = db.Column(db.String(36), db.ForeignKey("analysis.id", ondelete="CASCADE"), nullable=False)
    finding_id = db.Column(db.String(36), db.ForeignKey("analysis_finding.id", ondelete="CASCADE"), nullable=False)
    auto_fixable = db.Column(db.Boolean, default=False, nullable=False)
    context_question = db.Column(db.Text)


class Revision(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    writing_id = db.Column(db.String(36), db.ForeignKey("writing.id", ondelete="CASCADE"), nullable=False)
    base_version_id = db.Column(db.String(36), db.ForeignKey("writing_version.id"), nullable=False)
    result_version_id = db.Column(db.String(36), db.ForeignKey("writing_version.id"), nullable=False)
    status = db.Column(db.String(40), default="applied", nullable=False)


class RevisionChange(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    revision_id = db.Column(db.String(36), db.ForeignKey("revision.id", ondelete="CASCADE"), nullable=False)
    finding_id = db.Column(db.String(36), db.ForeignKey("analysis_finding.id", ondelete="SET NULL"))
    before_text = db.Column(db.Text, nullable=False)
    after_text = db.Column(db.Text, nullable=False)
    start_offset = db.Column(db.Integer, nullable=False)
    end_offset = db.Column(db.Integer, nullable=False)
    undone = db.Column(db.Boolean, default=False, nullable=False)


class FindingAction(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    finding_id = db.Column(db.String(36), db.ForeignKey("analysis_finding.id", ondelete="CASCADE"), nullable=False)
    action = db.Column(db.String(40), nullable=False)


class OfficialSource(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    name = db.Column(db.String(240), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    checked_at = db.Column(db.Date, nullable=False)


class LanguageRule(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    name = db.Column(db.String(240), nullable=False)
    pattern = db.Column(db.String(300), nullable=False)
    replacement = db.Column(db.String(300))
    status = db.Column(db.String(40), nullable=False)
    explanation = db.Column(db.Text, nullable=False)
    clause = db.Column(db.String(240), nullable=False)
    source_id = db.Column(db.String(36), db.ForeignKey("official_source.id", ondelete="SET NULL"))
    auto_fixable = db.Column(db.Boolean, default=False, nullable=False)
    context_required = db.Column(db.Boolean, default=False, nullable=False)


class ActivityRecord(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    action = db.Column(db.String(120), nullable=False, index=True)
    target_type = db.Column(db.String(60), nullable=False)
    target_id = db.Column(db.String(36))
    details = db.Column(db.JSON, default=dict)


class BackupRecord(db.Model, TimestampMixin):
    id = db.Column(db.String(36), primary_key=True, default=uuid4)
    filename = db.Column(db.String(255), nullable=False, unique=True)
    size = db.Column(db.Integer, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    include_uploads = db.Column(db.Boolean, default=True, nullable=False)
    schema_version = db.Column(db.String(20), default="1", nullable=False)


Index("ix_source_page_text", SourcePage.corrected_text)
