param(
    [ValidateSet("test", "lint", "format", "typecheck", "all")]
    [string]$Action = "all"
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$uv = Join-Path $root ".venv\Scripts\uv.exe"

if (-not (Test-Path -LiteralPath $uv -PathType Leaf)) {
    throw "Expected project-local uv at $uv"
}

function Invoke-Uv {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    & $uv @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "uv $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

Push-Location $root
try {
    switch ($Action) {
        "test" { Invoke-Uv run --locked pytest -q }
        "lint" { Invoke-Uv run --locked ruff check src/ tests/ }
        "format" { Invoke-Uv run --locked ruff format src/ tests/ --check }
        "typecheck" {
            Invoke-Uv run --locked mypy src/quant_research/policy.py src/quant_research/contracts.py src/quant_research/clock.py
        }
        "all" {
            Invoke-Uv run --locked ruff check src/ tests/
            Invoke-Uv run --locked ruff format src/ tests/ --check
            Invoke-Uv run --locked pytest -q
        }
    }
}
finally {
    Pop-Location
}
