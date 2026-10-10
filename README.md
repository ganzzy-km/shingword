# 글빛

글빛은 문학 분석 글을 작성하고, 평가 기준·작품 원문·인용문 근거 카드와 함께 논증 구조, PEEL, 인용문, 맞춤법을 점검하는 로컬 교육용 프로그램입니다. 일반 사용 화면에는 로그인이 없으며 React 화면과 Flask API를 한 컴퓨터에서 실행하고 데이터는 SQLite에 저장합니다. 국립국어원 표준국어대사전 API는 선택적인 보조 검증 기능이라 키가 없어도 나머지 기능이 모두 동작합니다.

분석 결과와 백분율은 교사의 평가 점수가 아닙니다. 프로그램으로 계산할 근거가 없는 지표는 0으로 표시하지 않고 `계산 불가`로 표시합니다. 문장 역할·논증 연결·PEEL 판정은 설명 가능한 로컬 휴리스틱이므로 교사와 학생의 최종 판단이 필요합니다.

## 전체 구조

```text
브라우저
  └─ http://127.0.0.1:5000
      └─ Waitress + Flask
          ├─ React production build (dist/)
          ├─ /api
          ├─ SQLite (backend/instance/geulbit.db)
          └─ 업로드 파일 (backend/uploads/)

서버 컴퓨터 전용 관리자
  └─ http://127.0.0.1:5001/local-admin/api-key
      ├─ Argon2id 관리자 인증
      └─ Windows DPAPI CurrentUser API 키 저장
```

- 프론트엔드: React 19, TypeScript, Vite 8, Tailwind CSS 4
- 백엔드: Flask 앱 팩토리, Flask-SQLAlchemy, Flask-Migrate
- 운영 서버: Waitress (`127.0.0.1:5000` 전용 바인딩)
- 데이터베이스: SQLite
- 비동기 분석: 현재 Flask 프로세스의 제한된 작업 스레드
- 한국어 형태소 분석: Kiwi/CoNg (`kiwipiepy`), 복수 후보와 신뢰도 보존
- 공식 사전 보조 검증: Flask 프록시, 캐시·재시도·회로 차단기 적용
- OCR: PDF 텍스트 레이어·TXT·DOCX 우선, 이미지 OCR은 선택 설치한 Tesseract 사용

## 언어 분석 구조

기존 논증 구조·PEEL·평가 기준 분석은 유지하면서 언어 분석을 다음 순서의 독립 모듈로 나눴습니다.

1. 직접 인용문 보호: `"..."`, `'...'`, `“...”`, `‘...’` 범위와 중첩 위치를 먼저 기록
2. 맞춤법·오타: 규칙 기반 오류와 문맥상 어휘 선택을 의미 유사도와 분리
3. 형태소·원형: 표면형, 품사, 기본형, 조사, 어미, 본용언·보조용언, 극성·시제·상·양태·사동·피동과 복수 후보 기록
4. 의미 역할: 주체·대상·상대·개념·서술어·인용 내용/주체/행위 구조화
5. 의미 비교: 형태소 표면 일치가 아니라 역할과 서술 관계를 비교
6. 공식 사전 보조 검증: 필요한 기본형과 교정 후보만 표준국어대사전에서 확인
7. 결과 통합: 형태소 신뢰도와 의미 유사도 점수를 분리하고 판정 근거·차단 조건 표시

인용문 내부 제안은 출처 대조가 필요한 가능성으로만 표시하며 수정 적용 버튼과 백엔드 적용 API 양쪽에서 차단합니다. 긍정/부정, 주체·대상 교환, 사동/피동, 수치·날짜·고유명사, 양태, 인용 내용·주체, 비교, 인과와 핵심 서술 관계가 다르면 단어가 비슷해도 같은 의미로 자동 확정하지 않습니다.

의미 판정은 `같은 의미일 가능성이 높음`, `비슷하거나 관련된 의미`, `다른 의미`, `판단 보류` 네 단계입니다. 가중치와 0.85/0.65 임계값은 논문 점수가 아닌 [프로젝트 상수](backend/app/analysis/thresholds.py)이며 테스트 자료에 맞춰 조정할 수 있습니다. 참고 문헌과 적용 한계는 [RESEARCH_NOTES.md](backend/app/analysis/RESEARCH_NOTES.md)에 기록했습니다.

## 처음 설치

PowerShell에서 프로젝트 폴더로 이동한 뒤 실행합니다.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
pnpm install --frozen-lockfile
```

`py` 명령이 없다면 설치된 Python 3.11 이상의 전체 경로로 `-m venv .venv`를 실행합니다. 프로젝트 경로에 한글이나 공백이 있어도 제공된 스크립트가 처리합니다.

## 데이터베이스 초기화와 마이그레이션

```powershell
Push-Location .\backend
& ..\.venv\Scripts\python.exe -m flask --app wsgi:app db upgrade
Pop-Location
```

새 데이터베이스에는 빈 작업 공간과 공식 출처가 연결된 기본 맞춤법 규칙만 생성됩니다. 평가 기준, 작품, 예시 글, 분석 결과 같은 사용자 샘플 데이터는 넣지 않습니다.

## 개발 환경 실행

터미널 1에서 Flask API를 실행합니다.

```powershell
Push-Location .\backend
& ..\.venv\Scripts\python.exe -m flask --app wsgi:app run --host 127.0.0.1 --port 5000
```

터미널 2에서 Vite를 실행합니다. Vite는 `/api` 요청을 `127.0.0.1:5000`으로 프록시합니다.

```powershell
pnpm dev
```

## Production 실행과 종료

가장 간단한 방법은 프로젝트 루트의 배치 파일을 실행하는 것입니다.

```bat
start-geulbit.bat
```

이 스크립트는 프로젝트·가상환경·의존성을 확인하고 React build, SQLite 마이그레이션, Waitress의 일반 앱 5000/로컬 관리자 5001 시작, `/api/health` 확인을 수행한 뒤 브라우저에서 [http://127.0.0.1:5000](http://127.0.0.1:5000)을 엽니다.

종료할 때는 다음 파일을 실행합니다.

```bat
stop-geulbit.bat
```

종료 스크립트는 저장된 PID, 실행 파일과 시작 시각이 현재 프로세스와 일치할 때만 해당 Waitress를 종료합니다. 다른 Python이나 포트 사용 프로세스를 일괄 종료하지 않습니다.

직접 실행하려면 다음 명령을 사용할 수 있습니다.

```powershell
pnpm run build
Push-Location .\backend
& ..\.venv\Scripts\python.exe -m flask --app wsgi:app db upgrade
& ..\.venv\Scripts\python.exe .\serve.py
```

`serve.py`의 일반 앱 주소는 `APP_HOST`와 `APP_PORT`로 조정할 수 있으며 기본값은 각각 `127.0.0.1`, `5000`입니다. 학교 접속 모드에서는 이 기본값을 유지하고 Cloudflare가 loopback 주소에 연결하게 하며, Flask를 `0.0.0.0`으로 직접 공개하지 않습니다. 로컬 관리자는 환경 변수와 관계없이 `127.0.0.1:5001`에만 바인딩됩니다.

## OCR 선택 설치

TXT, DOCX와 텍스트 레이어가 있는 PDF는 Tesseract 없이 텍스트를 추출합니다. PDF는 페이지마다 텍스트 레이어를 먼저 확인하므로 텍스트 페이지와 스캔 페이지가 섞여 있으면 스캔 페이지만 OCR합니다. 스캔 PDF, PNG, JPG, JPEG에서 실제 이미지 OCR을 사용하려면 Flask가 실행되는 **서버 컴퓨터**에 Windows용 Tesseract OCR을 별도로 설치해야 합니다. 학교 PC나 태블릿에는 Tesseract를 설치하지 않습니다.

1. 신뢰할 수 있는 배포처에서 Tesseract 5를 설치합니다.
2. 설치 폴더를 Windows `PATH`에 추가합니다.
3. `tessdata` 폴더에 한국어 언어 데이터 `kor.traineddata`가 있는지 확인합니다.
4. 영어 데이터 `eng.traineddata`도 설치합니다. 기본 인식 언어는 `kor+eng`입니다.
5. 프로그램을 다시 시작합니다.

설치 상태는 서버 컴퓨터의 PowerShell에서 확인합니다.

```powershell
tesseract --version
tesseract --list-langs
.\.venv\Scripts\python.exe .\backend\diagnose_ocr.py
```

언어 목록에 `kor`, `eng`가 모두 있어야 합니다. 실행 파일을 PATH에 넣지 않는 경우 현재 PowerShell 세션에서 다음처럼 지정할 수 있습니다. 실제 설치 위치는 사용자가 확인한 값을 사용해야 하며 저장소에 개인 경로를 기록하지 않습니다.

```powershell
$env:TESSERACT_CMD = "확인한-Tesseract-실행-파일-경로"
$env:TESSDATA_PREFIX = "tessdata를-포함한-상위-폴더"
```

Windows 배포와 언어 데이터는 [Tesseract 공식 설치 문서](https://tesseract-ocr.github.io/tessdoc/Installation.html)를 확인하세요. 글빛은 제3자 설치 파일을 자동으로 내려받거나 관리자 권한으로 실행하지 않습니다.

Tesseract 또는 요청한 언어 데이터가 없으면 글빛은 OCR 결과를 꾸며 내지 않고 `OCR 실행 환경 필요`로 표시합니다. 서버와 학교 터널은 계속 실행되며 직접 입력, 텍스트 PDF 추출, 맞춤법·형태소·의미 분석과 기존 자료 조회는 계속 사용할 수 있습니다. 표준국어대사전 API 키도 OCR 실행에 필요하지 않습니다.

지원 업로드 형식은 PDF, PNG, JPG/JPEG, TXT, DOCX이며 기본 파일 크기 제한은 50MB입니다. `MAX_UPLOAD_SIZE_MB` 환경 변수로 제한을 조정할 수 있습니다. 기본 OCR 보호 한도는 PDF 100페이지, 이미지 4천만 픽셀, 페이지당 30초, 문서 전체 180초입니다. 필요하면 각각 `OCR_MAX_PAGES`, `OCR_MAX_IMAGE_PIXELS`, `OCR_PAGE_TIMEOUT_SECONDS`, `OCR_TOTAL_TIMEOUT_SECONDS`로 조정할 수 있습니다.

`OCR 확인`을 누르면 브라우저 `prompt()` 대신 글빛 내부 대화상자가 열립니다. 파일 형식·페이지 수·처리 범위를 확인한 뒤 OCR을 한 번 실행하고, 원본 미리보기와 추출 글을 대조하여 수정·저장합니다. OCR은 따옴표, 하이픈·대시 또는 작은 글자를 오인식할 수 있으므로 결과를 정답으로 자동 확정하지 않습니다.

## 데이터 위치와 초기화

- SQLite: `backend/instance/geulbit.db`
- 업로드 원본: `backend/uploads/`
- 생성한 백업: `backend/backups/`
- React production build: `dist/`
- 암호화된 API 키와 관리자 세션 키: `backend/instance/secrets.dat` (DPAPI CurrentUser)
- 관리자 비밀번호 해시·사전 상태: `backend/instance/local-admin.json`
- 비밀값 없는 관리자 감사 기록: `backend/instance/local-admin-audit.jsonl`

설정의 `작업 공간 초기화`는 확인 문자열 `초기화`를 입력한 경우에만 사용자 자료, 글과 분석 기록, 설정, 업로드 파일을 삭제합니다. 기본 맞춤법 규칙과 공식 출처는 다시 생성됩니다. `분석 기록 전체 삭제`는 평가 기준과 작품 자료를 유지합니다.

작업 공간 초기화와 분석 기록 삭제는 로컬 관리자 비밀번호나 암호화된 API 키를 삭제하지 않습니다. 이 파일들은 SQLite 백업에도 포함하지 않으며 서버 컴퓨터에서 별도로 관리합니다.

## 표준국어대사전 API 키 최초 등록과 변경

1. 글빛 서버를 시작한 서버 컴퓨터에서만 `http://127.0.0.1:5001/local-admin/setup`을 엽니다.
2. 12자 이상의 로컬 관리자 비밀번호를 최초 설정합니다. 평문은 저장하지 않고 Argon2id 해시만 저장합니다.
3. 다시 로그인해 국립국어원에서 발급받은 16진수 32자리 API 키를 두 번 입력합니다.
4. 글빛이 `나무` 표제어로 실제 연결 시험을 수행합니다. 성공한 경우에만 `secrets.dat`에 DPAPI CurrentUser 범위로 암호화해 저장합니다.
5. 저장 뒤 전체 키는 다시 표시하지 않고 앞·뒤 4자만 남긴 마스킹 상태로 표시하며 관리자 세션을 종료합니다.

기존 키를 바꿀 때는 관리자 비밀번호, 새 키와 확인 값, `표준국어대사전 API 키 변경` 확인 문구가 모두 필요합니다. 새 키의 연결 시험이 실패하면 기존 키를 유지합니다. 로그인은 5회 실패 시 10분 잠기고, 성공한 세션도 10분 동안 활동이 없으면 만료됩니다. 모든 변경 POST 요청에는 CSRF 보호가 적용됩니다.

표준국어대사전 API 공식 요청은 `search.do`와 `view.do`를 사용합니다. 연결/응답 제한은 각각 2초/3초, 재시도는 최대 1회이며 연속 3회 실패하면 60초 동안 외부 호출을 쉬고 동일 표제어 결과는 제한된 메모리 캐시에 둡니다. `not_configured`, `invalid_key`, `timeout`, `service_unavailable`, `temporarily_disabled` 상태에서도 분석과 SQLite 저장은 HTTP 200으로 정상 완료되며 의미 점수를 감점하지 않습니다.

## 백업·복원·내보내기

설정 화면에서 다음 작업을 실행할 수 있습니다.

- 백업 만들기: SQLite의 일관된 스냅샷, 업로드 파일, 해시가 포함된 ZIP 생성
- 복원하기: `복원` 확인 문자열, ZIP 경로 검증, 데이터베이스 해시와 SQLite 무결성 확인 후 복원
- JSON 내보내기: 작업 공간, 평가 기준, 작품, 인용문 카드와 글 내보내기

복원 직전 데이터베이스 안전 사본은 `backend/backups/`에 남습니다. 복원 후에는 실행 중인 서버를 종료하고 다시 시작해 주세요.

## 학교 브라우저 원격 접속

학교 PC나 태블릿에는 Cloudflared를 설치할 필요가 없습니다. 글빛이 저장된 서버 컴퓨터에만 공식 Cloudflare `cloudflared` 실행 파일이 있어야 합니다. 스크립트는 실행 파일을 임의 URL에서 자동 다운로드하지 않습니다.

서버 컴퓨터에서 실행합니다.

```bat
start-school-tunnel.bat
```

스크립트는 다음 순서로 작동합니다.

1. React production build와 마이그레이션을 적용합니다.
2. Waitress를 `127.0.0.1:5000`에서 실행하고 로컬 응답을 확인합니다.
3. `cloudflared --version`을 확인합니다.
4. `cloudflared tunnel --url http://127.0.0.1:5000`으로 Quick Tunnel을 시작합니다.
5. URL 생성에 실패하면 해당 프로세스만 종료하고 `--protocol http2`로 한 번 재시도합니다.
6. `https://xxxxx.trycloudflare.com` 주소를 `quick-tunnel-url.txt`에 저장하고 가능한 경우 클립보드에 복사합니다.

표시된 주소를 학교의 Chrome 또는 Edge에서 엽니다. 서버 컴퓨터는 계속 켜져 있어야 하며 절전 모드에 들어가면 접속이 끊길 수 있습니다.

생성된 주소는 화면에 표시되고 클립보드와 프로젝트 루트의 `quick-tunnel-url.txt`에도 저장됩니다. Quick Tunnel을 다시 시작하면 주소가 달라질 수 있으므로 학교에 안내하기 전에 현재 파일의 주소를 다시 확인하세요.

상태 확인과 종료:

```bat
status-school-tunnel.bat
stop-school-tunnel.bat
```

상태 스크립트는 PID 파일만 믿지 않고 실행 파일과 시작 시각을 검증하며, URL 파일이 남아 있어도 cloudflared 프로세스가 종료되었으면 현재 접속 가능하다고 표시하지 않습니다. 종료 스크립트도 이번 실행으로 확인된 cloudflared와 Waitress만 종료합니다.

### Quick Tunnel 보안 주의사항

- Quick Tunnel은 임시 테스트와 시연용이며 다시 실행할 때 주소가 변경될 수 있습니다.
- 학교 접속 주소를 불필요한 사람에게 공유하지 마세요.
- 이 프로그램에는 로그인 기능이 없습니다. 주소를 아는 사람은 글빛의 자료와 기능에 접근할 수 있습니다.
- 로컬 관리자 5001 포트는 Quick Tunnel 명령에 포함되지 않고 loopback에만 바인딩되며, 5000 서버의 `/local-admin` 경로도 차단됩니다.
- 개인정보나 민감한 원문 자료를 저장한 상태에서는 터널을 실행하지 않는 것을 권장합니다.
- 사용이 끝나면 반드시 `stop-school-tunnel.bat`를 실행하세요.
- Vite 개발 서버나 HMR은 외부 터널로 공개하지 않습니다.
- 사용자 프로필의 `.cloudflared\config.yml` 또는 `config.yaml`이 Quick Tunnel을 방해할 수 있습니다. 스크립트는 해당 파일을 자동 삭제하거나 변경하지 않습니다.
- Quick Tunnel은 개발·학교 현장 시험을 위한 임시 접속 기능입니다. Oracle Cloud나 다른 상시 클라우드 서버 배포는 현재 구현 범위에 포함되지 않습니다.

Cloudflared가 없다면 공식 문서를 확인하거나 다음 명령으로 설치할 수 있습니다.

```powershell
winget install --id Cloudflare.cloudflared
```

### 학교 현장 확인 체크리스트

Codex가 서버 컴퓨터에서 확인한 로컬 테스트와 별개로, 실제 학교 네트워크에서는 다음 항목을 직접 확인합니다.

- 서버 컴퓨터가 켜져 있고 절전 모드가 해제되어 있는지 확인합니다.
- `status-school-tunnel.bat`에서 Waitress와 cloudflared가 모두 정상이고 현재 URL이 표시되는지 확인합니다.
- 학교 Wi-Fi의 Chrome 또는 Edge에서 현재 `trycloudflare.com` 주소가 열리는지 확인합니다.
- 홈 화면, 새 글 분석, 평가 기준, 작품 자료, 분석 기록과 설정 경로를 직접 열고 새로고침해 404가 발생하지 않는지 확인합니다.
- PDF, PNG, JPG 또는 JPEG 파일 하나를 올려 서버 컴퓨터에서 OCR 또는 텍스트 추출이 수행되는지 확인합니다.
- 태블릿 화면에서 메뉴, 파일 선택, 글 입력과 결과 화면을 사용할 수 있는지 확인합니다.
- 시험이 끝나면 서버 컴퓨터에서 `stop-school-tunnel.bat`를 실행하고 상태가 종료됨으로 표시되는지 확인합니다.

학교 PC나 태블릿에는 Node.js, Python, Tesseract 또는 cloudflared를 설치할 필요가 없습니다. 학교 네트워크가 `trycloudflare.com`을 차단한다면 프로그램 오류가 아니라 학교 네트워크 정책일 수 있으므로 담당자에게 허용 여부를 확인해야 합니다.

## 테스트와 검사

```powershell
.\.venv\Scripts\python.exe -m pytest .\backend\tests -q
.\.venv\Scripts\python.exe .\backend\validation\run_validation.py
.\node_modules\.bin\tsc.CMD --noEmit
pnpm run build
.\node_modules\.bin\oxfmt.CMD --check src package.json vite.config.ts tsconfig.json
```

현재 `package.json`에는 별도 lint 스크립트가 없습니다. TypeScript 검사와 production build가 정적 오류 검사를 담당합니다.

## 주요 API

- 작업 공간·대시보드·설정: `/api/workspace`, `/api/dashboard`, `/api/settings`
- 평가 기준·OCR: `/api/rubrics`, `POST /api/rubrics/{id}/ocr`
- 작품·페이지 OCR·인용문 카드: `/api/source-documents`, `POST /api/source-documents/{id}/ocr`, `/api/quote-cards`
- 서버 OCR 준비 상태: `GET /api/ocr/status` (실행 파일의 실제 경로는 반환하지 않음)
- 글·자동 저장·버전 비교: `/api/writings`, `/api/records`, `/api/writing-versions`
- 비동기 분석·결과·수정 적용: `/api/analyses`, `/api/analysis-jobs`, `/api/findings`, `/api/revisions`
- 형태소·의미 비교: `POST /api/semantic/compare`
- 공식 사전 상태·검색·상세: `/api/dictionary/status`, `/api/dictionary/lookup?q=...`, `/api/dictionary/entries/{target_code}?q=...`
- 규칙·백업·복원·초기화: `/api/rules`, `/api/backups`, `/api/workspace/reset`

프론트엔드는 항상 `/api/...` 상대 경로를 사용하므로 Quick Tunnel에서도 학교 컴퓨터 자신의 `localhost`로 잘못 요청하지 않습니다.

## 자주 발생하는 오류

- `FRONTEND_NOT_BUILT`: `pnpm run build`를 실행하세요.
- 5000번 포트 사용 중: 스크립트는 다른 프로세스를 종료하지 않습니다. 해당 프로그램을 직접 종료하거나 포트 사용 원인을 확인하세요.
- `.venv가 없습니다`: Python 가상환경을 만들고 `backend/requirements.txt`를 설치하세요.
- `OCR 실행 환경 필요`: `tesseract --version`, `tesseract --list-langs`와 `backend/diagnose_ocr.py`로 실행 파일, `tessdata`, `kor`, `eng` 상태를 확인하세요. 앱의 다른 기능은 계속 사용할 수 있습니다.
- `OCR 처리 실패`: 파일이 손상·암호화되었는지, PDF 페이지/이미지 픽셀/처리 시간 제한을 넘었는지 확인하세요.
- `일부 페이지만 처리됨`: 원본 미리보기와 페이지별 추출 글을 확인하고 실패한 스캔 페이지만 다시 처리하세요.
- `prompt() is not supported.`: OCR 흐름은 React 대화상자로 교체되었습니다. 이전 화면이 남아 있으면 `pnpm run build` 후 서버를 재시작하고 브라우저를 새로고침하세요.
- `공식 사전 보조 기능: 제한됨`: 서버 컴퓨터의 5001 로컬 관리자에서 키 상태를 확인하세요. 글 작성과 나머지 분석은 계속 사용할 수 있습니다.
- Quick Tunnel URL을 찾지 못함: `.school-tunnel-error.log`와 `.school-tunnel-http2-error.log`를 확인하고 방화벽·학교/가정 네트워크 정책을 점검하세요.
- 백업 복원 후 화면이 이전 상태: `stop-geulbit.bat` 후 `start-geulbit.bat`로 재시작하세요.
- 자동 저장 충돌: 같은 글을 여러 탭에서 수정한 경우 최신 기록을 다시 불러온 뒤 수정하세요.

## 보안 경계

Flask는 `dist/`만 정적 파일로 제공합니다. `.env`, SQLite, Python/TypeScript 소스, 업로드 저장 경로, 백업 폴더, 로컬 관리자 경로와 Git 메타데이터는 SPA fallback보다 먼저 차단합니다. 오류 응답에는 서버 파일 경로나 스택 추적을 노출하지 않으며 외부 실행에서 Flask debug 모드를 사용하지 않습니다. API 키는 URL, 응답, 오류 메시지와 감사 로그에 포함하지 않습니다.
