# 운영 migration 최신 상태 (2026-10-10)

사용자 별도 승인에 따라 운영 C:\Users\USER\GeulbitData의 0001_initial → 0002_geulbit_v2 → 0003_resource_ownership 적용 완료. 아래 0001/hash 유지 및 운영 승인 대기 기록은 적용 전 조사 이력이다. 최종 40개 테이블, ORM/schema/trigger 일치, integrity ok/FK 0; 기존 모든 컬럼 값과 설정 17/규칙 4 보존. 고유 Online Backup 및 격리 복원 PASS. 최초 사후 비교의 tuple/list 직렬화 오류(전체 명령 exit 1)는 추가 DB 변경 없이 canonical 읽기 검증(exit 0)으로 확인; migration 재실행 없음. 프로젝트 G5 DEFERRED_FINAL_REVIEW 유지. 상세 실행/backup 경로는 backend-checkpoint.json.operationalMigration 및 승인된 Data Root의 receipt에 기록. AI 키는 DPAPI 암호화 등록만 완료, 외부 호출 및 Codex 제공자 변경 없음. 다른 Phase/삭제/배포를 시작하지 않음.

# 최신 승인 및 정식 revision 검증

- P03~P12 개발 구현 및 실제 API/두 테마 격리 통합 검증을 진행했다. 운영 적용 상태와 개발 Gate는 별개다. 실제 DB는 0001_initial, 31개 테이블과 초기 설정·규칙을 그대로 유지한다.
- 0003_resource_ownership은 기존 workspace/rubric/quote_card의 nullable 소유권과 인덱스·제약만 추가한다. 기존 owner 추정·소급 snapshot 생성 없음. 격리 복사본은 0001→0002→0003 upgrade·재실행·FK/integrity·원래 값 보존 검증을 통과했다.
- 운영 서버의 기대 head는 0003이다. 운영 migration 승인 전에는 기존 0001 DB를 MIGRATION_REQUIRED로 차단하며 자동 upgrade/초기화하지 않는다. 기존 백업과 LocalCache는 이동·병합하지 않는다.
- 7일 정책은 미확정이다. 구현된 정리는 검증된 명시적 expires_at만 대상으로 하며, 정책·날짜 부여 과정·백업·개인 자료의 독립 수명에 관한 운영 승인이 없으면 시작/호출을 차단한다. 현재 운영 활성화 없음.
- 운영 입력: GEULBIT_V2=1, GEULBIT_SESSION_SIGNING_KEY, GEULBIT_SESSION_MAX_AGE; Google client ID/secret/HTTPS redirect/state TTL/외부 사용 승인. 값은 사용자 또는 운영자가 별도로 제공하며 소스에 비밀값을 저장하지 않는다.
- G5는 DEFERRED_FINAL_REVIEW. 실제 Google/BAZE 및 운영 삭제/배포 검증을 로컬 테스트로 대체하지 않는다.


- 사용자가 P03 인증/P04 저장/P05 분석 API/P06 규범/P07 구조/P08 자료실/P09 인용/P10 앵커/P11 AI/P12 운영·PDF·삭제·통합 배치를 명시 승인했다. 아래 과거 번호 배치 후보와 번호 미확정 차단은 폐기된 이력이다. 실행 SSOT: backend-queue.local.json.
- 정식 0002_geulbit_v2(down_revision=0001_initial): 기존 테이블·ID·초기값 유지, 9개 새 테이블과 22개 nullable 컬럼, FK/index/불변성 trigger 추가. 기존 0001 수정 없음.
- 실제 운영 복사본에서 upgrade·재실행·31개 테이블 기존 값 보존·integrity/FK·downgrade 차단·backup 복원 검증. 운영 DB는 0001/hash 유지. unsafe downgrade 대신 검증 backup 복원을 사용한다.
- 격리 근거: C:\Users\USER\GeulbitData\temp\formal-migration-532777a1fc1648fcb0aaabb77ba64c5f; 자세한 수치는 기존 checkpoint.formalMigration. 운영 적용 승인 미포함; Phase 개발은 계속한다.

# 글빛 2.0 DB 매핑 및 실행 준비

운영 DB는 읽기 전용 조사만 수행. 목표 경로는 최신 사용자 지정 C:\Users\USER\GeulbitData. P01/P02 G1~G4 PASS, G5 DEFERRED_FINAL_REVIEW.

## 실제 관찰 및 확정 경계

- HEAD: 68d771840014cdef9e9acc84be1f2f613cc269a0, master. 운영 Alembic 0001_initial; 31개 테이블; integrity ok/FK violation 0.
- writing/version/analysis/source_document/source_page/quote/rubric 계열은 0건. workspace 1, workspace_setting 17, language_rule 4, official_source 1. 이 초기 데이터를 삭제하거나 사용자의 계정으로 승격하지 않는다.
- CONFIRMED: 기존 writing/ writing_version/ analysis/ source_document의 물리 ID와 기존 /api 경로를 재사용한다. 새 essays/essay_versions/analysis_runs/documents 병렬 테이블을 만들지 않는다.
- CONFIRMED: 신규 원문은 NFC/LF, code point [start,end). USER/ADMIN 분리, 신규 승인 대기, private owner 보호, 공용 ADD 지정 검증 계정/DELETE ADMIN은 기존 사용자 지시로 확정. 구형 설계의 해당 미결은 이 명시 지시보다 우선하지 않는다.
- CONFIRMED: legacy revision은 글 수정 이력이며 document_revisions로 이름 변경하지 않는다. 소유권/본문 버전을 증명하지 못한 기존 행은 NULL/untrusted로 보존하고 접근/앵커 적용을 차단한다.
- DATA_MODEL/API_CONTRACT/DECISIONS/ACTIVE_PLAN의 확정 파일은 현재 저장소에 없다. docs/design/20261010와 실제 routes/models, Runner plan을 참조했다. 제안 DDL을 승인된 migration으로 위장하지 않는다.

## 14개 엔티티 매핑

| 목표 | 상태 | 실제 출발점 | 확정 재사용 및 필요한 변경 |
|---|---|---|---|
| users | NEEDS_MIGRATION | 없음; workspace.user_name은 인증 주체가 아님 | users 추가: id, issuer/sub UNIQUE, USER/ADMIN, 승인 상태, session_version, 검증된 email 메타데이터. 기본 USER/PENDING_APPROVAL; 계정 자동 생성/소유자 backfill 없음 |
| consents | NEEDS_MIGRATION | 없음 | users FK의 종류·정책 버전·동의/철회 시각 기록 추가. AI 동의와 일반 로그인 분리; 보존 정책 미결 |
| essays | NEEDS_MIGRATION | writing | 테이블과 id/content/revision_number 재사용. owner_id FK nullable 추가; 신규 저장은 서버 인증 소유자 필수. 원자적 revision 조건 UPDATE; NULL owner는 제공 금지. original_version_id는 이름만으로 현재 확정 버전으로 재해석하지 않음 |
| essay_versions | NEEDS_MIGRATION | writing_version | id/writing_id/parent_id/content/version_number 유지. snapshot_hash/normalization_version 추가, NFC/LF 확인 후 신규 snapshot만 인증. 기존 hash NULL은 미검증 이력이며 자동 정규화·불변 승격 없음 |
| analysis_runs | NEEDS_MIGRATION | analysis + analysis_job | analysis.id를 run ID로 재사용, essay_version_id FK/result JSON/schema/manifest/context/version/hash/완료 시각 확장. 정확한 같은 writing의 인증 version만 연결. 과거 writing_id로 최신 version을 추정하지 않음; 1 version:N analysis 허용. 기존 sentence/finding 테이블은 보존하고 신규 snapshot의 SSOT로 중복 생성하지 않음 |
| works | NEEDS_MIGRATION | writing.work 및 source_document.title/author는 문자열 | works 추가. 기존 문자열만으로 작품 identity/중복/판본 자동 병합 금지; 신규 작품은 명시적으로 연결. 고유 어휘 JSON 포함 |
| documents | NEEDS_MIGRATION | source_document + source_page; rubric 계열은 별도 기존 기준표 | source_document id/파일 메타데이터 재사용; owner_id/type/scope/access_mode/rights/source/edition 메타데이터 확장. 신규 공개 자료는 권리 확인 필수. 기존 source_page는 문서 snapshot이 아님; rubric→문서 자동 승격 없음 |
| work_documents | NEEDS_MIGRATION | 없음 | works와 source_document 연결 FK/UNIQUE 추가. 다른 판본을 작품 제목만으로 선택하지 않음 |
| document_revisions | NEEDS_MIGRATION | 없음; revision은 글 수정 이력 | 새 document_revisions만 추가. document FK, parent, revision_number UNIQUE, 내용/hash/파일 참조/생성 시각; UPDATE 차단. source_page의 mutable corrected_text를 과거 불변 snapshot으로 위조하지 않음 |
| essay_documents | NEEDS_MIGRATION | writing_resource(resource_type,resource_id), 대상 FK 없음 | 기존 writing_resource는 rubric/source/quote 연결을 보존. 문서 분석용 writing↔document_revision 명시적 FK 연결 추가; 최신 판본으로 조용히 대체하지 않음 |
| feedback_reactions | NEEDS_MIGRATION | finding_action(finding_id,action) | 기존 finding_action은 legacy finding 기준으로 보존. 신규 JSON feedback_id+analysis_id+user_id의 반응 테이블 추가; 현재 사용자/run 소유권 확인. 반응을 정확성 정답으로 사용하지 않음 |
| ai_interactions | NEEDS_MIGRATION | 없음; quote_card.inquiry_question은 AI 동의·실행 증거가 아님 | user/run/selected span/preview digest/consent version/status/questions 및 선택 메모 저장 경계 추가. 최소 문맥만 전송; 로그/중복 전체 원문 제외. 보존·budget·provider 조건 전에는 외부 OFF |
| audit_logs | NEEDS_MIGRATION | activity_record(action,target_type,target_id,details) | activity_record 재사용/확장: actor FK, 민감 원문 없는 허용 action 및 최소 메타데이터. 기존 자유 details를 새 감사 규약으로 자동 승인하지 않음 |
| app_settings | NEEDS_MIGRATION | workspace_setting UNIQUE(workspace_id,key) | workspace_setting의 범위는 작업공간 설정으로 유지; 전역 운영 설정용 key UNIQUE app_settings 추가. 기존 17개 value를 global 설정으로 임의 복제하지 않음 |

## Migration 및 복구 계약

- NEEDS_MIGRATION: 향후 새 0002 revision은 down_revision=0001_initial로 추가하며 기존 0001/models SSOT를 재작성하지 않는다. 새 revision의 DDL은 models와 일치하도록 별도 검토해야 한다. 현재 실제 migration 파일은 추가/수정하지 않았다.
- additive nullable FK/metadata와 새 기능 테이블 우선. 기존 칼럼명·원문·ID·행 유지. SQLite ALTER REFERENCES는 nullable/default NULL로 적용; NOT NULL/UNIQUE 강제는 backfill 증거 확인 뒤에만.
- 기존 initial migration은 db.metadata.create_all을 참조하므로 모델 확장 시 기존 첫 migration이 새 테이블까지 생성할 수 있다. 새 revision은 empty/fresh/upgraded DB 모두에서 중복 생성 없이 동작하도록 설계·검증해야 한다. 이번 시험은 이 실제 계보 연결을 완료한 것이 아니다.
- 신규 user의 owner FK는 세션에서만 부여. 현재 학생 데이터가 0건이므로 legacy owner 선택 결정은 필요 없다. 데이터가 나중에 생기면 자동 승격 금지; 증거 없는 분석 이력은 새 원문에 연결하지 않음.
- BEGIN IMMEDIATE의 짧은 migration transaction과 source sqlite backup API 사용. 실패는 explicit rollback, 운영 재시작 차단; rollback 불가능한 단계는 쓰기 중단 상태에서 같은 승인 root의 검증된 backup으로 복구. 운영 rollback/downgrade/delete는 이번 작업에서 실행하지 않음.
- 후보 backend/mapping/rehearsal.py는 Alembic Operations 기반 핵심 관계 실험만 수행. users/document_revisions + 6개 추가 컬럼/constraints; 나머지 엔티티의 DDL과 API는 미구현. 실행 조건 isolated=True; 운영 CLI/routes에서 호출하지 않는다.
- 실제 source 읽기전용 backup→격리 candidate rollback→candidate apply→backup/restore 검사 완료. 기존 31테이블 모든 행 수·schema/source SHA256 유지; users 0건, 허위 owner/version backfill 없음.
- 격리 파일 위치: `C:\Users\USER\GeulbitData\temp\db-mapping-rehearsal-62458e07138d491c920bbaa106fb4ac8`. 기존 운영자료와 구별한 검증용 복사본이며 운영에 자동 병합/이동하지 않는다. 승인되지 않은 삭제/보존기간 적용 없이 유지한다.
- 운영 source SHA256(before=after): `5eb7e531521311c01739065bb0494b27d23a438dba9389526da2ea429e6d38c5`. source와 candidate Alembic 값은 모두 0001_initial; candidate는 등록 migration이 아니므로 0002 성공으로 기록하지 않는다.

## P03~P12 실행 계약

NEEDS_DECISION: 기존 Queue에는 P03~P10의 prompt/activePlan/scope/test가 null이고 번호별 원본 설계가 없다. 아래는 기존 승인 기능을 실행 단위에 배치한 **번호 매핑 후보**이며 승인된 원본 Phase로 주장하지 않는다. P11 AI/P12 삭제 경계는 사용자 원문에서 확인했다. 새 아키텍처는 도입하지 않는다. 번호 배치 승인 후 아래 범위를 Runner plan/scope에 연결할 수 있다. 현 실행은 db-mapping-preparation 컴포넌트뿐이다.

| Phase/경계 | 선행 조건 | API·모델 사용 | 관련 검증 | 완료 조건 | 결정·외부 조건 |
|---|---|---|---|---|---|
| p03 DB/ownership mapping | p01,p02 및 additive DDL 승인 | 기존 모델 확장·FK·격리 Alembic upgrade/재실행/실패 rollback/백업 restore; 운영 적용 별도 | backend/mapping_tests (6개 실재); 완성 revision용 populated/empty/반복/동시 fixture는 후속 | 필요 컬럼·FK·불변성 및 기존 데이터 보존; 본 실험은 전체 P03 PASS 아님 | 새 운영 revision/적용 승인 |
| p04 OIDC/session/admin approval | p03 users/consents | 기존 components/auth.py 재사용; issuer/sub identity, 상태/session_version/CSRF; private owner 검사 | backend/component_tests/test_auth.py (실재); 인증 API/IDOR integration 후속 | mock state/nonce/signature/권한/IDOR PASS; 실인증 PENDING_EXTERNAL 분리 | bootstrap ADMIN 계정, redirect/session 수명, 비밀값 |
| p05 draft/version 저장 | p03,p04 | /api/writings, /autosave, /versions 유지; content/revisionNumber/id envelope 유지; expected revision 원자적 검사와 NFC/LF snapshot | backend/tests/test_writing_analysis.py 중 저장 테스트 재사용; stale/경합/최신 동일본문 테스트 후속 | 실패→초안 보존, 동시성 no overwrite, 불변 snapshot/반복 A-B-A 이력 | 추가 정책 없음; API 기존 이름 유지 |
| p06 version-bound analysis API | p02,p05 및 document context 계약 | /api/writings/<id>/analyses, /analyses/<id>, /analysis-jobs/<id> 유지; AnalysisJob 재사용; 순수 snapshot/structure 연결 | backend/engine_tests/test_snapshot.py 및 기존 analysis 테스트; API failure/timeout/경합 후속 | 입력 버전·manifest/result schema 일치; 실패 후 마지막 성공 보존; 짧은 DB transaction | 취소·중복 요청·재시도 상태 전이 계약 |
| p07 Work/Document/Revision 자료실 | p03,p04 | /source-documents, /files 및 기존 rubric 경로 유지. 신규 Work/revision 경로는 기존 API와 함께 명시 후 계약화 | backend/tests/test_core_resources.py 재사용; upload MIME/path/IDOR/public permission/revision 후속 | 개인/public, ADD 지정 계정, DELETE ADMIN, 권리/access_mode, append-only 검증 | 권리 미확인→PUBLIC 금지는 확정; legacy 승격은 하지 않음 |
| p08 선택 판본 인용·피드백 앵커 | p06,p07 | SelectedRevision/RapidFuzz 재사용; run/version/CP span 원본 유지; 기존 utf16Offset/book-layout 재사용 | backend/component_tests/test_language_components.py, scripts/book-layout.test.mjs 실재; API 문서 권한 후속 | 선택 revision/hash 일치, MATCH_ONLY body 비노출, 반복 구절/stale 정확 | 유사도 threshold 승인 설정 필요; 점수는 논리 판정 아님 |
| p09 PDF report/import | p05,p06,p04 | components/pdf.py 재사용; version/run/owner 기준 memory PDF, import preview 확인 후 신규 Writing; 기존 browser 인쇄 보존 | backend/component_tests/test_pdf.py 실재; authenticated download/import-confirm/API expiry race 후속 | 한글/긴 본문/옵션/소유권/손상·스캔 거부; 신규 essay 현재 owner, 과거 분석 미승격 | 새 PDF API 경로·파일/page limit 승인 |
| p10 운영 및 두 테마 실제 통합 | p04-p09 | 기존 Waitress/StorageGuard 보존; 실제 목록·저장·분석·자료·PDF 동일 API adapter; UI 재설계 없음 | targeted API plus scripts/verify-ui-design.cjs (fixture 검증); live authenticated E2E 후속 | 실제 DB 저장·두 테마 동일 ID/run, 오류 상태, 관리자는 개인글 자동 열람 불가 | 운영 공개는 Queue 제외; HTTPS/session 외부 환경 |
| p11 선택적 AI | p04,p06; 로컬 OFF 기능은 독립 검증 가능 | components/ai.py/consents/ai_interactions 재사용; preview와 실제 최소 문맥 일치; analysis 불변 | backend/component_tests/test_ai.py 실재; persisted quota/cache/consent integration 후속 | OFF 핵심 정상, 동의/owner/schema/0~2질문/fallback; 실 Gateway 별도 | provider 처리조건/계정/model/비용/한도/보존 승인 |
| p12 7일 접근 차단·정리 | ownership 및 해당 자원 모델; 미확정 정책 승인 | components/lifecycle.py 재사용; expires_at 기준 전후 접근 검사. 확정 후 관련 자원·캐시·작업 정리; metadata 휴지통 무단 보존 없음 | 기존 component expiry guard; restart/retry/delete FK/backup conflict 후속 | 읽기/수정/PDF/진행 작업 만료 차단, 재노출0, 참조 일관성 | 기산점·대상(계정/공용/연결개인자료)·백업 보존 정책 |

## 사용자 결정 최소 항목

1. NEEDS_DECISION: 위 물리 모델 재사용/additive 범위에 기반한 새 migration 작성·검토 및 **운영 적용 여부** 승인. 준비 시험 통과와 운영 적용 승인은 별개이다. 향후 DDL 전체·dry-run 결과를 제시한 뒤 운영 적용 여부를 판단한다.
2. NEEDS_DECISION: 원본 P03~P10 번호별 계획이 있으면 그 위치 제공; 없다면 위 기능→번호 배치 채택 여부. 번호 미확정을 이유로 이미 확정된 구조를 재설계하지 않는다.
3. NEEDS_DECISION: 실제 가입/운영 전에 bootstrap ADMIN 지정 계정·HTTPS redirect/session 수명; 삭제 전 7일 기산점/적용 대상/백업 보존; 외부 AI 전송 전 제공자 처리조건·한도. 각각 관련 Phase만 차단하며 핵심 로컬 엔진을 차단하지 않는다.

## 이번 검증과 한계

- `.venv/Scripts/python.exe -m pytest backend/mapping_tests -q -p no:cacheprovider`: exit 0, 6 passed (1.44s). 정상/실패/경계·FK·불변성·동일 essay version·backup/restore·rollback 검증. 초기 SQLite ALTER 제약 오류는 inline REFERENCES로 최소 수정; 테스트 약화 없음.
- 실제 운영 복사본 실험: exit 0, integrity ok/FK 0, 모든 기존 count 유지, rollback/복원 PASS, 운영 schema/hash 유지.
- 전체 P03 migration/API·IDOR Gate는 NOT_RUN이며 신규 인증 version 인증/hash 검증·revision parent 동일 문서 검사·metadata 불변성 범위는 후속 구현에서 강화/검증한다. 시험을 전체 migration 완료 또는 G5 검토로 해석하지 않는다.

## 실제 schema 인벤토리 (개인 행 값 제외)

각 항목은 컬럼명, NOT NULL/PK 표시, FK, 실제 index만 기록한다. CHECK/SQL 원문은 읽기 전용 sqlite_master와 모델에 재조회 가능하다.

- `activity_record` (0 rows): id!NULL*PK, action!NULL, target_type!NULL, target_id, details, created_at!NULL, updated_at!NULL; FK: none; index: ix_activity_record_action(action), sqlite_autoindex_activity_record_1 UNIQUE(id)
- `alembic_version` (1 rows): version_num!NULL*PK; FK: none; index: sqlite_autoindex_alembic_version_1 UNIQUE(version_num)
- `analysis` (0 rows): id!NULL*PK, writing_id!NULL, status!NULL, analysis_types, settings, metrics, disclaimer, created_at!NULL, updated_at!NULL; FK: writing_id→writing.id delete=CASCADE; index: ix_analysis_writing_id(writing_id), ix_analysis_status(status), sqlite_autoindex_analysis_1 UNIQUE(id)
- `analysis_finding` (0 rows): id!NULL*PK, analysis_id!NULL, finding_type!NULL, severity, title!NULL, current_text, suggestion, reason, rule, source_url, confidence, start_offset, end_offset, status!NULL, metadata_json, created_at!NULL, updated_at!NULL; FK: analysis_id→analysis.id delete=CASCADE; index: ix_analysis_finding_finding_type(finding_type), ix_analysis_finding_analysis_id(analysis_id), sqlite_autoindex_analysis_finding_1 UNIQUE(id)
- `analysis_job` (0 rows): id!NULL*PK, analysis_id!NULL, status!NULL, progress!NULL, current_step, completed_steps, error_message, cancel_requested!NULL, created_at!NULL, updated_at!NULL; FK: analysis_id→analysis.id delete=CASCADE; index: ix_analysis_job_status(status), sqlite_autoindex_analysis_job_2 UNIQUE(analysis_id), sqlite_autoindex_analysis_job_1 UNIQUE(id)
- `analysis_sentence` (0 rows): id!NULL*PK, analysis_id!NULL, paragraph_number!NULL, sentence_number!NULL, text!NULL, start_offset!NULL, end_offset!NULL, auto_role, user_role, confidence, rationale, created_at!NULL, updated_at!NULL; FK: analysis_id→analysis.id delete=CASCADE; index: ix_analysis_sentence_analysis_id(analysis_id), sqlite_autoindex_analysis_sentence_1 UNIQUE(id)
- `argument_link` (0 rows): id!NULL*PK, analysis_id!NULL, claim_sentence_id!NULL, evidence_sentence_id!NULL, score!NULL, status!NULL, details, created_at!NULL, updated_at!NULL; FK: evidence_sentence_id→analysis_sentence.id delete=NO ACTION, claim_sentence_id→analysis_sentence.id delete=NO ACTION, analysis_id→analysis.id delete=CASCADE; index: sqlite_autoindex_argument_link_1 UNIQUE(id)
- `backup_record` (0 rows): id!NULL*PK, filename!NULL, size!NULL, sha256!NULL, include_uploads!NULL, schema_version!NULL, created_at!NULL, updated_at!NULL; FK: none; index: sqlite_autoindex_backup_record_2 UNIQUE(filename), sqlite_autoindex_backup_record_1 UNIQUE(id)
- `draft_autosave` (0 rows): id!NULL*PK, writing_id!NULL, revision_number!NULL, content, created_at!NULL, updated_at!NULL; FK: writing_id→writing.id delete=CASCADE; index: sqlite_autoindex_draft_autosave_1 UNIQUE(id)
- `finding_action` (0 rows): id!NULL*PK, finding_id!NULL, action!NULL, created_at!NULL, updated_at!NULL; FK: finding_id→analysis_finding.id delete=CASCADE; index: sqlite_autoindex_finding_action_1 UNIQUE(id)
- `language_rule` (4 rows): id!NULL*PK, name!NULL, pattern!NULL, replacement, status!NULL, explanation!NULL, clause!NULL, source_id, auto_fixable!NULL, context_required!NULL, created_at!NULL, updated_at!NULL; FK: source_id→official_source.id delete=SET NULL; index: sqlite_autoindex_language_rule_1 UNIQUE(id)
- `ocr_run` (0 rows): id!NULL*PK, target_type!NULL, target_id!NULL, status!NULL, language, error_message, created_at!NULL, updated_at!NULL; FK: none; index: ix_ocr_run_target_id(target_id), ix_ocr_run_target_type(target_type), sqlite_autoindex_ocr_run_1 UNIQUE(id)
- `official_source` (1 rows): id!NULL*PK, name!NULL, url!NULL, checked_at!NULL, created_at!NULL, updated_at!NULL; FK: none; index: sqlite_autoindex_official_source_1 UNIQUE(id)
- `peel_result` (0 rows): id!NULL*PK, analysis_id!NULL, paragraph_number!NULL, elements, rationale, guidance, created_at!NULL, updated_at!NULL; FK: analysis_id→analysis.id delete=CASCADE; index: sqlite_autoindex_peel_result_1 UNIQUE(id)
- `quote_card` (0 rows): id!NULL*PK, workspace_id!NULL, document_id, selected_text!NULL, quote_text!NULL, work, author, page, scene, characters, keywords, inquiry_question, verification_status!NULL, created_at!NULL, updated_at!NULL; FK: document_id→source_document.id delete=RESTRICT, workspace_id→workspace.id delete=NO ACTION; index: ix_quote_card_verification_status(verification_status), sqlite_autoindex_quote_card_1 UNIQUE(id)
- `quote_check_result` (0 rows): id!NULL*PK, analysis_id!NULL, student_quote!NULL, source_quote, status!NULL, confidence, differences, source_document_id, source_page, created_at!NULL, updated_at!NULL; FK: source_document_id→source_document.id delete=SET NULL, analysis_id→analysis.id delete=CASCADE; index: sqlite_autoindex_quote_check_result_1 UNIQUE(id)
- `quote_verification` (0 rows): id!NULL*PK, quote_card_id!NULL, status!NULL, difference, reason, created_at!NULL, updated_at!NULL; FK: quote_card_id→quote_card.id delete=CASCADE; index: sqlite_autoindex_quote_verification_1 UNIQUE(id)
- `revision` (0 rows): id!NULL*PK, writing_id!NULL, base_version_id!NULL, result_version_id!NULL, status!NULL, created_at!NULL, updated_at!NULL; FK: result_version_id→writing_version.id delete=NO ACTION, base_version_id→writing_version.id delete=NO ACTION, writing_id→writing.id delete=CASCADE; index: sqlite_autoindex_revision_1 UNIQUE(id)
- `revision_change` (0 rows): id!NULL*PK, revision_id!NULL, finding_id, before_text!NULL, after_text!NULL, start_offset!NULL, end_offset!NULL, undone!NULL, created_at!NULL, updated_at!NULL; FK: finding_id→analysis_finding.id delete=SET NULL, revision_id→revision.id delete=CASCADE; index: sqlite_autoindex_revision_change_1 UNIQUE(id)
- `rubric` (0 rows): id!NULL*PK, workspace_id!NULL, name!NULL, subject, activity, status!NULL, description, created_at!NULL, updated_at!NULL; FK: workspace_id→workspace.id delete=NO ACTION; index: ix_rubric_name(name), ix_rubric_status(status), sqlite_autoindex_rubric_1 UNIQUE(id)
- `rubric_file` (0 rows): id!NULL*PK, rubric_id!NULL, original_name!NULL, stored_name!NULL, mime_type!NULL, size!NULL, page_count!NULL, ocr_text, corrected_text, ocr_confidence, created_at!NULL, updated_at!NULL; FK: rubric_id→rubric.id delete=CASCADE; index: sqlite_autoindex_rubric_file_2 UNIQUE(stored_name), sqlite_autoindex_rubric_file_1 UNIQUE(id)
- `rubric_item` (0 rows): id!NULL*PK, rubric_id!NULL, name!NULL, description, check_type, source_location, position, created_at!NULL, updated_at!NULL; FK: rubric_id→rubric.id delete=CASCADE; index: sqlite_autoindex_rubric_item_1 UNIQUE(id)
- `rubric_result` (0 rows): id!NULL*PK, analysis_id!NULL, rubric_item_id, status!NULL, rationale, related_sentences, created_at!NULL, updated_at!NULL; FK: rubric_item_id→rubric_item.id delete=SET NULL, analysis_id→analysis.id delete=CASCADE; index: sqlite_autoindex_rubric_result_1 UNIQUE(id)
- `source_document` (0 rows): id!NULL*PK, workspace_id!NULL, title!NULL, author, edition, original_name!NULL, stored_name!NULL, mime_type!NULL, size!NULL, status!NULL, page_count!NULL, created_at!NULL, updated_at!NULL; FK: workspace_id→workspace.id delete=NO ACTION; index: ix_source_document_status(status), ix_source_document_title(title), ix_source_document_author(author), sqlite_autoindex_source_document_2 UNIQUE(stored_name), sqlite_autoindex_source_document_1 UNIQUE(id)
- `source_page` (0 rows): id!NULL*PK, document_id!NULL, page_number!NULL, original_text, corrected_text, confidence, extraction_method, created_at!NULL, updated_at!NULL; FK: document_id→source_document.id delete=CASCADE; index: ix_source_page_text(corrected_text), sqlite_autoindex_source_page_2 UNIQUE(document_id,page_number), sqlite_autoindex_source_page_1 UNIQUE(id)
- `spelling_result` (0 rows): id!NULL*PK, analysis_id!NULL, finding_id!NULL, auto_fixable!NULL, context_question, created_at!NULL, updated_at!NULL; FK: finding_id→analysis_finding.id delete=CASCADE, analysis_id→analysis.id delete=CASCADE; index: sqlite_autoindex_spelling_result_1 UNIQUE(id)
- `workspace` (1 rows): id!NULL*PK, user_name!NULL, name!NULL, created_at!NULL, updated_at!NULL; FK: none; index: sqlite_autoindex_workspace_1 UNIQUE(id)
- `workspace_setting` (17 rows): id!NULL*PK, workspace_id!NULL, key!NULL, value!NULL, created_at!NULL, updated_at!NULL; FK: workspace_id→workspace.id delete=CASCADE; index: sqlite_autoindex_workspace_setting_2 UNIQUE(workspace_id,key), sqlite_autoindex_workspace_setting_1 UNIQUE(id)
- `writing` (0 rows): id!NULL*PK, workspace_id!NULL, title, work, author, inquiry_question, subject, conditions, due_date, content, status!NULL, revision_number!NULL, original_version_id, created_at!NULL, updated_at!NULL; FK: workspace_id→workspace.id delete=NO ACTION; index: ix_writing_status(status), ix_writing_title(title), ix_writing_work(work), sqlite_autoindex_writing_1 UNIQUE(id)
- `writing_resource` (0 rows): id!NULL*PK, writing_id!NULL, resource_type!NULL, resource_id!NULL, created_at!NULL, updated_at!NULL; FK: writing_id→writing.id delete=CASCADE; index: sqlite_autoindex_writing_resource_2 UNIQUE(writing_id,resource_type,resource_id), sqlite_autoindex_writing_resource_1 UNIQUE(id)
- `writing_version` (0 rows): id!NULL*PK, writing_id!NULL, parent_id, name!NULL, content, version_number!NULL, change_count, created_at!NULL, updated_at!NULL; FK: parent_id→writing_version.id delete=NO ACTION, writing_id→writing.id delete=CASCADE; index: ix_writing_version_writing_id(writing_id), sqlite_autoindex_writing_version_1 UNIQUE(id)

### Final isolated development checkpoint (2026-10-10)

Formal 0002/0003 revisions and P03-P12 development G1-G4 verified; final regression 224 passed. Recovery preserves pre-existing files on UUID collision and selects only the latest explicitly linked document edition while retaining past analysis snapshots. Actual API browser evidence: 43 screenshots; UI fixture evidence: 100 screenshots, both themes, 320/390/820/1024/1440px, complete 30,000-code-point reconstruction. Operational database remains 0001_initial unchanged: new server correctly reports MIGRATION_REQUIRED. Operational migration, Google/HTTPS/session configuration, BAZE processing terms/limits, retention basis/scope/private-document and backup policy, and G5 final review remain pending. No operating data migration, retention date assignment, external transmission or deployment performed. Resume from backend-checkpoint.json and existing Runner receipts.
