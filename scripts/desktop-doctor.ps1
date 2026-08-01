param(
    [switch]$NoExit
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $projectRoot "frontend"
$checks = [System.Collections.Generic.List[object]]::new()

function Add-DesktopCheck {
    param(
        [string]$Name,
        [bool]$Passed,
        [string]$Details,
        [bool]$Required = $true
    )

    $checks.Add([pscustomobject]@{
        Name = $Name
        Passed = $Passed
        Required = $Required
        Details = $Details
    })
}

function Find-VisualStudioInstallation {
    $vswhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path -LiteralPath $vswhere)) {
        return $null
    }

    $installationPath = & $vswhere -latest -products "*" `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath
    if ($LASTEXITCODE -ne 0 -or -not $installationPath) {
        return $null
    }
    return $installationPath.Trim()
}

function Find-WebView2Runtime {
    $applicationRoots = @(
        "C:\Program Files (x86)\Microsoft\EdgeWebView\Application",
        "C:\Program Files\Microsoft\EdgeWebView\Application"
    )
    foreach ($root in $applicationRoots) {
        if (-not (Test-Path -LiteralPath $root)) {
            continue
        }
        $runtime = Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName "msedgewebview2.exe" } |
            Where-Object { Test-Path -LiteralPath $_ } |
            Select-Object -First 1
        if ($runtime) {
            return $runtime
        }
    }

    $registryRoots = @(
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients",
        "HKCU:\Software\Microsoft\EdgeUpdate\Clients"
    )
    foreach ($registryRoot in $registryRoots) {
        $entry = Get-ChildItem $registryRoot -ErrorAction SilentlyContinue |
            ForEach-Object { Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue } |
            Where-Object { $_.name -like "*WebView2*" } |
            Select-Object -First 1
        if ($entry) {
            return "$($entry.name) $($entry.pv)".Trim()
        }
    }
    return $null
}

$rustc = Get-Command rustc.exe -ErrorAction SilentlyContinue
$cargo = Get-Command cargo.exe -ErrorAction SilentlyContinue
$rustup = Get-Command rustup.exe -ErrorAction SilentlyContinue
$node = Get-Command node.exe -ErrorAction SilentlyContinue
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue

Add-DesktopCheck "Rust compiler" ($null -ne $rustc) $(
    if ($rustc) { (& $rustc.Source --version) } else { "Install Rust stable with rustup" }
)
Add-DesktopCheck "Cargo" ($null -ne $cargo) $(
    if ($cargo) { (& $cargo.Source --version) } else { "cargo.exe was not found" }
)
Add-DesktopCheck "Rustup" ($null -ne $rustup) $(
    if ($rustup) { (& $rustup.Source show active-toolchain) } else { "rustup.exe was not found" }
)
Add-DesktopCheck "Node.js" ($null -ne $node) $(
    if ($node) { (& $node.Source --version) } else { "Install Node.js 20 or newer" }
)
Add-DesktopCheck "npm" ($null -ne $npm) $(
    if ($npm) { (& $npm.Source --version) } else { "npm.cmd was not found" }
)

$visualStudioPath = Find-VisualStudioInstallation
$linkCommand = Get-Command link.exe -ErrorAction SilentlyContinue
$linkPath = if ($linkCommand) {
    $linkCommand.Source
} elseif ($visualStudioPath) {
    Get-ChildItem (Join-Path $visualStudioPath "VC\Tools\MSVC") `
        -Filter link.exe -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -like "*\bin\Hostx64\x64\link.exe" } |
        Sort-Object FullName -Descending |
        Select-Object -ExpandProperty FullName -First 1
} else {
    $null
}
Add-DesktopCheck "MSVC linker" ($null -ne $linkPath) $(
    if ($linkPath) {
        $linkPath
    } else {
        "Install Visual Studio 2022 Build Tools: Desktop development with C++ and Windows 10/11 SDK"
    }
)

$webView2 = Find-WebView2Runtime
Add-DesktopCheck "WebView2 Runtime" ($null -ne $webView2) $(
    if ($webView2) { $webView2 } else { "Install Microsoft Edge WebView2 Evergreen Runtime" }
)

$tauriCli = Join-Path $frontendRoot "node_modules\@tauri-apps\cli\tauri.js"
Add-DesktopCheck "Frontend dependencies" (Test-Path -LiteralPath $tauriCli) $(
    if (Test-Path -LiteralPath $tauriCli) {
        "Tauri CLI is installed"
    } else {
        "Run npm install in frontend"
    }
)

$systemDrive = [System.IO.DriveInfo]::new($env:SystemDrive)
if ($systemDrive.IsReady) {
    $freeGb = [math]::Round($systemDrive.AvailableFreeSpace / 1GB, 2)
    Add-DesktopCheck "System drive free space" ($freeGb -ge 4) $(
        "$($systemDrive.RootDirectory.FullName) has $freeGb GB free; Build Tools may require at least 3.5 GB on the system drive"
    ) $false
}

Write-Host ""
Write-Host "Secure Messenger desktop diagnostics" -ForegroundColor Cyan
Write-Host "Project: $projectRoot"
Write-Host ""
foreach ($check in $checks) {
    $label = if ($check.Passed) { "OK" } elseif ($check.Required) { "MISSING" } else { "WARNING" }
    $color = if ($check.Passed) { "Green" } elseif ($check.Required) { "Red" } else { "Yellow" }
    Write-Host ("[{0}] {1}: {2}" -f $label, $check.Name, $check.Details) -ForegroundColor $color
}

$requiredFailures = @($checks | Where-Object { $_.Required -and -not $_.Passed })
if ($requiredFailures.Count -gt 0) {
    Write-Host ""
    Write-Host "Desktop prerequisites are incomplete." -ForegroundColor Red
    if (-not $NoExit) {
        exit 1
    }
    return $false
}

Write-Host ""
Write-Host "Desktop prerequisites are ready." -ForegroundColor Green
if (-not $NoExit) {
    exit 0
}
return $true
