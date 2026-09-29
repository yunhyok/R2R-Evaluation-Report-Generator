[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$InstallerPath,
    [Parameter(Mandatory)]
    [string]$InstallRoot,
    [ValidateRange(20, 300)]
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'
$disposableAppId = '{2E42973D-7A33-4CF3-91FD-7A4C62ACCC4F}'
$appExeName = 'R2REvaluationReportGenerator.exe'
$tempRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
$resolvedInstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$leaf = Split-Path -Leaf $resolvedInstallRoot
if (-not $resolvedInstallRoot.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "InstallRoot must be strictly under TEMP: $tempRoot"
}
if ($leaf -notmatch '^R2REvaluationReportGenerator-Verification-[A-Za-z0-9_-]+$') {
    throw 'InstallRoot must use the dedicated verification prefix.'
}
if (Test-Path -LiteralPath $resolvedInstallRoot) { throw "Refusing to reuse: $resolvedInstallRoot" }
if ((Split-Path -Leaf $InstallerPath) -notmatch 'disposable') {
    throw 'The lifecycle verifier accepts only the disposable-AppId installer.'
}

$uninstallKeys = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$disposableAppId`_is1",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$disposableAppId`_is1",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\$disposableAppId`_is1"
)
if ($uninstallKeys | Where-Object { Test-Path -LiteralPath $_ }) {
    throw 'Disposable AppId is already installed.'
}

function Invoke-ProcessWithTimeout {
    param([string]$FilePath, [string[]]$Arguments, [string]$Description)
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -PassThru -WindowStyle Hidden
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        $process | Stop-Process -Force
        throw "$Description timed out after $TimeoutSeconds seconds."
    }
    if ($process.ExitCode -ne 0) { throw "$Description failed: exit code $($process.ExitCode)." }
}

function Stop-InstalledApp {
    param([string]$ExecutablePath)
    Get-Process -Name 'R2REvaluationReportGenerator' -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $ExecutablePath } |
        Stop-Process -Force
}

$installer = [IO.Path]::GetFullPath($InstallerPath)
$appExe = Join-Path $resolvedInstallRoot $appExeName
$uninstaller = Join-Path $resolvedInstallRoot 'unins000.exe'
$synthetic = Join-Path $resolvedInstallRoot 'lifecycle-synthetic.xlsx'
$directoryArgument = '/DIR="' + $resolvedInstallRoot + '"'
$installArgs = @('/SP-', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOICONS', $directoryArgument)
$installed = $false
$uninstalled = $false

try {
    Invoke-ProcessWithTimeout $installer $installArgs 'Fresh installer run'
    $installed = $true
    if (-not (Test-Path -LiteralPath $appExe -PathType Leaf)) { throw 'Installed executable missing.' }
    Invoke-ProcessWithTimeout $appExe @('--self-test') 'Installed self-test'
    Invoke-ProcessWithTimeout $appExe @('--synthetic-export', $synthetic) 'Installed synthetic export'
    if (-not (Test-Path -LiteralPath $synthetic -PathType Leaf)) { throw 'Synthetic workbook missing.' }
    Invoke-ProcessWithTimeout $appExe @('--gui-smoke-test') 'Installed GUI smoke test'
    Invoke-ProcessWithTimeout $installer $installArgs 'Same-installer upgrade run'
    Invoke-ProcessWithTimeout $appExe @('--self-test') 'Post-upgrade self-test'
    $hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash
    Write-Output "Disposable installer SHA-256: $hash"
    if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) { throw 'Uninstaller missing.' }
    if (Test-Path -LiteralPath $synthetic -PathType Leaf) {
        Remove-Item -LiteralPath $synthetic -Force
    }
    Invoke-ProcessWithTimeout $uninstaller @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') 'Uninstall run'
    Start-Sleep -Seconds 2
    if (Test-Path -LiteralPath $appExe) { throw 'Uninstall left the application executable.' }
    if ($uninstallKeys | Where-Object { Test-Path -LiteralPath $_ }) { throw 'Uninstall key remains.' }
    if (Test-Path -LiteralPath $resolvedInstallRoot) {
        $residual = @(Get-ChildItem -Force -LiteralPath $resolvedInstallRoot)
        if ($residual.Count -ne 0) { throw 'Uninstall left files in the disposable install root.' }
        Remove-Item -LiteralPath $resolvedInstallRoot -Force
    }
    $uninstalled = $true
    Write-Output 'INSTALLER_LIFECYCLE_OK'
}
finally {
    Stop-InstalledApp $appExe
    if (Test-Path -LiteralPath $synthetic -PathType Leaf) {
        Remove-Item -LiteralPath $synthetic -Force
    }
    if ($installed -and -not $uninstalled -and (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
        try {
            Invoke-ProcessWithTimeout $uninstaller @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') 'Cleanup uninstall'
        }
        catch { Write-Warning "Cleanup uninstall failed: $($_.Exception.Message)" }
    }
}
