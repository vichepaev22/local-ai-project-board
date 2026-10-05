[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSCommandPath
$Py = Get-Command py -ErrorAction SilentlyContinue
if ($Py) {
    & $Py.Source -3 (Join-Path $Root 'run.py') @Arguments
    exit $LASTEXITCODE
}

$Python = Get-Command python -ErrorAction SilentlyContinue
if ($Python) {
    & $Python.Source (Join-Path $Root 'run.py') @Arguments
    exit $LASTEXITCODE
}

Write-Error 'Python 3.11 or newer was not found. Install Python, then run this launcher again.'
exit 1
