param(
    [switch]$Rebuild,
    [switch]$Status,
    [switch]$Logs,
    [switch]$Stop,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$projectRoot = Split-Path -Parent $PSScriptRoot
$compose = Join-Path $projectRoot 'compose.yaml'
$dockerDesktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
$dockerBin = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin'

function Invoke-Docker {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed with exit code $LASTEXITCODE." }
}

function Refresh-DockerPath {
    if ((Test-Path $dockerBin) -and ($env:Path -notlike "*$dockerBin*")) {
        $env:Path = "$dockerBin;$env:Path"
    }
}

function Install-DockerDesktop {
    Write-Host 'Docker Desktop is missing. Installing it now...' -ForegroundColor Yellow
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($winget) {
        & $winget.Source install --exact --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements --silent
        if ($LASTEXITCODE -ne 0) { throw "Docker Desktop installation failed with exit code $LASTEXITCODE." }
    } else {
        $installer = Join-Path $env:TEMP 'SecureMessenger-DockerDesktop-Installer.exe'
        $url = 'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe'
        Write-Host 'Downloading the official Docker Desktop installer...'
        Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
        $signature = Get-AuthenticodeSignature -LiteralPath $installer
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Docker') {
            Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
            throw 'The Docker Desktop installer signature is not valid.'
        }
        $process = Start-Process -FilePath $installer -ArgumentList 'install', '--accept-license', '--backend=wsl-2' -Verb RunAs -Wait -PassThru
        Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
        if ($process.ExitCode -ne 0) { throw "Docker Desktop installation failed with exit code $($process.ExitCode)." }
    }
    Refresh-DockerPath
    if (-not (Get-Command docker.exe -ErrorAction SilentlyContinue)) {
        throw 'Docker Desktop was installed, but Windows must be restarted. Restart and run start-docker.bat again.'
    }
}

function Wait-DockerEngine {
    Refresh-DockerPath
    if (-not (Get-Command docker.exe -ErrorAction SilentlyContinue)) { Install-DockerDesktop }
    & docker info *> $null
    if ($LASTEXITCODE -eq 0) { return }
    if (-not (Test-Path $dockerDesktop)) { throw 'Docker Desktop installation is incomplete.' }
    Write-Host 'Starting Docker Desktop...' -ForegroundColor Cyan
    Start-Process -FilePath $dockerDesktop
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        Start-Sleep -Seconds 3
        & docker info *> $null
        if ($LASTEXITCODE -eq 0) { return }
        if ($attempt % 5 -eq 0) { Write-Host "Waiting for Docker engine... ($($attempt * 3)s)" }
    }
    throw 'Docker engine did not become ready. Restart Windows and run start-docker.bat again.'
}

try {
    Wait-DockerEngine
    Push-Location $projectRoot
    try {
        if ($Stop) {
            Invoke-Docker compose -f $compose down
            Write-Host 'Secure Messenger stopped. Persistent data was preserved.' -ForegroundColor Green
            exit 0
        }
        if ($Status) { Invoke-Docker compose -f $compose ps; exit 0 }
        if ($Logs) { Invoke-Docker compose -f $compose logs -f --tail 100; exit 0 }

        $backendImage = (& docker compose -f $compose images -q backend 2>$null)
        $frontendImage = (& docker compose -f $compose images -q frontend 2>$null)
        if ($Rebuild -or -not $backendImage -or -not $frontendImage) {
            Write-Host 'Preparing images. The first launch can take a few minutes...' -ForegroundColor Cyan
            Invoke-Docker compose -f $compose build --pull
        } else {
            Write-Host 'Reusing existing images for a fast startup.' -ForegroundColor Cyan
        }

        Write-Host 'Starting services and waiting for health checks...' -ForegroundColor Cyan
        Invoke-Docker compose -f $compose up -d --wait --wait-timeout 180
        Write-Host ''
        Write-Host 'Secure Messenger is ready: http://localhost:8080' -ForegroundColor Green
        Write-Host 'Logs: start-docker.bat -Logs    Stop: start-docker.bat -Stop'
        if (-not $NoBrowser) { Start-Process 'http://localhost:8080' }
    } finally {
        Pop-Location
    }
} catch {
    Write-Host ''
    Write-Host "Startup failed: $($_.Exception.Message)" -ForegroundColor Red
    if (Get-Command docker.exe -ErrorAction SilentlyContinue) {
        & docker compose -f $compose logs --tail 60 2>$null
    }
    exit 1
}
