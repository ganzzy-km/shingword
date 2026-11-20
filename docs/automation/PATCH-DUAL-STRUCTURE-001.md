# PATCH-DUAL-STRUCTURE-001 Handoff

## STATUS

| 항목 | 상태 |
| --- | --- |
| STACK_QUOTE_DETECTION | PASS |
| DUAL_ENGINE_IMPLEMENTATION | PASS |
| AI_API_LIVE_VERIFIED | PASS_STAGING_LIVE |
| COMPARISON_UI | PASS |
| DATA_AND_PERMISSION_SAFETY | PASS_STAGING |
| ACCURACY_CERTIFICATION | BLOCKED_DATA |
| STAGING_VERIFIED | PASS_LIVE_SYNTHETIC |
| OPERATING_APPLIED | NOT_APPLIED |

후보는 `PATCH-DUAL-STRUCTURE-001` 작업 트리의 `7870e70` 기반 변경이다. `master`와 커밋·푸시·병합을 분리했다. 운영 기준은 글빛 1.2.0 및 `0005_writing_tools`다. 기존 S4 R2 설정은 `DISABLED`다. `PATCH-STABILITY-120-001`의 원본과 비교해 저장 완료 판정에 제목·작품·탐구 질문·본문을 모두 포함하는 수정을 확인했다.

## CHANGED

- 실제 BAZE 응답에서 원문을 바꿔 쓴 구절이 거부되는 사례를 발견했다. 프롬프트 2는 문장 ID에 기반한 전체 문장 범위를 우선하고 꼭 필요한 부분만 원문 그대로 복사하도록 안내한다. 원문 대조 규칙은 동일하다. BAZE가 응답 본문에 제공하는 실제 차감값도 저장하도록 추가했다.

- `extract_quotations()`를 단일 순회 스택으로 보완했다. 닫힌 범위는 기존 S4 인용 계약으로 제공한다. 확인이 필요한 부호는 위치만 보존하고 미완성 내용의 범위를 확정하지 않는다.
- `0006_dual_structure`는 `essay_structure_maps`와 `essay_structure_runs`를 추가한다. 기존 `0001`–`0005` 및 S4의 판정 코드와 저장 결과는 그대로 사용한다. 판본별 원문 맵·인용 위치와 AI 결과·실행 상태·사용량 기록을 구분한다. S4 공통 DTO는 읽을 때 변환한다.
- S4 기본 보기, AI 구조 분석, 비교를 기존 글 화면에 연결했다. 비교 화면은 역할·구간·관계 차이, 1:N/N:1과 단독 탐지를 표시한다. 인용 강조는 같은 원문 렌더링의 별도 범위다. 독립 AI 실행으로 새 판본을 준비할 수 있다.
- 변경 파일과 빌드, 검증 자료의 SHA-256은 `artifacts/dual-structure/evidence/manifest.json`에 있다. 인계 ZIP은 변경 소스와 검증 요약을 포함한다. STAGING 합성 DB·세션·키는 인계에서 제외했다.

## RULES

- 위치는 저장 판본의 Unicode 코드포인트 반개구간 `[start, end)`이다. React는 `Array.from`으로 범위를 분할하고 에디터 선택은 기존 UTF-16 변환을 쓴다. AI 구절은 문장 ID와 정확한 문자열의 1부터 시작하는 출현 순서로 확인한다.
- 전송은 사용자 요청, 정책 동의, 전송 문장 미리보기 확인을 거친다. BAZE 요청에는 문장 ID와 포함된 원문 문장, 고정 구조 지침과 JSON Schema만 있다. 에세이·사용자 메타데이터와 출처 원문은 포함하지 않는다. `MATCH_ONLY` 및 권리 미확인 자료와 연결된 글은 차단한다. 전체 원문에서 감지된 식별 정보와 겹치는 문장은 제외한다. 사용자가 미리보기에서 추가 문장을 제외할 수 있다.
- `BAZE_API_KEY`는 기존 서버 DPAPI에 둔다. `GEULBIT_STRUCTURE_AI_CONFIG_FILE`은 별도 승인된 서버 프로필의 비밀값 없는 절대경로 JSON을 읽는다. 필요한 상위 항목은 `AI_STRUCTURE_ENABLED`, `EXTERNAL_AI_TERMS_APPROVED`, `BAZE_STRUCTURE_GATEWAY`, `AI_STRUCTURE_POLICY_VERSION`, `AI_STRUCTURE_CALL_COST_UNITS`, `AI_LIMITS`다. Gateway 설정은 기존 승인 필드에 `structuredOutputConfirmed`를 추가한다. 실제 계정의 모델 ID, 처리 약관, 요금과 요청당 최대 과금 단위를 확인한 뒤 설정한다. 운영 프로필이 전달하는 외부 AI 금지 설정이 우선한다. [BAZE 구조화 출력](https://docs.mindlogic.ai/docs/mindlogic-prod/api-gateway/reference/chat-completions) · [BAZE 이용량](https://docs.mindlogic.ai/docs/khu/api-gateway/reference/usage) · [BAZE 개인정보처리방침](https://baze.co/legal/privacy/)
- 설정 상한은 판본 6,000 코드포인트, 문장 256개, 응답 65,536바이트, 출력 4,096토큰, 모델 요청 30초, 동시 AI 구조 작업 2개다. 작업 상태의 대기·실행 기한은 최대 40초다. HTTP 요청 본문은 16KiB로 제한한다. 자동 재시도는 0회다. SQLite에서 사용자·전체 예산을 함께 예약하며 중복·캐시 조회에는 외부 호출이나 새 예약이 없다. 제공자가 보고한 토큰과 크레딧을 저장하며 값이 없으면 요청당 예약 상한만 남는다. 복원 검역에서는 구조 전송 동의를 철회하고 최신 예산 기록을 유지한다.

### 적용과 복귀

1. 별도 운영 적용 승인 시 현재 코드·빌드 및 `0005` 암호화 백업의 SHA와 격리 복원 증거를 고정한다. 배포에는 승인된 제품 소스와 빌드만 사용한다. 기존 `storage_cli.py migrate`의 V2.1 경로는 이번 마이그레이션에 사용하지 않는다.
2. 먼저 `backend/v2_tests/staging_dual_structure.py init --root <새 합성 STAGING 사본> --adapter <기존 staging_service.py>`로 온라인 복사, `0005→0006→0005→0006`, 기존 행/파일 해시, 무결성/FK를 검증한다. 승인된 운영 적용이 필요해지면 공식 중지·스토리지 단독 쓰기 리스·검증 백업·0005 입력 확인을 거치는 전용 적용 절차에서 `0006_dual_structure`를 실행하고, 스키마·릴리스 매니페스트와 0006 백업·복원을 확인한 뒤 코드와 빌드를 연결한다.
3. 적용 뒤 장애 시 먼저 외부 AI 실행을 비활성화하고 0006과 새 결과를 보존한다. 신규 테이블이 비어 있는 격리 복사본에서 `downgrade`를 검증했다. 결과가 있는 복사본에서는 `downgrade`가 거부되었고 기존 데이터가 일치했다. 구 버전 복귀가 필요하면 0005 검증 백업과 0006 이후 변경을 따로 보존한 채 별도 격리 복구·승인을 받는다. 운영 DB 덮어쓰기나 새 결과의 폐기를 자동화하지 않았다.

## TESTED

- 로컬 시험판은 Google OAuth 미연결 상태를 표시하고 로그인 링크를 숨긴다. 연결된 서버 응답을 모의했을 때는 기존 로그인 링크를 표시했다. 브라우저에서 조회 실패 후 다시 확인과 시험 계정 홈 접속을 검사했다. 인증 API 테스트 14건, TypeScript 검사 및 Vite 빌드가 통과했다. 실제 Google 로그인 검증에는 별도로 등록된 STAGING OAuth 클라이언트와 일치하는 HTTPS 콜백 주소가 필요하다.

- 2026-11-20 외부 호출 승인으로 합성 STAGING 사본에서 BAZE Haiku 4.5를 검증했다. 최초 구조화 응답은 원문 대조에서 거부됐다. 프롬프트 수정 후 실제 응답 6건을 저장하고 Chrome 비교·구간 표시·다른 계정 조회 차단·중복 요청·판본 변경·서버 재시작 후 재조회·예산 초과·동의 철회를 확인했다. BAZE 일별 사용량은 7건에 12.58크레딧이었다. 개별 응답에는 차감 크레딧 필드가 없었으며 토큰 사용량은 저장됐다. 검증 기록은 `artifacts/dual-structure/live-20261120/verification-summary.json`에 있다.
- 합성 평가 4건의 원문 구간 검증은 7개 모두 통과했다. 정확한 구간 일치 기준의 F1은 주장 0.571, 근거 0.333, 관계 0.000이었다.
- 이번 변경 뒤 관련 pytest 159건, 프런트엔드 테스트 3개, TypeScript 검사가 통과했다. 브라우저가 사용한 빌드 파일 16개의 SHA-256이 기존 빌드와 일치했다.

- 후속 수정에서 과거 `API_DISPLAY_TEST_AMENDMENT/5`에 맞춰 S4 관계 표시 테스트를 복구했다. 기존 단문·30,000 코드포인트 입력은 각각 점수 4·6의 `REQUIRES_REVIEW` 관계와 화살표 0개를 검증한다. 승인된 양성 입력은 `SUFFICIENT_SIGNALS` 관계와 정확한 화살표 1개, 원문 위치, 소유권과 이전 판본의 불변성을 검증한다. 관련 pytest 52건이 통과했다. 실제 Kiwi 결과를 사용한 Chrome 스모크 테스트도 두 테마와 세 화면 폭에서 총 6개 통과했다. 승인된 화살표의 이동과 검토 관계의 화살표 미표시를 확인했다.
- 실제 Flask·Waitress·HTTPS·Chrome·SQLite의 합성 STAGING 사본에서 작성, 판본 고정, S4, 인용 표시, 동의, 비동기 AI, 비교, 저장·재조회, 편집 후 `STALE`, 새 판본 AI 실행, 프로세스 재시작과 재조회 확인. AI는 동일한 BAZE 전송 어댑터에 로컬 모의 HTTP 응답을 연결했다.
- 1440px·390px에서 두 테마, 읽기와 집중 편집, Escape, 원문 중복과 인용/근거 겹침을 검사했다. TypeScript `--noEmit` 및 Vite production build가 성공했다. 관련 pytest 144건과 Node 3개 파일이 통과했다. STAGING의 브라우저·HTTP 시나리오 10개가 통과했다.
- 기존 41개 테이블, 1,888개 행, 파일 470개가 복사·마이그레이션 중 동일했다. 무결성 `ok`, FK 위반 0건. 기존 보호 28개, 고정 39개, Runner 2개의 해시를 확인했다. 운영 스키마 `0005_writing_tools`를 읽기 전용으로 확인했다.
- 실제 로컬 고정밀 OCR `/6` 처리·원문 확정·재조회와 텍스트 PDF 직접 추출을 확인했다. 저장된 일반 OCR 작업을 다시 열었고, 새 일반 OCR 요청이 `OCR_MODE_RETIRED`로 거부되는 1.2.0 기준을 재현했다.
- 합성 평가 예제 4개로 평가기를 자체 점검했다. `backend/validation/evaluate_dual_structure.py`는 별도 정답에 대해 주장·근거의 precision/recall/F1, 방향·유형을 포함한 관계 점수, 응답·원문 구간 검증 통과율과 허위 후보 비율을 계산한다.

## RISKS

- 사람 검수 데이터가 없어 정확도를 인증하지 않았다. 자동 식별 정보 탐지는 이름·간접 식별 정보·연결 없이 붙여넣은 보호 구절을 완전히 판별할 수 없다. 전송 미리보기에서 문장 단위로 제외할 수 있다.
- 초기 작업 중 운영 소스와 같은 경로에 후보 파일이 쓰였다. 곧바로 후보를 분리하고 기준 바이트를 복원했다. 복원 뒤 운영 배포 매니페스트의 제품·빌드 파일 해시를 확인했다. 이 작업에서 운영 재시작·DB 마이그레이션·배포를 실행한 기록은 없다.
