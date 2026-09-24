param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

# 1. Prefer uv with explicit project anchor
if (Get-Command uv -ErrorAction SilentlyContinue) {
    & uv run --project "$PSScriptRoot" agents @ScriptArgs
    if ($LASTEXITCODE -eq 0) { exit 0 }

    # Fallback to direct script execution via uv if console entrypoint had issues
    & uv run --project "$PSScriptRoot" python "$PSScriptRoot\agents.py" @ScriptArgs
    if ($LASTEXITCODE -eq 0) { exit 0 }
}

# 2. Fallback to system python with standalone script
if (Get-Command python -ErrorAction SilentlyContinue) {
    & python "$PSScriptRoot\agents.py" @ScriptArgs
    if ($LASTEXITCODE -eq 0) { exit 0 }
}

# 3. Fallback to pure native PowerShell (zero Python dependencies required)
& powershell -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\agents_native.ps1" @ScriptArgs
exit $LASTEXITCODE
