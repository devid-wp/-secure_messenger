param(
    [switch]$NoReload
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $projectRoot ".venv"
$pythonPath = Join-Path $venvPath "Scripts\python.exe"

Set-Location $projectRoot

function New-ProjectVirtualEnvironment {
    if (Test-Path -LiteralPath $venvPath) {
        $brokenVenvPath = "$venvPath.broken-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Write-Host "The existing virtual environment is broken. Moving it to $brokenVenvPath"
        Move-Item -LiteralPath $venvPath -Destination $brokenVenvPath
    }

    Write-Host "Creating the Python virtual environment..."
    python -m venv $venvPath
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    New-ProjectVirtualEnvironment
}

& $pythonPath -c "import pydantic_core" 2>$null
if ($LASTEXITCODE -ne 0) {
    New-ProjectVirtualEnvironment
}

Write-Host "Installing backend dependencies..."
& $pythonPath -m pip install --upgrade pip
& $pythonPath -m pip install -r requirements-dev.txt

Write-Host "Applying database migrations..."
& $pythonPath -m alembic upgrade head

Write-Host "Starting backend at http://localhost:8000"
$uvicornArguments = @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000")
if (-not $NoReload) {
    $uvicornArguments += "--reload"
}
& $pythonPath @uvicornArguments
