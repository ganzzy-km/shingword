# 글빛 2.0 API 계약과 완료 조건

## 기존 API 관찰

아래는 로컬 route와 프론트에서 확인한 경로이다. Google OIDC와 불변 버전이 완료된 2.0 API 계약은 아니다. 실제 사용자 API는 인증 미구현 차단 상태로 보존한다.

| 기존 경로 | 관찰한 계약 | 2.0 차이 |
| --- | --- | --- |
| POST /api/writings | 글과 초기 WritingVersion 생성. 201 응답 | 사용자 소유권과 버전 불변성 계약 필요 |
| PATCH /api/writings/{id} | 변경 가능한 글 갱신 | 초안 저장과 불변 버전 생성 경계 필요 |
| POST /api/writings/{id}/autosave | 자동 저장과 revision_number 사용 | 동시 편집 충돌과 권한 계약 필요 |
| POST /api/writings/{id}/versions | 글 버전 생성. 201 응답 | 목표 essay_version과 매핑 필요 |
| GET /api/writings/{id}/versions | 버전 목록 | 권한과 원문 불변 조회 필요 |
| POST /api/analyses | writingId와 옵션 사용. analysisId, jobId, status 반환. 202 응답 | 입력 버전 고정과 응답 식별자 추가 필요 |
| GET /api/analysis-jobs/{id} | 진행률과 상태 조회 | 작업 상태표와 접근 권한 필요 |
| POST /api/analysis-jobs/{id}/cancel | cancel_requested. 종료 작업은 409 INVALID_STATE | 취소 확정 시점과 경합 계약 필요 |
| GET /api/analyses/{id} | 기존 결과 조회 | 분석 입력 버전과 앵커 연결 필요 |
| PATCH /api/analyses/{id}/sentences/{sentence_id} | 자동 역할과 사용자 역할 분리 | 사용자 판단이 원래 자동 결과를 덮어쓰지 않는 계약 필요 |
| POST /api/revisions | 글 수정 적용과 새 버전 | 자료 Revision과 이름 충돌 및 오래된 분석 적용 방지 필요 |

기존 프론트는 상대 `/api` 경로와 `{data: ...}` 성공 envelope를 사용하고 오류는 `{error: {code, message, fields}}` 형태를 읽는다. envelope 변경이 필요한 경우 기존 사용처를 확인한다. 위 표 밖의 API는 필요한 작업에서만 symbol과 route를 확인한다.

## 목표 의미 계약

확정 사항은 불변 입력 버전, 분석 실행 연결, code point 앵커, 두 UI의 공통 API, OIDC, 자료 계층, 질문 전용 AI이다. 아래 세부 필드와 실패 코드는 제안이다. 미결 값이 있는 영역은 확정 OpenAPI나 실행용 JSON Schema로 위장하지 않는다.

| 작업 | 요청의 의미 | 응답의 의미 | 실패와 일관성 조건 |
| --- | --- | --- | --- |
| 글 버전 생성 | 접근 가능한 글의 확인된 초안과 기준 버전 | 새 불변 버전 식별자와 본문 | 동시 저장 충돌에서 과거 버전 덮어쓰기 없음 |
| 분석 실행 생성 | essay_version 식별자와 분석 옵션 및 선택 자료 Revision | 실행과 작업 식별자 및 고정 입력 버전 | 없는 버전이나 타인 버전 거부. 실패 시 성공으로 오인할 실행 없음 |
| 실행 조회 | 접근 가능한 run 식별자 | 상태, 입력 버전, 결과와 분석 구성 식별자 | 타인 원문과 결과 노출 없음 |
| 구절 이동 | 결과의 입력 버전과 code point 앵커 | 검증된 구간 선택 | 버전 불일치와 quote 불일치에서 이동 비활성화 |
| 수정 적용 | 기준 버전과 선택 finding | 새 버전 및 적용 이력 | 인용 보호, 오래된 결과, 겹친 수정 충돌 검사 |
| 자료 선택 | Work와 Document의 특정 Revision | 해당 내용과 출처 식별자 | 다른 판본이나 Revision을 몰래 대체하지 않음 |
| AI 질문 | 사용자가 요청한 질문과 허용된 문맥 | 질문 응답과 처리 상태 | 분석·평가 자동 실행으로 확장하지 않음 |
| PDF 출력 | 선택 버전과 필요한 분석 실행 | 해당 버전의 출력 파일 | 본문 누락이나 다른 버전 혼입 없음 |
| PDF 가져오기 | 파일과 검증된 추출 내용 | 확인 가능한 새 초안 또는 버전이라는 제안 | 원래 버전이나 분석 복원으로 임의 인증하지 않음 |

앵커의 제안 필드는 version_id, start_cp, end_cp, quote이다. 분석 실행의 제안 필드는 run_id, essay_version_id, status, engine_version, ruleset_version이다. DB 이름과 camelCase/snake_case의 wire 매핑은 기존 계약 확인 후 확정한다. 새 `/api/essays`나 `/api/analysis-runs` 경로를 이 문서만으로 생성하지 않는다.

제안 오류 범주는 인증 누락, 권한 부족, 입력 오류, 버전 충돌, 앵커 무효, 작업 종료, 분석 불가, 외부 서비스 실패이다. HTTP 상태 코드와 machine code의 최종 대응표는 미결이다. 입력 오류, 권한 오류와 서버 오류를 성공 envelope로 숨기지 않는다. OIDC callback, AI 질문, 서버 PDF, 자료 계층의 새 경로와 요청 크기 상한은 미결이다.

작업 상태는 queued, running, cancel_requested, cancelled, completed, failed를 구분하는 방향이 제안이다. 완료와 취소가 경합할 때의 최종 상태, 재시도 시 새 run 생성 여부, 중복 요청 처리와 부분 결과 공개는 아직 확정하지 않는다. 임의 상태 전이로 운영 계약을 만들지 않는다.

## Acceptance criteria

이 기준은 목표를 검증하는 항목이다. 실행한 테스트 결과가 아니다. API 세부 정책이 미결인 항목은 PASS 대신 PENDING으로 둔다.

| ID | 정상 조건 | 실패 또는 경계 조건 | 필요한 검증 |
| --- | --- | --- | --- |
| AC01 구성 | 지정 스택과 C: 데이터 루트 사용 | 저장소 검증 실패에서 다른 위치로 자동 생성 없음 | 격리 storage fixture. 실제 운영 DB 사용 금지 |
| AC02 불변 버전 | A 버전 분석 중 B를 편집해도 결과는 A를 참조 | A 본문 변경 없음. 저장 실패에서 부분 상태 없음 | 모델·분석 서비스 targeted test와 동시 편집 사례 |
| AC03 실행 연결 | 재분석 결과가 구별되고 입력 버전과 규칙이 식별됨 | 과거 결과가 최신 초안으로 재귀속되지 않음 | run 조회·재시도·기준 버전 회귀 |
| AC04 Unicode | 한글, emoji, 결합 문자, CRLF와 반복 구절의 정확한 선택 | 범위 오류, quote 불일치, 다른 버전에서 이동·적용 차단 | 엔진 앵커와 프론트 변환 test. 정규화 정책 부분 PENDING |
| AC05 규범 분석 | 로컬 Kiwi와 ruleset으로 근거 있는 후보 반환 | Kiwi 실패와 미등록어를 성공 판정이나 오타로 위장하지 않음. 인용 내부 자동 적용 차단 | test_language_analysis와 인용 보호 targeted test |
| AC06 역할과 관계 | 주장·근거 후보 및 관계 신호의 이유 표시 | 근거 부족은 보류. 공유 단어만으로 논리적 정답 확정 없음 | synthetic 역할·관계 사례. 수치 기준 PENDING |
| AC07 공통 UI | 같은 글과 실행이 두 테마에서 같은 내용과 피드백 제공 | 테마 전환·메뉴 접기·리사이즈에서 선택과 원문 위치 유지 | book-layout과 관련 browser 검증 |
| AC08 책장 보존 | 10,000과 30,000 code point 페이지 결합이 원문과 일치 | 마지막 문단 누락, 중복 구절 오이동, 가로 넘침 없음 | 1440, 1024, 820, 390, 320px의 가상 글 검증 |
| AC09 OIDC와 권한 | 검증된 인증 주체만 자신의 허용 자료에 접근 | 잘못된 issuer, audience, state, nonce, 타인 ID 거부 | Mock 인증·권한 test. 실인증 통합 PENDING |
| AC10 자료실 | Work→Document→Revision과 선택 판본 출처 보존 | 다른 판본·수정본으로 인용 자동 치환 없음 | 자료 모델과 인용 회귀. 접근 모드 PENDING |
| AC11 AI 경계 | 질문 요청에서만 AI 동작 | 일반 분석·자동 저장·피드백에 AI 호출 0. 원문·토큰 로그 없음 | 외부 호출 Mock 횟수와 문맥 검사. 전송·보존 정책 PENDING |
| AC12 PDF | 선택 버전 전체와 마지막 문단이 출력에 포함 | 손상·암호화·텍스트 없는 PDF를 정상 복원으로 위장하지 않음 | 가상 PDF 생성·추출·렌더 확인. 서버·가져오기 계약 PENDING |
| AC13 취소와 실패 | 확정 상태표에 따라 종료 상태 조회 | 재시도·중복·취소 경합에서 고아 작업·이중 성공 없음 | 작은 서비스 경합 test. 상태표 확정 전 PENDING |
| AC14 보존 | 확정된 7일 시작점·대상·삭제 정책에 일치 | 백업·계정·공개 자료·진행 작업의 명세 없는 삭제 없음 | 정책 확정 전 전체 PENDING. 자동 삭제 테스트 실행 금지 |
| AC15 성능 | 1만·3만 code point와 약 5분 안정성의 시간·메모리 측정 | 유실과 브라우저 예외 없음. 부하 실패는 성공으로 표시하지 않음 | 가상 데이터 시뮬레이션. 지연·메모리 합격값 PENDING |

## 검증 범위와 완료 판정

관련 변경에서만 기존 `backend/tests/test_storage.py`, `test_writing_analysis.py`, `test_language_analysis.py`, `test_core_resources.py`의 필요한 test ID를 검색한다. 신규 목표 계약은 기존 테스트로 충족되는지 먼저 확인하고 빈틈에만 테스트를 추가한다. `scripts/book-layout.test.mjs`와 UI 검증은 화면·앵커 작업에만 사용한다. OIDC와 자료 Revision 및 run 계약의 신규 테스트는 아직 파일이 있다고 가정하지 않는다.

변경 중에는 가장 작은 실패 테스트와 관련 suite만 실행한다. 최종 후보나 광범위한 변경에만 전체 typecheck, unit, build와 필요한 E2E를 실행한다. 30분 soak는 기본값이 아니다. 성공 기록은 명령, 작업 경로, 종료 코드, 통과 수와 핵심 수치만 남긴다. 원문·토큰·대형 stdout은 기록하지 않는다.

로컬 ACCEPTANCE의 G1 요구사항 대응, G2 실제 테스트, G3 불변 조건, G4 범위, G5 독립 검증은 기존 자동화 계약이다. 현재 Queue는 실행 금지 초안이며 이 묶음은 Queue 승인을 대신하지 않는다. 인증·권한·오프셋·migration·삭제·AI 개인정보 경계의 Claude 검토 요구는 기존 문서 관찰이다. 최신 절은 사용자 지시에 따라 G5 DEFERRED라고 기록한다. 이를 보존하고 검토가 없으면 해당 Gate를 통과했다고 보고하지 않는다. 과거 절과 최신 절의 충돌을 이 패키지에서 원본 수정으로 해결하지 않는다.

문서 패키지 완료와 제품 구현 완료를 구분한다. 이 패키지의 완료 조건은 목표와 기존 상태 구분, 충돌 기록, 미결 표시, 원본 보존, 다운로드 가능한 파일 제공이다. 제품 통합 완료는 관련 정책 확정과 실제 검증 증거가 필요하며 이 작업에서 선언하지 않는다.

