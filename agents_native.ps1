<#
.SYNOPSIS
  Pure PowerShell implementation to track and poke 5-hour rate limit windows across Claude (CCS), Codex, and AGY.

.EXAMPLE
  .\agents_native.ps1 -Status
  .\agents_native.ps1 -Poke
  .\agents_native.ps1 -Dashboard
#>

param(
    [Alias("s")]
    [switch]$Status,

    [Alias("j")]
    [switch]$Json,

    [Alias("w")]
    [int]$Watch = 0,

    [Alias("p")]
    [switch]$Poke,

    [Alias("pw")]
    [switch]$PokeWatch,

    [Alias("pa")]
    [string]$PokeAt,

    [Alias("ap")]
    [switch]$Auto,

    [switch]$AutoPoke,

    [Alias("i")]
    [string]$Interval,

    [Alias("f")]
    [switch]$Force,

    [Alias("a", "agent")]
    [string]$TargetAgent,

    [Alias("d")]
    [switch]$Dashboard,

    [Alias("n")]
    [switch]$Notify,

    [switch]$TestNotify,

    [switch]$Prompt,

    [string]$PromptFormat,

    [switch]$Refresh,

    [string]$ScheduleInstall,

    [switch]$ScheduleStatus,

    [switch]$ScheduleRemove,

    [string]$Frequency = "daily",

    [switch]$Once,

    [Alias("insights")]
    [switch]$Analytics,

    [int]$Days = 7,

    [Alias("backfill-history")]
    [switch]$Backfill,

    [Alias("h", "?")]
    [switch]$Help
)

if ($Help) {
    Write-Host @"

⚡ AI Agents 5-Hour Window Tracker & Dashboard (PowerShell Native)

Monitor rolling rate limit windows, track weekly resets, and poke AI accounts non-interactively.

USAGE:
  .\agents_native.ps1 [-Status] [-Poke] [-Auto] [-PokeWatch] [-PokeAt <HH:MM>] [-Interval <dur>] [-Prompt] [-PromptFormat <fmt>] [-ScheduleInstall <HH:MM>] [-ScheduleStatus] [-ScheduleRemove] [-Analytics] [-Days <N>] [-Force] [-TargetAgent <id>] [-Dashboard] [-Help]

OPTIONS:
  -Status, -s            Display live 5-hour rolling threshold window state, time remaining,
                         next reset time, 5h % usage, and weekly quota reset date.
  -Auto, -auto           Start continuous autonomous auto-checker loop: checks status, waits for
                         earliest window reset, primes, and repeats until stopped.
  -AutoPoke              Alias for -Auto.
  -Analytics, -insights  Display quota consumption velocity, peak hours, and optimal priming analytics.
  -Days <int>            Number of days to analyze for analytics (default: 7).
  -Backfill              Backfill past poke history from legacy logs into SQLite database.
  -Json, -j              Output raw machine-readable JSON status for all accounts.
  -Watch, -w [seconds]   Continuously refresh the status table every N seconds (default: 15s).
  -Poke, -p              Trigger a prompt on inactive accounts to start the 5h window.
                         Active accounts are automatically skipped to conserve quota.
  -PokeWatch, -pw        Start autonomous watchdog mode: continuously monitors and pokes idle agents.
  -PokeAt, -pa <HH:MM>   Schedule an automated poke at a specific target time (e.g. 07:30 or 08:00).
  -Interval, -i <dur>    Polling interval for -PokeWatch (e.g. 30m, 2h, or auto for adaptive sleep).
  -Force, -f             When used with -Poke, forces a prompt even if window is already active.
  -TargetAgent, -a <id>  Target a specific agent (e.g. work, personal, work2, codex, agy).
  -Notify, -n            Send native OS desktop notifications on poke events and scheduled completions.
  -TestNotify            Send a test desktop notification to verify OS notification settings and exit.
  -Prompt                Output an ultra-fast (<15ms) cached status segment for custom shell prompts.
  -PromptFormat <str>    Format template or preset ('default', 'compact', 'minimal', 'tmux', 'json').
  -Refresh               Force refresh live status from provider APIs for prompt segment.
  -ScheduleInstall <time>Install an OS-level background scheduled task to prime quotas daily (default: 07:30).
  -ScheduleStatus        Display status of the OS-level background scheduled morning priming task.
  -ScheduleRemove        Uninstall and remove the OS-level background scheduled morning priming task.
  -Dashboard, -d         Launch the local web dashboard at http://localhost:5050.
  -Help, -h, -?          Show this help message and exit.

EXAMPLES:
  .\agents_native.ps1 -Status
  .\agents_native.ps1 -Analytics
  .\agents_native.ps1 -Prompt
  .\agents_native.ps1 -PromptFormat compact
  .\agents_native.ps1 -PromptFormat "Agents: {active}/{total}"
  .\agents_native.ps1 -ScheduleInstall 07:30 -Notify
  .\agents_native.ps1 -ScheduleStatus
  .\agents_native.ps1 -ScheduleRemove
  .\agents_native.ps1 -Poke -Notify
  .\agents_native.ps1 -PokeWatch -Interval 30m -Notify
  .\agents_native.ps1 -PokeAt 07:30 -Notify
  .\agents_native.ps1 -TestNotify
  .\agents_native.ps1 -Poke -Force -TargetAgent work
  .\agents_native.ps1 -Dashboard

"@ -ForegroundColor Cyan
    exit 0
}

# Default to Status if no action switch passed
if (-not $Status -and -not $Poke -and -not $Auto -and -not $AutoPoke -and -not $PokeWatch -and -not $PokeAt -and -not $Dashboard -and -not $Json -and -not $TestNotify -and -not $Prompt -and -not $PromptFormat -and -not $ScheduleInstall -and -not $ScheduleStatus -and -not $ScheduleRemove -and $Watch -eq 0 -and -not $PSBoundParameters.ContainsKey('Watch')) {
    $Status = $true
}

$nowUtc = [DateTime]::UtcNow

function Get-AgentCachePath {
    $p1 = Join-Path $HOME ".agent_quota_tracker\cache.json"
    $p2 = Join-Path $HOME ".agents_dashboard\cache.json"
    if (Test-Path $p1) { return $p1 }
    if (Test-Path $p2) { return $p2 }
    $dir = Join-Path $HOME ".agent_quota_tracker"
    if (-not (Test-Path $dir)) { $null = New-Item -ItemType Directory -Path $dir -Force }
    return $p1
}

function Save-AgentCache($dataList) {
    try {
        $path = Get-AgentCachePath
        $activeCount = 0
        $accounts = @()
        $now = [DateTimeOffset]::UtcNow
        $nowTs = [double]$now.ToUnixTimeSeconds()

        foreach ($a in $dataList) {
            if (-not $a -or -not $a.Name) { continue }
            if ($a.IsActive) { $activeCount++ }

            $resetsAtTs = $null
            if ($a.RemainingSeconds -gt 0) {
                $resetsAtTs = $nowTs + $a.RemainingSeconds
            }

            $accounts += [ordered]@{
                id = $a.Id
                name = $a.Name
                provider = $a.Provider
                is_active = [bool]$a.IsActive
                used_percent = $a.UsagePct
                resets_at = $a.NextReset
                resets_at_timestamp = $resetsAtTs
                time_remaining_seconds = $a.RemainingSeconds
                time_remaining_str = $a.Remaining
                weekly_used_percent = $a.WkUsage
                weekly_reset_str = $a.WeeklyReset
            }
        }

        $payload = [ordered]@{
            updated_at = (Get-Date).ToString("o")
            updated_at_timestamp = $nowTs
            active_count = $activeCount
            total_count = $accounts.Count
            accounts = $accounts
        }
        $json = $payload | ConvertTo-Json -Depth 5
        $json | Set-Content -Path $path -Encoding UTF8
    } catch {}
}

function Format-AgentDurationShort($seconds) {
    if ($seconds -le 0) { return "0m" }
    $hours = [math]::Floor($seconds / 3600)
    $remainder = $seconds % 3600
    $mins = [math]::Round($remainder / 60)
    if ($hours -gt 0) {
        if ($mins -gt 0) { return ("{0}h{1:D2}m" -f $hours, [int]$mins) }
        return "${hours}h"
    }
    $m = [math]::Max(1, [int]$mins)
    return "${m}m"
}

function Get-AgentPrompt([string]$Format = "default", [switch]$ForceRefresh) {
    $cachePath = Get-AgentCachePath
    $cache = $null

    if (-not $ForceRefresh -and (Test-Path $cachePath)) {
        try {
            $raw = Get-Content -Path $cachePath -Raw -Encoding UTF8
            $cache = $raw | ConvertFrom-Json
        } catch {}
    }

    if ($ForceRefresh -or $null -eq $cache -or -not $cache.accounts) {
        $freshData = Get-AgentData
        Save-AgentCache $freshData
        if (Test-Path $cachePath) {
            try {
                $raw = Get-Content -Path $cachePath -Raw -Encoding UTF8
                $cache = $raw | ConvertFrom-Json
            } catch {}
        }
    }

    if ($null -eq $cache -or -not $cache.accounts) {
        return "[🤖 No Quota Data]"
    }

    $now = [DateTimeOffset]::UtcNow
    $nowTs = [double]$now.ToUnixTimeSeconds()

    $activeAccounts = @()
    foreach ($acc in $cache.accounts) {
        if (-not $acc.is_active) { continue }
        $remaining = 0
        if ($null -ne $acc.resets_at_timestamp) {
            $remaining = [double]$acc.resets_at_timestamp - $nowTs
        } elseif ($null -ne $acc.time_remaining_seconds) {
            $remaining = [double]$acc.time_remaining_seconds
        }

        if ($remaining -gt 0) {
            $activeAccounts += [PSCustomObject]@{
                Account = $acc
                RemainingSeconds = [int]$remaining
            }
        }
    }

    $activeCount = $activeAccounts.Count
    $totalCount = $cache.accounts.Count

    if ($activeCount -gt 0) {
        $minSecs = ($activeAccounts | Measure-Object -Property RemainingSeconds -Minimum).Minimum
        $maxSecs = ($activeAccounts | Measure-Object -Property RemainingSeconds -Maximum).Maximum
        $minRemaining = Format-AgentDurationShort $minSecs
        $maxRemaining = Format-AgentDurationShort $maxSecs
        $statusStr = "Active"
        $iconStr = "⚡"
    } else {
        $minSecs = 0
        $maxSecs = 0
        $minRemaining = "Idle"
        $maxRemaining = "Idle"
        $statusStr = "Idle"
        $iconStr = "○"
    }

    $pct = if ($totalCount -gt 0) { [math]::Round(($activeCount / $totalCount) * 100) } else { 0 }
    $percentStr = "${pct}%"

    $fmt = if ([string]::IsNullOrWhiteSpace($Format)) { "default" } else { $Format.Trim() }

    switch ($fmt.ToLower()) {
        "default" {
            if ($activeCount -gt 0) {
                return "[$iconStr $activeCount/$totalCount Active • $minRemaining]"
            }
            return "[$iconStr 0/$totalCount Active • Idle]"
        }
        "compact" {
            if ($activeCount -gt 0) {
                return "$iconStr$activeCount/$totalCount $minRemaining"
            }
            return "$iconStr 0/$totalCount"
        }
        "minimal" {
            return "🤖 $activeCount/$totalCount"
        }
        "tmux" {
            if ($activeCount -gt 0) {
                return "#[fg=yellow]⚡#[default] $activeCount/$totalCount ($minRemaining)"
            }
            return "#[fg=brightblack]○#[default] 0/$totalCount"
        }
        "json" {
            return ([ordered]@{
                active = $activeCount
                total = $totalCount
                min_remaining = $minRemaining
                min_remaining_seconds = $minSecs
                max_remaining = $maxRemaining
                max_remaining_seconds = $maxSecs
                status = $statusStr
                icon = $iconStr
                percent = $percentStr
                updated_at = $cache.updated_at
            } | ConvertTo-Json -Compress)
        }
        default {
            $res = $fmt
            $res = $res.Replace("{active}", "$activeCount")
            $res = $res.Replace("{total}", "$totalCount")
            $res = $res.Replace("{min_remaining}", "$minRemaining")
            $res = $res.Replace("{min_remaining_seconds}", "$minSecs")
            $res = $res.Replace("{max_remaining}", "$maxRemaining")
            $res = $res.Replace("{max_remaining_seconds}", "$maxSecs")
            $res = $res.Replace("{status}", "$statusStr")
            $res = $res.Replace("{icon}", "$iconStr")
            $res = $res.Replace("{percent}", "$percentStr")
            return $res
        }
    }
}

function Extract-ReplySnippet([string]$rawText) {
    if (-not $rawText) { return "" }
    $rawText = $rawText.Replace([char]0x2018, "'").Replace([char]0x2019, "'").Replace([char]0x201C, '"').Replace([char]0x201D, '"')
    $lines = $rawText -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
    $cleaned = @()
    foreach ($l in $lines) {
        $low = $l.ToLower()
        if ($l -like "Warning:*" -or
            $l -like "Last progress:*" -or
            $l -like "Thinking Process:*" -or
            $l -like "Reading additional input*" -or
            $l -like "OpenAI Codex*" -or
            $l -like "--------*" -or
            $low -like "workdir:*" -or
            $low -like "model:*" -or
            $low -like "provider:*" -or
            $low -like "approval:*" -or
            $low -like "sandbox:*" -or
            $low -like "reasoning effort:*" -or
            $low -like "reasoning summaries:*" -or
            $low -like "session id:*" -or
            $low -like "tokens used*" -or
            $low -like "user *" -or
            $low -like "codex *") {
            continue
        }
        $cleaned += $l
    }
    if ($cleaned.Count -eq 0) {
        return if ($lines.Count -gt 0) { $lines[0] } else { "" }
    }
    $first = $cleaned[0]
    if ($first.Length -gt 120) {
        return $first.Substring(0, 117) + "..."
    }
    return $first
}

function Format-Remaining([TimeSpan]$span) {
    if ($span.TotalSeconds -le 0) { return "0s" }
    $parts = @()
    if ($span.Hours -gt 0) { $parts += "$($span.Hours)h" }
    if ($span.Minutes -gt 0) { $parts += "$($span.Minutes)m" }
    if ($span.Seconds -gt 0 -or $parts.Count -eq 0) { $parts += "$($span.Seconds)s" }
    return ($parts -join " ")
}

function Format-WeeklyReset([string]$resetsStr) {
    if (-not $resetsStr) { return "-" }
    try {
        $dtUtc = [DateTime]::Parse($resetsStr).ToUniversalTime()
        $span = $dtUtc - [DateTime]::UtcNow
        if ($span.TotalSeconds -le 0) { return "Reset due" }
        $hrs = [Math]::Round($span.TotalHours, 1)
        $dateStr = $dtUtc.ToLocalTime().ToString("ddd MMM dd, HH:mm")
        return "in ${hrs}h ($dateStr)"
    } catch {
        return "-"
    }
}

function Get-AccountsConfig {
    $candidates = @(
        (Join-Path (Get-Location) "agents.config.json"),
        (Join-Path $PSScriptRoot "agents.config.json"),
        (Join-Path $HOME ".agents_dashboard\config.json")
    )
    foreach ($cand in $candidates) {
        if (Test-Path $cand) {
            try {
                $raw = Get-Content $cand -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($raw.accounts) {
                    return ($raw.accounts | Where-Object { $null -eq $_.enabled -or $_.enabled -eq $true })
                }
            } catch {}
        }
    }
    return @(
        [PSCustomObject]@{ id="agy"; provider="agy"; name="Google Antigravity (AGY)"; category="personal" },
        [PSCustomObject]@{ id="codex"; provider="codex"; name="OpenAI Codex"; category="personal" },
        [PSCustomObject]@{ id="personal"; provider="claude"; profile="personal"; name="Claude (Personal)"; category="personal" },
        [PSCustomObject]@{ id="work"; provider="claude"; profile="work"; name="Claude (Work)"; category="work" },
        [PSCustomObject]@{ id="work2"; provider="claude"; profile="work2"; name="Claude (Work2)"; category="work" }
    )
}

function Get-AgentData {
    $accounts = Get-AccountsConfig
    $results = @()
    $nowUtc = [DateTime]::UtcNow

    foreach ($acc in $accounts) {
        $prov = "$($acc.provider)".ToLower()
        $aid = "$($acc.id)"
        $name = if ($acc.name) { $acc.name } else { $aid }

        if ($prov -eq "agy") {
            $isActiveAgy = $false
            $remStrAgy = "Inactive"
            $resetLocalAgy = "Ready to Poke"
            $usedAgy = 0.0
            $wkUsedAgy = "-"
            $wkResetAgy = "-"

            try {
                $rawAgyJson = & agy -p "/usage" --output-format json 2>$null
                if ($rawAgyJson) {
                    $agyData = $rawAgyJson | ConvertFrom-Json
                    $groups = $agyData.command.data.groups
                    $geminiGroup = $groups | Where-Object { $_.name -like "*Gemini*" } | Select-Object -First 1
                    if (-not $geminiGroup -and $groups.Count -gt 0) { $geminiGroup = $groups[0] }

                    if ($geminiGroup) {
                        $b5h = $geminiGroup.buckets | Where-Object { $_.window -eq "5h" -or $_.id -like "*5h*" } | Select-Object -First 1
                        $bWk = $geminiGroup.buckets | Where-Object { $_.window -eq "weekly" -or $_.id -like "*weekly*" } | Select-Object -First 1

                        if ($b5h) {
                            $rUtc5h = [DateTime]::Parse("$($b5h.reset_time)").ToUniversalTime()
                            $span5h = $rUtc5h - [DateTime]::UtcNow
                            $usedAgy = [Math]::Round((1.0 - [double]$b5h.remaining_fraction) * 100, 1)

                            $hasFreshPoke = $false
                            $statePath = Join-Path $HOME ".agents_dashboard\state.json"
                            if (Test-Path $statePath) {
                                try {
                                    $st = Get-Content $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
                                    $pStr = $st.agy.last_poked_at
                                    if ($pStr) {
                                        $pUtc = [DateTime]::Parse($pStr).ToUniversalTime()
                                        $diffSec = ($nowUtc - $pUtc).TotalSeconds
                                        if ($diffSec -ge 0 -and $diffSec -lt 600) { $hasFreshPoke = $true }
                                    }
                                } catch {}
                            }
                            $isSlidingIdleAgy = ($usedAgy -eq 0.0 -and -not $hasFreshPoke -and $span5h.TotalSeconds -ge 17955)

                            if ($span5h.TotalSeconds -gt 0 -and -not $isSlidingIdleAgy) {
                                $isActiveAgy = $true
                                $remStrAgy = Format-Remaining $span5h
                                $resetLocalAgy = $rUtc5h.ToLocalTime().ToString("HH:mm:ss") + " (Today)"
                            } else {
                                $usedAgy = 0.0
                                $remStrAgy = "Inactive"
                                $resetLocalAgy = "Ready to Poke"
                            }
                        }

                        if ($bWk) {
                            $wkUsedAgy = "$([Math]::Round((1.0 - [double]$bWk.remaining_fraction) * 100, 1))%"
                            $wkResetAgy = Format-WeeklyReset "$($bWk.reset_time)"
                        }
                    }
                }
            } catch {}

            # Fallback to history.jsonl if live query failed
            if (-not $isActiveAgy -and $usedAgy -eq 0.0 -and $wkUsedAgy -eq "-") {
                $agyHist = Join-Path $HOME ".gemini\antigravity-cli\history.jsonl"
                $latestAgyUtc = $null
                if (Test-Path $agyHist) {
                    $tail = Get-Content $agyHist -Tail 30 -ErrorAction SilentlyContinue
                    for ($i = $tail.Count - 1; $i -ge 0; $i--) {
                        try {
                            $obj = $tail[$i] | ConvertFrom-Json
                            if ($obj.timestamp) {
                                $latestAgyUtc = [DateTimeOffset]::FromUnixTimeMilliseconds([long]$obj.timestamp).UtcDateTime
                                break
                            }
                        } catch {}
                    }
                }

                if ($latestAgyUtc) {
                    $diff = $nowUtc - $latestAgyUtc
                    if ($diff.TotalHours -lt 5.0) {
                        $isActiveAgy = $true
                        $agyResetUtc = $latestAgyUtc.AddHours(5)
                        $remSpanAgy = $agyResetUtc - $nowUtc
                        $remStrAgy = Format-Remaining $remSpanAgy
                        $resetLocalAgy = $agyResetUtc.ToLocalTime().ToString("HH:mm:ss") + " (Today)"
                        $usedAgy = [Math]::Round(($diff.TotalSeconds / 18000.0) * 100, 1)
                    }
                }
            }

            $results += [PSCustomObject]@{
                Id               = "agy"
                Name             = $name
                Provider         = "AGY"
                IsActive         = $isActiveAgy
                State            = if ($isActiveAgy) { "● ACTIVE" } else { "○ INACTIVE" }
                Remaining        = $remStrAgy
                RemainingSeconds = if ($isActiveAgy -and $remSpanAgy) { [int]$remSpanAgy.TotalSeconds } else { 0 }
                NextReset        = $resetLocalAgy
                UsagePct         = "$usedAgy%"
                WkUsage          = $wkUsedAgy
                WeeklyReset      = $wkResetAgy
            }
        }
        elseif ($prov -eq "codex") {
            try {
                $rawCodexJson = & uv run python -c "from agents import get_codex_status; import json; print(json.dumps(get_codex_status().to_dict()))" 2>$null
                $cObj = $rawCodexJson | ConvertFrom-Json
                $isActiveCodex = [bool]$cObj.is_active
                $usedCodex = [double]$cObj.used_percent
                $remStrCodex = if ($cObj.time_remaining_str) { $cObj.time_remaining_str } else { "Inactive" }
                $remSecsCodex = if ($cObj.time_remaining_seconds) { [int]$cObj.time_remaining_seconds } else { 0 }
                $resetLocalCodex = "Ready to Poke"
                if ($cObj.resets_at) {
                    $rUtc = [DateTime]::Parse($cObj.resets_at).ToUniversalTime()
                    $resetLocalCodex = $rUtc.ToLocalTime().ToString("HH:mm:ss") + " (Today)"
                }
                $wkUsedCodex = if ($null -ne $cObj.weekly_used_percent) { "$($cObj.weekly_used_percent)%" } else { "-" }
                $wkResetCodex = if ($cObj.weekly_reset_str) { $cObj.weekly_reset_str } else { "-" }

                $results += [PSCustomObject]@{
                    Id               = "codex"
                    Name             = $name
                    Provider         = "Codex"
                    IsActive         = $isActiveCodex
                    State            = if ($isActiveCodex) { "● ACTIVE" } else { "○ INACTIVE" }
                    Remaining        = $remStrCodex
                    RemainingSeconds = $remSecsCodex
                    NextReset        = $resetLocalCodex
                    UsagePct         = "$([Math]::Round($usedCodex, 1))%"
                    WkUsage          = $wkUsedCodex
                    WeeklyReset      = $wkResetCodex
                }
            } catch {
                $results += [PSCustomObject]@{
                    Id = "codex"; Name = $name; Provider = "Codex"; IsActive = $false; State = "○ INACTIVE"; Remaining = "Inactive"; RemainingSeconds = 0; NextReset = "Ready to Poke"; UsagePct = "0.0%"; WkUsage = "-"; WeeklyReset = "-"
                }
            }
        }
        elseif ($prov -eq "claude") {
            $prof = if ($acc.profile) { $acc.profile } else { $aid }
            $jsonPath = Join-Path $HOME ".ccs\instances\$prof\.claude.json"
            $credsPath = Join-Path $HOME ".ccs\instances\$prof\.credentials.json"

            # Fallback to standard Claude CLI installation if CCS path does not exist
            if (-not (Test-Path $credsPath)) {
                $stdCreds1 = Join-Path $HOME ".claude\.credentials.json"
                $stdCreds2 = Join-Path $HOME ".credentials.json"
                if (Test-Path $stdCreds1) { $credsPath = $stdCreds1 }
                elseif (Test-Path $stdCreds2) { $credsPath = $stdCreds2 }
            }
            if (-not (Test-Path $jsonPath)) {
                $stdJson = Join-Path $HOME ".claude.json"
                if (Test-Path $stdJson) { $jsonPath = $stdJson }
            }
            try {
                $fiveHour = $null
                $sevenDay = $null

                if (Test-Path $credsPath) {
                    try {
                        $creds = Get-Content $credsPath -Raw -Encoding UTF8 | ConvertFrom-Json
                        $tok = $creds.claudeAiOauth.accessToken
                        if ($tok) {
                            $headers = @{ "Authorization" = "Bearer $tok"; "User-Agent" = "claude-code/2.1.281" }
                            $liveResp = Invoke-RestMethod -Uri "https://api.anthropic.com/api/oauth/usage" -Headers $headers -TimeoutSec 3 -ErrorAction Stop
                            if ($liveResp) {
                                $fiveHour = $liveResp.five_hour
                                $sevenDay = $liveResp.seven_day
                            }
                        }
                    } catch {}
                }

                if (-not $fiveHour -and (Test-Path $jsonPath)) {
                    $raw = Get-Content $jsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
                    $fiveHour = $raw.cachedUsageUtilization.utilization.five_hour
                    $sevenDay = $raw.cachedUsageUtilization.utilization.seven_day
                }

                if ($fiveHour) {
                    $used = if ($null -ne $fiveHour.utilization) { [double]$fiveHour.utilization } else { 0.0 }
                    $resetsStr = $fiveHour.resets_at
                    $isActive = $false
                    $remainingStr = "Inactive"
                    $resetLocal = "Ready to Poke"

                    $hasFreshPoke = $false
                    $statePath = Join-Path $HOME ".agents_dashboard\state.json"
                    if (Test-Path $statePath) {
                        try {
                            $st = Get-Content $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
                            $pStr = $st."claude-$prof".last_poked_at
                            if ($pStr) {
                                $pUtc = [DateTime]::Parse($pStr).ToUniversalTime()
                                $diffSec = ($nowUtc - $pUtc).TotalSeconds
                                if ($diffSec -ge 0 -and $diffSec -lt 600) { $hasFreshPoke = $true }
                            }
                        } catch {}
                    }
                    $remSpan = if ($resetsStr) { [DateTime]::Parse($resetsStr).ToUniversalTime() - $nowUtc } else { $null }
                    $remSecs = if ($remSpan) { $remSpan.TotalSeconds } else { 0 }
                    $isSlidingIdle = ($used -eq 0.0 -and -not $hasFreshPoke -and $remSecs -ge 17955)

                    if ($resetsStr) {
                        $resetsUtc = [DateTime]::Parse($resetsStr).ToUniversalTime()
                        if ($resetsUtc -gt $nowUtc -and -not $isSlidingIdle) {
                            $isActive = $true
                            $remainingStr = Format-Remaining $remSpan
                            $resetLocal = $resetsUtc.ToLocalTime().ToString("HH:mm:ss") + " (Today)"
                        } else {
                            $used = 0.0
                            $remainingStr = "Inactive"
                            $resetLocal = "Ready to Poke"
                        }
                    }

                    $wkUsed = if ($null -ne $sevenDay.utilization) { "$([Math]::Round([double]$sevenDay.utilization, 1))%" } else { "-" }
                    $wkReset = Format-WeeklyReset $sevenDay.resets_at

                    $results += [PSCustomObject]@{
                        Id               = "claude-$prof"
                        Name             = $name
                        Provider         = "Claude"
                        IsActive         = $isActive
                        State            = if ($isActive) { "● ACTIVE" } else { "○ INACTIVE" }
                        Remaining        = $remainingStr
                        RemainingSeconds = if ($isActive -and $remSpan) { [int]$remSpan.TotalSeconds } else { 0 }
                        NextReset        = $resetLocal
                        UsagePct         = "$([Math]::Round($used, 1))%"
                        WkUsage          = $wkUsed
                        WeeklyReset      = $wkReset
                    }
                } else {
                    $results += [PSCustomObject]@{
                        Id = "claude-$prof"; Name = $name; Provider = "Claude"; IsActive = $false; State = "○ INACTIVE"; Remaining = "Inactive"; RemainingSeconds = 0; NextReset = "Ready to Poke"; UsagePct = "0.0%"; WkUsage = "-"; WeeklyReset = "-"
                    }
                }
            } catch {
                $results += [PSCustomObject]@{
                    Id = "claude-$prof"; Name = $name; Provider = "Claude"; IsActive = $false; State = "ERROR"; Remaining = "-"; RemainingSeconds = 0; NextReset = "-"; UsagePct = "-"; WkUsage = "-"; WeeklyReset = "-"
                }
            }
        }
        elseif ($prov -eq "cursor") {
            try {
                $rawJson = & uv run --no-sync python -c "from agents import get_cursor_status; import json; print(json.dumps(get_cursor_status('$name', '$($acc.category)').to_dict()))" 2>$null
                if ($rawJson) {
                    $obj = $rawJson | ConvertFrom-Json
                    $isAct = [bool]$obj.is_active
                    $used = [double]$obj.used_percent
                    $state = if ($isAct) { "● ACTIVE" } else { "○ INACTIVE" }
                    $results += [PSCustomObject]@{
                        Id = $aid; Name = $name; Provider = "Cursor"; IsActive = $isAct; State = $state; Remaining = if ($isAct) { "Active" } else { "Idle" }; RemainingSeconds = 0; NextReset = if ($obj.weekly_resets_at) { "$($obj.weekly_resets_at)" } else { "Monthly" }; UsagePct = "$used%"; WkUsage = if ($obj.weekly_used_percent -ne $null) { "$($obj.weekly_used_percent)%" } else { "-" }; WeeklyReset = if ($obj.weekly_reset_str) { "$($obj.weekly_reset_str)" } else { "-" }
                    }
                } else {
                    $results += [PSCustomObject]@{
                        Id = $aid; Name = $name; Provider = "Cursor"; IsActive = $false; State = "○ INACTIVE"; Remaining = "Unconfigured"; RemainingSeconds = 0; NextReset = "-"; UsagePct = "0.0%"; WkUsage = "-"; WeeklyReset = "-"
                    }
                }
            } catch {
                $results += [PSCustomObject]@{
                    Id = $aid; Name = $name; Provider = "Cursor"; IsActive = $false; State = "ERROR"; Remaining = "-"; RemainingSeconds = 0; NextReset = "-"; UsagePct = "-"; WkUsage = "-"; WeeklyReset = "-"
                }
            }
        }
        elseif ($prov -in @("windsurf", "codeium")) {
            try {
                $rawJson = & uv run --no-sync python -c "from agents import get_windsurf_status; import json; print(json.dumps(get_windsurf_status('$name', '$($acc.category)').to_dict()))" 2>$null
                if ($rawJson) {
                    $obj = $rawJson | ConvertFrom-Json
                    $isAct = [bool]$obj.is_active
                    $used = [double]$obj.used_percent
                    $state = if ($isAct) { "● ACTIVE" } else { "○ INACTIVE" }
                    $results += [PSCustomObject]@{
                        Id = $aid; Name = $name; Provider = "Windsurf"; IsActive = $isAct; State = $state; Remaining = if ($isAct) { "Active" } else { "Idle" }; RemainingSeconds = 0; NextReset = "-"; UsagePct = "$used%"; WkUsage = if ($obj.weekly_used_percent -ne $null) { "$($obj.weekly_used_percent)%" } else { "-" }; WeeklyReset = "-"
                    }
                } else {
                    $results += [PSCustomObject]@{
                        Id = $aid; Name = $name; Provider = "Windsurf"; IsActive = $false; State = "○ INACTIVE"; Remaining = "Unconfigured"; RemainingSeconds = 0; NextReset = "-"; UsagePct = "0.0%"; WkUsage = "-"; WeeklyReset = "-"
                    }
                }
            } catch {
                $results += [PSCustomObject]@{
                    Id = $aid; Name = $name; Provider = "Windsurf"; IsActive = $false; State = "ERROR"; Remaining = "-"; RemainingSeconds = 0; NextReset = "-"; UsagePct = "-"; WkUsage = "-"; WeeklyReset = "-"
                }
            }
        }
        elseif ($prov -in @("copilot", "github-copilot", "github_copilot")) {
            try {
                $rawJson = & uv run --no-sync python -c "from agents import get_copilot_status; import json; print(json.dumps(get_copilot_status('$name', '$($acc.category)').to_dict()))" 2>$null
                if ($rawJson) {
                    $obj = $rawJson | ConvertFrom-Json
                    $isAct = [bool]$obj.is_active
                    $used = [double]$obj.used_percent
                    $state = if ($isAct) { "● ACTIVE" } else { "○ INACTIVE" }
                    $results += [PSCustomObject]@{
                        Id = $aid; Name = $name; Provider = "Copilot"; IsActive = $isAct; State = $state; Remaining = if ($obj.time_remaining_str) { "$($obj.time_remaining_str)" } else { "Active" }; RemainingSeconds = [int]$obj.time_remaining_seconds; NextReset = if ($obj.resets_at) { "$($obj.resets_at)" } else { "-" }; UsagePct = "$used%"; WkUsage = "-"; WeeklyReset = "-"
                    }
                } else {
                    $results += [PSCustomObject]@{
                        Id = $aid; Name = $name; Provider = "Copilot"; IsActive = $false; State = "○ INACTIVE"; Remaining = "Unconfigured"; RemainingSeconds = 0; NextReset = "-"; UsagePct = "0.0%"; WkUsage = "-"; WeeklyReset = "-"
                    }
                }
            } catch {
                $results += [PSCustomObject]@{
                    Id = $aid; Name = $name; Provider = "Copilot"; IsActive = $false; State = "ERROR"; Remaining = "-"; RemainingSeconds = 0; NextReset = "-"; UsagePct = "-"; WkUsage = "-"; WeeklyReset = "-"
                }
            }
        }
        elseif ($prov -in @("aider", "openrouter")) {
            try {
                $rawJson = & uv run --no-sync python -c "from agents import get_aider_status; import json; print(json.dumps(get_aider_status('$name', '$($acc.category)').to_dict()))" 2>$null
                if ($rawJson) {
                    $obj = $rawJson | ConvertFrom-Json
                    $isAct = [bool]$obj.is_active
                    $used = [double]$obj.used_percent
                    $state = if ($isAct) { "● ACTIVE" } else { "○ INACTIVE" }
                    $results += [PSCustomObject]@{
                        Id = $aid; Name = $name; Provider = "Aider"; IsActive = $isAct; State = $state; Remaining = if ($isAct) { "Active" } else { "Idle" }; RemainingSeconds = 0; NextReset = "-"; UsagePct = "$used%"; WkUsage = if ($obj.weekly_used_percent -ne $null) { "$($obj.weekly_used_percent)%" } else { "-" }; WeeklyReset = "-"
                    }
                } else {
                    $results += [PSCustomObject]@{
                        Id = $aid; Name = $name; Provider = "Aider"; IsActive = $false; State = "○ INACTIVE"; Remaining = "Unconfigured"; RemainingSeconds = 0; NextReset = "-"; UsagePct = "0.0%"; WkUsage = "-"; WeeklyReset = "-"
                    }
                }
            } catch {
                $results += [PSCustomObject]@{
                    Id = $aid; Name = $name; Provider = "Aider"; IsActive = $false; State = "ERROR"; Remaining = "-"; RemainingSeconds = 0; NextReset = "-"; UsagePct = "-"; WkUsage = "-"; WeeklyReset = "-"
                }
            }
        }
    }

    Save-AgentCache $results
    return $results
}

function Show-StatusTable($InputData = $null) {
    $winWidth = 120
    try {
        if ($Host -and $Host.UI -and $Host.UI.RawUI) {
            $winWidth = $Host.UI.RawUI.WindowSize.Width
        }
    } catch {
        $winWidth = 120
    }

    $nowStr = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $nowTime = (Get-Date).ToString("HH:mm:ss")
    $data = if ($InputData) { $InputData } else { Get-AgentData }

    if ($winWidth -ge 115) {
        Write-Host "`n⚡ AI AGENTS 5-HOUR & WEEKLY WINDOW QUOTA STATUS  •  Checked: $nowStr" -ForegroundColor Cyan
        Write-Host ("=" * 110) -ForegroundColor DarkCyan
        $header = "{0,-24} {1,-8} {2,-10} {3,-11} {4,-18} {5,-8} {6,-8} {7}" -f "Agent / Account", "Provider", "5h State", "5h Left", "5h Reset", "5h Use", "Wk Use", "Weekly Reset"
        Write-Host $header -ForegroundColor Yellow
        Write-Host ("-" * 110) -ForegroundColor DarkGray
        foreach ($a in $data) {
            $wkVal = $null
            if ($a.WkUsage -and $a.WkUsage -ne "-" -and $a.WkUsage -match "(\d+(\.\d+)?)") {
                $wkVal = [double]$matches[1]
            }
            $wkDisp = if ($wkVal -ge 100.0) { "⚠️ $($a.WkUsage)" } else { $a.WkUsage }
            $color = if ($wkVal -ge 100.0) { "Red" } elseif ($a.IsActive) { "White" } else { "DarkGray" }
            $line = "{0,-24} {1,-8} {2,-10} {3,-11} {4,-18} {5,-8} {6,-8} {7}" -f $a.Name, $a.Provider, $a.State, $a.Remaining, $a.NextReset, $a.UsagePct, $wkDisp, $a.WeeklyReset
            Write-Host $line -ForegroundColor $color
        }
        Write-Host ("=" * 110 + "`n") -ForegroundColor DarkCyan
    } else {
        Write-Host "`n⚡ AI AGENTS QUOTA STATUS  •  Checked: $nowTime" -ForegroundColor Cyan
        Write-Host ("=" * 80) -ForegroundColor DarkCyan
        $header = "{0,-14} {1,-10} {2,-9} {3,-7} {4,-6} {5,-6} {6}" -f "Agent", "State", "Left", "Reset", "5h%", "Wk%", "Weekly"
        Write-Host $header -ForegroundColor Yellow
        Write-Host ("-" * 80) -ForegroundColor DarkGray
        foreach ($a in $data) {
            $shortName = $a.Name.Replace("Google Antigravity (AGY)", "Antigravity").Replace("OpenAI Codex", "Codex").Replace("Claude (", "").Replace(")", "")
            $shortState = if ($a.IsActive) { "● ACTIVE" } else { "○ INACT" }
            $parts = $a.Remaining -split " "
            $shortLeft = if ($parts.Length -ge 2 -and $a.IsActive) { "$($parts[0]) $($parts[1])" } else { $a.Remaining }
            $shortReset = $a.NextReset.Replace(" (Today)", "")
            $wkReset = $a.WeeklyReset
            if ($wkReset -and $wkReset -ne "-" -and $wkReset.Contains("(")) {
                $p = $wkReset.Split("(")
                $h = $p[0].Trim().Replace(".0h", "h")
                $day = $p[1].Split(" ")[0].Trim(" )")
                $wkReset = "$h ($day)"
            }
            $wkVal = $null
            if ($a.WkUsage -and $a.WkUsage -ne "-" -and $a.WkUsage -match "(\d+(\.\d+)?)") {
                $wkVal = [double]$matches[1]
            }
            $wkDisp = if ($wkVal -ge 100.0) { "⚠️$([int]$wkVal)%" } else { $a.WkUsage }
            $color = if ($wkVal -ge 100.0) { "Red" } elseif ($a.IsActive) { "White" } else { "DarkGray" }
            $line = "{0,-14} {1,-10} {2,-9} {3,-7} {4,-6} {5,-6} {6}" -f $shortName, $shortState, $shortLeft, $shortReset, $a.UsagePct, $wkDisp, $wkReset
            Write-Host $line -ForegroundColor $color
        }
        Write-Host ("=" * 80 + "`n") -ForegroundColor DarkCyan
    }
    return $data
}

if ($Prompt -or -not [string]::IsNullOrEmpty($PromptFormat)) {
    $fmt = if ($PromptFormat) { $PromptFormat } else { "default" }
    $out = Get-AgentPrompt -Format $fmt -ForceRefresh:$Refresh
    Write-Output $out
    exit 0
}

if ($Json) {
    $data = Get-AgentData
    $data | ConvertTo-Json -Depth 5
    exit 0
}

if ($Watch -gt 0 -or $PSBoundParameters.ContainsKey('Watch')) {
    $interval = if ($Watch -gt 0) { $Watch } else { 15 }
    Write-Host "`n⚡ Live Quota Watch Mode enabled (refreshing every ${interval}s). Press Ctrl+C to exit.`n" -ForegroundColor Cyan
    try {
        while ($true) {
            Clear-Host
            Show-StatusTable
            Start-Sleep -Seconds $interval
        }
    } catch {
        Write-Host "`nWatch mode terminated.`n" -ForegroundColor DarkGray
    }
    exit 0
}

if ($Status) {
    Show-StatusTable
}

function Convert-DurationToSeconds($str) {
    if (-not $str -or $str -eq "auto") { return $null }
    if ($str -match '^\d+$') { return [int]$str }
    $h = 0; $m = 0; $s = 0
    if ($str -match '(\d+)\s*h') { $h = [int]$Matches[1] }
    if ($str -match '(\d+)\s*m') { $m = [int]$Matches[1] }
    if ($str -match '(\d+)\s*s') { $s = [int]$Matches[1] }
    $tot = ($h * 3600) + ($m * 60) + $s
    if ($tot -gt 0) { return $tot }
    return $null
}

function Get-TargetTimeInfo($timeStr) {
    $parts = $timeStr.Trim().Split(":")
    if ($parts.Length -lt 2) { throw "Invalid time format '$timeStr'. Expected HH:MM or HH:MM:SS in 24-hour format." }
    $h = [int]$parts[0]
    $m = [int]$parts[1]
    $s = if ($parts.Length -ge 3) { [int]$parts[2] } else { 0 }
    $now = Get-Date
    $target = Get-Date -Hour $h -Minute $m -Second $s -Millisecond 0
    if ($target -le $now) {
        $target = $target.AddDays(1)
    }
    $delta = [int]($target - $now).TotalSeconds
    return [PSCustomObject]@{ Target = $target; DeltaSeconds = $delta }
}

function Start-Countdown($totalSecs, $prefix) {
    $rawWidth = 100
    try {
        if ($Host -and $Host.UI -and $Host.UI.RawUI) {
            $rawWidth = $Host.UI.RawUI.WindowSize.Width
        }
    } catch {}
    if (-not $rawWidth -or $rawWidth -lt 40) { $rawWidth = 100 }
    $maxLen = [math]::Max(40, $rawWidth - 2)

    for ($rem = $totalSecs; $rem -gt 0; $rem--) {
        $h = [math]::Floor($rem / 3600)
        $m = [math]::Floor(($rem % 3600) / 60)
        $s = $rem % 60
        $durParts = @()
        if ($h -gt 0) { $durParts += "${h}h" }
        if ($m -gt 0) { $durParts += "${m}m" }
        if ($s -gt 0 -or $durParts.Count -eq 0) { $durParts += "${s}s" }
        $durStr = $durParts -join " "

        $line = "⏳ $($prefix): $durStr remaining"
        if ($line.Length -gt $maxLen) {
            $line = $line.Substring(0, $maxLen - 3) + "..."
        }
        $padded = $line.PadRight($maxLen)
        Write-Host -NoNewline "`r$padded"
        Start-Sleep -Seconds 1
    }
    Write-Host ""
}

function Send-DesktopNotification {
    param(
        [string]$Title = "⚡ Agent Quota Tracker",
        [string]$Message = "Notification"
    )
    try {
        $safeTitle = $Title.Replace("'", "’")
        $safeMessage = $Message.Replace("'", "’").Replace("`n", " ")
        $script = @"
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
`$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
`$textNodes = `$template.GetElementsByTagName('text')
`$null = `$textNodes.Item(0).AppendChild(`$template.CreateTextNode('$safeTitle'))
`$null = `$textNodes.Item(1).AppendChild(`$template.CreateTextNode('$safeMessage'))
`$toast = [Windows.UI.Notifications.ToastNotification]::new(`$template)
`$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe')
`$notifier.Show(`$toast)
"@
        Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $script -WindowStyle Hidden
        return $true
    } catch {
        return $false
    }
}

function Invoke-PokeAgents($forceMode, $targetAgentId, [switch]$NotifyAlert) {
    $modeStr = if ($forceMode) { " (FORCE mode enabled)" } else { "" }
    Write-Host "`n⚡ [POKE] Checking 5-hour rolling threshold windows$modeStr...`n" -ForegroundColor Yellow
    $data = Get-AgentData
    if ($targetAgentId -and $targetAgentId.Trim() -ne "") {
        $target = $targetAgentId.Trim().ToLower()
        $data = $data | Where-Object { $_.Id -eq $target -or $_.Id -eq "claude-$target" }
        if (-not $data) {
            Write-Host "✖ Unknown agent ID '$targetAgentId'. Options: work, personal, work2, codex, agy`n" -ForegroundColor Red
            return @()
        }
    }

    $pokedList = @()
    foreach ($item in $data) {
        if (-not $item -or -not $item.Name) { continue }

        if ($item.IsActive -and -not $forceMode) {
            Write-Host "  ↷ SKIPPED: $($item.Name.PadRight(25)) Window already ACTIVE ($($item.Remaining) remaining, $($item.UsagePct) used)." -ForegroundColor DarkYellow
            continue
        }

        $wkDbl = $null
        if ($item.WkUsage -and $item.WkUsage -ne "-" -and $item.WkUsage -match "(\d+(\.\d+)?)") {
            $wkDbl = [double]$matches[1]
        }
        if ($wkDbl -ge 100.0 -and -not $forceMode) {
            Write-Host "  ↷ SKIPPED: $($item.Name.PadRight(25)) Weekly quota exhausted ($($item.WkUsage) used). Use -Force to override." -ForegroundColor DarkYellow
            continue
        }

        $actionDesc = if ($item.IsActive -and $forceMode) { "Forcing poke" } else { "Window is inactive" }
        Write-Host "  ⏳ POKING:  $($item.Name.PadRight(25)) $actionDesc. Sending prompt & waiting for reply..." -ForegroundColor Cyan

        $replyText = ""
        $rawOutput = ""
        try {
            if ($item.Id -like "claude-*") {
                $prof = $item.Id.Replace("claude-", "")
                $ccsDir = Join-Path $HOME ".ccs\instances\$prof"
                $hasCcs = (Get-Command ccs -ErrorAction SilentlyContinue) -and (Test-Path $ccsDir)
                if ($hasCcs -and $prof -notin @("", "default", "system")) {
                    $out = $null | ccs $prof -p "Hello, how are you doing?" 2>&1
                } elseif (Get-Command claude -ErrorAction SilentlyContinue) {
                    $out = $null | claude -p "Hello, how are you doing?" 2>&1
                } elseif (Get-Command ccs -ErrorAction SilentlyContinue) {
                    $out = $null | ccs $prof -p "Hello, how are you doing?" 2>&1
                } else {
                    throw "Neither CCS (ccs) nor standard Claude CLI (claude) found in PATH."
                }
                $rawOutput = $out -join "`n"
            } elseif ($item.Id -eq "codex") {
                $out = $null | codex exec "Hello, how are you doing?" --ephemeral --skip-git-repo-check --color never 2>&1
                $rawOutput = $out -join "`n"
            } elseif ($item.Id -eq "agy") {
                $out = & agy -p "Hello, how are you doing?" --disable-slash-commands 2>&1
                $rawOutput = $out -join "`n"
            } elseif ($item.Id -eq "cursor" -or $item.Provider -eq "Cursor") {
                $out = & uv run --no-sync python -c "from agents import poke_cursor; import json; print(json.dumps(poke_cursor()))" 2>&1
                $rawOutput = $out -join "`n"
            } elseif ($item.Id -in @("windsurf", "codeium") -or $item.Provider -eq "Windsurf") {
                $out = & uv run --no-sync python -c "from agents import poke_windsurf; import json; print(json.dumps(poke_windsurf()))" 2>&1
                $rawOutput = $out -join "`n"
            } elseif ($item.Id -in @("copilot", "github-copilot") -or $item.Provider -eq "Copilot") {
                $out = & uv run --no-sync python -c "from agents import poke_copilot; import json; print(json.dumps(poke_copilot()))" 2>&1
                $rawOutput = $out -join "`n"
            } elseif ($item.Id -in @("aider", "openrouter") -or $item.Provider -eq "Aider") {
                $out = & uv run --no-sync python -c "from agents import poke_aider; import json; print(json.dumps(poke_aider()))" 2>&1
                $rawOutput = $out -join "`n"
            }
            $replyText = Extract-ReplySnippet $rawOutput
        } catch {
            Write-Host "  ✖ ERROR:   $($item.Name.PadRight(25)) Execution failed: $_" -ForegroundColor Red
            continue
        }

        # Verify locally: re-query agent status (retry up to 3 times)
        $freshItem = $null
        foreach ($delay in @(1000, 1800, 2200)) {
            Start-Sleep -Milliseconds $delay
            $freshList = Get-AgentData
            $freshItem = $freshList | Where-Object { $_.Id -eq $item.Id }
            if ($freshItem.IsActive) { break }
        }

        if ($freshItem.IsActive) {
            $pokedList += $item.Name
            Write-Host "  ✔ SUCCESS: $($item.Name.PadRight(25)) Verified ACTIVE ($($freshItem.Remaining) remaining, $($freshItem.UsagePct) used)" -ForegroundColor Green
            if ($replyText) {
                Write-Host "             ↳ Reply: `"$replyText`"" -ForegroundColor DarkGray
            }
        } else {
            Write-Host "  ⚠ WARNING: $($item.Name.PadRight(25)) Model replied, but 5h window did not register as active" -ForegroundColor Yellow
            if ($replyText) {
                Write-Host "             ↳ Reply: `"$replyText`"" -ForegroundColor DarkGray
            }
        }
    }

    if ($NotifyAlert -and $pokedList.Count -gt 0) {
        $namesStr = $pokedList -join ", "
        $null = Send-DesktopNotification -Title "⚡ Agent Quota Primed" -Message "Successfully primed: $namesStr"
    }

    $primedStr = if ($pokedList.Count -gt 0) { $pokedList -join ", " } else { "none" }
    Add-ScheduleLog "Poke executed: $($pokedList.Count) primed ($primedStr)"

    Write-Host "`nDone!`n"
    return $pokedList
}

function Get-ScheduleLogPath {
    $dir = Join-Path $HOME ".agent_quota_tracker"
    if (-not (Test-Path $dir)) { $null = New-Item -ItemType Directory -Path $dir -Force }
    return (Join-Path $dir "schedule.log")
}

function Add-ScheduleLog([string]$message) {
    try {
        $logPath = Get-ScheduleLogPath
        $timeStr = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        Add-Content -Path $logPath -Value "[$timeStr] $message" -Encoding UTF8 -ErrorAction SilentlyContinue
    } catch {}
}

function Install-AgentSchedule([string]$timeStr, [switch]$NotifyAlert, [string]$Frequency = "daily") {
    if (-not $timeStr) { $timeStr = "07:30" }
    if ($timeStr -notmatch '^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$') {
        Write-Host "✖ Error: Invalid time format '$timeStr'. Expected HH:MM in 24-hour format (e.g. 07:30)." -ForegroundColor Red
        return
    }
    $parts = $timeStr.Split(":")
    $hour = [int]$parts[0]
    $minute = [int]$parts[1]
    $formattedTime = "{0:D2}:{1:D2}" -f $hour, $minute

    $taskName = "AgentQuotaTrackerMorningPriming"
    $scriptPath = $PSCommandPath
    if (-not $scriptPath) { $scriptPath = "$PSScriptRoot\agents_native.ps1" }
    $workingDir = $PSScriptRoot

    $argList = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -Poke"
    if ($NotifyAlert) {
        $argList += " -Notify"
    }

    $freq = $Frequency.ToLower()
    $schedDesc = "Daily at $formattedTime"
    if ($freq -eq "once") {
        $schedDesc = "Once at $formattedTime"
        $targetDt = (Get-Date).Date.AddHours($hour).AddMinutes($minute)
        if ($targetDt -le (Get-Date)) { $targetDt = $targetDt.AddDays(1) }
        $trigger = New-ScheduledTaskTrigger -Once -At $targetDt
    } elseif ($freq -in @("weekdays", "weekday", "workdays")) {
        $schedDesc = "Weekdays at $formattedTime"
        $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $formattedTime
    } else {
        $trigger = New-ScheduledTaskTrigger -Daily -At $formattedTime
    }

    Write-Host "`n⚡ Registering OS-Level Scheduled Priming Task ($freq) at $formattedTime..." -ForegroundColor Cyan

    try {
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argList -WorkingDirectory $workingDir
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

        Add-ScheduleLog "Scheduled task installed: $schedDesc (Windows Task Scheduler)"

        Write-Host "✔ Successfully registered scheduled priming task!`n" -ForegroundColor Green
        Write-Host "  Task Name:      $taskName" -ForegroundColor White
        Write-Host "  Platform:       Windows Task Scheduler" -ForegroundColor Cyan
        Write-Host "  Schedule:       $schedDesc" -ForegroundColor Cyan
        $alertStr = if ($NotifyAlert) { "Enabled (-Notify)" } else { "Disabled" }
        Write-Host "  Desktop Alerts: $alertStr" -ForegroundColor Cyan
        Write-Host "  Execution:      powershell.exe $argList" -ForegroundColor Cyan
        Write-Host "  Log File:       $(Get-ScheduleLogPath)" -ForegroundColor Cyan
        Write-Host "`nThe system will automatically trigger morning priming even when your terminal is closed.`n" -ForegroundColor DarkGray
    } catch {
        Write-Host "✖ Failed to register scheduled task: $_" -ForegroundColor Red
    }
}

function Get-AgentScheduleStatus {
    $taskName = "AgentQuotaTrackerMorningPriming"
    Write-Host "`n⚡ OS-Level Scheduled Priming Task Status`n" -ForegroundColor Cyan
    Write-Host "  Task Name:      $taskName" -ForegroundColor White
    Write-Host "  Platform:       Windows Task Scheduler" -ForegroundColor Cyan

    $t = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($t) {
        $info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
        Write-Host "  Status:         Installed (Active)" -ForegroundColor Green
        Write-Host "  State:          $($t.State)" -ForegroundColor Cyan
        $nextRun = if ($info -and $info.NextRunTime -and $info.NextRunTime.Year -gt 2000) { $info.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss') } else { 'Pending' }
        Write-Host "  Next Run Time:  $nextRun" -ForegroundColor Cyan
        $lastRun = if ($info -and $info.LastRunTime -and $info.LastRunTime.Year -gt 2000) { $info.LastRunTime.ToString('yyyy-MM-dd HH:mm:ss') } else { 'Never' }
        Write-Host "  Last Run Time:  $lastRun" -ForegroundColor Cyan
        if ($info) {
            $exitCodeStr = if ($info.LastTaskResult -eq 0) { "0 (Success)" } else { "$($info.LastTaskResult)" }
            Write-Host "  Last Exit Code: $exitCodeStr" -ForegroundColor Cyan
        }
    } else {
        Write-Host "  Status:         Not Installed" -ForegroundColor Yellow
    }

    $logFile = Get-ScheduleLogPath
    Write-Host "  Log File:       $logFile" -ForegroundColor Cyan

    if (Test-Path $logFile) {
        $lines = @(Get-Content -Path $logFile -ErrorAction SilentlyContinue | Where-Object { $_.Trim() })
        if ($lines.Count -gt 0) {
            Write-Host "`n  Recent Schedule Logs (last 5 runs):" -ForegroundColor DarkGray
            $start = [math]::Max(0, $lines.Count - 5)
            for ($i = $start; $i -lt $lines.Count; $i++) {
                Write-Host "    $($lines[$i])" -ForegroundColor DarkGray
            }
        }
    }
    Write-Host ""
}

function Uninstall-AgentSchedule {
    $taskName = "AgentQuotaTrackerMorningPriming"
    Write-Host "`n⚡ Removing OS-Level Scheduled Priming Task..." -ForegroundColor Cyan
    try {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
        Add-ScheduleLog "Scheduled task removed (Windows Task Scheduler)"
        Write-Host "✔ Successfully uninstalled scheduled priming task.`n" -ForegroundColor Green
    } catch {
        Write-Host "✖ Failed to remove scheduled task: $_`n" -ForegroundColor Red
    }
}

if ($ScheduleInstall) {
    $f = if ($Once) { "once" } elseif ($Frequency) { $Frequency } else { "daily" }
    Install-AgentSchedule -timeStr $ScheduleInstall -NotifyAlert:$Notify -Frequency $f
    exit 0
}

if ($ScheduleStatus) {
    Get-AgentScheduleStatus
    exit 0
}

if ($ScheduleRemove) {
    Uninstall-AgentSchedule
    exit 0
}

if ($TestNotify) {
    Write-Host "⚡ Sending test desktop notification..." -ForegroundColor Cyan
    $ok = Send-DesktopNotification -Title "⚡ Agent Quota Tracker" -Message "Desktop notifications are working perfectly!"
    if ($ok) {
        Write-Host "✔ Notification dispatched successfully!" -ForegroundColor Green
        try {
            $tVal = (Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\PushNotifications' -ErrorAction SilentlyContinue).ToastEnabled
            if ($null -ne $tVal -and $tVal -eq 0) {
                Write-Host "ℹ Note: Windows Notifications are turned OFF in your Windows Settings (System > Notifications). Enable notifications to see visual toast alerts." -ForegroundColor Yellow
            }
        } catch {}
        Write-Host ""
    } else {
        Write-Host "✖ Notification failed to dispatch.`n" -ForegroundColor Red
    }
    exit 0
}

if ($PokeAt) {
    try {
        $info = Get-TargetTimeInfo $PokeAt
    } catch {
        Write-Host "✖ Error: $_" -ForegroundColor Red
        exit 1
    }
    $targetStr = $info.Target.ToString("yyyy-MM-dd HH:mm:ss")
    $rel = if ($info.Target.Date -eq (Get-Date).Date) { "today" } else { "tomorrow" }
    $notifyStr = if ($Notify) { " • Notifications: ON" } else { "" }
    Write-Host "`n=================================================================================" -ForegroundColor Cyan
    Write-Host "  ⚡ SCHEDULED PEAK-TIME PRIMING MODE" -ForegroundColor Cyan
    Write-Host "  Target Execution: $targetStr ($rel)$notifyStr" -ForegroundColor White
    Write-Host "  Strategic priming ensures 5-hour quota reset aligns with peak workday hours." -ForegroundColor DarkGray
    Write-Host "  Press Ctrl+C to cancel schedule." -ForegroundColor DarkGray
    Write-Host "=================================================================================`n" -ForegroundColor Cyan

    try {
        Start-Countdown $info.DeltaSeconds "Priming scheduled for $($info.Target.ToString('HH:mm:ss')) ($rel)"
    } catch {
        Write-Host "`n`n⚡ Scheduled poke cancelled by user.`n" -ForegroundColor Yellow
        exit 0
    }

    Write-Host "`n⚡ Target time reached ($targetStr)! Initiating scheduled poke...`n" -ForegroundColor Green
    $poked = Invoke-PokeAgents $Force $TargetAgent -NotifyAlert:$Notify
    Show-StatusTable

    if ($Notify) {
        $null = Send-DesktopNotification -Title "🎯 Morning Priming Complete" -Message "Priming complete! Agent windows ready for peak workday coding."
    }

    if ($PokeWatch) {
        Write-Host "Transitioning into automated watchdog mode...`n" -ForegroundColor Cyan
    } else {
        exit 0
    }
}

if ($Auto -or $AutoPoke) {
    $notifyStr = if ($Notify) { " • Notifications: ON" } else { "" }
    $forceStr = if ($Force) { " • Force: ON" } else { "" }
    Write-Host "`n=================================================================================" -ForegroundColor Cyan
    Write-Host "  ⚡ AUTONOMOUS QUOTA AUTO-CHECKER STARTED" -ForegroundColor Cyan
    Write-Host "  Continuous monitoring loop: checks status, waits for earliest window reset, primes, and repeats." -ForegroundColor White
    Write-Host "  Mode: Adaptive Quota Priming$notifyStr$forceStr • Press Ctrl+C to terminate." -ForegroundColor DarkGray
    Write-Host "=================================================================================`n" -ForegroundColor Cyan

    $cycle = 1
    try {
        while ($true) {
            $nowStr = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
            Write-Host "▶ Auto-Checker Cycle #$cycle • $nowStr" -ForegroundColor Magenta

            # Step 1: Fetch and display status table
            $currentData = Get-AgentData
            Show-StatusTable $currentData

            # Filter if target agent specified
            if ($TargetAgent) {
                $targetLower = $TargetAgent.ToLower()
                $currentData = $currentData | Where-Object { $_.Id -eq $targetLower -or $_.Id -eq "claude-$targetLower" }
            }

            # Step 2: Check for idle & ready accounts
            $idleReady = @()
            foreach ($item in $currentData) {
                $wkDbl = $null
                if ($item.WkUsage -and $item.WkUsage -ne "-" -and $item.WkUsage -match "(\d+(\.\d+)?)") {
                    $wkDbl = [double]$matches[1]
                }
                $isExhausted = ($wkDbl -ne $null -and $wkDbl -ge 100.0)
                if (-not $item.IsActive -and ($Force -or -not $isExhausted)) {
                    $idleReady += $item
                }
            }

            if ($idleReady.Count -gt 0) {
                $readyNames = ($idleReady | ForEach-Object { $_.Name }) -join ", "
                Write-Host "⚡ Found $($idleReady.Count) idle account(s) ready to prime ($readyNames). Poking now...`n" -ForegroundColor Yellow
                Invoke-PokeAgents $Force $TargetAgent -NotifyAlert:$Notify
                $currentData = Get-AgentData
                Show-StatusTable $currentData
                if ($TargetAgent) {
                    $targetLower = $TargetAgent.ToLower()
                    $currentData = $currentData | Where-Object { $_.Id -eq $targetLower -or $_.Id -eq "claude-$targetLower" }
                }
            } else {
                Write-Host "✔ All monitored accounts are currently active. Monitoring rolling 5h reset windows..." -ForegroundColor Green
            }

            # Step 3: Compute earliest next window expiration
            $sleepSecs = 120
            $reason = "all agents idle or freshly checked"
            $activeWithRem = @()
            foreach ($item in $currentData) {
                $wkDbl = $null
                if ($item.WkUsage -and $item.WkUsage -ne "-" -and $item.WkUsage -match "(\d+(\.\d+)?)") {
                    $wkDbl = [double]$matches[1]
                }
                $isExhausted = ($wkDbl -ne $null -and $wkDbl -ge 100.0)
                if ($item.IsActive -and $item.RemainingSeconds -gt 0 -and ($Force -or -not $isExhausted)) {
                    $activeWithRem += $item
                }
            }

            if ($activeWithRem.Count -gt 0) {
                $earliest = ($activeWithRem | Sort-Object RemainingSeconds)[0]
                $sleepSecs = [math]::Max(60, $earliest.RemainingSeconds + 45)
                $reason = "$($earliest.Name) ($($earliest.Remaining) left)"
            }

            $wakeTime = (Get-Date).AddSeconds($sleepSecs).ToString("HH:mm:ss")
            Write-Host "⏳ Next poke target: $wakeTime ($reason)" -ForegroundColor Cyan
            Write-Host "Ticking countdown started. Press Ctrl+C to stop.`n" -ForegroundColor DarkGray

            # Step 4: Countdown & Poke
            Start-Countdown $sleepSecs "Next poke at $wakeTime • $reason"
            Write-Host "`n⚡ Timer reached ($wakeTime)! Priming newly available quota window(s)...`n" -ForegroundColor Green
            Invoke-PokeAgents $Force $TargetAgent -NotifyAlert:$Notify
            $cycle++
        }
    } catch {
        Write-Host "`n⚡ Auto-checker loop stopped by user.`n" -ForegroundColor Yellow
        exit 0
    }
}

if ($PokeWatch) {
    $fixedSecs = Convert-DurationToSeconds $Interval
    $modeStr = if ($fixedSecs) { "fixed ${fixedSecs}s interval" } else { "adaptive window expiry mode" }
    $notifyStr = if ($Notify) { " • Notifications: ON" } else { "" }
    Write-Host "`n=================================================================================" -ForegroundColor Cyan
    Write-Host "  ⚡ AUTONOMOUS POKE WATCHDOG STARTED" -ForegroundColor Cyan
    Write-Host "  Running in $modeStr$notifyStr. Automatically primes 5h quota windows as accounts cool down." -ForegroundColor White
    Write-Host "  Press Ctrl+C to terminate." -ForegroundColor DarkGray
    Write-Host "=================================================================================`n" -ForegroundColor Cyan

    $cycle = 1
    try {
        while ($true) {
            $nowStr = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
            Write-Host "▶ Watchdog Cycle #$cycle • $nowStr" -ForegroundColor Magenta
            Invoke-PokeAgents $Force $TargetAgent -NotifyAlert:$Notify

            $sleepSecs = 120
            $reason = "adaptive check"
            if ($fixedSecs) {
                $sleepSecs = $fixedSecs
                $reason = "fixed ${fixedSecs}s"
            } else {
                $latestData = Get-AgentData
                $activeWithRem = @()
                foreach ($item in $latestData) {
                    $wkDbl = $null
                    if ($item.WkUsage -and $item.WkUsage -ne "-" -and $item.WkUsage -match "(\d+(\.\d+)?)") {
                        $wkDbl = [double]$matches[1]
                    }
                    $isExhausted = ($wkDbl -ne $null -and $wkDbl -ge 100.0)
                    if ($item.IsActive -and $item.RemainingSeconds -gt 0 -and ($Force -or -not $isExhausted)) {
                        $activeWithRem += $item
                    }
                }
                if ($activeWithRem.Count -gt 0) {
                    $earliest = ($activeWithRem | Sort-Object RemainingSeconds)[0]
                    $sleepSecs = [math]::Max(60, $earliest.RemainingSeconds + 45)
                    $reason = "$($earliest.Name) ($($earliest.Remaining) left)"
                } else {
                    $sleepSecs = 120
                    $reason = "all agents idle or freshly checked"
                }
            }

            $wakeTime = (Get-Date).AddSeconds($sleepSecs).ToString("HH:mm:ss")
            Write-Host "Next check at $wakeTime ($reason)" -ForegroundColor Cyan
            Start-Countdown $sleepSecs "Next check at $wakeTime"
            $cycle++
        }
    } catch {
        Write-Host "`n`n⚡ Poke watchdog mode stopped.`n" -ForegroundColor Yellow
        exit 0
    }
}

if ($Poke) {
    Invoke-PokeAgents $Force $TargetAgent -NotifyAlert:$Notify
}

if ($Analytics) {
    & uv run python "$PSScriptRoot\agents.py" --analytics --days $Days
    exit 0
}

if ($Backfill) {
    & uv run python "$PSScriptRoot\agents.py" --backfill
    exit 0
}

if ($Dashboard) {
    Write-Host "`n🚀 Launching Dashboard..." -ForegroundColor Cyan
    & uv run python "$PSScriptRoot\agents.py" --dashboard
}
