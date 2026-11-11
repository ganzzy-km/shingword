# V2.1 Release Candidate 적용 계약

최신 사용자 지시로 V2.1의 운영 0003→0004 migration·서버 중지/재시작·프런트엔드 교체·출시 승인서 갱신을 조건부 승인받았다. 후보·G4·격리 migration·새 검증 백업 및 데이터 보존 검사를 통과한 경우에만 순서대로 적용한다. V2.2 개발·migration은 격리 환경으로 제한한다. G5는 `WAIVED_BY_USER`이며 독립 검토 PASS가 아니다.

## 후보와 증거

- 최신 반응형 후보 빌드: `artifacts/mobile/build`; 후보 식별·해시: `artifacts/mobile/release-candidate.json`. 이전 V2.1 ZIP은 보존되지만 최신 모바일 후보와 혼동하지 않는다.
- 운영 승인서 초안: `artifacts/mobile/beta-release.candidate.json`, 반드시 `approved:false`로 보관한다. 기존 운영 승인서를 자동 덮어쓰지 않는다.
- 실제 격리 Flask/Waitress/HTTPS/SQLite/Kiwi 통합: `artifacts/mobile/v21-regression/integration-results.json`. 인증은 시험 서버의 가상 세션이다. 운영 Google 실로그인을 새로 검증한 결과와 혼동하지 않는다. 태블릿·모바일 세로/가로 두 테마 검증은 `artifacts/mobile/responsive-results.json`이며 터치 에뮬레이션을 실제 기기 검증으로 표시하지 않는다.
- 운영 DB 읽기 전용 Online Backup 복사본의 0004 upgrade·원본 데이터 보존·FK·무결성·암호화 백업·격리 복원: `artifacts/v21/operating-copy-results.json`. 원본은 0003 그대로다.
- 종합 브라우저 흐름: `artifacts/v21/system/evidence.json`. 물리 모바일의 길게 누르기 및 실제 재부팅은 미검증이다.

## 승인 후 적용 순서

프로젝트 폴더의 일반 PowerShell에서 기존 Python 환경을 사용한다. 실제 실행 여부는 최신 Checkpoint의 V2.1 운영 배포 기록을 참조한다.

1. 후보 해시/G4를 재확인한다. 운영 상태·현재 배포 파일·승인서와 설정을 보존한다. 이전 버전의 완전한 백엔드 소스 복구본이 확보되지 않았다면 자동 롤백 가능하다고 가정하지 않는다. 새 후보에 비밀값·운영 DB·업로드·시험 DB를 섞지 않는다.
2. 승인된 짧은 점검 시간에 기존 STOP으로 터널과 해당 실행의 writer를 종료한다. 수동 STOP 상태에서 유지보수 작업이 재공개하지 않는 기존 계약을 유지한다.

   ```powershell
   .venv\Scripts\python.exe backend\network_service.py stop --operating
   .venv\Scripts\python.exe backend\privacy_service.py backup --pre-migration-backup
   ```

   백업은 기존 C: 암호화 로컬 저장소와 DPAPI 키를 사용한다. 새 파일을 생성하며 이전 백업을 덮어쓰거나 사전 백업 단계에서 정리하지 않는다. Online Backup·파일 일관성·exclusive storage lease·격리 복원 성공 후에만 `.verified.json`을 발급한다. 실패하거나 writer가 남아 있으면 중단한다.

3. 방금 생성된 백업의 정확한 경로를 지정한다. migration은 검증된 **0003** 백업 생성 후 10분 이내에만 가능하며, 백업과 현재 DB의 모든 기존 행 및 연결 파일이 일치해야 한다.

   ```powershell
   $env:GEULBIT_DATA_ROOT = 'C:\Users\USER\GeulbitData'
   $env:GEULBIT_VOLUME_ID = [Environment]::GetEnvironmentVariable('GEULBIT_VOLUME_ID', 'User')
   .venv\Scripts\python.exe backend\storage_cli.py migrate --verified-backup '<방금 검증된 geulbit-*.gbb의 전체 경로>' --confirm-v21
   .venv\Scripts\python.exe backend\storage_cli.py check
   .venv\Scripts\python.exe backend\privacy_service.py backup
   ```

   0004는 사용자 주석 테이블·인덱스·트리거의 additive revision이다. 기존 ID·소유권·버전·분석 이력을 추정하거나 수정하지 않는다. 0003 백업 영수증은 0004의 백업 주기에 포함하지 않으므로 첫 0004 백업과 격리 복원이 필요하다. 모든 검사가 끝날 때까지 서비스를 시작하지 않는다.

4. 보존한 이전 `dist`를 유지하면서 후보 빌드를 적용한다. 후보의 런타임 코드/빌드 해시가 실제 배치와 일치하고 0004 백업 영수증이 유효한 것을 확인한 뒤에만 별도 승인에 따라 운영 승인서를 갱신한다. `approved:true`는 배포 승인과 적용 검증 후에만 설정한다. 비밀값과 기존 Google/ngrok/보존 정책은 교체하지 않는다.

   ```powershell
   .venv\Scripts\python.exe backend\network_service.py start --operating
   .venv\Scripts\python.exe backend\network_service.py status --operating
   ```

5. 고정 ngrok HTTPS·Host/Origin 차단·Google callback을 확인한다. 운영자의 실제 Chrome 로그인에서 기존 개인 글 목록, 로그아웃과 권한 차단을 확인한다. 운영 DB에 자동 시험 계정/에세이를 만들지 않는다. 사용자 주석 확인이 필요하면 운영자가 동의한 자신의 글에서 수행한다. AI 설정은 이번 후보 작업에서 활성화하거나 외부 전송하지 않았다.

## 실패 및 재개

- 단계별 성공 결과가 없으면 다음 단계로 이동하지 않는다. Gate/해시 검사를 끄거나 START에서 DB를 자동 생성하지 않는다.
- migration·보존 확인 실패 시 서버와 터널은 OFF로 유지한다. 운영 DB를 지우거나 강제 downgrade·백업 덮어쓰기를 하지 않는다. 오류 코드와 중단 단계만 기록한다.
- 기존 복원은 **새 격리 디렉터리**만 허용하며 최신 삭제/탈퇴/권한 회수 재적용, 세션 무효화, 외부 호출 차단을 유지한다. 0003 백업과 0004 권한 원본을 혼합하는 운영 복원은 자동 승인하지 않는다. 백업을 보존하고 별도 복구 검증 후 재개한다.
- START 실패 시 운영 승인서/코드 해시·schema·검증 백업 상태를 확인한다. 원인 해결 전 무한 재시작하지 않는다.
- Checkpoint의 V21RC와 후보 해시에서 재개한다. 완료된 구현이나 migration을 반복하지 않는다.

## 한계

주장·근거는 후보와 구조적 관계 단서다. 선정된 기준 예문 통과를 일반적인 논증 정확도 보장으로 해석하지 않는다. 불명확한 맞춤법은 제안/확인 필요로 유지하며 자동 치환하지 않는다. C: 원본과 로컬 백업은 디스크 전체 장애 시 함께 손실될 수 있다. 운영 반영과 새 실제 Google 로그인 검증은 승인 후 별도 수행한다.
