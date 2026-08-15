# Register nightly bank top-up with the Windows Task Scheduler.
#
# The scheduler is used rather than a background task inside the bot on
# purpose: a task living in the bot process dies whenever the bot does, and
# the whole point is that the bank keeps filling without anyone watching. It
# also survives a reboot, which a bot started by hand does not.
#
# ASCII only, deliberately: Windows PowerShell 5.1 reads a script without a
# BOM as ANSI, and a stray dash or quote breaks parsing in ways that look
# nothing like the real cause.
#
#   .\scripts\schedule_topup.ps1              # register, runs 04:00 daily
#   .\scripts\schedule_topup.ps1 -At 02:30    # a different time
#   .\scripts\schedule_topup.ps1 -Remove      # unregister

param(
    [string]$At = "04:00",
    [switch]$Remove
)

$TaskName = "IELTS bot - top up exercise bank"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Script = Join-Path $Root "scripts\top_up_bank.py"
$Log = Join-Path $Root "data\topup.log"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    "Unregistered '$TaskName'."
    return
}

if (-not (Test-Path $Python)) { throw "No interpreter at $Python. Create the venv first." }
if (-not (Test-Path $Script)) { throw "No script at $Script." }

# Output goes to a log rather than nowhere: a job whose failures are invisible
# is worse than no job, because the bank quietly stops growing.
$Inner = "'$Python' '$Script' *>> '$Log'"
$Argument = "-NoProfile -ExecutionPolicy Bypass -Command `"& $Inner`""
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $Argument -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At $At

# Start late if the machine was off, never run two at once, give up after two
# hours so a hung request cannot block tomorrow's run.
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2) -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Generates IELTS exercises until each section reaches its target." -Force | Out-Null

"Registered '$TaskName'. Runs daily at $At."
"Log: $Log"
"Run now:       Start-ScheduledTask -TaskName '$TaskName'"
"Last result:   Get-ScheduledTaskInfo -TaskName '$TaskName'"
