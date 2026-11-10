param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonExe,
    [string]$EnvFile = '.env',
    [switch]$Offline
)
$ErrorActionPreference = 'Stop'
$qtRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
if (-not $PythonExe) { $PythonExe = Join-Path $qtRoot '.venv\Scripts\python.exe' }
$qtPreviousPythonPath = $env:PYTHONPATH
Push-Location -LiteralPath $qtRoot
try {
    $env:PYTHONPATH = Join-Path $qtRoot 'src'
    $qtArguments = @('-m', 'quant_research.cli', 'daily-ops')
    if ($Offline) { $qtArguments += '--offline' }
    else { $qtArguments += @('--env-file', $EnvFile) }
    & $PythonExe @qtArguments
    $qtExit = $LASTEXITCODE
}
finally {
    $env:PYTHONPATH = $qtPreviousPythonPath
    Pop-Location
}
exit $qtExit
