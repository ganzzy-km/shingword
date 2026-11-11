# Google OIDC / HTTPS 운영 준비

운영 Data Root는 C:\Users\USER\GeulbitData, DB head는 0003_resource_ownership. 현재 Google 실계정 연결은 미검증이다. `.env.example`은 빈 설정 예시이며 서버가 자동 로드하지 않는다. 기존 DB 초기화/migration/사용자 추가를 설정 과정에서 실행하지 않는다.

## 필요한 외부 설정

1. Google Cloud Console 프로젝트의 OAuth 클라이언트를 **웹 애플리케이션**으로 만든다. Client ID/Secret은 아래 숨김 입력 CLI를 통해 기존 DPAPI CurrentUser 비밀 저장소에 등록한다. 서버 환경변수도 지원하지만 대화·명령 인수·Git 파일에 비밀값을 넣지 않는다.
2. Branding/동의 화면, Audience(조직 내부 또는 승인된 외부 대상), 테스트 상태의 테스트 사용자, 필요한 개인정보 안내를 구성한다. 최소 scopes는 `openid email profile`. 도메인·계정 허용 정책을 임의로 추가하지 않는다. 인증 성공 이후에도 신규 USER는 PENDING_APPROVAL이다.
3. 승인된 고정 HTTPS origin을 `GEULBIT_PUBLIC_ORIGIN`에 넣는다. 예: `https://school.example`. Authorized redirect URI와 `GEULBIT_GOOGLE_REDIRECT_URI`는 모두 정확히 `https://school.example/api/auth/callback`이어야 한다. path/port/끝 slash도 일치해야 하며 query/fragment/credentials는 금지한다. [Google 공식 OIDC 설정 및 redirect 설명](https://developers.google.com/identity/openid-connect/openid-connect).
4. 서버 서명 비밀은 암호학적 난수로 생성하여 기존 DPAPI 저장소에 등록했다. 사용자가 개발 검증용 세션 3600초와 OIDC state 300초를 승인했다. 비밀값은 Git/.env.example/클라이언트/로그에 기록하지 않는다.
5. 실인증 외부 사용을 승인한 뒤에만 `GEULBIT_GOOGLE_EXTERNAL_APPROVED=1`로 설정한다. 키/HTTPS/redirect/TTL이 갖춰지기 전에는 실제 Google 연결을 시도하지 않는다.

## 실행 경계

- Waitress는 `APP_HOST=127.0.0.1` 또는 `::1`로만 바인딩한다. 기본 HTTP localhost 상태 점검과 로그인 가능한 HTTPS 서비스는 별개이다. Secure 쿠키를 localhost 개발 목적으로 약화하지 않는다. 합성 OIDC 계약 테스트와 사용자 승인된 실제 Google 격리 검증을 구분한다.
- 기존 Cloudflare 계획대로, 별도 승인된 고정 HTTPS Tunnel이 localhost Waitress로 연결한다. 이번 작업은 Tunnel 설치·생성·실행·외부 공개를 하지 않는다. 변하는 Quick Tunnel URL은 고정 운영 OAuth 설정을 대신하지 않는다. 과거 학교 실행 스크립트에는 build/migration 단계가 있으므로 이번 검증에서 실행하지 않는다.
- 승인된 loopback 프록시일 때만 `GEULBIT_TRUSTED_PROXY=127.0.0.1`(또는 `::1`)을 명시한다. 1 hop의 `X-Forwarded-Proto`만 신뢰한다. forwarded Host/IP는 신뢰하지 않고 그 외 프록시 헤더는 Waitress가 제거한다. 원래 Host는 승인한 origin의 host/port와 일치해야 한다. wildcard/서브넷/임의 원격 IP는 거부한다. [Waitress 공식 프록시 설정](https://docs.pylonsproject.org/projects/waitress/en/latest/arguments.html).
- Flask TRUSTED_HOSTS는 localhost 및 승인한 origin 호스트로 제한한다. origin이 설정된 사용자 API는 HTTPS와 정확한 authority를 요구한다. 인증되지 않은 API, 다른 사용자의 글, ADMIN의 개인 글 접근 차단을 유지한다. [Flask Host·쿠키 보안](https://flask.palletsprojects.com/en/stable/web-security/).
- 최초 ADMIN 후보는 사용자가 지정한 `ps25090@onedu.jje.go.kr`이다. **이미 OIDC로 검증된 계정**에 대해 기존 bootstrap CLI를 사용한다. 실제 Google issuer·서명·audience·nonce·만료 검증 후 해당 계정의 검증된 sub로 격리 DB에서만 bootstrap했다. 운영 DB에는 적용하지 않았다. 첫 로그인 자동 승격은 없다.
- 쿠키는 HttpOnly/Secure/SameSite=Lax. 저장 등 상태 변경에는 X-CSRF-Token이 필수. 로그아웃·비활성화·승인 상태 변경은 session_version을 올려 이전 쿠키를 무효화한다.

## 현재 판정과 재개

실제 Google: PASS_ISOLATED. 지정 계정의 PENDING 승인 대기 → 명시적 ADMIN bootstrap → 새 Google 로그인 → 저장·자동저장·분석·기본/책장 테마·PDF 다운로드 → 실제 세션 로그아웃 API 및 이후 401을 확인했다. 운영 DB는 읽기 전용 검사에서 revision 0003_resource_ownership, 무결성 정상, FK 오류 0, 사용자/에세이 0이며 파일 해시가 동일하다. 증거는 backend-checkpoint.json의 actualGoogleValidation과 artifacts/auth-live/evidence.json. Mock 계약 테스트는 실인증 증거와 별도다. 프로젝트 G5는 DEFERRED_FINAL_REVIEW이다.

BAZE_API_KEY는 기존 DPAPI CurrentUser 저장소에 보존한다. 저장소 항목 갱신 과정은 기존 암호화 저장소 전체를 내부적으로 읽지만 BAZE 키를 출력·복사·로그 기록·테스트 전송하지 않는다. 처리 조건·모델·비용·사용 한도가 확정되기 전까지 외부 AI는 비활성화한다. 보존 정책/최종 출시 승인도 별도다.

## localhost HTTPS 개발 검증 재개

승인된 공개 설정은 Windows 현재 사용자 환경에 등록했다. 개발 launcher는 해당 설정을 직접 읽으므로 터미널 재시작에 의존하지 않는다.

```text
GEULBIT_PUBLIC_ORIGIN=https://localhost:8770
GEULBIT_GOOGLE_REDIRECT_URI=https://localhost:8770/api/auth/callback
GEULBIT_TRUSTED_PROXY=127.0.0.1
GEULBIT_SESSION_MAX_AGE=3600
GEULBIT_OIDC_STATE_TTL=300
```

Google Cloud Console의 Branding/Audience를 구성하고 Clients에서 웹 애플리케이션 클라이언트를 만든다. 개발 테스트 대상에 지정 계정을 포함한다. Authorized redirect URI는 정확히 `https://localhost:8770/api/auth/callback`이다. 서버 Authorization Code Flow에는 JavaScript origin 등록이 필수는 아니다. scopes는 `openid email profile`이며 동의 화면에 추가 권한을 임의로 요구하지 않는다. [Google 공식 설정](https://developers.google.com/identity/openid-connect/openid-connect).

프로젝트 폴더의 **일반 Windows 터미널**에서 다음 명령으로 두 값을 숨김 입력한다. 비밀값을 대화로 보내지 않는다. 이미 등록된 자격증명이 있으면 덮어쓰지 않고 중단한다.

```powershell
.venv\Scripts\python.exe backend\auth_setup.py google
.venv\Scripts\python.exe backend\auth_setup.py status
```

저장 위치는 승인된 Data Root의 `operational\secrets.dat`이며 Windows DPAPI CurrentUser 암호화를 재사용한다. 세션 비밀 및 기존 BAZE 항목을 보존한다. TESTING 앱은 운영 비밀 저장소를 자동 읽지 않는다. 일반 서버 시작에서는 비밀값이나 DB를 새로 생성하지 않는다.

localhost TLS는 Python 표준 라이브러리 프록시가 종료하고 Waitress는 HTTP 앱 서버로 동작한다. 두 프로세스 모두 `127.0.0.1`에만 바인딩한다. TLS 프록시는 고정 upstream `127.0.0.1:5000`만 사용하고 Host `localhost:8770`을 요구한다. 외부 공개용 서버나 Cloudflare 구성은 아니다. 인증 요청 URL·쿠키·본문의 접근 로그를 기록하지 않는다.

인증서는 localhost SAN만 가진 비-CA 개발 인증서이다. Windows **CurrentUser Root** 신뢰 등록이 완료됐다. 지문은 `129201E8C2CD52F64047977DA7156F5CCA375ACA`, 만료는 2027-01-08 21:13:57 KST이다. 저장 위치는 `operational\tls`이며 개인키는 암호화된 PKCS8, 암호는 기존 DPAPI 저장소에 있다. TLS 검증을 끄거나 Machine 신뢰 저장소를 변경하지 않았다.

Google 자격증명 등록 후 첫 실행에만 다음 명령으로 **새 격리 서비스 DB**를 명시적으로 초기화한다. 운영 DB를 사용하거나 다시 초기화하지 않는다. `--init`은 기존 저장소를 덮어쓰지 않는다. 자격증명이 없으면 초기화 전에 중단한다.

```powershell
.venv\Scripts\python.exe backend\run_auth_dev.py --root C:\Users\USER\GeulbitData\temp\oidc-dev-localhost --init --allow-google
```

후속 실행은 `--init`을 빼고 실행한다. 별도 터미널에서 아래 TLS 프록시를 실행한 뒤 브라우저로 `https://localhost:8770`을 연다.

```powershell
.venv\Scripts\python.exe backend\local_https_proxy.py
```

`--allow-google`는 이 격리 개발 프로세스에만 실제 Google 인증을 허용한다. BAZE·자동 삭제는 활성화하지 않는다. 최초 로그인은 승인 대기이다. 지정 계정의 실제 로그인에서 검증된 sub와 email_verified를 확인한 후 아래 명령을 실행하고 다시 로그인한다. sub를 추정하거나 다른 계정을 ADMIN으로 만들지 않는다.

```powershell
.venv\Scripts\python.exe backend\run_auth_dev.py --root C:\Users\USER\GeulbitData\temp\oidc-dev-localhost --allow-google --bootstrap-subject <실제로_검증된_sub> --confirm-account ps25090@onedu.jje.go.kr
```

지정 계정의 실제 로그인·bootstrap·재로그인과 격리 서비스 흐름은 검증됐다. 다른 실제 Google 계정의 일반 USER 승인 흐름은 미실행이며 관련 권한·CSRF·IDOR·세션 무효화는 격리 계약 테스트에서 검증한다. 기존 UI에는 로그아웃 버튼이 없어 임시 동일 origin 검증 페이지에서 기존 API를 호출했고 이후 세션 401을 확인한 뒤 검증 파일을 정리했다. UI 코드 변경은 없다. 짧은 가상 글의 책 열기는 확인했으나 긴 글 페이지 넘김은 이번 실인증 검증에서 반복하지 않았다. 실제 Windows 인증서 검증과 Edge HTTPS 접속, 합성 쿠키의 Secure/HttpOnly/SameSite=Lax 및 운영 DB 읽기 전용 증거는 `artifacts/auth-local-tls`에 있다. 합성 쿠키 검증은 실제 Google 세션 성공을 뜻하지 않는다.

## 실제 로그인 검증 이후 재개

Google 자격증명은 DPAPI에 등록되어 있다. 갱신이 필요할 때만 일반 Windows 터미널에서 `.venv\Scripts\python.exe backend\auth_setup.py google-secret`으로 Secret을 숨김 입력한다. 기존 Client ID·BAZE·세션 키는 보존한다. 서버는 갱신 후 재시작해야 한다.

```powershell
.venv\Scripts\python.exe backend\run_auth_dev.py --root C:\Users\USER\GeulbitData\temp\oidc-dev-localhost --allow-google
# 별도 터미널
.venv\Scripts\python.exe backend\local_https_proxy.py
```

기존 격리 DB에 `--init`을 다시 실행하지 않는다. ADMIN bootstrap도 완료됐으므로 반복하지 않는다. 로그아웃 검증으로 현재 글빛 세션은 종료됐다. https://localhost:8770 에서 Google 로그인하면 같은 격리 서재를 다시 사용할 수 있다. 운영 DB에 로그인 사용자나 테스트 글을 생성한 검증으로 해석하지 않는다.

## P14 ngrok 고정 주소 격리 시험 (2026-10-11)

외부 주소 https://crushable-movie-usable.ngrok-free.dev, callback /api/auth/callback. 사용자가 Google Cloud callback 추가 완료를 알렸다. 실제 Google 외부 callback 성공과는 별도다. localhost 설정과 기존 서버는 유지한다. 운영 DB/파일을 외부 upstream으로 연결하지 않는다.

```powershell
# 일반 터미널에서 숨김 입력. 토큰 다음 시험 접속 비밀번호 입력.
.venv\Scripts\python.exe backend\auth_setup.py ngrok
.venv\Scripts\python.exe backend\network_service.py prepare
.venv\Scripts\python.exe backend\network_service.py start
.venv\Scripts\python.exe backend\network_service.py status
.venv\Scripts\python.exe backend\network_service.py stop
.venv\Scripts\python.exe backend\network_service.py restart
```

접속 사용자명 geulbit. 비밀번호는 16자 이상이며 DPAPI에 저장한다. prepare는 지정된 새 격리 root에만 명시적으로 초기화하고 기존 저장소는 검사만 한다. 이 adapter는 기존 storage/DPAPI/OIDC/Waitress를 재사용한다. upstream http://127.0.0.1:5070, root C:/Users/USER/GeulbitData/temp/ngrok-dev-local. 토큰은 ngrok 자식 프로세스 환경으로만 전달하고 명령행·Git·ngrok yaml에 저장하지 않는다.

ngrok은 고정 URL/inspect=false, 관리 UI 및 remote management 비활성으로 구성한다. 접근 비밀번호/HTTPS Host/Origin/120회-60초 전체 요청 제한은 격리 WSGI 경계이다. 이는 운영 부하 설정 확정을 대체하지 않는다. 검증된 ps25090 계정만 callback을 허용하고 다른 계정은 DB 기록 전에 거부한다. 최초 ADMIN은 실제 검증된 sub와 기존 명시적 bootstrap 계약을 따라야 한다.

start는 private gate/health 검사 후에만 ngrok을 연다. 실패하면 이번 프로세스만 정리한다. start-local은 외부 공개 없이 사용한다. PID/image/생성 시각으로 소유 프로세스를 확인하며 서버 STOP은 named event로 Waitress.close를 요청한다. 타 서버를 종료하지 않는다. Windows 자동 시작/상시 공개/AI 호출/자동 삭제/G5 PASS 없음.

개인정보 안내 초안은 backend/config/privacy.example.json이다. 실제 수집 항목·별도 AI 동의·만14세 확인을 담되 draft/enabled=false이다. 보존 제안과 운영자/연락처/감사 보존 미확정 사항을 출시 전에 승인해야 한다. 일반 USER 자동 ACTIVE 가입은 아직 활성화하지 않으며 기존 PENDING 계약을 우회하지 않는다. 최신 목표의 동의 후 ACTIVE 가입은 정책 확정 후 후속 구현/검증 대상이다.

공식 CLI 근거: https://ngrok.com/docs/gateway/agent/cli 및 https://ngrok.com/docs/gateway/agent/config/v3. ngrok 중계 보존 조건 전체를 검증했다고 주장하지 않는다. 시험 완료 후 stop을 실행한다.

### P14 실제 외부 전송 검증 재개

ngrok/시험 접속 키는 DPAPI 등록 완료. 실제 START/STATUS/STOP/RESTART와 고정 HTTPS health/home 200, 시험 인증 없는 요청 401, 다른 Origin 변경 요청 403, 허용되지 않은 Host 400을 확인했다. Windows venv 런처와 worker PID 차이 때문에 STOP 이벤트를 찾지 못한 경로를 수정했다. 서버와 관리 CLI는 PID와 별개인 임의 event ID를 공유하며 기존 PID/image/생성 시각 소유권 검사와 정상 종료 계약은 유지한다.

관련 테스트 99개 PASS. 실제 Google redirect/callback 주소와 새 state/nonce, Secure/HttpOnly/SameSite 쿠키를 확인했다. Chrome ERR_BLOCKED_BY_CLIENT로 실제 계정 로그인은 Edge 사용자 조작 대기이며 토큰 검증·신규 계정 승인·외부 브라우저 서비스 흐름 PASS로 기록하지 않는다. 다른 외부 네트워크 기기 검증도 미실시다. 임시 시험은 지정 계정만 허용하고 일반 USER 자동 ACTIVE·자동 삭제·상시 배포는 비활성이다. 자세한 현재 실행 증거는 기존 Checkpoint의 p14Network.latestResume와 artifacts/network/live-resume-evidence.json이다.

### P14 Edge 실제 인증 이후 복구

실제 지정 Google 계정의 PENDING → 검증된 sub를 이용한 명시적 격리 ADMIN bootstrap → 새 로그인 정상 홈을 확인했다. 실제 세션의 저장·자동저장·충돌·원문 보존·분석·정상/오류 구분·span 9개 항목 PASS이며 두 테마/PDF/로그아웃 최종 결과는 대기다. 첫 홈의 workspace/settings 병렬 요청에서 작업 공간 중복 INSERT가 재현됐다. SQLite 충돌 안전 INSERT와 소유권 재확인을 적용하고 관련 24개 및 V2 회귀 159개가 통과했다. DB 무결성 확인 후에만 격리 서버를 재시작했다.

반복 시험 인증창을 피하기 위해 Basic 인증 성공 후 geulbit_private_test 서명 쿠키를 발급한다. 정확한 HTTPS Host를 요구하며 Domain 속성 없이 Secure/HttpOnly/SameSite=Lax, 비슬라이딩 3600초로 제한한다. 서명은 기존 시험 비밀번호와 호스트에 종속되며 새 비밀을 저장하지 않는다. 쿠키의 위조·만료·미래 발급 시각·다른 호스트는 거부한다. 배경 API의 시험 인증 실패에는 Basic challenge를 보내지 않고 401만 반환한다. 페이지 이동은 여전히 시험 인증을 요구한다. Google 세션이 없거나 무효하면 별도의 ACCESS_DENIED 401이고, 시험 쿠키는 Google 세션·CSRF·사용자 권한을 대신하지 않는다. 실제 외부에서 쿠키만 사용한 health 200, Google 세션 없는 API 401, callback state 없는 요청 401 및 추가 Basic challenge 없음 확인. 관련 34개 PASS. Edge에서 반복 인증창이 해소됐는지와 남은 서비스 흐름은 사용자 실행 결과로 확정한다.

### P14 최종 격리 검증 결과

사용자가 실제 Edge Google 세션 검증 결과 PASS를 제공했다. 앞서 확인한 저장/자동저장/낙관적 충돌/초안 보존과, 완료된 분석 재사용/버전 원문/규칙 및 span/기본·책장 테마/같은 글·분석/PDF 바이트와 다운로드 시작/로그아웃 후 세션·원문 401까지 통과했다. PDF 다운로드 파일을 별도로 열거나 별도 외부 네트워크 기기를 검사한 증거는 아니다. 새 Edge 스크린샷도 수집하지 않았다.

최종 backend 363 PASS, 프론트 typecheck/build 및 계정 10개·10k/30k 페이지/피드백 span 테스트 PASS. 시험 쿠키 검증은 요청당 한 번으로 줄였다. 최종 빌드 이후 실제 START/STATUS/STOP 재검증과 이전 RESTART 검증을 완료했다. 서버/터널은 정상 종료했고 dist의 임시 검증 페이지/스크립트는 제거됐다. 운영 DB는 revision 0003, integrity ok, FK 오류 0 및 원래 hash 동일이다. 비밀 저장소/운영 사용자 데이터/UI 디자인은 보존한다. 재개는 기존 network_service.py start/status/stop/restart만 사용한다. 최종 증거는 artifacts/network/final-service-evidence.json 및 기존 Checkpoint에 통합했다. 운영 개인정보·일반 USER 가입·삭제/외부 백업·Runner 보호 baseline·G5 조건은 별도이며 자동 배포/자동 시작/AI 호출/삭제 활성화는 없다.


## P13 출시 안전성 준비 (2026-10-11, 운영 활성화 아님)

현재 승인 기산점은 마지막 성공한 실제 NFC/LF 본문 변경 후 7일이다. 제목 변경·동일 저장·조회·동일 본문 분석은 연장하지 않는다. `GEULBIT_PERSONAL_DATA_POLICY=last-successful-body-change/7d-v1`이 이 기산점만 선택한다. 기존 본문의 기산점을 추정하거나 운영 expires_at을 backfill하지 않는다. RETENTION_APPROVED / RETENTION_DATES_VERIFIED / RETENTION_BACKUPS_VERIFIED는 모두 운영 비활성이다.

소유자 글 삭제와 `/api/account/withdraw`(CSRF, confirmation=WITHDRAW)는 격리 테스트에서 검증한다. 탈퇴는 INACTIVE와 session_version 변경, 개인 글·자료 정리, 동의 철회를 수행한다. 계정·동의 기록은 미정 보존기간으로 임의 삭제하지 않는다. DB 삭제 후 기존 app_settings의 privacy_job outbox에서 파일을 정리한다. 실패하면 FILES_PENDING 및 HTTP202로 남고 재시도한다. 공개 자료와 공유 참조는 보호한다. 알려진 보안 감사 이벤트는 30일, 관리자 이벤트는 90일의 정리 함수로 검증한다. 알 수 없는 기존 로그·동의 기록의 기간을 추정하지 않는다.

백업은 기존 SQLite Online Backup을 재사용한다. 모든 쓰기 서버가 종료된 상태에서 DB와 참조 파일, revision, SHA-256 manifest를 AES-256-GCM으로 묶는다. 안전한 최소 구현의 bundle 상한은 64MiB이며 초과하면 차단한다. DB를 복사하는 중 분석 작업·파일 삭제 대기가 있으면 차단한다. 별도 정상 NTFS volume과 physicalDiskId를 둘 다 고정해야 하며 동일 물리 디스크·미지정 E:는 거부한다.

아직 장치 설정과 백업 키는 없다. 장치 지정 후 운영자가 `C:/Users/USER/GeulbitData/operational/backup-config.json`에 approved=true, directory, volumeId, physicalDiskId, retentionDays=7, frequencyHours=24를 등록해야 한다. 비밀키는 JSON에 넣지 않는다.

```powershell
.venv\Scripts\python.exe backend\privacy_service.py status
# 장치·키 복구 계획 확정 뒤에만 기존 DPAPI에 추가(다른 키 보존)
.venv\Scripts\python.exe backend\privacy_service.py backup-key
# 모든 글빛 쓰기 서버를 종료하고 장치 승인 후 실행. 하루 미만이면 NOT_DUE.
.venv\Scripts\python.exe backend\privacy_service.py backup
# 지정 백업 폴더의 암호화 파일만 새 Data Root/temp/restore-* 격리 폴더로 복원
.venv\Scripts\python.exe backend\privacy_service.py restore --archive <승인된암호화백업> --isolation-name restore-manual-check
```

복원은 최신 원본 DB의 삭제 ledger·현재 리소스·계정 상태를 확인하고 삭제/만료/탈퇴/권한 회수를 재적용한다. 모든 세션을 무효화하고 AI를 끄며 restore_quarantine으로 정상 서버 시작을 막는다. 최신 권한·삭제 기록이 없거나 전체 원본 DB를 잃으면 복원을 차단한다. **별도 장치에 최신 삭제 기록을 내구성 있게 보존하는 재해복구 경로와 DPAPI 키 복구는 아직 출시 Gate를 통과하지 않았다.** 이 단계를 기존 정상 백업·완전 재해복구로 표시하지 않는다. 성공한 자동 격리 복원 검사 폴더는 정리하며, 불완전 복원은 RESTORE_BLOCKED로 차단한다. 운영 백업·일정 등록·자동 삭제는 실행하지 않았다.

인터넷/터널 장애는 기존 network_service status로 확인한다. 시험 인증 실패는 Google 인증 성공으로 처리하지 않는다. 기존 start/status/stop/restart를 재사용하며 운영 서버나 미소유 프로세스를 종료하지 않는다. 최종 검증 후 터널을 종료한다. 운영 연락처와 일반 가입 동의 적용, 별도 장치, 계정/동의 기간, Runner baseline 정합성, G5가 남아 있다.

ngrok 공식 무료 한도(2026-10-11 조회)는 월 전송 1GB·HTTP 20,000회, 지속 HTTP 4,000회/분, 온라인 endpoint 최대3이다. 글빛 시험 제한 120회/60초는 별도 보호 정책이며 이 수치를 늘리지 않았다. 계정 Usage와 제공자 변경을 출시 전에 확인한다. 무료 안내 페이지·PC 전원·인터넷 중단·한도 초과로 상시 서비스가 보장되지 않는다. 출처: https://ngrok.com/docs/pricing-limits/free-plan-limits


## 지인 대상 백업 없는 배포 정책 및 탈퇴 기록 (2026-10-11)

사용자는 백업 없이 지인에게만 배포하고 개인정보 문의·삭제 요청을 운영자에게 직접 연락하는 방식으로 승인했다. 별도 백업 장치·암호화 백업 Gate는 이 제한 배포 모드의 필수 조건에서 제외한다. 백업 사용 모드의 기존 검증은 유지하며 기존 백업을 삭제하지 않는다. 복구 가능성을 보장하지 않으며 실제 공개는 별도 최종 승인 전까지 하지 않는다. 정책 예제의 enabled 및 실제 운영 정리 설정은 여전히 false다.

탈퇴 시 기존 세션 무효화·개인 데이터 정리를 재사용하고 기존 app_settings에 privacy_account:<id> 작업을 저장한다. 최초 탈퇴 시각(UTC)으로부터 달력 2개월이며 말일이 없으면 그 월 말일, 시각은 유지한다. 로그인·조회·반복 요청으로 기산점을 연장하지 않는다. 탈퇴 계정을 OIDC callback, 관리자 활성화 또는 최초 관리자 bootstrap으로 복구하지 못한다. 만료 정리는 계정·동의·개인 workspace 설정을 원자적으로 삭제하고 90일 감사 이벤트의 계정 연결을 제거한다. 일반 INACTIVE 계정을 탈퇴로 추정하지 않는다. 실패는 BLOCKED와 안전한 코드만 남기며 재시도한다. 공용 작품·자료 소유권 등 unresolved FK가 있으면 계정·동의를 보존하고 ACCOUNT_OWNERSHIP_REFERENCE_BLOCKED로 표시한다. 그 참조를 옮기거나 공용 자료를 삭제하지 않는다. 이 예외의 처리는 아직 정책 결정이 필요하다.

자동 정리는 기존 시작·60초 요청 유지보수 Runner를 그대로 재사용한다. trusted app config에 ACCOUNT_RETENTION_POLICY=withdrawal/calendar-2months-v1 및 ACCOUNT_RETENTION_APPROVED=true를 명시한 경우에만 실행한다. 글 만료 정리의 백업 생략은 RETENTION_POLICY.backupRetention=no-backups-approved-acquaintances-v1 AND RETENTION_NO_BACKUP_APPROVED=true가 모두 필요하다. RETENTION_APPROVED, RETENTION_DATES_VERIFIED 및 독립 개인 자료 정책 Gate도 여전히 필요하다. HTTP 요청으로 정책을 승인할 수 없다. 현재 운영 설정을 바꾸거나 삭제를 실행하지 않았다. 외부 백업·상시 공개·AI 활성화도 하지 않았다.


## 비공개 베타 최종 준비 (2026-10-11; 공개하지 않음)

최신 사용자 답변으로 별도 백업 없는 지인 배포를 유지하며 B6는 승인된 제외 조건이다. 공용 자료가 남은 탈퇴 계정은 2개월 경과 시 Google issuer/sub/email/인증 여부/권한/실제 계정 timestamps 및 동의·개인 설정·감사 이벤트 연결을 제거하고, INACTIVE 기술 소유권 참조만 남긴다. 공용 문서의 workspace FK와 파일·revision을 보존한다. 기술 참조는 OIDC·관리자 활성화·bootstrap으로 계정이 되지 않는다. 관련 공용 문서 파일 및 FK 테스트 PASS. 미해결 개인 참조는 계속 BLOCKED다.

신규 가입은 BETA_SIGNUP_ENABLED=true 및 승인된 BETA_SIGNUP_POLICY(version/notice/contact)를 trusted app config에서 명시할 때만 변경된다. 기존 OIDC 검증 이후 별도 300초 Secure/HttpOnly/SameSite=Lax 가입 쿠키, CSRF form, 서버 연령 확인·정책 버전·필수 동의를 거쳐 USER ACTIVE를 원자적으로 적용한다. 세션 버전 CAS, nonce 교체·재전송 차단, 비활성·탈퇴·기존 PENDING 거절/차단 이력 보호를 유지한다. 기존 ACTIVE 사용자도 현행 동의가 없으면 개인 API를 사용할 수 없다. 운영은 아직 기본 PENDING 정책이고 새 beta flag는 켜지 않았다. 운영 설정은 출시 전 기존 실행 경로에 연결·검증해야 하며 현재 P14 adapter는 격리 전용이다.

변경된 인증·동의는 실제 격리 API + 합성 서명 OIDC 브라우저로 검증했으며 실제 외부 Google 즉시 가입 검증으로 표시하지 않는다. 이전 P14 실제 Google 검증은 ADMIN 승인 흐름이었다. 현재 서버·터널은 종료 상태다. G4의 기존 backend/app/config.py 보호 해시 불일치와 미실시 G5/B10을 숨기거나 갱신하지 않는다. 최종 출시 전 독립 개인 자료 만료 정책, 신규 외부 가입 smoke test, 운영 설정 적용과 최종 검토가 남는다.

운영자는 기존 network_service.py start/status/stop/restart를 사용한다(현재 격리 전용). 재부팅/PC 절전/인터넷 단절 후 status로 상태 확인 → 원인 해소 → restart → health/Google 세션 확인. PC 종료 시 서비스를 이용할 수 없으며 24시간 가동을 보장하지 않는다. 시험 접속 비밀번호 교체는 기존 auth_setup.py ngrok의 숨겨진 로컬 입력으로 수행하고 해당 실행을 재시작한다. 이전 시험 쿠키는 기존 비밀번호 기반 서명 때문에 무효화된다. 실제 토큰/비밀번호는 명령 인수·문서·로그에 쓰지 않는다.

공식 조건 확인: ngrok https://ngrok.com/docs/pricing-limits/free-plan-limits (1GB/월, HTTP 20,000회/월, 방문 안내, up to 3 endpoints); Google https://developers.google.com/identity/protocols/oauth2/production-readiness/overview (기본 openid/email/profile만 사용하는 Testing 외부 앱의 테스트 사용자 목록 예외; Workspace 관리자 차단은 별개). 실제 계정의 콘솔 게시 상태·사용량은 이 문서 조회로 검증됐다고 표시하지 않는다.


## 최신 제한 베타 출시 결정 — 2026-10-11

이번 사용자 지시가 이전 백업 없는 배포 결정을 대체한다. 별도 물리 백업 장치와 전용 문의 이메일은 필수 Gate에서 제외한다. 기존 SQLite Online Backup으로 C: Data Root/operational/local-backups에 암호화 백업을 생성하고 7일 보존하며 새 격리 경로에서 복원 검증한다. 전체 C: 디스크 고장 시 원본·백업·DPAPI 키가 함께 손실될 수 있고 완전 재해복구를 보장하지 않는다. E:는 사용하지 않는다. 내 계정의 열람·탈퇴 및 글 목록의 글별 삭제를 제공하고 추가 문의는 운영자를 아는 지인의 기존 직접 연락 경로를 사용한다. G5 Claude PASS 및 모든 필수 기술 Gate 통과 시만 지인 대상 공개를 조건부 승인한다. G4 보호 불일치, 독립 개인 자료 정책, 운영 가입·만료·실행 설정 및 신규 실Google 흐름은 해결되지 않았다. 현재 상시 공개·자동 삭제·예약 백업은 비활성이다.

로컬 백업은 기존 `backend/privacy_service.py backup`을 사용한다. 최초 암호화 키는 기존 DPAPI의 `backup-key` 명령으로 추가하며 다른 키를 보존한다. 이번 실행에서 13,819바이트 암호화 백업과 revision 0003 격리 복원을 검증했고 복원은 quarantine·세션 무효화·AI 비활성 상태다. 하루 미만의 재실행은 NOT_DUE; 7일 이상 인증된 백업만 정리한다. 쓰기 서버가 실행 중이면 백업을 차단한다. 예약 실행/운영 일시중단 연동은 아직 연결하지 않았다. 최신 원본 권한·삭제 DB를 잃으면 복원이 차단된다. 익명화/삭제된 Google 계정의 옛 식별정보가 담긴 백업도 격리 파일 작성 전에 차단하며 자동 익명 소유자 재구성을 추정하지 않는다.

```powershell
.venv\Scripts\python.exe backend\privacy_service.py status
.venv\Scripts\python.exe backend\privacy_service.py backup
.venv\Scripts\python.exe backend\network_service.py status
.venv\Scripts\python.exe backend\network_service.py stop
```

최신 사용자 결정으로 G5는 `WAIVED_BY_USER`이다. 이전 문단의 Claude 필수 조건은 대체되며 PASS 증거로 사용하지 않는다. G1~G4와 실Google 신규 USER 가입 검증은 유지한다.

기본 `start/status/stop/restart`는 격리 실행을 유지한다. `--beta-test`는 새로운 격리 가입 DB에서 실제 Google·동의·만 14세·ACTIVE USER 흐름을 검증한다. `--operating`은 운영 DB 초기화를 금지하며, 코드 해시·G1~G4·검증된 최근 로컬 백업이 있는 `operational/beta-release.json` 없이는 시작하지 않는다. 운영 공개는 모든 출시 검증 이후에만 수행한다.

운영 준비가 통과한 뒤 사용할 명령은 `network_service.py start --operating`, `status`, `stop`, `restart --operating`이다. `scheduler-install --operating`은 기존 Windows 예약 작업을 사용하며 같은 이름의 다른 작업을 덮어쓰지 않는다. 시간당 유지보수 시 해당 서버·터널을 잠시 종료하고 만료 자료·탈퇴 상태·파일 정리를 완료한 뒤 하루 1회 검증 백업과 재시작을 수행한다. 실패하면 서비스를 중단하고 미완료 상태를 보존한다. 수동 STOP 이후 예약 작업이 자동으로 공개하지 않는다. 현재 활성화 여부는 Checkpoint를 확인한다.

독립 개인 문서와 개인 평가 자료는 마지막 실제 본문 변경 후 7일이며 동일 본문 저장으로 연장하지 않는다. 만료 후 API 접근을 먼저 차단한다. 소유권 또는 과거 분석 참조가 불명확한 레거시 자료는 무단 삭제하지 않고 정리를 차단한다. C: 전체 고장 시 원본과 로컬 백업이 함께 손실될 수 있다.

## 최초 운영 안정화 — 2026-10-11

운영 DB 최신 가입 정보(사용자1·동의1·글0)를 포함한 새 암호화 백업과 격리 복원 완료. 등록된 Windows 작업을 직접 실행해 정리·백업 주기 확인·재시작과 수동 STOP 후 미자동시작을 검증했다. 이는 시간 트리거 첫 실행과 구분하며 Checkpoint에 기록한다. 작업은 USER의 대화형 로그인 중에만 실행되며 로그아웃·재부팅 시 무인 서비스 가용성을 보장하지 않는다.

START/STOP/RESTART와 maintenance-cycle은 OS mutex로 순서대로 실행한다. 경합은 기다리며 시간 초과는 안전하게 차단한다. 수동 STOP은 진행 중 유지보수 완료 후 최종 종료한다. PC 재부팅 후 프로젝트 PowerShell에서 기존 `network_service.py start --operating`으로 안전 Gate와 최근 검증 백업을 확인하고 실행한다. 실패하면 status 및 Windows 작업 LastTaskResult를 확인하며 DB 초기화·강제 복원·Gate 우회를 하지 않는다. 백업이 오래돼 시작이 차단되면 기존 privacy_service.py backup을 서비스가 정지된 상태에서 실행하고 검증 결과를 확인한다. 자동 삭제 참조 충돌이 있으면 임의 삭제하지 않는다.

별도 기기 확인: 휴대전화 Wi-Fi를 끄고 모바일 데이터로 지정 HTTPS 주소 접속 → 별도로 전달받은 시험 접속 정보 → Google 로그인 → 정상 홈 확인. 비밀번호·인증 코드·callback URL은 전달하지 말고 성공 여부 또는 오류 코드만 기록한다. 실제 재부팅·절전·물리 네트워크 차단은 이번에 수행하지 않았다.

## Google 단일 진입 — 최신 사용자 결정 2026-10-11

운영 서비스의 공유 접속 비밀번호(Basic) 단계는 사용자 요청으로 제거했다. 이전 시험 비밀번호 안내는 운영 진입에 적용하지 않는다. 지정 HTTPS 주소의 미로그인 방문은 /api/auth/login을 거쳐 Google 계정 선택으로 이동하며 로그인된 사용자는 홈을 표시한다. 신규 계정은 연령 확인·필수 동의 후 USER로 가입한다. 링크를 아는 Google 사용자에게 가입 경로가 열리므로 지인 전용 공유 비밀번호 제한은 더 이상 없다. Google 인증, USER/ADMIN 분리, CSRF·IDOR, HTTPS·Host·Origin·요청 제한은 유지한다. 격리 Basic 테스트 모드와 기존 비밀 저장 항목은 보존한다. 지인에게는 주소와 Google 로그인 안내만 전달하면 된다.

## BAZE 선택 구절 질문 연결 준비 (2026-10-11)

기존 components.ai → v2.ai_api → BazeProvider를 재사용한다. 실제 외부 요청은 0건이며 운영 network_service와 beta_runtime의 EXTERNAL_AI_TERMS_APPROVED=false, AI_PROVIDER=None 및 AI 비활성 시작 검사를 그대로 유지한다. 이 절은 운영 활성화 승인이 아니다. 키를 대화·명령 인수·Git으로 다시 입력하지 않는다. 기존 DPAPI BAZE_API_KEY를 서버에서만 읽는다.

공식 확인 자료:
- 연결/인증: https://docs.mindlogic.ai/docs/dcu-ac/api-gateway/getting-started/overview 및 /authentication (Bearer, OpenAI 호환 POST /chat/completions/, 말단 slash 포함). 현행 문서의 Base URL은 https://factchat-cloud.mindlogic.ai/v1/gateway. 기존 후보 https://factchat.mindlogic-kr-api.com/v1/gateway도 정확한 주소만 허용하며, 키를 발급한 화면의 주소를 우선 확인한다. 계정과 조직별 연결은 미검증.
- 모델: https://docs.mindlogic.ai/docs/dcu-ac/api-gateway/getting-started/models (조직/그룹 권한별 목록). 문서에 claude-haiku-4-5-20251001 등이 존재하지만 이 키의 사용 가능 모델로 확정하지 않는다. 실제 /models 인증 조회도 외부 승인 이후 수행한다.
- 요청/출력: https://docs.mindlogic.ai/docs/dcu-ac/api-gateway/reference/chat-completions (JSON Schema, max_completion_tokens). 이번 구현은 출력 상한 2048 이내를 요구하므로 큰 내부 추론 예산이 필요한 모델은 맞지 않을 수 있다. 실패 시 상한을 몰래 늘리지 않고 로컬 질문으로 돌아간다.
- 비용: https://docs.mindlogic.ai/docs/khu/api-gateway/reference/usage 및 https://docs.mindlogic.ai/docs/dcu-ac/api-gateway/reference/credits (키 계정의 크레딧 차감/사용량). 공개 문서에서 이 계정의 정확한 텍스트 모델 단가와 원화 환산을 확정하지 못했다. /estimate 문서는 이미지·비디오·음악용으로, 텍스트 견적 API라고 사용하지 않는다. 일/월 한도와 최대 요청 비용은 운영자가 확인한 최악 비용 상한을 동일한 정수 단위로 예약한다. 실패 호출도 예약을 환불하지 않으며 재시도하지 않는다. 다른 앱에서 같은 키로 쓴 비용은 글빛의 로컬 장부로 통제되지 않는다.
- 처리 조건: https://docs.mindlogic.ai/docs/puts/baze/policy/data-security 는 학습 미사용을 설명하지만 타 기관 페이지이며 이 계정 계약의 근거로 자동 승인하지 않는다. https://docs.mindlogic.ai/docs/general/baze-admin/security/chat-record-policy 는 웹 대화 기록 정책이므로 API 요청·로그·모델 제공사의 보존기간으로 동일시하지 않는다. Gateway 및 선택 모델 제공사의 보존기간, 국외 처리/처리자, 삭제·로그·학습 이용 조건은 계정에 적용되는 약관 또는 담당자 답변으로 확인해야 한다.

활성화 전 필요한 비밀 아닌 서버 설정(값은 아직 미확정):
1. BAZE_GATEWAY.baseUrl, model: 키 발급 화면의 정확한 주소와 계정에서 사용 가능한 llm 모델 ID.
2. maxCompletionTokens(1~2048), maxSelectedCodepoints(1~6000), timeoutSeconds(1~30).
3. AI_LIMITS: dailyRequests, monthlyBudgetUnits, callCostUnits, cooldownSeconds, concurrency. callCostUnits는 최대 입력/출력/추론 및 부가 요금을 포함하는 요청당 양수 상한이다. 숫자 단위·단가·환산 근거를 pricingReference에 기록하고 비용 상한의 근거가 없으면 활성화하지 않는다.
4. AI_POLICY_VERSION 및 실제 별도 AI 동의문. 전송 대상은 선택 구절과 질문 유형이며 전체 글·작품 전문·생각 메모·사용자/버전 ID는 보내지 않는다.
5. processingTermsReference와 pricingReference; endpointConfirmed, modelConfirmed, pricingConfirmed, processingTermsConfirmed, costUpperBoundConfirmed는 확인된 경우만 true.
6. EXTERNAL_AI_TERMS_APPROVED 및 기존 관리자 AI 스위치는 모든 설정 확인 후에만 활성화한다. 현재 운영 어댑터는 의도적으로 외부 AI를 강제 비활성화하므로, 별도 활성화 작업에서 기존 network_service/beta_runtime의 승인된 설정 연결과 Gate를 먼저 검증해야 한다. HTTP 요청이나 키 등록으로 이 차단을 우회하지 않는다.

모델은 선택 구절에서 0~2개 초점과 질문 의도를 고른다. 서버는 검증된 15개 질문 문구를 구성하므로 작품 사실을 지어낼 자유 서술을 받아들이지 않는다. 문맥 부족은 INSUFFICIENT_CONTEXT이며 잘못된 JSON·범위·중복 선택·도구 호출·차단·오류는 기존 로컬 질문으로 대체한다. 이는 자유 서술 생성 전체를 구현했다고 뜻하지 않는다. 기존 두 테마/API/PDF/메모 계약과 로컬 규범 분석은 유지한다.

### 초기 추천값 및 사용자 확인 동선 (2026-10-11)

모두 제안이며 운영에 적용하지 않았다. 현행 BAZE 공개 목록에 있는 claude-haiku-4-5-20251001을 첫 시험 후보로 한다. Anthropic은 이를 legacy로 표시하므로 장기 사용 보장이나 최저가라고 주장하지 않는다. 조직에서 더 최신 저비용 모델을 제공하면 /models와 JSON Schema·짧은 출력 지원을 확인한 뒤 비교한다. 현재 모델/계정 실호출 성공 증거는 없다.

추천: 선택 구절 합계1500 code points, 출력512 tokens, timeout20초, 사용자당 하루5회, cooldown30초, 전체 동시1개. 월 전체 예산10000원, 요청당 최대30원을 초기 목표로 하되 BAZE 원화/크레딧 환산 및 모델의 최악 비용을 확인한 뒤 정수 예산 단위로 변환한다. 현재 숫자를 실제 AI_LIMITS나 BAZE_GATEWAY 승인 flags로 쓰지 않았다. 요청당30원 상한을 전부 예약하면 월 최대333회이며 실제 비용이 낮아도 보수적으로 제한된다. 사용자당5회보다 전체 월 한도를 우선한다. Anthropic 직접 API의 Haiku4.5 공개 단가는 입력100만token당USD1/출력USD5이나 BAZE 과금표로 사용하지 않는다: https://platform.claude.com/docs/en/models/haiku-4-5/overview

확인 동선:
- 본인의 BAZE/FactChat 조직 서비스에 로그인 → 좌측 API Gateway/개발자 화면 → 해당 키 발급 안내의 Base URL 확인. 원본키는 다시 전달하지 않는다. 모델 목록/권한에서 후보 ID가 보이는지 확인하고, 화면에 목록이 없으면 담당자에게 API 사용가능 모델과 JSON Schema 지원을 문의한다. API 조회는 별도 외부 호출 승인 후 기존 서버에서 수행한다.
- BAZE 전체 관리자 권한이 있으면 관리자 → 데이터 → API 키 관리 → 해당 키 상세에서 상태·호출수·크레딧을 확인한다. 이 화면은 조회용이며 비용 hard cap 설정 화면이 아니다. 글빛 ADMIN 권한과 BAZE 전체 관리자 권한은 별개다.
- 관리자 → 데이터 → 크레딧 사용량/구매 내역에서 해당 모델 사용량과 크레딧을 확인한다. 정확한 입력/출력/추론/필터 요금과 크레딧 원화 환산이 보이지 않으면 조직 담당자나 마인드로직 지원에 요청한다. 지불이나 자동 충전은 실행하지 않는다.
- 관리자 → 보안 설정 → 대화 기록 정책은 웹 대화 정책만 확인한다. API 보존기간이 같다고 가정하지 않는다. 지원에 '글빛 선택 구절을 Chat Completions API로 전달할 때 Gateway 요청·응답·로그와 Anthropic 제공사의 보존기간, 처리 국가/수탁자, 학습 이용, 삭제 요청 방법 및 적용 약관을 확인해 달라'고 문의한다. API키나 학생글은 문의에 넣지 않는다.

공식 화면 안내: https://docs.mindlogic.ai/docs/general/baze-admin/credits/api-keys 및 https://docs.mindlogic.ai/docs/general/baze-admin/credits/usage-tracking

### 계정별 Gateway 주소 확인 (2026-10-11)

사용자가 실제 API Gateway 화면의 안내를 제공하여 이 키의 Base URL을 https://factchat.mindlogic-kr-api.com/v1/gateway 로 확정했다. 다른 배포처의 factchat-cloud 주소를 이 계정에 적용하지 않는다. 기존 adapter의 정확한 HTTPS allowlist에 이미 포함되므로 코드 변경은 필요 없다. Bearer 인증을 유지하며 외부 인증 성공은 아직 미검증이다. 에이전트 제공자 전환 프롬프트를 실행하지 않고 글빛 서버 설정에만 반영한다. 모델 가용성, 요금·비용 상한, API 데이터 처리 조건·별도 동의는 미확정이며 운영 활성화 및 실제 요청을 하지 않는다.

## 가상 문장 실제 BAZE 검증 (2026-10-11)

사용자 승인으로 학생 글 없이 가상 도서관 문장만 전송했다. claude-haiku-4-5-20251001, 출력 상한 512토큰, HTTP 200 및 질문 2개/원문 일치/출력 검증 PASS. 실제 usage: 입력 568, 출력 36, 합계 604토큰; 2.719초. BAZE 실제 차감 크레딧은 응답에 없어 미확인이다.

인증서 검증은 기존 certifi CA 묶음을 재사용하며 CERT_REQUIRED와 호스트 검증을 유지한다. Haiku가 지원하지 않는 wire JSON Schema의 maxItems/minimum/maximum만 제외했다. 서버의 질문 최대 2개, 정수 인덱스 범위, 중복 금지와 원문 일치 검증은 그대로 유지한다. 모델이 질문 의도와 초점을 선택하고 서버가 검증된 문구를 구성한다. 자유 서술 전체 생성으로 주장하지 않는다.

시도 기록: TLS 실패 2회, schema HTTP 400 3회, 최종 HTTP 200 1회. 별도 키 없는 TLS 상태 조회 1회. 자동 재시도 없음. 관련 테스트 52개, exit 0, Runner G1~G4 PASS. 기존 DPAPI 파일 불변 확인. 운영 DB/학생 데이터/세션 키/BAZE 키/UI/로컬 분석을 변경하지 않았고 운영 서버를 재시작하지 않았다. 운영 AI는 비활성 유지. 가격·처리 조건·별도 동의와 활성화 설정은 여전히 운영 활성화 선행 조건이다. G5는 WAIVED_BY_USER이며 독립 검토 PASS가 아니다.

## 운영 AI 활성화 대기 설정 (2026-10-11)

사용자 제공 계정 화면에서 성공 호출 1회/0.748크레딧을 확인했다. 이는 단일 가상 문장의 관측값이며 요청당 최악 비용 상한이 아니다. 초기 예산은 월 전체 100크레딧, 사용자 하루5회, 대기30초, 동시1개, 선택 구절 합계1500자, 출력512토큰, timeout20초로 준비한다. 같은 비용이라면 약133회이나 보장 처리량이 아니다. 1크레딧=1000 정수 장부 단위, 월100000단위 후보를 기존 예약 장부에서 사용한다. callCostUnits는 BAZE의 실제 입력/출력 단가와 상한을 확인하기 전 미설정이다. 위 후보는 운영 DB나 실행 설정에 적용하지 않았으며 비용 상한을 보장한다고 표시하지 않는다.

활성화에 필요한 계정 적용 조건: BAZE 및 Anthropic의 API 입력/출력/로그 보존기간과 예외, 학습·평가·사람 검토 여부, 실제 처리 주체와 국가, 삭제 요청 및 동의 철회 후 제공사 처리. 다른 기관의 학습 미사용 안내나 웹 채팅 보존 설정을 이 계정 API 조건으로 자동 승인하지 않는다.

별도 동의문은 위 실제 조건을 반영해 버전 확정 후 제공한다. 거부해도 로컬 분석은 이용 가능해야 한다. 선택 구절 전송 미리보기 확인 및 명시 실행만 허용하고 전체 글/이메일/생각 메모는 보내지 않는다. 현재 EXTERNAL_AI_TERMS_APPROVED=false, AI_PROVIDER=None 및 운영 AI 비활성 검사는 유지한다. 추가 외부 호출 없음.
