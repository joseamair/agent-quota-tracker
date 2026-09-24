param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

# 1. Prefer uv if installed
if (Get-Command uv -ErrorAction SilentlyContinue) {
    & uv run agents @ScriptArgs
    exit $LASTEXITCODE
}

# 2. Fallback to python with standalone script
if (Get-Command python -ErrorAction SilentlyContinue) {
    & python "$PSScriptRoot\agents.py" @ScriptArgs
    exit $LASTEXITCODE
}

# 3. Fallback to pure native PowerShell (zero Python dependencies)
& powershell -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\agents_native.ps1" @ScriptArgs
exit $LASTEXITCODE
