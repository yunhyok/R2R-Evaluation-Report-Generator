[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$python = if (Test-Path -LiteralPath $venvPython -PathType Leaf) { $venvPython } else { 'python' }
$packageVersion = (& $python -c "from r2r_evaluation_report import __version__; print(__version__)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $packageVersion) { throw 'Could not determine package version.' }

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Program $Arguments" }
}

if (-not $SkipTests) {
    Invoke-Checked $python @('-m', 'ruff', 'check', '.')
    Invoke-Checked $python @('-m', 'pytest')
    Invoke-Checked $python @('.\scripts\check_source_only.py')
    Invoke-Checked $python @('-m', 'r2r_evaluation_report', '--self-test')
}

$pyInstallerWork = Join-Path $env:LOCALAPPDATA 'R2REvaluationReportGenerator\PyInstallerWork'
New-Item -ItemType Directory -Path $pyInstallerWork -Force | Out-Null
Invoke-Checked $python @(
    '-m', 'PyInstaller', '--noconfirm', '--clean', '--workpath', $pyInstallerWork,
    '.\r2r_evaluation_report.spec'
)
$executable = Join-Path $projectRoot 'dist\R2REvaluationReportGenerator.exe'
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw 'PyInstaller did not produce the expected executable.'
}
Invoke-Checked $executable @('--self-test')
$previousQpaPlatform = $env:QT_QPA_PLATFORM
try {
    $env:QT_QPA_PLATFORM = 'offscreen'
    Invoke-Checked $executable @('--gui-smoke-test')
}
finally {
    if ($null -eq $previousQpaPlatform) {
        Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    }
    else {
        $env:QT_QPA_PLATFORM = $previousQpaPlatform
    }
}

if (-not $SkipInstaller) {
    $isccCandidates = @(
        (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1),
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Antigravity IDE\resources\app\node_modules\innosetup\bin\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe')
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
    if (-not $isccCandidates) { throw 'ISCC.exe was not found.' }
    $iss = '.\installer\r2r_evaluation_report_generator.iss'
    Invoke-Checked $isccCandidates @("/DAppVersion=$packageVersion", $iss)
    Invoke-Checked $isccCandidates @("/DAppVersion=$packageVersion", '/DDisposableValidation', $iss)
    $production = Join-Path $projectRoot "dist\installer\R2R-Evaluation-Report-Generator-$packageVersion-setup.exe"
    $disposable = Join-Path $projectRoot "dist\installer\disposable\R2R-Evaluation-Report-Generator-$packageVersion-disposable-setup.exe"
    if (-not (Test-Path -LiteralPath $production -PathType Leaf)) { throw 'Production installer missing.' }
    if (-not (Test-Path -LiteralPath $disposable -PathType Leaf)) { throw 'Disposable installer missing.' }
    $productionHash = (Get-FileHash -LiteralPath $production -Algorithm SHA256).Hash
    $hashManifest = "$production.sha256"
    "$productionHash  $(Split-Path -Leaf $production)" |
        Set-Content -LiteralPath $hashManifest -Encoding ascii
    Write-Output "Production installer SHA-256: $productionHash"
    Write-Output "SHA-256 manifest: $hashManifest"
}
