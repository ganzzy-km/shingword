# 글빛 백엔드 Acceptance 준비

## 2026-10-10 새 Data Root 교차 검증 완료 (최신)
- 승인·실제 경로 모두 `C:\Users\USER\GeulbitData`. Healthy/Fixed/NTFS, 초기화 전 디렉터리·DB 없음, 여유 1,258,151,075,840 bytes. Codex와 WMI로 별도 실행한 일반 Windows PowerShell이 같은 USER 계정으로 임시 파일을 양방향 읽기·쓰기했다. 두 환경의 resolve 결과가 동일하며 임시 파일·빈 검사 디렉터리를 정리한 후에만 User 환경변수 기본값을 변경하고 기존 CLI init을 실행했다.
- 초기 migration 0001_initial 성공. Codex 및 일반 Windows PowerShell CLI check 모두 exit 0/PASS. 무결성 ok/FK=1/WAL/timeout=5000ms, 재시작, 동일 root 내 SQLite backup 및 임시 DB 복원/내용 일치 확인. 운영 DB로 복원하거나 LocalCache 데이터를 병합·이동하지 않았다. 백업 자동 보존/삭제 규칙은 도입하지 않았다.
- targeted 21 passed, exit 0, 7.02s. 격리 SQLite 40 writer/40 writes/2.0582s/lost updates 0. 초기화 진행 중 조기 검증은 EXPLICIT_INITIALIZATION_REQUIRED로 차단되고 완료 후 재검증 성공. UI/P02 및 기존 migration 23개 보호 파일 hash 유지; LocalCache DB/백업도 hash 유지.
- Queue allowedPaths는 검증 스크립트와 기존 준비 계약만 추가, maxChangedFiles=10 유지. operational Data Root를 소스 수정 허용 경로로 추가하지 않았다. 기존 Runner preflight 실제 실행은 exit 1/BLOCKED: Unconfigured or invalid baseline. Git HEAD가 없고 pytest/SQLite 연결도 미확정이므로 configured:false, completed:[]를 유지한다. G1~G3 로컬 검증 성공, G4 공식 Scope receipt 미확정, G5 DEFERRED. 전체 P01 PASS나 의존 Phase 실행은 하지 않는다.
- 상세 교차 프로세스 증거·실제 경로·명령·수치는 기존 backend-checkpoint.json의 dataRootResolution에 있다. 아래 AppData/E: 차단 기록은 이전 시도의 보존 이력이다.

## 2026-10-10 C: 저장소 재개 결과 (최신)
사용자가 승인한 운영 Data Root는 `C:\Users\USER\AppData\Local\GeulbitData`이다. E: 조건은 이 최신 승인으로 대체하며 E: 자료는 변경하지 않는다. G5는 사용자 지시대로 **DEFERRED**이며 전체 P01 PASS receipt를 발행하지 않는다.

C:는 Healthy/NTFS/Fixed, 지정 root는 초기화 전 없었다. 기존 명시적 CLI init/migration 및 SQLite/FK/WAL/재시작/동일 저장소 백업·격리 복원은 성공했으나 Python의 실제 resolved root가 Codex 패키지 `LocalCache\Local\GeulbitData`인 것이 발견되었다. 승인된 물리 위치의 성공으로 인정하지 않는다. 생성 DB·백업은 삭제하지 않고 보존했다. `validate_volume`에 리디렉션 차단을 추가하여 현재 지정 경로 CLI check는 exit 1 / DATA_ROOT_REDIRECTED다.

최종 P01: G1 BLOCKED, G2/G3/G4는 로컬 증거만 확인(각각 Runner binding·독립 검토·baseline/scope receipt 미확정), G5 DEFERRED. targeted 21 passed / regression 76 passed. 정상·실패·경계 조건은 완화하지 않았다. P02 독립 분석 컴포넌트 감사 6개 조건 통과(Kiwi·결정성·span·빈 입력·Flask/DB 미사용·네트워크 차단). 순수 분석 작업은 독립 진행 가능하지만 정규화·스키마·생산용 패키지 계약 미완성으로 P02 PASS가 아니다. 재개 근거와 실제 경로·명령·수치는 기존 backend-checkpoint.json의 resumeAttempt에 기록했다. 다음 검증은 Codex 패키지 밖 Windows 터미널에서 실제 승인 경로를 확인해야 한다. 백업 자동 보존/삭제 정책은 미확정이며 도입하지 않았다.

상태: **P01 BLOCKED / NOT_CONFIGURED**. 2026-10-10 사용자 지시로 UI 완료와 백엔드 구현 착수가 확정되었다. P01 저장소 후보를 구현·격리 검증했으나 E: 환경과 필수 독립 검토가 차단되어 PASS가 아니다. `backend-queue.pending.json`은 여전히 Runner 실행 금지 초안이다. 새 지시의 P01 조건은 연결했으며 P02~P12 원본 번호별 범위는 추정하지 않는다. 최신 재개 지점은 `backend-checkpoint.json`이다.

## 기존 계약과 연결 경계

읽기 전용으로 확인한 Kit: `C:/Projects/dream-hs-automation-bounded-v3/automation/`의 `runner.mjs`, `recovery.mjs`, `lib.mjs`, `queue.json`, `result.schema.json`. 원본 Kit와 기존 Queue/실패 기록은 수정하지 않았다. 별도 Runner·스케줄러·DB는 만들지 않는다.

초안은 기존 Queue의 `version/configured/repo/expectedHead/expectedBranch/protected/phases`, Phase의 `id/mode/dependsOn/prompt/activePlan/allowedPaths/maxChangedFiles/timeoutSeconds/tests/requiredOutputs` 이름을 재사용한다. `configured:false`, baseline·Phase 명세 미확정으로 기존 `validateQueue`도 거부해야 한다. 이 초안을 기존 Kit의 `queue.json`에 덮어쓰거나 `--run`으로 실행하지 않는다.

연결 전 해소해야 하는 차이:

- 현 Kit는 kit 상대 prompt 경로, PostgreSQL journal·Docker·특정 migration과 package 경로를 고정 사용한다. 글빛은 Flask/SQLite이므로 이 설정을 그대로 복사할 수 없다. 기존 Runner 내 연결 방법을 확인해야 하며 새 엔진으로 우회하지 않는다.
- 현 `testGate`의 `minimumPass`는 TAP + disposable PostgreSQL을 사용한다. pytest 종료 코드만으로 G2를 PASS 처리하지 않는다. 기존 Runner에서 pytest 집계와 격리 SQLite fixture 지원을 확인해야 한다.
- 현 Reviewer는 Codex 호출이다. 고위험 Claude 리뷰가 필요한 경우 기존 리뷰 경로에 실제 Claude 결과를 연결해야 한다. Codex 리뷰로 필수 Claude 리뷰를 대체하지 않는다.
- 현 Recovery는 독립 리뷰가 발견한 결함을 보정하지만 테스트 실행 실패는 BLOCKED 경로로 간다. 테스트 결함의 최대 2회 보정과 성공 로그 요약 보존도 기존 Runner에서 충족되는지 확인해야 한다. 현재 충족했다고 주장하지 않는다.
- 로컬 Git에 HEAD가 없고 원격도 없다. 자동 commit으로 baseline을 만들지 않는다. 검증된 baseline·보호 파일·실행 환경과 Queue 승인을 원본 계약에 맞게 확인한 뒤 연결한다.

`AGENTS.md`는 존재한다. `DECISIONS.md`, `ARCHITECTURE.md`, `ACTIVE_PLAN.md`, 확정 P01~P12 문서는 발견하지 못했다. GitHub `ganzzy-km/shingword` 기본 main 저장소는 조회 시 비어 있었다. 다른 프로젝트 Phase나 DB 규칙은 글빛 설계로 가져오지 않는다.

## 공통 G1~G5 판정

각 Phase 원본을 받으면 아래 명세를 **해당 Phase prompt/독립 테스트**에 바인딩한다. 명령은 shell 문자열이 아닌 기존 `tests[].argv`와 `cwd`로 전달한다. 정상·실패·경계 중 하나라도 명세/기대값/증거가 없으면 PASS가 아니다.

| Gate | PASS 증거 | 실패·경계 판정 |
| --- | --- | --- |
| G1 요구사항 | 원본 문서 절 → 요구사항 → 정상/실패/경계 test ID → 관찰 가능한 기대 응답·최종 데이터 상태의 대응 | 기능 존재만 확인하지 않는다. 실패 시 부분 저장·중복 결과·고아 레코드가 없는지, 재시도·동시 작업 시 원본 설계의 일관성이 유지되는지 확인. 미정 기대값은 BLOCKED |
| G2 지정 테스트 | 승인된 argv/cwd, exit 0, 실제 pass 수 및 주요 수치; 실패·skip·cancel·timeout 0, 승인된 최소 통과 수 이상 | exit 0이어도 0 tests/집계 누락/skip은 불합격. targeted 우선, 최종 후보만 전체 typecheck/build/관련 회귀. 구현 보고를 실제 실행으로 대체하지 않음 |
| G3 불변 조건 | 동결 문서·보호 hash 일치, 승인된 migration 이력 유지, 승인된 fixture만 사용 | 정책/보안 충돌, 승인되지 않은 DB 변경, 학생 원문·토큰 로그, 실제 Google 인증·외부 AI 전송·운영 접근은 BLOCKED |
| G4 범위 | 기존 Scope Gate로 before/after 파일·추가·삭제·개수 검증, 현재 Phase 허용 경로만 변경 | 다음 Phase 구현·허용 경로 밖 변경·테스트 약화·보호 hash 재핀은 BLOCKED. 구현 Codex는 현재 Phase 종료 후 멈추고 Runner에 결과 전달 |
| G5 독립 검증 | 구현과 별도 검증 주체가 실제 코드/호출부/테스트와 G1~G4 증거를 읽기 전용 검토, issues 0; 리뷰 전후 source hash 일치 | 인증/권한/오프셋/migration/삭제/AI 개인정보 경계는 Claude 독립 리뷰 필수. 실행 불가·미확인·스스로 검토·리뷰 중 쓰기는 BLOCKED |

기존 `result.schema.json`의 `{status: PASS|BLOCKED, issues: string[], summary: string}`는 유지한다. 구현의 PASS는 완료 선언이 아니라 후보 제출이다. Runner가 G1~G5를 모두 실제로 확인한 후에만 기존 `pass-receipt.json`을 발행하고 연속 완료 prefix를 늘린다. UNKNOWN/NOT_RUN/SKIP을 PASS로 변환하지 않는다.

## 순서·보정·BLOCKED

UI 최종 검증 receipt + 원본 SSOT/Phase 명세 + 연결 계약 + 검증된 baseline + 사전 승인 Queue가 모두 준비되어야 P01을 시작한다. P01→P12 순서는 초안에 기록했으며 제품별 추가 의존성은 원본 확인 전 미정이다. 선행 Phase의 G1~G5 receipt가 하나라도 없으면 다음 Phase를 시작하지 않는다.

재구현 전 원본 요구사항과 기존 테스트/현재 코드/현재 baseline을 대조한다. 이미 검증된 기능은 실제 증거가 해당 요구사항을 충족할 때 재사용한다. 오래된 UI 결과나 기존 55-pass 보고를 새 Phase PASS로 간주하지 않는다.

재현 가능한 현재 Phase 범위 결함만 최소 수정한다. 초기 시도 + 자동 보정 최대 2회, 횟수는 중단/재개에도 누적한다. 동일 finding 반복, 2회 소진, 범위 확대, 정책/보안/DB 이력/보존 조건 문제는 BLOCKED. 환경/인증/용량 실패를 코드·보호 hash 수정으로 해결하지 않는다. 실패 기록은 덮어쓰지 않는다.

P11 실제 외부 AI 연결과 P12 미확정 삭제·보존 조건은 미정 부분에서 BLOCKED이며 자동으로 결정하거나 건너뛰어 전체 PASS로 표시하지 않는다. P13 OCR은 별도 승인된 v1.1이며 이 Queue 밖이다. 기존 OCR 회귀를 확인하는 것과 P13 구현은 구분한다. 운영 배포·최종 공개 승인·commit/push/merge/deploy/HOLD 채택은 Queue 밖이다.

## Checkpoint / Resume / Recovery

새 상태 엔진 대신 기존 Recovery `state.json` 계약을 사용한다: `completed`, `snapshot`, `corrections`, `findingKeys`, `reviewFindingHashes`, `lastAttempt`, `artifacts`, `preservedAttempts`, `controlFingerprint`, `config`, `dynamicProtected`. 대기 초안의 `preparationCheckpoint`는 준비 현황만 기록하며 런타임 `state.json`이나 PASS receipt가 아니다.

재개 시 Queue/Runner/도구/SSOT fingerprint, 승인 baseline, 보호 hash, source snapshot, receipt·tests·review·ZIP hash를 검증한다. `completed`는 receipt가 검증된 연속 prefix만 허용한다. 완료 Phase는 반복하지 않고 최초 미완료 Phase부터 재개한다. 중단된 후보를 구현 완료로 간주하지 않는다. 저장된 finding과 보정 횟수를 복원한다. 후보의 실제 상태를 read-only 진단한 뒤 필요한 검증만 재실행한다.

`blocked.json` 또는 hash 불일치가 있으면 자동 재개 금지. 실패 후보·기존 기록은 보존하고 별도로 승인된 복구 범위가 확인되기 전 baseline 교체·카운터 초기화·자동 재시작을 하지 않는다. 통과 receipt 없는 후보에서 다음 Phase를 시작하지 않는다. 성공 로그에는 argv/cwd, 종료 코드, 통과 수, 주요 수치만 남기고 사용자 원문·토큰·전체 stdout은 보존하지 않는다. 제어/증거 hash는 체크포인트 메타데이터로 유지한다.

## 최종 통합 검증 계획

P01~P12가 모두 통과한 최종 후보에서 초안의 `finalValidation.commands`를 기존 Runner에 연결한다. 테스트 fixture는 `backend/tests/conftest.py`의 tmp_path SQLite·업로드·백업·메모리 SecretStore이며 운영 DB를 사용하지 않는다. 외부 호출은 로컬 mock으로 차단한다. 현재 테스트에 없는 승인된 신규 계약 회귀는 원본 Phase에서 추가하고 해당 Gate에 연결한다.

최종 통합 시 승인된 계약에 따라 저장→분석→결과 재열기→수정/버전·오프셋→취소/실패→재시도→삭제/복구 흐름과 동시 작업·Unicode·빈값·상한·중복 요청·원자성을 검증한다. 정확한 상한·HTTP 코드·삭제 보존 기간·AI 전송 조건은 원본에서 가져온다. 에세이 PDF 복원·불변 분석 버전·만료 정책은 UI 체크포인트의 미해결 항목이며 임의 기대값을 넣지 않는다.

브라우저 검증은 가상 글과 별도 `scripts/ui-verification-server.py` 서버를 사용하고 `scripts/verify-library.cjs`로 확인한다. 기존 UI 수치는 참고 증거일 뿐 최종 후보 재검증을 대신하지 않는다. 필수 Claude 리뷰와 G1~G5 증거·중단/재개/2회 보정/차단 시 다음 Phase 미실행 검증까지 완료해야 기술 통합 PASS다. 공개 승인과 배포는 포함하지 않는다.
