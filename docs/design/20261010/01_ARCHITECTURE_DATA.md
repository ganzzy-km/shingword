# 글빛 2.0 아키텍처와 데이터 모델

## 확정 구성

프론트엔드는 React, Vite, TypeScript를 사용한다. 서버는 Flask와 Waitress를 사용한다. 영속 저장은 SQLite와 SQLAlchemy를 사용하고 스키마 이력은 Alembic으로 관리한다. 데이터 루트는 `C:\Users\USER\AppData\Local\GeulbitData`이다. Google OIDC를 사용자 인증의 목표로 삼는다.

기본 UI와 책장 UI는 같은 글, 버전, 분석 실행, 피드백과 API를 사용한다. 책의 페이지는 본문 위치 구간을 표현하는 화면 단위이다. 페이지별 글 저장이나 분석 복제를 만들지 않는다. 메뉴와 피드백 패널을 접어 본문 공간을 확보한다. 크기 변경과 테마 변경은 원문 위치를 기준으로 읽기 위치와 선택을 유지한다.

서버는 글의 불변 버전에 분석 실행을 연결한다. 로컬 Kiwi와 규범 ruleset이 분석을 수행한다. AI는 질문 기능에만 사용한다. 자료실은 Work→Document→Revision으로 구성한다. PDF 기능은 이 버전과 자료 경계를 따른다. 7일 보존의 세부 정책은 미결이다.

## 구성 요소와 책임

| 구성 요소 | 책임 | 경계 |
| --- | --- | --- |
| React 화면 | 편집, 읽기, 두 테마, 위치 이동, 상태 표시 | 분석 판정과 별도 원본 저장 엔진을 만들지 않음 |
| Flask API | 인증과 권한 검사, 입력 검증, 버전과 작업 연결 | 화면이 보낸 owner ID를 권한 증명으로 사용하지 않음 |
| 분석 서비스 | 입력 버전을 고정하고 기존 작업 흐름에서 실행 | 실행 중 최신 초안으로 입력을 바꾸지 않음 |
| Kiwi와 ruleset | 언어 분석과 근거 있는 규범 후보 생성 | 교사 점수나 논리적 진실을 확정하지 않음 |
| SQLite 저장소 | 버전과 실행 및 자료 관계 저장 | 데이터 루트 검증 실패 시 임의 위치로 fallback하지 않음 |
| 자료실 | 작품, 판본·문서, 수정 이력과 인용 출처 연결 | 서로 다른 판본과 Revision을 혼합하지 않음 |
| AI 질문 경계 | 명시적 질문에 대한 응답 | 로컬 분석, 자동 첨삭, 자동 평가에 AI를 연결하지 않음 |
| PDF 경계 | 버전에 연결된 출력과 가져오기 검증 | PDF에서 기존 분석·버전 신뢰성을 임의 복원하지 않음 |

루프백 바인딩과 상대 `/api` 경로는 기존 로컬 구조의 관찰이다. 학교 접속 방식, 도메인, 배포 토폴로지, OIDC redirect URI는 별도 미결 사항이다. 이 설계는 터널 개설이나 공개 배포를 지시하지 않는다.

## 논리 데이터 관계

아래 필드는 목표 불변 조건을 설명하기 위한 논리 필드 제안이다. 확정된 SQL DDL, 물리 테이블명, JSON 필드명이 아니다. essay_version과 analysis_runs는 사용자가 지정한 계약 개념이다.

| 엔터티 | 논리 필드 제안 | 관계와 불변 조건 |
| --- | --- | --- |
| User | id, oidc_issuer, oidc_subject | Google 인증 주체. 이메일만으로 계정 동일성을 결정하지 않음 |
| Essay | id, owner_id, draft, current_version_id | 편집 중 초안과 분석 입력 버전을 구분 |
| essay_version | id, essay_id, parent_id, text, created_at | 확정 후 본문 불변. 수정은 새 버전 생성 |
| analysis_runs | id, essay_version_id, status, engine_version, ruleset_version | 하나의 버전을 분석. 재분석은 별도 실행 |
| Finding | id, run_id, kind, anchor, rationale, rule_ref | 분석 실행과 근거 구간을 함께 참조 |
| RoleCandidate | run_id, sentence_anchor, role, signals | 주장과 근거 등의 후보. 확률 보정 여부는 미결 |
| RelationSignal | run_id, source_candidate, target_candidate, signals | 연결 후보와 관찰 신호. 참·거짓 증명 아님 |
| Work | id, title, author | 작품이라는 개념 |
| Document | id, work_id, edition_metadata | 특정 판본이나 자료 문서 |
| DocumentRevision | id, document_id, parent_id, text_or_file_ref | 해당 문서의 특정 내용 이력. 선택 Revision 고정 필요 |
| QuoteReference | revision_id, source_anchor, quote | 인용 출처를 특정 자료 내용에 연결 |
| EssayEditHistory | essay_id, base_version_id, result_version_id | 기존 글 수정 Revision과 자료 Revision의 의미를 분리 |

Work 1→N Document 1→N DocumentRevision 관계를 따른다. Essay 1→N essay_version 1→N analysis_runs 관계를 따른다. Finding과 후보 및 관계 신호는 analysis_runs에 종속한다. 자료가 필요한 분석은 선택한 DocumentRevision을 고정해 출처를 재현할 수 있어야 한다.

사용자 간 자료 접근 모드, 공개 자료 권한, Work 중복 기준, 판본 일치 기준, Revision의 물리 불변성·파일 해시 정책은 미결이다. 소유자나 접근 권한 없는 데이터가 응답에 섞이지 않아야 한다는 보안 조건은 필요하지만 구체적인 권한 역할표는 새로 확정하지 않는다.

## 기존 모델과의 차이

로컬 `backend/app/models.py`의 Writing은 변경 가능한 content를 가진다. WritingVersion은 글 이력을 보관한다. Analysis는 writing_id를 참조하지만 분석 입력 버전 FK가 없다. AnalysisJob은 Analysis에 연결된 실행 상태를 갖는다. 이 구조를 확인하지 않고 별도 테이블 묶음을 병렬로 구현하지 않는다.

기존 SourceDocument와 SourcePage는 자료 구조의 출발점이다. QuoteCard도 재사용 후보이다. 기존 Revision은 글 수정 이력이므로 DocumentRevision과 구별해야 한다. 확정된 마이그레이션 매핑이 없으므로 명칭 교체나 기존 데이터의 자동 승격은 하지 않는다. 출처를 증명할 수 없는 과거 분석은 위치 이동을 비활성화한다.

## 버전과 위치의 정합성

분석 입력은 불변 essay_version의 정확한 문자열이다. Finding의 앵커는 그 버전의 Unicode code point 좌표를 기준으로 한다. 버전 ID가 다르거나 원문 구간을 검증할 수 없으면 현재 글에 직접 적용하지 않는다. 재분석과 수정 적용은 원래 버전을 갱신하지 않고 새 실행 또는 새 버전을 만든다.

제안으로 버전 생성과 실행 등록을 트랜잭션으로 묶고 현재 버전 비교를 통해 동시 저장 충돌을 거부한다. 작업 스케줄링 실패 후 복구 방식, idempotency 키, 취소 상태 전이는 확정 API 계약이 필요하다. 기존 작업 서비스에 연결하며 새로운 Runner나 중복 작업 엔진을 만들지 않는다.

NFC 정규화와 CRLF→LF 정책은 기존 체크포인트에서도 미결이다. 저장 전 정규화 여부, 해시 기준 문자열, Kiwi 입력과 원문 사이의 변환 지도를 확정해야 한다. 정규화한 문자열의 위치를 원문 위치로 바로 쓰지 않는다.

## 저장과 인증 및 외부 처리

Config는 GEULBIT_DATA_ROOT와 GEULBIT_VOLUME_ID를 읽고 운영 경로를 검증 후 바인딩하는 후보 구조이다. 이번 목표 경로를 설정의 기준으로 사용하되 하위 폴더명, 볼륨 고정 방식, 백업·secret 위치는 기존 storage 계약과 대조 후 확정한다. 기존 경로를 자동 이동하거나 운영 DB를 열어 검증하지 않는다.

최종 조회의 최신 로컬 체크포인트는 지정 C: root가 `C:\Users\USER\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\GeulbitData`로 resolved됐다고 보고한다. 현재 지정 경로 check는 DATA_ROOT_REDIRECTED이며 승인된 물리 경로 충족이 아니다. 이 내용은 외부 작업의 기록 관찰이며 본 설계 작업에서 CLI나 DB를 실행한 결과가 아니다. 지정 경로의 문자열 일치뿐 아니라 실제 물리 위치를 확인하는 acceptance가 필요하다.

OIDC 세부 구현은 제안으로 state와 nonce 검증, issuer와 audience 검증, 서버 세션 관리, 변경 요청의 CSRF 보호를 포함한다. 계정 가입 허용 범위, 세션 수명, logout, 계정 연결, PKCE 적용 방식은 미결이다. 실제 Google 인증 없이 Mock 계약을 먼저 검증할 수 있으나 이를 실인증 통합 완료라고 표시하지 않는다.

AI 제공자, 모델, 전송 항목, 동의 방식, 질문과 응답 보존 정책은 미결이다. 질문 전용이라는 확정 경계 밖에 AI를 사용하지 않는다. 로컬 규범 분석에 외부 사전 호출을 필수로 연결하지 않는다. 구형 README의 선택적 사전 API 기능을 2.0 기본 분석 경로로 자동 채택하지 않는다.

## PDF와 보존 정책

PDF 출력이 어떤 버전과 분석 실행을 포함했는지 식별할 수 있어야 한다. 에세이 PDF 가져오기는 기존 버전의 복원이 보장되지 않으며 추출 내용을 확인한 뒤 새 초안 또는 새 버전으로 처리하는 방향은 제안이다. 출력 형식, 서버 생성 방식, 가져오기 메타데이터, OCR 포함 범위는 미결이다. 기존 브라우저 인쇄와 작품 PDF 추출의 존재만으로 서버 보고서·에세이 복원이 완료됐다고 판단하지 않는다.

7일 보존에서 시작점, 대상 데이터, 유예·복구, 삭제 시점, 분석 중 삭제, 재시도, 백업 및 로그, 계정 삭제, 공개 자료와 인용 의존성 처리는 모두 미결이다. created_at에 7일을 더한 자동 삭제나 복구 가능한 휴지통을 임의 구현하지 않는다. 확정 전에는 보존 관련 acceptance를 대기 상태로 유지한다.

