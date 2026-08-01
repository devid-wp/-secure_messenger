$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot ".run"
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$smokePort = 8765
$baseUrl = "http://127.0.0.1:$smokePort"
$smokeRoot = Join-Path $runtimeRoot "desktop-smoke-$PID"
$smokeDatabase = Join-Path $smokeRoot "smoke.db"
$backendProcess = $null

function Test-BackendReady {
    try {
        Invoke-WebRequest -Uri "$baseUrl/" `
            -UseBasicParsing -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Stop-ProcessTree {
    param([int]$ProcessId)

    $children = Get-CimInstance Win32_Process `
        -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId $child.ProcessId
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Normalize-ProcessPath {
    $currentPath = [System.Environment]::GetEnvironmentVariable(
        "Path", [System.EnvironmentVariableTarget]::Process
    )
    [System.Environment]::SetEnvironmentVariable(
        "PATH", $null, [System.EnvironmentVariableTarget]::Process
    )
    [System.Environment]::SetEnvironmentVariable(
        "Path", $null, [System.EnvironmentVariableTarget]::Process
    )
    [System.Environment]::SetEnvironmentVariable(
        "Path", $currentPath, [System.EnvironmentVariableTarget]::Process
    )
}

Set-Location $projectRoot
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
Normalize-ProcessPath

try {
    if (Test-BackendReady) {
        throw "Port $smokePort is already in use; cannot start an isolated smoke backend."
    }
    New-Item -ItemType Directory -Force -Path $smokeRoot | Out-Null
    $env:APP_ENV = "test"
    $env:DATABASE_URL = "sqlite+aiosqlite:///$($smokeDatabase.Replace('\', '/'))"
    $env:UPLOAD_DIR = Join-Path $smokeRoot "uploads"
    $env:MEDIA_DIR = Join-Path $smokeRoot "media"

    Write-Host "Starting isolated FastAPI for desktop integration testing..."
    $backendProcess = Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $PSScriptRoot "start-backend.ps1"),
        "-NoReload",
        "-Port", "$smokePort"
    ) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtimeRoot "desktop-test-backend.log") `
        -RedirectStandardError (Join-Path $runtimeRoot "desktop-test-backend-error.log")

    $backendReady = $false
    for ($attempt = 0; $attempt -lt 360; $attempt++) {
        if (Test-BackendReady) {
            $backendReady = $true
            break
        }
        if ($backendProcess.HasExited) {
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $backendReady) {
        $errorLog = Join-Path $runtimeRoot "desktop-test-backend-error.log"
        if (Test-Path -LiteralPath $errorLog) {
            Get-Content -Tail 30 $errorLog | Write-Error
        }
        throw "FastAPI did not become ready within 180 seconds."
    }

    if (-not (Test-Path -LiteralPath $pythonPath)) {
        throw "The backend virtual environment was not created."
    }
    & $pythonPath (Join-Path $PSScriptRoot "desktop-smoke.py") `
        "--base-url" $baseUrl
    if ($LASTEXITCODE -ne 0) {
        throw "Desktop integration smoke test failed with code $LASTEXITCODE."
    }
} finally {
    if ($backendProcess -and -not $backendProcess.HasExited) {
        Stop-ProcessTree -ProcessId $backendProcess.Id
    }
    $resolvedRuntimeRoot = [System.IO.Path]::GetFullPath($runtimeRoot)
    $resolvedSmokeRoot = [System.IO.Path]::GetFullPath($smokeRoot)
    if (
        (Test-Path -LiteralPath $resolvedSmokeRoot) -and
        $resolvedSmokeRoot.StartsWith(
            "$resolvedRuntimeRoot\", [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        Remove-Item -LiteralPath $resolvedSmokeRoot -Recurse -Force
    }
}
