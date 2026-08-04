$ErrorActionPreference = 'Stop'
$configDirectory = Join-Path $env:LOCALAPPDATA 'SecureMessenger'
$configFile = Join-Path $configDirectory 'web-app-url.txt'

function Read-AppUrl {
    if (Test-Path $configFile) {
        $saved = (Get-Content -LiteralPath $configFile -Raw).Trim()
        if ($saved) { return $saved }
    }
    Write-Host 'First launch: paste the HTTPS address of your hosted Secure Messenger.' -ForegroundColor Cyan
    $entered = (Read-Host 'Site URL').Trim().TrimEnd('/')
    $uri = $null
    if (-not [Uri]::TryCreate($entered, [UriKind]::Absolute, [ref]$uri) -or $uri.Scheme -ne 'https') {
        throw 'A valid HTTPS address is required.'
    }
    New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
    Set-Content -LiteralPath $configFile -Value $uri.AbsoluteUri.TrimEnd('/') -Encoding UTF8
    return $uri.AbsoluteUri.TrimEnd('/')
}

try {
    $url = Read-AppUrl
    $edge = Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'
    $chrome = Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'
    if (Test-Path $edge) {
        Start-Process -FilePath $edge -ArgumentList "--app=$url", '--start-maximized'
    } elseif (Test-Path $chrome) {
        Start-Process -FilePath $chrome -ArgumentList "--app=$url", '--start-maximized'
    } else {
        Start-Process $url
    }
} catch {
    Write-Host "Open failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
