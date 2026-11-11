# 글빛 UI·Architecture 감사 — 2026-10-10

판정: 요청한 계정 UI·로그아웃 및 핵심 감사 완료. 운영 출시 승인은 별도이며 G5는 DEFERRED_FINAL_REVIEW이다.
기준: AGENTS.md, UI_CHECKPOINT.md, docs/design/20261010/01_ARCHITECTURE_DATA.md·02_ENGINE.md·03_API_ACCEPTANCE.md, DB_MAPPING_PLAN.md와 최신 backend-checkpoint.json. 과거 설계 스냅샷의 미구현 표시는 현재 코드·운영 revision과 구분했다.

## 설계와 구현 대조

| 상태 | 경계 및 근거 | 검증 |
|---|---|---|
| MATCH | backend/components/auth.py의 validate_google_claims·SessionBoundary, backend/app/v2/auth_api.py: 검증된 Google sub, state/nonce, 서명·issuer/audience/만료, 활성 상태·session_version·CSRF | component_tests/test_auth.py, v2_tests/test_auth_api.py; 실제 Google 로그인은 격리 localhost 서버에서 별도 확인 |
| MATCH | backend/app/v2/common.py의 owned_writing 및 각 리소스 소유권 검사: ADMIN도 학생 글에 자동 접근하지 않음 | v2_tests의 권한·IDOR·자료실·PDF 테스트 |
| MATCH | backend/app/models.py와 0002/0003 migration: 기존 writing/writing_version/analysis/source_document 계열 재사용, 초안 revision·불변 버전·append-only 문서 revision | 운영 DB 읽기 전용 대조: 40개 테이블, ORM 누락 컬럼 0, revision 0003_resource_ownership, integrity ok/FK 오류 0; 격리 API·migration 테스트 |
| MATCH | backend/app/analysis/snapshot.py 및 순수 엔진: NFC/LF, code point [start,end), 버전 manifest, Kiwi, 후보 구조·규범·인용 대조 | engine_tests 및 book-layout.test.mjs; 동일 문자열 피드백 클릭 시 실제 선택 문자열 `몇일` 확인 |
| MATCH | src/Library.tsx·api.ts·book-layout.ts: 두 테마가 동일 writing/analysis API·상태 사용 | 30,000자 가상 글, 두 테마의 동일 책 1개·분석 1개, 편집기 본문 code point 30,000 및 페이지 넘김 |
| MATCH | PDF·AI·만료 경계: 특정 불변 버전/분석 보고서, 생성 후 소유권·만료 재확인, AI 동의·처리조건·최소 문맥, 미확정 자동 삭제 차단 | v2_tests 및 실제 Google 세션 PDF 다운로드; 외부 AI·자동 삭제 활성화하지 않음 |
| MISMATCH → 수정 | 운영 AI 상태 응답이 AI_TERMS_APPROVED를 읽고 실제 AI 경계는 EXTERNAL_AI_TERMS_APPROVED를 읽음 | operations_api.py가 동일 설정 키의 정확한 boolean을 사용; 관련 6개 테스트 통과 |
| MISSING → 구현 | 모든 화면의 검증된 계정 상세·제품 로그아웃 연결 | AccountMenu.tsx; USER/ADMIN 및 실제 Google 계정·로그아웃·뒤로가기 확인 |
| MISSING → 비활성 표시 | 기존 설정의 서버 백업/복원·전체 삭제/초기화·JSON 일괄 내보내기 버튼에 실제 서버 계약이 없음. OCR은 별도 v1.1 | App.tsx에서 비활성화·정확한 안내. 개인 PDF 및 지원 텍스트 PDF 가져오기는 유지 |
| UNVERIFIED | 공개 HTTPS 운영, 외부 AI 처리조건, 미확정 삭제 정책, Claude 최종 검토 | 승인 범위 밖. 운영 완료·G5 PASS로 표시하지 않음 |

## 발견한 결함과 최소 수정

- P1: 인증 실패 안내만 닫으면 이전 개인 화면이 남을 수 있는 구조를 수정했다. 확인되지 않은 세션에서는 개인 UI를 숨기고 inert 처리하며, 다른 계정으로 바뀌면 작업 공간을 초기화한다.
- P1: 로그아웃 시 사용자 상태·캐시 prefix·CSRF와 진행 중 API/PDF 응답을 함께 무효화했다. 서버 종료 성공 전에 가짜 로그아웃 성공을 표시하지 않으며 초안 저장 충돌·실패 시 종료하지 않는다.
- P2: 계정 UI 누락을 공통 헤더의 내 계정 dialog로 보완했다. 이름·사진은 검증된 선택적 Google profile만 사용하고, 권한·승인은 매번 서버 DB에서 확인한다. sub·토큰·보안 식별자는 표시하지 않는다. 기존 쿠키도 이름·사진 없이 동작한다.
- P2: 헤더 CSS가 dialog 로그아웃 버튼 테두리를 제거하는 충돌을 좁은 범위로 수정했다. 기존 두 테마·책 표지·페이지 계산·애니메이션은 재설계하지 않았다.
- P2: 작업 공간 표시 이름과 Google 이름을 명확히 구분하고, 미구현 위험 작업을 활성 버튼으로 표시하지 않는다.
- 개인정보: 선택적 프로필은 기존 서명 쿠키에 한정하며 DB 컬럼·migration을 추가하지 않았다. 사진은 검증된 HTTPS Google 이미지 호스트만 허용한다. 개인 응답은 no-store이다.

## 실제 검증과 범위

| 명령 | 종료 코드 | 결과 |
|---|---:|---|
| `.venv/Scripts/python.exe -m pytest backend/v2_tests backend/component_tests backend/engine_tests -q -p no:cacheprovider --tb=short` | 0 | 204 passed, 102.12초 |
| `.venv/Scripts/python.exe -m pytest backend/v2_tests/test_operations_api.py::test_admin_ai_status_uses_same_approved_terms_flag backend/v2_tests/test_ai_api.py -q -p no:cacheprovider --tb=short` | 0 | 마지막 설정 키 수정 후 6 passed, 7.81초; 전체 204개와 중복 있음 |
| `node scripts/account-session.test.mjs` | 0 | 7 passed: 세션 변경 중 응답·PDF, CSRF, 401/403/500, 네트워크 실패 |
| `node scripts/book-layout.test.mjs` | 0 | 10,000/30,000자·3가지 용량·Unicode·반복 구절·변경 구간 |
| `node node_modules/typescript/bin/tsc --noEmit` | 0 | typecheck 통과 |
| `node node_modules/vite/bin/vite.js build` | 0 | 22 modules, 최종 후보 build 354ms |

브라우저: 1440·1024·820·390·320px에서 계정 창/기본 홈/긴 글 편집/책장/책 읽기 25개 상태를 확인했다. DOM 가로 넘침 0, 편집기 30,000자 보존, 320px 다음 페이지 2/110 확인. 전체 110페이지를 실제 브라우저로 순회했다고 주장하지 않는다. 본문 완전성은 기존 페이지 계산 테스트와 함께 판단했다. 모바일 메뉴·작품 빈 목록·평가 기준·규칙·ADMIN 운영·로그아웃도 확인했다. QA 서버만 종료한 뒤 상태 다시 확인을 눌러 NETWORK_ERROR 표시·개인 글 차단을 실제 브라우저에서 확인했다. 403/500 및 세션 경합은 코드·API 테스트로 확인했으며 모든 장애의 브라우저 화면을 주입 검증한 것은 아니다.

실제 인증: 사용자에게서 실제 Google 이름·이메일·ADMIN·승인 완료 정상 표시 확인을 받았다. localhost:8770 격리 DB의 기존 가상 글·저장 완료·분석 completed·책 읽기를 재사용하여 계정 창, 실제 PDF 다운로드, 제품 로그아웃과 뒤로가기 개인 글 차단을 확인했다. 보고서 1페이지의 가상 본문과 이메일 미포함을 확인했다. 최초 ADMIN bootstrap을 반복하지 않았다.
Mock 인증: localhost:8766의 별도 가상 DB에서 RSA 검증 포함 PENDING_APPROVAL·USER·ADMIN, 승인 대기 API 차단·권한별 메뉴를 확인했다. Mock을 실제 Google 연결 증거로 사용하지 않았다.

## 스크린샷과 인수인계

참고: `Ui 참고 자료/스크린샷 2026-10-10 040205.png`, `040229.png` 및 참고 UI ZIP. 참고의 mock 문구·가상 만료일은 제품 기능으로 채택하지 않았다.
수정 전: `artifacts/auth-live/real-google-default-analysis.jpg`, `real-google-bookshelf.jpg`; 설정 전후: `artifacts/ui-arch-audit/admin-settings-320.jpg` → `admin-settings-fixed-320.jpg`.
수정 후: `artifacts/ui-arch-audit/account-user-320.jpg`, `default-editor-1440.jpg`, `bookshelf-home-390.jpg`, `book-reader-320.jpg`, `real-google-account.jpg`, `real-google-book.jpg`, `real-google-product-logout.jpg`. 첫 후보 계정 사진은 버튼 테두리 수정 전 캡처이며 최종 CSS와 구분한다.
정량 증거: `artifacts/ui-arch-audit/evidence.json`, `operational-readonly.json`; 실제 Google PDF: `real-google-report.pdf` (가상 에세이). 실제 계정 사진은 로컬 검토용이며 배포·Git 저장하지 않는다.

운영 DB·DPAPI 저장소·migration 3개·기존 전역 CSS의 작업 전후 SHA-256이 동일하다. 운영 사용자 0, 운영 DB에 테스트 사용자/글을 생성하지 않았다. 기존 백업·E: 데이터는 접근·수정하지 않았다.
Runner baseline을 새로 채택하지 않았다. src/library.css는 이번 요청에서 승인한 계정 UI/CSS 수정이며 기존 Protected Hash와 달라진다. 이 변경을 자동으로 기존 Phase G4 PASS로 인정하지 않는다. 다른 보호 파일은 해시로 검증한다. 후속 Runner 실행에는 이 승인된 CSS 변경의 정상적인 보호 파일 계약 반영이 필요하다.
남은 사항: 최종 독립 검토, 운영 출시 승인, 외부 AI·삭제 정책 확정. 실제 Google 격리 서버와 TLS 프록시는 loopback으로 유지하며, 별도 Mock QA 서버는 검증 후 종료했다. 미구현 설정 기능은 복구/삭제 API 승인을 받아 구현하기 전까지 비활성 상태를 유지한다.


## 2026-10-10 후속: 직관적인 화면 정리와 짧은 에세이 실동작 확인

수정 파일: src/Library.tsx, src/library.css. 편집 상단은 분석하기·책으로 읽기를 중심으로 유지하고 PDF·자료 판본 연결·수동 저장을 더 보기에 모았다. 자료/도움말, 분석 기록, 결과 필터, 사용자 반응은 필요할 때 펼친다. 피드백은 서버 순서를 유지해 처음 3개를 표시하며 전체 결과를 삭제하거나 축약 저장하지 않는다. 책에서 선택한 숨겨진 제안은 추가 표시한다. 심화 질문 문맥 확인은 선택한 피드백에서만 표시하고 외부 AI는 활성화하지 않았다.

직접 작성한 473자 가상 에세이 「책임은 말과 행동으로 드러난다」를 별도 격리 DB에서 분석했다. Kiwi 0.23.2가 13문장·13문장 역할 후보·관계 후보 2개·직접 인용 1개를 생성했다. 처음 3개 피드백 중 고정 오타 몇일→며칠을 탐지하고, 구조 단서는 확인 필요로 표시했다. 원문 이동의 실제 선택 문자열은 몇일이었다. 수정 후 재분석은 해당 오타 제안이 사라지고 구조 제안 2개를 유지했으며, 모든 반환 finding span은 분석 원문과 일치했다. 초안 revision 2·분석 이력 2개를 확인했다. 과거 분석은 기존 오타를 보존하고 변경된 초안에서 위치 재확인이 필요함을 표시했다.

실제 브라우저에서 PDF 다운로드·473자 본문 추출 미리보기·사용자 확인 후 새 글 생성·책장 테마 전환·로그아웃을 확인했다. 가져온 PDF의 과거 분석은 복원되지 않았다. 별도 10개 제안 fixture는 처음 3개→전체 10개→다시 3개로 동작했고, 책 두 번째 페이지에서 숨겨진 제안을 선택하면 선택 카드가 추가로 나타났다. 모든 테스트 글은 가상이며 실제 학생 글이나 운영 DB를 사용하지 않았다.

검증:
- `.venv/Scripts/python.exe -m pytest backend/v2_tests backend/engine_tests -q -p no:cacheprovider --tb=short`: exit 0, 152 passed, 73.75초. 자료실/인용/권한/동시 저장/불변 버전/AI 차단과 로컬 동작/관리자/PDF/만료 실패 경로 포함. 실제 외부 서비스 성공을 뜻하지 않는다.
- `node scripts/account-session.test.mjs`: exit 0, 7 passed.
- `node scripts/book-layout.test.mjs`: exit 0, 10k/30k 페이지·Unicode·변경 구간 검증.
- `node node_modules/typescript/bin/tsc --noEmit`: exit 0.
- `node node_modules/vite/bin/vite.js build`: exit 0, 최종 22 modules, 241ms.
- 1440/820/390px 편집기 473자 보존·가로 넘침 없음. 모바일 더 보기의 초기 오른쪽 넘침을 발견해 도구 영역 기준으로 위치를 수정했다. 수정 후 390/320px 각각 패널 경계 102~372/32~302px, 가로 넘침 없음.

증거: artifacts/ui-intuitive/browser-evidence.json, simple-api-evidence.json, editor-1440.jpg, editor-820.jpg, editor-390.jpg, more-390.jpg, more-320.jpg, bookshelf-390.jpg, book-feedback-390.jpg, simple-report.pdf. 이전 복잡한 화면은 artifacts/ui-arch-audit/default-editor-1440.jpg와 비교한다.

이번 브라우저 인증은 Mock USER이고 실제 API·SQLite·Kiwi·PDF를 사용했다. 실제 Google 로그인을 다시 수행한 것은 아니다. 외부 AI, 미확정 자동 삭제, 운영 백업/전체 복원은 이번 실동작 검증에서 활성화하지 않았다. 분석은 재현 가능한 규칙·구조 후보 검증이며 문학 해석의 정답이나 논리적 타당성 보증이 아니다. 운영 DB·비밀 저장소·migration·기존 전역 CSS 해시가 이전 보존 증거와 동일하다. G5·Runner 보호 CSS 계약 대기 상태를 변경하지 않는다.


## 2026-10-11 — 전체 기능 회귀 및 병목·자료실 UI 개선

기존 두 테마와 API 계약을 유지했다. 자료실의 잘못된 /files/sources 주소 기반 미리보기를 인증된 문서 본문 API + native dialog로 교체했다. 허용 형식은 텍스트 PDF/TXT로 표시하고 미지원 이미지/DOCX 및 도달할 수 없는 자료 OCR 흐름을 제거했다. 공용 삭제 버튼은 ADMIN에게만 제공하되 서버 권한 검증을 유지한다. 모바일 파일 카드 버튼을 다음 줄에 배치해 파일명 잘림·세로 배지 문제를 수정했다. 다운로드 허용 문서에만 원본 다운로드를 제공한다.

본문 code point 배열과 검증된 피드백 span을 변경 시에만 계산한다. 30,000자/447개/10회 span 검증 마이크로벤치마크: 666.34ms → 0.90ms, 결과 동일. 전체 UI/서버 지연 보장 아님. 긴 글 문단 버튼은 현재 주변 9개만 표시하고 전체 문단은 선택 목록으로 이동한다. 문단·본문·분석 데이터를 자르지 않는다. 자료 목록 조회는 본문을 읽지 않고 최신 판본 ID를 묶어 조회한다. 12문서+추가 판본 회귀에서 revision SELECT 1회, 본문 SELECT 없음.

사용자 승인 PDF에 한정한 전체 등록 계약과 권한/해시/314쪽/반복 등록 테스트를 추가했다. 실제 파일 전체 등록·열람·원본 다운로드를 격리 fixture DB에서 검증했다. 실제 Google 로그인 격리 서비스의 자료 등록은 로그인 대기이며 운영 등록 완료로 표시하지 않는다. 규범 출처는 사용자 승인 상태로 기록하고 실제 라이선스/최신 규범 확인과 구분한다.

검증: v2_tests+engine_tests 154 passed/82.79s, component_tests 53 passed/3.79s. 목록 최적화 후 library/quote/rules targeted 18 passed/8.35s. 모두 exit 0. account-session 7 cases, book-layout 10k/30k/Unicode, feedback-spans Unicode/반복/잘못된 위치/동등성 PASS. 최종 typecheck exit 0, build exit 0/218ms/23 modules. 116자 실제 Kiwi 결과에서 몇일의 정확한 선택, 10k/30k 저장·분석·모든 문장 span, 두 테마, 600문단 및 134쪽 마지막 이동, 자료 업로드/미리보기/Escape/실제 PDF 다운로드/로그아웃 확인. 1440/820/390px 편집·자료실 가로 넘침 없음. artifacts/optimization의 browser-evidence.json, api-evidence.json, span-benchmark.json, 스크린샷 및 simple-report.pdf 참조.

운영 SQLite revision 0003_resource_ownership, integrity ok, FK 위반 0. 운영 DB·DPAPI·원본 PDF 해시 불변. 운영 쓰기/삭제/migration/외부 AI/commit/push/deploy 없음. QA 서버 종료·생성된 QA HTML/JS 제거, 실제 OIDC 격리 Waitress만 --init 없이 재시작하고 TLS 프록시 보존. Runner 공식 G4는 기존 CSS 및 이전 규범 출처 작업의 02_ENGINE.md 보호 해시 조정 대기; 나머지 protectedGate PASS. 자동 baseline 채택·Gate 우회 없음. G5 DEFERRED_FINAL_REVIEW.


2026-10-11 등록 후 확인: 사용자 실제 Google 서비스 등록 완료 통보에 따라 기존 격리 DB를 read-only 확인했다. PUBLIC/REFERENCE/DOWNLOAD, 314쪽, 원본 3,156,652바이트 SHA 일치, 추출 213,042자 hash 일치, 문서/revision 각각 1개, 검증된 지정 ADMIN 소유권 정상. integrity ok/FK 0. 추가 업로드·운영 DB 쓰기 없음. 등록 대기 해제. 내장 브라우저 세션은 ACCESS_DENIED로 현재 UI 재검증 완료를 기록하지 않는다. 운영 DB·DPAPI 해시 불변, G5 및 Runner 대기 유지.


## 2026-10-11 전체 코드 검수·국소 최적화

핵심 API·분석·세션 전송 경로를 검수하고 68개 Python 소스의 문법 및 전체 백엔드 회귀를 확인했다. 모든 줄의 독립 보안 감사 완료나 운영 출시 검증을 뜻하지 않는다. 에세이 목록 분석 요약을 page IDs 기준으로 묶어 읽고 큰 result/input/context JSON을 제외한다. 12개 가상 에세이에서 실제 SELECT 12회→1회, wire/history/latest-success 유지. 인용 권한 재검증은 동일 순수 permission gate와 canonical validation만 호출하며 허위 검색을 제거했다. 자료 revision hash 및 실제 인용 검색은 유지한다. API 전송은 계정 전환 시 이전 CSRF 변경 요청을 fetch 전에 차단하고 다운로드/CSRF의 401도 세션 무효화 이벤트로 처리한다. RapidFuzz 중복 dependency 1행 제거. UI 디자인·운영 DB·migration 변경 없음.

전체 backend/tests+component_tests+engine_tests+v2_tests+mapping_tests: 357 PASS/87.65s/exit 0. 마지막 canonical validation 유지 보완 후 related 59 PASS/7.61s/exit 0. 계정 JS 10 cases, book-layout 10k/30k/Unicode, feedback-spans 동등성 PASS. typecheck/build exit 0, 23 modules/218ms. 증거 artifacts/code-review/evidence.json, list-query-benchmark.json. 처음 목록 코드의 변수 참조 오류를 작은 회귀 테스트로 발견해 수정했으며 테스트 완화 없음. 기존 Alembic 경로·SQLite datetime deprecation은 migration 변경 없이 남긴다.

운영 DB revision0003/integrity ok/FK0, DPAPI·migration·UI layout hash 불변. 실제 localhost 격리 Waitress만 무초기화 재시작했고 TLS 프록시 유지. 새 실인증·브라우저·외부 기기 검증 없음. 외부 AI/삭제/공개/commit/push 없음. G5 및 기존 Runner 보호 baseline 대기 유지. ngrok/개인정보/출시 조건은 기존 P14 checkpoint에서 이어간다.

## UI·긴 글 계산 개선 (2026-10-11)

기존 두 테마의 색·동선·API를 유지하고 카드 배경, 서재 안내, 버튼 상태, 검색 포커스와 종이 표면을 다듬었다. 보호된 book-layout.ts는 원래 해시 그대로 유지했다. 검색은 별도 text-search.ts로 분리해 위치마다 slice/join을 만들지 않으며 겹친 검색·이모지·CRLF·빈 검색·미일치 검증을 유지한다. 책 페이지 계산은 같은 너비/높이면 반복하지 않고 폰트 준비/본문 변경 시 다시 계산한다. RAF 방식은 모바일 검증 후 기존 동기 계산 방식으로 최소 조정했다.

Chrome 가상 fixture 1440/1024/820/390/320px, 110 스크린샷, 오류0/가로넘침0, 30000 code points 페이지 전체 재구성 PASS. 기본/책장/편집/피드백/검색/페이지 이동/모달/자료 화면/오류 상태를 검증했다. 대표 데스크톱·모바일·책 화면 이미지를 직접 확인했다. 첫 시도는 소스 HMR 전환 중 화면 탐색 실패, 이후 Vite가 검증 빌드 폰트 watch EBUSY로 중단했다. 최종 빌드를 파일 감시 없는 로컬 preview에서 재실행해 전부 통과했다. 결과 artifacts/ui-refinement/final/results.json.

검색 미세 측정: 15.28ms → 8.28ms, 30000자·30회, 결과 동등. 브라우저 전체 응답 시간 보장은 아니다. book-layout 10k/30k/Unicode/search 테스트, 계정 격리10 cases, tsc --noEmit, 별도 출력 build exit0. Runner backend AI 회귀52 PASS/G1~G4 PASS. 운영 DB/기존 dist/서비스/AI 설정 보존; 새 실계정 로그인·운영 PDF·공개 반영은 하지 않았다.

## 검증된 UI 운영 반영 (2026-10-11)

사용자의 명시적 외부 반영 승인으로 검증 빌드의 새 CSS/JS를 dist/assets에 추가하고 index.html만 마지막에 교체했다. 기존 assets를 보존해 이전 열린 화면도 동작한다. 운영 코드 증거의 index/새 asset hash를 갱신했고 이전 index 및 release receipt는 C:/Projects/dream-hs-automation-bounded-v3/output/geulbit/ui-rollbacks/2026-10-11T08-11-07-786Z에 보존했다. DB·migration·비밀값·분석 엔진 변경 및 서버/터널 재시작 없음.

실제 Chrome 지정 Google 계정 재로그인, 기본/책장 전환과 원래 기본 테마 복원, 실 API 38 탐지 규칙/134 규정 표시 PASS. DOM에서 새 bundle 확인, shell1/가로넘침0. 배포 전 브라우저 메시지3개와 구분해 배포 후 console error0. 운영 home/bookshelf/rules screenshot을 저장했다. 운영 DB에 시험 글을 생성하지 않았다. 저장·불변 버전·분석·재분석·PDF·권한 회귀는 격리 pytest56 PASS/48.96초/exit0로 검증했다. 운영 DB read-only revision0003/integrity ok/FK0, local/externalhealth200, 기존 프로세스 유지. 새 운영 글 생성·분석·PDF 실사용 흐름은 이번에 실행하지 않았으며 격리 결과와 혼동하지 않는다. AI 비활성/G5 WAIVED_BY_USER 유지.

## 주장·근거 연결 개발 검증 (2026-10-12, 운영 미반영)

고정 표현만 찾는 후보 탐지, 내용 검증 없는 최근 후속 근거 연결, 본문 표시 누락을 구분해 수정했다. Kiwi의 XSV/XSA 서술 구조와 작품·인물·행동 단서를 사용하며 앞선 12문장/2문단의 공통 주제어·연결 표현을 검토한다. 신호 점수4, 후보 차이2가 부족하면 관계를 보류한다. 이는 논리적 타당성 점수가 아니다. 기존 JSON에 run/version ID, 원문 span/quote, 후보 ID와 관계 근거를 호환 확장했고 기존 DB/migration은 바꾸지 않았다.

현재 textarea를 유지한 표시층과 책 본문에서 연한 주장 표시·근거 밑줄·작은 화살표를 같은 code point 주소로 렌더링한다. 본문/작품/탐구 문맥/판본 변경 시 관계를 숨기며 맞춤법 위치 매핑과 분리했다. 편집기 화살표는 긴 mirror 안의 이동 버튼 대신 보이는 좌표의 독립 버튼으로 배치해 터치/키보드 이동을 검증했다. 실제 Kiwi 격리 결과를 사용한 Chrome 1440/820/390 두 테마 6개 사례 PASS, 전체 페이지 재구성852쪽/30000자 PASS, 최종 상호작용6개 PASS, 브라우저 오류0. 13개 기준 예문의 기대 관계7개/오탐0/누락0은 이 예문에만 해당한다. 테스트 명령과 결과는 backend-checkpoint.json#argumentRelations에 기록했다. 운영 dist/DB/세션/비밀값/출시 receipt는 보존했으며 운영 반영하지 않았다. 새 개발 소스는 기존 운영 hash와 다르므로 승인된 반영 절차 전 운영 재시작·유지보수 preflight는 차단을 유지한다.

최종 스크린샷에서 선택된 본문 위에 강조색이 겹치는 것을 확인해, 편집기 장식 배경은 native textarea 아래에 두고 화살표만 별도 위층에 배치했다. native 선택 색·커서·가독성을 유지한 최종 Chrome6개 사례/타입 검사/빌드 PASS. 운영 파일·출시 hash는 갱신하지 않았다.
