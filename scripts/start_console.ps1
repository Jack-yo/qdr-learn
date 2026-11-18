$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$qtEnvFile = Join-Path (Get-Location).Path '.env'
if (Test-Path -LiteralPath $qtEnvFile -PathType Leaf) {
    & .\.venv\Scripts\python.exe -m quant_research.web --env-file $qtEnvFile @args
} else {
    & .\.venv\Scripts\python.exe -m quant_research.web @args
}
