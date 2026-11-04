param(
    [int]$BackendPort = 8010,
    [int]$FrontendPort = 5180
)

$root = $PSScriptRoot
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'

if (-not (Test-Path $python)) { throw "Missing backend venv: $python (see IMPLEMENTATION_PLAN.md, stage 0)" }
if (-not (Test-Path (Join-Path $root 'frontend\node_modules'))) {
    Push-Location (Join-Path $root 'frontend'); npm.cmd install; Pop-Location
}

# Actually try to bind: also catches ports reserved by Windows and IPv6-only listeners.
function Test-PortFree([int]$port) {
    foreach ($addr in '0.0.0.0', '127.0.0.1', '::1') {
        $l = $null
        try {
            $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse($addr), $port)
            $l.Start()
        }
        catch { return $false }
        finally { if ($l) { $l.Stop() } }
    }
    return $true
}

function Assert-PortFree([int]$port, [string]$name) {
    if (-not (Test-PortFree $port)) {
        throw "$name port $port is already in use. Stop the program using it, or pick another port: .\run.ps1 -BackendPort <n> -FrontendPort <n>"
    }
    return $port
}

$BackendPort = Assert-PortFree $BackendPort 'Backend'
$FrontendPort = Assert-PortFree $FrontendPort 'Frontend'

$backend = Start-Process -PassThru -NoNewWindow -WorkingDirectory (Join-Path $root 'backend') `
    -FilePath $python -ArgumentList '-m', 'uvicorn', 'app.main:app', '--port', $BackendPort

try {
    $env:API_URL = "http://127.0.0.1:$BackendPort"
    Write-Host "Backend : $env:API_URL"
    for ($i = 0; $i -lt 60; $i++) {
        try { Invoke-WebRequest "$env:API_URL/api/health" -UseBasicParsing -TimeoutSec 1 | Out-Null; break }
        catch { Start-Sleep -Milliseconds 500 }
    }
    Write-Host "App     : http://localhost:$FrontendPort   (Ctrl+C to stop)"
    Push-Location (Join-Path $root 'frontend')
    npm.cmd run dev -- --port $FrontendPort --strictPort --open
    Pop-Location
}
finally {
    if ($backend -and -not $backend.HasExited) { Stop-Process -Id $backend.Id -Force }
}
