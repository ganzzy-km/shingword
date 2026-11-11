# 사용자 주석 계약 — 개발 검증 / 운영 미반영

- 기존 AIInteraction.note는 AI 실행에 종속하므로 재사용하지 않는다. 사용자 메모는 `user_annotations` 한 테이블에 저장한다. 분석 JSON·본문·analysis_run을 수정하지 않는다.
- `0004_user_annotations`는 0003 후속 additive revision이다. 기존 migration, ID, 데이터 및 소유권은 변경하지 않는다. 새 테이블·인덱스·원문/소유권 검증 trigger만 추가한다. 운영 DB는 0003 그대로 유지한다. 운영 적용은 별도 승인 사항이다.
- 필드: UUID, user_id, writing_id, essay_version_id, span_start/end, quote, content(1–5000자), revision_number, created_at, updated_at, original_anchor(JSON). 최초 앵커는 trigger로 불변이며 사용자의 명시적 재연결은 현재 앵커만 갱신한다.
- 좌표: 정규화된 불변 버전의 Unicode code point `[start,end)`. 서버는 해당 에세이의 완료된 분석 결과가 있는 버전만 허용하고 실제 구절을 비교한다. 동일 구절/같은 구간의 여러 주석을 허용한다.
- API: `GET/POST /api/writings/{id}/annotations`, `GET/PATCH/DELETE /api/annotations/{id}`. 생성은 `{essayVersionId,span,quote,content}`. 수정은 `{revisionNumber,content}`; 명시적 재연결은 앵커 3필드도 포함. 삭제는 `{revisionNumber,confirmation:"삭제"}`. stale revision=409, 잘못된 입력=400, 소유권/만료=404. 기존 세션·CSRF 방어를 재사용한다. ADMIN도 타인 주석을 조회할 수 없다.
- 메모 변경은 Writing의 updated_at/expires_at/revision이나 버전·분석 개수를 바꾸지 않는다. 에세이 삭제·만료·탈퇴 및 복원 시 기존 graph 삭제의 FK cascade로 메모도 정리된다. 메모 본문은 감사 로그에 넣지 않는다.
- 프론트엔드는 기존 textarea와 동일한 UTF-16 어댑터·beforeinput edit map을 쓴다. 검증된 연속 편집만 위치 이동하며 겹치는 수정/증명할 수 없는 이동은 `현재 본문에서 위치 확인 필요`로 남긴다. 새로고침 후 임의 quote 검색으로 다시 붙이지 않는다. 다른 분석 버전의 메모는 별도로 표시한다. 재연결은 분석된 현재 본문에서 선택한 구절로만 가능하다.
- 기본/책장 공통 패널과 데이터. 작은 말풍선은 글자를 가리지 않는 여백에 배치한다. 같은 줄 여러 메모는 여백 아이콘을 공유하고 목록에서 각 메모를 선택한다. 책의 페이지는 원문 주소를 유지한다. 기존 주장·근거·관계 표시는 그대로 사용한다.
- 실패 입력 보존: 저장 네트워크/충돌/세션 만료 메시지를 구분한다. 주석 저장에만 세션 만료 시 편집 패널을 즉시 없애지 않는 옵션을 사용한다. 서버의 401 및 CSRF 검증은 유지하고 CSRF 캐시를 폐기한다. 새 탭 재로그인 링크를 제공한다. 브라우저를 닫거나 새로고침하면 저장하지 않은 메모는 보존되지 않는다.
- 격리 검증: API/소유권/만료/탈퇴/백업 복원, 0003→0004 기존 행 보존·실패 rollback·재시도·복원. 크롬 두 테마 × 1440/820/390, CRUD/입력 실패 보존/선택/여백 아이콘/다른 페이지 이동/STALE. 실제 격리 Kiwi 결과와 가상 CRUD 전송 fixture를 구분한다. 모바일 장치의 네이티브 긴 터치 선택은 실기기 미검증이다.
- 다음 실행: 운영 migration 및 배포 승인 전까지 개발 결과만 보존. 운영 release receipt를 갱신하거나 서버를 재시작하지 않는다. 0004 요구 버전으로 변경한 개발 코드를 운영 0003 DB에 바로 실행하지 않는다. 기존 0003 백업은 보존하며 이전 운영 도구로 사용할 수 있다. G5=`WAIVED_BY_USER` 유지.
