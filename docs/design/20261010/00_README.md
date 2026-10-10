# 글빛 2.0 Codex 설계 인계

2026년 10월 10일 기준으로 기존 자료와 사용자 지정 목표를 구분한 설계 묶음이다. 구현 완료 증명이나 실행 가능한 Active Plan은 아니다. 기존 파일을 대체하지 않고 별도 참고 문서로 사용한다.

## 읽기 순서와 판단 기준

| 파일 | 필요한 작업 |
| --- | --- |
| 00_README.md | 근거의 우선순위와 충돌 확인 |
| 01_ARCHITECTURE_DATA.md | 구성 요소와 데이터 관계 확인 |
| 02_ENGINE.md | 분석 단계와 위치 매핑 확인 |
| 03_API_ACCEPTANCE.md | API 경계와 완료 조건 확인 |

상태 용어는 다음과 같다. 확정은 이번 사용자 요청에서 명시한 목표이다. 관찰은 로컬 파일에서 확인한 현재 상태이다. 제안은 목표를 구현하기 위한 작성자의 추론이며 확정 정책이 아니다. 미결은 근거가 부족하거나 사용자가 세부 정책을 아직 정하지 않은 항목이다.

실제 개발 시 해당 저장소의 AGENTS.md와 최신 확정 설계 및 계약을 먼저 확인한다. Active Plan은 작업 범위를 정하지만 정책을 임의로 변경하지 않는다. 이번 사용자 지시가 구형 자료와 충돌하면 목표 방향은 이번 지시를 따르되 기존 자료를 조용히 수정하지 않는다. 새 근거가 발견되면 차이를 보고하고 이 묶음을 자동으로 SSOT로 승격하지 않는다.

## 원격 저장소 확인

[ganzzy-km/shingword](https://github.com/ganzzy-km/shingword)는 확인 시 빈 저장소였다. [저장소 메타데이터](https://api.github.com/repos/ganzzy-km/shingword)는 size 0과 default_branch main을 반환했다. [브랜치 목록](https://api.github.com/repos/ganzzy-km/shingword/branches)은 빈 배열을 반환했다. [루트 파일 조회](https://api.github.com/repos/ganzzy-km/shingword/contents/)는 HTTP 404와 This repository is empty를 반환했다. main이라는 메타데이터가 실제 main 브랜치나 커밋 존재를 뜻하지 않는다.

따라서 원격 AGENTS.md, docs, contracts, Active Plan과 비교할 수 없었으며 원격 커밋 SHA도 없다. 로컬 프로젝트를 이 원격 저장소의 체크아웃이라고 간주하지 않는다.

## 로컬 보조 근거

이전 대화의 경로인 `C:\Users\USER\Documents\ChatGPT\글빛`에서 필요한 범위만 읽었다. 이 경로는 프로그램 데이터 루트와 다르다. Git remote 출력은 비어 있었다. contracts 디렉터리와 확정 ARCHITECTURE.md, DECISIONS.md, ACTIVE_PLAN.md는 발견하지 못했다. 대기 Queue의 activePlan 값도 null이다.

| 근거 | 사용 범위 |
| --- | --- |
| AGENTS.md | React/Vite 구조와 탐색 지침. Figma Make의 이미 실행 중인 서버 안내는 로컬 실행 상태 증명이 아님 |
| README.md | 구형 구성과 기존 기능 설명 |
| UI_CHECKPOINT.md | 최신 UI 공통 상태와 code point 표현. 검증 수치는 과거 보고 |
| docs/automation/ACCEPTANCE.md | G1~G5와 현재 자동화 연결 제한 |
| docs/automation/backend-checkpoint.json | P01 BLOCKED와 재개 제한. PASS receipt 아님 |
| docs/automation/backend-queue.pending.json | 필요한 키와 activePlan만 확인. configured false인 실행 금지 초안 |
| backend/app/config.py, models.py | 저장 경로 바인딩과 기존 모델 정의 |
| backend/app/routes/core.py, writings.py, analyses.py | 인증 차단과 필요한 기존 API 범위 |
| backend/app/analysis/engine.py, integration.py, RESEARCH_NOTES.md | 기존 휴리스틱과 분석 모듈 경계 |
| src/api.ts | 상대 API 경로와 응답 envelope |

참조 파일의 SHA-256은 SOURCE_MANIFEST.json에 기록한다. 최종 확인 중 ACCEPTANCE.md와 backend-checkpoint.json이 이 작업 외부에서 갱신됐다. 변경된 최신 절과 필요한 키를 다시 확인했다. 최초·최종 관찰 해시를 함께 남기며 전체 로컬 자료를 고정 스냅샷이라고 주장하지 않는다. 원본 파일이나 대형 로그는 묶음에 복제하지 않는다. 참조 대화 글빛 프로그램 3의 사용자 보고도 확인했다. 조회된 assistant 본문은 content-reference만 반환하므로 상세 확정 설계 근거로 사용하지 않았다.

## 차이와 충돌

| 항목 | 기존 근거 | 이번 목표와 처리 |
| --- | --- | --- |
| 원격 SSOT | 저장소가 비어 있음 | 원격 검증 불가를 명시. 업로드나 baseline 생성 없음 |
| 인증 | README는 일반 사용자 로그인 없음. core.py는 인증 미구현 차단 | Google OIDC 확정 목표. 기존 무인증 설명은 2.0 계약으로 사용하지 않음 |
| 데이터 위치 | README는 backend/instance와 uploads. Config는 환경변수 기반 검증 후 바인딩 | C:\Users\USER\AppData\Local\GeulbitData 확정 목표. 디렉터리 생성이나 이동 없음 |
| 저장소 승인 | 최신 ACCEPTANCE는 C: 승인이 E: 조건을 대체한다고 명시. 같은 문서의 과거 절과 체크포인트 remaining에는 구형 조건이 남음 | 최신 절 우선. 실제 resolved 경로가 Codex 패키지 LocalCache로 바뀌어 DATA_ROOT_REDIRECTED 차단. 승인된 물리 경로의 성공으로 처리하지 않음 |
| 분석 버전 | WritingVersion은 있으나 Analysis에 version FK가 없음 | 불변 essay_version과 analysis_runs 연결이 목표. 스냅샷 완료로 판정하지 않음 |
| 분석 판정 | 기존 역할은 단일 라벨. 인접 근거 점수와 의미 임계값 존재 | 주장·근거 후보와 관계 신호가 목표. 기존 상수를 2.0 확정 수치로 승격하지 않음 |
| 자료실 | SourceDocument, SourcePage, QuoteCard 중심 | Work→Document→Revision 목표와 기존 모델 사이 매핑 필요 |
| Revision 명칭 | 현재 Revision은 글 수정 적용 이력 | 자료 Revision과 개념 충돌. 물리 명칭 변경은 미결 |
| PDF | 인쇄 저장 UI 있음. 에세이 복원 API 없음 | 서버 PDF와 복원 통합은 미완료. 작품 OCR을 에세이 복원으로 취급하지 않음 |
| 7일 보존 | 시작점과 백업·계정·공개 자료 정책 미정 | 세부 정책을 자동 결정하지 않음 |
| 검증 상태 | 최신 P01은 G1 BLOCKED와 G5 DEFERRED. UI는 Mock 검증 보고 | UI 완료와 검토 연기를 백엔드 통합 PASS로 바꾸지 않음 |

이 작업에서는 기존 문서와 코드를 덮어쓰지 않았다. P01 상태를 바꾸거나 새 Phase 번호를 배정하지 않는다. 최신 체크포인트의 G5 DEFERRED는 관찰한 상태로 유지하며 독립 검토 완료나 영구 면제를 뜻하지 않는다. 문서 정리 완료에는 코드 구현 Gate를 적용해 중단할 이유가 없다.

## Codex에 전달할 짧은 지시

이 묶음의 00_README.md로 출처와 충돌을 먼저 확인한다. 실제 저장소의 AGENTS.md, 최신 확정 계약, 현재 Active Plan을 우선하고 담당 작업에 필요한 설계 절만 읽는다. symbol 검색 → 정의 → 호출 위치 → 필요한 코드 범위 → 관련 테스트 순으로 탐색한다. 대형 로그와 EVIDENCE 전체를 읽지 않는다. 기존 엔진과 모델을 재사용하고 한 작업 단위만 수정한다. 제안과 미결 정책을 확정값으로 구현하지 않는다. 승인된 DB 변경 범위가 없으면 migration을 실행하지 않는다. 현재 차단 상태와 보호 파일을 유지한다. 관련 테스트 후 완료 조건을 만족하면 종료한다. 종료 보고는 STATUS, CHANGED, RULES, TESTED, RISKS만 간단히 남긴다.

