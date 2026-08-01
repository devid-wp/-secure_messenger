param(
    [switch]$SkipBackend
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $projectRoot "frontend"
$runtimeRoot = Join-Path $projectRoot ".run"
$doctor = Join-Path $PSScriptRoot "desktop-doctor.ps1"

Set-Location $projectRoot
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null

$prerequisitesReady = & $doctor -NoExit
if (-not $prerequisitesReady) {
    throw "Desktop prerequisites are incomplete. See the diagnostics above."
}

function Import-VisualStudioEnvironment {
    if (Get-Command link.exe -ErrorAction SilentlyContinue) {
        return
    }
    $vswhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
    $installationPath = & $vswhere -latest -products "*" `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath
    if (-not $installationPath) {
        throw "Visual Studio Build Tools installation was not found."
    }
    $vsDevCmd = Join-Path $installationPath.Trim() "Common7\Tools\VsDevCmd.bat"
    if (-not (Test-Path -LiteralPath $vsDevCmd)) {
        throw "VsDevCmd.bat was not found at $vsDevCmd"
    }

    $command = "call `"$vsDevCmd`" -no_logo -arch=x64 -host_arch=x64 >nul && set"
    $environmentLines = & $env:ComSpec /d /s /c $command
    if ($LASTEXITCODE -ne 0) {
        throw "Could not initialize the MSVC developer environment."
    }
    foreach ($line in $environmentLines) {
        if ($line -match "^([^=]+)=(.*)$") {
            Set-Item -Path "Env:$($matches[1])" -Value $matches[2]
        }
    }
    if (-not (Get-Command link.exe -ErrorAction SilentlyContinue)) {
        throw "MSVC environment loaded, but link.exe is still unavailable."
    }
}

function Test-BackendReady {
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:8000/" `
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

Import-VisualStudioEnvironment

$backendProcess = $null
try {
    if (-not $SkipBackend -and -not (Test-BackendReady)) {
        Write-Host "Starting FastAPI for the desktop client..."
        $backendProcess = Start-Process -FilePath "powershell.exe" -ArgumentList @(
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", (Join-Path $PSScriptRoot "start-backend.ps1"),
            "-NoReload"
        ) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $runtimeRoot "desktop-backend.log") `
            -RedirectStandardError (Join-Path $runtimeRoot "desktop-backend-error.log")

        $backendReady = $false
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
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
            throw "FastAPI did not start. Check .run/desktop-backend-error.log."
        }
    }

    $npm = Get-Command npm.cmd -ErrorAction Stop
    Write-Host "Starting Secure Messenger desktop..." -ForegroundColor Green
    Push-Location $frontendRoot
    try {
        & $npm.Source run desktop:dev
        if ($LASTEXITCODE -ne 0) {
            throw "Tauri development process exited with code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }
} finally {
    if ($backendProcess -and -not $backendProcess.HasExited) {
        Stop-ProcessTree -ProcessId $backendProcess.Id
    }
}
