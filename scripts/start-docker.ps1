param(
    [switch]$Rebuild,
    [switch]$Status,
    [switch]$Logs,
    [switch]$Stop,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$compose = Join-Path $projectRoot 'compose.yaml'

function Invoke-Docker {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed with exit code $LASTEXITCODE."
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker Desktop is not installed or docker.exe is not in PATH.'
}

try {
    & docker info *> $null
} catch {
    throw 'Docker Desktop is not running. Start it and run start-docker.bat again.'
}
if ($LASTEXITCODE -ne 0) {
    throw 'Docker Desktop is not running. Start it and run start-docker.bat again.'
}

Push-Location $projectRoot
try {
    if ($Stop) {
        Invoke-Docker compose -f $compose down
        Write-Host 'Secure Messenger stopped. Persistent data was preserved.' -ForegroundColor Green
        exit 0
    }
    if ($Status) {
        Invoke-Docker compose -f $compose ps
        exit 0
    }
    if ($Logs) {
        Invoke-Docker compose -f $compose logs -f --tail 100
        exit 0
    }

    $backendImage = (& docker compose -f $compose images -q backend 2>$null)
    $frontendImage = (& docker compose -f $compose images -q frontend 2>$null)
    $needsBuild = $Rebuild -or -not $backendImage -or -not $frontendImage

    if ($needsBuild) {
        Write-Host 'Preparing Secure Messenger images (first launch can take a few minutes)...' -ForegroundColor Cyan
        Invoke-Docker compose -f $compose build --pull
    } else {
        Write-Host 'Reusing existing images for a fast startup.' -ForegroundColor Cyan
    }

    Write-Host 'Starting services and waiting for health checks...' -ForegroundColor Cyan
    Invoke-Docker compose -f $compose up -d --wait --wait-timeout 180

    Write-Host ''
    Write-Host 'Secure Messenger is ready: http://localhost:8080' -ForegroundColor Green
    Write-Host 'API documentation:         http://localhost:8000/docs'
    Write-Host 'Logs:  start-docker.bat -Logs'
    Write-Host 'Stop:  start-docker.bat -Stop'
    if (-not $NoBrowser) {
        Start-Process 'http://localhost:8080'
    }
} catch {
    Write-Host ''
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host 'Recent service logs:' -ForegroundColor Yellow
    & docker compose -f $compose logs --tail 60 2>$null
    exit 1
} finally {
    Pop-Location
}
