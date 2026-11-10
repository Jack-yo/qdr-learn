$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& .\.venv\Scripts\python.exe -m quant_research.cli maintain-data @args
exit $LASTEXITCODE
