<#
.SYNOPSIS
    One-time setup: registers Simurg as a Windows Task Scheduler task that runs
    24/7 - starts at boot, keeps itself alive if it ever crashes, and runs even
    when nobody is logged in.

.DESCRIPTION
    Must be run from an ELEVATED PowerShell window (Run as Administrator), because
    "run whether user is logged on or not" requires your Windows account password,
    which this script prompts for interactively (never stored in this repo or
    passed on the command line).

    Safe to re-run: it replaces any existing task of the same name.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install_scheduled_task.ps1
#>

$ErrorActionPreference = "Stop"

$TaskName = "SimurgOpportunitiesBot"
$RepoRoot = $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

# --- Pre-flight checks ---
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "This script must be run from an elevated (Run as Administrator) PowerShell window."
    exit 1
}

if (-not (Test-Path $Python)) {
    Write-Error "Virtual environment not found at $Python`nRun start_simurg.bat once first to create it and install dependencies, then re-run this script."
    exit 1
}

# --- Credentials (entered here, never written to disk or passed as a CLI arg) ---
$cred = Get-Credential -UserName "$env:USERDOMAIN\$env:USERNAME" `
    -Message "Enter your Windows account password so Simurg can run even when you're logged out"
$plainPassword = $cred.GetNetworkCredential().Password

# --- Action: run the bot with no visible console window ---
# pythonw.exe (the windowless Python launcher) looks like the obvious choice here,
# but Task Scheduler cannot reliably track when a windowless/GUI-subsystem process
# exits - it reports the task as "completed successfully" almost instantly and then
# never relaunches it, even after a real crash. Instead, run the normal console
# python.exe wrapped in a hidden PowerShell window: Task Scheduler tracks the
# powershell.exe process (a real console-subsystem process, tracked reliably), and
# -WindowStyle Hidden keeps it invisible even if you're logged on when it runs.
$innerCommand = "& '$Python' -m src.main"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -Command `"$innerCommand`"" `
    -WorkingDirectory $RepoRoot

# --- Triggers ---
# 1) Fire once at boot (short delay so networking is up).
$triggerAtStartup = New-ScheduledTaskTrigger -AtStartup
$triggerAtStartup.Delay = "PT1M"

# 2) Keep-alive: re-fire every 5 minutes forever. Combined with the
#    "IgnoreNew" multiple-instances policy below, this is a no-op while the bot
#    is already running and only actually relaunches it after a crash - an
#    unlimited, uncapped self-healing loop.
# Task Scheduler's duration field can't hold [TimeSpan]::MaxValue (errors as
# "out of range") - 10 years is effectively indefinite for this purpose.
$triggerKeepAlive = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

# --- Settings ---
# ExecutionTimeLimit must be zero - Task Scheduler's default 3-day limit would
# otherwise silently kill a long-running task.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

# --- Replace any existing task of the same name (idempotent) ---
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Existing '$TaskName' task found - replacing it."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName `
    -Action $action `
    -Trigger @($triggerAtStartup, $triggerKeepAlive) `
    -Settings $settings `
    -User $cred.UserName `
    -Password $plainPassword `
    -RunLevel Limited `
    -Description "Simurg Opportunities Telegram bot - runs 24/7, restarts itself if it crashes." `
    | Out-Null

$plainPassword = $null

Write-Host ""
Write-Host "Task '$TaskName' registered." -ForegroundColor Green
Write-Host "Starting it now..."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 3
Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo | Format-List TaskName, LastRunTime, LastTaskResult, NextRunTime

Write-Host ""
Write-Host "Logs: $RepoRoot\logs\simurg.log"
Write-Host "Check status any time with:  schtasks /query /tn `"$TaskName`" /v /fo list"
Write-Host "Stop it with:                Stop-ScheduledTask -TaskName `"$TaskName`""
Write-Host "Disable it with:             Disable-ScheduledTask -TaskName `"$TaskName`""
