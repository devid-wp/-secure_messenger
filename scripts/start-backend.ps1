param(
    [switch]$NoReload,
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $projectRoot ".venv"
$pythonPath = Join-Path $venvPath "Scripts\python.exe"
$requirementsPath = Join-Path $projectRoot "requirements.txt"
$developmentRequirementsPath = Join-Path $projectRoot "requirements-dev.txt"
$requirementsStampPath = Join-Path $venvPath ".requirements.sha256"

Set-Location $projectRoot

function Find-BasePython {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return $pythonCommand.Source
    }

    $registryRoots = @(
        "HKCU:\Software\Python\PythonCore",
        "HKLM:\Software\Python\PythonCore",
        "HKLM:\Software\WOW6432Node\Python\PythonCore"
    )
    foreach ($registryRoot in $registryRoots) {
        $python = Get-ChildItem $registryRoot -ErrorAction SilentlyContinue |
            Sort-Object PSChildName -Descending |
            ForEach-Object {
                (Get-ItemProperty (Join-Path $_.PSPath "InstallPath") `
                    -ErrorAction SilentlyContinue).ExecutablePath
            } |
            Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
            Select-Object -First 1
        if ($python) {
            return $python
        }
    }
    throw "Python 3.12 or newer was not found. Install it from https://python.org/downloads/."
}

function Get-RequirementsHash {
    $content = (Get-Content -Raw $requirementsPath) + "`n" +
        (Get-Content -Raw $developmentRequirementsPath)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($content)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha256.ComputeHash($bytes)
    } finally {
        $sha256.Dispose()
    }
    return (($hash | ForEach-Object { $_.ToString("x2") }) -join "")
}

function New-ProjectVirtualEnvironment {
    if (Test-Path -LiteralPath $venvPath) {
        $brokenVenvPath = "$venvPath.broken-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Write-Host "The existing virtual environment is broken. Moving it to $brokenVenvPath"
        Move-Item -LiteralPath $venvPath -Destination $brokenVenvPath
    }

    Write-Host "Creating the Python virtual environment..."
    $basePython = Find-BasePython
    & $basePython -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the Python virtual environment with $basePython."
    }
}

$venvReady = Test-Path -LiteralPath $pythonPath
if ($venvReady) {
    try {
        & $pythonPath -c "import pydantic_core" 2>$null
        $venvReady = $LASTEXITCODE -eq 0
    } catch {
        $venvReady = $false
    }
}
if (-not $venvReady) {
    New-ProjectVirtualEnvironment
}

$requirementsHash = Get-RequirementsHash
$installedRequirementsHash = if (Test-Path -LiteralPath $requirementsStampPath) {
    (Get-Content -Raw $requirementsStampPath).Trim()
} else {
    ""
}
if ($installedRequirementsHash -ne $requirementsHash) {
    Write-Host "Installing backend dependencies..."
    & $pythonPath -m pip install -r $developmentRequirementsPath
    if ($LASTEXITCODE -ne 0) {
        throw "Backend dependency installation failed."
    }
    Set-Content -LiteralPath $requirementsStampPath -Value $requirementsHash
} else {
    Write-Host "Backend dependencies are up to date."
}

Write-Host "Applying database migrations..."
& $pythonPath -m alembic upgrade head

Write-Host "Starting backend at http://localhost:$Port"
$uvicornArguments = @(
    "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$Port"
)
if (-not $NoReload) {
    $uvicornArguments += "--reload"
}
& $pythonPath @uvicornArguments
