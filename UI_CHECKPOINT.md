# 글빛 2.0 UI 체크포인트

## 2026-10-10 참고 디자인 복원 및 책장 개선 완료
- 기준: Ui 참고 자료의 최신 디자인 ZIP, 040205 홈·040229 편집 화면·040244 설정 캡처, 빈 오크 책장·양장 표지·아이보리 종이 이미지. 원래 기본 테마까지 표지 카드와 작은 서체를 적용한 것이 참고 시안과 차이를 만든 원인이다.
- 변경: src/Library.tsx, src/BookCover.tsx, src/library.css, src/index.css. 기본 테마 흰색 글 카드·연녹색 메뉴·넓은 연속 편집기 복원. 책장 표지 240→310px, 편집 본문 18px, 읽기 19px(모바일 18px)/1.8, 최대 텍스트 폭 540px. 표지·로컬 글꼴 및 라이선스는 참고 ZIP에서 재사용.
- 메뉴: 데스크톱 접기 시 실제 본문 폭 확대. 1100px 이하 드로어, 포커스 순환·Escape·포커스 복귀. 접기 설정만 브라우저에 저장하며 기존 서버 설정 계약을 확장하지 않는다. 읽기 피드백 접기 지원.
- 구조: 한 Writing 상태·기존 분석 ID·기존 API를 두 테마에서 공유. 페이지는 code point span의 표현이며 별도 저장 모델·페이지 영구 주소·분석 복제를 만들지 않았다. 기존 불변 서버 버전 계약 부족 상태는 이 UI 작업으로 해결되었다고 주장하지 않는다.
- 검증: pnpm exec tsc --noEmit, pnpm run build, node scripts/book-layout.test.mjs, node scripts/verify-ui-design.cjs, node scripts/compare-ui-design.cjs 모두 종료 코드 0. 1440/1024/820/390/320px 100개 화면에서 예외·넘침·중복 화면 틀 0. 각 너비 30,000 code point 전체 페이지 결합 일치, 반복 구절 두 번째 위치 선택, 메뉴 변경 시 커서·선택·스크롤·원문 위치 보존, 양면/단면, 키보드·합성 터치 스와이프 검증 통과.
- 증거: artifacts/ui-design/before/after/ 수정 전 46개, artifacts/ui-design/after/ 수정 후 100개. home-comparison.png와 editor-comparison.png에 수정 전/실제 참고 캡처/수정 후를 나란히 배치하고 직접 열어 검토. 320px 책 피드백 및 데스크톱 메뉴 열린/접힌 책도 직접 확인.
- 보호: P01 및 backend-checkpoint.json 보호 파일 11개 SHA-256 동일. C: Data Root·인증 차단·P01 G5 BLOCKED 보존. Claude 검토·DB 작업·외부 전송·commit/push/배포 없음. 브라우저는 가상 API fixture만 사용하며 실제 서버 통합 완료를 뜻하지 않는다.

## 2026-10-10 UI 혼합 복구 완료
- 원인: 최신 Library는 dashboard에서만 표시되고 다른 경로는 구형 MainLayout으로 연결되어 테마가 바뀌어 보였다. 모든 경로의 화면 틀을 Library로 통일하고 기존 자료실·규칙·설정 내용만 내부에 유지했다. 개발 StrictMode에서 alive 상태가 복구되지 않아 저장·분석 완료 처리가 중단되는 문제도 수정했다.
- 변경: src/App.tsx, src/Library.tsx, src/library.css, scripts/verify-ui-recovery.cjs. 보조 화면 모바일 너비 조정, 화면 이동 시 초안 보존. 아래 기록은 이전 작업의 검증 이력이다.
- 검증: pnpm exec tsc --noEmit / pnpm run build / node scripts/book-layout.test.mjs / node scripts/verify-ui-recovery.cjs after 모두 종료 코드 0. 브라우저 1440·820·390px, 복구 후 46개 화면, 예외·가로 넘침·중복 화면 틀 0. 각 너비에서 30,000 code point 본문 전체 페이지 결합 일치, 피드백 구절 이동·검색·문단 탐색·테마 전환·API 실패 표시 통과.
- 증거: artifacts/ui-recovery/before/ (10개 화면), artifacts/ui-recovery/after/results.json 및 PNG. 대표 수정 전 legacy-new-analysis-1440.png와 수정 후 new-analysis-1440.png, book-feedback-390.png를 열어 비교했다.
- 보호: P01 저장소·SQLite·migration·CLI·서버 및 backend-checkpoint.json 11개 파일의 작업 시작/종료 SHA-256 동일. C: Data Root 관련 기존 설정 보존. DB 작업·외부 호출·자동 commit/push/배포 없음.
- 제한: 이번 브라우저 검증은 테스트 스크립트의 가상 API 응답만 사용했다. 운영 코드에 mock을 추가하지 않았으며 실제 인증·사용자 API 차단은 유지했다. 백엔드 재개 기준은 docs/automation/backend-checkpoint.json이다.

상태: 부분 완료. UI와 기존 API 연결 및 검증 완료. 아래 서버 계약 제한은 그대로 남아 있음.

## 구현
- `src/Library.tsx`: 실제 글 목록, 검색/정렬/목록 페이지 이동, 새 글/자동 저장, 연속 문서 편집, 문단 탐색, 본문 검색, 두 테마 설정, 읽기/편집 전환, 분석 진행/취소, 기존 결과/반응 API, 피드백 필터/그룹, 정확한 구절 이동, PDF 인쇄 보관, 휴지통 안내, PDF 파일 확인.
- `src/book-layout.ts`: 실측 페이지 분할과 Unicode code point 위치, 명시적인 beforeinput 편집 범위의 검증된 매핑. 수정되거나 출처를 증명할 수 없는 범위는 이동 비활성화.
- `src/library.css`, `src/index.css`: 독립적인 오크/표지/종이 레이어, 네 가지 표지 색, 책 열기와 페이지 전환, 반응형 양면/단면, reduced-motion, 접근 가능한 설정 창과 인쇄 스타일.
- `src/App.tsx`: 기존 화면을 유지하며 서재 연결. 기존 화면 이동 시 초안 유지, 작업 공간 초기화 시 서재 상태 초기화.
- `backend/app/routes/core.py`, `backend/app/seed.py`: 기존 WorkspaceSetting 저장 구조에 테마/장식/애니메이션 설정 추가. 새 테이블/마이그레이션 없음.
- `public/assets/`: 원본 참고 자료에서 필요한 오크·녹색 표지·종이 이미지만 복사. 원본 변경 없음.

## 실제 검증
- `pnpm exec tsc --noEmit`: 종료 코드 0.
- `pnpm run build`: 종료 코드 0.
- `.venv/Scripts/python.exe -m pytest backend/tests -q -p no:cacheprovider`: 55 passed.
- `node scripts/book-layout.test.mjs`: 1만/3만 자, 세 페이지 용량, Unicode/중복 구절/수정 범위 무효화 검증 통과.
- `node scripts/verify-library.cjs`: 실제 Flask API와 headless Edge 사용. 1440/1024/820/390/320px 가로 넘침 없음. 본문 검색과 분석 구절의 실제 선택 일치, 입력 전 위치 기록 후 매핑, 12,404자와 30,000 code point 본문 전체 페이지 결합 일치, 3만 자 62페이지, 터치 스와이프, 리사이즈 위치 유지, 첫/끝 페이지, 새 글 자동 저장, 설정 저장/모션/질감, PDF 오류와 비활성 처리, 모달 키보드 탐색 통과. 브라우저 예외 0.
- `artifacts/ui-verification/results.json`: 실제 검증 수치.
- `artifacts/ui-verification/*.png`: 화면 저장 후 데스크톱/태블릿/모바일 대표 화면을 열어 확인. 초기 선반 겹침, 읽기 폭, 측정 노드 재사용 문제, 표지 제목 잘림을 수정하고 재촬영.
- 인쇄 PDF 10페이지를 생성해 처음/마지막 페이지를 렌더링하고 확인. 마지막 65번째 문단 포함. 테스트 PDF는 가상 글이며 사용자 데이터가 아님.

## 서버 계약 제한
- 로컬 Git 저장소에 원격 URL이 없음. GitHub 저장소와의 연결을 주장하지 않으며 clone/commit/push/배포하지 않음.
- 최신 Architecture/DECISIONS/ACTIVE_PLAN 문서 및 승인된 7일 만료 계약이 없음. 현재 로컬 API에 자동 만료/삭제 예정 시각이 없으므로 임의의 날짜나 삭제 정책을 도입하지 않음. 휴지통에 삭제된 원문/제목/표지를 보관하지 않음.
- 기존 분석 데이터에 불변 WritingVersion 연결이 없음. 이전 분석은 원문 위치 재확인 상태이며 이동 비활성화. 현재 세션에서 제출한 본문과 일치하는 결과에만 매핑 제공. 서버의 동시 편집/분석 스냅샷 보장은 별도 계약이 필요함.
- 에세이 PDF 복원 API가 없음. 파일명/크기/헤더 확인 UI만 제공하며 추출/생성은 비활성화. 작품 자료 추출 API를 에세이 복원으로 위장하지 않음. PDF 저장은 브라우저 인쇄 대화상자 사용.
- 실제 휴대폰의 키보드 및 터치 하드웨어 검증은 하지 않음. Edge의 뷰포트와 실제 브라우저 터치 이벤트로 검증함.

## 실행과 다음 작업
- 개발 미리보기: http://localhost:8443/; Flask API: http://127.0.0.1:5000/.
- 검증 서버는 `scripts/ui-verification-server.py`로 별도 5055 포트와 `.tmp-ui-verification/test.db`를 사용. 테스트 글은 사용자 DB에 넣지 않음.
- 재검증: 검증 서버 실행 → build → `node scripts/verify-library.cjs`.
- 다음 단계는 승인된 분석 버전 연결·만료 정책·PDF 에세이 복원 API 계약을 확인하고 해당 UI를 연결하는 것. 기존 데이터/권한/보존 정책을 임의로 변경하지 않음.
