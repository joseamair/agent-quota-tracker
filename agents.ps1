param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

& uv run python "$PSScriptRoot\agents.py" @ScriptArgs
