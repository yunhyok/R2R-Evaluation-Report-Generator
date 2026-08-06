[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$ExecutablePath,
    [Parameter(Mandatory)][ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$MeasurementPath,
    [Parameter(Mandatory)][ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$PredictionPath,
    [Parameter(Mandatory)][string]$OutputPath,
    [ValidateRange(30, 300)][int]$TimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'
$executable = [IO.Path]::GetFullPath($ExecutablePath)
$measurement = [IO.Path]::GetFullPath($MeasurementPath)
$prediction = [IO.Path]::GetFullPath($PredictionPath)
$output = [IO.Path]::GetFullPath($OutputPath)
if ([IO.Path]::GetExtension($output) -ne '.xlsx') { throw 'OutputPath must end in .xlsx.' }
if (-not (Test-Path -LiteralPath (Split-Path -Parent $output) -PathType Container)) {
    throw 'OutputPath parent directory does not exist.'
}
if (Test-Path -LiteralPath $output) { throw "Refusing to overwrite UI verification output: $output" }

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

function Wait-ForValue {
    param([scriptblock]$Probe, [string]$Description)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $value = & $Probe
        if ($null -ne $value -and $value -ne $false) { return $value }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    throw "Timed out waiting for $Description."
}

function Find-ByName {
    param([System.Windows.Automation.AutomationElement]$Root, [string]$Name)
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::NameProperty,
        $Name
    )
    return $Root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
}

function Set-EditValue {
    param([System.Windows.Automation.AutomationElement]$Root, [string]$Name, [string]$Value)
    $element = Find-ByName $Root $Name
    if ($null -eq $element) { throw "UI edit not found: $Name" }
    $pattern = $element.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    $pattern.SetValue($Value)
}

function Invoke-Button {
    param([System.Windows.Automation.AutomationElement]$Root, [string]$Name)
    $element = Find-ByName $Root $Name
    if ($null -eq $element) { throw "UI button not found: $Name" }
    if (-not $element.Current.IsEnabled) { throw "UI button is disabled: $Name" }
    $pattern = $element.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
    $pattern.Invoke()
}

$parent = $null
$window = $null
$windowProcess = $null
try {
    $parent = Start-Process -FilePath $executable -PassThru
    $windowProcess = Wait-ForValue {
        Get-Process -Name 'R2REvaluationReportGenerator' -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -eq $executable -and $_.MainWindowHandle -ne 0 } |
            Select-Object -First 1
    } 'the application window'
    $window = [System.Windows.Automation.AutomationElement]::FromHandle(
        [IntPtr]$windowProcess.MainWindowHandle
    )
    Write-Output "UI_WINDOW_READY process=$($windowProcess.Id)"

    Set-EditValue $window '측정 CSV 또는 XLSX 파일' $measurement
    Set-EditValue $window '예측 CSV 또는 XLSX 파일' $prediction
    Set-EditValue $window '생성할 XLSX 파일 경로' $output
    Invoke-Button $window '사전 검사 실행'
    Write-Output 'UI_PREFLIGHT_INVOKED'

    Wait-ForValue {
        $button = Find-ByName $window '모든 제안 연결 명시적 확인'
        if ($null -ne $button -and $button.Current.IsEnabled) { return $button }
        return $null
    } 'the explicit confirm-all mapping control' | Out-Null
    Invoke-Button $window '모든 제안 연결 명시적 확인'
    Write-Output 'UI_MAPPING_CONFIRMATIONS confirmed=all'

    Wait-ForValue {
        $button = Find-ByName $window 'Excel 통합문서 생성'
        if ($null -ne $button -and $button.Current.IsEnabled) { return $button }
        return $null
    } 'the enabled Excel generation button' | Out-Null
    Invoke-Button $window 'Excel 통합문서 생성'
    Write-Output 'UI_GENERATION_INVOKED'

    Wait-ForValue {
        if (Test-Path -LiteralPath $output -PathType Leaf) {
            $file = Get-Item -LiteralPath $output
            if ($file.Length -gt 0) { return $file }
        }
        return $null
    } 'the generated real-data workbook' | Out-Null
    Wait-ForValue {
        $button = Find-ByName $window '생성된 통합문서 열기'
        if ($null -ne $button -and -not $button.Current.IsOffscreen) { return $button }
        return $null
    } 'the successful output controls' | Out-Null

    Write-Output "ACTUAL_UI_WORKFLOW_OK output=$output"
}
catch {
    if ($null -ne $windowProcess) {
        $processCondition = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ProcessIdProperty,
            $windowProcess.Id
        )
        $topWindows = [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
            [System.Windows.Automation.TreeScope]::Children,
            $processCondition
        )
        foreach ($topWindow in $topWindows) {
            Write-Warning "UI diagnostic window: $($topWindow.Current.Name)"
            $elements = $topWindow.FindAll(
                [System.Windows.Automation.TreeScope]::Descendants,
                [System.Windows.Automation.Condition]::TrueCondition
            )
            foreach ($element in $elements) {
                if ($element.Current.Name) {
                    Write-Warning (
                        "UI diagnostic element: " +
                        $element.Current.ControlType.ProgrammaticName + " | " +
                        $element.Current.Name
                    )
                }
            }
        }
    }
    throw
}
finally {
    if ($null -ne $window) {
        try {
            $pattern = $window.GetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern)
            $pattern.Close()
        }
        catch { Write-Warning "Graceful UI close failed: $($_.Exception.Message)" }
    }
    Start-Sleep -Milliseconds 500
    Get-Process -Name 'R2REvaluationReportGenerator' -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $executable } |
        Stop-Process -Force
}
