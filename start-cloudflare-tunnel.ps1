
param(
    [string]$WorkerUrl = $env:CLOUDFLARE_WORKER_URL,
    [string]$UpdateSecret = $env:TUNNEL_UPDATE_SECRET,
    [int]$FrontendPort = 5002,
    [int]$BackendPort = 5000
)

$ErrorActionPreference = "Stop"

function Write-Info($msg) {
    Write-Host "[INFO] $msg" -ForegroundColor Cyan
}

function Write-Err($msg) {
    Write-Host "[ERROR] $msg" -ForegroundColor Red
}

if (-not $WorkerUrl) {
    Write-Err "CLOUDFLARE_WORKER_URL is not set."
    exit 1
}

if (-not $UpdateSecret) {
    Write-Err "TUNNEL_UPDATE_SECRET is not set."
    exit 1
}

$cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue

if (-not $cloudflared) {
    Write-Err "cloudflared is not installed or not on PATH."
    exit 1
}

$LocalUrl = "http://127.0.0.1:$FrontendPort"

$stdoutLog = Join-Path $env:TEMP "edushield-cloudflared-out.log"
$stderrLog = Join-Path $env:TEMP "edushield-cloudflared-err.log"

Remove-Item $stdoutLog, $stderrLog -Force -ErrorAction SilentlyContinue

Write-Info "Starting Cloudflare Quick Tunnel for $LocalUrl"

$proc = Start-Process `
    -FilePath $cloudflared.Source `
    -ArgumentList @("tunnel", "--url", $LocalUrl) `
    -PassThru `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog

$tunnelUrl = $null

for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1

    $content = ""

    foreach ($file in @($stdoutLog, $stderrLog)) {
        if (Test-Path $file) {
            $content += Get-Content $file -Raw -ErrorAction SilentlyContinue
        }
    }

    if ($content -match "https://[a-z0-9-]+\.trycloudflare\.com") {
        $tunnelUrl = $Matches[0]
        break
    }

    if ($proc.HasExited) {
        break
    }
}

if (-not $tunnelUrl) {
    Write-Err "Failed to capture a trycloudflare.com URL."

    if (Test-Path $stdoutLog) {
        Get-Content $stdoutLog | Select-Object -Last 15
    }

    if (Test-Path $stderrLog) {
        Get-Content $stderrLog | Select-Object -Last 15
    }

    if (-not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force
    }

    exit 1
}

Write-Info "Tunnel URL captured successfully."
Write-Info "Registering tunnel with permanent Worker..."

$timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$message = "$timestamp.$tunnelUrl"

$hmac = New-Object System.Security.Cryptography.HMACSHA256
$hmac.Key = [Text.Encoding]::UTF8.GetBytes($UpdateSecret)

$signature = [BitConverter]::ToString(
    $hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($message))
).Replace("-", "").ToLowerInvariant()

$body = @{
    destination = $tunnelUrl
    timestamp = $timestamp
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod `
        -Method Post `
        -Uri "$($WorkerUrl.TrimEnd('/'))/register-tunnel" `
        -Headers @{
            "X-Tunnel-Timestamp" = "$timestamp"
            "X-Tunnel-Signature" = $signature
        } `
        -ContentType "application/json" `
        -Body $body
}
catch {
    Write-Err "Tunnel registration failed: $($_.Exception.Message)"

    if (-not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force
    }

    exit 1
}

if (-not $response.ok) {
    Write-Err "Worker did not confirm tunnel registration."

    if (-not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force
    }

    exit 1
}

Write-Host ""
Write-Info "Registration succeeded!"
Write-Info "Temporary mobile URL: $tunnelUrl"
Write-Info "Permanent Worker URL: $WorkerUrl"
Write-Info "Keep this window open while testing."
Write-Info "Press Ctrl+C to stop the tunnel."

try {
    while (-not $proc.HasExited) {
        Start-Sleep -Seconds 2
    }
}
finally {
    if (-not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force
    }
}
