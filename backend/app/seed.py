from datetime import date

from .extensions import db
from .models import Analysis, AnalysisJob, LanguageRule, OcrRun, OfficialSource, Rubric, SourceDocument, Workspace, WorkspaceSetting


DEFAULT_SETTINGS = {
    "theme": "default",
    "pageAnimation": True,
    "bookTexture": True,
    "autosaveInterval": 60,
    "argumentLinkThreshold": 7,
    "quoteSimilarityThreshold": 0.95,
    "defaultAnalysisType": "전체 분석",
    "allowBulkSpellingFix": True,
    "lowOcrConfidenceThreshold": 70,
    "ocrLanguage": "kor+eng",
    "imageZoom": 100,
    "ocrPreprocessing": True,
    "fontSize": "보통",
    "highContrast": False,
    "reduceMotion": False,
    "nonColorStatus": True,
    "lastBackupAt": None,
}


def ensure_defaults():
    workspace = db.session.get(Workspace, "local-workspace")
    if not workspace:
        workspace = Workspace(id="local-workspace", user_name="", name="글빛 작업 공간")
        db.session.add(workspace)
        db.session.flush()
    existing = {item.key for item in WorkspaceSetting.query.filter_by(workspace_id=workspace.id)}
    for key, value in DEFAULT_SETTINGS.items():
        if key not in existing:
            db.session.add(WorkspaceSetting(workspace_id=workspace.id, key=key, value=value))

    source = OfficialSource.query.filter_by(name="국립국어원 한국어 어문 규범").first()
    if not source:
        source = OfficialSource(
            name="국립국어원 한국어 어문 규범",
            url="https://korean.go.kr/",
            checked_at=date(2026, 8, 13),
        )
        db.session.add(source)
        db.session.flush()
    if LanguageRule.query.count() == 0:
        db.session.add_all([
            LanguageRule(name="의존 명사 '수'의 띄어쓰기", pattern=r"할수\s+있다", replacement="할 수 있다", status="명백한 오류", explanation="의존 명사 '수'는 앞말과 띄어 씁니다.", clause="한글 맞춤법 제42항", source_id=source.id, auto_fixable=True),
            LanguageRule(name="'며칠'의 표기", pattern=r"몇일", replacement="며칠", status="명백한 오류", explanation="날짜를 나타내는 말은 '며칠'로 적습니다.", clause="한글 맞춤법 제27항", source_id=source.id, auto_fixable=True),
            LanguageRule(name="'로서'와 '로써' 구분", pattern=r"\b로써\b", replacement=None, status="문맥 확인 필요", explanation="자격은 '로서', 수단은 '로써'를 사용합니다.", clause="어문 규범 일반", source_id=source.id, context_required=True),
            LanguageRule(name="'뿐'의 용법", pattern=r"뿐", replacement=None, status="문맥 확인 필요", explanation="조사와 의존 명사 용법에 따라 띄어쓰기가 달라집니다.", clause="한글 맞춤법 제42항", source_id=source.id, context_required=True),
        ])
    db.session.commit()


def recover_interrupted_jobs():
    jobs = AnalysisJob.query.filter(AnalysisJob.status.in_(["queued", "running", "cancel_requested"])).all()
    for job in jobs:
        job.status = "failed"
        job.error_message = "서버 재시작으로 분석 작업이 중단되었습니다. 다시 실행해 주세요."
        analysis = db.session.get(Analysis, job.analysis_id)
        if analysis:
            analysis.status = "failed"
    ocr_runs = OcrRun.query.filter(OcrRun.status.in_(["queued", "running", "processing"])).all()
    for run in ocr_runs:
        run.status = "failed"
        run.error_message = "서버 재시작으로 OCR 작업이 중단되었습니다. 다시 실행해 주세요."
        if run.target_type == "rubric":
            target = db.session.get(Rubric, run.target_id)
        elif run.target_type == "source-document":
            target = db.session.get(SourceDocument, run.target_id)
        else:
            target = None
        if target:
            target.status = "처리 실패"
    if jobs or ocr_runs:
        db.session.commit()
