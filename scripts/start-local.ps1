$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$frontendPath = Join-Path $projectRoot "frontend"
$toolsPath = Join-Path $projectRoot ".tools"
$runtimePath = Join-Path $projectRoot ".run"
$pythonVersion = "3.13.13"
$pythonSha256 = "3c9c81d80f91c002ced86d645422d81432c68c7d9b6b0e974768ca2e449a4d00"
$nodeVersion = "24.18.0"

Set-Location $projectRoot

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Find-SystemPython {
    $localPython = Join-Path $env:LocalAppData "Programs\Python\Python313\python.exe"
    if (Test-Path -LiteralPath $localPython) {
        return $localPython
    }
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return $pythonCommand.Source
    }
    return $null
}

function Install-Python {
    New-Item -ItemType Directory -Force -Path $toolsPath | Out-Null
    $installerPath = Join-Path $toolsPath "python-$pythonVersion-amd64.exe"
    $installerUrl = "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-amd64.exe"

    Write-Host "Python is missing. Downloading Python $pythonVersion..."
    Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath
    $actualHash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash
    if ($actualHash -ne $pythonSha256) {
        throw "The downloaded Python installer failed checksum verification."
    }

    Write-Host "Installing Python for the current Windows user..."
    $installer = Start-Process -FilePath $installerPath -ArgumentList @(
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=1",
        "Include_launcher=1",
        "Include_test=0"
    ) -Wait -PassThru
    if ($installer.ExitCode -ne 0) {
        throw "Python installation failed with code $($installer.ExitCode)."
    }
    Refresh-ProcessPath
}

function Find-NodeTools {
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($nodeCommand -and $npmCommand) {
        return @{
            Node = $nodeCommand.Source
            Npm = $npmCommand.Source
        }
    }

    $portableRoot = Join-Path $toolsPath "node-v$nodeVersion-win-x64"
    $portableNode = Join-Path $portableRoot "node.exe"
    $portableNpm = Join-Path $portableRoot "npm.cmd"
    if (-not (Test-Path -LiteralPath $portableNode)) {
        New-Item -ItemType Directory -Force -Path $toolsPath | Out-Null
        $archiveName = "node-v$nodeVersion-win-x64.zip"
        $archivePath = Join-Path $toolsPath $archiveName
        $baseUrl = "https://nodejs.org/dist/v$nodeVersion"

        Write-Host "Node.js is missing. Downloading portable Node.js $nodeVersion LTS..."
        Invoke-WebRequest -Uri "$baseUrl/$archiveName" -OutFile $archivePath
        $checksums = (Invoke-WebRequest -Uri "$baseUrl/SHASUMS256.txt").Content
        $expectedHash = (
            $checksums -split "`n" |
            Where-Object { $_ -match "\s+$([regex]::Escape($archiveName))$" } |
            Select-Object -First 1
        ).Split()[0]
        if (-not $expectedHash) {
            throw "Could not find the official Node.js checksum."
        }
        $actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash
        if ($actualHash -ne $expectedHash) {
            throw "The downloaded Node.js archive failed checksum verification."
        }
        Expand-Archive -LiteralPath $archivePath -DestinationPath $toolsPath -Force
    }
    return @{
        Node = $portableNode
        Npm = $portableNpm
    }
}

function Wait-ForUrl([string]$Url, [string]$Name) {
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        try {
            Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 | Out-Null
            Write-Host "$Name is ready."
            return
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    throw "$Name did not become ready. Check the logs in $runtimePath."
}

$systemPython = Find-SystemPython
if (-not $systemPython) {
    Install-Python
    $systemPython = Find-SystemPython
}
if (-not $systemPython) {
    throw "Python was installed but could not be found. Restart Windows and try again."
}

$nodeTools = Find-NodeTools
Write-Host "Python: $(& $systemPython --version)"
Write-Host "Node.js: $(& $nodeTools.Node --version)"

$venvHealthy = $false
if (Test-Path -LiteralPath $venvPython) {
    & $venvPython -c "import pydantic_core" 2>$null
    $venvHealthy = $LASTEXITCODE -eq 0
}
if (-not $venvHealthy) {
    if (Test-Path -LiteralPath $venvPath) {
        $backupPath = "$venvPath.broken-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Write-Host "Moving the broken virtual environment to $backupPath"
        Move-Item -LiteralPath $venvPath -Destination $backupPath
    }
    Write-Host "Creating a clean Python environment..."
    & $systemPython -m venv $venvPath
}

Write-Host "Checking backend dependencies..."
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements-dev.txt

Write-Host "Applying database migrations..."
& $venvPython -m alembic upgrade head

Write-Host "Checking frontend dependencies..."
Push-Location $frontendPath
try {
    & $nodeTools.Npm install
} finally {
    Pop-Location
}

New-Item -ItemType Directory -Force -Path $runtimePath | Out-Null
$backendLog = Join-Path $runtimePath "backend.log"
$backendErrorLog = Join-Path $runtimePath "backend-error.log"
$frontendLog = Join-Path $runtimePath "frontend.log"
$frontendErrorLog = Join-Path $runtimePath "frontend-error.log"

$backend = $null
$frontend = $null
try {
    Write-Host "Starting backend and frontend..."
    $backend = Start-Process -FilePath $venvPython -ArgumentList @(
        "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1", "--port", "8000"
    ) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $backendLog -RedirectStandardError $backendErrorLog
    $frontend = Start-Process -FilePath $nodeTools.Npm -ArgumentList @(
        "run", "dev", "--", "--host", "127.0.0.1"
    ) -WorkingDirectory $frontendPath -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendErrorLog

    Wait-ForUrl "http://127.0.0.1:8000/" "Backend"
    Wait-ForUrl "http://127.0.0.1:5173/" "Frontend"

    Write-Host ""
    Write-Host "Secure Messenger is ready:"
    Write-Host "http://localhost:5173" -ForegroundColor Green
    Write-Host ""
    Write-Host "Keep this window open. Press Ctrl+C to stop both servers."
    while (-not $backend.HasExited -and -not $frontend.HasExited) {
        Start-Sleep -Seconds 1
    }
    throw "A server stopped unexpectedly. Check the logs in $runtimePath."
} finally {
    if ($backend -and -not $backend.HasExited) {
        Stop-Process -Id $backend.Id -Force
    }
    if ($frontend -and -not $frontend.HasExited) {
        Stop-Process -Id $frontend.Id -Force
    }
}
