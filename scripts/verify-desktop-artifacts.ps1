param(
    [string]$TargetRoot = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $TargetRoot) {
    $TargetRoot = Join-Path $projectRoot "frontend\src-tauri\target\release"
}
$TargetRoot = [System.IO.Path]::GetFullPath($TargetRoot)
$application = Join-Path $TargetRoot "secure-messenger-desktop.exe"
$installer = Join-Path $TargetRoot "bundle\nsis\Secure Messenger_0.1.0_x64-setup.exe"

foreach ($artifact in @($application, $installer)) {
    if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) {
        throw "Desktop artifact is missing: $artifact"
    }
    $file = Get-Item -LiteralPath $artifact
    if ($file.Length -le 0) {
        throw "Desktop artifact is empty: $artifact"
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $artifact
    Write-Output ([pscustomobject]@{
        Path = $file.FullName
        SizeBytes = $file.Length
        Signature = $signature.Status
    })
}

Write-Host "Desktop release artifacts are present and non-empty." -ForegroundColor Green
