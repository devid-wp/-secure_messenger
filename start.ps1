$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is not installed. Install Docker Desktop, restart PowerShell, and run .\start.ps1 again."
}

Write-Host "Building and starting Secure Messenger..."
docker compose up --build
