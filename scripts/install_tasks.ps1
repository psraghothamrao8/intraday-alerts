# Windows Task Scheduler installation script (spec 07 §4.5)
# Installs:
#   1. IntradayAlertBot_Run: Mon-Fri at 08:40 (wakes computer to run live engine)
#   2. IntradayAlertBot_CollectEOD: Mon-Fri at 18:30 (collects EOD 1m candles & S4 data)

$ErrorActionPreference = "Stop"

$RepoDir = (Get-Item $PSScriptRoot).Parent.FullName
$PythonExe = (Get-Command python).Source

Write-Host "Installing Windows Scheduled Tasks..." -ForegroundColor Cyan
Write-Host "Repo Directory: $RepoDir"
Write-Host "Python Executable: $PythonExe"

# 1. 08:40 Run Task
$RunTaskName = "IntradayAlertBot_Run"
$RunTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At 08:40AM
$RunAction = New-ScheduledTaskAction -Execute $PythonExe -Argument "-m engine run" -WorkingDirectory $RepoDir
$RunSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun -StartWhenAvailable

Register-ScheduledTask -TaskName $RunTaskName -Action $RunAction -Trigger $RunTrigger -Settings $RunSettings -Description "Runs Intraday Alert Bot daily at 08:40" -Force
Write-Host "[SUCCESS] Registered task: $RunTaskName (08:40 Mon-Fri, WakeToRun)" -ForegroundColor Green

# 2. 18:30 Collect EOD Task
$EodTaskName = "IntradayAlertBot_CollectEOD"
$EodTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At 06:30PM
$EodAction = New-ScheduledTaskAction -Execute $PythonExe -Argument "-m engine collect-eod" -WorkingDirectory $RepoDir
$EodSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $EodTaskName -Action $EodAction -Trigger $EodTrigger -Settings $EodSettings -Description "Collects EOD candles daily at 18:30" -Force
Write-Host "[SUCCESS] Registered task: $EodTaskName (18:30 Mon-Fri)" -ForegroundColor Green
