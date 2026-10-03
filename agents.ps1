param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

# Normalize arguments for python CLI (e.g. -Prompt -> --prompt, -Status -> --status)
$pyArgs = @()
foreach ($arg in $ScriptArgs) {
    if ($arg -eq '-PromptFormat') {
        $pyArgs += '--prompt-format'
    } elseif ($arg -eq '-PokeWatch') {
        $pyArgs += '--poke-watch'
    } elseif ($arg -eq '-PokeAt') {
        $pyArgs += '--poke-at'
    } elseif ($arg -eq '-TestNotify') {
        $pyArgs += '--test-notify'
    } elseif ($arg -eq '-ScheduleInstall') {
        $pyArgs += '--schedule-install'
    } elseif ($arg -eq '-ScheduleStatus') {
        $pyArgs += '--schedule-status'
    } elseif ($arg -eq '-ScheduleRemove') {
        $pyArgs += '--schedule-remove'
    } elseif ($arg -eq '-RefreshInterval') {
        $pyArgs += '--refresh-interval'
    } elseif ($arg -eq '-TargetAgent') {
        $pyArgs += '--agent'
    } elseif ($arg -match '^-[A-Za-z]' -and -not $arg.StartsWith('--') -and $arg.Length -gt 2) {
        $pyArgs += ('--' + $arg.TrimStart('-').ToLower())
    } else {
        $pyArgs += $arg
    }
}

# 1. Prefer uv with explicit project anchor
if (Get-Command uv -ErrorAction SilentlyContinue) {
    & uv run --project "$PSScriptRoot" agents @pyArgs
    if ($LASTEXITCODE -eq 0) { exit 0 }

    # Fallback to direct script execution via uv if console entrypoint had issues
    & uv run --project "$PSScriptRoot" python "$PSScriptRoot\agents.py" @pyArgs
    if ($LASTEXITCODE -eq 0) { exit 0 }
}

# 2. Fallback to system python with standalone script
if (Get-Command python -ErrorAction SilentlyContinue) {
    & python "$PSScriptRoot\agents.py" @pyArgs
    if ($LASTEXITCODE -eq 0) { exit 0 }
}

# 3. Fallback to pure native PowerShell (zero Python dependencies required)
& powershell -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\agents_native.ps1" @ScriptArgs
exit $LASTEXITCODE
