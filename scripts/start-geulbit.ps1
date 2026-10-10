param(
    [switch]$NoBrowser,
    [switch]$SkipBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# 일부 개발 셸은 Path와 PATH를 동시에 넘겨 Windows PowerShell의 Start-Process를 깨뜨립니다.
$processPath = [Environment]::GetEnvironmentVariable("PATH", "Process")
[Environment]::SetEnvironmentVariable("Path", $null, "Process")
[Environment]::SetEnvironmentVariable("PATH", $processPath, "Process")

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendRoot = Join-Path $ProjectRoot "backend"
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PidFile = Join-Path $ProjectRoot ".school-server.pid"
$StateFile = Join-Path $ProjectRoot ".school-server-state.json"
$ServerLog = Join-Path $ProjectRoot ".school-server.log"
$ServerErrorLog = Join-Path $ProjectRoot ".school-server-error.log"
$HealthUrl = "http://127.0.0.1:5000/api/health"

function Get-ProcessRecord([int]$ProcessId) {
    Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
}

function Convert-ToUtc([object]$Value) {
    if ($Value -is [datetime]) { return ([datetime]$Value).ToUniversalTime() }
    return [datetimeoffset]::Parse([string]$Value, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind).UtcDateTime
}

function Test-OwnedServer([object]$State) {
    if ($null -eq $State -or $null -eq $State.pid) { return $false }
    $record = Get-ProcessRecord ([int]$State.pid)
    if ($null -eq $record) { return $false }
    $expected = [IO.Path]::GetFullPath([string]$State.executable)
    $actual = if ($record.Path) { [IO.Path]::GetFullPath([string]$record.Path) } else { "" }
    $started = $record.StartTime.ToUniversalTime()
    $expectedStart = Convert-ToUtc $State.startedAt
    return $actual -eq $expected -and [math]::Abs(($started - $expectedStart).TotalSeconds) -lt 10
}

function Remove-StaleServerState {
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
}

Write-Host "글빛 프로젝트: $ProjectRoot"
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "package.json"))) { throw "package.json을 찾을 수 없습니다." }
if (-not (Test-Path -LiteralPath (Join-Path $BackendRoot "wsgi.py"))) { throw "backend\wsgi.py를 찾을 수 없습니다." }
if (-not (Test-Path -LiteralPath $PythonExe)) { throw ".venv가 없습니다. README의 Python 가상환경 설치 절차를 먼저 실행해 주세요." }

if (Test-Path -LiteralPath $StateFile) {
    try { $existingState = Get-Content -LiteralPath $StateFile -Raw -Encoding utf8 | ConvertFrom-Json } catch { $existingState = $null }
    if (Test-OwnedServer $existingState) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $HealthUrl -TimeoutSec 3
            if ($response.StatusCode -eq 200) {
                $existingState.pid | Set-Content -LiteralPath $PidFile -Encoding ascii
                Write-Host "글빛 서버가 이미 실행 중입니다. PID: $($existingState.pid)"
                if (-not $NoBrowser) { Start-Process "http://127.0.0.1:5000" }
                return
            }
        } catch { }
        throw "이 프로젝트가 시작한 Waitress 프로세스는 있지만 응답하지 않습니다. stop-geulbit.bat를 실행해 주세요."
    }
    Remove-StaleServerState
}

$portPids = @(netstat -ano -p tcp | Select-String ':5000\s+.*LISTENING\s+(\d+)$' | ForEach-Object { [regex]::Match($_.Line, 'LISTENING\s+(\d+)$').Groups[1].Value } | Where-Object { $_ } | Select-Object -Unique)
if ($portPids.Count -gt 0) { throw "5000번 포트를 PID $($portPids -join ', ') 프로세스가 사용 중입니다. 다른 프로세스를 자동 종료하지 않았습니다." }
$adminPortPids = @(netstat -ano -p tcp | Select-String ':5001\s+.*LISTENING\s+(\d+)$' | ForEach-Object { [regex]::Match($_.Line, 'LISTENING\s+(\d+)$').Groups[1].Value } | Where-Object { $_ } | Select-Object -Unique)
if ($adminPortPids.Count -gt 0) { throw "5001번 로컬 관리자 포트를 PID $($adminPortPids -join ', ') 프로세스가 사용 중입니다. 다른 프로세스를 자동 종료하지 않았습니다." }

& $PythonExe -c "import flask, flask_sqlalchemy, flask_migrate, waitress, argon2, kiwipiepy"
if ($LASTEXITCODE -ne 0) { throw "Python 의존성이 없습니다. .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt 를 실행해 주세요." }

$Pnpm = Get-Command "pnpm.cmd" -ErrorAction SilentlyContinue
if (-not $Pnpm) { $Pnpm = Get-Command "pnpm" -ErrorAction SilentlyContinue }
if (-not $Pnpm) { throw "pnpm을 찾을 수 없습니다." }
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "node_modules"))) { throw "node_modules가 없습니다. pnpm install을 먼저 실행해 주세요." }

if (-not $SkipBuild) {
    Write-Host "React production build를 실행합니다."
    & $Pnpm.Source --dir $ProjectRoot run build
    if ($LASTEXITCODE -ne 0) { throw "React production build에 실패했습니다." }
}

Write-Host "로컬 OCR 준비 상태를 확인합니다. OCR이 없어도 글빛의 다른 기능은 실행됩니다."
& $PythonExe (Join-Path $BackendRoot "diagnose_ocr.py")
if ($LASTEXITCODE -ne 0) { Write-Warning "OCR 진단을 완료하지 못했지만 서버 시작은 계속합니다." }

Write-Host "SQLite 마이그레이션을 적용합니다."
Push-Location $BackendRoot
try {
    & $PythonExe -m flask --app wsgi:app db upgrade
    if ($LASTEXITCODE -ne 0) { throw "SQLite 마이그레이션에 실패했습니다." }
} finally { Pop-Location }

Remove-Item -LiteralPath $ServerLog -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $ServerErrorLog -Force -ErrorAction SilentlyContinue
Write-Host "Waitress 일반 앱(127.0.0.1:5000)과 로컬 관리자(127.0.0.1:5001)를 시작합니다."
$PythonBase = (& $PythonExe -c "import sys; print(sys._base_executable)").Trim()
if (-not (Test-Path -LiteralPath $PythonBase)) { throw "가상환경의 기본 Python 실행 파일을 찾을 수 없습니다." }
$startedAt = (Get-Date).ToUniversalTime()
$server = Start-Process -FilePath $PythonBase -ArgumentList @("serve.py") -WorkingDirectory $BackendRoot -WindowStyle Hidden -PassThru
$state = [ordered]@{
    pid = $server.Id
    executable = [IO.Path]::GetFullPath($PythonBase)
    projectRoot = $ProjectRoot
    marker = "serve.py (Waitress 5000 + local admin 5001)"
    startedAt = $startedAt.ToString("o")
}
$state | ConvertTo-Json | Set-Content -LiteralPath $StateFile -Encoding utf8
$server.Id | Set-Content -LiteralPath $PidFile -Encoding ascii

$healthy = $false
for ($attempt = 0; $attempt -lt 40; $attempt += 1) {
    if ($server.HasExited) { break }
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $HealthUrl -TimeoutSec 2
        if ($response.StatusCode -eq 200) { $healthy = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 500
}

if (-not $healthy) {
    if (-not $server.HasExited) { Stop-Process -Id $server.Id -ErrorAction SilentlyContinue }
    Remove-StaleServerState
    throw "Waitress가 정상 응답하지 않습니다. 로그: $ServerErrorLog"
}

Write-Host "글빛이 실행되었습니다: http://127.0.0.1:5000 (PID $($server.Id))"
Write-Host "서버 컴퓨터 전용 관리자: http://127.0.0.1:5001/local-admin/api-key"
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:5000" }
