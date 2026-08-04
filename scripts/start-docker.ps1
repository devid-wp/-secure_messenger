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
$dockerPlugins = Join-Path $env:ProgramFiles 'Docker\Docker\resources\cli-plugins'

function Invoke-Docker {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed with exit code $LASTEXITCODE." }
}

function Test-DockerEngine {
    & cmd.exe /d /c "docker info >nul 2>nul"
    return $LASTEXITCODE -eq 0
}

function Get-ComposeMode {
    & cmd.exe /d /c "docker compose version >nul 2>nul"
    if ($LASTEXITCODE -eq 0) { return 'plugin' }
    if (Get-Command docker-compose.exe -ErrorAction SilentlyContinue) { return 'legacy' }
    return $null
}

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $mode = Get-ComposeMode
    if ($mode -eq 'plugin') { & docker compose @Arguments }
    elseif ($mode -eq 'legacy') { & docker-compose @Arguments }
    else { throw 'Docker Compose is not installed. Finish Docker Desktop installation and restart Windows.' }
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed with exit code $LASTEXITCODE." }
}

function Refresh-DockerPath {
    if ((Test-Path $dockerBin) -and ($env:Path -notlike "*$dockerBin*")) {
        $env:Path = "$dockerBin;$env:Path"
    }
    if ((Test-Path $dockerPlugins) -and ($env:Path -notlike "*$dockerPlugins*")) {
        $env:Path = "$dockerPlugins;$env:Path"
    }
}

function Test-DockerInstallation {
    return (Test-Path $dockerDesktop) -and
        (Test-Path 'HKLM:\SOFTWARE\Docker Inc.\Docker Desktop') -and
        (Test-Path (Join-Path $dockerPlugins 'docker-compose.exe'))
}

function Repair-WindowsComponentStore {
    Write-Host ''
    Write-Host 'Windows component store corruption (14098) detected.' -ForegroundColor Yellow
    Write-Host 'Running the Microsoft-recommended DISM repair. This can take 10-30 minutes.' -ForegroundColor Yellow
    & dism.exe /Online /Cleanup-Image /RestoreHealth
    if ($LASTEXITCODE -ne 0) {
        throw "DISM could not repair Windows (exit code $LASTEXITCODE). Use a matching Windows installation source or perform an in-place Windows repair."
    }
    Write-Host 'Checking protected system files with SFC...' -ForegroundColor Cyan
    & sfc.exe /scannow
    if ($LASTEXITCODE -ne 0) {
        throw "SFC could not complete successfully (exit code $LASTEXITCODE)."
    }
    Write-Host ''
    Write-Host 'Windows repair completed. Restart Windows, then run start-docker.bat again.' -ForegroundColor Green
    exit 10
}

function Install-DockerDesktop {
    Write-Host 'Docker Desktop is missing or incomplete. Installing/repairing it now...' -ForegroundColor Yellow
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host 'Windows administrator approval is required once.' -ForegroundColor Yellow
        $elevatedArguments = @(
            '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', "`"$PSCommandPath`""
        )
        if ($Rebuild) { $elevatedArguments += '-Rebuild' }
        if ($Status) { $elevatedArguments += '-Status' }
        if ($Logs) { $elevatedArguments += '-Logs' }
        if ($Stop) { $elevatedArguments += '-Stop' }
        if ($NoBrowser) { $elevatedArguments += '-NoBrowser' }
        try {
            $elevated = Start-Process powershell.exe -ArgumentList $elevatedArguments -Verb RunAs -Wait -PassThru
        } catch {
            throw 'Administrator approval was cancelled. Run start-docker.bat again and approve the UAC prompt.'
        }
        exit $elevated.ExitCode
    }
    $downloadedInstaller = Join-Path $env:TEMP 'SecureMessenger-DockerDesktop-Installer.exe'
    $installer = $downloadedInstaller
    $url = 'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe'
    Write-Host 'Downloading the complete official Docker Desktop installer...'
    Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
    $signature = Get-AuthenticodeSignature -LiteralPath $installer
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Docker') {
        Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
        throw 'The Docker Desktop installer signature is not valid.'
    }
    $process = Start-Process -FilePath $installer -ArgumentList 'install', '--accept-license', '--backend=wsl-2' -Wait -PassThru
    Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
    if ($process.ExitCode -ne 0) {
        $adminInstallLog = 'C:\ProgramData\DockerDesktop\install-log-admin.txt'
        if ((Test-Path $adminInstallLog) -and (Select-String -Path $adminInstallLog -Pattern '14098|0x80073712' -Quiet)) {
            Repair-WindowsComponentStore
        }
        throw "Docker Desktop installation failed with exit code $($process.ExitCode). See C:\ProgramData\DockerDesktop\install-log-admin.txt."
    }
    Refresh-DockerPath
    if (-not (Test-DockerInstallation)) {
        throw 'Docker Desktop installation did not complete. Approve the UAC prompt, restart Windows, and run start-docker.bat again.'
    }
}

function Wait-DockerEngine {
    Refresh-DockerPath
    if (-not (Test-DockerInstallation)) { Install-DockerDesktop }
    if (Test-DockerEngine) { return }
    if (-not (Test-Path $dockerDesktop)) { throw 'Docker Desktop installation is incomplete.' }
    Write-Host 'Starting Docker Desktop...' -ForegroundColor Cyan
    $desktopProcess = Start-Process -FilePath $dockerDesktop -PassThru
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        Start-Sleep -Seconds 3
        if (Test-DockerEngine) { return }
        if ($attempt -ge 3 -and $desktopProcess.HasExited) {
            throw 'Docker Desktop exited before its engine started. Restart Windows to finish WSL 2 setup, then run start-docker.bat again.'
        }
        if ($attempt % 5 -eq 0) { Write-Host "Waiting for Docker engine... ($($attempt * 3)s)" }
    }
    throw 'Docker engine did not become ready. Restart Windows and run start-docker.bat again.'
}

try {
    Wait-DockerEngine
    Push-Location $projectRoot
    try {
        if ($Stop) {
            Invoke-Compose -f $compose down
            Write-Host 'Secure Messenger stopped. Persistent data was preserved.' -ForegroundColor Green
            exit 0
        }
        if ($Status) { Invoke-Compose -f $compose ps; exit 0 }
        if ($Logs) { Invoke-Compose -f $compose logs -f --tail 100; exit 0 }

        $composeMode = Get-ComposeMode
        if (-not $composeMode) { throw 'Docker Compose is unavailable. Restart Windows to complete Docker Desktop setup.' }
        if ($composeMode -eq 'plugin') {
            $backendImage = (& docker compose -f $compose images -q backend 2>$null)
            $frontendImage = (& docker compose -f $compose images -q frontend 2>$null)
        } else {
            $backendImage = (& docker-compose -f $compose images -q backend 2>$null)
            $frontendImage = (& docker-compose -f $compose images -q frontend 2>$null)
        }
        if ($Rebuild -or -not $backendImage -or -not $frontendImage) {
            Write-Host 'Preparing images. The first launch can take a few minutes...' -ForegroundColor Cyan
            Invoke-Compose -f $compose build --pull
        } else {
            Write-Host 'Reusing existing images for a fast startup.' -ForegroundColor Cyan
        }

        Write-Host 'Starting services and waiting for health checks...' -ForegroundColor Cyan
        Invoke-Compose -f $compose up -d --wait --wait-timeout 180
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
    if ((Get-Command docker.exe -ErrorAction SilentlyContinue) -and (Test-DockerEngine) -and (Get-ComposeMode)) {
        try { Invoke-Compose -f $compose logs --tail 60 } catch { }
    }
    exit 1
}
