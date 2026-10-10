Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$processPath = [Environment]::GetEnvironmentVariable("PATH", "Process")
[Environment]::SetEnvironmentVariable("Path", $null, "Process")
[Environment]::SetEnvironmentVariable("PATH", $processPath, "Process")

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TunnelPidFile = Join-Path $ProjectRoot ".school-tunnel.pid"
$TunnelStateFile = Join-Path $ProjectRoot ".school-tunnel-state.json"
$ServerStateFile = Join-Path $ProjectRoot ".school-server-state.json"
$TunnelLog = Join-Path $ProjectRoot ".school-tunnel.log"
$TunnelErrorLog = Join-Path $ProjectRoot ".school-tunnel-error.log"
$Http2Log = Join-Path $ProjectRoot ".school-tunnel-http2.log"
$Http2ErrorLog = Join-Path $ProjectRoot ".school-tunnel-http2-error.log"
$UrlFile = Join-Path $ProjectRoot "quick-tunnel-url.txt"
$LocalHealth = "http://127.0.0.1:5000/api/health"

function Get-ProcessRecord([int]$ProcessId) {
    Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
}

function Convert-ToUtc([object]$Value) {
    if ($Value -is [datetime]) { return ([datetime]$Value).ToUniversalTime() }
    return [datetimeoffset]::Parse([string]$Value, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind).UtcDateTime
}

function Test-OwnedTunnel([object]$State) {
    if ($null -eq $State -or $null -eq $State.pid) { return $false }
    $record = Get-ProcessRecord ([int]$State.pid)
    if ($null -eq $record) { return $false }
    $expected = [IO.Path]::GetFullPath([string]$State.executable)
    $actual = if ($record.Path) { [IO.Path]::GetFullPath([string]$record.Path) } else { "" }
    $expectedStart = Convert-ToUtc $State.startedAt
    return $actual -eq $expected -and [math]::Abs(($record.StartTime.ToUniversalTime() - $expectedStart).TotalSeconds) -lt 10
}

function Wait-ForTunnelUrl([System.Diagnostics.Process]$Process, [string]$OutputLog, [string]$ErrorLog) {
    for ($attempt = 0; $attempt -lt 90; $attempt += 1) {
        $content = ""
        if (Test-Path -LiteralPath $OutputLog) { $content += Get-Content -LiteralPath $OutputLog -Raw -ErrorAction SilentlyContinue }
        if (Test-Path -LiteralPath $ErrorLog) { $content += Get-Content -LiteralPath $ErrorLog -Raw -ErrorAction SilentlyContinue }
        $match = [regex]::Match($content, "https://[a-z0-9-]+\.trycloudflare\.com", [Text.RegularExpressions.RegexOptions]::IgnoreCase)
        if ($match.Success) { return $match.Value }
        if ($Process.HasExited) { return $null }
        Start-Sleep -Milliseconds 500
    }
    return $null
}

function Test-LocalServer {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $LocalHealth -TimeoutSec 3
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Test-ProductionBuildCurrent {
    $indexPath = Join-Path $ProjectRoot "dist\index.html"
    if (-not (Test-Path -LiteralPath $indexPath)) { return $false }
    $builtAt = (Get-Item -LiteralPath $indexPath).LastWriteTimeUtc
    $inputs = @(
        (Join-Path $ProjectRoot "index.html"),
        (Join-Path $ProjectRoot "package.json"),
        (Join-Path $ProjectRoot "pnpm-lock.yaml"),
        (Join-Path $ProjectRoot "vite.config.ts")
    )
    $inputs += Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "src") -Recurse -File -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
    foreach ($inputPath in $inputs) {
        if ((Test-Path -LiteralPath $inputPath) -and (Get-Item -LiteralPath $inputPath).LastWriteTimeUtc -gt $builtAt) {
            return $false
        }
    }
    return $true
}

function Get-LogSummary([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return "로그 파일 없음" }
    $lines = @(Get-Content -LiteralPath $Path -Tail 12 -ErrorAction SilentlyContinue)
    if ($lines.Count -eq 0) { return "로그 내용 없음" }
    return ($lines -join [Environment]::NewLine)
}

function Show-SchoolAddress([string]$Url, [switch]$AlreadyRunning) {
    Write-Host ""
    Write-Host "========================================"
    Write-Host "글빛 학교 접속 주소"
    Write-Host ""
    Write-Host $Url
    Write-Host ""
    Write-Host "========================================"
    if ($AlreadyRunning) { Write-Host "이미 학교 접속 서버가 실행 중입니다." }
    Write-Host "학교 PC 또는 태블릿의"
    Write-Host "Chrome 또는 Edge에서 접속하십시오."
    Write-Host ""
    Write-Host "현재 주소는"
    Write-Host "quick-tunnel-url.txt"
    Write-Host "파일에도 저장되었습니다."
    Write-Host ""
    Write-Host "Quick Tunnel을 다시 시작하면"
    Write-Host "주소가 변경될 수 있습니다."
    Write-Host "========================================"
}

function Get-CloudflaredPath {
    foreach ($commandName in @("cloudflared.exe", "cloudflared")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command) { return [IO.Path]::GetFullPath($command.Source) }
    }
    $candidates = @(
        (Join-Path $env:ProgramFiles "cloudflared\cloudflared.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "cloudflared\cloudflared.exe"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\cloudflared.exe")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return [IO.Path]::GetFullPath($candidate)
        }
    }
    return $null
}

function Stop-CurrentTunnel([System.Diagnostics.Process]$Process) {
    if (-not $Process.HasExited) {
        Stop-Process -Id $Process.Id -ErrorAction SilentlyContinue
        try { Wait-Process -Id $Process.Id -Timeout 5 -ErrorAction Stop } catch {
            if (Get-Process -Id $Process.Id -ErrorAction SilentlyContinue) { Stop-Process -Id $Process.Id -Force }
        }
    }
}

function Start-Tunnel([string]$Protocol, [string]$OutputLog, [string]$ErrorLog, [string]$CloudflaredExe) {
    Remove-Item -LiteralPath $OutputLog -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $ErrorLog -Force -ErrorAction SilentlyContinue
    $arguments = @("tunnel")
    if ($Protocol -eq "http2") { $arguments += @("--protocol", "http2") }
    $arguments += @("--url", "http://127.0.0.1:5000")
    return Start-Process -FilePath $CloudflaredExe -ArgumentList $arguments -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput $OutputLog -RedirectStandardError $ErrorLog -PassThru
}

Write-Host "글빛 프로젝트: $ProjectRoot"

if (Test-Path -LiteralPath $TunnelStateFile) {
    try { $existing = Get-Content -LiteralPath $TunnelStateFile -Raw -Encoding utf8 | ConvertFrom-Json } catch { $existing = $null }
    if (Test-OwnedTunnel $existing) {
        if ((Test-LocalServer) -and $existing.url) {
            $existing.pid | Set-Content -LiteralPath $TunnelPidFile -Encoding ascii
            ([string]$existing.url) | Set-Content -LiteralPath $UrlFile -Encoding utf8
            try { Set-Clipboard -Value ([string]$existing.url) } catch { Write-Warning "클립보드 복사는 지원되지 않았습니다." }
            Show-SchoolAddress ([string]$existing.url) -AlreadyRunning
            return
        }
        Write-Warning "기존 Quick Tunnel 프로세스는 살아 있지만 로컬 서버가 응답하지 않아 해당 터널만 정리합니다."
        $ownedProcess = Get-ProcessRecord ([int]$existing.pid)
        Stop-CurrentTunnel $ownedProcess
    }
    Remove-Item -LiteralPath $TunnelPidFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $TunnelStateFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $UrlFile -Force -ErrorAction SilentlyContinue
}
if (-not (Test-Path -LiteralPath $TunnelStateFile)) {
    Remove-Item -LiteralPath $TunnelPidFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $UrlFile -Force -ErrorAction SilentlyContinue
}

$serverWasRunning = $false
if (Test-Path -LiteralPath $ServerStateFile) { $serverWasRunning = Test-LocalServer }

$serverStartedByTunnel = -not $serverWasRunning
try {
    if (Test-ProductionBuildCurrent) {
        Write-Host "React production build가 최신 상태입니다."
        & (Join-Path $PSScriptRoot "start-geulbit.ps1") -NoBrowser -SkipBuild
    } else {
        Write-Host "React production build가 없거나 소스보다 오래되어 다시 생성합니다."
        & (Join-Path $PSScriptRoot "start-geulbit.ps1") -NoBrowser
    }
    try {
        $localResponse = Invoke-WebRequest -UseBasicParsing -Uri $LocalHealth -TimeoutSec 5
        if ($localResponse.StatusCode -ne 200) { throw "HTTP $($localResponse.StatusCode)" }
    } catch { throw "로컬 Waitress 서버가 정상 응답하지 않습니다." }

    $CloudflaredExe = Get-CloudflaredPath
    if (-not $CloudflaredExe) {
        throw "cloudflared가 설치되어 있지 않습니다. 자동 다운로드하지 않았습니다. 공식 Cloudflare 문서에 따라 설치하거나 'winget install --id Cloudflare.cloudflared'를 실행한 뒤 다시 시도해 주세요."
    }
    & $CloudflaredExe --version
    if ($LASTEXITCODE -ne 0) { throw "cloudflared --version 확인에 실패했습니다." }

    $userProfile = [Environment]::GetFolderPath("UserProfile")
    foreach ($configName in @("config.yml", "config.yaml")) {
        $configPath = Join-Path (Join-Path $userProfile ".cloudflared") $configName
        if (Test-Path -LiteralPath $configPath) { Write-Warning "$configPath 파일이 Quick Tunnel 실행을 방해할 수 있습니다. 자동 변경하지 않았습니다." }
    }

    Remove-Item -LiteralPath $UrlFile -Force -ErrorAction SilentlyContinue
    Write-Host "Cloudflare Quick Tunnel을 시작합니다."
    $protocol = "quic"
    $activeLog = $TunnelLog
    $activeErrorLog = $TunnelErrorLog
    $tunnel = Start-Tunnel $protocol $activeLog $activeErrorLog $CloudflaredExe
    $url = Wait-ForTunnelUrl $tunnel $activeLog $activeErrorLog

    $defaultFailure = $null
    if (-not $url) {
        $defaultFailure = Get-LogSummary $activeErrorLog
        Write-Warning "기본 QUIC 연결에서 주소를 만들지 못했습니다. HTTP/2로 한 번 다시 시도합니다."
        Stop-CurrentTunnel $tunnel
        $protocol = "http2"
        $activeLog = $Http2Log
        $activeErrorLog = $Http2ErrorLog
        $tunnel = Start-Tunnel $protocol $activeLog $activeErrorLog $CloudflaredExe
        $url = Wait-ForTunnelUrl $tunnel $activeLog $activeErrorLog
    }

    if (-not $url) {
        $http2Failure = Get-LogSummary $activeErrorLog
        Stop-CurrentTunnel $tunnel
        throw "Cloudflare Quick Tunnel 생성에 실패했습니다.`n`n기본 연결 결과:`n$defaultFailure`n`nHTTP/2 재시도 결과:`n$http2Failure`n`n수동 실행 명령:`ncloudflared tunnel --protocol http2 --url http://127.0.0.1:5000"
    }

    $state = [ordered]@{
        pid = $tunnel.Id
        executable = $CloudflaredExe
        projectRoot = $ProjectRoot
        marker = "tunnel 127.0.0.1:5000"
        protocol = $protocol
        url = $url
        outputLog = $activeLog
        errorLog = $activeErrorLog
        serverStartedByTunnel = $serverStartedByTunnel
        startedAt = (Get-Date).ToUniversalTime().ToString("o")
        externalVerified = $false
    }

    try {
        $external = Invoke-WebRequest -UseBasicParsing -Uri "$url/api/health" -TimeoutSec 20
        $state.externalVerified = $external.StatusCode -eq 200
    } catch { Write-Warning "공개 주소의 외부 HTTP 응답은 아직 확인하지 못했습니다. 터널 프로세스와 URL은 생성되었습니다." }

    $state | ConvertTo-Json | Set-Content -LiteralPath $TunnelStateFile -Encoding utf8
    $tunnel.Id | Set-Content -LiteralPath $TunnelPidFile -Encoding ascii
    $url | Set-Content -LiteralPath $UrlFile -Encoding utf8
    try { Set-Clipboard -Value $url } catch { Write-Warning "클립보드 복사는 지원되지 않았습니다." }

    Show-SchoolAddress $url
    Write-Host "사용이 끝나면 stop-school-tunnel.bat를 실행하세요."
} catch {
    if ($serverStartedByTunnel) {
        try { & (Join-Path $PSScriptRoot "stop-geulbit.ps1") } catch { Write-Warning "실패 후 Waitress 정리 중 오류가 발생했습니다: $($_.Exception.Message)" }
    }
    throw
}
