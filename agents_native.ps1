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

    [Alias("f")]
    [switch]$Force,

    [Alias("a", "agent")]
    [string]$TargetAgent,

    [Alias("d")]
    [switch]$Dashboard,

    [Alias("h", "?")]
    [switch]$Help
)

if ($Help) {
    Write-Host @"

⚡ AI Agents 5-Hour Window Tracker & Dashboard (PowerShell Native)

Monitor rolling rate limit windows, track weekly resets, and poke AI accounts non-interactively.

USAGE:
  .\agents_native.ps1 [-Status] [-Poke] [-Force] [-TargetAgent <id>] [-Dashboard] [-Help]

OPTIONS:
  -Status, -s            Display live 5-hour rolling threshold window state, time remaining,
                         next reset time, 5h % usage, and weekly quota reset date.
  -Json, -j              Output raw machine-readable JSON status for all accounts.
  -Watch, -w [seconds]   Continuously refresh the status table every N seconds (default: 15s).
  -Poke, -p              Trigger a prompt on inactive accounts to start the 5h window.
                         Active accounts are automatically skipped to conserve quota.
  -Force, -f             When used with -Poke, forces a prompt even if window is already active.
  -TargetAgent, -a <id>  Target a specific agent (e.g. work, personal, work2, codex, agy).
  -Dashboard, -d         Launch the local web dashboard at http://localhost:5050.
  -Help, -h, -?          Show this help message and exit.

EXAMPLES:
  .\agents_native.ps1 -Status
  .\agents_native.ps1 -Poke
  .\agents_native.ps1 -Poke -Force -TargetAgent work
  .\agents_native.ps1 -Dashboard

"@ -ForegroundColor Cyan
    exit 0
}

# Default to Status if no action switch passed
if (-not $Status -and -not $Poke -and -not $Dashboard -and -not $Json -and $Watch -eq 0 -and -not $PSBoundParameters.ContainsKey('Watch')) {
    $Status = $true
}

$nowUtc = [DateTime]::UtcNow

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
                            if ($span5h.TotalSeconds -gt 0) {
                                $isActiveAgy = $true
                                $remStrAgy = Format-Remaining $span5h
                                $resetLocalAgy = $rUtc5h.ToLocalTime().ToString("HH:mm:ss") + " (Today)"
                                $usedAgy = [Math]::Round((1.0 - [double]$b5h.remaining_fraction) * 100, 1)
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
                Id          = "agy"
                Name        = $name
                Provider    = "AGY"
                IsActive    = $isActiveAgy
                State       = if ($isActiveAgy) { "● ACTIVE" } else { "○ INACTIVE" }
                Remaining   = $remStrAgy
                NextReset   = $resetLocalAgy
                UsagePct    = "$usedAgy%"
                WkUsage     = $wkUsedAgy
                WeeklyReset = $wkResetAgy
            }
        }
        elseif ($prov -eq "codex") {
            try {
                $rawCodexJson = & uv run python -c "from agents import get_codex_status; import json; print(json.dumps(get_codex_status().to_dict()))" 2>$null
                $cObj = $rawCodexJson | ConvertFrom-Json
                $isActiveCodex = [bool]$cObj.is_active
                $usedCodex = [double]$cObj.used_percent
                $remStrCodex = if ($cObj.time_remaining_str) { $cObj.time_remaining_str } else { "Inactive" }
                $resetLocalCodex = "Ready to Poke"
                if ($cObj.resets_at) {
                    $rUtc = [DateTime]::Parse($cObj.resets_at).ToUniversalTime()
                    $resetLocalCodex = $rUtc.ToLocalTime().ToString("HH:mm:ss") + " (Today)"
                }
                $wkUsedCodex = if ($null -ne $cObj.weekly_used_percent) { "$($cObj.weekly_used_percent)%" } else { "-" }
                $wkResetCodex = if ($cObj.weekly_reset_str) { $cObj.weekly_reset_str } else { "-" }

                $results += [PSCustomObject]@{
                    Id          = "codex"
                    Name        = $name
                    Provider    = "Codex"
                    IsActive    = $isActiveCodex
                    State       = if ($isActiveCodex) { "● ACTIVE" } else { "○ INACTIVE" }
                    Remaining   = $remStrCodex
                    NextReset   = $resetLocalCodex
                    UsagePct    = "$([Math]::Round($usedCodex, 1))%"
                    WkUsage     = $wkUsedCodex
                    WeeklyReset = $wkResetCodex
                }
            } catch {
                $results += [PSCustomObject]@{
                    Id = "codex"; Name = $name; Provider = "Codex"; IsActive = $false; State = "○ INACTIVE"; Remaining = "Inactive"; NextReset = "Ready to Poke"; UsagePct = "0.0%"; WkUsage = "-"; WeeklyReset = "-"
                }
            }
        }
        elseif ($prov -eq "claude") {
            $prof = if ($acc.profile) { $acc.profile } else { $aid }
            $jsonPath = Join-Path $HOME ".ccs\instances\$prof\.claude.json"
            $credsPath = Join-Path $HOME ".ccs\instances\$prof\.credentials.json"
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

                    if ($resetsStr) {
                        $resetsUtc = [DateTime]::Parse($resetsStr).ToUniversalTime()
                        if ($resetsUtc -gt $nowUtc) {
                            $isActive = $true
                            $remSpan = $resetsUtc - $nowUtc
                            $remainingStr = Format-Remaining $remSpan
                            $resetLocal = $resetsUtc.ToLocalTime().ToString("HH:mm:ss") + " (Today)"
                        } else {
                            $used = 0.0
                        }
                    }

                    $wkUsed = if ($null -ne $sevenDay.utilization) { "$([Math]::Round([double]$sevenDay.utilization, 1))%" } else { "-" }
                    $wkReset = Format-WeeklyReset $sevenDay.resets_at

                    $results += [PSCustomObject]@{
                        Id          = "claude-$prof"
                        Name        = $name
                        Provider    = "Claude"
                        IsActive    = $isActive
                        State       = if ($isActive) { "● ACTIVE" } else { "○ INACTIVE" }
                        Remaining   = $remainingStr
                        NextReset   = $resetLocal
                        UsagePct    = "$([Math]::Round($used, 1))%"
                        WkUsage     = $wkUsed
                        WeeklyReset = $wkReset
                    }
                } else {
                    $results += [PSCustomObject]@{
                        Id = "claude-$prof"; Name = $name; Provider = "Claude"; IsActive = $false; State = "○ INACTIVE"; Remaining = "Inactive"; NextReset = "Ready to Poke"; UsagePct = "0.0%"; WkUsage = "-"; WeeklyReset = "-"
                    }
                }
            } catch {
                $results += [PSCustomObject]@{
                    Id = "claude-$prof"; Name = $name; Provider = "Claude"; IsActive = $false; State = "ERROR"; Remaining = "-"; NextReset = "-"; UsagePct = "-"; WkUsage = "-"; WeeklyReset = "-"
                }
            }
        }
    }

    return $results
}

function Show-StatusTable {
    $winWidth = 120
    try {
        if ($Host -and $Host.UI -and $Host.UI.RawUI) {
            $winWidth = $Host.UI.RawUI.WindowSize.Width
        }
    } catch {
        $winWidth = 120
    }

    if ($winWidth -ge 115) {
        Write-Host "`n⚡ AI AGENTS 5-HOUR & WEEKLY WINDOW QUOTA STATUS" -ForegroundColor Cyan
        Write-Host ("=" * 110) -ForegroundColor DarkCyan
        $header = "{0,-24} {1,-8} {2,-10} {3,-11} {4,-18} {5,-8} {6,-8} {7}" -f "Agent / Account", "Provider", "5h State", "5h Left", "5h Reset", "5h Use", "Wk Use", "Weekly Reset"
        Write-Host $header -ForegroundColor Yellow
        Write-Host ("-" * 110) -ForegroundColor DarkGray
        $data = Get-AgentData
        foreach ($a in $data) {
            $color = if ($a.IsActive) { "White" } else { "DarkGray" }
            $line = "{0,-24} {1,-8} {2,-10} {3,-11} {4,-18} {5,-8} {6,-8} {7}" -f $a.Name, $a.Provider, $a.State, $a.Remaining, $a.NextReset, $a.UsagePct, $a.WkUsage, $a.WeeklyReset
            Write-Host $line -ForegroundColor $color
        }
        Write-Host ("=" * 110 + "`n") -ForegroundColor DarkCyan
    } else {
        Write-Host "`n⚡ AI AGENTS QUOTA STATUS" -ForegroundColor Cyan
        Write-Host ("=" * 80) -ForegroundColor DarkCyan
        $header = "{0,-14} {1,-10} {2,-9} {3,-7} {4,-6} {5,-6} {6}" -f "Agent", "State", "Left", "Reset", "5h%", "Wk%", "Weekly"
        Write-Host $header -ForegroundColor Yellow
        Write-Host ("-" * 80) -ForegroundColor DarkGray
        $data = Get-AgentData
        foreach ($a in $data) {
            $color = if ($a.IsActive) { "White" } else { "DarkGray" }
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
            $line = "{0,-14} {1,-10} {2,-9} {3,-7} {4,-6} {5,-6} {6}" -f $shortName, $shortState, $shortLeft, $shortReset, $a.UsagePct, $a.WkUsage, $wkReset
            Write-Host $line -ForegroundColor $color
        }
        Write-Host ("=" * 80 + "`n") -ForegroundColor DarkCyan
    }
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

if ($Poke) {
    $modeStr = if ($Force) { " (FORCE mode enabled)" } else { "" }
    Write-Host "`n⚡ [POKE] Checking 5-hour rolling threshold windows$modeStr...`n" -ForegroundColor Yellow
    $data = Get-AgentData
    if ($TargetAgent -and $TargetAgent.Trim() -ne "") {
        $target = $TargetAgent.Trim().ToLower()
        $data = $data | Where-Object { $_.Id -eq $target -or $_.Id -eq "claude-$target" }
        if (-not $data) {
            Write-Host "✖ Unknown agent ID '$TargetAgent'. Options: work, personal, work2, codex, agy`n" -ForegroundColor Red
            return
        }
    }

    foreach ($item in $data) {
        if (-not $item -or -not $item.Name) { continue }

        if ($item.IsActive -and -not $Force) {
            Write-Host "  ↷ SKIPPED: $($item.Name.PadRight(25)) Window already ACTIVE ($($item.Remaining) remaining, $($item.UsagePct) used)." -ForegroundColor DarkYellow
            continue
        }

        $actionDesc = if ($item.IsActive -and $Force) { "Forcing poke" } else { "Window is inactive" }
        Write-Host "  ⏳ POKING:  $($item.Name.PadRight(25)) $actionDesc. Sending prompt & waiting for reply..." -ForegroundColor Cyan

        $replyText = ""
        $rawOutput = ""
        try {
            if ($item.Id -like "claude-*") {
                $prof = $item.Id.Replace("claude-", "")
                $out = $null | ccs $prof -p "Hello, how are you doing?" 2>&1
                $rawOutput = $out -join "`n"
            } elseif ($item.Id -eq "codex") {
                $out = $null | codex exec "Hello, how are you doing?" --ephemeral --skip-git-repo-check --color never 2>&1
                $rawOutput = $out -join "`n"
            } elseif ($item.Id -eq "agy") {
                $out = & agy -p "Hello, how are you doing?" --disable-slash-commands 2>&1
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
    Write-Host "`nDone!`n"
}

if ($Dashboard) {
    Write-Host "`n🚀 Launching Dashboard..." -ForegroundColor Cyan
    & uv run python "$PSScriptRoot\agents.py" --dashboard
}
