Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ServerStateFile = Join-Path $ProjectRoot ".school-server-state.json"
$TunnelStateFile = Join-Path $ProjectRoot ".school-tunnel-state.json"
$UrlFile = Join-Path $ProjectRoot "quick-tunnel-url.txt"
$ServerLog = Join-Path $ProjectRoot ".school-server.log"
$TunnelLog = Join-Path $ProjectRoot ".school-tunnel.log"

function Get-ProcessRecord([int]$ProcessId) {
    Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
}

function Convert-ToUtc([object]$Value) {
    if ($Value -is [datetime]) { return ([datetime]$Value).ToUniversalTime() }
    return [datetimeoffset]::Parse([string]$Value, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind).UtcDateTime
}

function Get-ValidatedState([string]$Path, [string]$Kind) {
    if (-not (Test-Path -LiteralPath $Path)) { return [pscustomobject]@{ exists = $false; valid = $false; stale = $false; state = $null } }
    try { $state = Get-Content -LiteralPath $Path -Raw -Encoding utf8 | ConvertFrom-Json } catch { return [pscustomobject]@{ exists = $true; valid = $false; stale = $true; state = $null } }
    $record = Get-ProcessRecord ([int]$state.pid)
    if ($null -eq $record) { return [pscustomobject]@{ exists = $true; valid = $false; stale = $true; state = $state } }
    $expected = [IO.Path]::GetFullPath([string]$state.executable)
    $actual = if ($record.Path) { [IO.Path]::GetFullPath([string]$record.Path) } else { "" }
    $expectedStart = Convert-ToUtc $state.startedAt
    $startValid = [math]::Abs(($record.StartTime.ToUniversalTime() - $expectedStart).TotalSeconds) -lt 10
    return [pscustomobject]@{ exists = $true; valid = ($actual -eq $expected -and $startValid); stale = $false; state = $state }
}

$server = Get-ValidatedState $ServerStateFile "server"
$tunnel = Get-ValidatedState $TunnelStateFile "tunnel"
$httpStatus = "응답 없음"
try { $httpStatus = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:5000/api/health" -TimeoutSec 3).StatusCode } catch { }
$urlExists = Test-Path -LiteralPath $UrlFile
$url = if ($urlExists) { (Get-Content -LiteralPath $UrlFile -Raw -Encoding utf8).Trim() } else { "없음" }

Write-Host "프로젝트 경로: $ProjectRoot"
Write-Host "Waitress 실행 여부: $($server.valid)"
Write-Host "Waitress PID: $(if ($server.state) { $server.state.pid } else { '없음' })"
Write-Host "Waitress 프로세스 검증: $(if ($server.valid) { '정상' } elseif ($server.stale) { '오래된 상태 파일' } else { '검증 실패 또는 없음' })"
Write-Host "127.0.0.1:5000 HTTP 상태: $httpStatus"
Write-Host "cloudflared 실행 여부: $($tunnel.valid)"
Write-Host "cloudflared PID: $(if ($tunnel.state) { $tunnel.state.pid } else { '없음' })"
Write-Host "cloudflared 프로세스 검증: $(if ($tunnel.valid) { '정상' } elseif ($tunnel.stale) { '오래된 상태 파일' } else { '검증 실패 또는 없음' })"
Write-Host "quick-tunnel-url.txt 존재: $urlExists"
Write-Host "현재 학교 접속 URL: $(if ($tunnel.valid) { $url } else { '현재 접속 가능하다고 확인할 수 없음' })"
Write-Host "서버 로그: $ServerLog"
Write-Host "터널 로그: $(if ($tunnel.state -and $tunnel.state.outputLog) { $tunnel.state.outputLog } else { $TunnelLog })"
