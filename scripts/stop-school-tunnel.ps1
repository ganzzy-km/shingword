Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PidFile = Join-Path $ProjectRoot ".school-tunnel.pid"
$StateFile = Join-Path $ProjectRoot ".school-tunnel-state.json"
$UrlFile = Join-Path $ProjectRoot "quick-tunnel-url.txt"
$stopServer = $false

function Get-ProcessRecord([int]$ProcessId) {
    Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
}

function Convert-ToUtc([object]$Value) {
    if ($Value -is [datetime]) { return ([datetime]$Value).ToUniversalTime() }
    return [datetimeoffset]::Parse([string]$Value, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind).UtcDateTime
}

if (Test-Path -LiteralPath $StateFile) {
    try { $state = Get-Content -LiteralPath $StateFile -Raw -Encoding utf8 | ConvertFrom-Json } catch { throw "터널 상태 파일을 읽을 수 없습니다. 안전을 위해 어떤 프로세스도 종료하지 않았습니다." }
    $stopServer = [bool]$state.serverStartedByTunnel
    $record = Get-ProcessRecord ([int]$state.pid)
    if ($null -eq $record) {
        Write-Host "기록된 cloudflared PID는 이미 종료되었습니다."
    } else {
        $expected = [IO.Path]::GetFullPath([string]$state.executable)
        $actual = if ($record.Path) { [IO.Path]::GetFullPath([string]$record.Path) } else { "" }
        $expectedStart = Convert-ToUtc $state.startedAt
        $owned = $actual -eq $expected -and [math]::Abs(($record.StartTime.ToUniversalTime() - $expectedStart).TotalSeconds) -lt 10
        if (-not $owned) { throw "PID $($state.pid)은 이번 글빛 Quick Tunnel 프로세스로 검증되지 않았습니다. 종료하지 않았습니다." }
        Stop-Process -Id ([int]$state.pid) -ErrorAction SilentlyContinue
        try { Wait-Process -Id ([int]$state.pid) -Timeout 5 -ErrorAction Stop } catch {
            if (Get-Process -Id ([int]$state.pid) -ErrorAction SilentlyContinue) { Stop-Process -Id ([int]$state.pid) -Force }
        }
        Write-Host "Quick Tunnel PID $($state.pid)을 종료했습니다."
    }
} else {
    Write-Host "이 프로젝트가 시작한 Quick Tunnel 상태 파일이 없습니다. 다른 cloudflared 프로세스는 종료하지 않았습니다."
}

Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $UrlFile -Force -ErrorAction SilentlyContinue

if ($stopServer) { & (Join-Path $PSScriptRoot "stop-geulbit.ps1") }
else { Write-Host "Quick Tunnel 시작 전에 실행 중이던 Waitress 서버는 유지했습니다." }
