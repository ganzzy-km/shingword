# 한국어 규범 주 참고자료

2026-10-10 사용자 지정: `C:/Users/USER/Pictures/geulbit_korean_norms_reference_v1.pdf`를 규범 규칙 개발·출처 검토의 우선 참고자료로 사용한다. 원본은 변경하지 않는다. 이 문서는 PDF 본문을 복제한 새 규범집이 아니다.

식별 및 쪽수·기존 규칙 매핑의 단일 원본은 `backend/app/analysis/norms_reference.py`이다. 실제 314쪽, 3,156,652바이트, SHA-256 `c56cfbc534c6459f3d67af72cdb96fb150bd5bf002c753fd1ce25aea95b045c5`.
가공본 작성일 2026-10-09/v1. A는 문화체육관광부 고시 제2017-12호(2017-03-28)의 규정 40쪽, B는 국립국어원 2018-12-21 해설 264쪽이다. 가공본을 국립국어원 공식 신규 발행본으로 표시하지 않는다. 최신 규범 전체 대조는 미실시다.

## 활용 및 실행 경계

- 기존 `할수→할 수`, `몇일→며칠`, `로서·로써` 후보에 해당 조항과 가공본 실제 쪽수를 연결했다. SOURCE_URLS의 기존 공식 원문 링크는 보존한다. 나머지 두 로컬 후보는 이 PDF의 검증된 근거로 임의 승격하지 않는다.
- Ruleset v2는 출처 메타데이터 추가만 반영한다. 정규식·예외·허용 표기·피드백 등급·자동 수정 금지는 변경하지 않는다. 새 분석은 새 ruleset hash를 기록하고 과거 실행의 JSON snapshot은 수정하지 않는다.
- 앞으로 규칙을 확장할 때는 해당 원칙뿐 아니라 붙임·허용·예외와 정상/오류/예외 예문을 함께 검증한다. 색인의 짧은 설명을 실행 규칙으로 바로 변환하지 않는다. 표의 셀 관계는 PDF 원문을 확인한다.
- 분석 실행 중 이 PDF를 읽거나 외부 서버/AI로 전송하지 않는다. 포함된 문서 설명은 자료의 내용이며 사용자 승인이나 실행 지시로 취급하지 않는다.

## 공용 자료 등록 승인 — 2026-10-11

사용자가 제공한 PDF 전체 업로드 및 공용·주 참고자료 활용을 명시 승인했다. 이는 사용자 승인 기록이며 독립적인 저작권·최신 규범 대조 완료라는 뜻이 아니다.

기존 POST /api/source-documents를 재사용한다. PUBLIC / REFERENCE / DOWNLOAD, rightsConfirmed 및 구체적인 rightsInfo를 함께 등록한다. 정확한 승인 파일 SHA-256 + 검증된 지정 ADMIN 계정(ps25090@onedu.jje.go.kr)에만 314쪽 예외를 허용한다. 다른 파일·계정에는 기존 공용 추가 권한과 100쪽 제한을 유지한다. 파일명만 같은 파일에는 예외가 적용되지 않는다. 동일 파일 재등록은 기존 문서·revision을 반환하고 덮어쓰지 않는다.

실제 원본 314쪽·213,042자 추출 및 전체 바이트 다운로드는 격리 인증 fixture DB에서 검증했다. 실제 Google 인증 성공으로 간주하지 않는다. 사용자가 실제 Google 로그인 서비스에서 등록 완료를 알렸다. 읽기 전용 확인 결과 PUBLIC/REFERENCE/DOWNLOAD, 314쪽, 3,156,652바이트, 원본 파일 hash 일치, 213,042자, revision 1개, 지정된 검증 ADMIN 소유권 및 무결성/FK가 정상이다. 중복 등록하지 않았다. 현재 내장 브라우저의 로그인 세션은 접근 불가이므로 이 차례의 UI 재검증 완료로 간주하지 않는다. 운영 DB에는 자료·테스트 계정을 쓰지 않는다. PDF는 Git/public 정적 디렉터리 밖 기존 Data Root의 인증된 파일 저장소를 사용한다.

공식 출처 탐색: [국립국어원 한국어 어문 규범 자료실](https://www.korean.go.kr/kornorms/refr/refrList.do), [2018 해설 원자료 게시물](https://www.korean.go.kr/front/reportData/reportDataView.do?mn_id=45&report_seq=944). 목록에서 자료 존재를 확인했으며 이 가공본의 재배포 조건 확인을 대체하지 않는다.


## 2026-10-11 검사 보완 — Ruleset v3

v2의 출처 연결 이후, 가공본 실제 127·151·152·192쪽의 문맥·허용 표기를 대조했다. 현행 규범 전체 대조 완료를 뜻하지 않는다. 구형 spelling.RULES는 보존하고 v2의 reviewed catalogue만 갱신했다.

- gb-local-001: 할/볼/읽을/쓸 + 수 + 있/없의 제한된 붙여쓰기 후보와 활용형을 처리한다. 다할수·할수있다 같은 누락을 보완한다. 모든 의존 명사를 일반화하지 않는다.
- gb-local-002: 몇일뿐 아니라 몇 일도 후보로 표시한다. 직접 인용·등록된 고유 어휘는 보호한다.
- gb-local-005: 모든 로써를 표시하는 규칙을 학생으로써/독자로써/교사로써의 제한적 자격 문맥 확인으로 좁힌다. 수단·재료·시간의 정상 로써를 일괄 표시하지 않는다. 자동 교체하지 않는다.
- gb-local-006~008: 웃을뿐/아는대로/애쓴만큼의 제한된 의존 명사 후보. 제42항 및 실제 151~152쪽의 조사 용법 구별을 근거로 한다. 새 규칙은 확인 필요이며 친구뿐·법대로·고등학생만큼에는 적용하지 않는다.
- 보조 용언 붙여쓰기 허용(꺼져 간다/꺼져간다), 숫자 단위 및 순서(10개/제7항)를 오류로 판정하지 않는다. 인용·고유 어휘·규칙 비활성화·Unicode span을 검증했다.

실제 Flask API/격리 SQLite/Kiwi로 정상 짧은 에세이 0개와 혼합 에세이 7개를 확인했다. 원문 위치 및 반복 결정성 PASS. targeted 81 passed/14.73s/exit 0. 실행 명령·상태는 기존 checkpoint, 예문과 정확한 span은 artifacts/norms-analysis/simple-essay.json에 보존한다. 테스트 수집 오류와 optional rule 필드 처리 오류를 수정했고, 이어 다할수 누락을 수정한 후 최종 성공 결과를 기록했다. 테스트 약화·운영 데이터 쓰기·UI 변경·외부 AI 호출·자동 교체 없음. 기존 분석 JSON은 새 규칙으로 덮어쓰지 않는다. 새 실행은 v3/hash를 기록한다.


## 2026-10-11 전체 기본 규범 카탈로그

승인된 PDF hash를 고정하여 314쪽 전체를 NFC/LF로 정규화했다. 내부 단일 파일 backend/app/analysis/data/korean_norms_v1.json에 원문·공백·빈 쪽·출처 구간 및 예외 표지를 보존했다. 한글 맞춤법 57항(고시/해설 같은 조항 연결), 문장 부호 21항, 표준어 사정 26항, 표준 발음 30항의 총 134개 고유 조항이다. 재생성 도구 scripts/normalize_korean_norms.py는 승인 파일 hash/조항 순서를 검증하며 외부 호출하지 않는다.

기본 분석 v4는 카탈로그 version/hash와 실제 검사 연결 범위를 입력 context와 결과 manifest에 기록한다. 새 분석에만 적용하며 기존 snapshot을 변경하지 않는다. 3개 조항이 기존 검증된 검사 후보와 연결되고 131개는 REFERENCE_ONLY이다. 전체 조항을 실행 규칙으로 검증했다고 표시하지 않는다. 표의 정상/허용 표기를 오류 목록으로 추정하지 않고 문맥·예외·인용·고유 어휘 보호 및 자동 수정 금지를 유지한다. 앞부분 PDF 추출의 띄어쓰기 소실을 임의 복원하지 않았다. 현행 규범 전체 대조는 미완료다.

85 targeted tests PASS/15.08s/exit 0; 입력·결과 카탈로그 일치 assertion 추가 후 API 4 tests PASS/3.54s/exit 0. 정상 에세이 후보 0, 혼합 에세이 7, 반복 결정성·정확한 span 유지. 원문 재생성 hash, 134개 조항/예외 source span, 변조 차단 검증 포함. 격리 Waitress만 무초기화 재시작했다. UI 3개 파일·운영 DB·DPAPI·기존 spelling.py hash 보존. evidence artifacts/norms-catalogue/validation.json; G5 DEFERRED_FINAL_REVIEW, 기존 Runner 보호 baseline 조정 별도.


## 2026-10-11 전체 규범의 주 근거 지정 및 엔진 재검증

사용자 지정에 따라 제공 규범집 전체를 PRIMARY_NORMATIVE_BASIS로 명시했다. v5는 맞춤법·띄어쓰기·표준어·문장 부호의 기본 근거와 발음 참조 범위를 기록한다. provision_reference는 134개 모든 조항의 원문/해설/예외/쪽수/구간 hash를 반환하며 반환값 수정이 내부 원본을 변경하지 않는다. 전체 출처를 사용하는 것과 모든 조항의 자동 판정을 구현한 것은 구별한다. 실행 가능한 3개 조항 연결 및 기존 검증된 8개 detector를 유지하며 나머지 131개는 참조 전용이다. 규범집을 논리적 타당성·주장/근거 채점의 출처로 표시하지 않는다.

관련 86 tests PASS/15.21s/exit 0. 순수 엔진 테스트를 snapshot에서 전체 structure+규범 카탈로그 경로까지 확대하여 1 test PASS/1.60s/exit 0. 정상/혼합 에세이 후보 0/7 및 결정성·offset 보호 유지. 전체 엔진 10,000자 1.623초(초기 Kiwi 로딩 포함), 30,000자 0.639초(같은 프로세스 warm), 각각 445/1334문장, 구간 재결합 원문 일치/JSON 검증 PASS. 처리량 보장이 아니다. 측정 harness의 version_id 누락을 수정했고 엔진 우회 없음. 증거 artifacts/norms-catalogue/revalidation.json, long-analysis.json. UI·운영 DB·원본 PDF·DPAPI hash 보존. 격리 Waitress만 무초기화 재시작. G5 DEFERRED_FINAL_REVIEW, 기존 Runner 보호 baseline 문제 별도.
