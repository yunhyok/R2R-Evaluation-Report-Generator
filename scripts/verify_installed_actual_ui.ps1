[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$InstallerPath,
    [Parameter(Mandatory)]
    [string]$InstallRoot,
    [Parameter(Mandatory)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$MeasurementPath,
    [Parameter(Mandatory)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$PredictionPath,
    [Parameter(Mandatory)]
    [string]$OutputPath,
    [ValidateRange(20, 600)]
    [int]$TimeoutSeconds = 240
)

$ErrorActionPreference = 'Stop'
$disposableAppId = '{2E42973D-7A33-4CF3-91FD-7A4C62ACCC4F}'
$appExeName = 'R2REvaluationReportGenerator.exe'
$actualUiScript = Join-Path $PSScriptRoot 'verify_actual_ui.ps1'
$tempRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
$resolvedInstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$installLeaf = Split-Path -Leaf $resolvedInstallRoot
$installer = [IO.Path]::GetFullPath($InstallerPath)
$measurement = [IO.Path]::GetFullPath($MeasurementPath)
$prediction = [IO.Path]::GetFullPath($PredictionPath)
$output = [IO.Path]::GetFullPath($OutputPath)

if (-not $resolvedInstallRoot.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "InstallRoot must be strictly under TEMP: $tempRoot"
}
if ($installLeaf -notmatch '^R2REvaluationReportGenerator-Verification-[A-Za-z0-9_-]+$') {
    throw 'InstallRoot must use the dedicated verification prefix.'
}
if (Test-Path -LiteralPath $resolvedInstallRoot) {
    throw "Refusing to reuse InstallRoot: $resolvedInstallRoot"
}
if ((Split-Path -Leaf $installer) -notmatch '(?i)disposable') {
    throw 'The installed actual-UI verifier accepts only the disposable-AppId installer.'
}
if (-not (Test-Path -LiteralPath $actualUiScript -PathType Leaf)) {
    throw "Existing actual-UI verifier is missing: $actualUiScript"
}
if ([IO.Path]::GetExtension($output) -ine '.xlsx') {
    throw 'OutputPath must end in .xlsx.'
}
$outputParent = Split-Path -Parent $output
if (-not (Test-Path -LiteralPath $outputParent -PathType Container)) {
    throw 'OutputPath parent directory must exist.'
}

function Get-ColorOnlyPath {
    param([string]$Path)
    $parent = Split-Path -Parent $Path
    $stem = [IO.Path]::GetFileNameWithoutExtension($Path)
    return Join-Path $parent ($stem + '-color-only.xlsx')
}

function Get-ScaleOutputPath {
    param([string]$Path, [string]$Label)
    $parent = Split-Path -Parent $Path
    $stem = [IO.Path]::GetFileNameWithoutExtension($Path)
    return Join-Path $parent ($stem + '-dpi-' + $Label + '.xlsx')
}

$scales = @(
    @{ Label = '100'; Factor = '0.6666667' },
    @{ Label = '125'; Factor = '0.8333333' },
    @{ Label = '150'; Factor = '1' }
)
$scaleOutputs = @{}
foreach ($scale in $scales) {
    $scaleOutputs[$scale.Label] = if ($scale.Label -eq '100') {
        $output
    }
    else {
        Get-ScaleOutputPath $output $scale.Label
    }
}
$outputCandidates = @($output, (Get-ColorOnlyPath $output))
foreach ($scale in $scales) {
    $scaleOutput = $scaleOutputs[$scale.Label]
    $outputCandidates += @($scaleOutput, (Get-ColorOnlyPath $scaleOutput))
}
$existingOutputs = @($outputCandidates | Select-Object -Unique | Where-Object {
        Test-Path -LiteralPath $_
    })
if ($existingOutputs.Count -gt 0) {
    throw "Refusing to overwrite existing output pair(s): $($existingOutputs -join ', ')"
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
    if ($process.ExitCode -ne 0) {
        throw "$Description failed: exit code $($process.ExitCode)."
    }
}

function Stop-InstalledApp {
    param([string]$ExecutablePath)
    Get-Process -Name 'R2REvaluationReportGenerator' -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $ExecutablePath } |
        Stop-Process -Force
}

function Invoke-ActualUi {
    param([string]$ExecutablePath, [string]$ScaleLabel, [string]$ScaleFactor, [string]$ScaleOutput)
    $previousQpa = $env:QT_QPA_PLATFORM
    $previousScale = $env:QT_SCALE_FACTOR
    $previousAuto = $env:QT_AUTO_SCREEN_SCALE_FACTOR
    try {
        Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
        $env:QT_SCALE_FACTOR = $ScaleFactor
        $env:QT_AUTO_SCREEN_SCALE_FACTOR = '0'
        & $actualUiScript `
            -ExecutablePath $ExecutablePath `
            -MeasurementPath $measurement `
            -PredictionPath $prediction `
            -OutputPath $ScaleOutput `
            -TimeoutSeconds $TimeoutSeconds
        if (-not $?) {
            throw "Actual UI workflow failed at effective $ScaleLabel percent."
        }
    }
    finally {
        if ($null -eq $previousQpa) { Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue }
        else { $env:QT_QPA_PLATFORM = $previousQpa }
        if ($null -eq $previousScale) { Remove-Item Env:QT_SCALE_FACTOR -ErrorAction SilentlyContinue }
        else { $env:QT_SCALE_FACTOR = $previousScale }
        if ($null -eq $previousAuto) { Remove-Item Env:QT_AUTO_SCREEN_SCALE_FACTOR -ErrorAction SilentlyContinue }
        else { $env:QT_AUTO_SCREEN_SCALE_FACTOR = $previousAuto }
    }
}

$appExe = Join-Path $resolvedInstallRoot $appExeName
$uninstaller = Join-Path $resolvedInstallRoot 'unins000.exe'
$synthetic = Join-Path $resolvedInstallRoot 'installed-ui-synthetic.xlsx'
$directoryArgument = '/DIR="' + $resolvedInstallRoot + '"'
$installArgs = @('/SP-', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOICONS', $directoryArgument)
$installed = $false
$uninstalled = $false

try {
    Invoke-ProcessWithTimeout $installer $installArgs 'Fresh disposable installer run'
    $installed = $true
    if (-not (Test-Path -LiteralPath $appExe -PathType Leaf)) {
        throw 'Installed executable missing.'
    }
    Invoke-ProcessWithTimeout $appExe @('--self-test') 'Installed self-test'

    foreach ($scale in $scales) {
        $previousQpa = $env:QT_QPA_PLATFORM
        $previousScale = $env:QT_SCALE_FACTOR
        $previousAuto = $env:QT_AUTO_SCREEN_SCALE_FACTOR
        try {
            $env:QT_QPA_PLATFORM = 'offscreen'
            $env:QT_SCALE_FACTOR = $scale.Factor
            $env:QT_AUTO_SCREEN_SCALE_FACTOR = '0'
            Invoke-ProcessWithTimeout $appExe @('--gui-smoke-test') `
                "Installed GUI smoke at effective $($scale.Label)% (factor $($scale.Factor), offscreen)"
        }
        finally {
            if ($null -eq $previousQpa) { Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue }
            else { $env:QT_QPA_PLATFORM = $previousQpa }
            if ($null -eq $previousScale) { Remove-Item Env:QT_SCALE_FACTOR -ErrorAction SilentlyContinue }
            else { $env:QT_SCALE_FACTOR = $previousScale }
            if ($null -eq $previousAuto) { Remove-Item Env:QT_AUTO_SCREEN_SCALE_FACTOR -ErrorAction SilentlyContinue }
            else { $env:QT_AUTO_SCREEN_SCALE_FACTOR = $previousAuto }
        }
        Invoke-ActualUi $appExe $scale.Label $scale.Factor $scaleOutputs[$scale.Label]
        Write-Output "INSTALLED_ACTUAL_UI_SCALE_OK effective=$($scale.Label)% factor=$($scale.Factor)"
    }

    if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
        throw 'Uninstaller missing.'
    }
    if (Test-Path -LiteralPath $synthetic -PathType Leaf) {
        Remove-Item -LiteralPath $synthetic -Force
    }
    Stop-InstalledApp $appExe
    Invoke-ProcessWithTimeout $uninstaller @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') 'Hidden uninstall'
    Start-Sleep -Seconds 2
    if (Test-Path -LiteralPath $appExe) { throw 'Uninstall left the application executable.' }
    if ($uninstallKeys | Where-Object { Test-Path -LiteralPath $_ }) {
        throw 'Disposable uninstall key remains.'
    }
    if (Test-Path -LiteralPath $resolvedInstallRoot) {
        $residual = @(Get-ChildItem -Force -LiteralPath $resolvedInstallRoot)
        if ($residual.Count -ne 0) { throw 'Uninstall left files in the disposable install root.' }
        Remove-Item -LiteralPath $resolvedInstallRoot -Force
    }
    $uninstalled = $true
    Write-Output 'INSTALLED_ACTUAL_UI_OK'
}
finally {
    Stop-InstalledApp $appExe
    if (Test-Path -LiteralPath $synthetic -PathType Leaf) {
        Remove-Item -LiteralPath $synthetic -Force
    }
    if (($installed -or (Test-Path -LiteralPath $uninstaller -PathType Leaf)) -and
        -not $uninstalled -and (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
        try {
            Invoke-ProcessWithTimeout $uninstaller @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') `
                'Cleanup uninstall'
        }
        catch {
            Write-Warning "Cleanup uninstall failed: $($_.Exception.Message)"
        }
    }
    if (Test-Path -LiteralPath $resolvedInstallRoot) {
        $remaining = @(Get-ChildItem -Force -LiteralPath $resolvedInstallRoot)
        if ($remaining.Count -eq 0) {
            Remove-Item -LiteralPath $resolvedInstallRoot -Force
        }
    }
}
